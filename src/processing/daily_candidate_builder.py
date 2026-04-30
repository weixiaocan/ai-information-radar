from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient


@dataclass
class DailyCandidateBuilder:
    client: DeepSeekClient
    signal_prompt_path: Path

    def build(self, today_items: list[ContentItem]) -> dict[str, Any]:
        builder_items = [item for item in today_items if item.source_type == "zara_x"]
        editorial_items = [item for item in today_items if item.source_type != "zara_x"]
        builder_hot_candidates = self._build_builder_hot_candidates(builder_items)
        editorial_candidates = self._build_editorial_candidates(editorial_items)
        return {
            "builder_hot_candidates": builder_hot_candidates,
            "editorial_candidates": editorial_candidates,
        }

    def _build_builder_hot_candidates(self, builder_items: list[ContentItem]) -> list[dict[str, str]]:
        if not builder_items:
            return []
        payload = self.client.daily_theme_signals(str(self.signal_prompt_path), builder_items)
        items_by_id = {item.content_id: item for item in builder_items}
        candidates: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for signal in payload.get("signals", []):
            content_id = str(signal.get("content_id", "")).strip()
            source = str(signal.get("source", "")).strip()
            url = str(signal.get("url", "")).strip()
            topic_label = str(signal.get("topic_label", "")).strip()
            core_claim = str(signal.get("core_claim", "")).strip()
            angle = str(signal.get("angle", "")).strip()
            excerpt = str(signal.get("excerpt", "")).strip()
            spotlight_text = str(signal.get("spotlight_text", "")).strip()
            if not all([content_id, source, url, topic_label, core_claim, excerpt]):
                continue
            if url in seen_urls:
                continue
            item = items_by_id.get(content_id)
            if item and self._is_weak_signal(item, topic_label, core_claim, excerpt):
                continue
            seen_urls.add(url)
            candidates.append(
                {
                    "content_id": content_id,
                    "source": source,
                    "url": url,
                    "topic_label": topic_label,
                    "core_claim": core_claim,
                    "angle": angle,
                    "excerpt": excerpt,
                    "spotlight_text": spotlight_text or core_claim,
                }
            )
        return candidates

    def _build_editorial_candidates(self, editorial_items: list[ContentItem]) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        for item in editorial_items:
            candidates.append(
                {
                    "content_id": item.content_id,
                    "type": "youtube" if item.source_type == "youtube" else "article",
                    "channel_or_source": item.source_name,
                    "title": item.title,
                    "url": item.url,
                    "summary": item.ai_summary or item.body[:240],
                }
            )
        return candidates

    def _is_weak_signal(
        self,
        item: ContentItem,
        topic_label: str,
        core_claim: str,
        excerpt: str,
    ) -> bool:
        import re

        raw_text = str(item.extra_metadata.get("raw_entry", {}).get("content") or item.body or "")
        normalized_text = re.sub(r"https?://\S+", " ", raw_text)
        normalized_text = re.sub(r"\s+", " ", normalized_text).strip()
        ascii_words = re.findall(r"[A-Za-z]{2,}", normalized_text)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized_text)
        info_units = len(ascii_words) + len(chinese_chars)

        generic_patterns = [
            "分享链接",
            "表示不可思议",
            "感到好笑",
            "询问",
            "高度尊重",
            "怀疑信息泄漏",
            "调侃",
        ]
        combined = " ".join([topic_label, core_claim, excerpt])
        if any(pattern in combined for pattern in generic_patterns):
            return True
        if info_units < 35:
            return True
        if len(re.findall(r"[.!?。！？]\s*", normalized_text)) <= 1 and info_units < 60:
            return True
        return False
