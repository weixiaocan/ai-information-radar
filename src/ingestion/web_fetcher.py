from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from goose3 import Goose

from src.models.content_item import ContentItem
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


class WebFetcher:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.goose = Goose()

    def fetch(self, sources: list[dict[str, Any]], seen_ids: set[str], recent_days: int) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = utc_days_ago(recent_days)
        for source in sources:
            if not source.get("enabled", True):
                continue
            try:
                entries = self._discover_entries(source)
            except Exception as exc:
                LOGGER.warning("Failed to discover web source %s: %s", source.get("name"), exc)
                continue
            for entry in entries:
                content_id = f"web_{entry['url']}"
                if content_id in seen_ids:
                    continue
                item = self._to_content_item(source, entry, content_id)
                if item.published_at < cutoff:
                    continue
                results.append(item)
        LOGGER.info("Fetched %s new web articles", len(results))
        return results

    def _discover_entries(self, source: dict[str, Any]) -> list[dict[str, str]]:
        response = requests.get(source["index_url"], timeout=self.timeout_seconds)
        response.raise_for_status()
        html = response.text
        article_base_url = str(source.get("article_base_url", "")).strip()
        pattern = re.escape(article_base_url) + r"[^\"'#<>\s]+"
        urls = list(dict.fromkeys(re.findall(pattern, html)))
        entries: list[dict[str, str]] = []
        for url in urls[:20]:
            title = self._extract_anchor_title(html, url)
            entries.append({"url": urljoin(source["index_url"], url), "title": title})
        return entries

    def _extract_anchor_title(self, html: str, url: str) -> str:
        anchor_pattern = re.compile(
            rf"<a[^>]+href=[\"']{re.escape(url)}[\"'][^>]*>(?P<title>.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        match = anchor_pattern.search(html)
        if not match:
            return ""
        title = re.sub(r"<[^>]+>", " ", match.group("title"))
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def _to_content_item(self, source: dict[str, Any], entry: dict[str, str], content_id: str) -> ContentItem:
        response = requests.get(entry["url"], timeout=self.timeout_seconds)
        response.raise_for_status()
        article = self.goose.extract(raw_html=response.text)
        title = article.title or entry.get("title") or "Untitled article"
        body = article.cleaned_text or ""
        published_at = self._extract_publish_datetime(response.text, article.publish_date)
        return ContentItem(
            content_id=content_id,
            source_type="web",
            source_name=source["name"],
            title=title,
            url=entry["url"],
            author=article.authors[0] if article.authors else None,
            published_at=published_at,
            fetched_at=utc_now(),
            body=body,
            body_type="article",
            extra_metadata={"display_name": source.get("display_name", source["name"])},
        )

    def _extract_publish_datetime(self, html: str, fallback: datetime | None) -> datetime:
        if fallback:
            return fallback if fallback.tzinfo else fallback.replace(tzinfo=timezone.utc)
        patterns = [
            r'"datePublished"\s*:\s*"([^"]+)"',
            r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
            r'<time[^>]+datetime="([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                continue
        return utc_now()
