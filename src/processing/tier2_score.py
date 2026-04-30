from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models.content_item import ContentItem
from src.storage.state_manager import StateManager
from src.utils.llm_client import DeepSeekClient


class Tier2Scorer:
    def __init__(
        self,
        client: DeepSeekClient,
        coarse_prompt_path: Path,
        deep_prompt_path: Path,
        state_manager: StateManager,
    ) -> None:
        self.client = client
        self.coarse_prompt_path = coarse_prompt_path
        self.deep_prompt_path = deep_prompt_path
        self.state_manager = state_manager

    def run_coarse(self, items: list[ContentItem], x_mentions_lookup: dict[str, int]) -> list[ContentItem]:
        return self._run(items, x_mentions_lookup, self.coarse_prompt_path, "coarse")

    def run_deep(self, items: list[ContentItem], x_mentions_lookup: dict[str, int]) -> list[ContentItem]:
        return self._run(items, x_mentions_lookup, self.deep_prompt_path, "deep")

    def _run(
        self,
        items: list[ContentItem],
        x_mentions_lookup: dict[str, int],
        prompt_path: Path,
        score_stage: str,
    ) -> list[ContentItem]:
        for item in items:
            if item.source_type != "youtube":
                continue
            score_payload = self.client.score(
                str(prompt_path),
                item,
                x_mentions_count=x_mentions_lookup.get(item.content_id, 0),
            )
            item.ai_score = score_payload.get("scores", {})
            item.ai_score_reasons = score_payload.get("reasons", {})
            item.extra_metadata["one_line_pitch"] = score_payload.get("one_line_pitch")
            item.extra_metadata["score_stage"] = score_stage
            total = score_total(item.ai_score or {})
            self.state_manager.append_score(
                {
                    "content_id": item.content_id,
                    "score_stage": score_stage,
                    "week": item.published_at.isocalendar().week,
                    "scores": item.ai_score,
                    "total": total,
                    "reasons": item.ai_score_reasons,
                    "one_line_pitch": score_payload.get("one_line_pitch"),
                    "rank": None,
                    "scored_at": datetime.utcnow().isoformat(),
                }
            )
        return items


def score_total(scores: dict[str, int | float]) -> float:
    if not scores:
        return 0.0
    return round(sum(float(value) for value in scores.values()) / len(scores), 2)
