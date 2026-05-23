# Daily Pipeline Hardening Plan

## Purpose

This document turns the recent ad hoc daily-digest fixes into a staged refactor plan.

The goal is not to remove LLM judgment from the system. The goal is to make the
`daily-curate -> daily` path structurally stable by separating:

- fact state
- decision state
- presentation copy
- final rendering

This plan is intended to be executed across multiple conversations. Each phase is
designed to be independently shippable.

## Current Problem Statement

The unstable part of the system is not ingestion or normalization. It is the daily
decision pipeline after `ContentItem` loading.

Today the pipeline effectively looks like:

`ContentItem -> builder_hot_candidates -> themes -> selections -> daily_digest`

The main weakness is that decision outputs and final user-facing copy are stored and
consumed together in the same state objects. When copy quality degrades, the whole
state object appears unreliable, which causes repeated patching in later stages.

## Current Layering

### Stable Fact Layer

Mostly deterministic, code-driven:

- source fetchers
- normalization into `ContentItem`
- transcript and state storage
- date window resolution
- final markdown/card writing

Primary files:

- [src/pipeline.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\pipeline.py:77)
- [src/storage/state_manager.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\storage\state_manager.py:10)

### LLM-Driven Daily Decision Layer

LLM participates in:

- builder hot candidate extraction
- theme grouping and summarization
- daily selection and value-pitch writing

Primary files:

- [src/processing/daily_candidate_builder.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_candidate_builder.py:20)
- [src/processing/theme_aggregator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\theme_aggregator.py:17)
- [src/processing/daily_curator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_curator.py:13)
- [src/utils/llm_client.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\utils\llm_client.py:151)

### Render Layer

`daily_digest` should ideally render trusted state only, but today it still performs
business repair logic such as cross-section dedup and summary/evidence safeguards.

Primary file:

- [src/output/daily_digest.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\output\daily_digest.py:12)

## Current Mixed Objects

### `builder_hot_candidates`

Current object mixes:

- decision state:
  - whether a builder/X item enters the hot candidate pool
  - source/url/content identity
- presentation copy:
  - `topic_label`
  - `core_claim`
  - `excerpt`
  - `spotlight_text`

### `themes`

Current object mixes:

- decision state:
  - whether themes exist
  - theme membership
  - `related_content_ids`
  - `discussion_dispersion`
- presentation copy:
  - `theme`
  - `summary`
  - `evidence[].excerpt`

### `selections`

Current object mixes:

- decision state:
  - which items are selected
- presentation copy:
  - `value_pitch`

## Refactor Principles

1. Keep LLM for semantic judgment and copy generation.
2. Move dedup, exclusivity, and fallback policy out of the render layer.
3. Separate decision state from presentation copy.
4. Make each stage output a harder contract.
5. Preserve the current product behavior while shrinking hidden coupling.

## Phase 1: Separate Decision State and Copy State

### Goal

Keep the current pipeline shape, but make state boundaries explicit.

### Changes

Restructure daily state payloads so each object distinguishes:

- `decision`
- `copy`

Suggested target shapes:

#### Builder hot candidates

```json
{
  "decision": {
    "content_id": "...",
    "url": "...",
    "source": "...",
    "topic_key": "...",
    "entered_hot_pool": true
  },
  "copy": {
    "topic_label": "...",
    "core_claim": "...",
    "excerpt": "...",
    "spotlight_text": "..."
  }
}
```

#### Themes

```json
{
  "decision": {
    "theme_id": "...",
    "member_content_ids": ["..."],
    "representative_urls": ["..."],
    "discussion_dispersion": "clustered"
  },
  "copy": {
    "theme_title": "...",
    "theme_summary": "...",
    "evidence": [
      {"source": "...", "excerpt": "...", "url": "..."}
    ]
  }
}
```

#### Selections

```json
{
  "decision": {
    "content_id": "...",
    "selected": true
  },
  "copy": {
    "value_pitch": "..."
  }
}
```

### Files Expected To Change

- [src/processing/daily_candidate_builder.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_candidate_builder.py:20)
- [src/processing/theme_aggregator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\theme_aggregator.py:17)
- [src/processing/daily_curator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_curator.py:13)
- [src/storage/state_manager.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\storage\state_manager.py:89)
- [src/pipeline.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\pipeline.py:200)
- [src/output/daily_digest.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\output\daily_digest.py:12)

### Tests To Add Or Update

- payload schema tests for candidates/themes/selections
- backward-compatibility tests for loading stored state
- digest rendering tests against the new payload structure

### Exit Criteria

- daily state clearly separates decision data from copy data
- render code no longer needs to infer which fields are decision-critical
- a bad copy field can be identified as a copy defect instead of a state defect

## Phase 2: Centralize Dedup and Section Exclusivity

### Goal

Make `daily_digest` consume an already-resolved section layout instead of repairing it.

### Changes

Move core dedup rules to decision-time processing:

- URL dedup
- content-id dedup
- same-family/package dedup
- per-source caps
- editorial pool near-duplicate filtering

Add a single resolver for cross-section exclusivity:

- theme members cannot also appear in supplementary
- selected items cannot also appear in supplementary
- builder items already consumed by a theme cannot reappear elsewhere

Suggested new module:

- `src/processing/daily_decision_resolver.py`

This resolver should output explicit section-ready membership:

- hot-theme members
- spotlight-only builder items
- selected editorial items
- supplementary items

### Files Expected To Change

- [src/processing/daily_candidate_builder.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_candidate_builder.py:20)
- new `src/processing/daily_decision_resolver.py`
- [src/pipeline.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\pipeline.py:234)
- [src/output/daily_digest.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\output\daily_digest.py:205)

