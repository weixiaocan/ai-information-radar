from __future__ import annotations

from typing import Any

from src.models.content_item import ContentItem


def get_original_source_name(item: ContentItem) -> str:
    raw_entry = item.extra_metadata.get("raw_entry", {})
    if item.source_type == "zara_x":
        return (
            str(item.author or "").strip()
            or str(raw_entry.get("author") or "").strip()
            or str(raw_entry.get("handle") or "").strip()
            or item.source_name
        )
    if item.source_type in {"zara_blog", "zara_podcast"}:
        return (
            str(raw_entry.get("name") or "").strip()
            or str(item.author or "").strip()
            or item.source_name
        )
    return item.source_name


def resolve_zara_source_name(feed_name: str, entry: dict[str, Any]) -> str:
    if feed_name == "zara_x":
        return str(entry.get("author") or "").strip() or feed_name
    if feed_name in {"zara_blog", "zara_podcast"}:
        return str(entry.get("name") or entry.get("author") or "").strip() or feed_name
    return feed_name
