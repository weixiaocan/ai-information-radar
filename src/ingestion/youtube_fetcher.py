from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from src.models.content_item import ContentItem
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)


class YouTubeFetcher:
    def __init__(self, api_key: str, timeout_seconds: int) -> None:
        if not api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not configured")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def fetch(
        self,
        channels: list[dict[str, Any]],
        seen_ids: set[str],
        recent_days: int,
        max_results_per_channel: int = 20,
        min_duration_minutes: int = 25,
    ) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = utc_days_ago(recent_days)
        for channel in channels:
            if not channel.get("enabled", True):
                continue
            channel_id = self._resolve_channel_id(channel["handle"])
            videos = self._fetch_latest_videos(channel_id, max_results_per_channel)
            for video in videos:
                published_at = datetime.fromisoformat(video["published_at"].replace("Z", "+00:00"))
                if published_at < cutoff:
                    continue
                if self._is_short(video["id"]):
                    continue
                detail = self._fetch_video_detail(video["id"])
                duration_seconds = _iso_duration_to_seconds(detail["contentDetails"]["duration"])
                if duration_seconds < min_duration_minutes * 60:
                    continue
                content_id = f"youtube_{video['id']}"
                if content_id in seen_ids:
                    continue
                body = detail["snippet"].get("description", "").strip() or video["title"]
                results.append(
                    ContentItem(
                        content_id=content_id,
                        source_type="youtube",
                        source_name=channel["name"],
                        title=video["title"],
                        url=f"https://www.youtube.com/watch?v={video['id']}",
                        author=video["channel_title"],
                        published_at=published_at,
                        fetched_at=utc_now(),
                        body=body,
                        body_type="description",
                        duration_seconds=duration_seconds,
                        view_count=int(detail["statistics"].get("viewCount", 0)),
                        like_count=int(detail["statistics"].get("likeCount", 0)),
                        comment_count=int(detail["statistics"].get("commentCount", 0)),
                        extra_metadata={
                            "channel_reason": channel.get("reason", ""),
                            "video_id": video["id"],
                            "channel_id": channel_id,
                            "transcript_status": "not_requested",
                        },
                    )
                )
        LOGGER.info("Fetched %s new YouTube metadata items", len(results))
        return results

    def fetch_playlists(
        self,
        playlists: list[dict[str, Any]],
        seen_ids: set[str],
        recent_days: int,
        max_results_per_playlist: int = 20,
        min_duration_minutes: int = 25,
    ) -> list[ContentItem]:
        results: list[ContentItem] = []
        cutoff = utc_days_ago(recent_days)
        for playlist in playlists:
            if not playlist.get("enabled", True):
                continue
            videos = self._fetch_playlist_videos(playlist["playlist_id"], max_results_per_playlist)
            for video in videos:
                published_at = datetime.fromisoformat(video["published_at"].replace("Z", "+00:00"))
                if published_at < cutoff:
                    continue
                if self._is_short(video["id"]):
                    continue
                detail = self._fetch_video_detail(video["id"])
                duration_seconds = _iso_duration_to_seconds(detail["contentDetails"]["duration"])
                if duration_seconds < min_duration_minutes * 60:
                    continue
                content_id = f"youtube_{video['id']}"
                if content_id in seen_ids:
                    continue
                body = detail["snippet"].get("description", "").strip() or video["title"]
                results.append(
                    ContentItem(
                        content_id=content_id,
                        source_type="youtube",
                        source_name=playlist["name"],
                        title=video["title"],
                        url=f"https://www.youtube.com/watch?v={video['id']}",
                        author=video["channel_title"],
                        published_at=published_at,
                        fetched_at=utc_now(),
                        body=body,
                        body_type="description",
                        duration_seconds=duration_seconds,
                        view_count=int(detail["statistics"].get("viewCount", 0)),
                        like_count=int(detail["statistics"].get("likeCount", 0)),
                        comment_count=int(detail["statistics"].get("commentCount", 0)),
                        extra_metadata={
                            "channel_reason": playlist.get("reason", ""),
                            "video_id": video["id"],
                            "playlist_id": playlist["playlist_id"],
                            "playlist_url": playlist.get("url", ""),
                            "transcript_status": "not_requested",
                        },
                    )
                )
        LOGGER.info("Fetched %s new YouTube playlist metadata items", len(results))
        return results

    def _resolve_channel_id(self, handle: str) -> str:
        response = self._youtube_get(
            "search",
            {
                "q": handle,
                "part": "snippet",
                "type": "channel",
                "maxResults": 1,
            },
        )
        items = response.get("items", [])
        if not items:
            raise RuntimeError(f"Unable to resolve channel handle: {handle}")
        return items[0]["snippet"]["channelId"]

    def _fetch_latest_videos(self, channel_id: str, max_results: int) -> list[dict[str, str]]:
        response = self._youtube_get(
            "search",
            {
                "channelId": channel_id,
                "part": "snippet",
                "order": "date",
                "type": "video",
                "maxResults": max_results,
            },
        )
        return [
            {
                "id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "channel_title": item["snippet"]["channelTitle"],
            }
            for item in response.get("items", [])
        ]

    def _fetch_playlist_videos(self, playlist_id: str, max_results: int) -> list[dict[str, str]]:
        response = self._youtube_get(
            "playlistItems",
            {
                "playlistId": playlist_id,
                "part": "snippet",
                "maxResults": max_results,
            },
        )
        videos: list[dict[str, str]] = []
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            resource_id = snippet.get("resourceId", {})
            video_id = resource_id.get("videoId")
            if not video_id:
                continue
            videos.append(
                {
                    "id": video_id,
                    "title": snippet.get("title", "Untitled"),
                    "published_at": snippet.get("publishedAt", utc_now().isoformat().replace("+00:00", "Z")),
                    "channel_title": snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle", ""),
                }
            )
        return videos

    def _fetch_video_detail(self, video_id: str) -> dict[str, Any]:
        response = self._youtube_get(
            "videos",
            {"id": video_id, "part": "contentDetails,statistics,snippet"},
        )
        items = response.get("items", [])
        if not items:
            raise RuntimeError(f"Unable to fetch video details for {video_id}")
        return items[0]

    def _youtube_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = requests.get(
            f"https://www.googleapis.com/youtube/v3/{path}",
            params={**params, "key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _is_short(self, video_id: str) -> bool:
        url = f"https://www.youtube.com/shorts/{video_id}"
        try:
            response = requests.head(url, allow_redirects=True, timeout=self.timeout_seconds)
            parsed = urlparse(response.url)
            return parsed.path.startswith("/shorts/")
        except Exception:
            return False


def _iso_duration_to_seconds(duration: str) -> int:
    pattern = re.compile(
        r"PT"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
    )
    match = pattern.fullmatch(duration)
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds
