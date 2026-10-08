# AI Radar Product Specification

## Document control

- Status: Approved
- Revision date: 2026-10-08
- Related evidence: `AGENTS.md`, `README.md`, existing systemd deployment units

## 1. Problem and context

AI Radar has working scheduled pipelines, but earlier documentation assumed that a personal computer and its VPN would remain available. A personal computer is not an acceptable production dependency because scheduled collection and delivery would stop whenever that computer is powered off, disconnected, or unavailable.

The product must move to a hosted execution model while preserving its existing source, curation, delivery, health, and public-site behavior.

## 2. Goals and success measures

- Scheduled AI Radar tasks run without a personal computer being powered on.
- Daily and weekly deliveries retain their current content and health semantics.
- File-based incremental state survives replacement of an individual runner or process.
- No duplicate delivery occurs during migration from the previous scheduler.
- The hosted execution path should not require purchasing another always-on overseas server unless included or usage-based runners prove unsuitable.

## 3. Primary workflows

1. The hosted scheduler starts ingest, scoring, curation, daily delivery, and weekly delivery at the configured Asia/Shanghai times.
2. Each task restores durable state before execution and persists changed state after successful execution.
3. Secrets are injected by the hosted environment and never stored in the repository.
4. Generated site content is committed and pushed to the separate `ai-radar-site` repository.
5. Failures remain observable through task logs, heartbeat state, source-health history, and the weekly health card.
6. During migration, the previous scheduler remains available for rollback but only one scheduler is enabled for delivery at a time.

## 4. Requirements and acceptance criteria

### HR-1 Hosted production execution — Must

Production execution must not depend on a personal computer.

Acceptance: with the maintainer's personal computer powered off, every scheduled task starts and completes in the hosted environment for two consecutive daily cycles.

### HR-2 Durable file state — Must

The existing file-based state model must be retained with durable persistence across runs.

Acceptance: a fresh runner can restore `seen_ids`, normalized content, health history, reports required by downstream tasks, and site publication state before running.

### HR-3 Secret isolation — Must

API keys, webhooks, OAuth credentials, tokens, and deploy credentials must use the hosted secret store or an equivalent protected mechanism.

Acceptance: repository history and build artifacts contain no `.env`, credential file, token, or secret value.

### HR-4 Network reachability — Must

The hosted environment must reach every configured content source and required API without relying on a VPN running on a personal computer.

Acceptance: an authorized smoke run records a successful or correctly classified source-health result for each configured source.

### HR-5 Safe scheduler cutover — Must

Migration must avoid duplicate delivery and duplicate site publication.

Acceptance: only one production scheduler has delivery enabled at any moment, and the previous scheduler remains available for rollback until two consecutive hosted daily cycles succeed.

### HR-6 Cost control — Should

Prefer included or usage-based managed execution over purchasing another always-on overseas server.

Acceptance: any recurring paid service requires explicit maintainer approval before activation.

## 5. Scope boundaries

In scope: hosted scheduling, durable state, secret injection, outbound source access, site publication, observability, and rollback.

Out of scope: requiring a personal computer to remain powered on; making a VPN on a mainland cloud server a production dependency; rewriting the content-selection behavior.

## 6. Risks and dependencies

- Ephemeral runners require an explicit durable-state design.
- Some sources may reject shared cloud-runner IPs; this must be tested before scheduler cutover.
- OAuth credential files require a protected persistence and refresh strategy.
- Hosted-runner quotas may require task consolidation or another managed execution option.

## 7. Confirmed decisions

- Production must not depend on a personal computer.
- The main source repository remains public.
- Secrets and credentials remain exclusively in the hosted secret store and must not be committed.

## 8. Approved deployment decisions

- GitHub-hosted Actions runners execute the scheduled pipelines, subject to the required no-delivery network and runtime smoke test before production cutover.
- The existing Tencent Shanghai server stores versioned durable runtime snapshots over SSH; it does not run the overseas collection workload.
- Snapshot retention, trust boundaries, rollback, and verification follow `docs/TECH_SPEC.md`.

## 9. Approval

The hosted-execution requirement and public-repository decision were explicitly confirmed by the project maintainer on 2026-10-07. The GitHub Actions execution and Tencent durable-state design was approved on 2026-10-08; production cutover remains gated by the specified smoke and migration checks.
