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
        self.assertTrue(any("summary 不是中文句子" in issue for issue in issues))
        self.assertTrue(any("evidence 1 不是中文" in issue for issue in issues))
        self.assertTrue(any("缺少原始链接" in issue for issue in issues))

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
        self.assertTrue(any("重复使用了同一条原始发言" in issue for issue in issues))

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
        self.assertTrue(any("Peter Steinberger 出现了 2 次" in issue for issue in issues))

    def test_empty_result_prefers_spotlight_text(self) -> None:
        aggregator = self._make_aggregator()
        payload = aggregator._empty_result(
            [
                {
                    "source": "Peter Steinberger",
                    "core_claim": "每次提交后自动审查并修复代码错误，最多循环5次。",
                    "spotlight_text": "Peter Steinberger 现在让 Codex 在每次提交后自动审查代码，发现问题就继续修，最多循环 5 次。",
                    "url": "https://x.com/test/1",
                }
            ]
        )
        self.assertEqual(
            payload["spotlight_posts"][0]["text"],
            "Peter Steinberger 现在让 Codex 在每次提交后自动审查代码，发现问题就继续修，最多循环 5 次。",
        )


if __name__ == "__main__":
    unittest.main()
