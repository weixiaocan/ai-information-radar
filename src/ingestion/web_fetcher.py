from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from goose3 import Goose

from src.models.content_item import ContentItem
from src.utils.http_retry import run_with_retries
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


class WebFetcher:
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

    DEFAULT_MAX_ENTRIES = 20

    def __init__(self, timeout_seconds: int, date_grace_days: int = 0) -> None:
        self.timeout_seconds = timeout_seconds
        self.date_grace_days = max(0, date_grace_days)
        self.goose = Goose()
        self.retry_attempts = 3
        self.retry_delays_seconds = (10, 30)
        self.source_statuses: dict[str, dict[str, Any]] = {}
        # Content IDs that can never enter a future window (older than the date grace
        # period) plus catalog initialization markers. The pipeline adds them to
        # seen_ids so old articles are not re-downloaded on every run.
        self.stale_content_ids: set[str] = set()

    def fetch(
        self,
        sources: list[dict[str, Any]],
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
            source_key = f"web:{source.get('name', 'unknown')}"
            before_count = len(results)
            article_failures = 0
            try:
                entries = self._discover_entries(source)
            except Exception as exc:
                LOGGER.warning("Failed to discover web source %s: %s", source.get("name"), exc)
                self.source_statuses[source_key] = {"status": "failed", "items_fetched": 0, "error": str(exc)}
                continue
            if source.get("undated") and not self._initialize_catalog(source, entries, seen_ids):
                self.source_statuses[source_key] = {
                    "status": "no_new_items",
                    "items_fetched": 0,
                    "error": "",
                    "note": f"catalog initialized with {len(entries)} existing entries",
                }
                continue
            for entry in entries:
                content_id = f"web_{entry['url']}"
                if content_id in seen_ids:
                    continue
                listed_at = entry.get("published_at")
                if isinstance(listed_at, datetime) and self._window_placement(listed_at, cutoff, window_end) == "stale":
                    self.stale_content_ids.add(content_id)
                    continue
                try:
                    item = self._to_content_item(source, entry, content_id)
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to fetch web article %s from source %s: %s",
                        entry.get("url", ""),
                        source.get("name", ""),
                        exc,
                    )
                    article_failures += 1
                    continue
                if source.get("undated"):
                    # Catalog pages carry no dates: a newly listed entry counts as
                    # published within the current window.
                    item.published_at = window_end - timedelta(seconds=1)
                    item.extra_metadata["published_precision"] = "discovered"
                    results.append(item)
                    continue
                placement = self._window_placement(item.published_at, cutoff, window_end)
                if placement == "stale":
                    self.stale_content_ids.add(content_id)
                    continue
                if placement != "in_window":
                    continue
                if self._is_date_only(item.published_at) and item.published_at < cutoff:
                    # Date-only timestamps are normalized to 00:00 UTC, which usually
                    # precedes the real publication time. Keep the source date and place
                    # the item at the window start so the daily report includes it.
                    item.extra_metadata["published_precision"] = "date"
                    item.extra_metadata["source_published_date"] = item.published_at.date().isoformat()
                    item.published_at = cutoff
                results.append(item)
            self.source_statuses[source_key] = {
                "status": "degraded" if article_failures else ("success" if len(results) > before_count else "no_new_items"),
                "items_fetched": len(results) - before_count,
                "failed_items": article_failures,
                "error": f"{article_failures} article fetches failed" if article_failures else "",
            }
        LOGGER.info("Fetched %s new web articles", len(results))
        return results

    def _window_placement(self, published_at: datetime, cutoff: datetime, window_end: datetime) -> str:
        """Classify a timestamp as in_window, future (may enter a later window) or stale."""
        if published_at >= window_end:
            return "future"
        if published_at >= cutoff:
            return "in_window"
        if self._is_date_only(published_at):
            grace_start = cutoff - timedelta(days=self.date_grace_days)
            if published_at + timedelta(days=1) > grace_start:
                return "in_window"
        return "stale"

    @staticmethod
    def _is_date_only(published_at: datetime) -> bool:
        return published_at.astimezone(timezone.utc).time() == time(0)

    def _initialize_catalog(self, source: dict[str, Any], entries: list[dict[str, Any]], seen_ids: set[str]) -> bool:
        """Return True when the catalog was already initialized.

        On the first run every listed entry is recorded as seen without being emitted,
        so only entries that appear later are reported as new.
        """
        marker = f"web_catalog_initialized:{source.get('name', 'unknown')}"
        if marker in seen_ids:
            return True
        if not entries:
            # An empty listing usually means the page failed to render; initializing
            # now would later report the whole catalog as new.
            return False
        self.stale_content_ids.add(marker)
        self.stale_content_ids.update(f"web_{entry['url']}" for entry in entries)
        return False

    def _discover_entries(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        response = run_with_retries(
            lambda: self._request(source["index_url"]),
            description=f"Web index fetch {source.get('name', source['index_url'])}",
            max_attempts=self.retry_attempts,
            retry_delays_seconds=self.retry_delays_seconds,
            logger=LOGGER,
        )
        html = response.text
        discovery = str(source.get("discovery", "links")).strip()
        if discovery == "embedded_json":
            entries = self._discover_embedded_json_entries(html, source)
        elif discovery == "anchor_class":
            entries = self._discover_anchor_class_entries(html, source)
        else:
            urls = self._discover_urls(html, str(source.get("article_base_url", "")).strip(), source["index_url"])
            entries = []
            for raw_url, normalized_url in urls:
                title = self._extract_anchor_title(html, raw_url) or self._extract_anchor_title(html, normalized_url)
                entries.append({"url": normalized_url, "title": title})
        max_entries = source.get("max_entries", None if source.get("undated") else self.DEFAULT_MAX_ENTRIES)
        return entries if max_entries is None else entries[: int(max_entries)]

    def _discover_embedded_json_entries(self, html: str, source: dict[str, Any]) -> list[dict[str, Any]]:
        """Read posts from framework data embedded in the page (escaped JSON objects).

        Each object of `item_type` provides either a `slug` (expanded with
        `slug_url_template`) or an `externalUrl`, plus a `date` and `title`.
        """
        # Next.js streams page data in several `self.__next_f.push([1,"..."])` chunks
        # that can split a string value; join the chunks before parsing.
        data = re.sub(r'"\]\)</script><script[^>]*>self\.__next_f\.push\(\[1,"', "", html)
        data = data.replace('\\"', '"')
        item_type = str(source.get("item_type", "")).strip()
        slug_url_template = str(source.get("slug_url_template", "")).strip()
        entries_by_url: dict[str, dict[str, Any]] = {}
        for match in re.finditer(r'"_type":"' + re.escape(item_type) + '"', data):
            segment = data[match.start() : match.start() + 3000]
            next_object = segment.find('"_type":', len(match.group(0)))
            if next_object > 0:
                segment = segment[:next_object]
            slug = self._json_string_field(segment, "slug")
            url = self._json_string_field(segment, "externalUrl")
            if not url and slug and slug_url_template:
                url = slug_url_template.format(slug=slug)
            if not url or url in entries_by_url:
                continue
            entry: dict[str, Any] = {"url": url, "title": self._json_string_field(segment, "title")}
            raw_date = self._json_string_field(segment, "date")
            if raw_date:
                try:
                    entry["published_at"] = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            entries_by_url[url] = entry
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(entries_by_url.values(), key=lambda entry: entry.get("published_at") or epoch, reverse=True)

    @staticmethod
    def _json_string_field(segment: str, field: str) -> str:
        match = re.search(r'"' + re.escape(field) + r'":"((?:[^"\\]|\\.)*)"', segment)
        return unescape(match.group(1)).strip() if match else ""

    def _discover_anchor_class_entries(self, html: str, source: dict[str, Any]) -> list[dict[str, Any]]:
        anchor_class = str(source.get("anchor_class", "")).strip()
        exclude_paths = {str(path).strip() for path in source.get("exclude_paths", [])}
        entries_by_url: dict[str, dict[str, Any]] = {}
        for match in re.finditer(r"<a\b[^>]*>", html, re.IGNORECASE):
            tag = match.group(0)
            class_match = re.search(r'class="([^"]*)"', tag)
            href_match = re.search(r'href="([^"]+)"', tag)
            if not class_match or not href_match or anchor_class not in class_match.group(1).split():
                continue
            href = href_match.group(1).strip()
            if href in exclude_paths:
                continue
            url = urljoin(source["index_url"], href)
            title_match = re.search(r'title="([^"]*)"', tag)
            entries_by_url.setdefault(url, {"url": url, "title": unescape(title_match.group(1)).strip() if title_match else ""})
        return list(entries_by_url.values())

    def _discover_urls(self, html: str, article_base_url: str, index_url: str) -> list[tuple[str, str]]:
        prefixes = [article_base_url]
        parsed_base = urlparse(article_base_url)
        if parsed_base.scheme and parsed_base.netloc and parsed_base.path:
            prefixes.append(parsed_base.path)

        discovered: dict[str, str] = {}
        for prefix in [prefix for prefix in prefixes if prefix]:
            pattern = re.escape(prefix) + r"[^\"'#<>\s\\]+"
            for raw_url in re.findall(pattern, html):
                normalized_url = urljoin(index_url, raw_url).rstrip("\\")
                discovered.setdefault(normalized_url, raw_url)
        return [(raw_url, normalized_url) for normalized_url, raw_url in discovered.items()]

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

    def _to_content_item(self, source: dict[str, Any], entry: dict[str, Any], content_id: str) -> ContentItem:
        response = run_with_retries(
            lambda: self._request(entry["url"]),
            description=f"Web article fetch {entry['url']}",
            max_attempts=self.retry_attempts,
            retry_delays_seconds=self.retry_delays_seconds,
            logger=LOGGER,
        )
        article = self.goose.extract(raw_html=response.text)
        title = article.title or entry.get("title") or "Untitled article"
        body = article.cleaned_text or ""
        listed_at = entry.get("published_at")
        published_at = (
            listed_at
            if isinstance(listed_at, datetime)
            else self._extract_publish_datetime(response.text, article.publish_date)
        )
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

    def _extract_publish_datetime(self, html: str, fallback: datetime | str | None) -> datetime:
        if fallback:
            if isinstance(fallback, datetime):
                return fallback if fallback.tzinfo else fallback.replace(tzinfo=timezone.utc)
            if isinstance(fallback, str):
                try:
                    parsed = datetime.fromisoformat(fallback.strip().replace("Z", "+00:00"))
                    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
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
                parsed = datetime.fromisoformat(value)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        text = unescape(re.sub(r"<!--.*?-->|<[^>]+>", " ", html, flags=re.DOTALL))
        text = re.sub(r"\s+", " ", text)
        date_match = re.search(
            r"\b(?:Published\s+)?"
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})\b",
            text,
            re.IGNORECASE,
        )
        if date_match:
            raw_date = date_match.group(1).replace("Sept", "Sep")
            for fmt in ("%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(raw_date, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return utc_now()

    def _request(self, url: str) -> requests.Response:
        response = requests.get(url, headers={"User-Agent": self.USER_AGENT}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response
