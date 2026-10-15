# 定时推送可靠性改造方案

> 状态：待实现（交给 Codex）。本文件遵循 `AGENTS.md` 的 V1 硬约束，不改变产品范围。

## 1. 现状诊断（2026-10-15 采集自 GitHub Actions API）

当前架构：GitHub 托管 Ubuntu runner 执行流水线（能访问海外源），大陆服务器只作为 SSH/rsync 状态存储。触发器是 GitHub `schedule` cron。

| 计划时间 (UTC) | 实际启动 (UTC) | 北京时间 | 延迟 | 结果 |
|---|---|---|---|---|
| 10-09 23:17 daily | 10-10 02:20 | 10:20 | 3h03m | success |
| 10-10 23:17 daily | 10-11 01:54 | 09:54 | 2h37m | success |
| 10-11 23:17 daily | 10-12 02:24 | 10:24 | 3h07m | success |
| 10-12 01:00 weekly | 10-12 07:06 | 15:06 | 6h06m | success |
| 10-12 23:17 daily | 10-13 03:34 | 11:34 | 4h17m | success |
| 10-13 23:17 daily | 10-14 01:54 | 09:54 | 2h37m | success |
| 10-14 23:17 daily | 10-15 01:29 | 09:29 | 2h12m | **failure**（`Run daily pipeline` 步骤，耗时 33 分钟后 exit 1） |

结论：

1. **"不准时"的根因是 GitHub `schedule` 触发器本身**，不是 Codex 定时任务，也不是流水线慢。GitHub 文档明确 `schedule` 是 best-effort，高峰期会延迟数小时甚至丢弃。避开整点（`6dbaa0c`）没有效果，延迟稳定在 2–6 小时。流水线本身只需 6–10 分钟。
2. `workflow_dispatch`（API 手动触发）通常在数秒内启动，不受 cron 队列影响。
3. 另有三项隐患：
   - 今天失败的原因未知，需要看日志（日志需鉴权，公开 API 拿不到）。
   - `ubuntu-latest` 将从 **2026-10-19** 起迁移到 Ubuntu 26，可能导致 Python/依赖异常。
   - 投递回执为 `uncertain`/`started` 时 `reserve_delivery` 直接拒绝，当天之后的所有重试都会失败，必须人工处理，而且目前没有任何告警。
   - 公开仓库 60 天无提交时 GitHub 会自动禁用 scheduled workflow（状态存在服务器上，不会产生提交，所以这是现实风险）。

## 2. 目标方案：服务器精准触发 + GitHub 执行 + 值守兜底

执行环境不变（GitHub runner，仍满足"不依赖个人电脑、能访问海外源"），只替换**触发器**，并补上**值守与告警**。

```
大陆服务器 systemd timer (07:00 北京)
   └─ curl POST workflow_dispatch ──► GitHub Actions (秒级启动) ──► 抓取/LLM/飞书/站点
                                            │
GitHub schedule cron（保留作兜底）──────────┘   同一 concurrency 组 + 投递回执去重

大陆服务器 watchdog timer (08:30 / 09:30 北京)
   └─ 读本地状态存储里的投递回执 → 未完成则重新 dispatch 一次 → 仍失败则飞书告警
```

为什么选服务器做触发器：服务器已经存在、是状态存储的所在地（服务器宕机时流水线本来也无法运行，不增加新的单点）、从大陆访问 `api.github.com` 和飞书 webhook 都可用。个人电脑不参与。

### 2.1 时间表（Asia/Shanghai）

| 任务 | 主触发 | 值守 1：重新触发 | 值守 2：告警 | GitHub cron 兜底 |
|---|---|---|---|---|
| daily | 每天 07:00 | 08:30 | 09:30 | 保留 `17 23 * * *` |
| weekly | 周一 08:00 | 09:30 | 10:30 | 保留 `0 1 * * 1` |

weekly 主触发晚于 daily，与 daily 共用 `ai-radar-production` concurrency 组，自动排队，不并发写状态。

## 3. 实现任务清单（给 Codex）

### T1. 先查清今天的失败（阻塞后续）

- `gh run list --workflow ai-radar-daily.yml -L 5`，`gh run view <id> --log-failed`，定位 2026-10-15 run 的失败原因并修复。
- 在服务器上检查 `${AI_RADAR_STATE_ROOT}/current/state/delivery_receipts/daily-*.json`。如果有 `started`/`uncertain` 状态，确认飞书是否实际收到，再人工把回执改为 `completed` 或删除后补跑。把处理步骤写进 `docs/TECH_SPEC.md` 运维章节。

### T2. Workflow 调整

