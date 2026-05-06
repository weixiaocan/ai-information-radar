import unittest
from pathlib import Path

from src.processing.theme_aggregator import ThemeAggregator


class ThemeAggregatorValidationTest(unittest.TestCase):
    def _make_aggregator(self) -> ThemeAggregator:
        return ThemeAggregator(
            client=None,  # type: ignore[arg-type]
            prompt_path=Path("prompts/theme_aggregator.md"),
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

    def test_empty_result_prefers_spotlight_text(self) -> None:
        aggregator = self._make_aggregator()
        payload = aggregator._empty_result(
            [
                {
                    "source": "Peter Steinberger",
                    "core_claim": "每次提交后自动审查并修复代码错误",
                    "spotlight_text": "Peter Steinberger 现在让 Codex 在每次提交后自动审查代码，发现问题就继续修",
                    "url": "https://x.com/test/1",
                }
            ]
        )
        self.assertEqual(payload["themes"], [])
        self.assertEqual(payload["discussion_dispersion"], "dispersed")
        self.assertEqual(
            payload["spotlight_posts"][0]["text"],
            "Peter Steinberger 现在让 Codex 在每次提交后自动审查代码，发现问题就继续修",
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


if __name__ == "__main__":
    unittest.main()
