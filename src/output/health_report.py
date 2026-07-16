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

        task_counts = Counter(str(entry.get("task", "")) for entry in heartbeats)
        ingest_runs = task_counts["ingest"]
        daily_runs = task_counts["daily"]
        curate_runs = task_counts["daily_curate"]
        expected_days = 7
        problem_sources = {
            source: counts
            for source, counts in source_counts.items()
            if any(counts[status] for status in ("failed", "feed_failed", "timed_out", "degraded", "success_with_article_fallbacks"))
        }
        task_missing = ingest_runs < expected_days or daily_runs < expected_days or curate_runs < expected_days
        overall = "异常" if any(
            counts["failed"] or counts["feed_failed"] or counts["timed_out"] for counts in problem_sources.values()
        ) or task_missing else ("有降级" if problem_sources else "正常")
        template = "red" if overall == "异常" else ("orange" if overall == "有降级" else "green")

        elements: list[dict[str, Any]] = [{
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**运行结论：{overall}**\n"
                    f"Ingest {ingest_runs}/{expected_days} · Daily Curate {curate_runs}/{expected_days} · Daily {daily_runs}/{expected_days}"
                ),
            },
        }]
        if problem_sources:
            lines = []
            for source, counts in sorted(problem_sources.items()):
                parts = [f"{status} × {count}" for status, count in counts.items() if status not in {"success", "no_new_items"} and count]
                detail = "，".join(parts)
                error = last_errors.get(source, "")
                if error:
                    error = error[:160]
                    detail += f"；最近错误：{error}"
                lines.append(f"• **{source}**：{detail}")
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**异常与降级来源**\n" + "\n".join(lines)}})
        else:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "本周未记录来源失败或降级。"}})

        observed_sources = len(source_counts)
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"观察到 {len(snapshots)} 次抓取快照 · {observed_sources} 个来源"}],
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


def shanghai_week_window(week_end: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo("Asia/Shanghai")
    week_start = week_end - timedelta(days=6)
    start_local = datetime.combine(week_start, time.min, tzinfo=tz)
    end_local = datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
