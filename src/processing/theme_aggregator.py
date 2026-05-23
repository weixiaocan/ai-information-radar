from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient
from src.utils.source_labels import get_original_source_name

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
        source_by_url = {item.url: get_original_source_name(item) for item in today_items if item.url}
        source_by_content_id = {item.content_id: get_original_source_name(item) for item in today_items}
        if not signals:
            return {"themes": [], "discussion_dispersion": "dispersed", "spotlight_posts": []}

        try:
            if len(signals) < 3:
                return self._empty_result(signals, source_by_url, source_by_content_id)

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
                    return self._empty_result(signals, source_by_url, source_by_content_id)
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

        normalized = self._normalize(payload, source_by_url, source_by_content_id)
        if not normalized.get("themes"):
            return self._empty_result(signals, source_by_url, source_by_content_id)
        return normalized

    def _collect_issues(self, payload: dict[str, Any] | None) -> list[str]:
        data = payload or {}
        issues: list[str] = []
        seen_urls: dict[str, int] = {}

        for theme_index, theme in enumerate(data.get("themes", [])[:3], start=1):
            summary = str(theme.get("summary", "")).strip()
            if summary:
                if self._looks_mostly_english(summary):
                    issues.append(f"Theme {theme_index} summary must be written in Chinese.")
                if summary.count("，") >= 3:
                    issues.append(f"Theme {theme_index} summary is overloaded; compress it to one core idea.")

            source_counter: Counter[str] = Counter()
            evidence_excerpts: list[str] = []
            for evidence_index, evidence in enumerate(theme.get("evidence", [])[:4], start=1):
                source = str(evidence.get("source", "")).strip()
                excerpt = str(evidence.get("excerpt", "")).strip()
                url = str(evidence.get("url", "")).strip()
                if source:
                    source_counter[source] += 1
                if not excerpt:
                    issues.append(f"Theme {theme_index} evidence {evidence_index} is missing excerpt.")
                    continue
                if self._looks_mostly_english(excerpt):
                    issues.append(f"Theme {theme_index} evidence {evidence_index} must be written in Chinese.")
                if len(excerpt) > 60:
                    issues.append(f"Theme {theme_index} evidence {evidence_index} is too long; keep it within 60 chars.")
                evidence_excerpts.append(excerpt)
                if not url:
                    issues.append(f"Theme {theme_index} evidence {evidence_index} is missing the original url.")
                    continue
                if url in seen_urls:
                    issues.append(
                        f"Theme {theme_index} evidence {evidence_index} reuses a post already used by theme {seen_urls[url]}."
                    )
                else:
                    seen_urls[url] = theme_index

            for source, count in source_counter.items():
                if count > 1:
                    issues.append(
                        f"Theme {theme_index} repeats source {source} {count} times; merge if they do not add distinct evidence."
                    )
            if summary:
                for evidence_index, excerpt in enumerate(evidence_excerpts, start=1):
                    if self._is_summary_too_similar_to_evidence(summary, excerpt):
                        issues.append(
                            f"Theme {theme_index} summary is too similar to evidence {evidence_index}; summarize the pattern instead of repeating one post."
                        )
                        break
        return issues

    def _normalize(
        self,
        payload: dict[str, Any] | None,
        source_by_url: dict[str, str],
        source_by_content_id: dict[str, str],
    ) -> dict[str, Any]:
        data = payload or {}
        themes: list[dict[str, Any]] = []
        for theme in data.get("themes", [])[:3]:
            related_content_ids = [
                str(content_id).strip()
                for content_id in theme.get("related_content_ids", [])
                if str(content_id).strip()
            ]
            evidence_payloads = []
            for entry in theme.get("evidence", [])[:4]:
                excerpt = str(entry.get("excerpt", "")).strip()
                if not excerpt:
                    continue
                url = str(entry.get("url", "")).strip()
                evidence_payloads.append(
                    {
                        "source": self._resolve_source_name(
                            str(entry.get("source", "")).strip(),
                            url,
                            related_content_ids,
                            source_by_url,
                            source_by_content_id,
                        ),
                        "excerpt": excerpt,
                        "url": url,
                    }
                )
            themes.append(
                {
                    "theme": str(theme.get("theme", "Unnamed theme")).strip() or "Unnamed theme",
                    "summary": str(theme.get("summary", "")).strip(),
                    "evidence": evidence_payloads,
                    "related_content_ids": related_content_ids,
                }
            )
        dispersion = str(data.get("discussion_dispersion", "dispersed")).strip() or "dispersed"
        if not themes:
            dispersion = "dispersed"
        return {
            "themes": themes,
            "discussion_dispersion": dispersion,
            "spotlight_posts": [],
            "supplementary_spotlight_posts": [],
        }

    def _empty_result(
        self,
        signals: list[dict[str, str]] | None = None,
        source_by_url: dict[str, str] | None = None,
        source_by_content_id: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        ranked_posts = [
            {
                "source": self._resolve_source_name(
                    str(signal.get("source", "")).strip(),
                    str(signal.get("url", "")).strip(),
                    [str(signal.get("content_id", "")).strip()],
                    source_by_url or {},
                    source_by_content_id or {},
                ),
                "text": signal.get("spotlight_text") or signal["core_claim"],
                "url": signal["url"],
            }
            for signal in (signals or [])[:10]
            if signal.get("source") and signal.get("url") and (signal.get("spotlight_text") or signal.get("core_claim"))
        ]
        return {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": ranked_posts[:5],
            "supplementary_spotlight_posts": ranked_posts[5:10],
        }

    def _resolve_source_name(
        self,
        raw_source: str,
        url: str,
        related_content_ids: list[str],
        source_by_url: dict[str, str],
        source_by_content_id: dict[str, str],
    ) -> str:
        authoritative = source_by_url.get(url, "")
        if not authoritative:
            for content_id in related_content_ids:
                authoritative = source_by_content_id.get(content_id, "")
                if authoritative:
                    break
        if authoritative:
            return authoritative
        if raw_source and not self._is_generic_builder_source(raw_source):
            return raw_source
        return raw_source or "Unknown source"

    def _is_generic_builder_source(self, source: str) -> bool:
        normalized = re.sub(r"[^a-z]+", "", source.lower())
        return normalized in {"x", "twitter", "tweet", "tweets", "builder", "builders", "xpost", "xposts"}

    def _looks_mostly_english(self, text: str) -> bool:
        ascii_letters = len(re.findall(r"[A-Za-z]", text))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        return ascii_letters >= 12 and ascii_letters > chinese_chars

    def _is_summary_too_similar_to_evidence(self, summary: str, excerpt: str) -> bool:
        summary_norm = self._normalize_similarity_text(summary)
        excerpt_norm = self._normalize_similarity_text(excerpt)
        if not summary_norm or not excerpt_norm:
            return False
        if summary_norm == excerpt_norm:
            return True
        summary_tokens = set(summary_norm.split())
        excerpt_tokens = set(excerpt_norm.split())
        if not summary_tokens or not excerpt_tokens:
            return False
        overlap = len(summary_tokens & excerpt_tokens) / min(len(summary_tokens), len(excerpt_tokens))
        return overlap >= 0.75

    def _normalize_similarity_text(self, text: str) -> str:
        normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", text.lower())
        normalized = re.sub(r"\b[a-z]{1,3}\b", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
