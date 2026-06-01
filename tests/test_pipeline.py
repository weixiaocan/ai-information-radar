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
from src.ingestion.zara_fetcher import ZaraFetchReport
from src.utils.daily_state import builder_candidate_copy, builder_candidate_decision, selection_copy, selection_decision


class PipelineHelpersTest(unittest.TestCase):
    def test_safe_fetch_newsletters_passes_gmail_settings_and_window(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.state_manager = Mock()
        pipeline.settings = Mock(
            gmail_credentials_path=Path("credentials.json"),
            gmail_token_path=Path("token.json"),
            request_timeout_seconds=30,
        )
        fetcher_instance = Mock()
        fetcher_instance.fetch.return_value = ["newsletter-item"]
        fetcher_cls = Mock(return_value=fetcher_instance)
        start_at = datetime(2026, 5, 28, 23, tzinfo=timezone.utc)
        end_at = datetime(2026, 5, 29, 23, tzinfo=timezone.utc)
        sources = [{"name": "every", "query": "from:hello@every.to"}]
        seen_ids = {"newsletter_email_seen"}

        result = Pipeline._safe_fetch_newsletters(
            pipeline,
            fetcher_cls,
            sources,
            seen_ids,
            recent_days=1,
            start_at=start_at,
            end_at=end_at,
        )

        self.assertEqual(result, ["newsletter-item"])
        fetcher_cls.assert_called_once_with(Path("credentials.json"), Path("token.json"), 30)
        fetcher_instance.fetch.assert_called_once_with(
            sources,
            seen_ids,
            1,
            start_at=start_at,
            end_at=end_at,
        )

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
        pipeline.state_manager.load_latest_window.return_value = {}
        pipeline.state_manager.resolve_latest_daily_run_id.return_value = None
        pipeline.state_manager.load_daily_candidates.return_value = {"builder_hot_candidates": [], "editorial_candidates": []}
        pipeline.state_manager.load_daily_themes.return_value = {"themes": [], "discussion_dispersion": "dispersed"}
        pipeline.state_manager.load_daily_selections.return_value = {"selections": []}
        pipeline.state_manager.write_heartbeat = Mock()
        pipeline.daily_builder = Mock()
        pipeline.daily_builder.collect_invariant_warnings.return_value = []
        pipeline.daily_builder.build.return_value = {"msg_type": "interactive"}
        pipeline._write_daily_report = Mock()
        pipeline.feishu = Mock()
        pipeline.site_publisher = None

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 4)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            payload = Pipeline.daily(pipeline, deliver=False)

        pipeline.daily_builder.build.assert_called_once()
        stats = pipeline.daily_builder.build.call_args.args[2]
        self.assertEqual(stats["total"], 1)

    def test_load_items_for_weekly_report_uses_previous_natural_week(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.transcript_store = Mock()
        expected_items = [
            ContentItem(
                content_id="rss_1",
                source_type="rss",
                source_name="techcrunch_ai",
                title="Weekly item",
                url="https://example.com/weekly",
                author="TechCrunch",
                published_at=datetime(2026, 5, 23, 12, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 24, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
            )
        ]
        pipeline.transcript_store.load_by_published_range.return_value = expected_items

        result = Pipeline._load_items_for_weekly_report(pipeline, date(2026, 5, 24))

        self.assertEqual(result, expected_items)
        start_at, end_at = pipeline.transcript_store.load_by_published_range.call_args.args
        self.assertEqual(start_at.date(), date(2026, 5, 18))
        self.assertEqual(end_at.date(), date(2026, 5, 25))

    def test_resolve_weekly_end_date_uses_previous_sunday(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 25)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            resolved = Pipeline._resolve_weekly_end_date(pipeline)

        self.assertEqual(resolved, date(2026, 5, 24))

    def test_weekly_uses_previous_natural_week_instead_of_tier2_snapshot(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        weekly_item = ContentItem(
            content_id="youtube_weekly",
            source_type="youtube",
            source_name="training_data",
            title="Weekly video",
            url="https://youtube.com/watch?v=weekly",
            author="Host",
            published_at=datetime(2026, 5, 23, 12, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 24, 1, tzinfo=timezone.utc),
            body="Transcript",
            body_type="transcript",
            ai_score={"relevance": 8, "contrarian": 7, "guest_rarity": 6, "popularity": 5},
        )
        pipeline._load_items_for_weekly_report = Mock(return_value=[weekly_item])
        pipeline._ensure_weekly_tier2_scores = Mock(return_value=[weekly_item])
        pipeline._resolve_weekly_end_date = Mock(return_value=date(2026, 5, 24))
        pipeline.report_writer = Mock()
        pipeline.weekly_builder = Mock()
        pipeline.weekly_builder.build.return_value = {"msg_type": "interactive"}
        pipeline._write_weekly_report = Mock(return_value=Path("reports/weekly/2026-W21.md"))
        pipeline.feishu = Mock()
        pipeline._publish_site_report = Mock()
        pipeline.state_manager = Mock()
        pipeline.state_manager.write_heartbeat = Mock()

        payload = Pipeline.weekly(pipeline, deliver=False)

        self.assertEqual(payload["msg_type"], "interactive")
        pipeline._load_items_for_weekly_report.assert_called_once_with(date(2026, 5, 24))
        pipeline._ensure_weekly_tier2_scores.assert_called_once_with([weekly_item])
        pipeline.report_writer.write.assert_called_once_with([weekly_item])
        pipeline.weekly_builder.build.assert_called_once_with([weekly_item], target_end_date=date(2026, 5, 24))
        pipeline._write_weekly_report.assert_called_once_with([weekly_item], target_end_date=date(2026, 5, 24))
        pipeline.feishu.send.assert_not_called()
        self.assertEqual(payload, {"msg_type": "interactive"})

    def test_ensure_weekly_tier2_scores_uses_weekly_youtube_items_not_latest_stage_snapshot(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.settings = Mock(tier2_candidate_count=5)
        pipeline.transcript_store = Mock()
        pipeline._fetch_transcripts_for_finalists = Mock()
        youtube_item = ContentItem(
            content_id="youtube_weekly",
            source_type="youtube",
            source_name="training_data",
            title="Weekly video",
            url="https://youtube.com/watch?v=weekly",
            author="Host",
            published_at=datetime(2026, 5, 23, 12, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 24, 1, tzinfo=timezone.utc),
            body="Transcript",
            body_type="transcript",
            ai_score=None,
        )
        x_item = ContentItem(
            content_id="zara_x_1",
            source_type="zara_x",
            source_name="zara_x",
            title="Builder mention",
            url="https://x.com/example/status/1",
            author="Builder",
            published_at=datetime(2026, 5, 23, 13, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 24, 1, tzinfo=timezone.utc),
            body="Check this out https://youtube.com/watch?v=weekly",
            body_type="tweet",
        )
        coarse_item = ContentItem.from_dict(
            {
                **youtube_item.to_dict(),
                "ai_score": {"relevance": 8, "contrarian": 7, "guest_rarity": 6, "popularity": 5},
                "ai_score_reasons": {},
                "extra_metadata": {"score_stage": "coarse"},
            }
        )
        deep_item = ContentItem.from_dict(
            {
                **youtube_item.to_dict(),
                "ai_score": {"relevance": 9, "contrarian": 8, "guest_rarity": 7, "popularity": 6},
                "ai_score_reasons": {},
                "extra_metadata": {"score_stage": "deep"},
            }
        )
        pipeline.scorer = Mock()
        pipeline.scorer.run_coarse.return_value = [coarse_item]
        pipeline._fetch_transcripts_for_finalists.return_value = [coarse_item]
        pipeline.scorer.run_deep.return_value = [deep_item]

        refreshed = Pipeline._ensure_weekly_tier2_scores(pipeline, [youtube_item, x_item])

        pipeline.scorer.run_coarse.assert_called_once()
        pipeline.scorer.run_deep.assert_called_once()
        refreshed_youtube = next(item for item in refreshed if item.content_id == "youtube_weekly")
        self.assertEqual(refreshed_youtube.ai_score["relevance"], 9)
        self.assertEqual(refreshed_youtube.extra_metadata["score_stage"], "deep")
        pipeline.transcript_store.save_many.assert_called_once()

    def test_daily_persists_invariant_warnings(self) -> None:
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
        pipeline._load_stage_items = Mock(return_value=[target_item])
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.load_available_dates.return_value = [date(2026, 5, 3)]
        pipeline.transcript_store.load_by_date.return_value = [target_item]
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {}
        pipeline.state_manager.resolve_latest_daily_run_id.return_value = None
        pipeline.state_manager.load_daily_candidates.return_value = {"builder_hot_candidates": [], "editorial_candidates": []}
        pipeline.state_manager.load_daily_themes.return_value = {"themes": [], "discussion_dispersion": "dispersed"}
        pipeline.state_manager.load_daily_selections.return_value = {"selections": []}
        pipeline.state_manager.write_heartbeat = Mock()
        pipeline.state_manager.append_invariant_warning = Mock()
        pipeline.daily_builder = Mock()
        pipeline.daily_builder.collect_invariant_warnings.return_value = [
            {
                "kind": "daily_digest_url_conflict",
                "url": "https://example.com/conflict",
                "first_content_id": "rss_1",
                "first_section": "selection",
                "second_content_id": "rss_2",
                "second_section": "supplementary",
            }
        ]
        pipeline.daily_builder.build.return_value = {"msg_type": "interactive"}
        pipeline._write_daily_report = Mock()
        pipeline.feishu = Mock()
        pipeline.site_publisher = None

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 4)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            payload = Pipeline.daily(pipeline, deliver=False)

        pipeline.state_manager.append_invariant_warning.assert_called_once()
        warning_payload = pipeline.state_manager.append_invariant_warning.call_args.args[0]
        self.assertEqual(warning_payload["day"], "2026-05-03")
        heartbeat_metadata = pipeline.state_manager.write_heartbeat.call_args.args[1]
        self.assertEqual(heartbeat_metadata["invariant_warnings"], 1)
        self.assertEqual(payload, {"msg_type": "interactive"})

    def test_daily_reads_explicit_run_artifact(self) -> None:
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
        pipeline._load_stage_items = Mock(return_value=[target_item])
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.load_available_dates.return_value = [date(2026, 5, 3)]
        pipeline.transcript_store.load_by_date.return_value = [target_item]
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {}
        pipeline.state_manager.load_daily_candidates.return_value = {"builder_hot_candidates": [], "editorial_candidates": []}
        pipeline.state_manager.load_daily_themes.return_value = {"themes": [], "discussion_dispersion": "dispersed"}
        pipeline.state_manager.load_daily_selections.return_value = {"selections": []}
        pipeline.state_manager.write_heartbeat = Mock()
        pipeline.daily_builder = Mock()
        pipeline.daily_builder.collect_invariant_warnings.return_value = []
        pipeline.daily_builder.build.return_value = {"msg_type": "interactive"}
        pipeline._write_daily_report = Mock()
        pipeline.feishu = Mock()
        pipeline.site_publisher = None

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 4)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            Pipeline.daily(pipeline, deliver=False, run_id="run-123")

        pipeline.state_manager.load_daily_candidates.assert_called_once_with("2026-05-03", "run-123")
        pipeline.state_manager.load_daily_themes.assert_called_once_with("2026-05-03", "run-123")
        pipeline.state_manager.load_daily_selections.assert_called_once_with("2026-05-03", "run-123")

    def test_daily_blocks_delivery_when_latest_curate_run_is_incomplete(self) -> None:
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
        pipeline._load_stage_items = Mock(return_value=[target_item])
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.load_available_dates.return_value = [date(2026, 5, 3)]
        pipeline.transcript_store.load_by_date.return_value = [target_item]
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {}
        pipeline.state_manager.resolve_latest_daily_run_id.return_value = "run-123"
        pipeline.state_manager.load_daily_manifest.return_value = {
            "run_id": "run-123",
            "target_day": "2026-05-03",
            "status": "curating",
            "artifacts": {},
        }
        pipeline.state_manager.write_heartbeat = Mock()
        pipeline.daily_builder = Mock()
        pipeline._write_daily_report = Mock()
        pipeline.feishu = Mock()
        pipeline.site_publisher = None

        with unittest.mock.patch("src.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 4)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            payload = Pipeline.daily(pipeline, deliver=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "daily_curate_incomplete")
        pipeline.daily_builder.build.assert_not_called()
        pipeline._write_daily_report.assert_not_called()
        pipeline.feishu.send.assert_not_called()
        pipeline.state_manager.write_heartbeat.assert_called_once_with(
            "daily_blocked_curate_incomplete",
            {
                "status": "blocked",
                "reason": "daily_curate_incomplete",
                "day": "2026-05-03",
                "run_id": "run-123",
                "items": 1,
            },
        )

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
        builder._is_builder_relevant = Mock(return_value=True)  # type: ignore[method-assign]
        builder._is_backfill_too_weak = Mock(return_value=False)  # type: ignore[method-assign]
        builder._is_backfill_too_vague = Mock(return_value=False)  # type: ignore[method-assign]
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
        self.assertIn("decision", payload["builder_hot_candidates"][0])
        self.assertIn("copy", payload["builder_hot_candidates"][0])
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
        self.assertEqual([item["content_id"] for item in filtered], ["rss_2", "rss_3"])

    def test_daily_candidate_builder_filters_every_event_newsletters(self) -> None:
        builder = DailyCandidateBuilder(client=Mock(), signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        raw_candidates = [
            {
                "content_id": "newsletter_event",
                "type": "article",
                "channel_or_source": "Every",
                "title": "You’re invited: Every 🤝 IRL + 2 digital events",
                "url": "https://mail.google.com/mail/#all/event",
                "summary": "Every 邀请订阅者参加纽约科技周线下聚会及两场线上活动。",
                "keywords": ["Every", "event"],
                "source_type": "newsletter_email",
            },
            {
                "content_id": "newsletter_article",
                "type": "article",
                "channel_or_source": "Every",
                "title": "Vibe Check: Opus 4.8",
                "url": "https://mail.google.com/mail/#all/article",
                "summary": "Anthropic is back with a stronger model.",
                "keywords": ["Anthropic", "Opus"],
                "source_type": "newsletter_email",
            },
        ]

        filtered = builder._filter_editorial_candidates(raw_candidates)

        self.assertEqual([item["content_id"] for item in filtered], ["newsletter_article"])

    def test_daily_candidate_builder_filters_package_family_release_duplicates(self) -> None:
        builder = DailyCandidateBuilder(client=Mock(), signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        raw_candidates = [
            {
                "content_id": "rss_1",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "datasette-agent 0.1a3",
                "url": "https://example.com/datasette-agent",
                "summary": "Simon Willison 发布 datasette-agent 0.1a3 版本",
                "keywords": ["datasette-agent"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_2",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "datasette-agent-charts 0.1a2",
                "url": "https://example.com/datasette-agent-charts",
                "summary": "Simon Willison 发布 datasette-agent-charts 0.1a2 版本",
                "keywords": ["datasette-agent-charts"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_3",
                "type": "article",
                "channel_or_source": "verge_ai",
                "title": "A different story",
                "url": "https://example.com/different",
                "summary": "Different topic",
                "keywords": ["different"],
                "source_type": "rss",
            },
        ]

        filtered = builder._filter_editorial_candidates(raw_candidates)
        self.assertEqual([item["content_id"] for item in filtered], ["rss_2", "rss_3"])

    def test_daily_candidate_builder_filters_space_and_slug_package_variants(self) -> None:
        builder = DailyCandidateBuilder(client=Mock(), signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        raw_candidates = [
            {
                "content_id": "rss_1",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "Datasette Agent",
                "url": "https://example.com/datasette-agent",
                "summary": "Datasette Agent 发布，可扩展 AI 助手",
                "keywords": ["datasette-agent"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_2",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "datasette-agent 0.1a3",
                "url": "https://example.com/datasette-agent-2",
                "summary": "Simon Willison 发布 datasette-agent 0.1a3 版本",
                "keywords": ["datasette-agent"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_3",
                "type": "article",
                "channel_or_source": "verge_ai",
                "title": "A different story",
                "url": "https://example.com/different",
                "summary": "Different topic",
                "keywords": ["different"],
                "source_type": "rss",
            },
        ]

        filtered = builder._filter_editorial_candidates(raw_candidates)
        self.assertEqual([item["content_id"] for item in filtered], ["rss_1", "rss_3"])

    def test_daily_candidate_builder_prefers_overview_over_release_fragment(self) -> None:
        builder = DailyCandidateBuilder(client=Mock(), signal_prompt_path=Path("prompts/theme_signal_extractor.md"))
        raw_candidates = [
            {
                "content_id": "rss_release",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "datasette-agent 0.1a3",
                "url": "https://example.com/datasette-agent-2",
                "summary": "Simon Willison 发布 datasette-agent 0.1a3 版本",
                "keywords": ["datasette-agent"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_overview",
                "type": "article",
                "channel_or_source": "simon_willison",
                "title": "Datasette Agent",
                "url": "https://example.com/datasette-agent",
                "summary": "Datasette Agent 发布，可扩展 AI 助手，支持对话查询和图表生成",
                "keywords": ["datasette-agent"],
                "source_type": "rss",
            },
            {
                "content_id": "rss_other",
                "type": "article",
                "channel_or_source": "verge_ai",
                "title": "A different story",
                "url": "https://example.com/different",
                "summary": "Different topic",
                "keywords": ["different"],
                "source_type": "rss",
            },
        ]

        filtered = builder._filter_editorial_candidates(raw_candidates)
        self.assertEqual([item["content_id"] for item in filtered], ["rss_overview", "rss_other"])

    def test_daily_curator_maps_candidate_index_back_to_candidate_item(self) -> None:
        client = Mock()
        client.daily_selections.return_value = {
            "selections": [
                {
                    "candidate_index": 1,
                    "value_pitch": "Hollywood writers are being pulled into AI training work.",
                }
            ],
            "selection_diversity": "diverse",
        }
        curator = DailyCurator(client=client, prompt_path=Path("prompts/daily_curator.md"))
        candidate_items = [
            ContentItem(
                content_id="rss_https://news.ycombinator.com/item?id=48093446",
                source_type="rss",
                source_name="hacker_news_ai",
                title="I work in Hollywood. Everyone who used to make TV is now training AI",
                url="https://www.wired.com/story/i-work-in-hollywood-everyone-who-used-to-make-tv-now-training-ai/",
                author="joozio",
                published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
            )
        ]

        payload = curator.curate_daily(candidate_items, set())

        self.assertEqual(
            selection_decision(payload["selections"][0])["content_id"],
            "rss_https://news.ycombinator.com/item?id=48093446",
        )
        self.assertEqual(
            selection_decision(payload["selections"][0])["title"],
            "I work in Hollywood. Everyone who used to make TV is now training AI",
        )
        self.assertEqual(
            selection_decision(payload["selections"][0])["url"],
            "https://www.wired.com/story/i-work-in-hollywood-everyone-who-used-to-make-tv-now-training-ai/",
        )

    def test_daily_curator_drops_invalid_candidate_index_and_empty_value_pitch(self) -> None:
        client = Mock()
        client.daily_selections.return_value = {
            "selections": [
                {"candidate_index": "1", "value_pitch": "should be ignored"},
                {"candidate_index": 1, "value_pitch": "   "},
                {"candidate_index": 1, "value_pitch": "valid pitch"},
            ],
            "selection_diversity": "diverse",
        }
        curator = DailyCurator(client=client, prompt_path=Path("prompts/daily_curator.md"))
        candidate_items = [
            ContentItem(
                content_id="rss_1",
                source_type="rss",
                source_name="simon_willison",
                title="A story",
                url="https://example.com/story",
                author="Simon",
                published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 11, 1, tzinfo=timezone.utc),
                body="Body",
                body_type="article",
            )
        ]

        payload = curator.curate_daily(candidate_items, set())

        self.assertEqual(len(payload["selections"]), 1)
        self.assertEqual(selection_copy(payload["selections"][0])["value_pitch"], "valid pitch")

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
        builder._collect_single_signal_issues = Mock(return_value=[])  # type: ignore[method-assign]
        builder._looks_mostly_english = Mock(return_value=False)  # type: ignore[method-assign]
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
        urls = {builder_candidate_decision(candidate)["url"] for candidate in payload["builder_hot_candidates"]}
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
        urls = {builder_candidate_decision(candidate)["url"] for candidate in payload["builder_hot_candidates"]}
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
            builder_candidate_copy(payload["builder_hot_candidates"][0])["spotlight_text"],
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

    def test_safe_fetch_zara_writes_heartbeat_for_failed_feed(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.settings = Mock()
        pipeline.settings.request_timeout_seconds = 30
        pipeline.settings.zara_retry_attempts = 4
        pipeline.settings.zara_retry_delays_seconds = (60, 180, 600)
        pipeline.settings.zara_retry_window_seconds = 960
        pipeline.state_manager = Mock()

        fetcher = Mock()
        fetcher.fetch.return_value = []
        fetcher.last_fetch_reports = [
            ZaraFetchReport(
                feed_name="zara_x",
                status="failed",
                attempts=3,
                items_fetched=0,
                error="timeout",
            )
        ]
        fetcher_cls = Mock(return_value=fetcher)

        items = Pipeline._safe_fetch_zara(
            pipeline,
            fetcher_cls,
            [{"name": "zara_x", "url": "https://example.com/feed-x.json"}],
            set(),
            1,
        )

        self.assertEqual(items, [])
        pipeline.state_manager.write_heartbeat.assert_called_once_with(
            "ingest_warning",
            {
                "source": "zara_x",
                "error": "timeout",
                "attempts": 3,
                "status": "failed",
            },
        )

    def test_safe_fetch_zara_passes_refresh_overrides_to_fetcher(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.settings = Mock()
        pipeline.settings.request_timeout_seconds = 30
        pipeline.settings.zara_retry_attempts = 4
        pipeline.settings.zara_retry_delays_seconds = (60, 180, 600)
        pipeline.settings.zara_retry_window_seconds = 960
        pipeline.state_manager = Mock()

        fetcher = Mock()
        fetcher.fetch.return_value = []
        fetcher.last_fetch_reports = []
        fetcher_cls = Mock(return_value=fetcher)

        Pipeline._safe_fetch_zara(
            pipeline,
            fetcher_cls,
            [{"name": "zara_x", "url": "https://example.com/feed-x.json"}],
            set(),
            1,
            retry_attempts=5,
            retry_delays_seconds=(90, 180, 300),
            retry_window_seconds=1200,
        )

        fetcher_cls.assert_called_once_with(
            [{"name": "zara_x", "url": "https://example.com/feed-x.json"}],
            30,
            retry_attempts=5,
            retry_delays_seconds=(90, 180, 300),
            retry_window_seconds=1200,
        )

    def test_daily_curate_marks_builder_fetch_failure_on_empty_hot_section(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        target_item = ContentItem(
            content_id="rss_1",
            source_type="rss",
            source_name="simon_willison",
            title="Story",
            url="https://example.com/story",
            author="Simon",
            published_at=datetime(2026, 5, 3, 12, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 4, 1, tzinfo=timezone.utc),
            body="Story body",
            body_type="article",
        )
        pipeline._load_stage_items = Mock(return_value=[target_item])
        pipeline._resolve_daily_target_date = Mock(return_value=date(2026, 5, 3))
        pipeline._load_items_for_daily_report = Mock(return_value=[target_item])
        pipeline.daily_candidate_builder = Mock()
        pipeline.daily_candidate_builder.build.return_value = {
            "builder_hot_candidates": [],
            "editorial_top10": [],
            "editorial_candidates": [],
        }
        pipeline.theme_aggregator = Mock()
        pipeline.theme_aggregator.aggregate_themes.return_value = {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": [],
        }
        pipeline.daily_curator = Mock()
        pipeline.daily_curator.curate_daily.return_value = {"selections": [], "selection_diversity": ""}
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {}
        pipeline.state_manager.load_latest_source_statuses.return_value = {
            "zara_x": {"status": "failed", "attempts": 3, "items_fetched": 0, "error": "timeout"}
        }

        payload = Pipeline.daily_curate(pipeline)

        self.assertEqual(payload["themes"]["degraded_reason"], "builder_source_fetch_failed")
        self.assertEqual(payload["themes"]["degraded_stage"], "builder_decision")
        self.assertEqual(payload["themes"]["fallback_mode"], "empty_themes")
        self.assertEqual(payload["themes"]["degraded_source"], "zara_x")

    def test_daily_curate_creates_run_versioned_state(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        target_item = ContentItem(
            content_id="rss_1",
            source_type="rss",
            source_name="simon_willison",
            title="Story",
            url="https://example.com/story",
            author="Simon",
            published_at=datetime(2026, 5, 3, 12, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 4, 1, tzinfo=timezone.utc),
            body="Story body",
            body_type="article",
        )
        pipeline._load_stage_items = Mock(return_value=[target_item])
        pipeline._resolve_daily_target_date = Mock(return_value=date(2026, 5, 3))
        pipeline._load_items_for_daily_report = Mock(return_value=[target_item])
        pipeline.daily_candidate_builder = Mock()
        pipeline.daily_candidate_builder.build.return_value = {
            "builder_hot_candidates": [],
            "editorial_top10": [],
            "editorial_candidates": [],
        }
        pipeline.theme_aggregator = Mock()
        pipeline.theme_aggregator.aggregate_themes.return_value = {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": [],
        }
        pipeline.daily_curator = Mock()
        pipeline.daily_curator.curate_daily.return_value = {"selections": [], "selection_diversity": ""}
        pipeline.daily_decision_resolver = Mock()
        pipeline.daily_decision_resolver.resolve.return_value = (
            {"builder_hot_candidates": [], "editorial_top10": [], "editorial_candidates": []},
            {"themes": [], "discussion_dispersion": "dispersed", "spotlight_posts": []},
            {"selections": [], "selection_diversity": ""},
        )
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {"label_date": "2026-05-03"}
        pipeline.state_manager.load_latest_source_statuses.return_value = {}
        pipeline.state_manager.create_daily_run.return_value = "run-123"

        payload = Pipeline.daily_curate(pipeline)

        self.assertEqual(payload["run_id"], "run-123")
        pipeline.state_manager.save_daily_candidates.assert_any_call("2026-05-03", unittest.mock.ANY, "run-123")
        pipeline.state_manager.save_daily_themes.assert_any_call("2026-05-03", unittest.mock.ANY, "run-123")
        pipeline.state_manager.save_daily_selections.assert_any_call("2026-05-03", unittest.mock.ANY, "run-123")
        pipeline.state_manager.finalize_daily_run.assert_called_once()

    def test_x_refresh_site_rebuilds_site_daily_from_base_window_plus_new_x_items(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        base_item = ContentItem(
            content_id="rss_1",
            source_type="rss",
            source_name="simon_willison",
            title="Story",
            url="https://example.com/story",
            author="Simon",
            published_at=datetime(2026, 5, 19, 1, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 20, 0, tzinfo=timezone.utc),
            body="Story body",
            body_type="article",
        )
        fresh_x_item = ContentItem(
            content_id="zara_x_1",
            source_type="zara_x",
            source_name="zara_x",
            title="Builder post",
            url="https://x.com/1",
            author="Aaron Levie",
            published_at=datetime(2026, 5, 20, 2, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 20, 8, tzinfo=timezone.utc),
            body="Builder body",
            body_type="summary",
        )
        pipeline.settings = Mock()
        pipeline.settings.project_root = Path(".")
        pipeline.settings.request_timeout_seconds = 30
        pipeline.settings.zara_x_refresh_retry_attempts = 4
        pipeline.settings.zara_x_refresh_retry_delays_seconds = (60, 180, 600)
        pipeline.settings.zara_x_refresh_retry_window_seconds = 960
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.side_effect = [
            {
                "start_at": "2026-05-19T23:00:00+00:00",
                "end_at": "2026-05-20T23:00:00+00:00",
                "label_date": "2026-05-20",
            }
        ]
        pipeline.state_manager.load_latest_source_statuses.return_value = {}
        pipeline.state_manager.save_latest_source_statuses = Mock()
        pipeline.state_manager.save_seen_ids = Mock()
        pipeline.state_manager.save_stage_content_ids = Mock()
        pipeline.state_manager.save_latest_window = Mock()
        pipeline.state_manager.save_daily_candidates = Mock()
        pipeline.state_manager.save_daily_themes = Mock()
        pipeline.state_manager.save_daily_selections = Mock()
        pipeline.state_manager.write_heartbeat = Mock()
        pipeline.state_manager.load_seen_ids.return_value = set()
        pipeline.transcript_store = Mock()
        pipeline.transcript_store.save_many = Mock()
        pipeline._safe_fetch_zara = Mock(return_value=[fresh_x_item])
        pipeline._summarize_zara_source_status = Mock(return_value={"status": "success"})
        pipeline._load_items_for_daily_report = Mock(return_value=[base_item])
        pipeline.daily_candidate_builder = Mock()
        pipeline.daily_candidate_builder.build.return_value = {
            "builder_hot_candidates": [],
            "editorial_top10": [{"content_id": "rss_1"}],
            "editorial_candidates": [{"content_id": "rss_1"}],
        }
        pipeline.theme_aggregator = Mock()
        pipeline.theme_aggregator.aggregate_themes.return_value = {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": [],
        }
        pipeline.daily_curator = Mock()
        pipeline.daily_curator.curate_daily.return_value = {"selections": [], "selection_diversity": ""}
        pipeline._write_daily_report = Mock(return_value=Path("reports/daily/2026-05-20.md"))
        pipeline._publish_site_report = Mock()

        payload = Pipeline.x_refresh_site(pipeline)

        self.assertTrue(payload["updated"])
        built_items = pipeline.daily_candidate_builder.build.call_args.args[0]
        self.assertEqual({item.content_id for item in built_items}, {"rss_1", "zara_x_1"})
        pipeline._publish_site_report.assert_called_once()
        pipeline.state_manager.write_heartbeat.assert_any_call(
            "x_refresh_site_start",
            unittest.mock.ANY,
        )
        pipeline.state_manager.write_heartbeat.assert_any_call(
            "x_refresh_site",
            unittest.mock.ANY,
        )

    def test_x_refresh_site_returns_without_publishing_when_zara_fetch_failed(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.settings = Mock()
        pipeline.settings.project_root = Path(".")
        pipeline.settings.request_timeout_seconds = 30
        pipeline.settings.zara_x_refresh_retry_attempts = 4
        pipeline.settings.zara_x_refresh_retry_delays_seconds = (60, 180, 600)
        pipeline.settings.zara_x_refresh_retry_window_seconds = 960
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {
            "start_at": "2026-05-19T23:00:00+00:00",
            "end_at": "2026-05-20T23:00:00+00:00",
            "label_date": "2026-05-20",
        }
        pipeline.state_manager.load_seen_ids.return_value = set()
        pipeline.state_manager.save_latest_source_statuses = Mock()
        pipeline.transcript_store = Mock()
        pipeline._safe_fetch_zara = Mock(return_value=[])
        pipeline._summarize_zara_source_status = Mock(
            return_value={"status": "timed_out", "attempts": 4, "items_fetched": 0, "error": "timeout"}
        )
        pipeline._publish_site_report = Mock()

        payload = Pipeline.x_refresh_site(pipeline)

        self.assertFalse(payload["updated"])
        self.assertEqual(payload["reason"], "zara_fetch_failed")
        pipeline.transcript_store.save_many.assert_not_called()
        pipeline._publish_site_report.assert_not_called()
        pipeline.state_manager.write_heartbeat.assert_any_call(
            "x_refresh_site_error",
            unittest.mock.ANY,
        )

    def test_x_refresh_site_records_empty_run_without_publishing(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.settings = Mock()
        pipeline.settings.project_root = Path(".")
        pipeline.settings.request_timeout_seconds = 30
        pipeline.settings.zara_x_refresh_retry_attempts = 4
        pipeline.settings.zara_x_refresh_retry_delays_seconds = (60, 180, 600)
        pipeline.settings.zara_x_refresh_retry_window_seconds = 960
        pipeline.state_manager = Mock()
        pipeline.state_manager.load_latest_window.return_value = {
            "start_at": "2026-05-19T23:00:00+00:00",
            "end_at": "2026-05-20T23:00:00+00:00",
            "label_date": "2026-05-20",
        }
        pipeline.state_manager.load_seen_ids.return_value = set()
        pipeline.state_manager.save_latest_source_statuses = Mock()
        pipeline.transcript_store = Mock()
        pipeline._safe_fetch_zara = Mock(return_value=[])
        pipeline._summarize_zara_source_status = Mock(
            return_value={"status": "empty", "attempts": 1, "items_fetched": 0, "error": ""}
        )
        pipeline._publish_site_report = Mock()

        payload = Pipeline.x_refresh_site(pipeline)

        self.assertFalse(payload["updated"])
        self.assertEqual(payload["new_x_items"], 0)
        pipeline.transcript_store.save_many.assert_not_called()
        pipeline._publish_site_report.assert_not_called()
        pipeline.state_manager.write_heartbeat.assert_any_call(
            "x_refresh_site",
            unittest.mock.ANY,
        )


if __name__ == "__main__":
    unittest.main()
