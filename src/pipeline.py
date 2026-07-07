from __future__ import annotations

import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.models.content_item import ContentItem
from src.output.daily_digest import DailyDigestBuilder
from src.output.feishu_delivery import FeishuDelivery
from src.output.top_video_report import TopVideoReportWriter
from src.output.weekly_digest import WeeklyDigestBuilder
from src.publishing.site_publisher import SitePublisher
from src.processing.daily_candidate_builder import DailyCandidateBuilder
from src.processing.daily_decision_resolver import DailyDecisionResolver
from src.processing.daily_curator import DailyCurator
from src.processing.theme_aggregator import ThemeAggregator
from src.processing.tier1_summary import Tier1Summarizer
from src.processing.tier2_score import Tier2Scorer, score_total
from src.storage.state_manager import StateManager
from src.storage.transcript_store import TranscriptStore
from src.utils.config import Settings, load_yaml
from src.utils.daily_state import normalize_daily_candidates_payload, theme_decision
from src.utils.llm_client import DeepSeekClient
from src.utils.transcript_client import TranscriptClient

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_manager = StateManager(settings.project_root / "state")
        self.transcript_store = TranscriptStore(settings.project_root / "transcripts")
        self.client = DeepSeekClient(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        self.transcript_client = TranscriptClient(
            timeout_seconds=settings.request_timeout_seconds,
            supadata_api_key=settings.supadata_api_key,
        )
        self.daily_builder = DailyDigestBuilder()
        self.daily_candidate_builder = DailyCandidateBuilder(
            self.client,
            settings.project_root / "prompts" / "builder_hot_decision.md",
            copy_prompt_path=settings.project_root / "prompts" / "builder_hot_copy.md",
        )
        self.theme_aggregator = ThemeAggregator(
            self.client,
            settings.project_root / "prompts" / "theme_decision.md",
            copy_prompt_path=settings.project_root / "prompts" / "theme_copy.md",
        )
        self.daily_curator = DailyCurator(
            self.client,
            settings.project_root / "prompts" / "selection_decision.md",
            copy_prompt_path=settings.project_root / "prompts" / "selection_copy.md",
        )
        self.daily_decision_resolver = DailyDecisionResolver()
        self.weekly_builder = WeeklyDigestBuilder(
            self.client,
            str(settings.project_root / "prompts" / "weekly_pitch.md"),
            str(settings.project_root / "prompts" / "weekly_themes.md"),
        )
        self.daily_reports_root = settings.project_root / "reports" / "daily"
        self.weekly_reports_root = settings.project_root / "reports" / "weekly"
        self.daily_reports_root.mkdir(parents=True, exist_ok=True)
        self.weekly_reports_root.mkdir(parents=True, exist_ok=True)
        self.report_writer = TopVideoReportWriter(
            self.client,
            settings.project_root / "prompts" / "ebook_report.md",
            settings.project_root / "reports" / "ebook",
        )
        self.summarizer = Tier1Summarizer(self.client, settings.project_root / "prompts" / "tier1_summary.md")
        self.scorer = Tier2Scorer(
            self.client,
            settings.project_root / "prompts" / "tier2_coarse.md",
            settings.project_root / "prompts" / "tier2_score.md",
            self.state_manager,
        )
        self.feishu = FeishuDelivery(settings.feishu_webhook_url, settings.request_timeout_seconds)
        self.site_publisher = (
            SitePublisher(
                settings.project_root,
                settings.site_repo_path,
                git_branch=settings.site_git_branch,
                timeout_seconds=settings.site_publish_timeout_seconds,
                push_retry_delays_seconds=settings.site_push_retry_delays_seconds,
            )
            if settings.site_publish_enabled and settings.site_repo_path is not None
            else None
        )
        self._last_zara_fetch_reports: list[Any] = []

    def ingest(self, recent_days_override: int | None = None, ignore_seen: bool = False) -> list[ContentItem]:
        from src.ingestion.gmail_newsletter_fetcher import GmailNewsletterFetcher
        from src.ingestion.rss_fetcher import RSSFetcher
        from src.ingestion.web_fetcher import WebFetcher
        from src.ingestion.youtube_fetcher import YouTubeFetcher
        from src.ingestion.zara_fetcher import ZaraFetcher

        seen_ids = self.state_manager.load_seen_ids()
        effective_seen_ids = set() if ignore_seen else seen_ids
        window_end = datetime.now(timezone.utc)
        recent_days = (
            recent_days_override
            if recent_days_override is not None
            else (self.settings.bootstrap_days if not seen_ids else self.settings.incremental_days)
        )
        previous_window = self.state_manager.load_latest_window("ingest")
        window_start = self._resolve_ingest_window_start(
            previous_window,
            recent_days=recent_days,
            recent_days_override=recent_days_override,
            ignore_seen=ignore_seen,
            seen_ids=seen_ids,
            window_end=window_end,
        )
        channel_config = load_yaml(self.settings.project_root / "config" / "channels.yaml")
        channels = channel_config.get("channels", [])
        playlists = channel_config.get("playlists", [])
        rss_sources = load_yaml(self.settings.project_root / "config" / "rss_sources.yaml").get("sources", [])
        web_sources = load_yaml(self.settings.project_root / "config" / "web_sources.yaml").get("sources", [])
        newsletter_sources = load_yaml(self.settings.project_root / "config" / "newsletter_sources.yaml").get("sources", [])
        zara_feeds = [
            feed
            for feed in load_yaml(self.settings.project_root / "config" / "zara_feed.yaml").get("feeds", [])
            if str(feed.get("name", "")).strip() == "zara_x"
        ]

        youtube_items = self._safe_fetch_youtube(
            YouTubeFetcher,
            channels,
            effective_seen_ids,
            recent_days,
            window_start,
            window_end,
        )
        playlist_items = self._safe_fetch_youtube_playlists(
            YouTubeFetcher,
            playlists,
            effective_seen_ids,
            recent_days,
            window_start,
            window_end,
        )
        rss_items = self._safe_fetch_rss(RSSFetcher, rss_sources, effective_seen_ids, recent_days, window_start, window_end)
        web_items = self._safe_fetch_web(WebFetcher, web_sources, effective_seen_ids, recent_days, window_start, window_end)
        newsletter_items = self._safe_fetch_newsletters(
            GmailNewsletterFetcher,
            newsletter_sources,
            effective_seen_ids,
            recent_days,
            window_start,
            window_end,
        )
        zara_items = self._safe_fetch_zara(
            ZaraFetcher,
            zara_feeds,
            effective_seen_ids,
            recent_days,
            window_start,
            window_end,
        )
        self.state_manager.save_latest_source_statuses(
            {
                "zara_x": self._summarize_zara_source_status("zara_x"),
            }
        )
        items = youtube_items + playlist_items + rss_items + web_items + newsletter_items + zara_items
        self.transcript_store.save_many(items)
        seen_ids.update(item.content_id for item in items)
        self.state_manager.save_seen_ids(seen_ids)
        self.state_manager.save_stage_content_ids("ingest", [item.content_id for item in items])
        self.state_manager.save_latest_window(
            "ingest",
            self._build_window_payload(window_start, window_end),
        )
        self.state_manager.write_heartbeat(
            "ingest",
            {
                "new_items": len(items),
                "recent_days": recent_days,
                "ignore_seen": ignore_seen,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )
        return items

    def tier1(self, items: list[ContentItem] | None = None) -> list[ContentItem]:
        items = items or self._load_stage_items("ingest")
        enriched = self.summarizer.run(items)
        self.transcript_store.save_many(enriched)
        self.state_manager.save_stage_content_ids("tier1", [item.content_id for item in enriched])
        self.state_manager.write_heartbeat("tier1", {"items": len(enriched)})
        return enriched

    def tier2(self, items: list[ContentItem] | None = None) -> list[ContentItem]:
        items = items or self._load_stage_items("tier1")
        mentions = compute_x_mentions(items)
        youtube_items = [item for item in items if item.source_type == "youtube"]
        coarse_scored = self.scorer.run_coarse(youtube_items, mentions)
        finalists = select_top_candidates(coarse_scored, self.settings.tier2_candidate_count)
        finalists = self._fetch_transcripts_for_finalists(finalists)
        finalists = self.scorer.run_deep(finalists, mentions)
        finalists_by_id = {item.content_id: item for item in finalists}
        merged_items = [finalists_by_id.get(item.content_id, item) for item in items]
        self.transcript_store.save_many(merged_items)
        self.state_manager.save_stage_content_ids("tier2", [item.content_id for item in merged_items])
        self.state_manager.write_heartbeat(
            "tier2",
            {"items": len(youtube_items), "finalists": len(finalists)},
        )
        return merged_items

    def daily(self, items: list[ContentItem] | None = None, deliver: bool = True, run_id: str | None = None) -> dict:
        items = items or self._load_stage_items("tier1")
        report_window = self.state_manager.load_latest_window("ingest")
        target_date = self._resolve_daily_target_date(items, report_window)
        day = target_date.isoformat() if target_date else "latest"
        resolved_run_id = run_id or (self.state_manager.resolve_latest_daily_run_id(day) if target_date else None)
        daily_items = self._load_items_for_daily_report(target_date, report_window, items)
        if deliver and target_date and not self._daily_curate_artifacts_ready(day, resolved_run_id, len(daily_items)):
            manifest = self.state_manager.load_daily_manifest(day, resolved_run_id) if resolved_run_id else {}
            payload = {
                "status": "blocked",
                "reason": "daily_curate_incomplete",
                "day": day,
                "run_id": resolved_run_id or "",
                "items": len(daily_items),
            }
            self._append_ops_event(
                {
                    "severity": "blocked",
                    "task": "daily",
                    "event": "daily_curate_incomplete",
                    "day": day,
                    "run_id": resolved_run_id or "",
                    "deliver": deliver,
                    "details": payload,
                }
            )
            self.state_manager.write_heartbeat("daily_blocked_curate_incomplete", payload)
            return payload
        candidates_data = (
            self.state_manager.load_daily_candidates(day, resolved_run_id)
            if target_date
            else normalize_daily_candidates_payload({"builder_hot_candidates": [], "editorial_candidates": []})
        )
        themes_data = (
            self.state_manager.load_daily_themes(day, resolved_run_id)
            if target_date
            else {"themes": [], "discussion_dispersion": "dispersed"}
        )
        selections_data = self.state_manager.load_daily_selections(day, resolved_run_id) if target_date else {"selections": []}
        quality = (
            self._assess_daily_curate_quality(
                self.state_manager.load_daily_manifest(day, resolved_run_id) if target_date and resolved_run_id else {},
                candidates_data,
                themes_data,
                selections_data,
            )
            if deliver and target_date
            else {"blocking": {}, "warnings": {}}
        )
        if quality["blocking"]:
            payload = {
                "status": "blocked",
                "reason": "daily_curate_blocking_errors",
                "day": day,
                "run_id": resolved_run_id or "",
                "items": len(daily_items),
                "blocking_errors": quality["blocking"],
            }
            if quality["warnings"]:
                payload["warnings"] = quality["warnings"]
            self._append_ops_event(
                {
                    "severity": "blocked",
                    "task": "daily",
                    "event": "daily_curate_blocking_errors",
                    "day": day,
                    "run_id": resolved_run_id or "",
                    "deliver": deliver,
                    "details": payload,
                }
            )
            self.state_manager.write_heartbeat("daily_blocked_curate_blocking_errors", payload)
            return payload
        if quality["warnings"]:
            self._append_ops_event(
                {
                    "severity": "warning",
                    "task": "daily",
                    "event": "daily_curate_deliverable_warnings",
                    "day": day,
                    "run_id": resolved_run_id or "",
                    "deliver": deliver,
                    "warnings": quality["warnings"],
                    "action": "delivering_with_fallbacks",
                }
            )
        stats = {"total": len(daily_items)}
        invariant_warnings = self.daily_builder.collect_invariant_warnings(
            themes_data,
            selections_data,
            candidates_data,
        )
        for warning in invariant_warnings:
            warning_payload: dict[str, Any] = {"day": day, **warning}
            self.state_manager.append_invariant_warning(warning_payload)
        payload = self.daily_builder.build(themes_data, selections_data, stats, target_date=target_date, candidates_data=candidates_data)
        report_path = self._write_daily_report(themes_data, selections_data, stats, target_date, candidates_data)
        if deliver:
            self.feishu.send(payload)
        self._publish_site_report("daily", report_path, day)
        self.state_manager.write_heartbeat(
            "daily",
            {
                "items": len(daily_items),
                "themes": len(themes_data.get("themes", [])),
                "selections": len(selections_data.get("selections", [])),
                "invariant_warnings": len(invariant_warnings),
                "degraded_warnings": len(quality["warnings"]),
                "run_id": resolved_run_id or "",
            },
        )
        return payload

    def daily_curate(self, items: list[ContentItem] | None = None, run_id: str | None = None) -> dict[str, Any]:
        items = items or self._load_stage_items("tier1")
        report_window = self.state_manager.load_latest_window("ingest")
        target_date = self._resolve_daily_target_date(items, report_window)
        day = target_date.isoformat() if target_date else "latest"
        resolved_run_id = run_id or self.state_manager.create_daily_run(day, source_window=report_window, status="curating")
        daily_items = self._load_items_for_daily_report(target_date, report_window, items)
        candidates = self.daily_candidate_builder.build(daily_items)
        candidates = normalize_daily_candidates_payload(candidates)
        self.state_manager.save_daily_candidates(day, candidates, resolved_run_id)
        builder_hot_candidates = candidates.get("builder_hot_candidates", [])
        editorial_candidate_ids = {
            str(candidate.get("content_id", "")).strip()
            for candidate in candidates.get("editorial_top10", [])
            if str(candidate.get("content_id", "")).strip()
        }
        editorial_items = [item for item in daily_items if item.content_id in editorial_candidate_ids]
        themes_data = self.theme_aggregator.aggregate_themes(daily_items, builder_hot_candidates)
        latest_source_statuses = self.state_manager.load_latest_source_statuses()
        zara_x_status = latest_source_statuses.get("zara_x", {})
        if (
            not themes_data.get("themes")
            and not themes_data.get("spotlight_posts")
            and str(zara_x_status.get("status", "")).strip() in {"failed", "timed_out"}
        ):
            themes_data["degraded_reason"] = "builder_source_fetch_failed"
            themes_data["degraded_stage"] = "builder_decision"
            themes_data["fallback_mode"] = "empty_themes"
            themes_data["degraded_source"] = "zara_x"
        self.state_manager.save_daily_themes(day, themes_data, resolved_run_id)
        exclude_ids: set[str] = set()
        for theme in themes_data.get("themes", []):
            exclude_ids.update(theme_decision(theme).get("member_content_ids", []))
        selections_data = self.daily_curator.curate_daily(editorial_items, exclude_ids)
        self.state_manager.save_daily_selections(day, selections_data, resolved_run_id)
        resolver = getattr(self, "daily_decision_resolver", DailyDecisionResolver())
        candidates, themes_data, selections_data = resolver.resolve(
            candidates,
            themes_data,
            selections_data,
        )
        self.state_manager.save_daily_candidates(day, candidates, resolved_run_id)
        self.state_manager.save_daily_themes(day, themes_data, resolved_run_id)
        self.state_manager.save_daily_selections(day, selections_data, resolved_run_id)
        self.state_manager.finalize_daily_run(
            day,
            resolved_run_id,
            status="completed",
            candidates=candidates,
            themes=themes_data,
            selections=selections_data,
            source_window=report_window,
        )
        self.state_manager.write_heartbeat(
            "daily_curate",
            {
                "items": len(daily_items),
                "builder_hot_candidates": len(builder_hot_candidates),
                "editorial_candidates": len(editorial_items),
                "themes": len(themes_data.get("themes", [])),
                "selections": len(selections_data.get("selections", [])),
                "run_id": resolved_run_id,
            },
        )
        return {"run_id": resolved_run_id, "day": day, "candidates": candidates, "themes": themes_data, "selections": selections_data}

    def _daily_curate_run_ready(self, day: str, run_id: str | None, item_count: int) -> bool:
        return self._daily_curate_artifacts_ready(day, run_id, item_count)

    def _daily_curate_artifacts_ready(self, day: str, run_id: str | None, item_count: int) -> bool:
        if item_count <= 0:
            return True
        if not run_id:
            return False
        manifest = self.state_manager.load_daily_manifest(day, run_id)
        if str(manifest.get("status", "")).strip() != "completed":
            return False
        artifacts = manifest.get("artifacts", {})
        if not all(str(artifacts.get(name, "")).strip() for name in ("candidates", "themes", "selections")):
            return False
        return True

    def _assess_daily_curate_quality(
        self,
        manifest: dict[str, Any],
        candidates_data: dict[str, Any],
        themes_data: dict[str, Any],
        selections_data: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        degraded = self._daily_curate_degraded_summary(manifest)
        blocking: dict[str, Any] = {}
        warnings: dict[str, Any] = {}
        for section, metadata in degraded.items():
            fallback_mode = str(metadata.get("fallback_mode", "")).strip()
            degraded_stage = str(metadata.get("degraded_stage", "")).strip()
            if section == "candidates" and degraded_stage == "builder_copy" and fallback_mode == "per_item_copy_fallback":
                issues = self._builder_copy_fallback_issues(candidates_data)
                if issues:
                    blocking[section] = {**metadata, "quality_issues": issues}
                else:
                    warnings[section] = {**metadata, "fallback_quality": "passed"}
                continue
            blocking[section] = metadata
        if not blocking and not candidates_data.get("builder_hot_candidates") and not selections_data.get("selections"):
            blocking.setdefault(
                "daily_content",
                {
                    "degraded_reason": "empty_daily_digest",
                    "degraded_stage": "daily_quality",
                    "fallback_mode": "",
                },
            )
        return {"blocking": blocking, "warnings": warnings}

    def _daily_curate_degraded_summary(self, manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
        degraded = manifest.get("degraded", {})
        if not isinstance(degraded, dict):
            return {}
        summary: dict[str, dict[str, str]] = {}
        for section in ("candidates", "themes", "selections"):
            metadata = degraded.get(section, {})
            if not isinstance(metadata, dict):
                continue
            degraded_stage = str(metadata.get("degraded_stage", "")).strip()
            degraded_reason = str(metadata.get("degraded_reason", "")).strip()
            fallback_mode = str(metadata.get("fallback_mode", "")).strip()
            if section == "themes" and fallback_mode == "spotlight_only":
                continue
            if degraded_stage or degraded_reason or fallback_mode:
                summary[section] = {
                    "degraded_reason": degraded_reason,
                    "degraded_stage": degraded_stage,
                    "fallback_mode": fallback_mode,
                }
        return summary

    def _builder_copy_fallback_issues(self, candidates_data: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for candidate in candidates_data.get("builder_hot_candidates", []):
            decision = candidate.get("decision", {}) if isinstance(candidate, dict) else {}
            copy = candidate.get("copy", {}) if isinstance(candidate, dict) else {}
            content_id = str(decision.get("content_id", "")).strip()
            missing_fields = [
                field
                for field, value in {
                    "source": decision.get("source"),
                    "url": decision.get("url"),
                    "topic_label": copy.get("topic_label"),
                    "core_claim": copy.get("core_claim"),
                    "excerpt": copy.get("excerpt"),
                    "spotlight_text": copy.get("spotlight_text"),
                }.items()
                if not str(value or "").strip()
            ]
            short_fields = [
                field
                for field in ("core_claim", "excerpt", "spotlight_text")
                if 0 < len(str(copy.get(field, "")).strip()) < 12
            ]
            mojibake_fields = [
                field
                for field in ("topic_label", "core_claim", "excerpt", "spotlight_text")
                if self._looks_like_mojibake(str(copy.get(field, "")))
            ]
            if missing_fields or short_fields or mojibake_fields:
                issues.append(
                    {
                        "content_id": content_id,
                        "missing_fields": missing_fields,
                        "short_fields": short_fields,
                        "mojibake_fields": mojibake_fields,
                    }
                )
        if not candidates_data.get("builder_hot_candidates"):
            issues.append(
                {
                    "content_id": "",
                    "missing_fields": ["builder_hot_candidates"],
                    "short_fields": [],
                    "mojibake_fields": [],
                }
            )
        return issues

    def _looks_like_mojibake(self, text: str) -> bool:
        if "\ufffd" in text:
            return True
        markers = ("Ã", "Â", "â€", "锛", "鎵", "鐨", "浠", "涓", "绋", "妯")
        return sum(1 for marker in markers if marker in text) >= 2

    def _append_ops_event(self, payload: dict[str, Any]) -> None:
        append_ops_event = getattr(self.state_manager, "append_ops_event", None)
        if append_ops_event:
            append_ops_event(payload)

    def x_refresh_site(self) -> dict[str, Any]:
        from src.ingestion.zara_fetcher import ZaraFetcher

        base_window = self.state_manager.load_latest_window("ingest")
        if not base_window:
            self.state_manager.write_heartbeat("x_refresh_site_error", {"reason": "missing_ingest_window"})
            return {"updated": False, "reason": "missing_ingest_window"}

        refresh_start = self._parse_window_timestamp(base_window.get("end_at"))
        if refresh_start is None:
            self.state_manager.write_heartbeat("x_refresh_site_error", {"reason": "missing_ingest_window_end"})
            return {"updated": False, "reason": "missing_ingest_window_end"}
        refresh_end = datetime.now(timezone.utc)
        self.state_manager.write_heartbeat(
            "x_refresh_site_start",
            {
                "window_start": refresh_start.isoformat(),
                "window_end": refresh_end.isoformat(),
            },
        )

        seen_ids = self.state_manager.load_seen_ids()
        zara_feeds = [
            feed
            for feed in load_yaml(self.settings.project_root / "config" / "zara_feed.yaml").get("feeds", [])
            if str(feed.get("name", "")).strip() == "zara_x"
        ]
        zara_items = self._safe_fetch_zara(
            ZaraFetcher,
            zara_feeds,
            seen_ids,
            recent_days=1,
            start_at=refresh_start,
            end_at=refresh_end,
            retry_attempts=self.settings.zara_x_refresh_retry_attempts,
            retry_delays_seconds=self.settings.zara_x_refresh_retry_delays_seconds,
            retry_window_seconds=self.settings.zara_x_refresh_retry_window_seconds,
        )
        self.state_manager.save_latest_source_statuses(
            {
                "zara_x": self._summarize_zara_source_status("zara_x"),
            }
        )
        zara_status = self._summarize_zara_source_status("zara_x")
        day = str(base_window.get("label_date", "")).strip() or "latest"
        if str(zara_status.get("status", "")).strip() in {"failed", "timed_out"}:
            self.state_manager.write_heartbeat(
                "x_refresh_site_error",
                {
                    "reason": "zara_fetch_failed",
                    "source_status": zara_status,
                    "window_start": refresh_start.isoformat(),
                    "window_end": refresh_end.isoformat(),
                    "report_day": day,
                },
            )
            return {
                "updated": False,
                "reason": "zara_fetch_failed",
                "report_day": day,
                "source_status": zara_status,
            }
        if not zara_items:
            self.state_manager.write_heartbeat(
                "x_refresh_site",
                {
                    "new_x_items": 0,
                    "status": str(zara_status.get("status", "empty")).strip() or "empty",
                    "window_start": refresh_start.isoformat(),
                    "window_end": refresh_end.isoformat(),
                    "report_day": day,
                    "site_updated": False,
                },
            )
            return {
                "updated": False,
                "new_x_items": 0,
                "report_day": day,
                "source_status": zara_status,
            }
        self.transcript_store.save_many(zara_items)
        seen_ids.update(item.content_id for item in zara_items)
        self.state_manager.save_seen_ids(seen_ids)
        self.state_manager.save_stage_content_ids("x_refresh", [item.content_id for item in zara_items])
        self.state_manager.save_latest_window(
            "x_refresh",
            self._build_window_payload(refresh_start, refresh_end),
        )

        target_date = date.fromisoformat(day) if day != "latest" else None
        report_items = self._load_items_for_site_x_refresh(target_date, base_window, zara_items)
        candidates, themes_data, selections_data, stats = self._build_daily_sections(report_items)
        run_id = self.state_manager.create_daily_run(day, source_window=base_window, status="refreshing")
        self.state_manager.save_daily_candidates(day, candidates, run_id)
        self.state_manager.save_daily_themes(day, themes_data, run_id)
        self.state_manager.save_daily_selections(day, selections_data, run_id)
        self.state_manager.finalize_daily_run(
            day,
            run_id,
            status="completed",
            candidates=candidates,
            themes=themes_data,
            selections=selections_data,
            source_window=base_window,
        )
        report_path = self._write_daily_report(themes_data, selections_data, stats, target_date, candidates)
        self._publish_site_report("daily", report_path, day)
        self.state_manager.write_heartbeat(
            "x_refresh_site",
            {
                "new_x_items": len(zara_items),
                "status": str(zara_status.get("status", "success")).strip() or "success",
                "window_start": refresh_start.isoformat(),
                "window_end": refresh_end.isoformat(),
                "report_day": day,
                "site_updated": True,
                "run_id": run_id,
            },
        )
        return {
            "updated": True,
            "new_x_items": len(zara_items),
            "report_day": day,
            "run_id": run_id,
            "source_status": zara_status,
        }

    def weekly(self, items: list[ContentItem] | None = None, deliver: bool = True) -> dict:
        weekly_end_date = self._resolve_weekly_end_date()
        weekly_items = self._load_items_for_weekly_report(weekly_end_date)
        weekly_items = self._ensure_weekly_tier2_scores(weekly_items)
        ebook_report_paths = self.report_writer.write(weekly_items)
        digest_data = self.weekly_builder.prepare_digest(weekly_items, target_end_date=weekly_end_date)
        payload = self.weekly_builder.build(weekly_items, target_end_date=weekly_end_date, digest_data=digest_data)
        report_path = self._write_weekly_report(
            weekly_items,
            target_end_date=weekly_end_date,
            digest_data=digest_data,
        )
        exported_ebook_reports = self._copy_weekly_ebook_reports(ebook_report_paths)
        if deliver:
            self.feishu.send(payload)
        target_label = report_path.stem if report_path else "latest"
        self._publish_site_report("weekly", report_path, target_label)
        self.state_manager.write_heartbeat(
            "weekly",
            {
                "items": len(weekly_items),
                "window_start": (weekly_end_date - timedelta(days=6)).isoformat(),
                "window_end": weekly_end_date.isoformat(),
                "exported_ebook_reports": len(exported_ebook_reports),
            },
        )
        return payload

    def _ensure_weekly_tier2_scores(self, items: list[ContentItem]) -> list[ContentItem]:
        youtube_items = [item for item in items if item.source_type == "youtube"]
        if not youtube_items:
            return items

        mentions = compute_x_mentions(items)
        items_by_id = {item.content_id: item for item in items}
        youtube_by_id = {item.content_id: item for item in youtube_items}

        coarse_candidates = [
            item for item in youtube_items if str(item.extra_metadata.get("score_stage", "")).strip() != "deep"
        ]
        coarse_inputs = [
            item for item in coarse_candidates if not item.ai_score or str(item.extra_metadata.get("score_stage", "")).strip() != "coarse"
        ]
        if coarse_inputs:
            scored_coarse = self.scorer.run_coarse(coarse_inputs, mentions)
            for item in scored_coarse:
                youtube_by_id[item.content_id] = item
                items_by_id[item.content_id] = item

        ranked = sorted(
            youtube_by_id.values(),
            key=lambda item: score_total(item.ai_score or {}),
            reverse=True,
        )
        finalists = ranked[: self.settings.tier2_candidate_count]
        finalists_to_deepen = [
            item for item in finalists if str(item.extra_metadata.get("score_stage", "")).strip() != "deep"
        ]
        if finalists_to_deepen:
            finalists_with_transcripts = self._fetch_transcripts_for_finalists(finalists_to_deepen)
            deep_scored = self.scorer.run_deep(finalists_with_transcripts, mentions)
            for item in deep_scored:
                youtube_by_id[item.content_id] = item
                items_by_id[item.content_id] = item

        refreshed_items = [items_by_id[item.content_id] for item in items]
        self.transcript_store.save_many(refreshed_items)
        return refreshed_items

    def publish_site(self, report_type: str = "all") -> dict[str, Any]:
        if self.site_publisher is None:
            return {"enabled": False, "reason": "site_publishing_disabled"}
        result = self.site_publisher.publish(report_type, target_label=report_type)
        self.state_manager.write_heartbeat(
            "site_publish",
            {
                "report_type": report_type,
                "daily_count": result.synced.daily_count,
                "weekly_count": result.synced.weekly_count,
                "changed": result.changed,
                "commit_message": result.commit_message or "",
            },
        )
        return {
            "enabled": True,
            "report_type": report_type,
            "daily_count": result.synced.daily_count,
            "weekly_count": result.synced.weekly_count,
            "changed": result.changed,
            "commit_message": result.commit_message,
        }

    def recover_site_publish(self) -> dict[str, Any]:
        if self.site_publisher is None:
            return {"enabled": False, "reason": "site_publishing_disabled"}
        try:
            result = self.site_publisher.recover_pending_push()
        except Exception as exc:
            self.state_manager.write_heartbeat(
                "site_publish_recovery_error",
                {
                    "error": str(exc),
                },
            )
            return {
                "enabled": True,
                "pushed": False,
                "error": str(exc),
            }

        self.state_manager.write_heartbeat("site_publish_recovery", {"pushed": result.pushed})
        return {
            "enabled": True,
            "pushed": result.pushed,
        }

    def _load_stage_items(self, stage: str) -> list[ContentItem]:
        content_ids = self.state_manager.load_stage_content_ids(stage)
        if not content_ids:
            return []
        return self.transcript_store.load_by_content_ids(content_ids)

    def _safe_fetch_youtube(
        self,
        fetcher_cls,
        channels: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        try:
            return fetcher_cls(
                self.settings.youtube_api_key,
                self.settings.request_timeout_seconds,
            ).fetch(channels, seen_ids, recent_days=recent_days, start_at=start_at, end_at=end_at)
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "youtube", "error": str(exc)})
            return []

    def _safe_fetch_youtube_playlists(
        self,
        fetcher_cls,
        playlists: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        try:
            return fetcher_cls(
                self.settings.youtube_api_key,
                self.settings.request_timeout_seconds,
            ).fetch_playlists(playlists, seen_ids, recent_days=recent_days, start_at=start_at, end_at=end_at)
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "youtube_playlists", "error": str(exc)})
            return []

    def _safe_fetch_rss(
        self,
        fetcher_cls,
        rss_sources: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        try:
            return fetcher_cls(self.settings.request_timeout_seconds).fetch(
                rss_sources,
                seen_ids,
                recent_days,
                start_at=start_at,
                end_at=end_at,
            )
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "rss", "error": str(exc)})
            return []

    def _safe_fetch_web(
        self,
        fetcher_cls,
        web_sources: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        try:
            return fetcher_cls(self.settings.request_timeout_seconds).fetch(
                web_sources,
                seen_ids,
                recent_days,
                start_at=start_at,
                end_at=end_at,
            )
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "web", "error": str(exc)})
            return []

    def _safe_fetch_newsletters(
        self,
        fetcher_cls,
        newsletter_sources: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        try:
            return fetcher_cls(
                self.settings.gmail_credentials_path,
                self.settings.gmail_token_path,
                self.settings.request_timeout_seconds,
            ).fetch(
                newsletter_sources,
                seen_ids,
                recent_days,
                start_at=start_at,
                end_at=end_at,
            )
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "newsletter_email", "error": str(exc)})
            return []

    def _safe_fetch_zara(
        self,
        fetcher_cls,
        zara_feeds: list[dict],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        retry_attempts: int | None = None,
        retry_delays_seconds: tuple[int, ...] | None = None,
        retry_window_seconds: int | None = None,
    ) -> list[ContentItem]:
        try:
            fetcher = fetcher_cls(
                zara_feeds,
                self.settings.request_timeout_seconds,
                retry_attempts=retry_attempts or self.settings.zara_retry_attempts,
                retry_delays_seconds=retry_delays_seconds or self.settings.zara_retry_delays_seconds,
                retry_window_seconds=(
                    self.settings.zara_retry_window_seconds
                    if retry_window_seconds is None
                    else retry_window_seconds
                ),
            )
            items = fetcher.fetch(seen_ids, recent_days, start_at=start_at, end_at=end_at)
            self._last_zara_fetch_reports = list(getattr(fetcher, "last_fetch_reports", []))
            for report in getattr(fetcher, "last_fetch_reports", []):
                if getattr(report, "status", "") not in {"failed", "timed_out"}:
                    continue
                self.state_manager.write_heartbeat(
                    "ingest_warning",
                    {
                        "source": report.feed_name,
                        "error": report.error,
                        "attempts": report.attempts,
                        "status": report.status,
                    },
                )
            return items
        except Exception as exc:
            self._last_zara_fetch_reports = []
            self.state_manager.write_heartbeat("ingest_warning", {"source": "zara", "error": str(exc)})
            return []

    def _summarize_zara_source_status(self, feed_name: str) -> dict[str, Any]:
        for report in self._last_zara_fetch_reports:
            if getattr(report, "feed_name", "") != feed_name:
                continue
            return {
                "status": getattr(report, "status", ""),
                "attempts": getattr(report, "attempts", 0),
                "items_fetched": getattr(report, "items_fetched", 0),
                "error": getattr(report, "error", ""),
            }
        return {
            "status": "unavailable",
            "attempts": 0,
            "items_fetched": 0,
            "error": "",
        }

    def _fetch_transcripts_for_finalists(self, finalists: list[ContentItem]) -> list[ContentItem]:
        for item in finalists:
            video_id = str(item.extra_metadata.get("video_id", ""))
            if not video_id:
                continue
            result = self.transcript_client.fetch(video_id, item.url)
            if result.text:
                item.body = result.text
                item.body_type = "transcript"
                item.extra_metadata["transcript_status"] = "fetched"
                item.extra_metadata["transcript_source"] = result.source
            else:
                item.extra_metadata["transcript_status"] = "failed"
                item.extra_metadata["transcript_error"] = result.error
                self.state_manager.append_transcript_failure(
                    {
                        "video_id": video_id,
                        "channel_name": item.source_name,
                        "title": item.title,
                        "timestamp": item.fetched_at.isoformat(),
                        "error": result.error or "Transcript unavailable",
                    }
                )
        return finalists

    def _write_daily_report(
        self,
        themes_data: dict,
        selections_data: dict,
        stats: dict[str, int],
        target_date,
        candidates_data: dict | None = None,
    ) -> Path:
        filename = target_date.isoformat() if target_date else "latest"
        path = self.daily_reports_root / f"{filename}.md"
        path.write_text(
            self.daily_builder.render_markdown(
                themes_data,
                selections_data,
                stats,
                target_date=target_date,
                candidates_data=candidates_data,
            ),
            encoding="utf-8",
        )
        return path

    def _write_weekly_report(
        self,
        items: list[ContentItem],
        target_end_date: date | None = None,
        digest_data: dict[str, Any] | None = None,
    ) -> Path:
        if target_end_date is None:
            target_end_date = self._resolve_weekly_end_date()
        week = target_end_date.isocalendar()
        filename = f"{week.year}-W{week.week:02d}"
        path = self.weekly_reports_root / f"{filename}.md"
        path.write_text(
            self.weekly_builder.render_markdown(
                items,
                target_end_date=target_end_date,
                digest_data=digest_data,
            ),
            encoding="utf-8",
        )
        return path

    def _copy_weekly_ebook_reports(self, report_paths: list[Path]) -> list[Path]:
        export_dir = getattr(self.settings, "weekly_ebook_export_dir", None)
        if export_dir is None:
            return []

        export_root = Path(export_dir)
        export_root.mkdir(parents=True, exist_ok=True)
        exported: list[Path] = []
        for report_path in report_paths:
            if not report_path.exists():
                continue
            target_path = export_root / report_path.name
            shutil.copy2(report_path, target_path)
            exported.append(target_path)
        return exported

    def _resolve_weekly_end_date(self) -> date:
        today = date.today()
        return today - timedelta(days=today.weekday() + 1)

    def _weekly_window_bounds(self, target_end_date: date) -> tuple[datetime, datetime]:
        window_start = datetime.combine(target_end_date - timedelta(days=6), datetime.min.time(), tzinfo=LOCAL_TIMEZONE)
        window_end = datetime.combine(target_end_date + timedelta(days=1), datetime.min.time(), tzinfo=LOCAL_TIMEZONE)
        return window_start, window_end

    def _load_items_for_weekly_report(self, target_end_date: date) -> list[ContentItem]:
        start_at, end_at = self._weekly_window_bounds(target_end_date)
        stored_items = self.transcript_store.load_by_published_range(start_at, end_at)
        return sorted(stored_items, key=lambda item: item.published_at)

    def _resolve_daily_target_date(
        self,
        items: list[ContentItem],
        report_window: dict[str, Any] | None = None,
    ) -> date | None:
        if report_window:
            label = str(report_window.get("label_date", "")).strip()
            if label:
                return date.fromisoformat(label)
        item_dates = sorted({item.published_at.date() for item in items}) or self.transcript_store.load_available_dates()
        if not item_dates:
            return None

        preferred = date.today() - timedelta(days=1)
        if preferred in item_dates:
            return preferred

        earlier_dates = [item_date for item_date in item_dates if item_date < preferred]
        if earlier_dates:
            return earlier_dates[-1]

        return item_dates[-1]

    def _load_items_for_report_window(
        self,
        report_window: dict[str, Any] | None,
        fallback_items: list[ContentItem],
    ) -> list[ContentItem]:
        if report_window:
            start_at = self._parse_window_timestamp(report_window.get("start_at"))
            end_at = self._parse_window_timestamp(report_window.get("end_at"))
            if start_at and end_at:
                stored_items = self.transcript_store.load_by_published_range(start_at, end_at)
                if stored_items:
                    return stored_items
                return [item for item in fallback_items if start_at <= item.published_at < end_at]
        target_date = self._resolve_daily_target_date(fallback_items)
        if not target_date:
            return []
        stored_items = self.transcript_store.load_by_date(target_date)
        if stored_items:
            return stored_items
        return [item for item in fallback_items if item.published_at.date() == target_date]

    def _load_items_for_daily_report(
        self,
        target_date: date | None,
        report_window: dict[str, Any] | None,
        fallback_items: list[ContentItem],
    ) -> list[ContentItem]:
        items = self._load_items_for_report_window(report_window, fallback_items)
        if not target_date:
            return items

        zara_items = self.transcript_store.load_by_date(target_date)
        zara_by_id = {
            item.content_id: item
            for item in zara_items
            if item.source_type == "zara_x"
        }
        merged_by_id = {item.content_id: item for item in items if item.source_type != "zara_x"}
        merged_by_id.update(zara_by_id)
        return sorted(merged_by_id.values(), key=lambda item: item.published_at)

    def _resolve_ingest_window_start(
        self,
        previous_window: dict[str, Any],
        recent_days: int,
        recent_days_override: int | None,
        ignore_seen: bool,
        seen_ids: set[str],
        window_end: datetime,
    ) -> datetime:
        if not ignore_seen and recent_days_override is None:
            previous_end = self._parse_window_timestamp(previous_window.get("end_at"))
            if previous_end:
                return previous_end
        if not seen_ids:
            return window_end - timedelta(days=self.settings.bootstrap_days)
        return window_end - timedelta(days=recent_days)

    def _build_window_payload(self, start_at: datetime, end_at: datetime) -> dict[str, str]:
        return {
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "label_date": start_at.astimezone(LOCAL_TIMEZONE).date().isoformat(),
        }

    def _parse_window_timestamp(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        return datetime.fromisoformat(text)

    def _build_daily_sections(
        self,
        daily_items: list[ContentItem],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, int]]:
        candidates = self.daily_candidate_builder.build(daily_items)
        candidates = normalize_daily_candidates_payload(candidates)
        builder_hot_candidates = candidates.get("builder_hot_candidates", [])
        editorial_candidate_ids = {
            str(candidate.get("content_id", "")).strip()
            for candidate in candidates.get("editorial_top10", [])
            if str(candidate.get("content_id", "")).strip()
        }
        editorial_items = [item for item in daily_items if item.content_id in editorial_candidate_ids]
        themes_data = self.theme_aggregator.aggregate_themes(daily_items, builder_hot_candidates)
        latest_source_statuses = self.state_manager.load_latest_source_statuses()
        zara_x_status = latest_source_statuses.get("zara_x", {})
        if (
            not themes_data.get("themes")
            and not themes_data.get("spotlight_posts")
            and str(zara_x_status.get("status", "")).strip() in {"failed", "timed_out"}
        ):
            themes_data["degraded_reason"] = "builder_source_fetch_failed"
            themes_data["degraded_stage"] = "builder_decision"
            themes_data["fallback_mode"] = "empty_themes"
            themes_data["degraded_source"] = "zara_x"
        exclude_ids: set[str] = set()
        for theme in themes_data.get("themes", []):
            exclude_ids.update(theme_decision(theme).get("member_content_ids", []))
        selections_data = self.daily_curator.curate_daily(editorial_items, exclude_ids)
        resolver = getattr(self, "daily_decision_resolver", DailyDecisionResolver())
        candidates, themes_data, selections_data = resolver.resolve(
            candidates,
            themes_data,
            selections_data,
        )
        stats = {"total": len(daily_items)}
        return candidates, themes_data, selections_data, stats

    def _load_items_for_site_x_refresh(
        self,
        target_date: date | None,
        base_window: dict[str, Any],
        fresh_x_items: list[ContentItem],
    ) -> list[ContentItem]:
        base_items = self._load_items_for_daily_report(target_date, base_window, [])
        merged_by_id = {item.content_id: item for item in base_items}
        for item in fresh_x_items:
            merged_by_id[item.content_id] = item
        return sorted(merged_by_id.values(), key=lambda item: item.published_at)

    def _publish_site_report(self, report_type: str, report_path: Path | None, target_label: str) -> None:
        if self.site_publisher is None:
            return
        try:
            result = self.site_publisher.publish(report_type, target_label=target_label)
            self.state_manager.write_heartbeat(
                "site_publish",
                {
                    "report_type": report_type,
                    "target": target_label,
                    "changed": result.changed,
                    "commit_message": result.commit_message or "",
                    "daily_count": result.synced.daily_count,
                    "weekly_count": result.synced.weekly_count,
                    "report_path": str(report_path) if report_path else "",
                },
            )
        except Exception as exc:
            self.state_manager.write_heartbeat(
                "site_publish_error",
                {
                    "report_type": report_type,
                    "target": target_label,
                    "report_path": str(report_path) if report_path else "",
                    "error": str(exc),
                },
            )


def compute_x_mentions(items: list[ContentItem]) -> dict[str, int]:
    zara_text = "\n".join(item.body for item in items if item.source_type.startswith("zara_") and item.body).lower()
    counts: dict[str, int] = {}
    for item in items:
        if item.source_type != "youtube":
            continue
        url = item.url.lower()
        video_id = str(item.extra_metadata.get("video_id", "")).lower()
        url_mentions = zara_text.count(url)
        text_without_urls = zara_text.replace(url, " ")
        standalone_id_mentions = len(re.findall(rf"\b{re.escape(video_id)}\b", text_without_urls)) if video_id else 0
        counts[item.content_id] = url_mentions + standalone_id_mentions
    return counts


def select_top_candidates(items: list[ContentItem], candidate_count: int) -> list[ContentItem]:
    ranked = sorted(
        [item for item in items if item.source_type == "youtube" and item.ai_score],
        key=lambda item: score_total(item.ai_score or {}),
        reverse=True,
    )
    return ranked[:candidate_count]
