import unittest
from datetime import date, datetime, timedelta, timezone

from src.output.health_report import WeeklyHealthReportBuilder


class WeeklyHealthReportBuilderTest(unittest.TestCase):
    def test_report_surfaces_failed_and_degraded_sources(self) -> None:
        snapshots = [
            {
                "timestamp": "2026-07-06T00:00:00+00:00",
                "sources": {
                    "rss:verge_ai": {"status": "feed_failed", "error": "403 Forbidden"},
                    "rss:hacker_news_ai": {"status": "success_with_article_fallbacks", "error": ""},
                    "youtube:latent_space": {"status": "no_new_items", "error": ""},
                }
            }
        ]
        heartbeats = []
        for offset in range(7):
            timestamp = (datetime(2026, 7, 6, tzinfo=timezone.utc) + timedelta(days=offset)).isoformat()
            heartbeats.extend([
                {"task": "ingest", "timestamp": timestamp},
                {"task": "daily_curate", "timestamp": timestamp},
                {"task": "daily", "timestamp": timestamp},
            ])

        payload = WeeklyHealthReportBuilder().build(
            snapshots, heartbeats, week_start=date(2026, 7, 6), week_end=date(2026, 7, 12)
        )

        self.assertEqual(payload["card"]["header"]["template"], "red")
        content = "\n".join(
            element.get("text", {}).get("content", "") for element in payload["card"]["elements"]
        )
        self.assertIn("RSS · verge ai", content)
        self.assertIn("403 Forbidden", content)
        self.assertIn("RSS · hacker news ai", content)
        self.assertNotIn("youtube:latent_space", content)

    def test_report_is_green_when_all_runs_and_sources_are_healthy(self) -> None:
        snapshots = [
            {
                "timestamp": (datetime(2026, 7, 6, tzinfo=timezone.utc) + timedelta(days=offset)).isoformat(),
                "sources": {"rss:verge_ai": {"status": "success", "error": ""}},
            }
            for offset in range(7)
        ]
        heartbeats = []
        for offset in range(7):
            timestamp = (datetime(2026, 7, 6, tzinfo=timezone.utc) + timedelta(days=offset)).isoformat()
            heartbeats.extend([
                {"task": "ingest", "timestamp": timestamp},
                {"task": "daily_curate", "timestamp": timestamp},
                {"task": "daily", "timestamp": timestamp},
            ])

        payload = WeeklyHealthReportBuilder().build(
            snapshots, heartbeats, week_start=date(2026, 7, 6), week_end=date(2026, 7, 12)
        )

        self.assertEqual(payload["card"]["header"]["template"], "green")

    def test_duplicate_runs_on_same_day_are_counted_once(self) -> None:
        timestamp = "2026-07-06T00:00:00+00:00"
        heartbeats = [{"task": "ingest", "timestamp": timestamp} for _ in range(5)]

        payload = WeeklyHealthReportBuilder().build(
            [], heartbeats, week_start=date(2026, 7, 6), week_end=date(2026, 7, 12)
        )

        content = payload["card"]["elements"][0]["text"]["content"]
        self.assertIn("新闻抓取：完成 1 天，缺少 6 天", content)
        self.assertNotIn("5/7", content)


if __name__ == "__main__":
    unittest.main()
