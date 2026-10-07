# AI Radar Hosted Execution Technical Specification

## Document control

- Status: In review
- Revision date: 2026-10-07
- Approved product specification: `docs/PRODUCT_SPEC.md`
- Current-system baseline: public source repository, file-backed runtime state, five systemd timers on the former Hong Kong server

## 1. Design drivers

### Required outcomes

- Production collection, curation, Feishu delivery, and site publication continue while the maintainer's personal computer is powered off.
- The main source repository remains public and contains no runtime state or credentials.
- Existing `state/`, `transcripts/`, and `reports/` semantics remain intact across ephemeral runner replacement.
- Overseas source access does not depend on a VPN installed on the Tencent Shanghai server.
- Cutover must prevent duplicate Feishu delivery and duplicate site publication.
- No additional always-on overseas server is purchased for V1.

### Current facts

- The CLI already exposes independent `ingest`, `tier1`, `daily-curate`, `daily`, and `weekly` tasks.
- Runtime data is stored below `state/`, `transcripts/`, and `reports/`; all three paths are intentionally ignored by Git.
- Site publication writes to a separate `ai-radar-site` Git repository.
- Gmail OAuth currently reads credential and token JSON files and may rewrite the token file after refresh.
- The former server remains available as a rollback execution environment during migration.

### Non-goals

- Rewriting source selection, scoring, curation, or report content behavior.
- Running a VPN or proxy service on the Tencent server.
- Publishing runtime transcripts or operational state to the public source repository.
- Claiming high availability; this remains a single-maintainer hosted automation.

## 2. Options and decisions

### Execution platform

| Option | Cost | Overseas reachability | Persistent host required | Decision |
| --- | ---: | --- | --- | --- |
| GitHub-hosted Actions runner | Included for public repository under current GitHub policy | Expected, must be smoke-tested | No | Selected |
| Second overseas VPS | Recurring | Yes | Yes | Rejected for V1 cost goal |
| Tencent server only | Already owned | Some sources may be blocked | Yes | State store only |
| Personal Windows computer | Already owned | Depends on local power/VPN | Yes | Rejected for production |

GitHub Actions is selected for execution, subject to a no-delivery network smoke test. Shared runner IP rejection or repeated schedule latency that breaks two consecutive daily cycles is the reconsideration trigger.

### Durable state

| Option | Main issue | Decision |
| --- | --- | --- |
| Actions cache/artifacts | Retention and eviction make them unsuitable as the source of truth | Rejected |
| Commit state to public repo | Exposes content/operations data and grows history | Rejected |
| Separate private state repo | Works, but adds another repository and stores large transcripts poorly | Reserve fallback |
| Existing Tencent server over SSH | No new server cost, durable disk already owned, encrypted transfer | Selected |

The Tencent server stores versioned runtime snapshots under `/srv/ai-radar-data`. It does not execute source collection. A dedicated unprivileged `ai-radar-sync` account owns only this directory.

### Scheduling shape

- One daily workflow starts at `23:00 UTC` (`07:00 Asia/Shanghai`) and runs `ingest -> tier1 -> daily-curate -> daily --deliver` sequentially.
- One weekly workflow starts Monday at `01:00 UTC` (`09:00 Asia/Shanghai`) and runs `weekly --deliver`.
- `workflow_dispatch` provides a smoke/manual path; delivery defaults to false.
- A repository-level concurrency group serializes all production workflows with `cancel-in-progress: false`.

Consolidating the four daily stages in one job avoids restoring and persisting the same file state four times. It preserves stage order; exact completion time may differ from the old staggered timers.

## 3. System context and architecture

```text
GitHub schedule/manual trigger
        |
        v
GitHub-hosted Ubuntu runner ---- outbound APIs ----> YouTube/RSS/Web/Gmail/DeepSeek/Supadata
        |        |
        |        +---- Feishu webhook (delivery-enabled runs only)
        |
        +---- SSH/rsync ---- Tencent Shanghai `/srv/ai-radar-data`
        |                   durable, versioned runtime snapshots
        |
        +---- deploy key ---> `weixiaocan/ai-radar-site`
```

Trust zones:

- The public repository is untrusted for secrets and stores code/config only.
- GitHub `production` environment secrets provide API credentials, OAuth JSON, the state-sync SSH key, pinned host key, and site deploy key.
- The runner is ephemeral. Secret files are created under `$RUNNER_TEMP`, permissioned `0600`, excluded from artifacts, and deleted with the runner.
- The Tencent sync user has no sudo access and owns no application/service directories outside `/srv/ai-radar-data`.

## 4. Domain data and state

The durable bundle contains exactly:

- `state/`: deduplication IDs, stage pointers, daily run manifests, health history, heartbeat, and operational events;
- `transcripts/`: normalized source content used by downstream daily/weekly rebuilding;
- `reports/`: generated daily/weekly/ebook material required for publication and recovery.

