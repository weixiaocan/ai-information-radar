from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.processing.tier2_score import score_total
from src.utils.config import load_yaml
from src.utils.llm_client import DeepSeekClient


class WeeklyDigestBuilder:
    def __init__(self, client: DeepSeekClient, pitch_prompt_path: str, themes_prompt_path: str) -> None:
        self.client = client
        self.pitch_prompt_path = pitch_prompt_path
        self.themes_prompt_path = themes_prompt_path
        self.display_name_map = self._load_display_name_map()

    def build(self, items: list[ContentItem]) -> dict[str, Any]:
        top_payloads = self._build_top_payloads(items)
        theme_payload = self.client.weekly_themes(
            self.themes_prompt_path,
            [item for item in items if item.ai_summary or item.body],
        )
        week_number, monday, sunday = self._week_window(items)
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "purple",
                    "title": {
                        "tag": "plain_text",
                        "content": f"AI Radar 周报 · 第 {week_number} 周（{monday:%m-%d} ~ {sunday:%m-%d}）",
                    },
                },
                "elements": self._build_elements(theme_payload.get("themes", []), top_payloads),
            },
        }

    def render_markdown(self, items: list[ContentItem]) -> str:
        top_payloads = self._build_top_payloads(items)
        theme_payload = self.client.weekly_themes(
            self.themes_prompt_path,
            [item for item in items if item.ai_summary or item.body],
        )
        themes = theme_payload.get("themes", [])
        week_number, monday, sunday = self._week_window(items)

        lines = [f"# AI Radar 周报 · 第 {week_number} 周（{monday:%m-%d} ~ {sunday:%m-%d}）", ""]
        if themes:
            lines.append("## 本周重要主题")
            lines.append("")
            for theme in themes:
                lines.extend(self._render_markdown_theme_block(theme))
                lines.append("")

        lines.append("## 本周最值得亲自看的内容")
        lines.append("")
        medals = ["🥇", "🥈"]
        for index, payload in enumerate(top_payloads):
            if payload is None:
                continue
            item: ContentItem = payload["item"]
            display_name = self._get_display_name(item.source_name)
            lines.append(f"### {medals[index]} Top {index + 1}: {item.title}")
            lines.append("")
            lines.append(f"**{display_name}**")
            lines.append("")
            lines.append(payload["pitch"])
            lines.append("")
            lines.append(self._format_score_line(payload["total"], item.ai_score or {}))
            lines.append("")

        return "\n".join(lines)

    def _build_top_payloads(self, items: list[ContentItem]) -> list[dict[str, Any] | None]:
        ranked = sorted(
            [item for item in items if item.source_type == "youtube" and item.ai_score],
            key=lambda item: score_total(item.ai_score or {}),
            reverse=True,
        )
        top_items = ranked[:2]
        while len(top_items) < 2:
            top_items.append(None)

        top_payloads: list[dict[str, Any] | None] = []
        for item in top_items:
            if item is None:
                top_payloads.append(None)
                continue
            pitch = self.client.weekly_pitch(self.pitch_prompt_path, item, item.ai_score or {})
            top_payloads.append({"item": item, "pitch": pitch, "total": score_total(item.ai_score or {})})
        return top_payloads

    def _build_elements(
        self,
        themes: list[dict[str, Any]],
        top_payloads: list[dict[str, Any] | None],
    ) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []
        if themes:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**本周重要主题**"}})
            for theme in themes:
                elements.append(
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": self._render_theme_block(theme)},
                    }
                )
            elements.append({"tag": "hr"})

        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**本周最值得亲自看的内容**"}})
        elements.append({"tag": "hr"})

        medals = ["🥇", "🥈"]
        button_types = ["primary", "default"]
        for index, payload in enumerate(top_payloads):
            if payload is None:
                continue
            item: ContentItem = payload["item"]
            display_name = self._get_display_name(item.source_name)
            score_line = self._format_score_line(payload["total"], item.ai_score or {})
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**{medals[index]} 推荐 #{index + 1}**\n\n"
                            f"**[{item.title}]({item.url})** · **{display_name}**\n\n"
                            f"{payload['pitch']}\n\n"
                            f"{score_line}"
                        ),
                    },
                }
            )
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": f"看 Top {index + 1}"},
                            "url": item.url,
                            "type": button_types[index],
                        }
                    ],
                }
            )
            elements.append({"tag": "hr"})
        return elements

    def _render_theme_block(self, theme: dict[str, Any]) -> str:
        content_lines = [f"**🧭 {theme.get('title', '未命名主题')}**", ""]
        summary = str(theme.get("summary", "")).strip()
        if summary:
            content_lines.append(summary)
            content_lines.append("")
        for highlight in theme.get("highlights", [])[:4]:
            content_lines.append(self._render_theme_highlight_line(highlight))
        return "\n".join(content_lines)

    def _render_markdown_theme_block(self, theme: dict[str, Any]) -> list[str]:
        content_lines = [f"### 🧭 {theme.get('title', '未命名主题')}", ""]
        summary = str(theme.get("summary", "")).strip()
        if summary:
            content_lines.append(summary)
            content_lines.append("")
        for highlight in theme.get("highlights", [])[:4]:
            content_lines.append(self._render_theme_highlight_line(highlight))
        return content_lines

    def _render_theme_highlight_line(self, highlight: dict[str, Any]) -> str:
        title = str(highlight.get("title", "")).strip()
        url = str(highlight.get("url", "")).strip()
        source_name = str(highlight.get("source_name", "")).strip()
        source_type = str(highlight.get("type", "")).strip().lower()
        if not source_type:
            source_type = "youtube" if "youtube.com" in url or "youtu.be" in url else "article"
        emoji = "🎙️" if source_type == "youtube" else "📰"
        display_name = self._get_display_name(source_name) if source_name else self._fallback_display_name("unknown")
        if title and url:
            return f"> {emoji} `{display_name}` · [{title}]({url})"
        if title:
            return f"> {emoji} `{display_name}` · {title}"
        return f"> {emoji} `{display_name}`"

    def _format_score_line(self, total: float, scores: dict[str, Any]) -> str:
        return (
            f"**🏁 总分 {total:.1f}** · "
            f"相关度 {int(scores.get('relevance', 0))} · "
            f"观点 {int(scores.get('contrarian', 0))} · "
            f"嘉宾 {int(scores.get('guest_rarity', 0))} · "
            f"传播 {int(scores.get('popularity', 0))}"
        )

    def _week_window(self, items: list[ContentItem]) -> tuple[int, date, date]:
        if items:
            anchor = max(items, key=lambda item: item.published_at).published_at.date()
        else:
            anchor = date.today()
        iso = anchor.isocalendar()
        monday = anchor - timedelta(days=anchor.weekday())
        sunday = monday + timedelta(days=6)
        return iso.week, monday, sunday

    def _get_display_name(self, source_name: str) -> str:
        return self.display_name_map.get(source_name, self._fallback_display_name(source_name))

    def _load_display_name_map(self) -> dict[str, str]:
        project_root = Path(__file__).resolve().parents[2]
        channels = load_yaml(project_root / "config" / "channels.yaml").get("channels", [])
        rss_sources = load_yaml(project_root / "config" / "rss_sources.yaml").get("sources", [])
        mapping: dict[str, str] = {}
        for channel in channels:
            name = str(channel.get("name", "")).strip()
            display_name = str(channel.get("display_name", "")).strip()
            if name and display_name:
                mapping[name] = display_name
        for source in rss_sources:
            name = str(source.get("name", "")).strip()
            display_name = str(source.get("display_name", "")).strip()
            if name and display_name:
                mapping[name] = display_name
        return mapping

    def _fallback_display_name(self, source_name: str) -> str:
        words = [part for part in source_name.replace("-", "_").split("_") if part]
        if not words:
            return source_name
        return " ".join(word.capitalize() for word in words)
