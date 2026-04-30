import unittest

from src.output.daily_digest import DailyDigestBuilder


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

    def test_daily_digest_shows_supplementary_candidates_without_selected_sources(self) -> None:
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
        self.assertFalse(any("should be deduped" in text for text in card_texts))

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


if __name__ == "__main__":
    unittest.main()
