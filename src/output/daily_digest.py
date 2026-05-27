from __future__ import annotations

import logging
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from src.utils.daily_state import (
    builder_candidate_copy,
    builder_candidate_decision,
    normalize_daily_candidates_payload,
    normalize_daily_selections_payload,
    normalize_daily_themes_payload,
    selection_copy,
    selection_decision,
    theme_copy,
    theme_decision,
)
from src.utils.source_labels import load_display_name_map

LOGGER = logging.getLogger(__name__)


class DailyDigestBuilder:
    def __init__(self) -> None:
        self.display_name_map = load_display_name_map()

    def _strip_leading_punctuation(self, text: str) -> str:
        return re.sub(r"^[,，:：;；、\.\s]+", "", text).strip()

    def _sanitize_link_label(self, text: str) -> str:
        return re.sub(r"<([^<>]+)>", r"[\1]", text)

    def build(
        self,
        themes_data: dict[str, Any] | None,
        selections_data: dict[str, Any] | None,
        stats: dict[str, int] | None,
        target_date: date | None = None,
        candidates_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        themes_payload = normalize_daily_themes_payload(themes_data)
        themes = list(themes_payload.get("themes", []))
        spotlight_posts = list(themes_payload.get("spotlight_posts", []))
        selections_payload = normalize_daily_selections_payload(selections_data)
        selections = list(selections_payload.get("selections", []))
        supplementary_items = list(themes_payload.get("supplementary_items", []))
        self._warn_on_url_conflicts(selections, supplementary_items)
        stats_payload = stats or {"total": 0}
        digest_date = target_date or date.today()
        related_ids = {
            content_id
            for theme in themes
            for content_id in theme_decision(theme).get("member_content_ids", [])
            if str(content_id).strip()
        }

        elements: list[dict[str, Any]] = []
        if themes:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**🌡️ 今日热议（{len(themes)} 个主题）**"}})
            for theme in themes:
                visible_evidence = self._dedupe_theme_evidence_against_summary(
                    str(theme_copy(theme).get("theme_summary", "")).strip(),
                    theme_copy(theme).get("evidence", []),
                )
                evidence_lines = "\n".join(
                    self._render_evidence_line(evidence)
                    for evidence in visible_evidence[:4]
                    if evidence.get("excerpt")
                )
                summary = self._strip_terminal_punctuation(str(theme_copy(theme).get("theme_summary", "")).strip())
                content = f"**▎{theme_copy(theme).get('theme_title', '未命名主题')}**\n{summary}"
                if evidence_lines:
                    content += f"\n{evidence_lines}"
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
        elif spotlight_posts:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**🌡️ 今日热议（值得看的 {len(spotlight_posts)} 条 builder 帖子）**"},
                }
            )
            for post in spotlight_posts:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": self._render_spotlight_line(post)}})
        elif str(themes_payload.get("degraded_reason", "")).strip() == "builder_source_fetch_failed":
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "**今日热议**\n_builder/X 信号源抓取失败，今日热议暂未生成_"},
                }
            )
        else:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "**🌡️ 今日热议**\n_今日 builder 圈讨论较为分散，无集中主题_"},
                }
            )

        elements.append({"tag": "hr"})

        if selections:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**🎯 今日精选（{len(selections)} 条）**"}})
            for selection in selections:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": self._render_selection_block(selection)}})
        else:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "**🎯 今日精选**\n_今日内容质量普遍不高，无精选推荐_"},
                }
            )

        if supplementary_items:
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**🪻 补充候选（{len(supplementary_items)} 条）**"}})
            for item in supplementary_items:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": self._render_supplementary_line(item)}})

        elements.append({"tag": "hr"})
        filtered_count = max(int(stats_payload.get("total", 0)) - len(selections) - len(related_ids), 0)
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": (
                            f"今日抓取 {stats_payload.get('total', 0)} 条"
                            f" · 呈现精选 {len(selections)} 条 + 主题 {len(themes)} 个"
                            f" · 过滤掉 {filtered_count} 条"
                        ),
                    }
                ],
            }
        )

        weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][digest_date.weekday()]
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {"tag": "plain_text", "content": f"📡 AI Radar · {digest_date.isoformat()} 日报 · 周{weekday_cn}"},
                },
                "elements": elements,
            },
        }

    def render_markdown(
        self,
        themes_data: dict[str, Any] | None,
        selections_data: dict[str, Any] | None,
        stats: dict[str, int] | None,
        target_date: date | None = None,
        candidates_data: dict[str, Any] | None = None,
    ) -> str:
        themes_payload = normalize_daily_themes_payload(themes_data)
        themes = list(themes_payload.get("themes", []))
        spotlight_posts = list(themes_payload.get("spotlight_posts", []))
        selections_payload = normalize_daily_selections_payload(selections_data)
        selections = list(selections_payload.get("selections", []))
        supplementary_items = list(themes_payload.get("supplementary_items", []))
        self._warn_on_url_conflicts(selections, supplementary_items)
        stats_payload = stats or {"total": 0}
        digest_date = target_date or date.today()
        weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][digest_date.weekday()]
        related_ids = {
            content_id
            for theme in themes
            for content_id in theme_decision(theme).get("member_content_ids", [])
            if str(content_id).strip()
        }

        lines = [f"# 📡 AI Radar · {digest_date.isoformat()} 日报 · 周{weekday_cn}", ""]
        lines.append("## 🌡️ 今日热议")
        lines.append("")
        if themes:
            for theme in themes:
                visible_evidence = self._dedupe_theme_evidence_against_summary(
                    str(theme_copy(theme).get("theme_summary", "")).strip(),
                    theme_copy(theme).get("evidence", []),
                )
                lines.append(f"### ▎{theme_copy(theme).get('theme_title', '未命名主题')}")
                lines.append("")
                summary = self._strip_terminal_punctuation(str(theme_copy(theme).get("theme_summary", "")).strip())
                if summary:
                    lines.append(summary)
                    lines.append("")
                for evidence in visible_evidence[:4]:
                    if str(evidence.get("excerpt", "")).strip():
                        lines.append(self._render_markdown_evidence_line(evidence))
                lines.append("")
        elif spotlight_posts:
            for post in spotlight_posts:
                lines.append(self._render_markdown_spotlight_line(post))
            lines.append("")
        elif str(themes_payload.get("degraded_reason", "")).strip() == "builder_source_fetch_failed":
            lines.append("_builder/X 信号源抓取失败，今日热议暂未生成_")
            lines.append("")
        else:
            lines.append("_今日 builder 圈讨论较为分散，无集中主题_")
            lines.append("")

        lines.append("## 🎯 今日精选")
        lines.append("")
        if selections:
            for selection in selections:
                lines.extend(self._render_markdown_selection_block(selection))
                lines.append("")
        else:
            lines.append("_今日内容质量普遍不高，无精选推荐_")
            lines.append("")

        if supplementary_items:
            lines.append("## 🪻 补充候选")
            lines.append("")
            for item in supplementary_items:
                lines.append(self._render_markdown_supplementary_line(item))
            lines.append("")

        filtered_count = max(int(stats_payload.get("total", 0)) - len(selections) - len(related_ids), 0)
        lines.append("## 📊 今日数据")
        lines.append("")
        lines.append(
            f"今日抓取 {stats_payload.get('total', 0)} 条"
            f" · 呈现精选 {len(selections)} 条 + 主题 {len(themes)} 个"
            f" · 过滤掉 {filtered_count} 条"
        )
        lines.append("")
        return "\n".join(lines)

    def _build_supplementary_candidates(
        self,
        themes_payload: dict[str, Any],
        selections: list[dict[str, Any]],
        candidates_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates_data = normalize_daily_candidates_payload(candidates_data)
        themes = list(themes_payload.get("themes", []))
        spotlight_posts = list(themes_payload.get("spotlight_posts", []))
        supplementary_spotlight_posts = list(themes_payload.get("supplementary_spotlight_posts", []))
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

        supplementary: list[dict[str, Any]] = []
        source_counts: dict[str, int] = {}
        supplementary_limit = 10 if (not themes and spotlight_posts) else 5

        editorial_pool = candidates_data.get("editorial_top10") or candidates_data.get("editorial_candidates", [])
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
                if dedup_key and dedup_key in displayed_editorial_keys:
                    continue
                if any(item.get("content_id") == content_id for item in supplementary):
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
                        "brief": self._strip_terminal_punctuation(str(candidate.get("summary", "")).strip()),
                    }
                )
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
                if dedup_key:
                    displayed_editorial_keys.add(dedup_key)
                if len(supplementary) >= supplementary_limit:
                    return supplementary

        for candidate in candidates_data.get("builder_hot_candidates", []):
            candidate_decision = builder_candidate_decision(candidate)
            candidate_copy = builder_candidate_copy(candidate)
            url = str(candidate_decision.get("url", "")).strip()
            source_name = str(candidate_decision.get("source", "")).strip()
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
                        str(candidate_copy.get("spotlight_text") or candidate_copy.get("core_claim", "")).strip()
                    ),
                }
            )
            if len(supplementary) >= supplementary_limit:
                break

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

    def _enforce_section_invariants(
        self,
        selections: list[dict[str, Any]],
        supplementary_items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized_selections: list[dict[str, Any]] = []
        selection_ids: set[str] = set()
        for selection in selections:
            content_id = str(selection_decision(selection).get("content_id", "")).strip()
            if not content_id:
                continue
            if content_id in selection_ids:
                continue
            normalized_selections.append(selection)
            selection_ids.add(content_id)

        normalized_supplementary: list[dict[str, Any]] = []
        supplementary_ids: set[str] = set()
        for item in supplementary_items:
            content_id = str(item.get("content_id", "")).strip()
            if content_id and content_id in selection_ids:
                continue
            if content_id and content_id in supplementary_ids:
                continue
            normalized_supplementary.append(item)
            if content_id:
                supplementary_ids.add(content_id)

        return normalized_selections, normalized_supplementary

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
        if not tokens:
            return ""
        return ""

    def _warn_on_url_conflicts(
        self,
        selections: list[dict[str, Any]],
        supplementary_items: list[dict[str, Any]],
    ) -> None:
        for warning in self.collect_url_conflicts(selections, supplementary_items):
            LOGGER.warning(
                "Daily digest URL conflict detected: url=%s first_content_id=%s second_content_id=%s second_section=%s",
                warning["url"],
                warning["first_content_id"],
                warning["second_content_id"],
                warning["second_section"],
            )

    def collect_invariant_warnings(
        self,
        themes_data: dict[str, Any] | None,
        selections_data: dict[str, Any] | None,
        candidates_data: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        themes_payload = normalize_daily_themes_payload(themes_data)
        selections = list(normalize_daily_selections_payload(selections_data).get("selections", []))
        supplementary_items = list(themes_payload.get("supplementary_items", []))
        return self.collect_url_conflicts(selections, supplementary_items)

    def collect_url_conflicts(
        self,
        selections: list[dict[str, Any]],
        supplementary_items: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        seen_by_url: dict[str, tuple[str, str]] = {}
        for section_name, items in (("selection", selections), ("supplementary", supplementary_items)):
            for item in items:
                item_payload = selection_decision(item) if section_name == "selection" else item
                url = str(item_payload.get("url", "")).strip()
                content_id = str(item_payload.get("content_id", "")).strip()
                if not url or not content_id:
                    continue
                previous = seen_by_url.get(url)
                if previous and previous[0] != content_id:
                    warnings.append(
                        {
                            "kind": "daily_digest_url_conflict",
                            "url": url,
                            "first_content_id": previous[0],
                            "first_section": previous[1],
                            "second_content_id": content_id,
                            "second_section": section_name,
                        }
                    )
                    continue
                seen_by_url[url] = (content_id, section_name)
        return warnings

    def _render_evidence_line(self, evidence: dict[str, Any]) -> str:
        source = str(evidence.get("source", "未知来源")).strip() or "未知来源"
        excerpt = self._strip_leading_punctuation(self._strip_terminal_punctuation(str(evidence.get("excerpt", "")).strip()))
        url = str(evidence.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"• {self._source_icon('builder')} {source_md}：{excerpt}"

    def _render_markdown_evidence_line(self, evidence: dict[str, Any]) -> str:
        source = str(evidence.get("source", "未知来源")).strip() or "未知来源"
        excerpt = self._strip_leading_punctuation(self._strip_terminal_punctuation(str(evidence.get("excerpt", "")).strip()))
        url = str(evidence.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"- {self._source_icon('builder')} {source_md}：{excerpt}"

    def _dedupe_theme_evidence_against_summary(
        self,
        summary: str,
        evidence_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        skipped_similar = False
        for evidence in evidence_items:
            excerpt = str(evidence.get("excerpt", "")).strip()
            if not skipped_similar and self._is_text_too_similar(summary, excerpt):
                skipped_similar = True
                continue
            filtered.append(evidence)
        return filtered

    def _is_text_too_similar(self, left: str, right: str) -> bool:
        left_norm = self._normalize_similarity_text(left)
        right_norm = self._normalize_similarity_text(right)
        if not left_norm or not right_norm:
            return False
        if left_norm == right_norm:
            return True
        shorter, longer = sorted((left_norm, right_norm), key=len)
        if len(shorter) >= 12 and shorter in longer:
            return True
        if SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.6:
            return True
        left_tokens = set(left_norm.split())
        right_tokens = set(right_norm.split())
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
        return overlap >= 0.75

    def _normalize_similarity_text(self, text: str) -> str:
        normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", text.lower())
        normalized = re.sub(r"\b[a-z]{1,3}\b", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _render_spotlight_line(self, post: dict[str, Any]) -> str:
        source = str(post.get("source", "未知来源")).strip() or "未知来源"
        text = self._strip_leading_punctuation(self._strip_terminal_punctuation(str(post.get("text", "")).strip()))
        url = str(post.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"• {self._source_icon('builder')} {source_md}：{text}"

    def _render_markdown_spotlight_line(self, post: dict[str, Any]) -> str:
        source = str(post.get("source", "未知来源")).strip() or "未知来源"
        text = self._strip_leading_punctuation(self._strip_terminal_punctuation(str(post.get("text", "")).strip()))
        url = str(post.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"- {self._source_icon('builder')} {source_md}：{text}"

    def _render_selection_block(self, selection: dict[str, Any]) -> str:
        decision = selection_decision(selection)
        copy = selection_copy(selection)
        icon = self._source_icon(str(decision.get("type", "article")).strip().lower())
        source_name = str(decision.get("channel_or_source", "未知来源")).strip() or "未知来源"
        display_name = self._get_display_name(source_name)
        title = self._sanitize_link_label(str(decision.get("title", "Untitled")).strip() or "Untitled")
        url = str(decision.get("url", "")).strip()
        value_pitch = self._strip_terminal_punctuation(str(copy.get("value_pitch", "")).strip())
        return f"{icon} **{display_name}**\n[{title}]({url})\n{value_pitch}"

    def _render_markdown_selection_block(self, selection: dict[str, Any]) -> list[str]:
        decision = selection_decision(selection)
        copy = selection_copy(selection)
        icon = self._source_icon(str(decision.get("type", "article")).strip().lower())
        source_name = str(decision.get("channel_or_source", "未知来源")).strip() or "未知来源"
        display_name = self._get_display_name(source_name)
        title = self._sanitize_link_label(str(decision.get("title", "Untitled")).strip() or "Untitled")
        url = str(decision.get("url", "")).strip()
        value_pitch = self._strip_terminal_punctuation(str(copy.get("value_pitch", "")).strip())
        return [f"{icon} **{display_name}**", f"[{title}]({url})", value_pitch]

    def _render_supplementary_line(self, item: dict[str, Any]) -> str:
        display_name = self._get_display_name(str(item.get("source_name", "未知来源")).strip() or "未知来源")
        brief = self._strip_terminal_punctuation(str(item.get("brief", "")).strip())
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        item_type = str(item.get("type", "article")).strip().lower()
        icon = self._source_icon(item_type)
        if title:
            return f"{icon} **{display_name}** · [{title}]({url}) · {brief}"
        return f"{icon} **{display_name}** · [{display_name}]({url}) · {brief}"

    def _render_markdown_supplementary_line(self, item: dict[str, Any]) -> str:
        display_name = self._get_display_name(str(item.get("source_name", "未知来源")).strip() or "未知来源")
        brief = self._strip_terminal_punctuation(str(item.get("brief", "")).strip())
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        item_type = str(item.get("type", "article")).strip().lower()
        icon = self._source_icon(item_type)
        if title:
            return f"- {icon} **{display_name}** · [{title}]({url}) · {brief}"
        return f"- {icon} **{display_name}** · [{display_name}]({url}) · {brief}"

    def _get_display_name(self, source_name: str) -> str:
        return self.display_name_map.get(source_name, self._fallback_display_name(source_name))

    def _fallback_display_name(self, source_name: str) -> str:
        if " " in source_name or any(char.isupper() for char in source_name):
            return source_name
        words = [part for part in source_name.replace("-", "_").split("_") if part]
        if not words:
            return source_name
        return " ".join(word.capitalize() for word in words)

    def _source_icon(self, item_type: str) -> str:
        if item_type == "builder":
            return "𝕏"
        if item_type == "youtube":
            return "▶️"
        return "📰"

    def _strip_terminal_punctuation(self, text: str) -> str:
        return text.rstrip("。？！.!?；;")
