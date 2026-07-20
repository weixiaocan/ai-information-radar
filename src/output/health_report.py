from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


FAILURE_STATUSES = {"failed", "feed_failed", "timed_out"}
DEGRADED_STATUSES = {"degraded", "success_with_article_fallbacks"}
PROBLEM_STATUSES = FAILURE_STATUSES | DEGRADED_STATUSES


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
        source_events: list[dict[str, Any]] = []
        for snapshot in snapshots:
            snapshot_day = self._entry_day(snapshot)
            for source, metadata in (snapshot.get("sources") or {}).items():
                if not isinstance(metadata, dict):
                    continue
                status = str(metadata.get("status", "unknown")).strip() or "unknown"
                source_counts[str(source)][status] += 1
                error = str(metadata.get("error", "")).strip()
                if error:
                    last_errors[str(source)] = error
                if status in PROBLEM_STATUSES:
                    source_events.append({"day": snapshot_day, "source": str(source), "status": status, "error": error})

        expected_days = 7
        ingest_days = self._task_days(heartbeats, "ingest", week_start, week_end)
        curate_days = self._task_days(heartbeats, "daily_curate", week_start, week_end)
        daily_days = self._daily_target_days(heartbeats, week_start, week_end)
        snapshot_days = self._snapshot_days(snapshots, week_start, week_end)
        missing = {
            "新闻抓取": self._missing_days(ingest_days, week_start, week_end),
            "内容策划": self._missing_days(curate_days, week_start, week_end),
            "日报生成与推送": self._missing_days(daily_days, week_start, week_end),
        }
        incidents, individual_events = self._group_shared_incidents(source_events)
        unresolved_failures = [event for event in source_events if event["status"] in FAILURE_STATUSES and not self._recovered(event, snapshots)]
        task_missing = any(missing.values())

        if task_missing or unresolved_failures:
            overall = "需要处理"
            template = "red"
            action = self._action_text(missing, unresolved_failures)
        elif len(snapshot_days) < expected_days:
            overall = "暂不需要处理（监控记录不完整）"
            template = "orange"
            action = "**你现在要做什么**\n• 暂时不用处理；本周故障已恢复，日报也已补齐。\n• 下周继续观察。若再次出现大批来源同时断连，优先检查本机代理或网络，而不是逐个检查信息源。"
        elif source_events:
            overall = "暂不需要处理（异常已恢复）"
            template = "orange"
            action = "**你现在要做什么**\n• 暂时不用处理；本周异常已恢复。\n• 若同类故障下周再次出现，再检查本机代理或网络。"
        else:
            overall = "运行正常，无需处理"
            template = "green"
            action = "**你现在要做什么**\n• 无需处理。"

        task_lines = [
            f"• {label}：{self._task_sentence(expected_days - len(days), expected_days, days)}"
            for label, days in missing.items()
        ]
        elements: list[dict[str, Any]] = [self._markdown(
            f"**结论：{overall}**\n" + "\n".join(task_lines)
        ), self._markdown(action)]

        event_lines: list[str] = []
        for incident in incidents:
            recovered = all(self._recovered(event, snapshots) for event in incident["events"])
            kinds = "、".join(sorted({self._source_kind(event["source"]) for event in incident["events"]}))
            state = "后续抓取已恢复" if recovered else "截至周末仍未确认恢复"
            event_lines.append(
                f"• **{incident['day']} 共享网络故障**：{incident['count']} 个来源同时断连"
                f"（{kinds}），判断为本机网络/代理问题，不是 {incident['count']} 个来源分别故障；{state}。"
            )
        individual_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for event in individual_events:
            individual_groups[(event["source"], event["status"], self._error_signature(event["error"]))].append(event)
        for grouped in individual_groups.values():
            event = grouped[-1]
            detail = self._status_label(event["status"])
            if len(grouped) > 1:
                detail += f" {len(grouped)} 天"
            if event["error"]:
                detail += f"：{self._friendly_error(event['error'])}"
            if event["status"] in DEGRADED_STATUSES:
                state = "内容未中断，无需处理"
            else:
                state = "已恢复" if self._recovered(event, snapshots) else "未确认恢复"
            event_lines.append(f"• **{self._source_label(event['source'])}**：{detail}；{state}。")
        if event_lines:
            elements.append(self._markdown("**本周发生了什么**\n" + "\n".join(event_lines)))

        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": (
                f"逐源健康记录覆盖 {len(snapshot_days)}/7 天，共观察 {len(source_counts)} 个来源。"
                "完成天数按内容目标日期计算，补发成功也算完成；同一天重复运行只计算一次。"
            )}],
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

    def _task_days(self, heartbeats: list[dict[str, Any]], task: str, week_start: date, week_end: date) -> set[date]:
        return {day for entry in heartbeats if str(entry.get("task", "")) == task
                and (day := self._entry_day(entry)) is not None and week_start <= day <= week_end}

    def _daily_target_days(self, heartbeats: list[dict[str, Any]], week_start: date, week_end: date) -> set[date]:
        days: set[date] = set()
        for entry in heartbeats:
            task = str(entry.get("task", ""))
            metadata = entry.get("metadata") or {}
            target = ""
            if task == "site_publish" and metadata.get("report_type") == "daily":
                target = str(metadata.get("target", ""))
            elif task == "daily":
                target = str(metadata.get("target_day") or metadata.get("day") or "")
            try:
                target_day = date.fromisoformat(target) if target else self._entry_day(entry)
            except ValueError:
                continue
            if target_day is not None and week_start <= target_day <= week_end:
                days.add(target_day)
        return days

    def _snapshot_days(self, snapshots: list[dict[str, Any]], week_start: date, week_end: date) -> set[date]:
        return {day for entry in snapshots if (day := self._entry_day(entry)) is not None and week_start <= day <= week_end}

    def _entry_day(self, entry: dict[str, Any]) -> date | None:
        try:
            return datetime.fromisoformat(str(entry.get("timestamp", ""))).astimezone(ZoneInfo("Asia/Shanghai")).date()
        except (TypeError, ValueError):
            return None

    def _missing_days(self, actual: set[date], week_start: date, week_end: date) -> list[date]:
        expected = {week_start + timedelta(days=offset) for offset in range((week_end - week_start).days + 1)}
        return sorted(expected - actual)

    def _task_sentence(self, actual_days: int, expected_days: int, missing_days: list[date]) -> str:
        if actual_days >= expected_days:
            return "7 天均完成"
        dates = "、".join(day.strftime("%m-%d") for day in missing_days)
        return f"完成 {actual_days} 天；缺少 {dates}"

    def _group_shared_incidents(self, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups: dict[tuple[date | None, str], list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            if event["status"] in FAILURE_STATUSES and event["error"]:
                groups[(event["day"], self._error_signature(event["error"]))].append(event)
        shared_ids: set[int] = set()
        incidents = []
        for (day, _), grouped in groups.items():
            if len(grouped) < 3:
                continue
            shared_ids.update(id(event) for event in grouped)
            incidents.append({"day": day.isoformat() if day else "日期未知", "count": len(grouped), "events": grouped})
        return incidents, [event for event in events if id(event) not in shared_ids]

    def _recovered(self, event: dict[str, Any], snapshots: list[dict[str, Any]]) -> bool:
        for snapshot in snapshots:
            day = self._entry_day(snapshot)
            if not (day and event["day"] and day > event["day"]):
                continue
            sources = snapshot.get("sources") or {}
            candidates = [sources.get(event["source"], {})]
            if event["source"].endswith(":all"):
                prefix = event["source"].partition(":")[0] + ":"
                candidates.extend(metadata for source, metadata in sources.items() if source.startswith(prefix))
            if any(metadata.get("status") in {"success", "no_new_items", "empty", "success_with_article_fallbacks"}
                   for metadata in candidates if isinstance(metadata, dict)):
                return True
        return False

    def _action_text(self, missing: dict[str, list[date]], failures: list[dict[str, Any]]) -> str:
        lines = ["**你现在要做什么**"]
        for label, days in missing.items():
            if days:
                lines.append(f"• 补跑{label}：{'、'.join(day.isoformat() for day in days)}。")
        if failures:
            if len(failures) >= 3:
                lines.append("• 多个来源同时未恢复：先检查本机网络和代理，再手动补跑 ingest；不要逐个排查来源。")
            else:
                names = "、".join(self._source_label(event["source"]) for event in failures)
                lines.append(f"• 检查仍未恢复的来源：{names}。")
        return "\n".join(lines)

    def _friendly_error(self, error: str) -> str:
        if "RemoteDisconnected" in error or "Remote end closed connection" in error:
            return "远端连接被中断（通常是本机网络或代理波动）"
        return error[:120]

    def _error_signature(self, error: str) -> str:
        if "RemoteDisconnected" in error or "Remote end closed connection" in error:
            return "remote_disconnected"
        return error[:160]

    def _status_label(self, status: str) -> str:
        return {"failed": "抓取失败", "feed_failed": "订阅源失败", "timed_out": "请求超时",
                "degraded": "部分内容失败", "success_with_article_fallbacks": "原文失败，已自动使用 RSS 摘要"}.get(status, status)

    def _source_kind(self, source: str) -> str:
        return {"rss": "RSS", "youtube": "YouTube", "youtube_playlist": "YouTube 播放列表",
                "web": "网页", "newsletter": "邮件", "zara": "Builder/X"}.get(source.partition(":")[0], source.partition(":")[0])

    def _source_label(self, source: str) -> str:
        kind, _, name = source.partition(":")
        return f"{self._source_kind(kind + ':')} · {(name or source).replace('_', ' ')}"

    def _markdown(self, content: str) -> dict[str, Any]:
        return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def shanghai_week_window(week_end: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo("Asia/Shanghai")
    week_start = week_end - timedelta(days=6)
    start_local = datetime.combine(week_start, time.min, tzinfo=tz)
    end_local = datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
