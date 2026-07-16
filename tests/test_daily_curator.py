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

    def test_selection_copy_retries_when_value_pitch_is_english(self) -> None:
        client = Mock()
        client.daily_selection_decisions.return_value = {
            "selections": [{"candidate_index": 1}],
        }
        client.daily_selection_copy.side_effect = [
            {
                "selections": [{"candidate_index": 1, "value_pitch": "This article explains why agent harnesses matter."}],
                "selection_diversity": "English diversity text",
            },
            {
                "selections": [{"candidate_index": 1, "value_pitch": "这篇文章解释了为什么 agent harness 会影响工程落地"}],
                "selection_diversity": "这组精选覆盖了工程实践。",
            },
        ]
        curator = DailyCurator(client, Path("prompts/selection_decision.md"), Path("prompts/selection_copy.md"))
        candidate_items = [
            ContentItem(
                content_id="rss_1",
                source_type="rss",
                source_name="simon_willison",
                title="Agent harnesses",
                url="https://example.com/story",
                author="Simon",
                published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
                ai_summary="Agent harnesses help teams ship reliable agent workflows.",
            )
        ]

        payload = curator.curate_daily(candidate_items, set())

        self.assertEqual(client.daily_selection_copy.call_count, 2)
        self.assertEqual(selection_copy(payload["selections"][0])["value_pitch"], "这篇文章解释了为什么 agent harness 会影响工程落地")
        self.assertFalse(payload["selections"][0]["degraded_stage"])

    def test_selection_copy_fallback_does_not_emit_english_summary(self) -> None:
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
                title="Agent harnesses",
                url="https://example.com/story",
                author="Simon",
                published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
                ai_summary="Agent harnesses help teams ship reliable agent workflows.",
            )
        ]

        payload = curator.curate_daily(candidate_items, set())

        value_pitch = selection_copy(payload["selections"][0])["value_pitch"]
        self.assertEqual(value_pitch, "simon_willison 这条内容可作为今日精选参考")
        self.assertNotIn("Agent harnesses help", value_pitch)

    def test_selection_copy_preserves_complete_ai_value_pitch_without_numeric_truncation(self) -> None:
        client = Mock()
        long_pitch = "这是一条由模型生成的完整推荐语，" * 10 + "结尾信息必须保留。"
        client.daily_selection_decisions.return_value = {"selections": [{"candidate_index": 1}]}
        client.daily_selection_copy.return_value = {
            "selections": [{"candidate_index": 1, "value_pitch": long_pitch}],
            "selection_diversity": "覆盖多个方向。",
        }
        curator = DailyCurator(client, Path("prompts/selection_decision.md"), Path("prompts/selection_copy.md"))
        item = ContentItem(
            content_id="rss_1",
            source_type="rss",
            source_name="source",
            title="标题",
            url="https://example.com/story",
            author=None,
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
            body="正文",
            body_type="article",
            ai_summary="完整摘要。",
        )

        payload = curator.curate_daily([item], set())

        self.assertEqual(selection_copy(payload["selections"][0])["value_pitch"], long_pitch)


if __name__ == "__main__":
    unittest.main()
