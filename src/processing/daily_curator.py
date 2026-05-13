from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient
from src.utils.source_labels import get_original_source_name


@dataclass
class DailyCurator:
    client: DeepSeekClient
    prompt_path: Path

    def curate_daily(self, candidate_items: list[ContentItem], exclude_ids: set[str]) -> dict[str, Any]:
        if not candidate_items:
            return {"selections": [], "selection_diversity": ""}
        try:
            payload = self.client.daily_selections(str(self.prompt_path), candidate_items, exclude_ids)
        except Exception:
            return {"selections": [], "selection_diversity": ""}
        return self._normalize(payload, candidate_items, exclude_ids)

    def _normalize(
        self,
        payload: dict[str, Any] | None,
        candidate_items: list[ContentItem],
        exclude_ids: set[str],
    ) -> dict[str, Any]:
        data = payload or {}
        candidate_by_index = {
            index: item
            for index, item in enumerate(candidate_items, start=1)
        }
        selections: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for selection in data.get("selections", [])[:5]:
            candidate_index = self._coerce_candidate_index(selection.get("candidate_index"))
            if candidate_index is None:
                continue
            matched_item = candidate_by_index.get(candidate_index)
            if not matched_item:
                continue
            content_id = matched_item.content_id
            if content_id in exclude_ids or content_id in seen_ids:
                continue
            value_pitch = self._normalize_value_pitch(selection.get("value_pitch"))
            if not value_pitch:
                continue
            seen_ids.add(content_id)
            selections.append(
                {
                    "content_id": content_id,
                    "type": "youtube" if matched_item.source_type == "youtube" else "article",
                    "channel_or_source": get_original_source_name(matched_item),
                    "title": matched_item.title,
                    "url": matched_item.url,
                    "value_pitch": value_pitch,
                }
            )
        return {
            "selections": selections,
            "selection_diversity": str(data.get("selection_diversity", "")).strip(),
        }

    def _coerce_candidate_index(self, value: Any) -> int | None:
        return value if isinstance(value, int) and value > 0 else None

    def _normalize_value_pitch(self, value: Any) -> str:
        return str(value or "").strip()
