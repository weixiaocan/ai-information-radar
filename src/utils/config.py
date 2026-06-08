from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class Settings:
    project_root: Path
    youtube_api_key: str
    deepseek_api_key: str
    supadata_api_key: str
    deepseek_base_url: str
    feishu_webhook_url: str
    gmail_credentials_path: Path | None = None
    gmail_token_path: Path | None = None
    site_publish_enabled: bool = False
    site_repo_path: Path | None = None
    site_git_branch: str = "main"
    site_publish_timeout_seconds: int = 60
    site_push_retry_delays_seconds: tuple[int, ...] = (180, 300, 600)
    weekly_ebook_export_dir: Path | None = Path(r"D:\huangxh\AI_Projects_100\p13_公众号文章\AI_RADAR")
    request_timeout_seconds: int = 30
    zara_retry_attempts: int = 4
    zara_retry_delays_seconds: tuple[int, ...] = (60, 180, 600)
    zara_retry_window_seconds: int = 960
    zara_x_refresh_retry_attempts: int = 4
    zara_x_refresh_retry_delays_seconds: tuple[int, ...] = (60, 180, 600)
    zara_x_refresh_retry_window_seconds: int = 960
    bootstrap_days: int = 7
    incremental_days: int = 1
    tier2_candidate_count: int = 5


def load_settings(project_root: Path | None = None) -> Settings:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    load_dotenv(root / ".env")
    return Settings(
        project_root=root,
        youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        supadata_api_key=os.getenv("SUPADATA_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", ""),
        gmail_credentials_path=_resolve_optional_path(root, os.getenv("GMAIL_CREDENTIALS_PATH", "")),
        gmail_token_path=_resolve_optional_path(root, os.getenv("GMAIL_TOKEN_PATH", "")),
        site_publish_enabled=os.getenv("SITE_PUBLISH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        site_repo_path=_resolve_optional_path(root, os.getenv("SITE_REPO_PATH", "..\\ai-radar-site")),
        site_git_branch=os.getenv("SITE_GIT_BRANCH", "main"),
        site_publish_timeout_seconds=int(os.getenv("SITE_PUBLISH_TIMEOUT_SECONDS", "60")),
        site_push_retry_delays_seconds=_parse_int_tuple(os.getenv("SITE_PUSH_RETRY_DELAYS_SECONDS", "180,300,600")),
        weekly_ebook_export_dir=_resolve_optional_path(
            root,
            os.getenv(
                "WEEKLY_EBOOK_EXPORT_DIR",
                r"D:\huangxh\AI_Projects_100\p13_公众号文章\AI_RADAR",
            ),
        ),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        zara_retry_attempts=int(os.getenv("ZARA_RETRY_ATTEMPTS", "4")),
        zara_retry_delays_seconds=_parse_int_tuple(os.getenv("ZARA_RETRY_DELAYS_SECONDS", "60,180,600")),
        zara_retry_window_seconds=int(os.getenv("ZARA_RETRY_WINDOW_SECONDS", "960")),
        zara_x_refresh_retry_attempts=int(os.getenv("ZARA_X_REFRESH_RETRY_ATTEMPTS", "4")),
        zara_x_refresh_retry_delays_seconds=_parse_int_tuple(
            os.getenv("ZARA_X_REFRESH_RETRY_DELAYS_SECONDS", "60,180,600")
        ),
        zara_x_refresh_retry_window_seconds=int(os.getenv("ZARA_X_REFRESH_RETRY_WINDOW_SECONDS", "960")),
        bootstrap_days=int(os.getenv("BOOTSTRAP_DAYS", "7")),
        incremental_days=int(os.getenv("INCREMENTAL_DAYS", "1")),
        tier2_candidate_count=int(os.getenv("TIER2_CANDIDATE_COUNT", "5")),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _resolve_optional_path(project_root: Path, raw_path: str) -> Path | None:
    candidate = raw_path.strip()
    if not candidate:
        return None
    path = Path(candidate)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return path


def _parse_int_tuple(raw_value: str) -> tuple[int, ...]:
    values = [segment.strip() for segment in raw_value.split(",")]
    return tuple(int(value) for value in values if value)
