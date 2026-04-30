from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from src.models.content_item import ContentItem
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


class ZaraFetcher:
    def __init__(self, feeds: list[dict[str, Any]], timeout_seconds: int) -> None:
        self.feeds = feeds
        self.timeout_seconds = timeout_seconds

    def fetch(self, seen_ids: set[str], recent_days: int) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = utc_days_ago(recent_days)
        for feed in self.feeds:
            if not feed.get("enabled", True):
                continue
            try:
                response = requests.get(feed["url"], timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                for entry in self._extract_entries(feed["name"], payload):
                    item = self._to_content_item(feed, entry)
                    if item.content_id in seen_ids or item.published_at < cutoff:
                        continue
                    results.append(item)
            except Exception as exc:
                LOGGER.warning("Failed to fetch Zara feed %s: %s", feed.get("name"), exc)
        LOGGER.info("Fetched %s new Zara items", len(results))
        return results

    def _extract_entries(self, feed_name: str, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if feed_name == "zara_x":
            entries: list[dict[str, Any]] = []
            for builder in payload.get("x", []):
                for tweet in builder.get("tweets", []):
                    entries.append(
                        {
                            "id": tweet.get("id"),
                            "title": f"{builder.get('name', builder.get('handle', 'Unknown'))}: {tweet.get('text', '')[:80]}",
                            "summary": tweet.get("text", ""),
                            "content": tweet.get("text", ""),
                            "url": tweet.get("url"),
                            "author": builder.get("name") or builder.get("handle"),
                            "date": tweet.get("createdAt"),
                            "type": "x",
                        }
                    )
            return entries
        if feed_name == "zara_blog":
            return payload.get("blogs", [])
        if feed_name == "zara_podcast":
            return payload.get("podcasts", [])
        return payload.get("items", [])

    def _to_content_item(self, feed: dict[str, Any], entry: dict) -> ContentItem:
        source_kind = str(entry.get("type", "summary")).lower()
        source_type = feed["name"] if feed["name"].startswith("zara_") else f"zara_{source_kind}"
        native_id = entry.get("id") or entry.get("url") or entry.get("title")
        published_at = _parse_datetime(entry.get("published_at") or entry.get("date"))
        return ContentItem(
            content_id=f"{source_type}_{native_id}",
            source_type=source_type,
            source_name=feed["name"],
            title=entry.get("title") or entry.get("summary") or "Untitled Zara item",
            url=entry.get("url") or entry.get("link") or "",
            author=entry.get("author"),
            published_at=published_at,
            fetched_at=utc_now(),
            body=entry.get("content") or entry.get("summary") or entry.get("transcript") or "",
            body_type="summary" if feed["name"] != "zara_podcast" else "transcript",
            extra_metadata={"raw_entry": entry, "display_name": feed.get("display_name", feed["name"])},
        )


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)
