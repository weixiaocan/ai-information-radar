from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


class WeeklyHealthReportBuilder:
    def build(
        self,
        snapshots: list[dict[str, Any]],
        heartbeats: list[dict[str, Any]],
        *,
        week_start: date,
        week_end: date,
    ) -> dict[str, Any]:
        source_counts: dict[str, Counter[str]] = defaultdict(Counter)
        last_errors: dict[str, str] = {}
        for snapshot in snapshots:
            for source, metadata in (snapshot.get("sources") or {}).items():
                if not isinstance(metadata, dict):
                    continue
                status = str(metadata.get("status", "unknown")).strip() or "unknown"
                source_counts[str(source)][status] += 1
                error = str(metadata.get("error", "")).strip()
                if error:
                    last_errors[str(source)] = error

        expected_days = 7
        ingest_runs = self._successful_days(heartbeats, "ingest", week_start, week_end)
        daily_runs = self._successful_days(heartbeats, "daily", week_start, week_end)
        curate_runs = self._successful_days(heartbeats, "daily_curate", week_start, week_end)
        snapshot_days = self._snapshot_days(snapshots, week_start, week_end)
        problem_sources = {
            source: counts
            for source, counts in source_counts.items()
            if any(counts[status] for status in ("failed", "feed_failed", "timed_out", "degraded", "success_with_article_fallbacks"))
        }
        task_missing = ingest_runs < expected_days or daily_runs < expected_days or curate_runs < expected_days
        has_failure = any(
            counts["failed"] or counts["feed_failed"] or counts["timed_out"] for counts in problem_sources.values()
        )
        if has_failure or task_missing:
            overall = "需要处理"
            template = "red"
        elif len(snapshot_days) < expected_days:
            overall = "数据积累中"
            template = "orange"
        elif problem_sources:
            overall = "有降级"
            template = "orange"
        else:
            overall = "运行正常"
            template = "green"

        elements: list[dict[str, Any]] = [{
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**本周结论：{overall}**\n"
                    f"• 新闻抓取：{self._task_sentence(ingest_runs, expected_days)}\n"
                    f"• 内容策划：{self._task_sentence(curate_runs, expected_days)}\n"
                    f"• 日报生成与推送：{self._task_sentence(daily_runs, expected_days)}"
                ),
            },
        }]
        if problem_sources:
            lines = []
            for source, counts in sorted(problem_sources.items()):
                parts = [
                    f"{self._status_label(status)} {count} 天"
                    for status, count in counts.items()
                    if status not in {"success", "no_new_items", "empty"} and count
                ]
                detail = "，".join(parts)
                error = last_errors.get(source, "")
                if error:
                    error = error[:160]
                    detail += f"；最近错误：{error}"
                lines.append(f"• **{self._source_label(source)}**：{detail}")
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**异常与降级来源**\n" + "\n".join(lines)}})
        else:
            source_message = "本周逐源记录中未发现失败或降级。"
            if len(snapshot_days) < expected_days:
                source_message += f"但健康记录目前只覆盖 {len(snapshot_days)} 天，暂不能代表完整一周。"
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": source_message}})

        observed_sources = len(source_counts)
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"逐源健康记录覆盖 {len(snapshot_days)}/7 天，共观察 {observed_sources} 个来源；同一天重复运行只计算一次"}],
        })
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": template,
                    "title": {"tag": "plain_text", "content": f"AI Radar 系统健康周报 · {week_start}—{week_end}"},
                },
                "elements": elements,
            },
        }

    def _successful_days(
        self,
        heartbeats: list[dict[str, Any]],
        task: str,
        week_start: date,
        week_end: date,
    ) -> int:
        days: set[date] = set()
        tz = ZoneInfo("Asia/Shanghai")
        for entry in heartbeats:
            if str(entry.get("task", "")) != task:
                continue
            try:
                day = datetime.fromisoformat(str(entry.get("timestamp", ""))).astimezone(tz).date()
            except (TypeError, ValueError):
                continue
            if week_start <= day <= week_end:
                days.add(day)
        return len(days)

    def _snapshot_days(
        self,
        snapshots: list[dict[str, Any]],
        week_start: date,
        week_end: date,
    ) -> set[date]:
        days: set[date] = set()
        tz = ZoneInfo("Asia/Shanghai")
        for entry in snapshots:
            try:
                day = datetime.fromisoformat(str(entry.get("timestamp", ""))).astimezone(tz).date()
            except (TypeError, ValueError):
                continue
            if week_start <= day <= week_end:
                days.add(day)
        return days

    def _task_sentence(self, actual_days: int, expected_days: int) -> str:
        if actual_days >= expected_days:
            return "7 天均完成"
        return f"完成 {actual_days} 天，缺少 {expected_days - actual_days} 天"

    def _status_label(self, status: str) -> str:
        return {
            "failed": "抓取失败",
            "feed_failed": "订阅源失败",
            "timed_out": "请求超时",
            "degraded": "部分内容失败",
            "success_with_article_fallbacks": "原文失败但已用 RSS 摘要降级",
        }.get(status, status)

    def _source_label(self, source: str) -> str:
        kind, _, name = source.partition(":")
        kind_label = {
            "rss": "RSS",
            "youtube": "YouTube",
            "youtube_playlist": "YouTube 播放列表",
            "web": "网页",
            "newsletter": "邮件订阅",
            "zara": "Builder/X",
        }.get(kind, kind)
        display_name = (name or source).replace("_", " ")
        return f"{kind_label} · {display_name}"


def shanghai_week_window(week_end: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo("Asia/Shanghai")
    week_start = week_end - timedelta(days=6)
    start_local = datetime.combine(week_start, time.min, tzinfo=tz)
    end_local = datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
