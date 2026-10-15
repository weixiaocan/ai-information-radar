import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.ingestion.web_fetcher import WebFetcher

SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_START = datetime(2026, 10, 14, 7, tzinfo=SHANGHAI)
WINDOW_END = datetime(2026, 10, 15, 7, tzinfo=SHANGHAI)


class _TextResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def _article(title: str, visible_date: str) -> str:
    return f"<html><head><title>{title}</title></head><body><p class=\"date\">{visible_date}</p><p>{title} body.</p></body></html>"


def _serve(pages: dict[str, str]):
    def request(url: str) -> _TextResponse:
        if url not in pages:
            raise AssertionError(f"unexpected request: {url}")
        return _TextResponse(pages[url])

    return request


class WebFetcherWindowTest(unittest.TestCase):
    def _fetch(self, fetcher: WebFetcher, source: dict, pages: dict[str, str], seen_ids: set[str] | None = None):
        with patch.object(fetcher, "_request", side_effect=_serve(pages)):
            return fetcher.fetch([source], seen_ids or set(), recent_days=1, start_at=WINDOW_START, end_at=WINDOW_END)

    def test_date_only_article_published_after_previous_run_is_kept(self) -> None:
        # Regression: anthropic.com/engineering/redesigning-source-control (Oct 13) was
        # dated 00:00 UTC and fell before a late-starting window, so it was never kept.
        fetcher = WebFetcher(timeout_seconds=30, date_grace_days=2)
        source = {
            "name": "anthropic_engineering",
            "index_url": "https://www.anthropic.com/engineering",
            "article_base_url": "https://www.anthropic.com/engineering/",
        }
        pages = {
            "https://www.anthropic.com/engineering": (
                '<a href="/engineering/redesigning-source-control">Redesigning source control</a>'
                '<a href="/engineering/how-we-contain-claude">How we contain Claude</a>'
            ),
            "https://www.anthropic.com/engineering/redesigning-source-control": _article(
                "Redesigning source control", "Published Oct 13, 2026"
            ),
            "https://www.anthropic.com/engineering/how-we-contain-claude": _article(
                "How we contain Claude", "Published May 25, 2026"
            ),
        }

        items = self._fetch(fetcher, source, pages)

        self.assertEqual([item.url for item in items], ["https://www.anthropic.com/engineering/redesigning-source-control"])
        self.assertEqual(items[0].published_at, WINDOW_START)
        self.assertEqual(items[0].extra_metadata["source_published_date"], "2026-10-13")
        self.assertEqual(
            fetcher.stale_content_ids,
            {"web_https://www.anthropic.com/engineering/how-we-contain-claude"},
        )

    def test_date_only_article_outside_grace_is_stale(self) -> None:
        fetcher = WebFetcher(timeout_seconds=30, date_grace_days=0)
        placement = fetcher._window_placement(
            datetime(2026, 10, 12, tzinfo=timezone.utc), WINDOW_START, WINDOW_END
        )
        self.assertEqual(placement, "stale")

    def test_future_article_is_left_for_next_window(self) -> None:
        fetcher = WebFetcher(timeout_seconds=30, date_grace_days=2)
        placement = fetcher._window_placement(
            datetime(2026, 10, 15, tzinfo=timezone.utc), WINDOW_START, WINDOW_END
        )
        self.assertEqual(placement, "future")

    def test_embedded_json_listing_joins_stream_chunks_and_skips_stale_without_fetch(self) -> None:
        fetcher = WebFetcher(timeout_seconds=30, date_grace_days=2)
        source = {
            "name": "claude_blog",
            "index_url": "https://www.claude.com/blog",
            "discovery": "embedded_json",
            "item_type": "blogPost",
            "slug_url_template": "https://claude.com/blog/{slug}",
        }
        index = (
            '<script>self.__next_f.push([1,"{\\"_type\\":\\"blogPost\\",\\"slug\\":null,'
            '\\"externalUrl\\":\\"https://claude.dev/blog/automati"])</script>'
            '<script nonce="abc">self.__next_f.push([1,"ng-evals/\\",\\"date\\":\\"2026-10-14\\",'
            '\\"title\\":\\"Automating evals\\"},{\\"_type\\":\\"blogPost\\",\\"slug\\":\\"old-post\\",'
            '\\"date\\":\\"2026-09-01\\",\\"title\\":\\"Old post\\"}"])</script>'
        )
        pages = {
            "https://www.claude.com/blog": index,
            "https://claude.dev/blog/automating-evals/": _article("Automating evals", ""),
        }

        items = self._fetch(fetcher, source, pages)

        self.assertEqual([item.url for item in items], ["https://claude.dev/blog/automating-evals/"])
        self.assertEqual(items[0].published_at, datetime(2026, 10, 14, tzinfo=timezone.utc))
        self.assertIn("web_https://claude.com/blog/old-post", fetcher.stale_content_ids)

    def test_undated_catalog_initializes_then_reports_new_entries(self) -> None:
        source = {
            "name": "anthropic_academy",
            "index_url": "https://anthropic.skilljar.com/",
            "discovery": "anchor_class",
            "anchor_class": "coursebox-container",
            "undated": True,
        }
        first_index = '<a href="/claude-101" title="Claude 101" class="coursebox-container course">x</a>'
        fetcher = WebFetcher(timeout_seconds=30)

        items = self._fetch(fetcher, source, {"https://anthropic.skilljar.com/": first_index})

        self.assertEqual(items, [])
        self.assertEqual(
            fetcher.stale_content_ids,
            {"web_catalog_initialized:anthropic_academy", "web_https://anthropic.skilljar.com/claude-101"},
        )
        self.assertEqual(fetcher.source_statuses["web:anthropic_academy"]["status"], "no_new_items")

        seen_ids = set(fetcher.stale_content_ids)
        second_index = first_index + (
            '<a href="/introduction-to-subagents" title="Introduction to Subagents" '
            'class="coursebox-container course">y</a>'
        )
        fetcher = WebFetcher(timeout_seconds=30)

        items = self._fetch(
            fetcher,
            source,
            {
                "https://anthropic.skilljar.com/": second_index,
                "https://anthropic.skilljar.com/introduction-to-subagents": _article("Introduction to Subagents", ""),
            },
            seen_ids,
        )

        self.assertEqual([item.url for item in items], ["https://anthropic.skilljar.com/introduction-to-subagents"])
        self.assertTrue(WINDOW_START <= items[0].published_at < WINDOW_END)
        self.assertEqual(items[0].extra_metadata["published_precision"], "discovered")

    def test_empty_catalog_listing_does_not_initialize(self) -> None:
        fetcher = WebFetcher(timeout_seconds=30)
        source = {
            "name": "anthropic_academy",
            "index_url": "https://anthropic.skilljar.com/",
            "discovery": "anchor_class",
            "anchor_class": "coursebox-container",
            "undated": True,
        }

        items = self._fetch(fetcher, source, {"https://anthropic.skilljar.com/": "<html>maintenance</html>"})

        self.assertEqual(items, [])
        self.assertEqual(fetcher.stale_content_ids, set())


if __name__ == "__main__":
    unittest.main()
