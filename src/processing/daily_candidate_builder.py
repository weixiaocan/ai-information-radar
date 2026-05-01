from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.llm_client import DeepSeekClient


@dataclass
class DailyCandidateBuilder:
    client: DeepSeekClient
    signal_prompt_path: Path
    editorial_top_n: int = 10
    per_source_limit: int = 2
    per_topic_limit: int = 1
    builder_spotlight_target: int = 4

    def build(self, today_items: list[ContentItem]) -> dict[str, Any]:
        builder_items = [item for item in today_items if item.source_type == "zara_x"]
        editorial_items = [item for item in today_items if item.source_type != "zara_x"]
        builder_hot_candidates = self._build_builder_hot_candidates(builder_items)
        editorial_candidates_raw = self._build_editorial_candidates(editorial_items)
        editorial_candidates_filtered = self._filter_editorial_candidates(editorial_candidates_raw)
        editorial_top10 = self._rank_editorial_candidates(editorial_candidates_filtered)[: self.editorial_top_n]
        return {
            "builder_hot_candidates": builder_hot_candidates,
            "editorial_candidates_raw": editorial_candidates_raw,
            "editorial_candidates_filtered": editorial_candidates_filtered,
            "editorial_top10": editorial_top10,
            "editorial_candidates": editorial_top10,
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
                    "spotlight_text": self._resolve_spotlight_text(
                        source=source,
                        spotlight_text=spotlight_text,
                        excerpt=excerpt,
                        core_claim=core_claim,
                    ),
                }
            )

        if len(candidates) < 3:
            candidates = self._backfill_builder_candidates(builder_items, candidates)
        return candidates

    def _backfill_builder_candidates(
        self,
        builder_items: list[ContentItem],
        candidates: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        existing_ids = {candidate["content_id"] for candidate in candidates}
        existing_urls = {candidate["url"] for candidate in candidates}

        for item in builder_items:
            if len(candidates) >= self.builder_spotlight_target:
                break
            if item.content_id in existing_ids or item.url in existing_urls:
                continue

            raw_excerpt = (item.ai_summary or item.body or "").strip()
            if not raw_excerpt:
                continue
            if not self._is_builder_relevant(item, raw_excerpt):
                continue
            if self._is_backfill_too_weak(item, raw_excerpt):
                continue
            if self._is_backfill_too_vague(item, raw_excerpt):
                continue

            excerpt = self._truncate_text(raw_excerpt, 60)
            source = item.author or item.source_name
            spotlight_text = self._truncate_text(self._normalize_spotlight_text(source, raw_excerpt), 90)
            candidates.append(
                {
                    "content_id": item.content_id,
                    "source": source,
                    "url": item.url,
                    "topic_label": item.title[:40] or "Builder 观察",
                    "core_claim": excerpt,
                    "angle": "补充观察",
                    "excerpt": excerpt,
                    "spotlight_text": spotlight_text,
                }
            )
            existing_ids.add(item.content_id)
            existing_urls.add(item.url)

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
        topic_counts: dict[str, int] = {}

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
            if source_counts.get(source_name, 0) >= self.per_source_limit:
                continue

            topic_key = self._topic_key(title, summary)
            if topic_counts.get(topic_key, 0) >= self.per_topic_limit:
                continue

            seen_content_ids.add(content_id)
            seen_urls.add(url)
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
            topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1
            filtered.append(candidate)

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
            "第一手",
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

    def _is_backfill_too_weak(self, item: ContentItem, text: str) -> bool:
        del item
        normalized = re.sub(r"https?://\S+", " ", text)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if len(normalized) < 18:
            return True

        generic_patterns = [
            "哈哈",
            "lol",
            "interesting",
            "nice",
            "cool",
            "赞",
            "转发",
            "收藏",
        ]
        lowered = normalized.lower()
        return any(pattern in lowered for pattern in generic_patterns)

    def _is_backfill_too_vague(self, item: ContentItem, text: str) -> bool:
        del item
        normalized = self._strip_terminal_punctuation(text.strip())
        lowered = normalized.lower()

        vague_patterns = [
            "讨论",
            "聊",
            "提到",
            "谈到",
            "说到",
            "问题",
            "情况",
            "看法",
            "观点",
            "alignment failure",
        ]
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
            if self._is_spotlight_sentence_good(candidate):
                return self._truncate_text(candidate, 90)
        return self._truncate_text(candidates[-1] or "", 90)

    def _is_spotlight_sentence_good(self, text: str) -> bool:
        normalized = self._strip_terminal_punctuation(text.strip())
        if not normalized:
            return False
        if self._is_backfill_too_vague(None, normalized):  # type: ignore[arg-type]
            return False
        weak_phrases = [
            "讨论",
            "提到",
            "聊到",
            "说到",
            "看法",
            "问题",
        ]
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
            "model",
            "models",
            "openai",
            "anthropic",
            "gemini",
            "grok",
            "codex",
        }
        chinese_terms = [
            "软件",
            "模型",
            "智能体",
            "代理",
            "编程",
            "工程",
            "自动化",
            "推理",
            "训练",
            "部署",
        ]
        return any(term in ascii_tokens for term in ascii_terms) or any(term in haystack for term in chinese_terms)

    def _strip_terminal_punctuation(self, text: str) -> str:
        return text.rstrip("。？！.!?；;")

    def _normalize_spotlight_text(self, source: str, text: str) -> str:
        normalized = self._strip_terminal_punctuation(text.strip())
        if not normalized:
            return normalized

        source_name = source.strip()
        if source_name:
            patterns = [
                rf"^{re.escape(source_name)}\s*[：:，, ]*说",
                rf"^{re.escape(source_name)}\s*[：:，, ]*认为",
                rf"^{re.escape(source_name)}\s*[：:，, ]*表示",
                rf"^{re.escape(source_name)}\s*[：:，, ]*指出",
                rf"^{re.escape(source_name)}\s*[：:，, ]*",
            ]
            for pattern in patterns:
                updated = re.sub(pattern, "", normalized, count=1).strip()
                if updated and updated != normalized:
                    normalized = updated
                    break

        normalized = re.sub(r"^(他|她|其)\s*(说|认为|表示|指出)", "", normalized, count=1).strip()
        return normalized or self._strip_terminal_punctuation(text.strip())

    def _truncate_text(self, text: str, max_len: int) -> str:
        stripped = self._strip_terminal_punctuation(text.strip())
        if len(stripped) <= max_len:
            return stripped
        return stripped[: max_len - 1].rstrip() + "…"

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
