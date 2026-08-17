from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from src.models.content_item import ContentItem
from src.utils.http_retry import run_with_retries
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)

ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


class HNAlgoliaFetcher:
    """Fetch high-signal Hacker News stories via the official Algolia API.

    The previous source used hnrss.org, which 502s intermittently (~35% of days)
    and whose narrow keyword query missed releases like "DeepSeek Harness".
    This fetcher queries Algolia (official, reliable) once per keyword and
    dedupes by objectID, so a story is picked up if it matches any keyword.
    Article bodies are not extracted here (many HN targets are paywalled); the
    story title + URL + points carry enough signal for downstream curation.
    """

    USER_AGENT = "AI-Radar-HN/1.0 (+local personal feed reader)"

    def __init__(
        self,
        timeout_seconds: int,
        retry_attempts: int = 4,
        retry_delays_seconds: tuple[int, ...] = (10, 30, 60),
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_delays_seconds = retry_delays_seconds
        self.source_statuses: dict[str, dict] = {}

    def fetch(
        self,
        sources: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        cutoff = start_at or utc_days_ago(recent_days)
        window_end = end_at or utc_now()
        results: list[ContentItem] = []
        for source in sources:
            if not source.get("enabled", True):
                continue
            name = str(source.get("name", "hacker_news_ai"))
            keywords = [kw.strip() for kw in str(source.get("query", "")).split() if kw.strip()]
            min_points = int(source.get("min_points", 100))
            try:
                hits = self._fetch_deduped_hits(keywords, min_points)
            except Exception as exc:
                LOGGER.warning("Failed to fetch HN Algolia source %s: %s", name, exc)
                self.source_statuses[f"rss:{name}"] = {
                    "status": "feed_failed",
                    "items_fetched": 0,
                    "error": str(exc),
                }
                continue
            source_items = 0
            for hit in hits:
                object_id = str(hit.get("objectID", "")).strip()
                content_id = f"rss_{object_id}"
                if content_id in seen_ids:
                    continue
                published_at = _parse_algolia_datetime(hit.get("created_at"))
                if published_at < cutoff or published_at >= window_end:
                    continue
                results.append(self._to_content_item(source, hit, content_id, published_at))
                source_items += 1
            self.source_statuses[f"rss:{name}"] = {
                "status": "success" if source_items else "no_new_items",
                "items_fetched": source_items,
                "error": "",
            }
        LOGGER.info("Fetched %s new HN Algolia items", len(results))
        return results

    def _fetch_deduped_hits(self, keywords: list[str], min_points: int) -> list[dict]:
        deduped: dict[str, dict] = {}
        for keyword in keywords:
            try:
                payload = self._search(keyword, min_points)
            except Exception as exc:
                LOGGER.warning("HN Algolia keyword query %r failed: %s", keyword, exc)
                continue
            for hit in payload.get("hits", []):
                object_id = str(hit.get("objectID", "")).strip()
                if object_id and object_id not in deduped:
                    deduped[object_id] = hit
        return list(deduped.values())

    def _search(self, keyword: str, min_points: int) -> dict[str, Any]:
        url = (
            f"{ALGOLIA_SEARCH_URL}?query={quote(keyword)}"
            f"&tags=story&numericFilters=points%3E%3D{min_points}&hitsPerPage=20"
        )
        response = run_with_retries(
            lambda: self._request(url),
            description=f"HN Algolia query {keyword}",
            max_attempts=self.retry_attempts,
            retry_delays_seconds=self.retry_delays_seconds,
            logger=LOGGER,
        )
        return response.json()

    def _to_content_item(
        self,
        source: dict,
        hit: dict,
        content_id: str,
        published_at: datetime,
    ) -> ContentItem:
        object_id = str(hit.get("objectID", "")).strip()
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        story_text = str(hit.get("story_text") or "").strip()
        return ContentItem(
            content_id=content_id,
            source_type="rss",
            source_name=str(source.get("name", "hacker_news_ai")),
            title=hit.get("title") or "Untitled HN story",
            url=url,
            author=hit.get("author"),
            published_at=published_at,
            fetched_at=utc_now(),
            body=story_text,
            body_type="article",
            extra_metadata={
                "display_name": source.get("display_name", "Hacker News AI"),
                "hn_points": hit.get("points"),
                "hn_comments": hit.get("num_comments"),
                "hn_object_id": object_id,
            },
        )

    def _request(self, url: str) -> requests.Response:
        response = requests.get(
            url,
            headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response


def _parse_algolia_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return utc_now()
