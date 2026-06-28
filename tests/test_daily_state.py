import json
import shutil
import unittest
from pathlib import Path

from src.output.daily_digest import DailyDigestBuilder
from src.storage.state_manager import StateManager


class DailyStateCompatibilityTest(unittest.TestCase):
    def test_state_manager_loads_legacy_daily_payloads_into_decision_and_copy(self) -> None:
        temp_dir = Path("state") / "_test_daily_state_compat"
        manager = StateManager(temp_dir)
        try:
            (manager.candidates_dir / "2026-05-01.json").write_text(
                json.dumps(
                    {
                        "builder_hot_candidates": [
                            {
                                "content_id": "zara_x_1",
                                "source": "Aaron Levie",
                                "url": "https://x.com/1",
                                "topic_label": "Agents",
                                "core_claim": "Agents are expanding software work.",
                                "excerpt": "Agents are expanding software work.",
                                "spotlight_text": "Agents are expanding software work.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (manager.themes_dir / "2026-05-01.json").write_text(
                json.dumps(
                    {
                        "themes": [
                            {
                                "theme": "Agent tooling",
                                "summary": "Builders are converging on browser-first agents.",
                                "evidence": [{"source": "Aaron Levie", "excerpt": "Browser agents.", "url": "https://x.com/1"}],
                                "related_content_ids": ["zara_x_1"],
                            }
                        ],
                        "discussion_dispersion": "clustered",
                    }
                ),
                encoding="utf-8",
            )
            (manager.selections_dir / "2026-05-01.json").write_text(
                json.dumps(
                    {
                        "selections": [
                            {
                                "content_id": "rss_1",
                                "type": "article",
                                "channel_or_source": "simon_willison",
                                "title": "A story",
                                "url": "https://example.com/story",
                                "value_pitch": "Useful overview.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            candidates = manager.load_daily_candidates("2026-05-01")
            themes = manager.load_daily_themes("2026-05-01")
            selections = manager.load_daily_selections("2026-05-01")

            self.assertIn("decision", candidates["builder_hot_candidates"][0])
            self.assertIn("copy", candidates["builder_hot_candidates"][0])
            self.assertEqual(themes["themes"][0]["decision"]["member_content_ids"], ["zara_x_1"])
            self.assertEqual(themes["themes"][0]["copy"]["theme_title"], "Agent tooling")
            self.assertEqual(selections["selections"][0]["copy"]["value_pitch"], "Useful overview.")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_daily_digest_renders_nested_daily_payloads(self) -> None:
        payload = DailyDigestBuilder().build(
            themes_data={
                "themes": [
                    {
                        "decision": {
                            "theme_id": "theme_1",
                            "member_content_ids": ["zara_x_1"],
                            "representative_urls": ["https://x.com/1"],
                            "discussion_dispersion": "clustered",
                        },
                        "copy": {
                            "theme_title": "Agent tooling",
                            "theme_summary": "Builders are converging on browser-first agents.",
                            "evidence": [{"source": "Aaron Levie", "excerpt": "Browser agents.", "url": "https://x.com/1"}],
                        },
                    }
                ]
            },
            selections_data={
                "selections": [
                    {
                        "decision": {
                            "content_id": "rss_1",
                            "selected": True,
                            "type": "article",
                            "channel_or_source": "simon_willison",
                            "title": "A story",
                            "url": "https://example.com/story",
                        },
                        "copy": {
                            "value_pitch": "Useful overview.",
                        },
                    }
                ]
            },
            stats={"total": 3},
            candidates_data={"builder_hot_candidates": [], "editorial_candidates": []},
        )

        payload_text = json.dumps(payload, ensure_ascii=False)
        self.assertIn("Agent tooling", payload_text)
        self.assertIn("Useful overview", payload_text)

    def test_state_manager_preserves_degraded_metadata(self) -> None:
        temp_dir = Path("state") / "_test_daily_state_degraded"
        manager = StateManager(temp_dir)
        try:
            manager.save_daily_candidates(
                "2026-05-02",
                {
                    "builder_hot_candidates": [
                        {
                            "decision": {"content_id": "zara_x_1", "url": "https://x.com/1", "source": "Aaron Levie"},
                            "copy": {"topic_label": "Agents", "core_claim": "Claim", "excerpt": "Claim", "spotlight_text": "Claim"},
                            "degraded_reason": "builder_copy_failed",
                            "degraded_stage": "builder_copy",
                            "fallback_mode": "copy_from_item_excerpt",
                        }
                    ],
                    "degraded_reason": "builder_copy_failed",
                    "degraded_stage": "builder_copy",
                    "fallback_mode": "per_item_copy_fallback",
                },
            )
            manager.save_daily_themes(
                "2026-05-02",
                {
                    "themes": [],
                    "discussion_dispersion": "dispersed",
                    "degraded_reason": "theme_membership_failed",
                    "degraded_stage": "theme_decision",
                    "fallback_mode": "spotlight_only",
                },
            )
            manager.save_daily_selections(
                "2026-05-02",
                {
                    "selections": [
                        {
                            "decision": {"content_id": "rss_1", "selected": True, "type": "article", "channel_or_source": "simon_willison", "title": "A story", "url": "https://example.com/story"},
                            "copy": {"value_pitch": "Useful overview."},
                            "degraded_reason": "selection_copy_failed",
                            "degraded_stage": "selection_copy",
                            "fallback_mode": "value_pitch_from_summary",
                        }
                    ],
                    "degraded_reason": "selection_copy_failed",
                    "degraded_stage": "selection_copy",
                    "fallback_mode": "value_pitch_from_summary",
                },
            )

            candidates = manager.load_daily_candidates("2026-05-02")
            themes = manager.load_daily_themes("2026-05-02")
            selections = manager.load_daily_selections("2026-05-02")

            self.assertEqual(candidates["degraded_stage"], "builder_copy")
            self.assertEqual(candidates["builder_hot_candidates"][0]["fallback_mode"], "copy_from_item_excerpt")
            self.assertEqual(themes["degraded_stage"], "theme_decision")
            self.assertEqual(themes["fallback_mode"], "spotlight_only")
            self.assertEqual(selections["degraded_stage"], "selection_copy")
            self.assertEqual(selections["selections"][0]["fallback_mode"], "value_pitch_from_summary")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_state_manager_appends_ops_events(self) -> None:
        temp_dir = Path("state") / "_test_ops_events"
        manager = StateManager(temp_dir)
        try:
            manager.append_ops_event(
                {
                    "severity": "warning",
                    "task": "daily",
                    "event": "daily_curate_deliverable_warnings",
                    "day": "2026-05-03",
                    "run_id": "run-123",
                }
            )

            lines = manager.ops_events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertIn("timestamp", event)
            self.assertEqual(event["severity"], "warning")
            self.assertEqual(event["event"], "daily_curate_deliverable_warnings")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_state_manager_versions_daily_state_by_run_and_tracks_latest_pointer(self) -> None:
        temp_dir = Path("state") / "_test_daily_state_runs"
        manager = StateManager(temp_dir)
        try:
            run_id_1 = manager.create_daily_run("2026-05-03", source_window={"label_date": "2026-05-03"})
            manager.save_daily_candidates("2026-05-03", {"builder_hot_candidates": [{"decision": {"content_id": "z1", "url": "https://x.com/1", "source": "A"}, "copy": {"topic_label": "T1", "core_claim": "C1", "excerpt": "E1", "spotlight_text": "S1"}}]}, run_id_1)
            manager.save_daily_themes("2026-05-03", {"themes": [], "discussion_dispersion": "dispersed"}, run_id_1)
            manager.save_daily_selections("2026-05-03", {"selections": []}, run_id_1)
            manager.finalize_daily_run(
                "2026-05-03",
                run_id_1,
                status="completed",
                candidates={"builder_hot_candidates": [{"decision": {"content_id": "z1", "url": "https://x.com/1", "source": "A"}, "copy": {"topic_label": "T1", "core_claim": "C1", "excerpt": "E1", "spotlight_text": "S1"}}]},
                themes={"themes": [], "discussion_dispersion": "dispersed"},
                selections={"selections": []},
                source_window={"label_date": "2026-05-03"},
            )

            run_id_2 = manager.create_daily_run("2026-05-03", source_window={"label_date": "2026-05-03"})
            manager.save_daily_candidates("2026-05-03", {"builder_hot_candidates": [{"decision": {"content_id": "z2", "url": "https://x.com/2", "source": "B"}, "copy": {"topic_label": "T2", "core_claim": "C2", "excerpt": "E2", "spotlight_text": "S2"}}]}, run_id_2)
            manager.save_daily_themes("2026-05-03", {"themes": [], "discussion_dispersion": "dispersed"}, run_id_2)
            manager.save_daily_selections("2026-05-03", {"selections": []}, run_id_2)
            manager.finalize_daily_run(
                "2026-05-03",
                run_id_2,
                status="completed",
                candidates={"builder_hot_candidates": [{"decision": {"content_id": "z2", "url": "https://x.com/2", "source": "B"}, "copy": {"topic_label": "T2", "core_claim": "C2", "excerpt": "E2", "spotlight_text": "S2"}}]},
                themes={"themes": [], "discussion_dispersion": "dispersed"},
                selections={"selections": []},
                source_window={"label_date": "2026-05-03"},
            )

            self.assertEqual(manager.resolve_latest_daily_run_id("2026-05-03"), run_id_2)
            self.assertEqual(manager.load_daily_candidates("2026-05-03", run_id_1)["builder_hot_candidates"][0]["decision"]["content_id"], "z1")
            self.assertEqual(manager.load_daily_candidates("2026-05-03", run_id_2)["builder_hot_candidates"][0]["decision"]["content_id"], "z2")
            self.assertEqual(manager.load_daily_candidates("2026-05-03")["builder_hot_candidates"][0]["decision"]["content_id"], "z2")

            manifest = manager.load_daily_manifest("2026-05-03", run_id_2)
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["target_day"], "2026-05-03")
            self.assertEqual(manifest["artifacts"]["candidates"], "candidates.json")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
