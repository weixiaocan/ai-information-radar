# AI Radar

一个面向 AI 从业者的日报 / 周报系统，用来回答一件事：**哪些内容值得看，哪些可以跳过。**

它会抓取一组固定来源，做标准化、摘要、筛选，然后把结果推送到飞书。

## 它做什么

- 每天推送一份日报
- 每周推送一份周报
- 单独给出本周最值得亲自看的 Top 2 视频
- 把 Builder/X 讨论和 editorial 精选分开处理

## 信息源

当前主内容源：

- YouTube channels / playlists
- RSS feeds
- Web scrape sources

Builder/X 信号源：

- Zara upstream builder feed

其中 Builder/X 仍使用 [`zarazhangrui/follow-builders`](https://github.com/zarazhangrui/follow-builders) 作为上游输入；Zara 只负责 Builder/X，blog / podcast 内容已经并入本地抓取链路。

## 日报

日报包含四部分：

- `今日热议`：只看 Builder/X
- `今日精选`：只从 editorial candidates 里选
- `补充候选`：进过候选池但没进前两栏
- `今日数据`：当天抓取与展示统计

## 周报

周报包含两部分：

- `本周重要主题`
- `本周最值得亲自看的内容`

其中 Top 2 只来自完成 Tier 2 评分的 YouTube 内容。

每周推荐的播客文字稿默认复制到 Obsidian 目录 `D:\huangxh\obsidian\输出\公众号\已发布\AI_RADAR`，项目内的 `reports/ebook/` 原稿仍保留。本地生成任务可通过 `.env` 中的 `WEEKLY_EBOOK_EXPORT_DIR` 覆盖导出路径；Windows 计划任务使用的服务器拉取脚本 `scripts/pull_weekly_ebook.ps1` 只同步服务器本周一以来生成的稿件到上述 Obsidian 目录，并在日志中记录周区间和文件名。PowerShell 脚本以纯 ASCII 保存，并在运行时构造中文路径，避免 Windows PowerShell 5 将无 BOM 的 UTF-8 路径解码成乱码。

## 快速开始

```powershell
git clone https://github.com/weixiaocan/ai-information-radar.git
cd ai-information-radar
conda create -n ai-radar python=3.11 -y
D:\anaconda\envs\ai-radar\python.exe -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，至少填写：

- `YOUTUBE_API_KEY`
- `DEEPSEEK_API_KEY`
- `SUPADATA_API_KEY`
- `FEISHU_WEBHOOK_URL`

注册定时任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_tasks.ps1 -PythonExe "D:\anaconda\envs\ai-radar\python.exe"
```

手动推送一次日报：

```powershell
D:\anaconda\envs\ai-radar\python.exe main.py --task daily --deliver
```

## 常用命令

```powershell
D:\anaconda\envs\ai-radar\python.exe main.py --task ingest
D:\anaconda\envs\ai-radar\python.exe main.py --task tier1
D:\anaconda\envs\ai-radar\python.exe main.py --task daily-curate
D:\anaconda\envs\ai-radar\python.exe main.py --task daily --deliver
D:\anaconda\envs\ai-radar\python.exe main.py --task tier2
D:\anaconda\envs\ai-radar\python.exe main.py --task weekly --deliver
```

## 运行健康记录

- 每次 `ingest` 会把逐源状态追加到 `state/source_health.jsonl`，不会只保留最后一次结果。
- 状态区分 `success`、`no_new_items`、`degraded`、`failed`、`feed_failed`、`timed_out` 等情况。
- 每周一的 `weekly --deliver` 会在内容周报之后，再单独发送一张飞书系统健康周报。
- 健康周报检查过去一周的 ingest、daily-curate、daily 是否按天完成，并列出异常或降级来源、发生次数和最近错误。

## 输出示例

<p align="center">
  <img src="docs/images/daily_digest.png" alt="AI Radar daily digest screenshot" width="820" />
</p>

## 公开站点发布

这个仓库可以把生成好的日报 / 周报同步到一个独立的公开站点仓库。

1. 创建并克隆一个同级仓库，例如 `..\ai-radar-site`
2. 将 [`site_starter/`](./site_starter) 里的 Astro 起始模板复制过去
3. 在 `.env` 中设置以下配置

```env
SITE_PUBLISH_ENABLED=true
SITE_REPO_PATH=..\ai-radar-site
SITE_GIT_BRANCH=main
SITE_PUBLISH_TIMEOUT_SECONDS=60
SITE_PUSH_RETRY_DELAYS_SECONDS=180,300,600
```

`SITE_PUSH_RETRY_DELAYS_SECONDS` controls automatic retries for `git push`. The default `180,300,600` means retry once after 3 minutes, then after 5 minutes, then after 10 minutes.

手动同步并发布：

```powershell
D:\anaconda\envs\ai-radar\python.exe main.py --task publish-site
```

只恢复已经提交但推送失败的站点更新：

```powershell
D:\anaconda\envs\ai-radar\python.exe main.py --task recover-site
```

用仓库内置的 starter 初始化独立站点仓库：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_site_repo.ps1 -SiteRepoPath ..\ai-radar-site
cd ..\ai-radar-site
npm install
```

完成后，只要 `SITE_PUBLISH_ENABLED=true`，`daily` 和 `weekly` 任务就会自动把内容发布到站点仓库。

## 目录结构

- `src/`：代码
- `config/`：来源配置
- `prompts/`：提示词
- `transcripts/`：标准化内容仓
- `state/`：运行状态、候选池、主题、选择结果
- `reports/`：日报 / 周报归档

## 阿里云服务器部署

生产任务运行在香港阿里云 Ubuntu 服务器，项目目录为 `/opt/ai-radar`。服务器使用 Python 虚拟环境和 systemd timers；Windows 本机只保留代码副本，以下 5 个计划任务必须保持禁用，避免重复抓取或重复推送：

- `AI Radar Ingest`
- `AI Radar Tier1`
- `AI Radar Daily Curate`
- `AI Radar Daily Digest`
- `AI Radar Weekly Digest`

服务器按 `Asia/Shanghai` 时区执行：

| 时间 | systemd timer | 任务 |
| --- | --- | --- |
| 每天 07:00 | `ai-radar-ingest.timer` | 抓取最近 1 天内容 |
| 每天 07:30 | `ai-radar-tier1.timer` | Tier 1 处理 |
| 每天 07:50 | `ai-radar-daily-curate.timer` | 日报策展 |
| 每天 08:30 | `ai-radar-daily.timer` | 生成、发布并推送日报 |
| 每周一 09:00 | `ai-radar-weekly.timer` | 生成周报并发送系统健康卡 |

在本机通过 SSH 查看定时器和日志：

```powershell
ssh ai-radar-server "systemctl list-timers 'ai-radar-*' --all"
ssh ai-radar-server "journalctl -u ai-radar-daily.service -n 100 --no-pager"
ssh ai-radar-server "tail -n 20 /opt/ai-radar/state/heartbeat.log"
```

服务器手动补跑命令：

```powershell
ssh ai-radar-server "cd /opt/ai-radar && ./scripts/run_pipeline.sh ingest --days 1"
ssh ai-radar-server "cd /opt/ai-radar && ./scripts/run_pipeline.sh tier1"
ssh ai-radar-server "cd /opt/ai-radar && ./scripts/run_pipeline.sh daily-curate"
ssh ai-radar-server "cd /opt/ai-radar && ./scripts/run_pipeline.sh daily --deliver"
ssh ai-radar-server "cd /opt/ai-radar && ./scripts/run_pipeline.sh weekly --deliver"
```

部署使用的 systemd 文件位于 `deploy/systemd/`。修改代码或配置后，需要同步到 `/opt/ai-radar` 并执行 `systemctl daemon-reload`；不要把 `.env`、SSH 私钥或其他 secrets 提交到 Git。
