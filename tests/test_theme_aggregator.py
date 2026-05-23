import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.processing.theme_aggregator import ThemeAggregator


class ThemeAggregatorValidationTest(unittest.TestCase):
    def _make_aggregator(self) -> ThemeAggregator:
        return ThemeAggregator(
            client=Mock(),
            prompt_path=Path("prompts/theme_decision.md"),
            copy_prompt_path=Path("prompts/theme_copy.md"),
        )

    def test_collect_issues_flags_english_excerpt_and_missing_url(self) -> None:
        aggregator = self._make_aggregator()
        issues = aggregator._collect_issues(
            {
                "themes": [
                    {
                        "summary": "A long English sentence that should not pass validation here.",
                        "evidence": [
                            {
                                "source": "X",
                                "excerpt": "microsoft will remain our primary cloud partner across all clouds",
                                "url": "",
                            }
                        ],
                    }
                ]
            }
        )
        self.assertTrue(any("summary must be written in Chinese" in issue for issue in issues))
        self.assertTrue(any("evidence 1 must be written in Chinese" in issue for issue in issues))
        self.assertTrue(any("missing the original url" in issue for issue in issues))

    def test_collect_issues_flags_cross_theme_duplicate_url(self) -> None:
        aggregator = self._make_aggregator()
        issues = aggregator._collect_issues(
            {
                "themes": [
                    {
                        "summary": "这是中文总结",
                        "evidence": [
                            {"source": "A", "excerpt": "这是中文事实一", "url": "https://x.com/1"},
                            {"source": "B", "excerpt": "这是中文事实二", "url": "https://x.com/2"},
                            {"source": "C", "excerpt": "这是中文事实三", "url": "https://x.com/3"},
                        ],
                    },
                    {
                        "summary": "这是第二个中文总结",
                        "evidence": [
                            {"source": "D", "excerpt": "这是中文事实四", "url": "https://x.com/1"},
                        ],
                    },
                ]
            }
        )
        self.assertTrue(any("reuses a post already used by theme 1" in issue for issue in issues))

    def test_collect_issues_flags_same_source_reuse_within_theme(self) -> None:
        aggregator = self._make_aggregator()
        issues = aggregator._collect_issues(
            {
                "themes": [
                    {
                        "summary": "这是中文总结",
                        "evidence": [
                            {"source": "Peter Steinberger", "excerpt": "中文事实一", "url": "https://x.com/a"},
                            {"source": "Peter Steinberger", "excerpt": "中文事实二", "url": "https://x.com/b"},
                            {"source": "Aaron Levie", "excerpt": "中文事实三", "url": "https://x.com/c"},
                        ],
                    }
                ]
            }
        )
        self.assertTrue(any("repeats source Peter Steinberger 2 times" in issue for issue in issues))

    def test_collect_issues_flags_summary_that_repeats_evidence(self) -> None:
        aggregator = self._make_aggregator()
        issues = aggregator._collect_issues(
            {
                "themes": [
                    {
                        "summary": "Aaron Levie 指出 AI 从廉价聊天工具发展到昂贵代理，推理成本明显上升。",
                        "evidence": [
                            {
                                "source": "Aaron Levie",
                                "excerpt": "Aaron Levie 说 AI 从廉价聊天工具发展到具有大上下文窗口的代理，推理成本大幅上升。",
                                "url": "https://x.com/1",
                            },
                            {
                                "source": "Garry Tan",
                                "excerpt": "Garry Tan 提到每个人都应该拥有一个带 GBrain 的智能体。",
                                "url": "https://x.com/2",
                            },
                            {
                                "source": "Zara Zhang",
                                "excerpt": "该工具允许用户在飞书里像同事一样与 Claude Code 对话。",
                                "url": "https://x.com/3",
                            },
                        ],
                    }
                ]
            }
        )
        self.assertTrue(any("summary is too similar to evidence 1" in issue for issue in issues))

    def test_empty_result_prefers_spotlight_text(self) -> None:
        aggregator = self._make_aggregator()
        payload = aggregator._empty_result(
            [
                {
                    "source": "Peter Steinberger",
                    "core_claim": "每次提交后自动审查并修复代码错误",
                    "spotlight_text": "Peter Steinberger 现在让 Codex 在每次提交后自动审查代码，发现问题就继续修。",
                    "url": "https://x.com/test/1",
                }
            ]
        )
        self.assertEqual(payload["themes"], [])
        self.assertEqual(payload["discussion_dispersion"], "dispersed")
        self.assertEqual(
            payload["spotlight_posts"][0]["text"],
            "Peter Steinberger 现在让 Codex 在每次提交后自动审查代码，发现问题就继续修。",
        )

    def test_empty_result_rewrites_generic_x_source_from_url_mapping(self) -> None:
        aggregator = self._make_aggregator()
        payload = aggregator._empty_result(
            [
                {
                    "content_id": "zara_x_1",
                    "source": "X",
                    "core_claim": "GBrain 发布了新版本",
                    "spotlight_text": "GBrain 发布了新版本",
                    "url": "https://x.com/garrytan/status/1",
                }
            ],
            source_by_url={"https://x.com/garrytan/status/1": "Garry Tan"},
            source_by_content_id={"zara_x_1": "Garry Tan"},
        )
        self.assertEqual(payload["spotlight_posts"][0]["source"], "Garry Tan")

    def test_theme_membership_is_preserved_when_copy_generation_fails(self) -> None:
        client = Mock()
        client.daily_theme_decisions.return_value = {
            "discussion_dispersion": "moderate",
            "themes": [
                {
                    "theme_id": "theme_1",
                    "member_content_ids": ["zara_x_1", "zara_x_2", "zara_x_3"],
                }
            ],
        }
        client.daily_theme_copy.return_value = {
            "themes": [
                {
                    "theme_id": "theme_1",
                    "theme_title": "",
                    "theme_summary": "",
                    "evidence": [],
                }
            ]
        }
        aggregator = ThemeAggregator(client, Path("prompts/theme_decision.md"), Path("prompts/theme_copy.md"))
        items = [
            ContentItem(
                content_id=f"zara_x_{index}",
                source_type="zara_x",
                source_name="zara_x",
                title=f"Builder post {index}",
                url=f"https://x.com/{index}",
                author=f"Builder {index}",
                published_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 5, 1, tzinfo=timezone.utc),
                body=f"Body {index}",
                body_type="tweet",
                ai_summary=f"Summary {index}",
            )
            for index in range(1, 4)
        ]
        signals = [
            {
                "decision": {"content_id": f"zara_x_{index}", "source": f"Builder {index}", "url": f"https://x.com/{index}"},
                "copy": {
                    "topic_label": "Agent 工程",
                    "core_claim": f"Summary {index}",
                    "angle": "经验观察",
                    "excerpt": f"Summary {index}",
                    "spotlight_text": f"Summary {index}",
                },
            }
            for index in range(1, 4)
        ]

        payload = aggregator.aggregate_themes(items, signals)

        self.assertEqual(payload["themes"][0]["decision"]["member_content_ids"], ["zara_x_1", "zara_x_2", "zara_x_3"])
        self.assertTrue(payload["themes"][0]["copy"]["theme_title"])
        self.assertTrue(payload["themes"][0]["copy"]["evidence"])
        self.assertEqual(payload["themes"][0]["degraded_stage"], "theme_copy")
        self.assertEqual(payload["themes"][0]["fallback_mode"], "copy_from_member_signals")
        self.assertEqual(payload["degraded_stage"], "theme_copy")


if __name__ == "__main__":
    unittest.main()
