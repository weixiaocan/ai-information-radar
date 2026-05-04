import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.pipeline import compute_x_mentions, select_top_candidates
from src.processing.daily_candidate_builder import DailyCandidateBuilder
from src.processing.daily_curator import DailyCurator
from src.processing.theme_aggregator import ThemeAggregator
from src.storage.state_manager import StateManager
from src.pipeline import Pipeline


class PipelineHelpersTest(unittest.TestCase):
    def test_resolve_daily_target_date_prefers_previous_local_day(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.load_available_dates.return_value = []
        items = [
            ContentItem(
                content_id="rss_1",
                source_type="rss",
                source_name="simon_willison",
                title="Day 1",
                url="https://example.com/1",
                author="Simon",
                published_at=datetime(2026, 4, 30, 12, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 13, tzinfo=timezone.utc),
                body="Day 1 body",
                body_type="article",
            ),
            ContentItem(
                content_id="rss_2",
                source_type="rss",
                source_name="simon_willison",
                title="Day 2",
                url="https://example.com/2",
                author="Simon",
                published_at=datetime(2026, 5, 1, 12, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 1, 13, tzinfo=timezone.utc),
                body="Day 2 body",
                body_type="article",
            ),
        ]
        from unittest.mock import patch

        with patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            resolved = Pipeline._resolve_daily_target_date(pipeline, items)

        self.assertEqual(resolved, date(2026, 4, 30))

    def test_resolve_daily_target_date_falls_back_to_stored_dates(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.load_available_dates.return_value = [date(2026, 5, 2), date(2026, 5, 3)]

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 4)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            resolved = Pipeline._resolve_daily_target_date(pipeline, [])

        self.assertEqual(resolved, date(2026, 5, 3))

    def test_daily_uses_all_stored_items_for_target_date(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        target_item = ContentItem(
            content_id="rss_target",
            source_type="rss",
            source_name="simon_willison",
            title="Target",
            url="https://example.com/target",
            author="Simon",
            published_at=datetime(2026, 5, 3, 12, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 4, 1, tzinfo=timezone.utc),
            body="Target body",
            body_type="article",
        )
        fallback_item = ContentItem(
            content_id="rss_other",
            source_type="rss",
            source_name="simon_willison",
            title="Other",
            url="https://example.com/other",
            author="Simon",
            published_at=datetime(2026, 5, 3, 10, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 4, 1, tzinfo=timezone.utc),
            body="Other body",
            body_type="article",
        )
        pipeline._load_stage_items = Mock(return_value=[fallback_item])
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.load_available_dates.return_value = [date(2026, 5, 3)]
        pipeline.transcript_store.load_by_date.return_value = [target_item]
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_daily_candidates.return_value = {"builder_hot_candidates": [], "editorial_candidates": []}
        pipeline.state_manager.load_daily_themes.return_value = {"themes": [], "discussion_dispersion": "dispersed"}
        pipeline.state_manager.load_daily_selections.return_value = {"selections": []}
        pipeline.state_manager.write_heartbeat = Mock()
        pipeline.daily_builder = Mock()
        pipeline.daily_builder.build.return_value = {"msg_type": "interactive"}
        pipeline._write_daily_report = Mock()
        pipeline.feishu = Mock()

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 4)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            payload = Pipeline.daily(pipeline, deliver=False)

        pipeline.daily_builder.build.assert_called_once()
        stats = pipeline.daily_builder.build.call_args.args[2]
        self.assertEqual(stats["total"], 1)
        self.assertEqual(payload, {"msg_type": "interactive"})

    def test_compute_x_mentions_matches_video_id_and_url(self) -> None:
        youtube_item = ContentItem(
            content_id="youtube_abc",
            source_type="youtube",
            source_name="latent_space",
            title="Video",
            url="https://www.youtube.com/watch?v=abc",
            author="Host",
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
            body="Transcript",
            body_type="transcript",
            extra_metadata={"video_id": "abc"},
        )
        zara_item = ContentItem(
            content_id="zara_x_1",
            source_type="zara_x",
            source_name="zara_follow_builders",
            title="Mention",
            url="https://example.com",
            author="Builder",
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
            body="Watch https://www.youtube.com/watch?v=abc and abc",
            body_type="summary",
        )
        counts = compute_x_mentions([youtube_item, zara_item])
        self.assertEqual(counts["youtube_abc"], 2)

    def test_select_top_candidates_picks_highest_scores(self) -> None:
        items = []
        for idx, score in enumerate([5.0, 8.5, 7.0], start=1):
            items.append(
                ContentItem(
                    content_id=f"youtube_{idx}",
                    source_type="youtube",
                    source_name="latent_space",
                    title=f"Video {idx}",
                    url=f"https://example.com/{idx}",
                    author="Host",
                    published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
                    fetched_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
                    body="Description",
                    body_type="description",
                    ai_score={
                        "relevance": score,
                        "contrarian": score,
                        "guest_rarity": score,
                        "popularity": score,
                    },
                )
            )
        selected = select_top_candidates(items, 2)
        self.assertEqual([item.content_id for item in selected], ["youtube_2", "youtube_3"])

    def test_daily_candidate_builder_splits_builder_and_editorial_candidates(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Aaron Levie",
                    "url": "https://x.com/1",
                    "topic_label": "AI代理创造更多技术机会",
                    "core_claim": "AI代理不会减少软件工作，反而会创造更多技术机会",
                    "angle": "未来判断",
                    "excerpt": "代理会带来更多软件和更多技术岗位",
                    "spotlight_text": "Aaron Levie 认为 AI 代理不会减少软件工作，反而会创造更多技术机会",
                }
            ]
        }
        builder = DailyCandidateBuilder(client=client, signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Builder post",
                url="https://x.com/1",
                author="Aaron Levie",
                published_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 29, 1, tzinfo=timezone.utc),
                body="Agents create more software work. This expands technical opportunity across teams and companies. It also creates more orchestration work, more automation demand, and more software in every organization.",
                body_type="summary",
                extra_metadata={"raw_entry": {"content": "Agents create more software work. This expands technical opportunity across teams and companies. It also creates more orchestration work, more automation demand, and more software in every organization."}},
            ),
            ContentItem(
                content_id="youtube_1",
                source_type="youtube",
                source_name="dwarkesh_patel",
                title="Video",
                url="https://youtube.com/watch?v=1",
                author="Dwarkesh Patel",
                published_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 29, 1, tzinfo=timezone.utc),
                body="Description",
                body_type="description",
                ai_summary="前沿 LLM 的训练与部署细节",
            ),
        ]
        payload = builder.build(items)
        self.assertEqual(len(payload["builder_hot_candidates"]), 1)
        self.assertEqual(len(payload["editorial_candidates"]), 1)
        self.assertEqual(payload["editorial_candidates"][0]["content_id"], "youtube_1")
        self.assertIn("editorial_candidates_raw", payload)
        self.assertIn("editorial_candidates_filtered", payload)
        self.assertIn("editorial_top10", payload)

    def test_daily_candidate_builder_filters_duplicates_before_top10(self) -> None:
        builder = DailyCandidateBuilder(client=Mock(), signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        raw_candidates = [
            {
                "content_id": "rss_1",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "Codex CLI 0.128.0 adds /goal",
                "url": "https://example.com/codex-1",
                "summary": "Codex CLI 新增 /goal 循环功能",
                "keywords": ["codex", "cli"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_2",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "Codex CLI /goal in practice",
                "url": "https://example.com/codex-2",
                "summary": "Codex CLI 新增 /goal 循环功能",
                "keywords": ["codex", "cli"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_3",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "Another Simon post",
                "url": "https://example.com/simon-3",
                "summary": "LLM 工具重构",
                "keywords": ["llm"],
                "source_type": "rss",
            },
        ]
        filtered = builder._filter_editorial_candidates(raw_candidates)
        self.assertEqual(len(filtered), 2)
        self.assertEqual([item["content_id"] for item in filtered], ["rss_1", "rss_3"])

    def test_daily_candidate_builder_ranks_and_limits_top10(self) -> None:
        builder = DailyCandidateBuilder(client=Mock(), signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        candidates = []
        for index in range(12):
            candidates.append(
                {
                    "content_id": f"item_{index}",
                    "type": "article",
                    "channel_or_source": "simon_willison" if index == 0 else f"source_{index}",
                    "title": f"Codex item {index}",
                    "url": f"https://example.com/{index}",
                    "summary": "Codex agent engineering workflow",
                    "keywords": ["codex", "agent"],
                    "source_type": "rss",
                }
            )
        ranked = builder._rank_editorial_candidates(candidates)[: builder.editorial_top_n]
        self.assertEqual(len(ranked), 10)
        self.assertEqual(ranked[0]["content_id"], "item_0")

    def test_daily_candidate_builder_backfills_builder_spotlights_when_strong_signals_are_few(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Aaron Levie",
                    "url": "https://x.com/1",
                    "topic_label": "Agent 工程岗位",
                    "core_claim": "Aaron Levie 说内部 Agent 工程岗位会越来越重要",
                    "angle": "未来判断",
                    "excerpt": "Aaron Levie 说内部 Agent 工程岗位会越来越重要",
                    "spotlight_text": "Aaron Levie 说内部 Agent 工程岗位会越来越重要",
                }
            ]
        }
        builder = DailyCandidateBuilder(client=client, signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
        items = [
            ContentItem(
                content_id=f"zara_x_{index}",
                source_type="zara_x",
                source_name="zara_x",
                title=f"Builder post {index}",
                url=f"https://x.com/{index}",
                author=f"Builder {index}",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="Agents are changing internal tooling and software org design in concrete ways.",
                body_type="summary",
                ai_summary="Agents are changing internal tooling and software org design in concrete ways.",
            )
            for index in range(1, 5)
        ]
        payload = builder.build(items)
        self.assertGreaterEqual(len(payload["builder_hot_candidates"]), 3)

    def test_daily_candidate_builder_skips_irrelevant_personal_backfill_posts(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Aaron Levie",
                    "url": "https://x.com/1",
                    "topic_label": "Agent 工程岗位",
                    "core_claim": "内部 Agent 工程岗位会越来越重要",
                    "angle": "未来判断",
                    "excerpt": "内部 Agent 工程岗位会越来越重要",
                    "spotlight_text": "内部 Agent 工程岗位会越来越重要",
                }
            ]
        }
        builder = DailyCandidateBuilder(client=client, signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Agent hiring",
                url="https://x.com/1",
                author="Aaron Levie",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="Companies will need internal agent engineers.",
                body_type="summary",
                ai_summary="Companies will need internal agent engineers.",
            ),
            ContentItem(
                content_id="zara_x_2",
                source_type="zara_x",
                source_name="zara_x",
                title="Personal update",
                url="https://x.com/2",
                author="Peter Yang",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="My kid got me sick again and broke a long healthy streak.",
                body_type="summary",
                ai_summary="My kid got me sick again and broke a long healthy streak.",
            ),
            ContentItem(
                content_id="zara_x_3",
                source_type="zara_x",
                source_name="zara_x",
                title="Agent workflow",
                url="https://x.com/3",
                author="Builder 3",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="Agents are changing internal tooling workflows.",
                body_type="summary",
                ai_summary="Agents are changing internal tooling workflows.",
            ),
            ContentItem(
                content_id="zara_x_4",
                source_type="zara_x",
                source_name="zara_x",
                title="LLM tooling",
                url="https://x.com/4",
                author="Builder 4",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="New LLM tooling is changing coding workflows.",
                body_type="summary",
                ai_summary="New LLM tooling is changing coding workflows.",
            ),
        ]
        payload = builder.build(items)
        urls = {candidate["url"] for candidate in payload["builder_hot_candidates"]}
        self.assertNotIn("https://x.com/2", urls)

    def test_daily_candidate_builder_skips_vague_backfill_posts(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Sam Altman",
                    "url": "https://x.com/1",
                    "topic_label": "GPT-5.5-Cyber",
                    "core_claim": "即将推出 GPT-5.5-Cyber 模型",
                    "angle": "技术机制",
                    "excerpt": "即将推出 GPT-5.5-Cyber 模型",
                    "spotlight_text": "即将推出 GPT-5.5-Cyber 模型",
                }
            ]
        }
        builder = DailyCandidateBuilder(client=client, signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Cyber launch",
                url="https://x.com/1",
                author="Sam Altman",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="Launching GPT-5.5-Cyber for defenders.",
                body_type="summary",
                ai_summary="Launching GPT-5.5-Cyber for defenders.",
            ),
            ContentItem(
                content_id="zara_x_2",
                source_type="zara_x",
                source_name="zara_x",
                title="alignment failure",
                url="https://x.com/2",
                author="Sam Altman",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="alignment failure",
                body_type="summary",
                ai_summary="讨论对齐失败问题",
            ),
            ContentItem(
                content_id="zara_x_3",
                source_type="zara_x",
                source_name="zara_x",
                title="Agent hiring",
                url="https://x.com/3",
                author="Aaron Levie",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="Hiring internal agent engineers.",
                body_type="summary",
                ai_summary="Hiring internal agent engineers.",
            ),
            ContentItem(
                content_id="zara_x_4",
                source_type="zara_x",
                source_name="zara_x",
                title="Tooling",
                url="https://x.com/4",
                author="Builder 4",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="New coding agent tooling changed our workflow.",
                body_type="summary",
                ai_summary="New coding agent tooling changed our workflow.",
            ),
        ]
        payload = builder.build(items)
        urls = {candidate["url"] for candidate in payload["builder_hot_candidates"]}
        self.assertNotIn("https://x.com/2", urls)

    def test_daily_candidate_builder_prefers_concrete_excerpt_when_spotlight_text_is_vague(self) -> None:
        client = Mock()
        client.daily_theme_signals.return_value = {
            "signals": [
                {
                    "content_id": "zara_x_1",
                    "source": "Sam Altman",
                    "url": "https://x.com/1",
                    "topic_label": "GPT-5.5-Cyber",
                    "core_claim": "未来几天将向关键网络防御者推出 GPT-5.5-Cyber 模型",
                    "angle": "技术机制",
                    "excerpt": "未来几天将向关键网络防御者推出 GPT-5.5-Cyber 模型",
                    "spotlight_text": "讨论 GPT-5.5-Cyber",
                }
            ]
        }
        builder = DailyCandidateBuilder(client=client, signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        builder._is_weak_signal = Mock(return_value=False)  # type: ignore[method-assign]
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Cyber launch",
                url="https://x.com/1",
                author="Sam Altman",
                published_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 30, 1, tzinfo=timezone.utc),
                body="Launching GPT-5.5-Cyber for defenders.",
                body_type="summary",
                ai_summary="Launching GPT-5.5-Cyber for defenders.",
            )
        ]
        payload = builder.build(items)
        self.assertEqual(
            payload["builder_hot_candidates"][0]["spotlight_text"],
            "未来几天将向关键网络防御者推出 GPT-5.5-Cyber 模型",
        )

    def test_daily_curate_can_return_candidates_payload(self) -> None:
        temp_dir = Path("state") / "_test_daily_candidates"
        state_manager = StateManager(temp_dir)
        items = [
            ContentItem(
                content_id="zara_x_1",
                source_type="zara_x",
                source_name="zara_x",
                title="Builder post",
                url="https://x.com/1",
                author="Aaron Levie",
                published_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 29, 1, tzinfo=timezone.utc),
                body="Agents create more software work. This expands technical opportunity across teams and companies. It also creates more orchestration work, more automation demand, and more software in every organization.",
                body_type="summary",
                extra_metadata={"raw_entry": {"content": "Agents create more software work. This expands technical opportunity across teams and companies. It also creates more orchestration work, more automation demand, and more software in every organization."}},
            ),
            ContentItem(
                content_id="youtube_1",
                source_type="youtube",
                source_name="dwarkesh_patel",
                title="Video",
                url="https://youtube.com/watch?v=1",
                author="Dwarkesh Patel",
                published_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 4, 29, 1, tzinfo=timezone.utc),
                body="Description",
                body_type="description",
                ai_summary="前沿 LLM 的训练与部署细节",
            ),
        ]
        candidate_builder = Mock()
        candidate_builder.build.return_value = {
            "builder_hot_candidates": [
                {
                    "content_id": "zara_x_1",
                    "source": "Aaron Levie",
                    "url": "https://x.com/1",
                    "topic_label": "AI代理创造更多技术机会",
                    "core_claim": "AI代理不会减少软件工作，反而会创造更多技术机会",
                    "angle": "未来判断",
                    "excerpt": "代理会带来更多软件和更多技术岗位",
                    "spotlight_text": "Aaron Levie 认为 AI 代理不会减少软件工作，反而会创造更多技术机会",
                }
            ],
            "editorial_top10": [
                {
                    "content_id": "youtube_1",
                    "type": "youtube",
                    "channel_or_source": "dwarkesh_patel",
                    "title": "Video",
                    "url": "https://youtube.com/watch?v=1",
                    "summary": "前沿 LLM 的训练与部署细节",
                }
            ],
            "editorial_candidates": [
                {
                    "content_id": "youtube_1",
                    "type": "youtube",
                    "channel_or_source": "dwarkesh_patel",
                    "title": "Video",
                    "url": "https://youtube.com/watch?v=1",
                    "summary": "前沿 LLM 的训练与部署细节",
                }
            ],
        }
        theme_aggregator = Mock(spec=ThemeAggregator)
        theme_aggregator.aggregate_themes.return_value = {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": [{"source": "Aaron Levie", "text": "spotlight", "url": "https://x.com/1"}],
        }
        daily_curator = Mock(spec=DailyCurator)
        daily_curator.curate_daily.return_value = {"selections": [], "selection_diversity": ""}

        try:
            candidates = candidate_builder.build(items)
            builder_hot_candidates = candidates["builder_hot_candidates"]
            editorial_ids = {candidate["content_id"] for candidate in candidates["editorial_top10"]}
            editorial_items = [item for item in items if item.content_id in editorial_ids]
            themes_data = theme_aggregator.aggregate_themes(items, builder_hot_candidates)
            selections_data = daily_curator.curate_daily(editorial_items, set())
            state_manager.save_daily_candidates("2026-04-29", candidates)
            state_manager.save_daily_themes("2026-04-29", themes_data)
            state_manager.save_daily_selections("2026-04-29", selections_data)
            payload = {"candidates": candidates, "themes": themes_data, "selections": selections_data}
            self.assertIn("candidates", payload)
            self.assertEqual(len(payload["candidates"]["builder_hot_candidates"]), 1)
            self.assertEqual(len(payload["candidates"]["editorial_candidates"]), 1)
            saved = state_manager.load_daily_candidates("2026-04-29")
            self.assertEqual(len(saved["editorial_candidates"]), 1)
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