- `ai-radar-weekly.yml` 增加 `workflow_dispatch`，并加上与 daily 相同的 `confirm == 'RUN_PRODUCTION'` 守卫。
- 两个 workflow 的 dispatch 增加可选输入 `trigger_source`（`server-primary` / `server-watchdog` / `manual`），写入 heartbeat 和 run 日志，用于统计各触发源的延迟。
- **提前去重**：在 `Restore durable state` 之后、ingest 之前新增一步，计算当天的 daily 目标日期（与 `latest_ingest_window.label_date` 的计算规则保持一致，从同一个函数导出，不要复制逻辑）。如果回执已是 `completed`，就 `exit 0` 并输出 "already delivered"，避免迟到的 cron 兜底重复跑 ingest 和 DeepSeek。为此在 `src/hosting/delivery_receipt.py` 增加 `status` 子命令。
- `runs-on` 固定为 `ubuntu-24.04`，不再用 `ubuntu-latest`；把 `actions/checkout`、`actions/setup-python` 升级到 Node 24 版本，继续用 commit SHA 固定。
- 加一条 `if: failure()` 步骤：用 `FEISHU_WEBHOOK_URL`（或单独的 `FEISHU_OPS_WEBHOOK_URL`）发一条简短的中文失败告警，附 run 链接，所有请求加 `--max-time`。告警本身失败不影响 job 结论。

### T3. 服务器触发器（新增 `deploy/trigger/`）

- `deploy/trigger/dispatch.sh TASK SOURCE`：
  - `curl --max-time 20 --retry 3 --retry-delay 30 --retry-all-errors` 调 `POST /repos/weixiaocan/ai-information-radar/actions/workflows/ai-radar-{daily,weekly}.yml/dispatches`，body `{"ref":"main","inputs":{"confirm":"RUN_PRODUCTION","trigger_source":"..."}}`。
  - 期望 HTTP 204。否则以非 0 退出，并在 `${AI_RADAR_STATE_ROOT}/ops/trigger.jsonl` 追加一条记录。
- 凭据：fine-grained PAT，**只授予这个仓库的 Actions: Read and write**，存放在服务器 `/etc/ai-radar/dispatch.env`（`chmod 600`，属主为运行用户），绝不提交。在 `.env.example` 和文档中说明变量名 `AI_RADAR_DISPATCH_TOKEN`。
- systemd：`ai-radar-dispatch@.service`（oneshot，参数为 task）+ `ai-radar-dispatch-daily.timer`（`OnCalendar=*-*-* 07:00:00 Asia/Shanghai`，`Persistent=true`，`RandomizedDelaySec=0`）+ `ai-radar-dispatch-weekly.timer`（`Mon *-*-* 08:00:00 Asia/Shanghai`）。
- 注意：`deploy/systemd/` 里旧的本机执行 timer 必须保持 disabled，不能与 GitHub 执行同时启用（TECH_SPEC 的单写者约束）。新 timer 只发 HTTP 请求，不运行流水线，也不写 `current/` 状态。

### T4. 服务器值守（watchdog）

- `deploy/trigger/watchdog.py TASK --phase {redispatch,alert}`，纯标准库，所有网络调用都有显式超时：
  1. 直接读服务器本地 `${AI_RADAR_STATE_ROOT}/current/state/delivery_receipts/{task}-{target}.json`（服务器就是状态存储，无需 SSH）。
  2. 回执为 `completed`：静默退出。
  3. 通过 GitHub API 查询该 workflow 是否有 `queued`/`in_progress` 的 run。有则只记录，不动作。
  4. 回执不存在且无运行中的 run：`redispatch` 阶段调用 `dispatch.sh TASK server-watchdog`；`alert` 阶段发飞书告警。
  5. 回执为 `started`/`uncertain`：**不重新触发**（可能已推送，避免重复），直接飞书告警"需要人工核对"，并附回执内容。
  6. 同时检查 workflow `state` 是否为 `disabled_inactivity`/`disabled_manually`。如果是，立即告警（应对 60 天无活动自动禁用）。
- 每次检查追加到 `${AI_RADAR_STATE_ROOT}/ops/watchdog.jsonl`。告警发送失败也要记录。
- systemd timer 按 2.1 的时间表配置。

### T5. 测试与验收

- 单元测试：`delivery_receipt status` 子命令；提前去重步骤；watchdog 在 completed / 无回执且无运行 / 运行中 / uncertain / workflow 被禁用五种情况下的行为（mock GitHub API 和文件系统）。
- 手动验证：服务器上执行 `systemctl start ai-radar-dispatch@daily`，确认 GitHub 在 1 分钟内启动 run、`trigger_source=server-primary`；同一天再触发一次，确认走提前去重，几秒内结束。
- 上线验收：连续 3 天，每日推送在 **07:20 前**到达飞书；当周周一 weekly 和系统健康卡在 08:30 前到达。在 `docs/TECH_SPEC.md` 记录实际时间。
- 文档：更新 `docs/TECH_SPEC.md` 的调度章节（主触发改为服务器 dispatch，cron 降级为兜底），README 补一段运维说明；保留 README 中的 Zara 来源说明。

## 4. 备选方案（当前不实施，记录触发条件）

- **服务器访问 `api.github.com` 频繁失败**：把主触发换成 Cloudflare Workers Cron Triggers（免费、准时、海外网络），调用同样的 dispatch API；值守仍留在服务器。
- **GitHub runner 到大陆服务器的 SSH/rsync 频繁超时，或 runner IP 被源站拒绝**：放弃 GitHub 执行，改用一台海外小 VPS（香港/新加坡，约 30–40 元/月），直接复用现有 `deploy/systemd/` 的 timer，状态本地持久化并每日备份。这是最简单的形态，也就是迁移前香港服务器的方案。
