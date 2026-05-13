import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient


class LLMClientValidationTest(unittest.TestCase):
    def test_daily_selections_includes_candidate_index_in_prompt(self) -> None:
        client = DeepSeekClient(api_key="key", base_url="https://example.com", timeout_seconds=30)
        item = ContentItem(
            content_id="rss_1",
            source_type="rss",
            source_name="simon_willison",
            title="A story",
            url="https://example.com/story",
            author="Simon Willison",
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
            body="Body",
            body_type="article",
            ai_summary="Summary",
            ai_keywords=["llm"],
        )

        with patch("src.utils.llm_client.load_prompt", return_value="{candidates_json}") as load_prompt_mock:
            with patch.object(client, "_chat_completion", return_value='{"selections": [], "selection_diversity": ""}') as chat_mock:
                client.daily_selections("prompts/daily_curator.md", [item], set())

        load_prompt_mock.assert_called_once()
        prompt = chat_mock.call_args.args[0]
        self.assertIn('"candidate_index": 1', prompt)
        self.assertNotIn('"content_id": "rss_1"', prompt)

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
