from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import requests
from goose3 import Goose

from src.models.content_item import ContentItem
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


class RSSFetcher:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.goose = Goose()

    def fetch(self, sources: list[dict], seen_ids: set[str], recent_days: int) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = utc_days_ago(recent_days)
        for source in sources:
            if not source.get("enabled", True):
                continue
            parsed = feedparser.parse(source["url"])
            for entry in parsed.entries:
                native_id = entry.get("id") or entry.get("link") or entry.get("title")
                content_id = f"rss_{native_id}"
                if content_id in seen_ids:
                    continue
                item = self._to_content_item(source, entry, content_id)
                if item.published_at < cutoff:
                    continue
                results.append(item)
        LOGGER.info("Fetched %s new RSS items", len(results))
        return results

    def _to_content_item(self, source: dict, entry: dict, content_id: str) -> ContentItem:
        url = entry.get("link", "")
        body = self._extract_article(url) if url else ""
        if not body:
            summary_blocks = entry.get("summary", "")
            body = summary_blocks if isinstance(summary_blocks, str) else str(summary_blocks)
        return ContentItem(
            content_id=content_id,
            source_type="rss",
            source_name=source["name"],
            title=entry.get("title", "Untitled RSS item"),
            url=url,
            author=entry.get("author"),
            published_at=_parse_struct_time(entry),
            fetched_at=utc_now(),
            body=body,
            body_type="article",
            extra_metadata={"display_name": source.get("display_name", source["name"])},
        )

    def _extract_article(self, url: str) -> str:
        try:
            response = requests.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            article = self.goose.extract(raw_html=response.text)
            return article.cleaned_text or ""
        except Exception as exc:
            LOGGER.warning("Failed to extract RSS article body from %s: %s", url, exc)
            return ""


def _parse_struct_time(entry: dict) -> datetime:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        return datetime(*published[:6], tzinfo=timezone.utc)
    return utc_now()