### Tests To Add Or Update

- same-family dedup tests
- cross-section exclusivity tests
- supplementary candidate eligibility tests
- invariant-warning tests

### Exit Criteria

- render layer no longer performs primary business dedup
- section conflicts are resolved before rendering
- render layer retains only final invariant checks and warnings

## Phase 3: Split Semantic Decision From Copy Generation

### Goal

Keep LLM judgment, but stop coupling decision success to copy quality.

### Changes

Break each LLM-assisted stage into two logical steps.

### 3A. Builder Hot

Step 1:

- decide which builder posts enter the hot pool
- optionally assign a topic key or clustering hint

Step 2:

- generate display copy only for the accepted pool

### 3B. Themes

Step 1:

- decide whether themes exist
- decide membership per theme

Step 2:

- generate `theme_title`
- generate `theme_summary`
- generate evidence excerpts for already-fixed membership

### 3C. Selections

Step 1:

- choose selected candidates

Step 2:

- generate `value_pitch` for selected items only

### Files Expected To Change

- [src/utils/llm_client.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\utils\llm_client.py:151)
- [src/processing/daily_candidate_builder.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_candidate_builder.py:20)
- [src/processing/theme_aggregator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\theme_aggregator.py:17)
- [src/processing/daily_curator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_curator.py:13)

### Tests To Add Or Update

- decision-step success with copy-step retry
- copy-step failure fallback tests
- membership preserved when summary generation fails
- selection preserved when value-pitch generation fails

### Exit Criteria

- a copy failure does not invalidate a correct decision result
- retries can target copy-only defects without regenerating whole decisions
- theme membership and selection membership become independently inspectable

## Phase 4: Standardize Fallback Policy

### Goal

Stop adding fallback behavior case by case.

### Changes

Write explicit fallback rules for each daily stage:

- builder signal decision failure
- builder copy failure
- theme membership failure
- theme copy failure
- selection decision failure
- selection copy failure

Example policy direction:

- decision failures change section structure
- copy failures preserve section structure and downgrade wording only

Fallback behavior should be documented in code and represented in output state.

Suggested additions:

- `degraded_reason`
- `degraded_stage`
- `fallback_mode`

### Files Expected To Change

- [src/processing/daily_candidate_builder.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_candidate_builder.py:32)
- [src/processing/theme_aggregator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\theme_aggregator.py:17)
- [src/processing/daily_curator.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\processing\daily_curator.py:13)
- [src/pipeline.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\pipeline.py:200)

### Tests To Add Or Update

- explicit fallback-path tests for each degraded stage
- state payload tests asserting structured degraded metadata

### Exit Criteria

- every degraded daily output can be mapped to a known fallback path
- fallback behavior is deterministic and documented
- render layer does not guess what failed upstream

## Phase 5: Version Daily State By Run

### Goal

Eliminate state overwrites and timing ambiguity between `daily-curate` and `daily`.

### Changes

Replace day-only state files with run-versioned state:

```text
state/
  runs/
    daily/
      2026-05-22/
        <run_id>/
          candidates.json
          themes.json
          selections.json
          manifest.json
```

The manifest should include:

- run id
- target day
- source window metadata
- timestamps
- status
- degraded metadata

`daily` should consume an explicit run artifact, not simply whatever currently exists
under `state/themes/<day>.json`.

### Files Expected To Change

- [src/storage/state_manager.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\storage\state_manager.py:10)
- [src/pipeline.py](D:\huangxh\AI_Projects_100\p22_AI_Radar\src\pipeline.py:200)
- any scripts that invoke `daily-curate` and `daily`

### Tests To Add Or Update

- run-version read/write tests
- latest-pointer tests
- rerun isolation tests
- daily consumption tests for explicit run ids

### Exit Criteria

- repeated runs for the same day do not overwrite historical decision state
- `daily` reads a declared run artifact
- debugging a bad report can be tied to one exact curate run

## Recommended Execution Order

1. Phase 1: separate decision and copy state
2. Phase 2: centralize dedup and exclusivity
3. Phase 3: split decision from copy generation
4. Phase 4: standardize fallback policy
5. Phase 5: version daily state by run

This order is intentional:

- Phase 1 gives clearer objects to work with
- Phase 2 stops most of the ongoing patch churn
- Phase 3 reduces semantic/copy coupling
- Phase 4 makes failure behavior predictable
- Phase 5 hardens reruns and debugging

## Suggested Conversation Breakdown

### Conversation 1

Phase 1 only.

Focus:

- payload redesign
- state-manager compatibility
- render compatibility

### Conversation 2

Phase 2 only.

Focus:

- dedup ownership
- section exclusivity resolver
- digest simplification

### Conversation 3

Phase 3 only.

Focus:

- split LLM calls by responsibility
- preserve decisions when copy retries fail

### Conversation 4

Phase 4 only.

Focus:

- codify fallback states
- ensure degraded outputs are explicit and deterministic

### Conversation 5

Phase 5 only.

Focus:

- run ids
- state versioning
- rerun safety

## Non-Goals

This plan does not aim to:

- remove LLM from hot/theme/selection judgment
- replace semantic grouping with hard-coded topic rules
- redesign ingestion
- change the V1 source model or delivery channel

## Final Acceptance Criteria

The daily pipeline hardening effort is complete when:

1. decision state and presentation copy are clearly separated
2. render layer is no longer the main location for business repair logic
3. dedup and section exclusivity are resolved before rendering
4. copy-generation defects do not invalidate correct decision membership
5. degraded behavior follows explicit stage-specific fallback rules
6. daily reruns are versioned and reproducible

