from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/config/default-sources.json"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def dump_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def playlist_id_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query).get("list", [""])[0]


def source_name(name: str) -> str:
    return (
        name.lower()
        .replace("&", "and")
        .replace("'", "")
        .replace("-", "_")
        .replace(" ", "_")
        .replace("__", "_")
    )


def sync_channels(payload: dict) -> None:
    path = PROJECT_ROOT / "config" / "channels.yaml"
    current = load_yaml(path)
    channels = list(current.get("channels", []))
    playlists = list(current.get("playlists", []))
    channel_names = {item.get("name") for item in channels}
    playlist_names = {item.get("name") for item in playlists}

    for podcast in payload.get("podcasts", []):
        name = source_name(str(podcast.get("name", "")))
        url = str(podcast.get("url", "")).strip()
        if "playlist?list=" in url:
            playlist_id = playlist_id_from_url(url)
            if not playlist_id or name in playlist_names:
                continue
            playlists.append(
                {
                    "name": name,
                    "display_name": podcast.get("name", name),
                    "playlist_id": playlist_id,
                    "url": url,
                    "enabled": True,
                    "reason": "Synced from zarazhangrui/follow-builders",
                }
            )
            playlist_names.add(name)
        elif "youtube.com" in url:
            handle = str(urlparse(url).path.rstrip("/").split("/")[-1] or "")
            if not handle:
                continue
            if not handle.startswith("@"):
                handle = f"@{handle}"
            if name in channel_names:
                continue
            channels.append(
                {
                    "name": name,
                    "display_name": podcast.get("name", name),
                    "handle": handle,
                    "enabled": True,
                    "reason": "Synced from zarazhangrui/follow-builders",
                }
            )
            channel_names.add(name)

    dump_yaml(path, {"channels": channels, "playlists": playlists})


def sync_web_sources(payload: dict) -> None:
    path = PROJECT_ROOT / "config" / "web_sources.yaml"
    current = load_yaml(path)
    sources = list(current.get("sources", []))
    source_names = {item.get("name") for item in sources}
    for blog in payload.get("blogs", []):
        name = source_name(str(blog.get("name", "")))
        if name in source_names:
            continue
        sources.append(
            {
                "name": name,
                "display_name": blog.get("name", name),
                "type": blog.get("type", "scrape"),
                "index_url": blog.get("indexUrl", ""),
                "article_base_url": blog.get("articleBaseUrl", ""),
                "enabled": True,
            }
        )
        source_names.add(name)
    dump_yaml(path, {"sources": sources})


def main() -> None:
    response = requests.get(SOURCE_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    sync_channels(payload)
    sync_web_sources(payload)
    print(json.dumps({"status": "ok", "source_url": SOURCE_URL}, ensure_ascii=False))


if __name__ == "__main__":
    main()
