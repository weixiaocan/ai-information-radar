import unittest
from datetime import date

from src.output.health_report import WeeklyHealthReportBuilder


class WeeklyHealthReportBuilderTest(unittest.TestCase):
    def test_report_surfaces_failed_and_degraded_sources(self) -> None:
        snapshots = [
            {
                "sources": {
                    "rss:verge_ai": {"status": "feed_failed", "error": "403 Forbidden"},
                    "rss:hacker_news_ai": {"status": "success_with_article_fallbacks", "error": ""},
                    "youtube:latent_space": {"status": "no_new_items", "error": ""},
                }
            }
        ]
        heartbeats = []
        for _ in range(7):
            heartbeats.extend([{"task": "ingest"}, {"task": "daily_curate"}, {"task": "daily"}])

        payload = WeeklyHealthReportBuilder().build(
            snapshots, heartbeats, week_start=date(2026, 7, 6), week_end=date(2026, 7, 12)
        )

        self.assertEqual(payload["card"]["header"]["template"], "red")
        content = "\n".join(
            element.get("text", {}).get("content", "") for element in payload["card"]["elements"]
        )
        self.assertIn("rss:verge_ai", content)
        self.assertIn("403 Forbidden", content)
        self.assertIn("rss:hacker_news_ai", content)
        self.assertNotIn("youtube:latent_space", content)

    def test_report_is_green_when_all_runs_and_sources_are_healthy(self) -> None:
        snapshots = [{"sources": {"rss:verge_ai": {"status": "success", "error": ""}}} for _ in range(7)]
        heartbeats = []
        for _ in range(7):
            heartbeats.extend([{"task": "ingest"}, {"task": "daily_curate"}, {"task": "daily"}])

        payload = WeeklyHealthReportBuilder().build(
            snapshots, heartbeats, week_start=date(2026, 7, 6), week_end=date(2026, 7, 12)
        )

        self.assertEqual(payload["card"]["header"]["template"], "green")


if __name__ == "__main__":
    unittest.main()
