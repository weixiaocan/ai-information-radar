# AGENTS.md

## Source of Truth

- `prd.md` defines product scope and acceptance criteria.
- `AGENTS.md` defines V1 hard constraints and overrides `prd.md` when they conflict.
- `README.md` must keep the Zara source attribution and the note that the Builder feed uses `zarazhangrui/follow-builders` as one upstream input.

## V1 Hard Constraints

- V1 runs on a Windows local machine.
- LLM provider is DeepSeek API.
- Scheduling is done by Windows Task Scheduler.
- Delivery is via Feishu webhook.
- State is stored locally in files, not in a database.
- Secrets must come from `.env`.
- Prompts stay in files, not inline.
- Use explicit timeouts for every external API call.
- Consult `state/seen_ids.json` for incremental fetching.
- Write heartbeat metadata on successful task runs.
- Append transcript fetch failures to `state/transcript_failures.jsonl`.
- First bootstrap ingest fetches only the last 7 days of content.
- Normal daily ingest fetches only the last 1 day of content.
- Do not backfill outside the configured bootstrap window unless explicitly requested.
- Do not default to generated transcripts.

## Content Policy

- Supported sources in V1 are YouTube channels, RSS feeds, and Zara feed.
- Normalize all sources into a shared `ContentItem`.
- Daily and weekly digests must be generated from normalized source content, not by rewriting previous digests.
- `今日热议` is builder/X only.
- `今日精选` is chosen only from editorial candidates.
- `补充候选` must only contain candidates that entered the pool but did not enter `今日热议` or `今日精选`.
- Weekly Top 2 recommendations must come only from YouTube items that completed Tier 2 scoring.

## Non-Goals

- No database.
- No frontend UI.
- No cloud deployment.
- No multi-provider LLM abstraction beyond a single provider-ready client surface.
- No Feishu feedback loop in V1.
- No weekly report built by concatenating daily reports.
