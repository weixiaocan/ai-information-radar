import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.pipeline import compute_x_mentions, select_top_candidates
from src.processing.daily_candidate_builder import DailyCandidateBuilder
from src.processing.daily_curator import DailyCurator
from src.processing.theme_aggregator import ThemeAggregator
from src.storage.state_manager import StateManager


class PipelineHelpersTest(unittest.TestCase):
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
            editorial_ids = {candidate["content_id"] for candidate in candidates["editorial_candidates"]}
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
