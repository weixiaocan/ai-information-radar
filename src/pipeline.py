from __future__ import annotations

import re
from pathlib import Path

from src.models.content_item import ContentItem
from src.output.daily_digest import DailyDigestBuilder
from src.output.feishu_delivery import FeishuDelivery
from src.output.top_video_report import TopVideoReportWriter
from src.output.weekly_digest import WeeklyDigestBuilder
from src.processing.daily_candidate_builder import DailyCandidateBuilder
from src.processing.daily_curator import DailyCurator
from src.processing.theme_aggregator import ThemeAggregator
from src.processing.tier1_summary import Tier1Summarizer
from src.processing.tier2_score import Tier2Scorer, score_total
from src.storage.state_manager import StateManager
from src.storage.transcript_store import TranscriptStore
from src.utils.config import Settings, load_yaml
from src.utils.llm_client import DeepSeekClient
from src.utils.transcript_client import TranscriptClient


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
            settings.project_root / "prompts" / "theme_signal_extractor.md",
        )
        self.theme_aggregator = ThemeAggregator(
            self.client,
            settings.project_root / "prompts" / "theme_aggregator.md",
        )
        self.daily_curator = DailyCurator(self.client, settings.project_root / "prompts" / "daily_curator.md")
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

    def ingest(self, recent_days_override: int | None = None, ignore_seen: bool = False) -> list[ContentItem]:
        from src.ingestion.rss_fetcher import RSSFetcher
        from src.ingestion.youtube_fetcher import YouTubeFetcher
        from src.ingestion.zara_fetcher import ZaraFetcher

        seen_ids = self.state_manager.load_seen_ids()
        effective_seen_ids = set() if ignore_seen else seen_ids
        recent_days = (
            recent_days_override
            if recent_days_override is not None
            else (self.settings.bootstrap_days if not seen_ids else self.settings.incremental_days)
        )
        channels = load_yaml(self.settings.project_root / "config" / "channels.yaml").get("channels", [])
        rss_sources = load_yaml(self.settings.project_root / "config" / "rss_sources.yaml").get("sources", [])
        zara_feeds = load_yaml(self.settings.project_root / "config" / "zara_feed.yaml").get("feeds", [])

        youtube_items = self._safe_fetch_youtube(YouTubeFetcher, channels, effective_seen_ids, recent_days)
        rss_items = self._safe_fetch_rss(RSSFetcher, rss_sources, effective_seen_ids, recent_days)
        zara_items = self._safe_fetch_zara(ZaraFetcher, zara_feeds, effective_seen_ids, recent_days)
        items = youtube_items + rss_items + zara_items
        self.transcript_store.save_many(items)
        seen_ids.update(item.content_id for item in items)
        self.state_manager.save_seen_ids(seen_ids)
        self.state_manager.save_stage_content_ids("ingest", [item.content_id for item in items])
        self.state_manager.write_heartbeat(
            "ingest",
            {"new_items": len(items), "recent_days": recent_days, "ignore_seen": ignore_seen},
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

    def daily(self, items: list[ContentItem] | None = None, deliver: bool = True) -> dict:
        items = items or self._load_stage_items("tier1")
        target_date = max((item.published_at.date() for item in items), default=None)
        day = target_date.isoformat() if target_date else "latest"
        candidates_data = self.state_manager.load_daily_candidates(day) if target_date else {"builder_hot_candidates": [], "editorial_candidates": []}
        themes_data = self.state_manager.load_daily_themes(day) if target_date else {"themes": [], "discussion_dispersion": "dispersed"}
        selections_data = self.state_manager.load_daily_selections(day) if target_date else {"selections": []}
        stats = {"total": len(items)}
        payload = self.daily_builder.build(themes_data, selections_data, stats, target_date=target_date, candidates_data=candidates_data)
        self._write_daily_report(themes_data, selections_data, stats, target_date, candidates_data)
        if deliver:
            self.feishu.send(payload)
        self.state_manager.write_heartbeat(
            "daily",
            {"items": len(items), "themes": len(themes_data.get("themes", [])), "selections": len(selections_data.get("selections", []))},
        )
        return payload

    def daily_curate(self, items: list[ContentItem] | None = None) -> dict[str, dict]:
        items = items or self._load_stage_items("tier1")
        target_date = max((item.published_at.date() for item in items), default=None)
        day = target_date.isoformat() if target_date else "latest"
        candidates = self.daily_candidate_builder.build(items)
        builder_hot_candidates = candidates.get("builder_hot_candidates", [])
        editorial_candidate_ids = {
            str(candidate.get("content_id", "")).strip()
            for candidate in candidates.get("editorial_candidates", [])
            if str(candidate.get("content_id", "")).strip()
        }
        editorial_items = [item for item in items if item.content_id in editorial_candidate_ids]
        themes_data = self.theme_aggregator.aggregate_themes(items, builder_hot_candidates)
        exclude_ids: set[str] = set()
        for theme in themes_data.get("themes", []):
            exclude_ids.update(theme.get("related_content_ids", []))
        selections_data = self.daily_curator.curate_daily(editorial_items, exclude_ids)
        self.state_manager.save_daily_candidates(day, candidates)
        self.state_manager.save_daily_themes(day, themes_data)
        self.state_manager.save_daily_selections(day, selections_data)
        self.state_manager.write_heartbeat(
            "daily_curate",
            {
                "items": len(items),
                "builder_hot_candidates": len(builder_hot_candidates),
                "editorial_candidates": len(editorial_items),
                "themes": len(themes_data.get("themes", [])),
                "selections": len(selections_data.get("selections", [])),
            },
        )
        return {"candidates": candidates, "themes": themes_data, "selections": selections_data}

    def weekly(self, items: list[ContentItem] | None = None, deliver: bool = True) -> dict:
        items = items or self._load_stage_items("tier2")
        self.report_writer.write(items)
        payload = self.weekly_builder.build(items)
        self._write_weekly_report(items)
        if deliver:
            self.feishu.send(payload)
        self.state_manager.write_heartbeat("weekly", {"items": len(items)})
        return payload

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
    ) -> list[ContentItem]:
        try:
            return fetcher_cls(
                self.settings.youtube_api_key,
                self.settings.request_timeout_seconds,
            ).fetch(channels, seen_ids, recent_days=recent_days)
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "youtube", "error": str(exc)})
            return []

    def _safe_fetch_rss(self, fetcher_cls, rss_sources: list[dict], seen_ids: set[str], recent_days: int) -> list[ContentItem]:
        try:
            return fetcher_cls(self.settings.request_timeout_seconds).fetch(rss_sources, seen_ids, recent_days)
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "rss", "error": str(exc)})
            return []

    def _safe_fetch_zara(self, fetcher_cls, zara_feeds: list[dict], seen_ids: set[str], recent_days: int) -> list[ContentItem]:
        try:
            return fetcher_cls(zara_feeds, self.settings.request_timeout_seconds).fetch(seen_ids, recent_days)
        except Exception as exc:
            self.state_manager.write_heartbeat("ingest_warning", {"source": "zara", "error": str(exc)})
            return []

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

    def _write_weekly_report(self, items: list[ContentItem]) -> Path:
        if items:
            week = max(items, key=lambda item: item.published_at).published_at.isocalendar()
            filename = f"{week.year}-W{week.week:02d}"
        else:
            filename = "latest"
        path = self.weekly_reports_root / f"{filename}.md"
        path.write_text(self.weekly_builder.render_markdown(items), encoding="utf-8")
        return path


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
