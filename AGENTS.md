# AGENTS.md

## Source of Truth

- `docs/PRODUCT_SPEC.md` defines public product scope and acceptance criteria.
- `AGENTS.md` defines V1 hard constraints and overrides `docs/PRODUCT_SPEC.md` when they conflict.
- `README.md` must keep the Zara source attribution and the note that the Builder feed uses `zarazhangrui/follow-builders` as one upstream input.

## V1 Hard Constraints

- Production runs in an always-available hosted execution environment and must not depend on a personal computer remaining powered on.
- Windows local execution is optional for development, manual recovery, and migration verification only.
- LLM provider is DeepSeek API.
- Production scheduling must be managed by the hosted execution environment and continue while the maintainer's personal computer is offline.
- Delivery is via Feishu webhook.
- State remains file-based rather than database-backed, but production state must use durable persistence that survives runner or process replacement.
- Secrets must come from `.env` for local development or from the hosted platform's secret store in production; secrets must never be committed.
- Prompts stay in files, not inline.
- Use explicit timeouts for every external API call.
- Consult `state/seen_ids.json` for incremental fetching.
- Write heartbeat metadata on successful task runs.
- Append transcript fetch failures to `state/transcript_failures.jsonl`.
- First bootstrap ingest fetches only the last 7 days of content.
- Normal daily ingest fetches only the last 1 day of content.
- Do not backfill outside the configured bootstrap window unless explicitly requested.
- Do not default to generated transcripts.
- Daily and weekly digests must be rebuilt from stored normalized content for the target date or week, not from only the latest ingest batch.
- Source labels shown in daily and weekly reports must prefer the original source or author label, not upstream transport names such as `zara_x`, `zara_blog`, or `zara_podcast`.

## Content Policy

- Supported primary content sources in V1 are YouTube channels, YouTube playlists, RSS feeds, and web scrape sources.
- Zara is not a primary article or podcast source in V1.
- Zara is retained only as an upstream Builder/X signal source via `zara_x`.
- `zara_x` is an upstream daily batch feed from `zarazhangrui/follow-builders` that is typically generated around 15:00-16:00 Asia/Shanghai and already covers the upstream recent 24-hour window; do not apply a second local `published_at` window filter to `zara_x`, and use only `seen_ids` incremental dedupe for this source.
- Normalize all sources into a shared `ContentItem`.
- Daily and weekly digests must be generated from normalized source content, not by rewriting previous digests.
- `今日热议` is builder/X only.
- `今日精选` is chosen only from editorial candidates.
- `补充候选` must only contain candidates that entered the pool but did not enter `今日热议` or `今日精选`.
- Daily curation must be based on the full normalized content set for the target day.
- Weekly themes may summarize any normalized weekly content, including Zara X signals, RSS, web, and YouTube.
- Weekly Top 2 recommendations must come only from YouTube items that completed Tier 2 scoring.

## Operations Health

- Every ingest run must append a per-source health snapshot to `state/source_health.jsonl`; do not rely only on `state/latest_source_status.json`.
- Source health must distinguish successful fetches, successful runs with no new items, degraded fallbacks, failures, feed failures, and timeouts.
- `no_new_items` is a healthy run and must not be reported as a source failure.
- The scheduled Monday weekly task must send a separate Feishu system health card after the content weekly digest.
- The system health card is Feishu-only. Do not write it into weekly content reports or publish it to the public site.
- Weekly task completion counts must use distinct Asia/Shanghai calendar days; repeated or manual runs on the same day count only once.
- Do not report the system as healthy unless both task history and per-source health history cover the full reporting week.
- The weekly health card must use clear Chinese descriptions, list missing task days, and show each degraded or failed source with occurrence count and latest error.
- A health-card delivery failure must be recorded in heartbeat and `state/ops_events.jsonl` without blocking the content weekly report or site publication.



## Workflow

- At the end of each task, if the project has been modified, automatically create a git commit unless the user explicitly says not to commit.
- Use a clear non-interactive commit message that summarizes the completed change.
