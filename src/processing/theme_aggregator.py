from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient

LOGGER = logging.getLogger(__name__)


@dataclass
class ThemeAggregator:
    client: DeepSeekClient
    prompt_path: Path

    def aggregate_themes(
        self,
        today_items: list[ContentItem],
        builder_hot_candidates: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not today_items:
            return {"themes": [], "discussion_dispersion": "dispersed", "spotlight_posts": []}

        signals = list(builder_hot_candidates or [])
        if not signals:
            return {"themes": [], "discussion_dispersion": "dispersed", "spotlight_posts": []}

        try:
            if len(signals) < 3:
                return self._empty_result(signals)

            payload = self.client.daily_themes(
                str(self.prompt_path),
                today_items,
                theme_signals=signals,
            )
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                issues = self._collect_issues(payload)
                if not issues:
                    break
                if attempt == max_attempts:
                    LOGGER.warning("Theme aggregation still invalid after %s attempts: %s", attempt, issues)
                    return self._empty_result(signals)
                LOGGER.info("Theme aggregation failed validation on attempt %s; retrying with feedback: %s", attempt, issues)
                payload = self.client.daily_themes(
                    str(self.prompt_path),
                    today_items,
                    theme_signals=signals,
                    feedback=issues,
                )
        except Exception:
            LOGGER.exception("Theme aggregation failed")
            return {"themes": [], "discussion_dispersion": "dispersed", "spotlight_posts": []}

        normalized = self._normalize(payload)
        if not normalized.get("themes"):
            return self._empty_result(signals)
        return normalized

    def _collect_issues(self, payload: dict[str, Any] | None) -> list[str]:
        data = payload or {}
        issues: list[str] = []
        seen_urls: dict[str, int] = {}

        for theme_index, theme in enumerate(data.get("themes", [])[:3], start=1):
            summary = str(theme.get("summary", "")).strip()
            if summary:
                if self._looks_mostly_english(summary):
                    issues.append(f"主题{theme_index}的 summary 不是中文句子，请改成自然中文")
                if summary.count("，") >= 3:
                    issues.append(f"主题{theme_index}的 summary 信息塞太满，请压成一个核心意思")

            source_counter: Counter[str] = Counter()
            for evidence_index, evidence in enumerate(theme.get("evidence", [])[:4], start=1):
                source = str(evidence.get("source", "")).strip()
                excerpt = str(evidence.get("excerpt", "")).strip()
                url = str(evidence.get("url", "")).strip()
                if source:
                    source_counter[source] += 1
                if not excerpt:
                    issues.append(f"主题{theme_index}的 evidence {evidence_index} 缺少 excerpt")
                    continue
                if self._looks_mostly_english(excerpt):
                    issues.append(f"主题{theme_index}的 evidence {evidence_index} 不是中文，请改成中文事实句")
                if len(excerpt) > 60:
                    issues.append(f"主题{theme_index}的 evidence {evidence_index} 太长，请压到 60 字以内")
                if not url:
                    issues.append(f"主题{theme_index}的 evidence {evidence_index} 缺少原始链接 url")
                    continue
                if url in seen_urls:
                    issues.append(
                        f"主题{theme_index}的 evidence {evidence_index} 与主题{seen_urls[url]}重复使用了同一条原始发言，请只保留在最契合的一个主题里"
                    )
                else:
                    seen_urls[url] = theme_index

            for source, count in source_counter.items():
                if count > 1:
                    issues.append(
                        f"主题{theme_index}中 {source} 出现了 {count} 次，请确认这些 evidence 是否提供不同维度的新信息；若只是同义重复，请合并为一条"
                    )
        return issues

    def _normalize(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        data = payload or {}
        themes: list[dict[str, Any]] = []
        for theme in data.get("themes", [])[:3]:
            evidence_payloads = []
            for entry in theme.get("evidence", [])[:4]:
                excerpt = str(entry.get("excerpt", "")).strip()
                if not excerpt:
                    continue
                evidence_payloads.append(
                    {
                        "source": str(entry.get("source", "未知来源")).strip() or "未知来源",
                        "excerpt": excerpt,
                        "url": str(entry.get("url", "")).strip(),
                    }
                )
            themes.append(
                {
                    "theme": str(theme.get("theme", "未命名主题")).strip() or "未命名主题",
                    "summary": str(theme.get("summary", "")).strip(),
                    "evidence": evidence_payloads,
                    "related_content_ids": [
                        str(content_id).strip()
                        for content_id in theme.get("related_content_ids", [])
                        if str(content_id).strip()
                    ],
                }
            )
        dispersion = str(data.get("discussion_dispersion", "dispersed")).strip() or "dispersed"
        if not themes:
            dispersion = "dispersed"
        return {"themes": themes, "discussion_dispersion": dispersion, "spotlight_posts": []}

    def _empty_result(self, signals: list[dict[str, str]]) -> dict[str, Any]:
        spotlight_posts = [
            {
                "source": signal["source"],
                "text": signal.get("spotlight_text") or signal["core_claim"],
                "url": signal["url"],
            }
            for signal in signals[:4]
        ]
        return {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": spotlight_posts,
        }

    def _looks_mostly_english(self, text: str) -> bool:
        ascii_letters = len(re.findall(r"[A-Za-z]", text))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        return ascii_letters >= 12 and ascii_letters > chinese_chars
