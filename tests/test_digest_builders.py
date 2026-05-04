import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.output.daily_digest import DailyDigestBuilder
from src.output.weekly_digest import WeeklyDigestBuilder


class DailyDigestBuilderTest(unittest.TestCase):
    def test_daily_digest_contains_theme_and_selection(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={
                "themes": [
                    {
                        "theme": "浏览器代理成为入口",
                        "summary": "Builder 在讨论让 agent 用浏览器执行真实操作",
                        "evidence": [
                            {
                                "source": "Simon",
                                "excerpt": "浏览器比 API 覆盖面更广",
                                "url": "https://example.com/evidence",
                            }
                        ],
                    }
                ]
            },
            selections_data={
                "selections": [
                    {
                        "content_id": "rss_1",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "A story",
                        "url": "https://example.com",
                        "value_pitch": "Simon 写了他如何亲手评估这次模型更新的实际表现",
                    }
                ]
            },
            stats={"total": 6},
        )
        theme_text = payload["card"]["elements"][1]["text"]["content"]
        selection_text = payload["card"]["elements"][4]["text"]["content"]
        note_text = payload["card"]["elements"][6]["elements"][0]["content"]
        self.assertIn("[**Simon**](https://example.com/evidence)", theme_text)
        self.assertIn("**Simon Willison**", selection_text)
        self.assertIn("Simon 写了他如何亲手评估这次模型更新的实际表现", selection_text)
        self.assertIn("今日抓取 6 条", note_text)

    def test_daily_digest_header_uses_target_content_date(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={"themes": [], "spotlight_posts": []},
            selections_data={"selections": []},
            stats={"total": 0},
            target_date=date(2026, 4, 30),
        )
        header_text = payload["card"]["header"]["title"]["content"]
        self.assertEqual(header_text, "📡 AI Radar · 2026-04-30 日报 · 周四")

    def test_daily_digest_falls_back_to_spotlight_posts(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={
                "themes": [],
                "spotlight_posts": [
                    {
                        "source": "Aaron Levie",
                        "text": "AI 代理不会减少软件工作，反而会创造更多技术机会",
                        "url": "https://x.com/levie/status/1",
                    }
                ],
            },
            selections_data={"selections": []},
            stats={"total": 3},
        )
        spotlight_header = payload["card"]["elements"][0]["text"]["content"]
        spotlight_line = payload["card"]["elements"][1]["text"]["content"]
        self.assertIn("值得看的 1 条 builder 帖子", spotlight_header)
        self.assertIn("[**Aaron Levie**](https://x.com/levie/status/1)", spotlight_line)

    def test_fallback_display_name_title_cases_source_name(self) -> None:
        builder = DailyDigestBuilder()
        self.assertEqual(builder._fallback_display_name("foo_bar_baz"), "Foo Bar Baz")

    def test_selection_value_pitch_strips_terminal_punctuation(self) -> None:
        builder = DailyDigestBuilder()
        content = builder._render_selection_block(
            {
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "A story",
                "url": "https://example.com",
                "value_pitch": "Simon 把 LLM 工具重构成了消息驱动的结构。",
            }
        )
        self.assertIn("Simon 把 LLM 工具重构成了消息驱动的结构", content)
        self.assertNotIn("结构。", content)

    def test_daily_digest_shows_supplementary_candidates_without_selected_items(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={"themes": [], "spotlight_posts": []},
            selections_data={
                "selections": [
                    {
                        "content_id": "youtube_1",
                        "type": "youtube",
                        "channel_or_source": "dwarkesh_patel",
                        "title": "Top pick",
                        "url": "https://example.com/top",
                        "value_pitch": "Top pick",
                    }
                ]
            },
            stats={"total": 8},
            candidates_data={
                "builder_hot_candidates": [],
                "editorial_candidates": [
                    {
                        "content_id": "youtube_1",
                        "type": "youtube",
                        "channel_or_source": "dwarkesh_patel",
                        "title": "Top pick",
                        "url": "https://example.com/top",
                        "summary": "should be hidden",
                    },
                    {
                        "content_id": "rss_2",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "Another story",
                        "url": "https://example.com/another",
                        "summary": "Simon 的补充候选",
                    },
                    {
                        "content_id": "rss_3",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "Duplicate source",
                        "url": "https://example.com/duplicate",
                        "summary": "should be deduped",
                    },
                ],
            },
        )
        card_texts = [
            element.get("text", {}).get("content", "")
            for element in payload["card"]["elements"]
            if element.get("tag") == "div"
        ]
        self.assertTrue(any("补充候选" in text for text in card_texts))
        self.assertTrue(any("Simon 的补充候选" in text for text in card_texts))
        self.assertFalse(any("should be hidden" in text for text in card_texts))
        self.assertTrue(any("should be deduped" in text for text in card_texts))

    def test_supplementary_candidates_render_in_one_line(self) -> None:
        builder = DailyDigestBuilder()
        line = builder._render_supplementary_line(
            {
                "type": "article",
                "source_name": "simon_willison",
                "title": "Another story",
                "url": "https://example.com/another",
                "brief": "Simon 的补充候选",
            }
        )
        self.assertIn("**Simon Willison** · [Another story](https://example.com/another) · Simon 的补充候选", line)
        self.assertNotIn("\n", line)

    def test_supplementary_candidates_can_expand_to_second_item_from_same_source(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={"themes": [], "spotlight_posts": []},
            selections_data={
                "selections": [
                    {
                        "content_id": "picked_1",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "Picked",
                        "url": "https://example.com/picked",
                        "value_pitch": "picked",
                    }
                ]
            },
            stats={"total": 10},
            candidates_data={
                "editorial_top10": [
                    {
                        "content_id": "picked_1",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "Picked",
                        "url": "https://example.com/picked",
                        "summary": "picked",
                    },
                    {
                        "content_id": "extra_1",
                        "type": "article",
                        "channel_or_source": "techcrunch_ai",
                        "title": "Extra 1",
                        "url": "https://example.com/extra1",
                        "summary": "extra1",
                    },
                    {
                        "content_id": "extra_2",
                        "type": "article",
                        "channel_or_source": "verge_ai",
                        "title": "Extra 2",
                        "url": "https://example.com/extra2",
                        "summary": "extra2",
                    },
                    {
                        "content_id": "extra_3",
                        "type": "article",
                        "channel_or_source": "hacker_news_ai",
                        "title": "Extra 3",
                        "url": "https://example.com/extra3",
                        "summary": "extra3",
                    },
                    {
                        "content_id": "extra_4",
                        "type": "article",
                        "channel_or_source": "techcrunch_ai",
                        "title": "Extra 4",
                        "url": "https://example.com/extra4",
                        "summary": "extra4",
                    },
                ]
            },
        )
        card_texts = [
            element.get("text", {}).get("content", "")
            for element in payload["card"]["elements"]
            if element.get("tag") == "div"
        ]
        supplementary_lines = [text for text in card_texts if "· [" in text]
        self.assertTrue(any("Extra 4" in text for text in supplementary_lines))

    def test_builder_candidates_move_to_supplementary_when_no_themes(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={"themes": [], "spotlight_posts": []},
            selections_data={"selections": []},
            stats={"total": 4},
            candidates_data={
                "builder_hot_candidates": [
                    {
                        "content_id": "zara_x_1",
                        "source": "Aaron Levie",
                        "url": "https://x.com/levie/status/1",
                        "core_claim": "AI 代理不会减少软件工作",
                        "spotlight_text": "Aaron Levie 认为 AI 代理不会减少软件工作",
                    }
                ],
                "editorial_top10": [],
            },
        )
        card_texts = [
            element.get("text", {}).get("content", "")
            for element in payload["card"]["elements"]
            if element.get("tag") == "div"
        ]
        self.assertTrue(any("补充候选" in text for text in card_texts))
        self.assertTrue(any("Aaron Levie" in text for text in card_texts))


