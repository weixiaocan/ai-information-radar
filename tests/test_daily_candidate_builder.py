import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.processing.daily_candidate_builder import DailyCandidateBuilder
from src.utils.daily_state import builder_candidate_copy, builder_candidate_decision


class DailyCandidateBuilderTest(unittest.TestCase):
    def test_builder_failure_still_returns_editorial_candidates(self) -> None:
        client = Mock()
        client.daily_builder_hot_decisions.side_effect = RuntimeError("deepseek unavailable")
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Builder post",
                url="https://x.com/1",
                author="Builder",
                published_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 21, 1, tzinfo=timezone.utc),
                body="Builder body",
                body_type="tweet",
            ),
            ContentItem(
                content_id="rss_1",
                source_type="rss",
                source_name="simon_willison",
                title="Editorial post",
                url="https://example.com/post",
                author="Simon Willison",
                published_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 21, 1, tzinfo=timezone.utc),
                body="Editorial body",
                body_type="article",
                ai_summary="Useful editorial summary",
            ),
        ]

        payload = builder.build(items)

        self.assertEqual(payload["builder_hot_candidates"], [])
        self.assertEqual(payload["editorial_candidates"][0]["content_id"], "rss_1")
        self.assertEqual(payload["degraded_reason"], "builder_decision_failed")
        self.assertEqual(payload["degraded_stage"], "builder_decision")

    def test_synthesize_signal_from_english_builder_post(self) -> None:
        client = Mock()
        client.daily_builder_hot_copy.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_2",
                    "source": "Zara Zhang",
                    "url": "https://x.com/zarazhangrui/status/2",
                    "topic_label": "AI 团队设计",
                    "core_claim": "这是中文核心观点",
                    "angle": "经验观察",
                    "excerpt": "这是中文摘录",
                    "spotlight_text": "这是中文聚光句",
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
        assert payload is not None
        self.assertEqual(builder_candidate_decision(payload)["source"], "Zara Zhang")
        self.assertEqual(builder_candidate_copy(payload)["spotlight_text"], "这是中文核心观点")

    def test_builder_copy_retries_until_spotlight_text_is_chinese(self) -> None:
        client = Mock()
        client.daily_builder_hot_decisions.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Zara Zhang",
                    "url": "https://x.com/zarazhangrui/status/1",
                    "topic_key": "AI 团队设计",
                }
            ]
        }
        client.daily_builder_hot_copy.side_effect = [
            {
                "signals": [
                    {
                        "content_id": "zara_x_1",
                        "source": "Zara Zhang",
                        "url": "https://x.com/zarazhangrui/status/1",
                        "topic_label": "AI-native team",
                        "core_claim": "I think that in an AI-native team",
                        "angle": "personal view",
                        "excerpt": "ICs should start thinking like managers",
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
                        "topic_label": "AI 团队设计",
                        "core_claim": "这是中文核心观点",
                        "angle": "经验观察",
                        "excerpt": "这是中文摘录",
                        "spotlight_text": "这是中文聚光句",
                    }
                ]
            },
        ]
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
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

        self.assertEqual(client.daily_builder_hot_copy.call_count, 2)
        self.assertEqual(builder_candidate_decision(payload["builder_hot_candidates"][0])["source"], "Zara Zhang")
        self.assertEqual(builder_candidate_copy(payload["builder_hot_candidates"][0])["spotlight_text"], "这是中文核心观点")

    def test_builder_signal_source_uses_authoritative_author_name(self) -> None:
        client = Mock()
        client.daily_builder_hot_decisions.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "X",
                    "url": "https://x.com/garrytan/status/1",
                    "topic_key": "GBrain 发布",
                }
            ]
        }
        client.daily_builder_hot_copy.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "X",
                    "url": "https://x.com/garrytan/status/1",
                    "topic_label": "GBrain 发布",
                    "core_claim": "这是中文核心观点",
                    "angle": "产品发布",
                    "excerpt": "这是中文摘录",
                    "spotlight_text": "这是中文聚光句",
                }
            ]
        }
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
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
                body="GBrain launch update.",
                body_type="tweet",
                ai_summary="GBrain launch update.",
            )
        ]

        payload = builder.build(items)

        self.assertEqual(builder_candidate_decision(payload["builder_hot_candidates"][0])["source"], "Garry Tan")

    def test_builder_uses_structured_chinese_fallback_when_copy_generation_stays_invalid(self) -> None:
        client = Mock()
        client.daily_builder_hot_decisions.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Aaron Levie",
                    "url": "https://x.com/1",
                    "topic_key": "Agent 工程岗位",
                }
            ]
        }
        client.daily_builder_hot_copy.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Aaron Levie",
                    "url": "https://x.com/1",
                    "topic_label": "",
                    "core_claim": "",
                    "angle": "",
                    "excerpt": "",
                    "spotlight_text": "",
                }
            ]
        }
        builder = DailyCandidateBuilder(client, Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Agent hiring",
                url="https://x.com/1",
                author="Aaron Levie",
                published_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 5, 1, tzinfo=timezone.utc),
                body="Companies will need internal agent engineers.",
                body_type="tweet",
                ai_summary="Companies will need internal agent engineers.",
            )
        ]

        payload = builder.build(items)

        candidate = payload["builder_hot_candidates"][0]
        self.assertEqual(builder_candidate_decision(candidate)["content_id"], "zara_x_1")
        self.assertIn("相关的具体项目或实践", builder_candidate_copy(candidate)["spotlight_text"])
        self.assertFalse(builder._looks_mostly_english(builder_candidate_copy(candidate)["spotlight_text"]))
        self.assertEqual(candidate["degraded_stage"], "builder_copy")
        self.assertEqual(payload["degraded_stage"], "builder_copy")


if __name__ == "__main__":
    unittest.main()
