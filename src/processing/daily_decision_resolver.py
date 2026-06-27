from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.utils.daily_state import (
    builder_candidate_copy,
    builder_candidate_decision,
    normalize_daily_candidates_payload,
    normalize_daily_selections_payload,
    normalize_daily_themes_payload,
    selection_decision,
    theme_copy,
    theme_decision,
)


@dataclass
class DailyDecisionResolver:
    def resolve(
        self,
        candidates_data: dict[str, Any] | None,
        themes_data: dict[str, Any] | None,
        selections_data: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        candidates_payload = normalize_daily_candidates_payload(candidates_data)
        themes_payload = normalize_daily_themes_payload(themes_data)
        selections_payload = normalize_daily_selections_payload(selections_data)

        normalized_selections = self._dedupe_selections(selections_payload.get("selections", []))
        themes_payload["spotlight_posts"] = self._dedupe_spotlight_posts(
            themes_payload.get("spotlight_posts", []),
            themes_payload.get("themes", []),
        )
        themes_payload["supplementary_items"] = self._build_supplementary_items(
            themes_payload,
            normalized_selections,
            candidates_payload,
        )
        selections_payload["selections"] = normalized_selections
        return candidates_payload, themes_payload, selections_payload

    def _build_supplementary_items(
        self,
        themes_payload: dict[str, Any],
        selections: list[dict[str, Any]],
        candidates_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        themes = list(themes_payload.get("themes", []))
        spotlight_posts = list(themes_payload.get("spotlight_posts", []))
        supplementary_spotlight_posts = list(themes_payload.get("supplementary_spotlight_posts", []))
        supplementary: list[dict[str, Any]] = []
        supplementary_limit = 10 if (not themes and spotlight_posts) else 5

        displayed_selection_ids = {
            str(selection_decision(selection).get("content_id", "")).strip()
            for selection in selections
            if str(selection_decision(selection).get("content_id", "")).strip()
        }
        displayed_editorial_keys = {
            self._editorial_dedup_key(
                str(selection_decision(selection).get("title", "")).strip(),
                str(selection_decision(selection).get("url", "")).strip(),
            )
            for selection in selections
            if str(selection_decision(selection).get("type", "")).strip().lower() != "builder"
        }
        displayed_editorial_keys.discard("")
        displayed_builder_urls = {
            str(post.get("url", "")).strip()
            for post in spotlight_posts
            if str(post.get("url", "")).strip()
        }
        displayed_builder_urls.update(
            str(evidence.get("url", "")).strip()
            for theme in themes
            for evidence in theme_copy(theme).get("evidence", [])
            if str(evidence.get("url", "")).strip()
        )
        related_ids = {
            str(content_id).strip()
            for theme in themes
            for content_id in theme_decision(theme).get("member_content_ids", [])
            if str(content_id).strip()
        }

        source_counts: dict[str, int] = {}
        editorial_pool = candidates_payload.get("editorial_top10") or candidates_payload.get("editorial_candidates", [])
        for max_per_source in (1, 2):
            for candidate in editorial_pool:
                content_id = str(candidate.get("content_id", "")).strip()
                source_name = str(candidate.get("channel_or_source", "")).strip()
                title = str(candidate.get("title", "")).strip()
                url = str(candidate.get("url", "")).strip()
                dedup_key = self._editorial_dedup_key(title, url)
                if not content_id or not source_name:
                    continue
                if content_id in displayed_selection_ids or content_id in related_ids:
                    continue
                if any(item.get("content_id") == content_id for item in supplementary):
                    continue
                if dedup_key and dedup_key in displayed_editorial_keys:
                    continue
                if source_counts.get(source_name, 0) >= max_per_source:
                    continue
                supplementary.append(
                    {
                        "content_id": content_id,
                        "type": str(candidate.get("type", "article")).strip().lower(),
                        "source_name": source_name,
                        "title": title,
                        "url": url,
                        "brief": self._supplementary_editorial_brief(candidate),
                    }
                )
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
                if dedup_key:
                    displayed_editorial_keys.add(dedup_key)
                if len(supplementary) >= supplementary_limit:
                    return supplementary

        for candidate in candidates_payload.get("builder_hot_candidates", []):
            decision = builder_candidate_decision(candidate)
            copy = builder_candidate_copy(candidate)
            url = str(decision.get("url", "")).strip()
            source_name = str(decision.get("source", "")).strip()
            if not url or not source_name:
                continue
            if url in displayed_builder_urls:
                continue
            if any(item.get("url") == url for item in supplementary):
                continue
            supplementary.append(
                {
                    "type": "builder",
                    "source_name": source_name,
                    "title": "",
                    "url": url,
                    "brief": self._strip_terminal_punctuation(
                        str(copy.get("spotlight_text") or copy.get("core_claim", "")).strip()
                    ),
                }
            )
            if len(supplementary) >= supplementary_limit:
                return supplementary

        for post in supplementary_spotlight_posts:
            url = str(post.get("url", "")).strip()
            source_name = str(post.get("source", "")).strip()
            if not url or not source_name:
                continue
            if url in displayed_builder_urls:
                continue
            if any(item.get("url") == url for item in supplementary):
                continue
            supplementary.append(
                {
                    "type": "builder",
                    "source_name": source_name,
                    "title": "",
                    "url": url,
                    "brief": self._strip_terminal_punctuation(str(post.get("text", "")).strip()),
                }
            )
            if len(supplementary) >= supplementary_limit:
                break

        return supplementary

    def _dedupe_spotlight_posts(
        self,
        spotlight_posts: list[dict[str, Any]],
        themes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        used_urls = {
            str(evidence.get("url", "")).strip()
            for theme in themes
            for evidence in theme_copy(theme).get("evidence", [])
            if str(evidence.get("url", "")).strip()
        }
        deduped: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for post in spotlight_posts:
            url = str(post.get("url", "")).strip()
            if not url or url in used_urls or url in seen_urls:
                continue
            deduped.append(post)
            seen_urls.add(url)
        return deduped

    def _dedupe_selections(self, selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for selection in selections:
            content_id = str(selection_decision(selection).get("content_id", "")).strip()
            if not content_id or content_id in seen_ids:
                continue
            deduped.append(selection)
            seen_ids.add(content_id)
        return deduped

    def _editorial_dedup_key(self, title: str, url: str) -> str:
        package_key = self._package_family_key(title)
        if package_key:
            return package_key
        normalized_title = title.strip().lower()
        if normalized_title:
            return normalized_title
        normalized_url = url.strip().lower()
        if normalized_url:
            return normalized_url
        return ""

    def _package_family_key(self, title: str) -> str:
        lowered = title.lower()
        slug_match = re.search(r"\b([a-z0-9]+(?:[-_][a-z0-9]+)+)\b", lowered)
        if slug_match:
            slug = re.sub(r"\b\d+(?:\.\d+)+(?:[a-z]+\d*)?\b", " ", slug_match.group(1))
            tokens = [token for token in re.split(r"[-_]+", slug) if token and not token.isdigit()]
            if tokens:
                return "pkg:" + " ".join(tokens[:2])

        normalized_title = re.sub(r"\b\d+(?:\.\d+)+(?:[a-z]+\d*)?\b", " ", lowered)
        tokens = [token for token in re.findall(r"[a-z0-9]+", normalized_title) if len(token) >= 2]
        if len(tokens) >= 2 and tokens[1] in {"agent", "plugin", "sdk", "cli", "server", "client", "charts"}:
            return "pkg:" + " ".join(tokens[:2])
        return ""

    def _supplementary_editorial_brief(self, candidate: dict[str, Any]) -> str:
        summary = self._strip_terminal_punctuation(str(candidate.get("summary", "")).strip())
        if summary and not self._looks_mostly_english(summary):
            return summary
        source_name = str(candidate.get("channel_or_source", "")).strip()
        title = str(candidate.get("title", "")).strip()
        if source_name and title:
            return f"这条内容来自 {source_name}，标题为《{title}》，因未进入今日精选，仅作为补充候选保留。"
        if source_name:
            return f"这条内容来自 {source_name}，因未进入今日精选，仅作为补充候选保留。"
        return "这条内容未进入今日精选，仅作为补充候选保留。"

    def _looks_mostly_english(self, text: str) -> bool:
        letters = re.findall(r"[A-Za-z]", text)
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        return len(letters) >= 20 and len(letters) > len(cjk) * 2

    def _strip_terminal_punctuation(self, text: str) -> str:
        return text.rstrip("銆傦紵锛?!?锛?")
