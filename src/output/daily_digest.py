from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.utils.config import load_yaml


class DailyDigestBuilder:
    def __init__(self) -> None:
        self.display_name_map = self._load_display_name_map()

    def build(
        self,
        themes_data: dict[str, Any] | None,
        selections_data: dict[str, Any] | None,
        stats: dict[str, int] | None,
        target_date: date | None = None,
        candidates_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        themes_payload = themes_data or {}
        themes = list(themes_payload.get("themes", []))
        spotlight_posts = list(themes_payload.get("spotlight_posts", []))
        selections = list((selections_data or {}).get("selections", []))
        supplementary_items = self._build_supplementary_candidates(themes_payload, selections, candidates_data or {})
        stats_payload = stats or {"total": 0}
        digest_date = target_date or date.today()
        related_ids = {
            content_id
            for theme in themes
            for content_id in theme.get("related_content_ids", [])
            if str(content_id).strip()
        }

        elements: list[dict[str, Any]] = []
        if themes:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**🌡️ 今日热议（{len(themes)} 个主题）**"}})
            for theme in themes:
                evidence_lines = "\n".join(
                    self._render_evidence_line(evidence)
                    for evidence in theme.get("evidence", [])[:4]
                    if evidence.get("excerpt")
                )
                summary = self._strip_terminal_punctuation(str(theme.get("summary", "")).strip())
                content = f"**▎{theme.get('theme', '未命名主题')}**\n{summary}"
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
        themes_payload = themes_data or {}
        themes = list(themes_payload.get("themes", []))
        spotlight_posts = list(themes_payload.get("spotlight_posts", []))
        selections = list((selections_data or {}).get("selections", []))
        supplementary_items = self._build_supplementary_candidates(themes_payload, selections, candidates_data or {})
        stats_payload = stats or {"total": 0}
        digest_date = target_date or date.today()
        weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][digest_date.weekday()]
        related_ids = {
            content_id
            for theme in themes
            for content_id in theme.get("related_content_ids", [])
            if str(content_id).strip()
        }

        lines = [f"# 📡 AI Radar · {digest_date.isoformat()} 日报 · 周{weekday_cn}", ""]
        lines.append("## 🌡️ 今日热议")
        lines.append("")
        if themes:
            for theme in themes:
                lines.append(f"### ▎{theme.get('theme', '未命名主题')}")
                lines.append("")
                summary = self._strip_terminal_punctuation(str(theme.get("summary", "")).strip())
                if summary:
                    lines.append(summary)
                    lines.append("")
                for evidence in theme.get("evidence", [])[:4]:
                    if str(evidence.get("excerpt", "")).strip():
                        lines.append(self._render_markdown_evidence_line(evidence))
                lines.append("")
        elif spotlight_posts:
            for post in spotlight_posts:
                lines.append(self._render_markdown_spotlight_line(post))
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
        displayed_selection_ids = {
            str(selection.get("content_id", "")).strip()
            for selection in selections
            if str(selection.get("content_id", "")).strip()
        }
        displayed_builder_urls = {
            str(post.get("url", "")).strip()
            for post in themes_payload.get("spotlight_posts", [])
            if str(post.get("url", "")).strip()
        }
        displayed_builder_urls.update(
            str(evidence.get("url", "")).strip()
            for theme in themes_payload.get("themes", [])
            for evidence in theme.get("evidence", [])
            if str(evidence.get("url", "")).strip()
        )
        related_ids = {
            str(content_id).strip()
            for theme in themes_payload.get("themes", [])
            for content_id in theme.get("related_content_ids", [])
            if str(content_id).strip()
        }

        supplementary: list[dict[str, Any]] = []
        source_counts: dict[str, int] = {}

        editorial_pool = candidates_data.get("editorial_top10") or candidates_data.get("editorial_candidates", [])
        for max_per_source in (1, 2):
            for candidate in editorial_pool:
                content_id = str(candidate.get("content_id", "")).strip()
                source_name = str(candidate.get("channel_or_source", "")).strip()
                if not content_id or not source_name:
                    continue
                if content_id in displayed_selection_ids or content_id in related_ids:
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
                        "title": str(candidate.get("title", "")).strip(),
                        "url": str(candidate.get("url", "")).strip(),
                        "brief": self._strip_terminal_punctuation(str(candidate.get("summary", "")).strip()),
                    }
                )
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
                if len(supplementary) >= 5:
                    return supplementary

        for candidate in candidates_data.get("builder_hot_candidates", []):
            url = str(candidate.get("url", "")).strip()
            source_name = str(candidate.get("source", "")).strip()
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
                        str(candidate.get("spotlight_text") or candidate.get("core_claim", "")).strip()
                    ),
                }
            )
            if len(supplementary) >= 5:
                break

        return supplementary

    def _render_evidence_line(self, evidence: dict[str, Any]) -> str:
        source = str(evidence.get("source", "未知来源")).strip() or "未知来源"
        excerpt = self._strip_terminal_punctuation(str(evidence.get("excerpt", "")).strip())
        url = str(evidence.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"• {self._source_icon('builder')} {source_md}：{excerpt}"

    def _render_markdown_evidence_line(self, evidence: dict[str, Any]) -> str:
        source = str(evidence.get("source", "未知来源")).strip() or "未知来源"
        excerpt = self._strip_terminal_punctuation(str(evidence.get("excerpt", "")).strip())
        url = str(evidence.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"- {self._source_icon('builder')} {source_md}：{excerpt}"

    def _render_spotlight_line(self, post: dict[str, Any]) -> str:
        source = str(post.get("source", "未知来源")).strip() or "未知来源"
        text = self._strip_terminal_punctuation(str(post.get("text", "")).strip())
        url = str(post.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"• {self._source_icon('builder')} {source_md}：{text}"

    def _render_markdown_spotlight_line(self, post: dict[str, Any]) -> str:
        source = str(post.get("source", "未知来源")).strip() or "未知来源"
        text = self._strip_terminal_punctuation(str(post.get("text", "")).strip())
        url = str(post.get("url", "")).strip()
        source_md = f"[**{source}**]({url})" if url else f"**{source}**"
        return f"- {self._source_icon('builder')} {source_md}：{text}"

    def _render_selection_block(self, selection: dict[str, Any]) -> str:
        icon = self._source_icon(str(selection.get("type", "article")).strip().lower())
        source_name = str(selection.get("channel_or_source", "未知来源")).strip() or "未知来源"
        display_name = self._get_display_name(source_name)
        title = str(selection.get("title", "Untitled")).strip() or "Untitled"
        url = str(selection.get("url", "")).strip()
        value_pitch = self._strip_terminal_punctuation(str(selection.get("value_pitch", "")).strip())
        return f"{icon} **{display_name}**\n[{title}]({url})\n{value_pitch}"

    def _render_markdown_selection_block(self, selection: dict[str, Any]) -> list[str]:
        icon = self._source_icon(str(selection.get("type", "article")).strip().lower())
        source_name = str(selection.get("channel_or_source", "未知来源")).strip() or "未知来源"
        display_name = self._get_display_name(source_name)
        title = str(selection.get("title", "Untitled")).strip() or "Untitled"
        url = str(selection.get("url", "")).strip()
        value_pitch = self._strip_terminal_punctuation(str(selection.get("value_pitch", "")).strip())
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

    def _load_display_name_map(self) -> dict[str, str]:
        project_root = Path(__file__).resolve().parents[2]
        channels = load_yaml(project_root / "config" / "channels.yaml").get("channels", [])
        playlists = load_yaml(project_root / "config" / "channels.yaml").get("playlists", [])
        rss_sources = load_yaml(project_root / "config" / "rss_sources.yaml").get("sources", [])
        web_sources = load_yaml(project_root / "config" / "web_sources.yaml").get("sources", [])
        mapping: dict[str, str] = {}
        for channel in channels:
            name = str(channel.get("name", "")).strip()
            display_name = str(channel.get("display_name", "")).strip()
            if name and display_name:
                mapping[name] = display_name
        for playlist in playlists:
            name = str(playlist.get("name", "")).strip()
            display_name = str(playlist.get("display_name", "")).strip()
            if name and display_name:
                mapping[name] = display_name
        for source in rss_sources:
            name = str(source.get("name", "")).strip()
            display_name = str(source.get("display_name", "")).strip()
            if name and display_name:
                mapping[name] = display_name
        for source in web_sources:
            name = str(source.get("name", "")).strip()
            display_name = str(source.get("display_name", "")).strip()
            if name and display_name:
                mapping[name] = display_name
        return mapping

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
