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
    request_timeout_seconds: int = 30
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
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        bootstrap_days=int(os.getenv("BOOTSTRAP_DAYS", "7")),
        incremental_days=int(os.getenv("INCREMENTAL_DAYS", "1")),
        tier2_candidate_count=int(os.getenv("TIER2_CANDIDATE_COUNT", "5")),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
