from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class ContentItem:
    content_id: str
    source_type: str
    source_name: str
    title: str
    url: str
    author: Optional[str]
    published_at: datetime
    fetched_at: datetime
    body: str
    body_type: str
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    ai_summary: Optional[str] = None
    ai_keywords: list[str] = field(default_factory=list)
    ai_score: Optional[dict[str, Any]] = None
    ai_score_reasons: Optional[dict[str, str]] = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat()
        data["fetched_at"] = self.fetched_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ContentItem":
        payload = dict(payload)
        payload["published_at"] = _coerce_datetime(payload["published_at"])
        payload["fetched_at"] = _coerce_datetime(payload["fetched_at"])
        payload.setdefault("ai_keywords", [])
        payload.setdefault("extra_metadata", {})
        return cls(**payload)


def _coerce_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)

