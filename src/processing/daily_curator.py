from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from src.models.content_item import ContentItem
from src.utils.daily_state import normalize_selection, with_degraded_fields
from src.utils.llm_client import DeepSeekClient
from src.utils.source_labels import get_original_source_name


@dataclass
class DailyCurator:
    client: DeepSeekClient
    prompt_path: Path
    copy_prompt_path: Path | None = None

    def curate_daily(self, candidate_items: list[ContentItem], exclude_ids: set[str]) -> dict[str, Any]:
        if not candidate_items:
            return {"selections": [], "selection_diversity": ""}
        try:
            decision_payload = self.client.daily_selection_decisions(str(self.prompt_path), candidate_items, exclude_ids)
            if not isinstance(decision_payload, dict):
                decision_payload = self.client.daily_selections(str(self.prompt_path), candidate_items, exclude_ids)
        except Exception:
            return with_degraded_fields(
                {"selections": [], "selection_diversity": ""},
                degraded_reason="selection_decision_failed",
                degraded_stage="selection_decision",
                fallback_mode="empty_selection",
            )
        payload = self._normalize(decision_payload, candidate_items, exclude_ids)
        if candidate_items and not payload["selections"]:
            return with_degraded_fields(
                payload,
                degraded_reason="selection_decision_failed",
                degraded_stage="selection_decision",
                fallback_mode="empty_selection",
            )
        if any(selection.get("degraded_stage") for selection in payload["selections"]):
            return with_degraded_fields(
                payload,
                degraded_reason="selection_copy_failed",
                degraded_stage="selection_copy",
                fallback_mode="value_pitch_from_summary",
            )
        return payload

    def _normalize(
        self,
        payload: dict[str, Any] | None,
        candidate_items: list[ContentItem],
        exclude_ids: set[str],
    ) -> dict[str, Any]:
        data = payload or {}
        candidate_by_index = {index: item for index, item in enumerate(candidate_items, start=1)}
        selected_indexes = self._collect_selected_indexes(data)
        copy_payload = self._fetch_selection_copy(candidate_items, exclude_ids, selected_indexes)
        copy_by_index = self._copy_by_candidate_index(copy_payload)
        selections: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for candidate_index in selected_indexes[:5]:
            matched_item = candidate_by_index.get(candidate_index)
            if not matched_item:
                continue
            content_id = matched_item.content_id
            if content_id in exclude_ids or content_id in seen_ids:
                continue
            value_pitch = self._normalize_value_pitch(copy_by_index.get(candidate_index, {}).get("value_pitch"))
            used_copy_fallback = False
            if not value_pitch:
                value_pitch = self._fallback_value_pitch(matched_item)
                used_copy_fallback = True
            seen_ids.add(content_id)
            selection = normalize_selection(
                {
                    "decision": {
                        "content_id": content_id,
                        "selected": True,
                        "type": "youtube" if matched_item.source_type == "youtube" else "article",
                        "channel_or_source": get_original_source_name(matched_item),
                        "title": matched_item.title,
                        "url": matched_item.url,
                    },
                    "copy": {
                        "value_pitch": value_pitch,
                    },
                }
            )
            if used_copy_fallback:
                selection = with_degraded_fields(
                    selection,
                    degraded_reason="selection_copy_failed",
                    degraded_stage="selection_copy",
                    fallback_mode="value_pitch_from_summary",
                )
            selections.append(selection)
        return {
            "selections": selections,
            "selection_diversity": self._normalize_value_pitch(copy_payload.get("selection_diversity")),
        }

    def _collect_selected_indexes(self, payload: dict[str, Any]) -> list[int]:
        indexes: list[int] = []
        for selection in payload.get("selections", [])[:5]:
            candidate_index = self._coerce_candidate_index(selection.get("candidate_index"))
            if candidate_index is None or candidate_index in indexes:
                continue
            indexes.append(candidate_index)
        return indexes

    def _fetch_selection_copy(
        self,
        candidate_items: list[ContentItem],
        exclude_ids: set[str],
        selected_indexes: list[int],
    ) -> dict[str, Any]:
        if not selected_indexes:
            return {}
        try:
            payload = self.client.daily_selection_copy(
                str(self.copy_prompt_path or self.prompt_path),
                candidate_items,
                selected_indexes,
                exclude_ids,
            )
            if not isinstance(payload, dict):
                payload = self.client.daily_selections(str(self.copy_prompt_path or self.prompt_path), candidate_items, exclude_ids)
        except Exception:
            return {}
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            issues = self._collect_copy_issues(payload, selected_indexes)
            if not issues:
                break
            if attempt == max_attempts:
                break
            try:
                payload = self.client.daily_selection_copy(
                    str(self.copy_prompt_path or self.prompt_path),
                    candidate_items,
                    selected_indexes,
                    exclude_ids,
                    feedback=issues,
                )
                if not isinstance(payload, dict):
                    payload = self.client.daily_selections(str(self.copy_prompt_path or self.prompt_path), candidate_items, exclude_ids)
            except Exception:
                break
        return payload or {}

    def _copy_by_candidate_index(self, payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for selection in payload.get("selections", [])[:5]:
            candidate_index = self._coerce_candidate_index(selection.get("candidate_index"))
            if candidate_index is None:
                continue
            result[candidate_index] = selection
        return result

    def _collect_copy_issues(self, payload: dict[str, Any] | None, selected_indexes: list[int]) -> list[str]:
        issues: list[str] = []
        copy_by_index = self._copy_by_candidate_index(payload or {})
        for candidate_index in selected_indexes[:5]:
            copy = copy_by_index.get(candidate_index, {})
            value_pitch = str(copy.get("value_pitch", "")).strip()
            if not value_pitch:
                issues.append(f"Selection {candidate_index} missing `value_pitch`.")
                continue
            if self._looks_mostly_english(value_pitch):
                issues.append(f"Selection {candidate_index} `value_pitch` must be rewritten into natural Chinese.")
            if self._looks_truncated(value_pitch):
                issues.append(f"Selection {candidate_index} `value_pitch` is truncated; rewrite it as a complete sentence.")
        diversity = str((payload or {}).get("selection_diversity", "")).strip()
        if diversity and self._looks_mostly_english(diversity):
            issues.append("`selection_diversity` must be written in Chinese.")
        return issues

    def _fallback_value_pitch(self, item: ContentItem) -> str:
        source = get_original_source_name(item)
        summary = str(item.ai_summary or "").strip()
        if not summary or self._looks_mostly_english(summary):
            title = item.title.strip()
            if title and not self._looks_mostly_english(title):
                return self._normalize_value_pitch(f"{source} 这条内容关注《{title}》，可作为今日精选参考")
            return self._normalize_value_pitch(f"{source} 这条内容可作为今日精选参考")
        return self._normalize_value_pitch(f"{source} 这条内容主要讲的是 {summary}")

    def _coerce_candidate_index(self, value: Any) -> int | None:
        return value if isinstance(value, int) and value > 0 else None

    def _normalize_value_pitch(self, value: Any) -> str:
        return str(value or "").strip()

    def _looks_mostly_english(self, text: str) -> bool:
        letters = re.findall(r"[A-Za-z]", text)
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        return len(letters) >= 12 and len(letters) > len(cjk)

    def _looks_truncated(self, text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        return normalized.endswith(("...", "…", "/", "-", ":", "："))