Secrets, `.env`, Gmail credential/token files, Git metadata, virtual environments, caches, and logs containing runner diagnostics are excluded.

Snapshot rules:

1. Each job restores the current snapshot before constructing `Pipeline`.
2. A successful or classified-failure run uploads into a new staging snapshot; it never edits the current snapshot in place.
3. A manifest records run ID, workflow/task, UTC timestamp, Git commit SHA, file counts, byte counts, and bundle checksum.
4. Promotion validates required JSON/JSONL readability and atomically switches the `current` symlink.
5. Retain the latest 14 daily snapshot generations plus one pre-cutover snapshot; pruning never removes `current`.
6. If upload, validation, or promotion fails, the prior `current` remains authoritative and the workflow fails.

Invariant: only one scheduler may write production state or deliver at a time.

## 5. Modules and interfaces

### Hosted workflow entry points

- Daily and weekly workflows check out source, install Python 3.11 dependencies, materialize secrets, restore state, run the existing CLI, persist state, and upload sanitized diagnostics.
- Workflows declare `permissions: contents: read` and are triggered only by `schedule` and `workflow_dispatch`; secret-bearing jobs never run on `pull_request`.
- Official actions are pinned to immutable commit SHAs.

### State transfer scripts

- `restore_state.sh RUN_ID`: authenticates with the pinned Tencent host key and restores `current/{state,transcripts,reports}` into the workspace.
- `persist_state.sh RUN_ID TASK COMMIT_SHA`: uploads the three directories to a versioned staging area, generates/validates the manifest, and promotes it atomically.
- The scripts reject an empty remote baseline after cutover unless an explicit bootstrap flag is supplied.

### Secret materialization

- API keys and webhook values are exported directly from GitHub environment secrets.
- `GMAIL_CREDENTIALS_JSON_B64` and `GMAIL_TOKEN_JSON_B64` are decoded into `$RUNNER_TEMP`; `GMAIL_CREDENTIALS_PATH` and `GMAIL_TOKEN_PATH` point there.
- The original refresh token remains in GitHub Secrets. Refreshed short-lived access-token changes are not persisted to the public repo or state bundle.

### Site publishing

- The workflow checks out `weixiaocan/ai-radar-site` as a sibling path using a repository-scoped read/write deploy key.
- `SITE_REPO_PATH`, `SITE_PUBLISH_ENABLED`, branch, Git author, and push timeout are set in the runner.
- Existing `SitePublisher` remains the publication boundary and its retry behavior is retained.

## 6. Main and failure flows

### Daily success

1. Acquire GitHub concurrency slot and restore current durable bundle.
2. Execute the four existing CLI tasks in order; only the final daily task uses `--deliver`.
3. Existing daily publication updates the site repository.
4. Persist and atomically promote the runtime snapshot.
5. Upload sanitized task logs as a short-retention Actions artifact.

### Smoke and cutover

1. Configure secrets and server-side sync account.
2. Import the latest former-server runtime bundle as the pre-cutover snapshot.
3. Run manual smoke without `--deliver` and with site publishing disabled.
4. Disable all five former-server timers.
5. Enable scheduled GitHub delivery.
6. Keep the former server available until two consecutive daily cycles complete and the Monday workflow is either observed or manually dry-run.

### Failures

- Source/API failure: preserve existing source-health classification and persist the resulting operational state when structurally valid.
- Pipeline crash: upload sanitized logs; promote state only if bundle validation succeeds. Delivery stages are not retried automatically inside the same run unless existing application logic is idempotent.
- State restore failure: abort before any collection or delivery.
- State persist failure after delivery: mark the workflow failed and block automatic rerun with delivery until an operator compares Feishu/site history, preventing duplicates.
- Site push failure: retain existing pending commit behavior, persist state, and use `recover-site` after inspection.
- Schedule delay: record actual start/finish timestamps; do not start a second overlapping run.

## 7. Security, privacy, and compliance

- GitHub Secrets/environment secrets store all API keys, webhook URLs, OAuth JSON, and private keys.
- The state SSH host key is pinned; `StrictHostKeyChecking=yes` is mandatory.
- The state-sync key is unique to Actions and restricted in `authorized_keys` with forwarding disabled.
- The Tencent account is unprivileged, has a dedicated home/data directory, and cannot control Docker or systemd.
- Workflow logs must not echo environment variables, decoded credential files, raw provider responses containing credentials, or private keys.
- Actions artifacts contain only sanitized logs and manifest metadata, never `state/`, `transcripts/`, `reports/`, `.env`, or Gmail files.
- Branch protection and review of workflow changes are recommended because default-branch workflow code can access production secrets.

## 8. Observability and operations

