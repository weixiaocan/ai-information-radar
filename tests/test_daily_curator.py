import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.processing.daily_curator import DailyCurator
from src.utils.daily_state import selection_copy, selection_decision


class DailyCuratorTest(unittest.TestCase):
    def test_selection_is_preserved_when_copy_generation_fails(self) -> None:
        client = Mock()
        client.daily_selection_decisions.return_value = {
            "selections": [{"candidate_index": 1}],
        }
        client.daily_selection_copy.return_value = {
            "selections": [{"candidate_index": 1, "value_pitch": ""}],
            "selection_diversity": "",
        }
        curator = DailyCurator(client, Path("prompts/selection_decision.md"), Path("prompts/selection_copy.md"))
        candidate_items = [
            ContentItem(
                content_id="rss_1",
                source_type="rss",
                source_name="simon_willison",
                title="A story",
                url="https://example.com/story",
                author="Simon",
                published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
                ai_summary="Summary",
            )
        ]

        payload = curator.curate_daily(candidate_items, set())

        self.assertEqual(selection_decision(payload["selections"][0])["content_id"], "rss_1")
        self.assertTrue(selection_copy(payload["selections"][0])["value_pitch"])
        self.assertEqual(payload["selections"][0]["degraded_stage"], "selection_copy")
        self.assertEqual(payload["degraded_stage"], "selection_copy")


if __name__ == "__main__":
    unittest.main()
