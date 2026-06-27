import unittest

from src.processing.daily_decision_resolver import DailyDecisionResolver


class DailyDecisionResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = DailyDecisionResolver()

    def test_resolver_excludes_theme_members_and_selections_from_supplementary(self) -> None:
        candidates, themes, selections = self.resolver.resolve(
            candidates_data={
                "editorial_top10": [
                    {
                        "content_id": "rss_theme",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "Theme item",
                        "url": "https://example.com/theme",
                        "summary": "theme summary",
                    },
                    {
                        "content_id": "rss_selected",
                        "type": "article",
                        "channel_or_source": "verge_ai",
                        "title": "Selected item",
                        "url": "https://example.com/selected",
                        "summary": "selected summary",
                    },
                    {
                        "content_id": "rss_extra",
                        "type": "article",
                        "channel_or_source": "techcrunch_ai",
                        "title": "Extra item",
                        "url": "https://example.com/extra",
                        "summary": "extra summary",
                    },
                ],
                "builder_hot_candidates": [
                    {
                        "decision": {"content_id": "zara_x_1", "url": "https://x.com/used", "source": "Aaron Levie"},
                        "copy": {"core_claim": "Used", "spotlight_text": "Used"},
                    },
                    {
                        "decision": {"content_id": "zara_x_2", "url": "https://x.com/free", "source": "Garry Tan"},
                        "copy": {"core_claim": "Free", "spotlight_text": "Free"},
                    },
                ],
            },
            themes_data={
                "themes": [
                    {
                        "decision": {"member_content_ids": ["rss_theme"]},
                        "copy": {
                            "theme_title": "Theme",
                            "theme_summary": "Theme summary",
                            "evidence": [{"source": "Aaron Levie", "excerpt": "used", "url": "https://x.com/used"}],
                        },
                    }
                ]
            },
            selections_data={
                "selections": [
                    {
                        "decision": {
                            "content_id": "rss_selected",
                            "selected": True,
                            "type": "article",
                            "channel_or_source": "verge_ai",
                            "title": "Selected item",
                            "url": "https://example.com/selected",
                        },
                        "copy": {"value_pitch": "pick"},
                    }
                ]
            },
        )

        del candidates
        del selections
        supplementary_ids = {item.get("content_id") for item in themes["supplementary_items"] if item.get("content_id")}
        supplementary_urls = {item.get("url") for item in themes["supplementary_items"]}
        self.assertEqual(supplementary_ids, {"rss_extra"})
        self.assertIn("https://x.com/free", supplementary_urls)
        self.assertNotIn("https://x.com/used", supplementary_urls)

    def test_resolver_dedupes_same_package_family_and_expands_source_caps(self) -> None:
        _, themes, _ = self.resolver.resolve(
            candidates_data={
                "editorial_top10": [
                    {
                        "content_id": "picked",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "Datasette Agent",
                        "url": "https://example.com/picked",
                        "summary": "picked summary",
                    },
                    {
                        "content_id": "variant",
                        "type": "article",
                        "channel_or_source": "simon_willison",
                        "title": "datasette-agent 0.1a3",
                        "url": "https://example.com/variant",
                        "summary": "variant summary",
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
                        "channel_or_source": "techcrunch_ai",
                        "title": "Extra 2",
                        "url": "https://example.com/extra2",
                        "summary": "extra2",
                    },
                    {
                        "content_id": "extra_3",
                        "type": "article",
                        "channel_or_source": "verge_ai",
                        "title": "Extra 3",
                        "url": "https://example.com/extra3",
                        "summary": "extra3",
                    },
                    {
                        "content_id": "extra_4",
                        "type": "article",
                        "channel_or_source": "hacker_news_ai",
                        "title": "Extra 4",
                        "url": "https://example.com/extra4",
                        "summary": "extra4",
                    },
                ]
            },
            themes_data={"themes": [], "spotlight_posts": []},
            selections_data={
                "selections": [
                    {
                        "decision": {
                            "content_id": "picked",
                            "selected": True,
                            "type": "article",
                            "channel_or_source": "simon_willison",
                            "title": "Datasette Agent",
                            "url": "https://example.com/picked",
                        },
                        "copy": {"value_pitch": "picked"},
                    }
                ]
            },
        )

        titles = [item.get("title") for item in themes["supplementary_items"]]
        self.assertNotIn("datasette-agent 0.1a3", titles)
        self.assertIn("Extra 2", titles)

    def test_resolver_does_not_emit_english_summary_for_supplementary(self) -> None:
        _, themes, _ = self.resolver.resolve(
            candidates_data={
                "editorial_top10": [
                    {
                        "content_id": "rss_extra",
                        "type": "article",
                        "channel_or_source": "TechCrunch AI",
                        "title": "Early Bird pricing ends tonight for TechCrunch Founder Summit",
                        "url": "https://example.com/extra",
                        "summary": "Tonight is your last chance to save up to $190 on your pass to TechCrunch Founder Summit 2026.",
                    }
                ]
            },
            themes_data={"themes": [], "spotlight_posts": []},
            selections_data={"selections": []},
        )

        self.assertEqual(len(themes["supplementary_items"]), 1)
        brief = themes["supplementary_items"][0]["brief"]
        self.assertIn("这条内容来自 TechCrunch AI", brief)
        self.assertNotIn("Tonight is your last chance", brief)

    def test_resolver_dedupes_duplicate_spotlight_posts(self) -> None:
        _, themes, _ = self.resolver.resolve(
            candidates_data={},
            themes_data={
                "themes": [
                    {
                        "decision": {"member_content_ids": ["zara_x_1"]},
                        "copy": {
                            "theme_title": "Theme",
                            "theme_summary": "Summary",
                            "evidence": [{"source": "Aaron Levie", "excerpt": "used", "url": "https://x.com/1"}],
                        },
                    }
                ],
                "spotlight_posts": [
                    {"source": "Aaron Levie", "text": "used", "url": "https://x.com/1"},
                    {"source": "Garry Tan", "text": "free", "url": "https://x.com/2"},
                    {"source": "Garry Tan", "text": "free again", "url": "https://x.com/2"},
                ],
            },
            selections_data={"selections": []},
        )

        self.assertEqual(themes["spotlight_posts"], [{"source": "Garry Tan", "text": "free", "url": "https://x.com/2"}])


if __name__ == "__main__":
    unittest.main()
