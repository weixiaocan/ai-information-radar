from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.daily_state import (
    normalize_daily_candidates_payload,
    normalize_daily_selections_payload,
    normalize_daily_themes_payload,
)
from src.utils.time_utils import utc_now


class StateManager:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.seen_ids_path = state_dir / "seen_ids.json"
        self.scores_path = state_dir / "scores.jsonl"
        self.heartbeat_path = state_dir / "heartbeat.log"
        self.transcript_failures_path = state_dir / "transcript_failures.jsonl"
        self.invariant_warnings_path = state_dir / "invariant_warnings.jsonl"
        self.source_status_path = state_dir / "latest_source_status.json"
        self.themes_dir = state_dir / "themes"
        self.selections_dir = state_dir / "selections"
        self.candidates_dir = state_dir / "candidates"
        self.window_batches = {
            "ingest": state_dir / "latest_ingest_window.json",
            "x_refresh": state_dir / "latest_x_refresh_window.json",
        }
        self.themes_dir.mkdir(parents=True, exist_ok=True)
        self.selections_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self.stage_batches = {
            "ingest": state_dir / "latest_ingest_ids.json",
            "tier1": state_dir / "latest_tier1_ids.json",
            "tier2": state_dir / "latest_tier2_ids.json",
            "x_refresh": state_dir / "latest_x_refresh_ids.json",
        }

    def load_seen_ids(self) -> set[str]:
        if not self.seen_ids_path.exists():
            return set()
        return set(json.loads(self.seen_ids_path.read_text(encoding="utf-8")))

    def save_seen_ids(self, seen_ids: set[str]) -> None:
        self.seen_ids_path.write_text(
            json.dumps(sorted(seen_ids), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_score(self, payload: dict[str, Any]) -> None:
        with self.scores_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def write_heartbeat(self, task_name: str, metadata: dict[str, Any] | None = None) -> None:
        entry = {
            "task": task_name,
            "timestamp": utc_now().isoformat(),
            "metadata": metadata or {},
        }
        with self.heartbeat_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def append_transcript_failure(self, payload: dict[str, Any]) -> None:
        with self.transcript_failures_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def append_invariant_warning(self, payload: dict[str, Any]) -> None:
        with self.invariant_warnings_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_latest_source_statuses(self, payload: dict[str, Any]) -> None:
        self.source_status_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_latest_source_statuses(self) -> dict[str, Any]:
        if not self.source_status_path.exists():
            return {}
        return json.loads(self.source_status_path.read_text(encoding="utf-8"))

    def save_stage_content_ids(self, stage: str, content_ids: list[str]) -> None:
        path = self.stage_batches[stage]
        path.write_text(json.dumps(content_ids, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_stage_content_ids(self, stage: str) -> list[str]:
        path = self.stage_batches[stage]
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_latest_window(self, window_name: str, payload: dict[str, Any]) -> None:
        path = self.window_batches[window_name]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_latest_window(self, window_name: str) -> dict[str, Any]:
        path = self.window_batches[window_name]
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_daily_themes(self, day: str, payload: dict[str, Any]) -> None:
        path = self.themes_dir / f"{day}.json"
        path.write_text(
            json.dumps(normalize_daily_themes_payload(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_daily_themes(self, day: str) -> dict[str, Any]:
        path = self.themes_dir / f"{day}.json"
        if not path.exists():
            return normalize_daily_themes_payload({"themes": [], "discussion_dispersion": "dispersed"})
        return normalize_daily_themes_payload(json.loads(path.read_text(encoding="utf-8")))

    def save_daily_selections(self, day: str, payload: dict[str, Any]) -> None:
        path = self.selections_dir / f"{day}.json"
        path.write_text(
            json.dumps(normalize_daily_selections_payload(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_daily_selections(self, day: str) -> dict[str, Any]:
        path = self.selections_dir / f"{day}.json"
        if not path.exists():
            return normalize_daily_selections_payload({"selections": []})
        return normalize_daily_selections_payload(json.loads(path.read_text(encoding="utf-8")))

    def save_daily_candidates(self, day: str, payload: dict[str, Any]) -> None:
        path = self.candidates_dir / f"{day}.json"
        path.write_text(
            json.dumps(normalize_daily_candidates_payload(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_daily_candidates(self, day: str) -> dict[str, Any]:
        path = self.candidates_dir / f"{day}.json"
        if not path.exists():
            return normalize_daily_candidates_payload({"builder_hot_candidates": [], "editorial_candidates": []})
        return normalize_daily_candidates_payload(json.loads(path.read_text(encoding="utf-8")))
