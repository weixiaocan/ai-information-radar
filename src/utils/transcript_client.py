from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import IpBlocked, RequestBlocked, TranscriptsDisabled, VideoUnavailable

LOGGER = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str | None
    source: str | None
    error: str | None = None


class TranscriptClient:
    def __init__(self, timeout_seconds: int, supadata_api_key: str = "") -> None:
        self.timeout_seconds = timeout_seconds
        self.supadata_api_key = supadata_api_key
        self.youtube_api = YouTubeTranscriptApi()

    def fetch(self, video_id: str, video_url: str) -> TranscriptResult:
        first_try = self._fetch_native(video_id)
        if first_try.text:
            return first_try
        if not self.supadata_api_key:
            return first_try
        second_try = self._fetch_supadata_native(video_url)
        if second_try.text:
            return second_try
        merged_error = "; ".join(part for part in [first_try.error, second_try.error] if part)
        return TranscriptResult(text=None, source=None, error=merged_error or "Transcript unavailable")

    def _fetch_native(self, video_id: str) -> TranscriptResult:
        try:
            transcript = self.youtube_api.fetch(video_id)
            return TranscriptResult(
                text="\n".join(segment.text for segment in transcript),
                source="youtube_transcript_api",
            )
        except (IpBlocked, RequestBlocked, TranscriptsDisabled, VideoUnavailable) as exc:
            return TranscriptResult(text=None, source=None, error=str(exc))
        except Exception as exc:
            LOGGER.warning("Unexpected transcript fetch failure for %s: %s", video_id, exc)
            return TranscriptResult(text=None, source=None, error=str(exc))

    def _fetch_supadata_native(self, video_url: str) -> TranscriptResult:
        try:
            response = requests.get(
                "https://api.supadata.ai/v1/transcript",
                headers={"x-api-key": self.supadata_api_key},
                params={"url": video_url, "text": "true", "mode": "native"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("content")
            if isinstance(content, list):
                text = "\n".join(chunk.get("text", "") for chunk in content if chunk.get("text"))
            elif isinstance(content, str):
                text = content
            else:
                text = payload.get("text") or ""
            return TranscriptResult(text=text or None, source="supadata_native")
        except Exception as exc:
            LOGGER.warning("Supadata native transcript fetch failed for %s: %s", video_url, exc)
            return TranscriptResult(text=None, source=None, error=str(exc))
