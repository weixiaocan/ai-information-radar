from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.daily_state import (
    builder_candidate_copy,
    builder_candidate_decision,
    normalize_theme,
    with_degraded_fields,
)
from src.utils.llm_client import DeepSeekClient
from src.utils.source_labels import get_original_source_name

LOGGER = logging.getLogger(__name__)


@dataclass
class ThemeAggregator:
    client: DeepSeekClient
    prompt_path: Path
    copy_prompt_path: Path | None = None

    def aggregate_themes(
        self,
        today_items: list[ContentItem],
        builder_hot_candidates: list[dict[str, Any]] | None = None,
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
                return with_degraded_fields(
                    self._empty_result(signals, source_by_url, source_by_content_id),
                    degraded_reason="theme_membership_failed",
                    degraded_stage="theme_decision",
                    fallback_mode="spotlight_only",
                )

            decisions_payload = self._fetch_theme_decisions(today_items, signals)
            normalized_decisions = self._normalize_decisions(decisions_payload)
            if not normalized_decisions["themes"]:
                return with_degraded_fields(
                    self._empty_result(signals, source_by_url, source_by_content_id),
                    degraded_reason="theme_membership_failed",
                    degraded_stage="theme_decision",
                    fallback_mode="spotlight_only",
                )

            copy_payload = self._fetch_theme_copy(today_items, signals, normalized_decisions)
            normalized = self._normalize_copy(
                copy_payload,
                normalized_decisions,
                signals,
                source_by_url,
                source_by_content_id,
            )
        except Exception:
            LOGGER.exception("Theme aggregation failed")
            return with_degraded_fields(
                {"themes": [], "discussion_dispersion": "dispersed", "spotlight_posts": []},
                degraded_reason="theme_membership_failed",
                degraded_stage="theme_decision",
                fallback_mode="empty_themes",
            )

        if not normalized.get("themes"):
            return with_degraded_fields(
                self._empty_result(signals, source_by_url, source_by_content_id),
                degraded_reason="theme_membership_failed",
                degraded_stage="theme_decision",
                fallback_mode="spotlight_only",
            )
        if any(theme.get("degraded_stage") for theme in normalized.get("themes", [])):
            return with_degraded_fields(
                normalized,
                degraded_reason="theme_copy_failed",
                degraded_stage="theme_copy",
                fallback_mode="theme_copy_from_signals",
            )
        return normalized

    def _fetch_theme_decisions(
        self,
        today_items: list[ContentItem],
        signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        flattened = [self._flatten_builder_signal(signal) for signal in signals]
        payload = self.client.daily_theme_decisions(str(self.prompt_path), today_items, theme_signals=flattened)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            issues = self._collect_decision_issues(payload)
            if not issues:
                break
            if attempt == max_attempts:
                LOGGER.warning("Theme decision still invalid after %s attempts: %s", attempt, issues)
                break
            payload = self.client.daily_theme_decisions(
                str(self.prompt_path),
                today_items,
                theme_signals=flattened,
                feedback=issues,
            )
        return payload

    def _fetch_theme_copy(
        self,
        today_items: list[ContentItem],
        signals: list[dict[str, Any]],
        normalized_decisions: dict[str, Any],
    ) -> dict[str, Any]:
        flattened = [self._flatten_builder_signal(signal) for signal in signals]
        decision_payload = [
            {
                "theme_id": theme["decision"]["theme_id"],
                "member_content_ids": theme["decision"]["member_content_ids"],
            }
            for theme in normalized_decisions["themes"]
        ]
        payload = self.client.daily_theme_copy(
            str(self.copy_prompt_path or self.prompt_path),
            today_items,
            decision_payload,
            theme_signals=flattened,
        )
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            issues = self._collect_issues(payload)
            if not issues:
                break
            if attempt == max_attempts:
                LOGGER.warning("Theme copy still invalid after %s attempts: %s", attempt, issues)
                break
            payload = self.client.daily_theme_copy(
                str(self.copy_prompt_path or self.prompt_path),
                today_items,
                decision_payload,
                theme_signals=flattened,
                feedback=issues,
            )
        return payload

    def _collect_decision_issues(self, payload: dict[str, Any] | None) -> list[str]:
        data = payload or {}
        seen_members: set[str] = set()
        issues: list[str] = []
        for theme_index, theme in enumerate(data.get("themes", [])[:3], start=1):
            member_ids = [
                str(content_id).strip()
                for content_id in theme.get("member_content_ids", [])
                if str(content_id).strip()
            ]
            if len(member_ids) < 3:
                issues.append(f"Theme {theme_index} must include at least 3 member_content_ids.")
            for content_id in member_ids:
                if content_id in seen_members:
                    issues.append(f"Theme {theme_index} reuses member_content_id {content_id}.")
                seen_members.add(content_id)
        return issues

    def _collect_issues(self, payload: dict[str, Any] | None) -> list[str]:
        data = payload or {}
        issues: list[str] = []
        seen_urls: dict[str, int] = {}

        for theme_index, theme in enumerate(data.get("themes", [])[:3], start=1):
            summary = str(theme.get("theme_summary") or theme.get("summary") or "").strip()
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
                if source and self._starts_with_source_attribution(source, excerpt):
                    issues.append(
                        f"Theme {theme_index} evidence {evidence_index} should not repeat the source name at the start."
                    )
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
                    issues.append(f"Theme {theme_index} repeats source {source} {count} times; merge if redundant.")
            if summary:
                for evidence_index, excerpt in enumerate(evidence_excerpts, start=1):
                    if self._is_summary_too_similar_to_evidence(summary, excerpt):
                        issues.append(
                            f"Theme {theme_index} summary is too similar to evidence {evidence_index}; summarize the pattern instead."
                        )
                        break
        return issues

    def _normalize_decisions(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        data = payload or {}
        dispersion = str(data.get("discussion_dispersion", "dispersed")).strip() or "dispersed"
        themes = []
        for index, theme in enumerate(data.get("themes", [])[:3], start=1):
            member_content_ids = [
                str(content_id).strip()
                for content_id in theme.get("member_content_ids", [])
                if str(content_id).strip()
            ]
            if len(member_content_ids) < 3:
                continue
            themes.append(
                normalize_theme(
                    {
                        "decision": {
                            "theme_id": str(theme.get("theme_id", "")).strip() or f"theme_{index}",
                            "member_content_ids": member_content_ids,
                            "representative_urls": [],
                            "discussion_dispersion": dispersion,
                        },
                        "copy": {
                            "theme_title": "",
                            "theme_summary": "",
                            "evidence": [],
                        },
                    }
                )
            )
        if not themes:
            dispersion = "dispersed"
        return {
            "themes": themes,
            "discussion_dispersion": dispersion,
        }

    def _normalize_copy(
        self,
        payload: dict[str, Any] | None,
        normalized_decisions: dict[str, Any],
        signals: list[dict[str, Any]],
        source_by_url: dict[str, str],
        source_by_content_id: dict[str, str],
    ) -> dict[str, Any]:
        signal_by_content_id = {
            builder_candidate_decision(signal).get("content_id", ""): signal
            for signal in signals
            if builder_candidate_decision(signal).get("content_id")
        }
        raw_copy_by_theme_id: dict[str, dict[str, Any]] = {}
        for index, theme in enumerate((payload or {}).get("themes", [])[:3], start=1):
            theme_id = str(theme.get("theme_id", "")).strip() or f"theme_{index}"
            raw_copy_by_theme_id[theme_id] = theme

        themes: list[dict[str, Any]] = []
        for decision_theme in normalized_decisions["themes"]:
            decision = decision_theme["decision"]
            copy_payload = raw_copy_by_theme_id.get(decision["theme_id"], {})
            normalized = self._build_theme_from_decision(
                decision=decision,
                copy_payload=copy_payload,
                signal_by_content_id=signal_by_content_id,
                source_by_url=source_by_url,
                source_by_content_id=source_by_content_id,
            )
            themes.append(normalized)

        dispersion = normalized_decisions["discussion_dispersion"]
        if not themes:
            dispersion = "dispersed"
        return {
            "themes": themes,
            "discussion_dispersion": dispersion,
            "spotlight_posts": [],
            "supplementary_spotlight_posts": [],
        }

    def _build_theme_from_decision(
        self,
        *,
        decision: dict[str, Any],
        copy_payload: dict[str, Any],
        signal_by_content_id: dict[str, dict[str, Any]],
        source_by_url: dict[str, str],
        source_by_content_id: dict[str, str],
    ) -> dict[str, Any]:
        member_content_ids = list(decision.get("member_content_ids", []))
        fallback_evidence = self._fallback_theme_evidence(member_content_ids, signal_by_content_id)
        evidence_payloads = []
        for entry in copy_payload.get("evidence", [])[:4]:
            url = str(entry.get("url", "")).strip()
            source = self._resolve_source_name(
                str(entry.get("source", "")).strip(),
                url,
                member_content_ids,
                source_by_url,
                source_by_content_id,
            )
            excerpt = self._normalize_evidence_excerpt(source, str(entry.get("excerpt", "")).strip())
            if not excerpt:
                continue
            evidence_payloads.append(
                {
                    "source": source,
                    "excerpt": excerpt,
                    "url": url,
                }
            )
        if not evidence_payloads:
            evidence_payloads = fallback_evidence

        fallback_title, fallback_summary = self._fallback_theme_copy(member_content_ids, signal_by_content_id)
        theme_title = str(copy_payload.get("theme_title") or copy_payload.get("theme") or "").strip() or fallback_title
        theme_summary = str(copy_payload.get("theme_summary") or copy_payload.get("summary") or "").strip() or fallback_summary
        theme_payload = normalize_theme(
            {
                "decision": {
                    "theme_id": decision["theme_id"],
                    "member_content_ids": member_content_ids,
                    "representative_urls": [item["url"] for item in evidence_payloads if item.get("url")],
                    "discussion_dispersion": decision["discussion_dispersion"],
                },
                "copy": {
                    "theme_title": theme_title,
                    "theme_summary": theme_summary,
                    "evidence": evidence_payloads,
                },
            }
        )
        if not copy_payload.get("theme_title") or not copy_payload.get("theme_summary") or not copy_payload.get("evidence"):
            return with_degraded_fields(
                theme_payload,
                degraded_reason="theme_copy_failed",
                degraded_stage="theme_copy",
                fallback_mode="copy_from_member_signals",
            )
        return theme_payload

    def _fallback_theme_copy(
        self,
        member_content_ids: list[str],
        signal_by_content_id: dict[str, dict[str, Any]],
    ) -> tuple[str, str]:
        topic_labels: list[str] = []
        core_claims: list[str] = []
        for content_id in member_content_ids:
            signal = signal_by_content_id.get(content_id)
            if not signal:
                continue
            copy = builder_candidate_copy(signal)
            if copy.get("topic_label"):
                topic_labels.append(str(copy["topic_label"]))
            if copy.get("core_claim"):
                core_claims.append(str(copy["core_claim"]))
        title = topic_labels[0] if topic_labels else "Builder 热议"
        summary = core_claims[0] if core_claims else "多位 builder 围绕同一件事形成了集中讨论。"
        return title, summary

    def _fallback_theme_evidence(
        self,
        member_content_ids: list[str],
        signal_by_content_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        evidence_payloads: list[dict[str, str]] = []
        for content_id in member_content_ids[:4]:
            signal = signal_by_content_id.get(content_id)
            if not signal:
                continue
            decision = builder_candidate_decision(signal)
            copy = builder_candidate_copy(signal)
            source = str(decision.get("source", "")).strip()
            evidence_payloads.append(
                {
                    "source": source,
                    "excerpt": self._normalize_evidence_excerpt(
                        source,
                        str(copy.get("excerpt") or copy.get("core_claim") or "").strip(),
                    ),
                    "url": str(decision.get("url", "")).strip(),
                }
            )
        return [entry for entry in evidence_payloads if entry["excerpt"]]

    def _empty_result(
        self,
        signals: list[dict[str, Any]] | None = None,
        source_by_url: dict[str, str] | None = None,
        source_by_content_id: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        ranked_posts = [
            {
                "source": self._resolve_source_name(
                    builder_candidate_decision(signal).get("source", ""),
                    builder_candidate_decision(signal).get("url", ""),
                    [builder_candidate_decision(signal).get("content_id", "")],
                    source_by_url or {},
                    source_by_content_id or {},
                ),
                "text": builder_candidate_copy(signal).get("spotlight_text")
                or builder_candidate_copy(signal).get("core_claim", ""),
                "url": builder_candidate_decision(signal).get("url", ""),
            }
            for signal in (signals or [])[:10]
            if builder_candidate_decision(signal).get("source")
            and builder_candidate_decision(signal).get("url")
            and (builder_candidate_copy(signal).get("spotlight_text") or builder_candidate_copy(signal).get("core_claim"))
        ]
        return {
            "themes": [],
            "discussion_dispersion": "dispersed",
            "spotlight_posts": ranked_posts[:5],
            "supplementary_spotlight_posts": ranked_posts[5:10],
        }

    def _flatten_builder_signal(self, signal: dict[str, Any]) -> dict[str, str]:
        decision = builder_candidate_decision(signal)
        copy = builder_candidate_copy(signal)
        return {
            "content_id": str(decision.get("content_id", "")).strip(),
            "source": str(decision.get("source", "")).strip(),
            "url": str(decision.get("url", "")).strip(),
            "topic_label": str(copy.get("topic_label", "")).strip(),
            "core_claim": str(copy.get("core_claim", "")).strip(),
            "angle": str(copy.get("angle", "")).strip(),
            "excerpt": str(copy.get("excerpt", "")).strip(),
            "spotlight_text": str(copy.get("spotlight_text", "")).strip(),
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

    def _normalize_evidence_excerpt(self, source: str, excerpt: str) -> str:
        normalized = excerpt.strip()
        if not normalized or not source.strip():
            return normalized

        source_name = re.escape(source.strip())
        patterns = [
            rf"^{source_name}\s*[:：,，\-]\s*",
            rf"^{source_name}\s+(表示|认为|指出|提到|分享|分析|建议|说)(?:了)?\s*",
            rf"^{source_name}\s*",
        ]
        for pattern in patterns:
            updated = re.sub(pattern, "", normalized, count=1).strip()
            if updated and updated != normalized:
                return updated
        return normalized

    def _starts_with_source_attribution(self, source: str, excerpt: str) -> bool:
        normalized = excerpt.strip()
        if not normalized or not source.strip():
            return False
        source_name = re.escape(source.strip())
        return bool(
            re.match(
                rf"^{source_name}(?:\s*[:：,，\-]\s*|\s+(?:表示|认为|指出|提到|分享|分析|建议|说)(?:了)?\s+|\s+)",
                normalized,
            )
        )

    def _is_summary_too_similar_to_evidence(self, summary: str, excerpt: str) -> bool:
        summary_norm = self._normalize_similarity_text(summary)
        excerpt_norm = self._normalize_similarity_text(excerpt)
        if not summary_norm or not excerpt_norm:
            return False
        if summary_norm == excerpt_norm:
            return True
        shorter, longer = sorted((summary_norm, excerpt_norm), key=len)
        if len(shorter) >= 12 and shorter in longer:
            return True
        if SequenceMatcher(None, summary_norm, excerpt_norm).ratio() >= 0.6:
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
