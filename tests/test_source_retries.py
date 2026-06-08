import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from src.ingestion.rss_fetcher import RSSFetcher
from src.ingestion.web_fetcher import WebFetcher
from src.ingestion.youtube_fetcher import YouTubeFetcher


class _TextResponse:
    def __init__(self, text: str, url: str = "https://example.com/final") -> None:
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        return None


class _JsonResponse(_TextResponse):
    def __init__(self, payload: dict, url: str = "https://example.com/final") -> None:
        super().__init__("", url=url)
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class SourceRetryTest(unittest.TestCase):
    @patch("src.utils.http_retry.time.sleep", return_value=None)
    def test_rss_fetch_retries_feed_request_and_recovers(self, _sleep: Mock) -> None:
        fetcher = RSSFetcher(timeout_seconds=30)
        source = {"name": "rss_source", "url": "https://example.com/rss.xml", "enabled": True}

        with (
            patch(
                "src.ingestion.rss_fetcher.requests.get",
                side_effect=[requests.Timeout("boom"), _TextResponse("<rss />")],
            ) as mock_get,
            patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=Mock(entries=[])),
        ):
            items = fetcher.fetch(
                [source],
                seen_ids=set(),
                recent_days=7,
                start_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
                end_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            )

        self.assertEqual(items, [])
        self.assertEqual(mock_get.call_count, 2)
        _sleep.assert_called_once_with(10)

    @patch("src.utils.http_retry.time.sleep", return_value=None)
    def test_web_fetch_retries_index_request_and_recovers(self, _sleep: Mock) -> None:
        fetcher = WebFetcher(timeout_seconds=30)
        fetcher.goose = Mock()
        fetcher.goose.extract.return_value = Mock(
            title="Article A",
            cleaned_text="Body",
            publish_date=datetime(2026, 5, 17, tzinfo=timezone.utc),
            authors=[],
        )
        source = {
            "name": "web_source",
            "index_url": "https://example.com/blog",
            "article_base_url": "/posts/",
            "enabled": True,
        }
        index_html = '<a href="/posts/article-a">Article A</a>'

        with patch(
            "src.ingestion.web_fetcher.requests.get",
            side_effect=[
                requests.Timeout("boom"),
                _TextResponse(index_html),
                _TextResponse("<html><body>Article A</body></html>"),
            ],
        ) as mock_get:
            items = fetcher.fetch(
                [source],
                seen_ids=set(),
                recent_days=7,
                start_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
                end_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_id, "web_https://example.com/posts/article-a")
        self.assertEqual(mock_get.call_count, 3)
        _sleep.assert_called_once_with(10)

    def test_web_fetch_discovers_relative_links_when_source_base_is_absolute(self) -> None:
        fetcher = WebFetcher(timeout_seconds=30)
        html = """
        <a href="/engineering/how-we-contain-claude">How we contain Claude</a>
        <script>{"url":"https://www.anthropic.com/engineering/old-post\\"}</script>
        """
        urls = fetcher._discover_urls(
            html,
            "https://www.anthropic.com/engineering/",
            "https://www.anthropic.com/engineering",
        )

        self.assertIn(
            ("/engineering/how-we-contain-claude", "https://www.anthropic.com/engineering/how-we-contain-claude"),
            urls,
        )
        self.assertTrue(all(not normalized_url.endswith("\\") for _, normalized_url in urls))

    @patch("src.utils.http_retry.time.sleep", return_value=None)
    def test_youtube_get_retries_timeout_and_recovers(self, _sleep: Mock) -> None:
        fetcher = YouTubeFetcher(api_key="key", timeout_seconds=30)

        with patch(
            "src.ingestion.youtube_fetcher.requests.get",
            side_effect=[requests.Timeout("boom"), _JsonResponse({"items": []})],
        ) as mock_get:
            payload = fetcher._youtube_get("search", {"q": "test"})

        self.assertEqual(payload, {"items": []})
        self.assertEqual(mock_get.call_count, 2)
        _sleep.assert_called_once_with(10)


if __name__ == "__main__":
    unittest.main()
