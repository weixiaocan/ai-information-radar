from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterable

from src.models.content_item import ContentItem
from src.utils.slugify import slugify


class TranscriptStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, item: ContentItem) -> Path:
        day_dir = self.root / item.published_at.strftime("%Y-%m-%d") / slugify(item.source_type)
        day_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{slugify(item.source_name)}_{slugify(item.title, fallback=item.content_id)}.md"
        path = day_dir / filename
        path.write_text(self._render_markdown(item), encoding="utf-8")
        return path

    def save_many(self, items: Iterable[ContentItem]) -> list[Path]:
        return [self.save(item) for item in items]

    def load_by_content_ids(self, content_ids: list[str]) -> list[ContentItem]:
        wanted = set(content_ids)
        items: list[ContentItem] = []
        for path in self.root.rglob("*.md"):
            item = self._load_item(path)
            if item and item.content_id in wanted:
                items.append(item)
        items.sort(key=lambda item: item.published_at)
        return items

    def load_by_date(self, target_date: date) -> list[ContentItem]:
        day_dir = self.root / target_date.isoformat()
        items: list[ContentItem] = []
        if not day_dir.exists():
            return items
        for path in day_dir.rglob("*.md"):
            item = self._load_item(path)
            if item and item.published_at.date() == target_date:
                items.append(item)
        items.sort(key=lambda item: item.published_at)
        return items

    def load_available_dates(self) -> list[date]:
        dates: list[date] = []
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                dates.append(date.fromisoformat(path.name))
            except ValueError:
                continue
        dates.sort()
        return dates

    def _render_markdown(self, item: ContentItem) -> str:
        frontmatter = {
            "content_id": item.content_id,
            "source_type": item.source_type,
            "source_name": item.source_name,
            "title": item.title,
            "url": item.url,
            "author": item.author,
            "published_at": item.published_at.isoformat(),
            "fetched_at": item.fetched_at.isoformat(),
            "body_type": item.body_type,
            "duration_seconds": item.duration_seconds,
            "view_count": item.view_count,
            "like_count": item.like_count,
            "comment_count": item.comment_count,
            "ai_summary": item.ai_summary,
            "ai_keywords": item.ai_keywords,
            "ai_score": item.ai_score,
            "ai_score_reasons": item.ai_score_reasons,
            "extra_metadata": item.extra_metadata,
        }
        return f"---\n{json.dumps(frontmatter, ensure_ascii=False, indent=2)}\n---\n\n{item.body.strip()}\n"

    def _load_item(self, path: Path) -> ContentItem | None:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        try:
            _, rest = text.split("---\n", 1)
            frontmatter_raw, body = rest.split("\n---\n\n", 1)
        except ValueError:
            return None
        payload = json.loads(frontmatter_raw)
        payload["body"] = body.strip()
        return ContentItem.from_dict(payload)
