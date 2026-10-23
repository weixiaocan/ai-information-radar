# 抓取窗口固定化与信息源扩充方案

> 状态：已实现（2026-10-15）。AGENTS.md 的窗口措辞已同步修订（已获维护者同意）。
>
> 实现时的调整：
> - 不另设 YouTube 单频道上限，因为 Tier 2 本来就只对全局前 `TIER2_CANDIDATE_COUNT`（默认 5）条抓取字幕。
> - 机器之心 `https://www.jiqizhixin.com/rss` 现在返回的是"数据服务"网页，不是 RSS，所以没有加入；中文源的替代方案待定。
> - 只有日期的文章被宽限收录时，`published_at` 会被置为窗口起点，原始日期保存在 `extra_metadata.source_published_date`，这样日报能按窗口读到它。

## 1. 抓取窗口固定化（与触发时间解耦）

问题：hosted `run_daily.sh` 传 `--days 1`，窗口 = [运行时刻-24h, 运行时刻)。GitHub 触发在 09:29–11:34 漂移，导致缺口、重叠，运行失败的那天整天丢失；只有日期精度的网页文章（Anthropic）被记为 00:00 UTC，几乎必然落在窗口起点之前被丢弃（已复现：`anthropic.com/engineering/redesigning-source-control`，2026-10-13）。

改为：

- 日窗口固定为 Asia/Shanghai `[D-1 07:00, D 07:00)`，与实际运行时刻无关；`label_date` 按此窗口定义，与 `delivery_receipt` 的 target 计算共用同一函数。
- 补漏：若上一个已完成窗口的结束时间早于本窗口起点，从上次结束处开始，最多回看 3 天；超过上限写 `ops_events.jsonl` 并告警。重叠部分由 `seen_ids` 去重。
- 只有日期精度的条目（时间部分为 00:00 且来源没有提供时间）：按 Asia/Shanghai 日期比较，宽限 2 天，并依赖 `seen_ids` 去重。
- 被判定为窗口外的旧网页文章 URL 也记入 `seen_ids`（或单独的 `web_known_urls`），避免每次运行重复下载 20 篇旧文。
- `zara_x` 行为不变（不做窗口过滤，只用 `seen_ids`）。
- 去掉 hosted 脚本中的 `--days 1`，改为显式窗口模式；首次 bootstrap 仍为 7 天。
- 同步修订 AGENTS.md："Normal daily ingest fetches only the last 1 day" → 固定日窗口，失败后补漏最多 3 天。
- 测试：触发时间漂移（07:00 / 09:30 / 11:30）、前一天失败、日期精度文章在美国下午发布这三种场景，都不漏、不重复。

## 2. Anthropic 来源

| 动作 | 来源 | 说明 |
|---|---|---|
| 新增 | `https://www.claude.com/blog` | 列表数据在 Next/Webflow 嵌入的转义 JSON 中（`slug\":\"...`），文章 URL 形如 `/blog/<slug>`；需要为 web_fetcher 增加该页面的发现逻辑（或通用的"嵌入 JSON slug"发现方式），注意过滤掉分类 slug（如 `agents`、`coding`） |
| 修复 | `anthropic.com/engineering` | 由第 1 节修复；保留现有配置 |
| 新增 | Anthropic Academy `https://anthropic.skilljar.com/` | 课程列表在静态 HTML 中（`href="/<course-slug>"`）。无发布日期：首次运行时把现有课程全部写入 seen 而不推送，之后新出现的 slug 视为当天发布；排除 `certification-faq` 等非课程链接 |
| 停用 | `claude_blog`（实为 `anthropic.com/news`） | `enabled: false`；或改名为 "Anthropic News" 后停用 |

## 3. YouTube 新增频道（`config/channels.yaml`）

| name | display_name | handle | reason |
|---|---|---|---|
| ai_engineer | AI Engineer | `@aiDotEngineer` | 一线团队讲 Agent、评估、上线的工程实践；大会后会集中上传，注意成本 |
| indydevdan | IndyDevDan | `@indydevdan` | Claude Code 与 agentic coding 工作流实战 |
| cole_medin | Cole Medin | `@ColeMedin` | 从零搭建 Agent / RAG / MCP 项目，代码开源，适合动手练习 |
| dave_ebbelaar | Dave Ebbelaar | `@daveebbelaar` | 面向开发者的 AI 工程实践与转行路径 |

- AI Engineer 大会期间单日可能新增几十个视频：Tier 1 摘要和粗评分会覆盖全部视频，但只有全局前 5 条会抓字幕。

## 4. RSS 新增（`config/rss_sources.yaml`）

| name | display_name | url |
|---|---|---|
| hamel_husain | Hamel Husain | `https://hamel.dev/index.xml` |
| chip_huyen | Chip Huyen | `https://huyenchip.com/feed.xml` |
| huggingface_blog | Hugging Face Blog | `https://huggingface.co/blog/feed.xml` |

- 明确不加：AINews（本身是 AI 生成的汇总，与现有源高度重叠）、claude-cookbooks（需要过滤提交）。
- 2026-10-23 修订：原方案排除了 `anthropic.com/research`，但未记录理由；该栏目包含与 AI Agent、工程实践和工作变化直接相关的研究，因此加入监控。常规抓取窗口不会自动补录加入前的旧文。

## 5. 提示词

- `prompts/daily_curator.md` 的来源信任名单加上：AI Engineer、Hamel Husain、Claude Blog（claude.com）、Anthropic Engineering（已有）。

## 6. 验收

- 本地对每个新源跑一次不推送的 ingest（smoke），在 `source_health.jsonl` 中显示 success 或 no_new_items。
- 用 `redesigning-source-control` 做回归测试：修复后它会被收录。
- 更新 README 的信息源列表，保留 Zara 来源说明。
