from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.daily_state import builder_candidate_decision, normalize_builder_hot_candidate, with_degraded_fields
from src.utils.llm_client import DeepSeekClient
from src.utils.source_labels import get_original_source_name


@dataclass
class DailyCandidateBuilder:
    client: DeepSeekClient
    signal_prompt_path: Path
    copy_prompt_path: Path | None = None
    editorial_top_n: int = 10
    per_source_limit: int = 2
    per_topic_limit: int = 1
    builder_candidate_limit: int = 10

    def build(self, today_items: list[ContentItem]) -> dict[str, Any]:
        builder_items = [item for item in today_items if item.source_type == "zara_x"]
        editorial_items = [item for item in today_items if item.source_type != "zara_x"]
        builder_hot_candidates = self._build_builder_hot_candidates(builder_items)
        editorial_candidates_raw = self._build_editorial_candidates(editorial_items)
        editorial_candidates_filtered = self._filter_editorial_candidates(editorial_candidates_raw)
        editorial_top10 = self._rank_editorial_candidates(editorial_candidates_filtered)[: self.editorial_top_n]
        payload = {
            "builder_hot_candidates": builder_hot_candidates,
            "editorial_candidates_raw": editorial_candidates_raw,
            "editorial_candidates_filtered": editorial_candidates_filtered,
            "editorial_top10": editorial_top10,
            "editorial_candidates": editorial_top10,
        }
        if builder_items and not builder_hot_candidates:
            return with_degraded_fields(
                payload,
                degraded_reason="builder_decision_failed",
                degraded_stage="builder_decision",
                fallback_mode="empty_hot_pool",
            )
        if any(candidate.get("degraded_stage") for candidate in builder_hot_candidates):
            return with_degraded_fields(
                payload,
                degraded_reason="builder_copy_failed",
                degraded_stage="builder_copy",
                fallback_mode="per_item_copy_fallback",
            )
        return payload

    def _build_builder_hot_candidates(self, builder_items: list[ContentItem]) -> list[dict[str, Any]]:
        if not builder_items:
            return []

        decisions = self._fetch_builder_decisions(builder_items)
        copies = self._fetch_builder_copy_payload(builder_items, decisions)
        items_by_id = {item.content_id: item for item in builder_items}
        items_by_url = {item.url: item for item in builder_items if item.url}
        copy_by_content_id = {
            payload["content_id"]: payload
            for payload in copies
            if payload.get("content_id")
        }
        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for decision in decisions:
            content_id = decision["content_id"]
            source = decision["source"]
            url = decision["url"]
            topic_key = decision["topic_key"]
            if not all([content_id, source, url]) or url in seen_urls:
                continue

            item = items_by_id.get(content_id)
            copy_payload = copy_by_content_id.get(content_id)
            used_copy_fallback = False
            if copy_payload and self._collect_single_signal_issues(copy_payload):
                copy_payload = None
            if not copy_payload:
                copy_payload = self._fallback_builder_copy(item, topic_key, source)
                used_copy_fallback = True

            topic_label = copy_payload["topic_label"]
            core_claim = copy_payload["core_claim"]
            excerpt = copy_payload["excerpt"]
            if item and self._is_weak_signal(item, topic_label, core_claim, excerpt):
                continue

            seen_urls.add(url)
            resolved_source = self._resolve_builder_source(source, item, items_by_url.get(url))
            candidate = self._make_builder_hot_candidate(
                content_id=content_id,
                source=resolved_source,
                url=url,
                topic_label=topic_label,
                core_claim=core_claim,
                angle=copy_payload["angle"],
                excerpt=excerpt,
                spotlight_text=self._resolve_spotlight_text(
                    source=resolved_source,
                    spotlight_text=copy_payload["spotlight_text"],
                    excerpt=excerpt,
                    core_claim=core_claim,
                ),
            )
            if used_copy_fallback:
                candidate = with_degraded_fields(
                    candidate,
                    degraded_reason="builder_copy_failed",
                    degraded_stage="builder_copy",
                    fallback_mode="copy_from_item_excerpt",
                )
            candidates.append(candidate)

        if len(candidates) < min(3, self.builder_candidate_limit):
            candidates = self._backfill_builder_candidates(builder_items, candidates)
        return [normalize_builder_hot_candidate(candidate) for candidate in candidates[: self.builder_candidate_limit]]

    def _coerce_signal_payload(self, signal: dict[str, Any] | None) -> dict[str, str]:
        data = signal or {}
        return {
            "content_id": str(data.get("content_id", "")).strip(),
            "source": str(data.get("source", "")).strip(),
            "url": str(data.get("url", "")).strip(),
            "topic_label": str(data.get("topic_label", "")).strip(),
            "core_claim": str(data.get("core_claim", "")).strip(),
            "angle": str(data.get("angle", "")).strip(),
            "excerpt": str(data.get("excerpt", "")).strip(),
            "spotlight_text": str(data.get("spotlight_text", "")).strip(),
        }

    def _coerce_signal_decision_payload(self, signal: dict[str, Any] | None) -> dict[str, str]:
        data = signal or {}
        return {
            "content_id": str(data.get("content_id", "")).strip(),
            "source": str(data.get("source", "")).strip(),
            "url": str(data.get("url", "")).strip(),
            "topic_key": str(data.get("topic_key") or data.get("topic_label") or "").strip(),
        }

    def _resolve_builder_source(
        self,
        source: str,
        item_by_id: ContentItem | None,
        item_by_url: ContentItem | None,
    ) -> str:
        for item in (item_by_id, item_by_url):
            if item:
                return get_original_source_name(item)
        normalized = source.strip()
        if normalized:
            return normalized
        return "Unknown"

    def _backfill_builder_candidates(
        self,
        builder_items: list[ContentItem],
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        existing_ids = {builder_candidate_decision(candidate).get("content_id", "") for candidate in candidates}
        existing_urls = {builder_candidate_decision(candidate).get("url", "") for candidate in candidates}

        for item in builder_items:
            if len(candidates) >= self.builder_candidate_limit:
                break
            if item.content_id in existing_ids or item.url in existing_urls:
                continue

            raw_excerpt = (item.ai_summary or item.body or "").strip()
            if not raw_excerpt:
                continue
            fallback_signal = None
            if self._looks_mostly_english(raw_excerpt):
                fallback_signal = self._synthesize_signal_from_item(item)
                if not fallback_signal:
                    continue
            if not self._is_builder_relevant(item, raw_excerpt):
                continue
            if self._is_backfill_too_weak(item, raw_excerpt):
                continue
            if self._is_backfill_too_vague(item, raw_excerpt):
                continue

            if fallback_signal:
                candidates.append(fallback_signal)
                existing_ids.add(item.content_id)
                existing_urls.add(item.url)
                continue

            excerpt = self._truncate_text(raw_excerpt, 60)
            source = item.author or item.source_name
            spotlight_text = self._truncate_text(self._normalize_spotlight_text(source, raw_excerpt), 90)
            candidates.append(
                with_degraded_fields(
                    normalize_builder_hot_candidate(
                    {
                        "decision": {
                            "content_id": item.content_id,
                            "source": source,
                            "url": item.url,
                            "topic_key": item.title[:40] or "Builder 观察",
                            "entered_hot_pool": True,
                        },
                        "copy": {
                            "topic_label": item.title[:40] or "Builder 观察",
                            "core_claim": excerpt,
                            "angle": "补充观察",
                            "excerpt": excerpt,
                            "spotlight_text": spotlight_text,
                        },
                    }
                    ),
                    degraded_reason="builder_decision_failed",
                    degraded_stage="builder_decision",
                    fallback_mode="backfill_from_item",
                )
            )
            existing_ids.add(item.content_id)
            existing_urls.add(item.url)

        return candidates

    def _make_builder_hot_candidate(
        self,
        *,
        content_id: str,
        source: str,
        url: str,
        topic_label: str,
        core_claim: str,
        angle: str,
        excerpt: str,
        spotlight_text: str,
    ) -> dict[str, Any]:
        return normalize_builder_hot_candidate(
            {
                "decision": {
                    "content_id": content_id,
                    "url": url,
                    "source": source,
                    "topic_key": topic_label,
                    "entered_hot_pool": True,
                },
                "copy": {
                    "topic_label": topic_label,
                    "core_claim": core_claim,
                    "angle": angle,
                    "excerpt": excerpt,
                    "spotlight_text": spotlight_text,
                },
            }
        )

    def _build_editorial_candidates(self, editorial_items: list[ContentItem]) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        for item in editorial_items:
            candidates.append(
                {
                    "content_id": item.content_id,
                    "type": "youtube" if item.source_type == "youtube" else "article",
                    "channel_or_source": get_original_source_name(item),
                    "title": item.title,
                    "url": item.url,
                    "summary": item.ai_summary or item.body[:240],
                    "keywords": item.ai_keywords,
                    "source_type": item.source_type,
                }
            )
        return candidates

    def _filter_editorial_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        seen_content_ids: set[str] = set()
        source_counts: dict[str, int] = {}
        topic_indexes: dict[str, int] = {}

        for candidate in candidates:
            content_id = str(candidate.get("content_id", "")).strip()
            url = str(candidate.get("url", "")).strip()
            source_name = str(candidate.get("channel_or_source", "")).strip()
            summary = str(candidate.get("summary", "")).strip()
            title = str(candidate.get("title", "")).strip()
            if not all([content_id, url, source_name, title, summary]):
                continue
            if content_id in seen_content_ids or url in seen_urls:
                continue

            topic_key = self._topic_key(title, summary)
            existing_topic_index = topic_indexes.get(topic_key)
            if existing_topic_index is not None:
                existing_candidate = filtered[existing_topic_index]
                if self._prefer_editorial_candidate(candidate, existing_candidate):
                    old_content_id = str(existing_candidate.get("content_id", "")).strip()
                    old_url = str(existing_candidate.get("url", "")).strip()
                    if old_content_id:
                        seen_content_ids.discard(old_content_id)
                    if old_url:
                        seen_urls.discard(old_url)
                    filtered[existing_topic_index] = candidate
                    seen_content_ids.add(content_id)
                    seen_urls.add(url)
                continue
            if source_counts.get(source_name, 0) >= self.per_source_limit:
                continue

            seen_content_ids.add(content_id)
            seen_urls.add(url)
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
            filtered.append(candidate)
            topic_indexes[topic_key] = len(filtered) - 1

        return filtered

    def _rank_editorial_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            payload = dict(candidate)
            payload["rank_score"] = self._editorial_score(candidate)
            scored.append(payload)
        return sorted(
            scored,
            key=lambda item: (
                -float(item.get("rank_score", 0.0)),
                str(item.get("channel_or_source", "")),
                str(item.get("title", "")),
                str(item.get("content_id", "")),
            ),
        )

    def _editorial_score(self, candidate: dict[str, Any]) -> float:
        text = " ".join(
            [
                str(candidate.get("title", "")).lower(),
                str(candidate.get("summary", "")).lower(),
                " ".join(str(keyword).lower() for keyword in candidate.get("keywords", [])[:8]),
            ]
        )
        source_name = str(candidate.get("channel_or_source", "")).strip()
        source_type = str(candidate.get("source_type", "")).strip()

        score = 0.0
        if source_type == "youtube":
            score += 0.5

        score += self._source_trust_score(source_name)

        agent_terms = [
            "agent",
            "agents",
            "agentic",
            "coding",
            "codex",
            "cli",
            "harness",
            "workflow",
            "tool",
            "stripe",
            "openai",
            "anthropic",
            "llm",
            "rss",
        ]
        for term in agent_terms:
            if term in text:
                score += 1.0

        high_signal_phrases = [
            "first-hand",
            "评估",
            "infrastructure",
            "安全",
            "security",
            "payment",
            "fraud",
            "engineering",
            "部署",
            "训练",
        ]
        for phrase in high_signal_phrases:
            if phrase in text:
                score += 0.6

        penalty_phrases = [
            "融资",
            "valuation",
            "ipo",
            "广告",
            "smart glasses",
            "badge",
            "conversations a week",
        ]
        for phrase in penalty_phrases:
            if phrase in text:
                score -= 0.8

        return round(score, 3)

    def _source_trust_score(self, source_name: str) -> float:
        preferred_scores = {
            "simon_willison": 3.0,
            "training_data": 2.4,
            "dwarkesh_patel": 2.2,
            "techcrunch_ai": 1.0,
            "verge_ai": 0.8,
            "hacker_news_ai": 0.8,
            "zara_podcast": 1.4,
        }
        return preferred_scores.get(source_name, 0.0)

    def _topic_key(self, title: str, summary: str) -> str:
        package_key = self._package_family_key(title)
        if package_key:
            return package_key

        text = f"{title} {summary}".lower()
        phrases = [
            "codex",
            "claude code",
            "gpt-5.5",
            "stripe",
            "grok",
            "gemini",
            "salesforce",
            "spotify",
            "openai",
            "anthropic",
        ]
        for phrase in phrases:
            if phrase in text:
                return phrase

        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", text)
            if len(token) >= 4 and token not in {"with", "from", "that", "this", "your", "about"}
        ]
        return " ".join(tokens[:3]) or title.lower()

    def _prefer_editorial_candidate(self, candidate: dict[str, Any], existing_candidate: dict[str, Any]) -> bool:
        candidate_priority = self._editorial_candidate_priority(candidate)
        existing_priority = self._editorial_candidate_priority(existing_candidate)
        if candidate_priority != existing_priority:
            return candidate_priority > existing_priority
        return str(candidate.get("content_id", "")) < str(existing_candidate.get("content_id", ""))

    def _editorial_candidate_priority(self, candidate: dict[str, Any]) -> tuple[int, int, int, int]:
        title = str(candidate.get("title", "")).strip()
        summary = str(candidate.get("summary", "")).strip()
        is_versioned = self._has_version_marker(title)
        is_release_note = self._looks_like_release_note(title, summary)
        token_count = len(re.findall(r"[A-Za-z0-9]+", title))
        return (
            0 if is_versioned else 1,
            0 if is_release_note else 1,
            1 if token_count <= 3 else 0,
            len(summary),
        )

    def _has_version_marker(self, text: str) -> bool:
        return bool(re.search(r"\b\d+(?:\.\d+)+(?:[a-z]+\d*)?\b", text.lower()))

    def _looks_like_release_note(self, title: str, summary: str) -> bool:
        haystack = f"{title} {summary}".lower()
        release_terms = ["version", "release", "released", "发布", "版本", "更新", "changelog"]
        return any(term in haystack for term in release_terms)

    def _package_family_key(self, title: str) -> str:
        lowered = title.lower()
        slug_match = re.search(r"\b([a-z0-9]+(?:[-_][a-z0-9]+)+)\b", lowered)
        if slug_match:
            slug = re.sub(r"\b\d+(?:\.\d+)+(?:[a-z]+\d*)?\b", " ", slug_match.group(1))
            tokens = [token for token in re.split(r"[-_]+", slug) if token and not token.isdigit()]
            if tokens:
                return " ".join(tokens[:2])

        normalized_title = re.sub(r"\b\d+(?:\.\d+)+(?:[a-z]+\d*)?\b", " ", lowered)
        tokens = [token for token in re.findall(r"[a-z0-9]+", normalized_title) if len(token) >= 2]
        if len(tokens) >= 2 and tokens[1] in {"agent", "plugin", "sdk", "cli", "server", "client", "charts"}:
            return " ".join(tokens[:2])
        return ""

    def _is_backfill_too_weak(self, item: ContentItem, text: str) -> bool:
        del item
        normalized = re.sub(r"https?://\S+", " ", text)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if len(normalized) < 18:
            return True

        generic_patterns = ["哈哈", "lol", "interesting", "nice", "cool", "赞", "转发", "收藏"]
        lowered = normalized.lower()
        return any(pattern in lowered for pattern in generic_patterns)

    def _is_backfill_too_vague(self, item: ContentItem | None, text: str) -> bool:
        del item
        normalized = self._strip_terminal_punctuation(text.strip())
        lowered = normalized.lower()

        vague_patterns = ["讨论", "提到", "谈到", "说到", "问题", "情况", "看法", "观点", "alignment failure"]
        concrete_markers = [
            "发布",
            "推出",
            "上线",
            "招聘",
            "开源",
            "收购",
            "融资",
            "合作",
            "限制",
            "支持",
            "模型",
            "agent",
            "agents",
            "gpt",
            "claude",
            "codex",
            "openai",
            "anthropic",
            "gemini",
            "grok",
            "stripe",
            "box",
        ]

        has_vague_pattern = any(pattern in lowered for pattern in vague_patterns)
        has_concrete_marker = any(marker in lowered for marker in concrete_markers)

        if has_vague_pattern and not has_concrete_marker:
            return True
        if len(normalized) <= 14 and " " not in normalized and not re.search(r"[A-Z0-9]", normalized):
            return True
        return False

    def _resolve_spotlight_text(
        self,
        source: str,
        spotlight_text: str,
        excerpt: str,
        core_claim: str,
    ) -> str:
        candidates = [
            self._normalize_spotlight_text(source, spotlight_text),
            self._normalize_spotlight_text(source, excerpt),
            self._normalize_spotlight_text(source, core_claim),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if self._looks_mostly_english(candidate):
                continue
            if self._looks_truncated(candidate):
                continue
            if self._is_spotlight_sentence_good(candidate):
                return self._truncate_text(candidate, 90)
        return self._truncate_text(candidates[-1] or "", 90)

    def _is_spotlight_sentence_good(self, text: str) -> bool:
        normalized = self._strip_terminal_punctuation(text.strip())
        if not normalized:
            return False
        if self._is_backfill_too_vague(None, normalized):
            return False
        weak_phrases = ["讨论", "提到", "聊到", "说到", "看法", "问题"]
        if any(phrase in normalized for phrase in weak_phrases) and len(normalized) < 22:
            return False
        return True

    def _is_builder_relevant(self, item: ContentItem, text: str) -> bool:
        haystack = " ".join(
            [
                str(item.title or ""),
                str(item.ai_summary or ""),
                str(text or ""),
                " ".join(str(keyword) for keyword in item.ai_keywords[:8]),
            ]
        ).lower()
        ascii_tokens = set(re.findall(r"[a-z0-9\-\+\.#]+", haystack))
        ascii_terms = {
            "ai",
            "agent",
            "agents",
            "agentic",
            "llm",
            "gpt",
            "claude",
            "codex",
            "openai",
            "anthropic",
            "gemini",
            "grok",
            "model",
            "models",
            "prompt",
            "tool",
            "tools",
            "workflow",
            "automation",
            "coding",
            "engineer",
            "engineering",
        }
        chinese_terms = ["软件", "模型", "智能体", "代理", "编程", "工程", "自动化", "推理", "训练", "部署"]
        return any(term in ascii_tokens for term in ascii_terms) or any(term in haystack for term in chinese_terms)

    def _strip_terminal_punctuation(self, text: str) -> str:
        return text.rstrip("。？！!?；;：:")

    def _normalize_spotlight_text(self, source: str, text: str) -> str:
        normalized = self._strip_terminal_punctuation(text.strip())
        if not normalized:
            return normalized

        source_name = source.strip()
        if source_name:
            patterns = [
                rf"^{re.escape(source_name)}\s*[:：，,\- ]*说",
                rf"^{re.escape(source_name)}\s*[:：，,\- ]*认为",
                rf"^{re.escape(source_name)}\s*[:：，,\- ]*表示",
                rf"^{re.escape(source_name)}\s*[:：，,\- ]*指出",
                rf"^{re.escape(source_name)}\s*[:：，,\- ]*",
            ]
            for pattern in patterns:
                updated = re.sub(pattern, "", normalized, count=1).strip()
                if updated and updated != normalized:
                    normalized = updated
                    break

        normalized = re.sub(r"^(作者|原帖)\s*(说|认为|表示|指出)", "", normalized, count=1).strip()
        return normalized or self._strip_terminal_punctuation(text.strip())

    def _truncate_text(self, text: str, max_len: int) -> str:
        stripped = self._strip_terminal_punctuation(text.strip())
        if len(stripped) <= max_len:
            return stripped
        return stripped[: max_len - 1].rstrip() + "…"

    def _decision_prompt_path(self) -> str:
        return str(self.signal_prompt_path)

    def _copy_prompt_path(self) -> str:
        return str(self.copy_prompt_path or self.signal_prompt_path)

    def _fetch_builder_decisions(self, builder_items: list[ContentItem]) -> list[dict[str, str]]:
        payload = self.client.daily_builder_hot_decisions(self._decision_prompt_path(), builder_items)
        if not isinstance(payload, dict):
            payload = self.client.daily_theme_signals(self._decision_prompt_path(), builder_items)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            issues = self._collect_decision_issues(payload)
            if not issues:
                break
            if attempt == max_attempts:
                break
            payload = self.client.daily_builder_hot_decisions(self._decision_prompt_path(), builder_items, feedback=issues)
            if not isinstance(payload, dict):
                payload = self.client.daily_theme_signals(self._decision_prompt_path(), builder_items, feedback=issues)
        return [
            signal
            for signal in (
                self._coerce_signal_decision_payload(signal)
                for signal in (payload or {}).get("signals", [])[: self.builder_candidate_limit]
            )
            if signal["content_id"] and signal["url"]
        ]

    def _fetch_builder_copy_payload(
        self,
        builder_items: list[ContentItem],
        decisions: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not decisions:
            return []
        payload = self.client.daily_builder_hot_copy(self._copy_prompt_path(), builder_items, decisions)
        if not isinstance(payload, dict):
            payload = self.client.daily_theme_signals(self._copy_prompt_path(), builder_items)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            issues = self._collect_signal_issues(payload)
            if not issues:
                break
            if attempt == max_attempts:
                break
            payload = self.client.daily_builder_hot_copy(
                self._copy_prompt_path(),
                builder_items,
                decisions,
                feedback=issues,
            )
            if not isinstance(payload, dict):
                payload = self.client.daily_theme_signals(self._copy_prompt_path(), builder_items, feedback=issues)
        return [self._coerce_signal_payload(signal) for signal in (payload or {}).get("signals", [])[: len(decisions)]]

    def _collect_decision_issues(self, payload: dict[str, Any] | None) -> list[str]:
        issues: list[str] = []
        data = payload or {}
        for index, signal in enumerate(data.get("signals", [])[:10], start=1):
            decision = self._coerce_signal_decision_payload(signal)
            if not decision["content_id"]:
                issues.append(f"Signal {index} missing `content_id`.")
            if not decision["url"]:
                issues.append(f"Signal {index} missing `url`.")
            if not decision["source"]:
                issues.append(f"Signal {index} missing `source`.")
        return issues

    def _collect_signal_issues(self, payload: dict[str, Any] | None) -> list[str]:
        issues: list[str] = []
        data = payload or {}
        for index, signal in enumerate(data.get("signals", [])[:10], start=1):
            for issue in self._collect_single_signal_issues(self._coerce_signal_payload(signal)):
                issues.append(f"Signal {index} {issue}")
        return issues

    def _collect_single_signal_issues(self, signal: dict[str, str]) -> list[str]:
        issues: list[str] = []
        for field in ("topic_label", "core_claim", "excerpt", "spotlight_text"):
            value = str(signal.get(field, "")).strip()
            if not value:
                issues.append(f"missing `{field}`.")
                continue
            if self._looks_mostly_english(value):
                issues.append(f"`{field}` must be rewritten into natural Chinese.")
            if field != "topic_label" and self._looks_truncated(value):
                issues.append(f"`{field}` is truncated; rewrite it as a complete sentence.")
        return issues

    def _synthesize_signal_from_item(self, item: ContentItem) -> dict[str, Any] | None:
        source = self._resolve_builder_source(item.author or item.source_name, item, item)
        decision = {
            "content_id": item.content_id,
            "source": source,
            "url": item.url,
            "topic_key": item.title[:40].strip() or "Builder 观察",
        }
        copy_payloads = self._fetch_builder_copy_payload([item], [decision])
        repaired = copy_payloads[0] if copy_payloads else self._fallback_builder_copy(item, decision["topic_key"], source)
        if self._collect_single_signal_issues(repaired):
            repaired = self._fallback_builder_copy(item, decision["topic_key"], source)
        return with_degraded_fields(
            self._make_builder_hot_candidate(
            content_id=item.content_id,
            source=source,
            url=item.url,
            topic_label=repaired["topic_label"],
            core_claim=repaired["core_claim"],
            angle=repaired["angle"],
            excerpt=repaired["excerpt"],
            spotlight_text=self._resolve_spotlight_text(
                source=source,
                spotlight_text=repaired["spotlight_text"],
                excerpt=repaired["excerpt"],
                core_claim=repaired["core_claim"],
            ),
            ),
            degraded_reason="builder_copy_failed",
            degraded_stage="builder_copy",
            fallback_mode="copy_from_item_excerpt",
        )

    def _fallback_builder_copy(
        self,
        item: ContentItem | None,
        topic_key: str,
        source: str,
    ) -> dict[str, str]:
        raw_excerpt = ""
        if item is not None:
            raw_excerpt = (
                item.ai_summary
                or str(item.extra_metadata.get("raw_entry", {}).get("content") or "")
                or item.body
            ).strip()
        excerpt = self._truncate_text(raw_excerpt or topic_key or "Builder 观察", 60)
        spotlight_text = self._resolve_spotlight_text(
            source=source,
            spotlight_text=raw_excerpt,
            excerpt=excerpt,
            core_claim=excerpt,
        )
        topic_label = self._truncate_text(topic_key or (item.title if item else "") or "Builder 观察", 16)
        return {
            "content_id": item.content_id if item else "",
            "source": source,
            "url": item.url if item else "",
            "topic_label": topic_label,
            "core_claim": excerpt,
            "angle": "补充观察",
            "excerpt": excerpt,
            "spotlight_text": spotlight_text or excerpt,
        }

    def _looks_mostly_english(self, text: str) -> bool:
        ascii_letters = len(re.findall(r"[A-Za-z]", text))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        return ascii_letters >= 12 and ascii_letters > chinese_chars

    def _looks_truncated(self, text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        return normalized.endswith(("...", "…", "/", "-", ":", "："))

    def _is_weak_signal(
        self,
        item: ContentItem,
        topic_label: str,
        core_claim: str,
        excerpt: str,
    ) -> bool:
        raw_text = str(item.extra_metadata.get("raw_entry", {}).get("content") or item.body or "")
        normalized_text = re.sub(r"https?://\S+", " ", raw_text)
        normalized_text = re.sub(r"\s+", " ", normalized_text).strip()
        ascii_words = re.findall(r"[A-Za-z]{2,}", normalized_text)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized_text)
        info_units = len(ascii_words) + len(chinese_chars)

        generic_patterns = ["分享链接", "表示不可思议", "感到好笑", "询问", "高度尊重", "怀疑信息泛滥", "调侃"]
        combined = " ".join([topic_label, core_claim, excerpt])
        if any(pattern in combined for pattern in generic_patterns):
            return True
        if info_units < 35:
            return True
        if len(re.findall(r"[.!?。！？]\s*", normalized_text)) <= 1 and info_units < 60:
            return True
        return False
