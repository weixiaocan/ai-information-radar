from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_days_ago(days: int) -> datetime:
    return utc_now() - timedelta(days=days)
