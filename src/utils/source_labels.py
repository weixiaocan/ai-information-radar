from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.config import load_yaml


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
    display_name = str(item.extra_metadata.get("display_name", "")).strip()
    if display_name:
        return display_name
    return item.source_name


def resolve_zara_source_name(feed_name: str, entry: dict[str, Any]) -> str:
    if feed_name == "zara_x":
        return str(entry.get("author") or "").strip() or feed_name
    if feed_name in {"zara_blog", "zara_podcast"}:
        return str(entry.get("name") or entry.get("author") or "").strip() or feed_name
    return feed_name


def load_display_name_map(project_root: Path | None = None) -> dict[str, str]:
    root = project_root or Path(__file__).resolve().parents[2]
    channels_config = load_yaml(root / "config" / "channels.yaml")
    sources = [
        *channels_config.get("channels", []),
        *channels_config.get("playlists", []),
        *load_yaml(root / "config" / "rss_sources.yaml").get("sources", []),
        *load_yaml(root / "config" / "web_sources.yaml").get("sources", []),
        *load_yaml(root / "config" / "newsletter_sources.yaml").get("sources", []),
    ]
    mapping: dict[str, str] = {}
    for source in sources:
        name = str(source.get("name", "")).strip()
        display_name = str(source.get("display_name", "")).strip()
        if name and display_name:
            mapping[name] = display_name
    return mapping
