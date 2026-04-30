from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from src.models.content_item import ContentItem
from src.utils.prompt_loader import load_prompt

LOGGER = logging.getLogger(__name__)


@dataclass
class DeepSeekClient:
    api_key: str
    base_url: str
    timeout_seconds: int

    def _chat_completion(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        json_output: bool = True,
        timeout_seconds: int | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": "You are a precise JSON-only assistant. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}

        response = requests.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_seconds or self.timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]

    def summarize(self, prompt_path: str, item: ContentItem) -> dict[str, Any]:
        prompt_template = load_prompt(Path(prompt_path))
        content_hint = "完整字幕" if item.body_type == "transcript" else "标题、描述与元数据"
        prompt = prompt_template.format(
            source_name=item.source_name,
            title=item.title,
            author=item.author or "Unknown",
            body_type=item.body_type,
            content_hint=content_hint,
            duration_seconds=item.duration_seconds or 0,
            view_count=item.view_count or 0,
            like_count=item.like_count or 0,
            comment_count=item.comment_count or 0,
            channel_reason=item.extra_metadata.get("channel_reason", ""),
            body=item.body[:8000],
        )
        return self._decode_json(self._chat_completion(prompt, model="deepseek-chat"))

    def score(self, prompt_path: str, item: ContentItem, x_mentions_count: int) -> dict[str, Any]:
        prompt_template = load_prompt(Path(prompt_path))
        content_label = "字幕全文" if item.body_type == "transcript" else "标题、描述与元信息"
        prompt = prompt_template.format(
            view_count=item.view_count or 0,
            like_count=item.like_count or 0,
            comment_count=item.comment_count or 0,
            x_mentions_count=x_mentions_count,
            channel_name=item.source_name,
            channel_reason=item.extra_metadata.get("channel_reason", ""),
            title=item.title,
            guest_if_extractable=item.extra_metadata.get("guest", "Unknown"),
            duration_seconds=item.duration_seconds or 0,
            content_label=content_label,
            content=item.body[:15000],
        )
        return self._decode_json(self._chat_completion(prompt, model="deepseek-chat"))

    def weekly_pitch(self, prompt_path: str, item: ContentItem, score_payload: dict[str, Any]) -> str:
        prompt_template = load_prompt(Path(prompt_path))
        prompt = prompt_template.format(
            title=item.title,
            channel_name=item.source_name,
            score_json=json.dumps(score_payload, ensure_ascii=False),
            transcript=item.body[:15000],
        )
        result = self._chat_completion(prompt, model="deepseek-chat", temperature=0.4, max_tokens=1200)
        pitch = self._coerce_pitch_text(result)
        issues = self._collect_weekly_pitch_issues(pitch)
        if issues:
            retry_prompt = (
                prompt
                + "\n\n【上一版输出存在以下问题，请严格修正后重写】\n- "
                + "\n- ".join(issues)
                + "\n输出语言必须是中文；保留三段结构，并包含 2-3 个以「• 」开头的 bullets。"
            )
            retry_result = self._chat_completion(retry_prompt, model="deepseek-chat", temperature=0.4, max_tokens=1400)
            pitch = self._coerce_pitch_text(retry_result)
        return pitch

    def weekly_themes(self, prompt_path: str, items: list[ContentItem]) -> dict[str, Any]:
        prompt_template = load_prompt(Path(prompt_path))
        digest_lines: list[str] = []
        for item in items[:80]:
            digest_lines.append(
                "\n".join(
                    [
                        f"- source_type: {item.source_type}",
                        f"  source_name: {item.source_name}",
                        f"  title: {item.title}",
                        f"  summary: {item.ai_summary or item.body[:160]}",
                        f"  keywords: {', '.join(item.ai_keywords[:5])}",
                        f"  url: {item.url}",
                    ]
                )
            )
        prompt = prompt_template.format(items_blob="\n".join(digest_lines))
        result = self._chat_completion(prompt, model="deepseek-chat", max_tokens=2600)
        payload = self._decode_json(result)
        issues = self._collect_weekly_theme_issues(payload)
        if issues:
            retry_prompt = (
                prompt
                + "\n\n【上一版输出存在以下问题，请严格修正后重写完整 JSON】\n- "
                + "\n- ".join(issues)
                + "\n请保证 themes 数量、summary 中文质量、highlight 字段完整性都符合要求。"
            )
            retry_result = self._chat_completion(retry_prompt, model="deepseek-chat", max_tokens=2800)
            payload = self._decode_json(retry_result)
        return payload

    def daily_theme_signals(self, prompt_path: str, items: list[ContentItem]) -> dict[str, Any]:
        prompt_template = load_prompt(Path(prompt_path))
        builder_posts = [
            {
                "content_id": item.content_id,
                "author": item.author or item.source_name,
                "title": item.title,
                "ai_summary": item.ai_summary or "",
                "body": item.body[:1200],
                "url": item.url,
            }
            for item in items
            if item.source_type == "zara_x"
        ]
        prompt = prompt_template.format(
            n_posts=len(builder_posts),
            builder_posts=json.dumps(builder_posts, ensure_ascii=False, indent=2),
        )
        return self._decode_json(self._chat_completion(prompt, model="deepseek-chat", max_tokens=2200))

    def daily_themes(
        self,
        prompt_path: str,
        items: list[ContentItem],
        theme_signals: list[dict[str, str]] | None = None,
        feedback: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt_template = load_prompt(Path(prompt_path))
        builder_posts = [
            {
                "content_id": item.content_id,
                "author": item.author or item.source_name,
                "title": item.title,
                "body": item.body[:600],
                "url": item.url,
            }
            for item in items
            if item.source_type == "zara_x"
        ]
        youtube_summaries = [
            {
                "content_id": item.content_id,
                "channel": item.source_name,
                "title": item.title,
                "summary": item.ai_summary or item.body[:200],
                "url": item.url,
            }
            for item in items
            if item.source_type == "youtube"
        ]
        article_summaries = [
            {
                "content_id": item.content_id,
                "source": item.source_name,
                "title": item.title,
                "summary": item.ai_summary or item.body[:200],
                "url": item.url,
            }
            for item in items
            if item.source_type != "youtube" and item.source_type != "zara_x"
        ]
        prompt = prompt_template.format(
            n_posts=len(builder_posts),
            builder_posts=json.dumps(builder_posts, ensure_ascii=False, indent=2),
            theme_signals_json=json.dumps(theme_signals or [], ensure_ascii=False, indent=2),
            youtube_summaries=json.dumps(youtube_summaries, ensure_ascii=False, indent=2),
            article_summaries=json.dumps(article_summaries, ensure_ascii=False, indent=2),
        )
        if feedback:
            prompt += (
                "\n\n【上一版输出存在以下问题，请严格修正后重写完整 JSON】\n- "
                + "\n- ".join(feedback)
                + "\n请不要只修一部分；重写完整输出，并确保 summary 和 excerpt 都是自然中文。"
            )
        return self._decode_json(self._chat_completion(prompt, model="deepseek-chat", max_tokens=2000))

    def daily_selections(
        self,
        prompt_path: str,
        items: list[ContentItem],
        exclude_ids: set[str],
    ) -> dict[str, Any]:
        prompt_template = load_prompt(Path(prompt_path))
        candidates = [
            {
                "content_id": item.content_id,
                "type": "youtube" if item.source_type == "youtube" else "article",
                "channel_or_source": item.source_name,
                "title": item.title,
                "url": item.url,
                "summary": item.ai_summary or item.body[:240],
                "keywords": item.ai_keywords,
            }
            for item in items
            if item.source_type != "zara_x"
        ]
        prompt = prompt_template.format(
            exclude_content_ids=json.dumps(sorted(exclude_ids), ensure_ascii=False, indent=2),
            candidates_json=json.dumps(candidates, ensure_ascii=False, indent=2),
        )
        return self._decode_json(self._chat_completion(prompt, model="deepseek-chat", max_tokens=1600))

    def ebook_report(self, prompt_path: str, item: ContentItem, rank: int) -> str:
        prompt_template = load_prompt(Path(prompt_path))
        scores = item.ai_score or {}
        reasons = item.ai_score_reasons or {}
        prompt = prompt_template.format(
            rank=rank,
            title=item.title,
            channel_name=item.source_name,
            url=item.url,
            published_at=item.published_at.isoformat(),
            duration_seconds=item.duration_seconds or 0,
            transcript_status=item.extra_metadata.get("transcript_status", item.body_type),
            ai_summary=item.ai_summary or "",
            one_line_pitch=item.extra_metadata.get("one_line_pitch", ""),
            relevance=scores.get("relevance", 0),
            contrarian=scores.get("contrarian", 0),
            guest_rarity=scores.get("guest_rarity", 0),
            popularity=scores.get("popularity", 0),
            reason_relevance=reasons.get("relevance", ""),
            reason_contrarian=reasons.get("contrarian", ""),
            reason_guest_rarity=reasons.get("guest_rarity", ""),
            reason_popularity=reasons.get("popularity", ""),
            source_text=item.body[:24000],
        )
        return self._chat_completion(
            prompt,
            model="deepseek-chat",
            temperature=0.4,
            max_tokens=5200,
            json_output=False,
            timeout_seconds=max(self.timeout_seconds * 4, 120),
        )

    def _decode_json(self, raw_text: str, expect_json: bool = True) -> Any:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            LOGGER.warning("Failed to decode model response as JSON: %s", raw_text[:200])
            if expect_json:
                raise
            return raw_text

    def _coerce_pitch_text(self, raw_text: str) -> str:
        data = self._decode_json(raw_text, expect_json=False)
        if isinstance(data, dict):
            return str(data.get("pitch") or data.get("content") or json.dumps(data, ensure_ascii=False))
        return str(data)

    def _collect_weekly_pitch_issues(self, pitch: str) -> list[str]:
        issues: list[str] = []
        if self._looks_mostly_english(pitch):
            issues.append("输出不是中文，请全部改成中文，只有专有名词保留英文")
        bullet_count = pitch.count("• ")
        if bullet_count < 2:
            issues.append("第二段缺少 2-3 个以「• 」开头的 bullets")
        paragraph_count = len([part for part in pitch.split("\n\n") if part.strip()])
        if paragraph_count < 3:
            issues.append("没有按三段结构输出，请用空行分成三段")
        return issues

    def _collect_weekly_theme_issues(self, payload: dict[str, Any] | None) -> list[str]:
        data = payload or {}
        themes = data.get("themes", [])
        issues: list[str] = []
        if not isinstance(themes, list) or not themes:
            return ["themes 为空，请输出 3 到 5 个主题"]
        if len(themes) < 3 or len(themes) > 5:
            issues.append("themes 数量必须在 3 到 5 个之间")
        for theme_index, theme in enumerate(themes[:5], start=1):
            title = str(theme.get("title", "")).strip()
            summary = str(theme.get("summary", "")).strip()
            highlights = theme.get("highlights", [])
            if not title:
                issues.append(f"主题{theme_index}缺少 title")
            if not summary:
                issues.append(f"主题{theme_index}缺少 summary")
            elif self._looks_mostly_english(summary):
                issues.append(f"主题{theme_index}的 summary 不是中文")
            if not isinstance(highlights, list) or len(highlights) < 2 or len(highlights) > 4:
                issues.append(f"主题{theme_index}的 highlights 数量必须在 2 到 4 条之间")
                continue
            for highlight_index, highlight in enumerate(highlights, start=1):
                if not str(highlight.get("title", "")).strip():
                    issues.append(f"主题{theme_index}的 highlight {highlight_index} 缺少 title")
                if not str(highlight.get("url", "")).strip():
                    issues.append(f"主题{theme_index}的 highlight {highlight_index} 缺少 url")
                if not str(highlight.get("source_name", "")).strip():
                    issues.append(f"主题{theme_index}的 highlight {highlight_index} 缺少 source_name")
                highlight_type = str(highlight.get("type", "")).strip()
                if highlight_type not in {"youtube", "article"}:
                    issues.append(f"主题{theme_index}的 highlight {highlight_index} type 必须是 youtube 或 article")
        return issues

    def _looks_mostly_english(self, text: str) -> bool:
        ascii_letters = len(re.findall(r"[A-Za-z]", text))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        return ascii_letters >= 20 and ascii_letters > chinese_chars
