# AGENTS.md

## Project Intent

AI Radar is a personal AI information radar for deciding what is worth reading or watching, not for rewriting every source into a substitute artifact. V1 should automate a complete daily and weekly loop locally.

## Source of Truth

- Product scope, source list, and acceptance criteria live in `prd.md`.
- V1 implementation defaults and engineering constraints live in this file.
- If `prd.md` and implementation details conflict during V1 delivery, follow `AGENTS.md`.
- `README.md` must explicitly preserve the `zara` source attribution and note that the Builder feed uses the `zarazhangrui/follow-builders` center feed as one upstream input.

## V1 Locked Decisions

- LLM provider: `DeepSeek API`
- Runtime: `Windows local machine`
- Scheduler: `Windows Task Scheduler`
- Delivery: `Feishu webhook`
- Storage: local filesystem plus JSON/JSONL state files

## Architecture Constraints

- Supported sources in V1: YouTube channels, RSS feeds, Zara feed
- All sources must normalize into a shared `ContentItem`
- Tier 1 runs on all new content and only produces a one-line summary plus keywords
- Tier 2 runs only on YouTube content and only produces scores, reasons, and recommendation copy
- The system should recommend original content, not rewrite long-form videos into substitute articles
- `transcripts/` is the normalized content store, not a reports directory
- `transcripts/` may contain YouTube transcripts, RSS article bodies, and Zara feed text
- Daily and weekly digests should be generated from normalized source content, not by rewriting previous digests
- `transcripts/` should be organized by day and then by source type:
  - `transcripts/YYYY-MM-DD/youtube/`
  - `transcripts/YYYY-MM-DD/rss/`
  - `transcripts/YYYY-MM-DD/zara_x/`

## Repo Layout Expectations

- Source code lives under `src/`
- Static config lives under `config/`
- Prompt templates live under `prompts/`
- Runtime outputs live under `state/` and `transcripts/`
- Tests live under `tests/`
- Final human-readable outputs live under `reports/`
- `reports/daily/` stores final daily markdown archives
- `reports/weekly/` stores final weekly markdown archives
- `reports/ebook/YYYY-Www/` stores the Top 2 long-form ebook outputs for that week
- `state/themes/` stores normalized daily hot-topic outputs
- `state/selections/` stores normalized daily featured selections
- `state/candidates/` stores the explicit daily candidate pools used before final selection

## Daily Digest Rules

- Daily processing should be split into distinct stages:
  - ingest all new source content
  - enrich all content with Tier 1 summaries
  - build explicit candidate pools
  - select final daily hot items and featured items
  - render and deliver the digest
- Daily candidate building must be explicit rather than implicit.
- The daily candidate pools are:
  - `builder_hot_candidates`: builder/X items eligible for `今日热议`
  - `editorial_candidates`: YouTube, RSS, and article items eligible for `今日精选`
- Candidate building and final selection should be treated as separate decisions.
- Rewriting copy should not implicitly reshuffle the selected list unless the candidate-selection step is rerun.

### 今日热议

- `今日热议` should be driven only by builder/X content.
- Builder/X raw content should be converted into structured signals before theme aggregation.
- Weak signals should be filtered before theme aggregation, including examples such as:
  - pure link sharing
  - very short reactions
  - generic praise without concrete information
  - low-information quips
- If builder discussion forms real concentrated themes, output `0-3` themes.
- A real theme requires:
  - at least `3` different builders or information sources
  - internal logical cohesion between evidence items
  - no cross-theme reuse of the same original post
- If there are not enough strong signals to form themes, `今日热议` must degrade to spotlight posts instead of forcing themes.
- Spotlight posts should directly show `2-4` worthwhile builder posts.

### 今日精选

- `今日精选` should be selected only from `editorial_candidates`.
- `今日精选` should remain selective and capped at `5` items.
- Selection should prioritize:
  - relevance to AI Agent, harness engineering, coding agents, and agentic engineering
  - information density
  - source trust
  - diversity across angles and products
- `value_pitch` copy should be generated only for already selected items.
- `value_pitch` should read like natural Chinese, not bullet fragments, RSS labels, or translationese.

### 补充候选

- Daily digests may include a lightweight `补充候选` section.
- `补充候选` is not a second recommendation layer; it is a weak-exposure recap of worthwhile candidates that did not make `今日热议` or `今日精选`.
- `补充候选` should only contain items that:
  - entered the candidate pool
  - did not enter `今日热议`
  - did not enter `今日精选`
- `补充候选` should stay lightweight:
  - at most `4-6` items
  - at most `1` item per source
  - single-line rendering preferred

### Daily Layout

- The daily digest should use these sections:
  - `今日热议`
  - `今日精选`
  - optional `补充候选`
  - `今日数据`
- The daily product behavior is: around `08:00`, deliver the previous day's content.

## Weekly Digest Rules

- Weekly processing should work directly on the week's normalized content set, not by merging daily digests.
- The weekly digest should contain two layers:
  - `本周重要主题`
  - `本周最值得亲自看的内容`
- Weekly Top 2 recommendations in Feishu are the decision layer; the long-form ebook is the deep-reading layer.
- Weekly themes should be generated from the week's normalized content set.
- Weekly Top 2 recommendations should be chosen only from YouTube items that have completed Tier 2 scoring.
- Weekly ranking should use a two-stage strategy:
  - light scoring on all weekly YouTube candidates
  - transcript fetching and deeper scoring only for Top K finalists
- Do not add an extra brief report layer for Top 2 unless explicitly requested.
- Top 2 ebook outputs should be chapterized reading artifacts for deep reading and English learning, not short summary notes.
- The ebook structure should avoid redundant sections like a second-pass `我的中文理解` that merely repeats the chapter summary.

## Implementation Rules

- Secrets must come from `.env`
- Every external API call must use explicit timeouts
- Incremental fetching must consult `state/seen_ids.json`
- Every task should write heartbeat metadata on success
- Transcript fetch failures must be appended to `state/transcript_failures.jsonl`
- Prompts should stay in files, not be hard-coded inline unless templating is trivial
- First bootstrap ingest should only fetch the last `7` days of content
- Normal daily ingest should only fetch the last `1` day of content
- Avoid backfilling old content outside the configured bootstrap window unless explicitly requested
- Do not fetch transcripts for every long YouTube video by default
- Preferred transcript strategy is:
  - first try `youtube-transcript-api`
  - then fallback to `Supadata` native transcript
  - do not default to generated transcripts because of cost

## Non-Goals

- No database
- No frontend UI
- No cloud deployment
- No multi-provider LLM abstraction beyond a single provider-ready client surface
- No Feishu feedback loop in V1
- No transcript generation for every candidate video
- No weekly report built by concatenating daily reports

## Acceptance Alignment

V1 is complete when the pipeline can ingest supported sources, persist normalized content, generate Tier 1 and Tier 2 outputs, and send daily and weekly Feishu cards using local scheduling.
