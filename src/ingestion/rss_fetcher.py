from __future__ import annotations

import logging
import html
import re
from datetime import datetime, timezone

import feedparser
import requests
from goose3 import Goose

from src.models.content_item import ContentItem
from src.utils.http_retry import run_with_retries
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


class RSSFetcher:
    USER_AGENT = "AI-Radar-RSS/1.0 (+local personal feed reader)"
    FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.1"
    ARTICLE_ACCEPT = "text/html, application/xhtml+xml;q=0.9, */*;q=0.1"

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.goose = Goose()
        self.retry_attempts = 3
        self.retry_delays_seconds = (10, 30)
        self.feed_body_min_chars = 200
        self.source_statuses: dict[str, dict] = {}

    def fetch(
        self,
        sources: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = start_at or utc_days_ago(recent_days)
        window_end = end_at or utc_now()
        for source in sources:
            if not source.get("enabled", True):
                continue
            try:
                parsed = self._fetch_feed(source)
            except Exception as exc:
                LOGGER.warning("Failed to fetch RSS source %s: %s", source.get("name"), exc)
                self.source_statuses[f"rss:{source.get('name', source.get('url', 'unknown'))}"] = {
                    "status": "feed_failed",
                    "items_fetched": 0,
                    "article_fallbacks": 0,
                    "error": str(exc),
                }
                continue
            source_items = 0
            article_fallbacks = 0
            for entry in parsed.entries:
                native_id = entry.get("id") or entry.get("link") or entry.get("title")
                content_id = f"rss_{native_id}"
                if content_id in seen_ids:
                    continue
                published_at = _parse_struct_time(entry)
                if published_at < cutoff or published_at >= window_end:
                    continue
                item = self._to_content_item(source, entry, content_id, published_at=published_at)
                results.append(item)
                source_items += 1
                if item.extra_metadata.get("rss_body_source") == "feed_fallback":
                    article_fallbacks += 1
            self.source_statuses[f"rss:{source.get('name', source.get('url', 'unknown'))}"] = {
                "status": "success" if not article_fallbacks else "success_with_article_fallbacks",
                "items_fetched": source_items,
                "article_fallbacks": article_fallbacks,
                "error": "",
            }
        LOGGER.info("Fetched %s new RSS items", len(results))
        return results

    def _fetch_feed(self, source: dict) -> feedparser.FeedParserDict:
        response = run_with_retries(
            lambda: self._request(source["url"], feed=True),
            description=f"RSS feed fetch {source.get('name', source['url'])}",
            max_attempts=self.retry_attempts,
            retry_delays_seconds=self.retry_delays_seconds,
            logger=LOGGER,
        )
        return feedparser.parse(response.text)

    def _to_content_item(
        self,
        source: dict,
        entry: dict,
        content_id: str,
        *,
        published_at: datetime | None = None,
    ) -> ContentItem:
        url = entry.get("link", "")
        feed_body = self._entry_feed_body(entry)
        body_source = "feed"
        if len(feed_body) >= self.feed_body_min_chars:
            body = feed_body
        else:
            body = self._extract_article(url) if url else ""
            if body:
                body_source = "article"
            else:
                body = feed_body
                body_source = "feed_fallback"
        return ContentItem(
            content_id=content_id,
            source_type="rss",
            source_name=source["name"],
            title=entry.get("title", "Untitled RSS item"),
            url=url,
            author=entry.get("author"),
            published_at=published_at or _parse_struct_time(entry),
            fetched_at=utc_now(),
            body=body,
            body_type="article",
            extra_metadata={
                "display_name": source.get("display_name", source["name"]),
                "rss_body_source": body_source,
            },
        )

    def _extract_article(self, url: str) -> str:
        try:
            response = run_with_retries(
                lambda: self._request(url),
                description=f"RSS article fetch {url}",
                max_attempts=self.retry_attempts,
                retry_delays_seconds=self.retry_delays_seconds,
                logger=LOGGER,
            )
            article = self.goose.extract(raw_html=response.text)
            return article.cleaned_text or ""
        except Exception as exc:
            LOGGER.warning("Failed to extract RSS article body from %s: %s", url, exc)
            return ""

    def _entry_feed_body(self, entry: dict) -> str:
        blocks: list[str] = []
        for content in entry.get("content", []) or []:
            if isinstance(content, dict) and content.get("value"):
                blocks.append(str(content["value"]))
        if not blocks and entry.get("summary"):
            blocks.append(str(entry.get("summary")))
        raw = "\n".join(blocks)
        plain = re.sub(r"<[^>]+>", " ", html.unescape(raw))
        return re.sub(r"\s+", " ", plain).strip()

    def _request(self, url: str, *, feed: bool = False) -> requests.Response:
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": self.FEED_ACCEPT if feed else self.ARTICLE_ACCEPT,
        }
        response = requests.get(url, headers=headers, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response


def _parse_struct_time(entry: dict) -> datetime:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        return datetime(*published[:6], tzinfo=timezone.utc)
    return utc_now()
