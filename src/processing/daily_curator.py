from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient


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
        return self._normalize(payload, exclude_ids)

    def _normalize(self, payload: dict[str, Any] | None, exclude_ids: set[str]) -> dict[str, Any]:
        data = payload or {}
        selections: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for selection in data.get("selections", [])[:5]:
            content_id = str(selection.get("content_id", "")).strip()
            if not content_id or content_id in exclude_ids or content_id in seen_ids:
                continue
            seen_ids.add(content_id)
            item_type = str(selection.get("type", "article")).strip().lower()
            selections.append(
                {
                    "content_id": content_id,
                    "type": "youtube" if item_type == "youtube" else "article",
                    "channel_or_source": str(selection.get("channel_or_source", "未知来源")).strip() or "未知来源",
                    "title": str(selection.get("title", "Untitled")).strip() or "Untitled",
                    "url": str(selection.get("url", "")).strip(),
                    "value_pitch": str(selection.get("value_pitch", "")).strip(),
                }
            )
        return {
            "selections": selections,
            "selection_diversity": str(data.get("selection_diversity", "")).strip(),
        }
