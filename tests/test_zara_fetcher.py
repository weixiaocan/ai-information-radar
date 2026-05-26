import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from src.ingestion.zara_fetcher import ZaraFetcher


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class ZaraFetcherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = {
            "name": "zara_x",
            "display_name": "Zara Follow Builders X",
            "url": "https://example.com/feed-x.json",
            "enabled": True,
        }
        self.blog_feed = {
            "name": "zara_blog",
            "display_name": "Zara Blogs",
            "url": "https://example.com/feed-blog.json",
            "enabled": True,
        }

    @patch("src.ingestion.zara_fetcher.time.sleep", return_value=None)
    def test_fetch_retries_timeout_and_recovers(self, _sleep: Mock) -> None:
        payload = {
            "x": [
                {
                    "name": "Aaron Levie",
                    "tweets": [
                        {
                            "id": "1",
                            "text": "Agent workflow shipping",
                            "url": "https://x.com/levie/status/1",
                            "createdAt": "2026-05-15T04:19:23.000Z",
                        }
                    ],
                }
            ]
        }
        fetcher = ZaraFetcher([self.feed], timeout_seconds=30)

        with patch(
            "src.ingestion.zara_fetcher.requests.get",
            side_effect=[requests.Timeout("boom"), FakeResponse(payload)],
        ) as mock_get:
            items = fetcher.fetch(seen_ids=set(), recent_days=30)

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(len(items), 1)
        self.assertEqual(fetcher.last_fetch_reports[0].status, "success")
        self.assertEqual(fetcher.last_fetch_reports[0].attempts, 2)
        _sleep.assert_called_once_with(60)

    @patch("src.ingestion.zara_fetcher.time.sleep", return_value=None)
    def test_fetch_marks_failed_after_retries_exhausted(self, _sleep: Mock) -> None:
        fetcher = ZaraFetcher([self.feed], timeout_seconds=30)

        with patch(
            "src.ingestion.zara_fetcher.requests.get",
            side_effect=requests.Timeout("still failing"),
        ) as mock_get:
            items = fetcher.fetch(seen_ids=set(), recent_days=30)

        self.assertEqual(items, [])
        self.assertEqual(mock_get.call_count, 4)
        self.assertEqual(fetcher.last_fetch_reports[0].status, "failed")
        self.assertEqual(fetcher.last_fetch_reports[0].attempts, 4)
        self.assertIn("still failing", fetcher.last_fetch_reports[0].error)
        self.assertEqual(_sleep.call_count, 3)

    @patch("src.ingestion.zara_fetcher.time.sleep", return_value=None)
    @patch("src.ingestion.zara_fetcher.time.monotonic", side_effect=[0.0, 0.0, 0.0, 35.0, 35.0])
    def test_fetch_marks_timed_out_when_retry_window_is_exhausted(self, _monotonic: Mock, _sleep: Mock) -> None:
        fetcher = ZaraFetcher(
            [self.feed],
            timeout_seconds=30,
            retry_attempts=4,
            retry_delays_seconds=(30, 60, 120),
            retry_window_seconds=50,
        )

        with patch(
            "src.ingestion.zara_fetcher.requests.get",
            side_effect=requests.Timeout("still failing"),
        ) as mock_get:
            items = fetcher.fetch(seen_ids=set(), recent_days=30)

        self.assertEqual(items, [])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(fetcher.last_fetch_reports[0].status, "timed_out")
        self.assertEqual(fetcher.last_fetch_reports[0].attempts, 2)
        self.assertEqual(_sleep.call_count, 1)

    def test_zara_x_ignores_local_time_window_but_still_dedupes_seen_ids(self) -> None:
        payload = {
            "x": [
                {
                    "name": "Aaron Levie",
                    "tweets": [
                        {
                            "id": "1",
                            "text": "Older upstream batch item",
                            "url": "https://x.com/levie/status/1",
                            "createdAt": "2026-05-24T01:00:00.000Z",
                        },
                        {
                            "id": "2",
                            "text": "Already seen item",
                            "url": "https://x.com/levie/status/2",
                            "createdAt": "2026-05-24T02:00:00.000Z",
                        },
                    ],
                }
            ]
        }
        fetcher = ZaraFetcher([self.feed], timeout_seconds=30)
        start_at = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)
        end_at = datetime(2026, 5, 26, 0, 0, tzinfo=timezone.utc)

        with patch("src.ingestion.zara_fetcher.requests.get", return_value=FakeResponse(payload)):
            items = fetcher.fetch(
                seen_ids={"zara_x_2"},
                recent_days=1,
                start_at=start_at,
                end_at=end_at,
            )

        self.assertEqual([item.content_id for item in items], ["zara_x_1"])
        self.assertEqual(fetcher.last_fetch_reports[0].status, "success")

    def test_non_x_zara_feeds_still_apply_local_time_window(self) -> None:
        payload = {
            "blogs": [
                {
                    "id": "blog-1",
                    "title": "Outside local window",
                    "summary": "Should be filtered",
                    "content": "Should be filtered",
                    "url": "https://example.com/blog-1",
                    "author": "Zara",
                    "date": "2026-05-24T01:00:00.000Z",
                    "type": "blog",
                }
            ]
        }
        fetcher = ZaraFetcher([self.blog_feed], timeout_seconds=30)
        start_at = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)
        end_at = datetime(2026, 5, 26, 0, 0, tzinfo=timezone.utc)

        with patch("src.ingestion.zara_fetcher.requests.get", return_value=FakeResponse(payload)):
            items = fetcher.fetch(
                seen_ids=set(),
                recent_days=1,
                start_at=start_at,
                end_at=end_at,
            )

        self.assertEqual(items, [])
        self.assertEqual(fetcher.last_fetch_reports[0].status, "empty")
