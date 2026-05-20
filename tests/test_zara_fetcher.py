import unittest
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
