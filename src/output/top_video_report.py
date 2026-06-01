from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from src.models.content_item import ContentItem
from src.processing.tier2_score import score_total
from src.utils.llm_client import DeepSeekClient
from src.utils.source_labels import get_original_source_name
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
            path = week_dir / f"top{index}_{slugify(get_original_source_name(item))}_{slugify(item.title)}.md"
            report_text = self._sanitize_report_title(self.client.ebook_report(str(self.prompt_path), item, index), item)
            path.write_text(report_text, encoding="utf-8")
            outputs.append(path)
        return outputs

    def _sanitize_report_title(self, report_text: str, item: ContentItem) -> str:
        first_heading = self._first_heading(report_text)
        if not first_heading:
            return f"# {self._fallback_title(item)}\n\n{report_text.lstrip()}"
        if not self._looks_like_prompt_example_leak(first_heading, item):
            return report_text
        return re.sub(r"^# .*$", f"# {self._fallback_title(item)}", report_text, count=1, flags=re.MULTILINE)

    def _first_heading(self, report_text: str) -> str:
        match = re.search(r"^#\s+(.+?)\s*$", report_text, flags=re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _looks_like_prompt_example_leak(self, heading: str, item: ContentItem) -> bool:
        normalized_heading = heading.lower()
        normalized_title = unescape(item.title).lower()
        if "硬件浪潮" in normalized_heading and "hardware" not in normalized_title:
            return True
        return "ai 硬件浪潮才刚开始" in normalized_heading and "hardware boom" not in normalized_title

    def _fallback_title(self, item: ContentItem) -> str:
        title = unescape(item.title).split("|", 1)[0].strip()
        if title.lower() == "inside yc's ai playbook":
            return "YC AI Playbook 内幕"
        return title or "Top 视频精读笔记"
