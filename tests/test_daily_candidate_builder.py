import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.processing.daily_candidate_builder import DailyCandidateBuilder


class DailyCandidateBuilderTest(unittest.TestCase):
    def test_builder_signal_source_uses_authoritative_author_name(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "X",
                    "url": "https://x.com/garrytan/status/1",
                    "topic_label": "GBrain",
                    "core_claim": "GBrain 发布了新版本并扩展模型支持",
                    "angle": "产品发布",
                    "excerpt": "GBrain 发布了新版本并扩展模型支持，包含更完整的嵌入与工具能力",
                    "spotlight_text": "GBrain 发布了新版本并扩展模型支持",
                }
            ]
        }
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="garry_tan",
                title="garry_tan: GBrain update",
                url="https://x.com/garrytan/status/1",
                author="Garry Tan",
                published_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 5, 1, tzinfo=timezone.utc),
                body="GBrain 发布了新版本并扩展模型支持，包含更完整的嵌入与工具能力。",
                body_type="tweet",
                ai_summary="GBrain 发布了新版本并扩展模型支持",
            )
        ]

        payload = builder.build(items)

        self.assertEqual(payload["builder_hot_candidates"][0]["source"], "Garry Tan")


if __name__ == "__main__":
    unittest.main()
