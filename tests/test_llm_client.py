import unittest
from datetime import datetime, timezone
from json import JSONDecodeError
from unittest.mock import Mock, patch

import requests

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient


class LLMClientValidationTest(unittest.TestCase):
    def test_chat_completion_retries_transient_network_errors(self) -> None:
        client = DeepSeekClient(
            api_key="key",
            base_url="https://example.com",
            timeout_seconds=30,
            retry_delays_seconds=(0, 0),
        )
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
        response.raise_for_status.return_value = None

        with patch(
            "src.utils.llm_client.requests.post",
            side_effect=[requests.exceptions.SSLError("eof"), response],
        ) as post_mock:
            with patch("src.utils.llm_client.time.sleep") as sleep_mock:
                result = client._chat_completion("prompt", model="deepseek-chat")

        self.assertEqual(result, "{}")
        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.0)

    def test_chat_completion_does_not_retry_auth_errors(self) -> None:
        client = DeepSeekClient(
            api_key="key",
            base_url="https://example.com",
            timeout_seconds=30,
            retry_delays_seconds=(0, 0),
        )
        response = Mock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=response)

        with patch("src.utils.llm_client.requests.post", return_value=response) as post_mock:
            with self.assertRaises(requests.exceptions.HTTPError):
                client._chat_completion("prompt", model="deepseek-chat")

        post_mock.assert_called_once()

    def test_chat_completion_json_retries_once_on_invalid_json(self) -> None:
        client = DeepSeekClient(api_key="key", base_url="https://example.com", timeout_seconds=30)

        with patch.object(
            client,
            "_chat_completion",
            side_effect=['{"signals": [', '{"signals": []}'],
        ) as chat_mock:
            payload = client._chat_completion_json("prompt", model="deepseek-chat", max_tokens=2200)

        self.assertEqual(payload, {"signals": []})
        self.assertEqual(chat_mock.call_count, 2)

    def test_chat_completion_json_raises_after_second_invalid_json(self) -> None:
        client = DeepSeekClient(api_key="key", base_url="https://example.com", timeout_seconds=30)

        with patch.object(
            client,
            "_chat_completion",
            side_effect=['{"signals": [', '{"signals": ['],
        ):
            with self.assertRaises(JSONDecodeError):
                client._chat_completion_json("prompt", model="deepseek-chat", max_tokens=2200)

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

    def test_daily_builder_hot_copy_prompt_formats_real_template(self) -> None:
        client = DeepSeekClient(api_key="key", base_url="https://example.com", timeout_seconds=30)
        item = ContentItem(
            content_id="zara_x_1",
            source_type="zara_x",
            source_name="zara_x",
            title="Builder post",
            url="https://x.com/example/status/1",
            author="Builder",
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
            body="Builder body",
            body_type="tweet",
            ai_summary="Builder summary",
        )

        with patch.object(client, "_chat_completion", return_value='{"signals": []}') as chat_mock:
            payload = client.daily_builder_hot_copy(
                "prompts/builder_hot_copy.md",
                [item],
                [{"content_id": "zara_x_1", "source": "Builder", "url": item.url, "topic_key": "Agent"}],
            )

        self.assertEqual(payload, {"signals": []})
        prompt = chat_mock.call_args.args[0]
        self.assertIn('"content_id": "zara_x_1"', prompt)
        self.assertIn('"author": "Builder"', prompt)

    def test_daily_report_prompt_templates_format_real_files(self) -> None:
        client = DeepSeekClient(api_key="key", base_url="https://example.com", timeout_seconds=30)
        builder_item = ContentItem(
            content_id="zara_x_1",
            source_type="zara_x",
            source_name="zara_x",
            title="Builder post",
            url="https://x.com/example/status/1",
            author="Builder",
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
            body="Builder body",
            body_type="tweet",
            ai_summary="Builder summary",
        )
        editorial_item = ContentItem(
            content_id="rss_1",
            source_type="rss",
            source_name="simon_willison",
            title="Editorial post",
            url="https://example.com/post",
            author="Simon Willison",
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
            body="Editorial body",
            body_type="article",
            ai_summary="Editorial summary",
        )

        with patch.object(client, "_chat_completion", return_value='{"themes": [], "discussion_dispersion": "dispersed"}') as chat_mock:
            client.daily_theme_decisions(
                "prompts/theme_decision.md",
                [builder_item],
                theme_signals=[{"content_id": "zara_x_1", "source": "Builder", "url": builder_item.url, "topic_key": "Agent"}],
            )
        self.assertIn('"theme_id": "theme_1"', chat_mock.call_args.args[0])

        with patch.object(client, "_chat_completion", return_value='{"themes": []}') as chat_mock:
            client.daily_theme_copy(
                "prompts/theme_copy.md",
                [builder_item],
                decided_themes=[{"theme_id": "theme_1", "member_content_ids": ["zara_x_1"]}],
                theme_signals=[{"content_id": "zara_x_1", "source": "Builder", "url": builder_item.url, "topic_key": "Agent"}],
            )
        self.assertIn('"evidence"', chat_mock.call_args.args[0])

        with patch.object(client, "_chat_completion", return_value='{"selections": []}') as chat_mock:
            client.daily_selection_decisions(
                "prompts/selection_decision.md",
                [editorial_item],
                set(),
            )
        self.assertIn('"candidate_index": 1', chat_mock.call_args.args[0])

        with patch.object(client, "_chat_completion", return_value='{"selections": [], "selection_diversity": ""}') as chat_mock:
            client.daily_selection_copy(
                "prompts/selection_copy.md",
                [editorial_item],
                [1],
                set(),
            )
        self.assertIn('"value_pitch": "..."', chat_mock.call_args.args[0])

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