- Existing `heartbeat.log`, `source_health.jsonl`, `ops_events.jsonl`, and weekly Feishu health card remain authoritative application signals.
- GitHub Actions supplies per-run logs, outcome, duration, commit SHA, and manual rerun controls.
- A job summary reports task, target date, restored snapshot ID, promoted snapshot ID, source-health counts, publication result, and delivery flag without secret values.
- GitHub failure notification is enabled; an optional Feishu operational alert can be added after the core cutover.
- Snapshot retention is 14 days; the pre-cutover snapshot is retained until migration acceptance.
- Rollback restores the latest validated snapshot to `/opt/ai-radar`, disables GitHub schedules/delivery, and re-enables the five former-server timers. Both sides must never be active simultaneously.

## 9. Verification and evaluation strategy

### Deterministic tests

- Existing unit test suite remains green.
- Add tests for workflow command construction, secret-path handling, snapshot manifest validation, empty-baseline rejection, and no-delivery defaults.
- Static checks assert no workflow runs secret-bearing jobs on pull requests and no runtime directory is uploaded as an artifact.

### Integration evidence

- Server bootstrap test proves the sync account cannot use sudo or write outside its assigned data root.
- State round-trip test restores a fixture bundle, changes files, promotes a version, and restores identical checksums.
- Site dry run confirms checkout/commit path without pushing production content.
- Authorized no-delivery smoke run records a classified result for every configured source.

### Acceptance evidence

- Two consecutive scheduled daily cycles succeed while the personal computer is off.
- `seen_ids`, normalized transcripts, health history, and generated reports survive a fresh runner.
- Exactly one daily Feishu delivery and at most one site commit occur per target day.
- Repository and artifacts pass secret scanning.

## 10. Delivery plan

### HR-T1 Runner-safe deployment seams

- Add hosted shell scripts, environment validation, and tests without enabling a schedule.
- Covers HR-2 and HR-3.
- Evidence: unit tests and local fixture state round trip.

### HR-T2 Tencent durable state store

- Create the unprivileged sync account, import a validated pre-cutover snapshot, and verify restricted permissions and atomic promotion.
- Covers HR-2.
- Evidence: remote permission checks, manifest/checksum comparison, rollback restore.

### HR-T3 GitHub workflows and secret configuration

- Add manual smoke plus disabled-by-default daily/weekly workflow definitions, configure production environment secrets, site deploy key, concurrency, and summaries.
- Covers HR-1, HR-3, HR-4, HR-6.
- Evidence: tests plus a manual no-delivery workflow run.

### HR-T4 Controlled cutover

- Freeze/snapshot old state, disable old timers, enable GitHub schedules, observe two daily cycles, then record migration acceptance.
- Covers HR-1 and HR-5.
- Evidence: timer state, workflow URLs/run IDs, heartbeat/source-health entries, Feishu and site deduplication check.

## 11. Requirement traceability

| Requirement | Design | Delivery | Evidence |
| --- | --- | --- | --- |
| HR-1 hosted execution | Sections 2, 3, 5 | HR-T3, HR-T4 | Two scheduled cycles with PC off |
| HR-2 durable state | Sections 2, 4, 5 | HR-T1, HR-T2 | Round-trip checksums and fresh-runner restore |
| HR-3 secret isolation | Sections 3, 5, 7 | HR-T1, HR-T3 | Secret scan and artifact inspection |
| HR-4 network reachability | Sections 2, 6 | HR-T3 | No-delivery source smoke |
| HR-5 safe cutover | Sections 4, 6, 8 | HR-T4 | Single active scheduler and dedupe check |
| HR-6 cost control | Section 2 | HR-T3 | No second overseas VPS |

## 12. Risks and open technical decisions

| Risk/open item | Impact | Closure condition |
| --- | --- | --- |
| Shared GitHub runner IP blocked by a source | Missing source data | Smoke test every configured source; choose a low-cost managed runner only if failures repeat |
| GitHub scheduled jobs can start late | Late digest | Measure two cycles; reconsider platform if lateness breaches the acceptable window |
| Tencent SSH port is reachable from dynamic runner IPs | Credential attack surface | Dedicated user/key, no sudo, forwarding disabled, pinned host key, server rate limiting |
| Delivery succeeds but state promotion fails | Manual rerun could duplicate delivery | Persist a delivery receipt/idempotency marker before enabling automatic reruns; require operator review meanwhile |
| Snapshot growth | Disk exhaustion | Record bytes per snapshot, hard-link unchanged files, retain 14 daily generations, alert before 80% disk use |
| GitHub public-runner policy or quota changes | Cost/availability change | Re-check policy when billing notifications or runner failures appear |

The delivery-receipt safeguard is a required implementation detail before scheduled delivery is enabled. The exact acceptable schedule delay threshold remains a maintainer product choice; initial observation will record actual latency rather than assuming it.

## 13. Approval

Status: awaiting maintainer approval. Approval authorizes implementation of HR-T1 through HR-T3 and a no-delivery smoke run. Enabling production delivery and disabling the former-server timers remain a separately visible cutover step.
