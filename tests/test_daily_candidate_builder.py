import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.processing.daily_candidate_builder import DailyCandidateBuilder


class DailyCandidateBuilderTest(unittest.TestCase):
    def test_synthesize_signal_from_english_builder_post(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_2",
                    "source": "Zara Zhang",
                    "url": "https://x.com/zarazhangrui/status/2",
                    "topic_label": "AI 原生团队分工",
                    "core_claim": "她认为 AI 原生团队里，IC 要像管理者一样分派任务给 agent。",
                    "angle": "涓汉浣撻獙",
                    "excerpt": "她提出 IC 要学会给 agent 分派任务、设标准并验证输出。",
                    "spotlight_text": "她提出 AI 原生团队里，IC 要像管理者一样分派任务给 agent 并验证结果。",
                }
            ]
        }
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        item = ContentItem(
            content_id="zara_x_2",
            source_type="zara_x",
            source_name="zara_x",
            title="Zara Zhang post",
            url="https://x.com/zarazhangrui/status/2",
            author="Zara Zhang",
            published_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 21, 1, tzinfo=timezone.utc),
            body="I think that in an AI-native team, ICs should start thinking like managers...",
            body_type="tweet",
            ai_summary="I think that in an AI-native team, ICs should start thinking like managers...",
        )

        payload = builder._synthesize_signal_from_item(item)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["source"], "Zara Zhang")
        self.assertIn("AI 鍘熺敓鍥㈤槦", payload["spotlight_text"])

    def test_builder_signal_retries_until_spotlight_text_is_chinese(self) -> None:
        client = Mock()
        client.daily_theme_signals.side_effect = [
            {
                "signals": [
                    {
                        "content_id": "zara_x_1",
                        "source": "Zara Zhang",
                        "url": "https://x.com/zarazhangrui/status/1",
                        "topic_label": "AI-native team",
                        "core_claim": "I think that in an AI-native team,",
                        "angle": "个人体验",
                        "excerpt": "ICs should start thinking like managers: how to delegate...",
                        "spotlight_text": "Great slide from the session...",
                    }
                ]
            },
            {
                "signals": [
                    {
                        "content_id": "zara_x_1",
                        "source": "Zara Zhang",
                        "url": "https://x.com/zarazhangrui/status/1",
                        "topic_label": "AI 原生团队分工",
                        "core_claim": "她认为 AI 原生团队里，IC 要像管理者一样分派任务给 agent。",
                        "angle": "个人体验",
                        "excerpt": "她提出 IC 要学会给 agent 分派任务、设标准并验证输出。",
                        "spotlight_text": "她提出 AI 原生团队里，IC 要像管理者一样分派任务给 agent 并验证结果。",
                    }
                ]
            },
        ]
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Zara Zhang post",
                url="https://x.com/zarazhangrui/status/1",
                author="Zara Zhang",
                published_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 21, 1, tzinfo=timezone.utc),
                body="I think that in an AI-native team, ICs should start thinking like managers...",
                body_type="tweet",
                ai_summary="I think that in an AI-native team, ICs should start thinking like managers...",
            )
        ]

        payload = builder.build(items)

        self.assertEqual(client.daily_theme_signals.call_count, 3)
        self.assertEqual(payload["builder_hot_candidates"][0]["source"], "Zara Zhang")
        self.assertIn("AI 原生团队", payload["builder_hot_candidates"][0]["spotlight_text"])

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
