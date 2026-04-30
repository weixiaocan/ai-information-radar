from __future__ import annotations

from pathlib import Path

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient


class Tier1Summarizer:
    def __init__(self, client: DeepSeekClient, prompt_path: Path) -> None:
        self.client = client
        self.prompt_path = prompt_path

    def run(self, items: list[ContentItem]) -> list[ContentItem]:
        for item in items:
            response = self.client.summarize(str(self.prompt_path), item)
            item.ai_summary = response["summary"]
            item.ai_keywords = response.get("keywords", [])
        return items

