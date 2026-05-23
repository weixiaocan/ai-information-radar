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
        self.daily_runs_dir = state_dir / "runs" / "daily"
        self.window_batches = {
            "ingest": state_dir / "latest_ingest_window.json",
            "x_refresh": state_dir / "latest_x_refresh_window.json",
        }
        self.themes_dir.mkdir(parents=True, exist_ok=True)
        self.selections_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self.daily_runs_dir.mkdir(parents=True, exist_ok=True)
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

    def create_daily_run(
        self,
        day: str,
        *,
        source_window: dict[str, Any] | None = None,
        status: str = "curating",
    ) -> str:
        run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = self._daily_run_dir(day, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run_id,
            "target_day": day,
            "status": status,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
            "source_window": source_window or {},
            "artifacts": {},
            "degraded": {},
        }
        self._manifest_path(day, run_id).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._latest_run_pointer_path(day).write_text(
            json.dumps({"run_id": run_id, "updated_at": manifest["updated_at"]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return run_id

    def resolve_latest_daily_run_id(self, day: str) -> str | None:
        path = self._latest_run_pointer_path(day)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        run_id = str(payload.get("run_id", "")).strip()
        return run_id or None

    def save_daily_manifest(
        self,
        day: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> None:
        manifest = self.load_daily_manifest(day, run_id)
        merged = dict(manifest)
        merged.update(payload)
        merged["run_id"] = run_id
        merged["target_day"] = day
        merged["updated_at"] = utc_now().isoformat()
        self._manifest_path(day, run_id).write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_daily_manifest(self, day: str, run_id: str) -> dict[str, Any]:
        path = self._manifest_path(day, run_id)
        if not path.exists():
            return {
                "run_id": run_id,
                "target_day": day,
                "status": "unknown",
                "created_at": "",
                "updated_at": "",
                "source_window": {},
                "artifacts": {},
                "degraded": {},
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def finalize_daily_run(
        self,
        day: str,
        run_id: str,
        *,
        status: str,
        candidates: dict[str, Any],
        themes: dict[str, Any],
        selections: dict[str, Any],
        source_window: dict[str, Any] | None = None,
    ) -> None:
        degraded = {
            "candidates": self._extract_degraded_metadata(candidates),
            "themes": self._extract_degraded_metadata(themes),
            "selections": self._extract_degraded_metadata(selections),
        }
        self.save_daily_manifest(
            day,
            run_id,
            {
                "status": status,
                "source_window": source_window or self.load_daily_manifest(day, run_id).get("source_window", {}),
                "artifacts": {
                    "candidates": "candidates.json",
                    "themes": "themes.json",
                    "selections": "selections.json",
                },
                "counts": {
                    "builder_hot_candidates": len(candidates.get("builder_hot_candidates", [])),
                    "themes": len(themes.get("themes", [])),
                    "selections": len(selections.get("selections", [])),
                },
                "degraded": degraded,
            },
        )
        self._latest_run_pointer_path(day).write_text(
            json.dumps({"run_id": run_id, "updated_at": utc_now().isoformat()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_daily_themes(self, day: str, payload: dict[str, Any], run_id: str | None = None) -> None:
        normalized = normalize_daily_themes_payload(payload)
        if run_id is None:
            path = self.themes_dir / f"{day}.json"
        else:
            path = self._daily_run_dir(day, run_id) / "themes.json"
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_daily_themes(self, day: str, run_id: str | None = None) -> dict[str, Any]:
        if run_id is None:
            run_id = self.resolve_latest_daily_run_id(day)
        if run_id:
            path = self._daily_run_dir(day, run_id) / "themes.json"
            if path.exists():
                return normalize_daily_themes_payload(json.loads(path.read_text(encoding="utf-8")))
        legacy_path = self.themes_dir / f"{day}.json"
        if not legacy_path.exists():
            return normalize_daily_themes_payload({"themes": [], "discussion_dispersion": "dispersed"})
        return normalize_daily_themes_payload(json.loads(legacy_path.read_text(encoding="utf-8")))

    def save_daily_selections(self, day: str, payload: dict[str, Any], run_id: str | None = None) -> None:
        normalized = normalize_daily_selections_payload(payload)
        if run_id is None:
            path = self.selections_dir / f"{day}.json"
        else:
            path = self._daily_run_dir(day, run_id) / "selections.json"
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_daily_selections(self, day: str, run_id: str | None = None) -> dict[str, Any]:
        if run_id is None:
            run_id = self.resolve_latest_daily_run_id(day)
        if run_id:
            path = self._daily_run_dir(day, run_id) / "selections.json"
            if path.exists():
                return normalize_daily_selections_payload(json.loads(path.read_text(encoding="utf-8")))
        legacy_path = self.selections_dir / f"{day}.json"
        if not legacy_path.exists():
            return normalize_daily_selections_payload({"selections": []})
        return normalize_daily_selections_payload(json.loads(legacy_path.read_text(encoding="utf-8")))

    def save_daily_candidates(self, day: str, payload: dict[str, Any], run_id: str | None = None) -> None:
        normalized = normalize_daily_candidates_payload(payload)
        if run_id is None:
            path = self.candidates_dir / f"{day}.json"
        else:
            path = self._daily_run_dir(day, run_id) / "candidates.json"
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_daily_candidates(self, day: str, run_id: str | None = None) -> dict[str, Any]:
        if run_id is None:
            run_id = self.resolve_latest_daily_run_id(day)
        if run_id:
            path = self._daily_run_dir(day, run_id) / "candidates.json"
            if path.exists():
                return normalize_daily_candidates_payload(json.loads(path.read_text(encoding="utf-8")))
        legacy_path = self.candidates_dir / f"{day}.json"
        if not legacy_path.exists():
            return normalize_daily_candidates_payload({"builder_hot_candidates": [], "editorial_candidates": []})
        return normalize_daily_candidates_payload(json.loads(legacy_path.read_text(encoding="utf-8")))

    def load_daily_run_bundle(self, day: str, run_id: str | None = None) -> dict[str, Any]:
        resolved_run_id = run_id or self.resolve_latest_daily_run_id(day)
        return {
            "run_id": resolved_run_id or "",
            "manifest": self.load_daily_manifest(day, resolved_run_id) if resolved_run_id else {},
            "candidates": self.load_daily_candidates(day, resolved_run_id),
            "themes": self.load_daily_themes(day, resolved_run_id),
            "selections": self.load_daily_selections(day, resolved_run_id),
        }

    def _daily_run_day_dir(self, day: str) -> Path:
        return self.daily_runs_dir / day

    def _daily_run_dir(self, day: str, run_id: str) -> Path:
        return self._daily_run_day_dir(day) / run_id

    def _latest_run_pointer_path(self, day: str) -> Path:
        return self._daily_run_day_dir(day) / "latest.json"

    def _manifest_path(self, day: str, run_id: str) -> Path:
        return self._daily_run_dir(day, run_id) / "manifest.json"

    def _extract_degraded_metadata(self, payload: dict[str, Any]) -> dict[str, str]:
        return {
            "degraded_reason": str(payload.get("degraded_reason", "")).strip(),
            "degraded_stage": str(payload.get("degraded_stage", "")).strip(),
            "fallback_mode": str(payload.get("fallback_mode", "")).strip(),
        }
