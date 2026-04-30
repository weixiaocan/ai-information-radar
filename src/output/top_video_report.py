from __future__ import annotations

from pathlib import Path

from src.models.content_item import ContentItem
from src.processing.tier2_score import score_total
from src.utils.llm_client import DeepSeekClient
from src.utils.slugify import slugify


class TopVideoReportWriter:
    def __init__(self, client: DeepSeekClient, prompt_path: Path, reports_root: Path) -> None:
        self.client = client
        self.prompt_path = prompt_path
        self.reports_root = reports_root
        self.reports_root.mkdir(parents=True, exist_ok=True)

    def write(self, items: list[ContentItem]) -> list[Path]:
        ranked = sorted(
            [item for item in items if item.source_type == "youtube" and item.ai_score],
            key=lambda item: score_total(item.ai_score or {}),
            reverse=True,
        )[:2]
        if not ranked:
            return []
        week = ranked[0].published_at.isocalendar()
        week_dir = self.reports_root / f"{week.year}-W{week.week:02d}"
        week_dir.mkdir(parents=True, exist_ok=True)
        for path in week_dir.glob("top*.md"):
            path.unlink()

        outputs: list[Path] = []
        for index, item in enumerate(ranked, start=1):
            path = week_dir / f"top{index}_{slugify(item.source_name)}_{slugify(item.title)}.md"
            path.write_text(self.client.ebook_report(str(self.prompt_path), item, index), encoding="utf-8")
            outputs.append(path)
        return outputs
