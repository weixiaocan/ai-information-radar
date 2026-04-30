import unittest

from src.utils.llm_client import DeepSeekClient


class LLMClientValidationTest(unittest.TestCase):
    def test_collect_weekly_pitch_issues_flags_english_and_missing_structure(self) -> None:
        client = DeepSeekClient(api_key="", base_url="", timeout_seconds=30)
        issues = client._collect_weekly_pitch_issues(
            "Evan Spiegel explains why distribution matters more than product moats in AI."
        )
        self.assertTrue(any("不是中文" in issue for issue in issues))
        self.assertTrue(any("bullets" in issue for issue in issues))
        self.assertTrue(any("三段结构" in issue for issue in issues))

    def test_collect_weekly_theme_issues_flags_missing_fields(self) -> None:
        client = DeepSeekClient(api_key="", base_url="", timeout_seconds=30)
        issues = client._collect_weekly_theme_issues(
            {
                "themes": [
                    {
                        "title": "Theme 1",
                        "summary": "This summary is still in English and should fail validation.",
                        "highlights": [{"title": "A", "url": "", "source_name": "", "type": "podcast"}],
                    },
                    {"title": "", "summary": "", "highlights": []},
                ]
            }
        )
        self.assertTrue(any("themes 数量必须" in issue for issue in issues))
        self.assertTrue(any("summary 不是中文" in issue for issue in issues))
        self.assertTrue(any("highlights 数量必须" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