class WeeklyDigestBuilderTest(unittest.TestCase):
    def test_weekly_digest_uses_original_source_names_for_historical_zara_items(self) -> None:
        client = Mock()
        client.weekly_themes.return_value = {
            "themes": [
                {
                    "title": "Claude ecosystem",
                    "summary": "Theme summary",
                    "highlights": [
                        {
                            "title": "Built-in memory for Claude Managed Agents",
                            "url": "https://claude.com/blog/memory",
                            "source_name": "Anthropic Engineering",
                            "type": "article",
                        }
                    ],
                }
            ]
        }
        client.weekly_pitch.return_value = "pitch"
        builder = WeeklyDigestBuilder(client, "prompts/weekly_pitch.md", "prompts/weekly_themes.md")
        items = [
            ContentItem(
                content_id="zara_blog_1",
                source_type="zara_blog",
                source_name="zara_blog",
                title="Built-in memory for Claude Managed Agents",
                url="https://claude.com/blog/memory",
                author=None,
                published_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 3, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
                ai_summary="Summary",
                extra_metadata={"raw_entry": {"name": "Anthropic Engineering"}},
            )
        ]

        markdown = builder.render_markdown(items)

        self.assertIn("`Anthropic Engineering`", markdown)

    def test_weekly_digest_top_section_uses_playlist_display_name(self) -> None:
        client = Mock()
        client.weekly_themes.return_value = {"themes": []}
        client.weekly_pitch.return_value = "pitch"
        builder = WeeklyDigestBuilder(client, "prompts/weekly_pitch.md", "prompts/weekly_themes.md")
        items = [
            ContentItem(
                content_id="youtube_1",
                source_type="youtube",
                source_name="training_data",
                title="Inference cloud",
                url="https://youtube.com/watch?v=1",
                author="Host",
                published_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 3, 1, tzinfo=timezone.utc),
                body="Transcript",
                body_type="transcript",
                ai_score={
                    "relevance": 8,
                    "contrarian": 8,
                    "guest_rarity": 8,
                    "popularity": 8,
                },
            )
        ]

        markdown = builder.render_markdown(items)

        self.assertIn("**Training Data**", markdown)


if __name__ == "__main__":
    unittest.main()
