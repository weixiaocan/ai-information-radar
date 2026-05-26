from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.models.content_item import ContentItem
from src.utils.source_labels import resolve_zara_source_name
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


@dataclass
class ZaraFetchReport:
    feed_name: str
    status: str
    attempts: int
    items_fetched: int
    error: str = ""


class ZaraFetcher:
    def __init__(
        self,
        feeds: list[dict[str, Any]],
        timeout_seconds: int,
        retry_attempts: int = 4,
        retry_delays_seconds: tuple[int, ...] = (60, 180, 600),
        retry_window_seconds: int | None = None,
    ) -> None:
        self.feeds = feeds
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_delays_seconds = retry_delays_seconds
        self.retry_window_seconds = retry_window_seconds
        self.last_fetch_reports: list[ZaraFetchReport] = []

    def fetch(
        self,
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = start_at or utc_days_ago(recent_days)
        window_end = end_at or utc_now()
        self.last_fetch_reports = []
        for feed in self.feeds:
            if not feed.get("enabled", True):
                continue
            items, report = self._fetch_single_feed(feed, seen_ids, cutoff, window_end)
            results.extend(items)
            self.last_fetch_reports.append(report)
        LOGGER.info("Fetched %s new Zara items", len(results))
        return results

    def _fetch_single_feed(
        self,
        feed: dict[str, Any],
        seen_ids: set[str],
        cutoff: datetime,
        window_end: datetime,
    ) -> tuple[list[ContentItem], ZaraFetchReport]:
        attempts = 0
        last_error = ""
        feed_name = str(feed.get("name", "unknown"))
        started_at = time.monotonic()

        for attempt in range(1, self.retry_attempts + 1):
            attempts = attempt
            try:
                response = requests.get(feed["url"], timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                items: list[ContentItem] = []
                apply_local_window = self._should_apply_local_time_window(feed_name)
                for entry in self._extract_entries(feed_name, payload):
                    item = self._to_content_item(feed, entry)
                    if item.content_id in seen_ids:
                        continue
                    if apply_local_window and (item.published_at < cutoff or item.published_at >= window_end):
                        continue
                    items.append(item)
                status = "success" if items else "empty"
                return items, ZaraFetchReport(
                    feed_name=feed_name,
                    status=status,
                    attempts=attempts,
                    items_fetched=len(items),
                )
            except Exception as exc:
                last_error = str(exc)
                retryable = self._is_retryable_exception(exc)
                if self._retry_window_exhausted(started_at):
                    LOGGER.warning("Failed to fetch Zara feed %s after retry window elapsed: %s", feed_name, exc)
                    return [], ZaraFetchReport(
                        feed_name=feed_name,
                        status="timed_out",
                        attempts=attempts,
                        items_fetched=0,
                        error=last_error,
                    )
                if attempt >= self.retry_attempts or not retryable:
                    LOGGER.warning("Failed to fetch Zara feed %s after %s attempt(s): %s", feed_name, attempt, exc)
                    return [], ZaraFetchReport(
                        feed_name=feed_name,
                        status="failed",
                        attempts=attempts,
                        items_fetched=0,
                        error=last_error,
                    )
                delay = self.retry_delays_seconds[min(attempt - 1, len(self.retry_delays_seconds) - 1)]
                if self._retry_window_exhausted(started_at, next_delay_seconds=delay):
                    LOGGER.warning(
                        "Failed to fetch Zara feed %s before attempt %s retry window would be exceeded: %s",
                        feed_name,
                        attempt,
                        exc,
                    )
                    return [], ZaraFetchReport(
                        feed_name=feed_name,
                        status="timed_out",
                        attempts=attempts,
                        items_fetched=0,
                        error=last_error,
                    )
                LOGGER.warning(
                    "Failed to fetch Zara feed %s on attempt %s/%s: %s; retrying in %ss",
                    feed_name,
                    attempt,
                    self.retry_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

        return [], ZaraFetchReport(
            feed_name=feed_name,
            status="failed",
            attempts=attempts,
            items_fetched=0,
            error=last_error,
        )

    def _retry_window_exhausted(self, started_at: float, next_delay_seconds: int = 0) -> bool:
        if self.retry_window_seconds is None:
            return False
        elapsed_seconds = time.monotonic() - started_at
        return elapsed_seconds + next_delay_seconds >= self.retry_window_seconds

    def _should_apply_local_time_window(self, feed_name: str) -> bool:
        return feed_name != "zara_x"

    def _is_retryable_exception(self, exc: Exception) -> bool:
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return exc.response.status_code >= 500
        return False

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
        source_name = resolve_zara_source_name(feed["name"], entry)
        native_id = entry.get("id") or entry.get("url") or entry.get("title")
        published_at = _parse_datetime(entry.get("published_at") or entry.get("date"))
        return ContentItem(
            content_id=f"{source_type}_{native_id}",
            source_type=source_type,
            source_name=source_name,
            title=entry.get("title") or entry.get("summary") or "Untitled Zara item",
            url=entry.get("url") or entry.get("link") or "",
            author=entry.get("author"),
            published_at=published_at,
            fetched_at=utc_now(),
            body=entry.get("content") or entry.get("summary") or entry.get("transcript") or "",
            body_type="summary" if feed["name"] != "zara_podcast" else "transcript",
            extra_metadata={
                "raw_entry": entry,
                "display_name": feed.get("display_name", feed["name"]),
                "upstream_source_name": feed["name"],
            },
        )


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)
