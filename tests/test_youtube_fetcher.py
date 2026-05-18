import unittest
from datetime import datetime, timezone

from src.ingestion.youtube_fetcher import YouTubeFetcher


class _StubYouTubeFetcher(YouTubeFetcher):
    def __init__(self) -> None:
        self.api_key = "test"
        self.timeout_seconds = 30
        self._runtime_diagnostics_logged = False

    def _resolve_channel_id(self, handle: str) -> str:
        if handle == "@broken":
            raise RuntimeError("timeout")
        return f"id-{handle}"

    def _fetch_latest_videos(self, channel_id: str, max_results: int) -> list[dict[str, str]]:
        return [
            {
                "id": "video-1",
                "title": "Working video",
                "published_at": "2026-05-17T12:00:00Z",
                "channel_title": "Working Channel",
            }
        ]

    def _fetch_playlist_videos(self, playlist_id: str, max_results: int) -> list[dict[str, str]]:
        if playlist_id == "broken-playlist":
            raise RuntimeError("timeout")
        return [
            {
                "id": "video-2",
                "title": "Playlist video",
                "published_at": "2026-05-17T12:00:00Z",
                "channel_title": "Playlist Channel",
            }
        ]

    def _fetch_video_detail(self, video_id: str) -> dict:
        return {
            "contentDetails": {"duration": "PT30M"},
            "statistics": {"viewCount": "100", "likeCount": "10", "commentCount": "1"},
            "snippet": {"description": f"Description for {video_id}"},
        }

    def _is_short(self, video_id: str) -> bool:
        return False


class YouTubeFetcherTest(unittest.TestCase):
    def test_fetch_continues_after_channel_failure(self) -> None:
        fetcher = _StubYouTubeFetcher()

        items = fetcher.fetch(
            channels=[
                {"name": "broken", "handle": "@broken", "enabled": True},
                {"name": "working", "handle": "@working", "enabled": True},
            ],
            seen_ids=set(),
            recent_days=7,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_id, "youtube_video-1")
        self.assertEqual(items[0].source_name, "working")

    def test_fetch_playlists_continues_after_playlist_failure(self) -> None:
        fetcher = _StubYouTubeFetcher()

        items = fetcher.fetch_playlists(
            playlists=[
                {"name": "broken_playlist", "playlist_id": "broken-playlist", "enabled": True},
                {"name": "working_playlist", "playlist_id": "working-playlist", "enabled": True},
            ],
            seen_ids=set(),
            recent_days=7,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_id, "youtube_video-2")
        self.assertEqual(items[0].source_name, "working_playlist")
