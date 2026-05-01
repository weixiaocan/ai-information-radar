# AI Radar

一个帮我做“看不看”决策的 AI 信息雷达。

它每天追踪多种 AI 信息源，但不会把所有内容都重写成长文，而是先抓取、归一化、建立候选池，再筛出真正值得看的内容，最后通过飞书自动推送日报和周报。

![AI Radar 日报截图](docs/images/daily_digest.png)

## 它做什么

- 聚合 YouTube、RSS 和 Builder/X 信息源
- 将所有来源统一归一化为 `ContentItem`
- 先构建候选池，再做最终选择，而不是边改写边重排
- 每天早上推送前一天的日报
- 每周生成周报和 Top 2 深读内容

## 日报结构

日报分四层：

- `今日热议`
  - 只基于 Builder/X 内容
  - 如果几个人在讨论同一件事，聚合成 `0-3` 个主题
  - 主题 evidence 只展示 X 来源
  - 如果凑不成真主题，降级成 `2-4` 条值得看的 Builder/X 帖子
- `今日精选`
  - 只从 `editorial_candidates` 里选
  - 目前最多 `5` 条
  - 先做显式候选池过滤与排序，再做最终精选
- `补充候选`
  - 展示进入过候选池，但没有进入 `今日热议` 或 `今日精选` 的内容
  - 保持轻量，优先单行展示
- `今日数据`

### 今日热议规则

- 主题聚合只看 Builder/X
- 真主题要求至少 `3` 个不同 builder 或信息源在讨论同一件事
- 不能只因为共享一个大词就硬并成主题
- Spotlight 文案只讲“发生了什么”，不解释“为什么值得看”
- 如果一句话讲不清具体发生了什么，就不应进入 spotlight

### 今日精选规则

- 只从 `editorial_candidates` 中选择
- 当前会先产生：
  - `editorial_candidates_raw`
  - `editorial_candidates_filtered`
  - `editorial_top10`
- 最终 `今日精选` 从 `Top 10` 中选出
- `value_pitch` 只给已经入选的内容生成

## 周报结构

周报分两层：

- `本周重要主题`
- `本周最值得亲自看的内容`

其中周报 Top 2 只从完成 Tier 2 评分的 YouTube 内容中选出。

## 信息源

当前仓库显式配置了：

- 9 个 YouTube channels，见 [`config/channels.yaml`](config/channels.yaml)
- 4 个 RSS sources，见 [`config/rss_sources.yaml`](config/rss_sources.yaml)
- 3 个 Builder / blog / podcast 聚合 feeds，见 [`config/zara_feed.yaml`](config/zara_feed.yaml)

其中 Builder 聚合源的接入思路借鉴自 [`zarazhangrui/follow-builders`](https://github.com/zarazhangrui/follow-builders)，当前项目使用了它的中心 feed 作为上游输入之一。

## 来源图标

日报里目前使用这组来源图标：

- `𝕏`：X / Builder
- `▶️`：YouTube
- `📰`：RSS / article

## 技术栈

- Python
- DeepSeek API
- Feishu webhook
- Windows Task Scheduler
- 本地文件系统 + JSON / JSONL 状态文件

## 如何使用

V1 当前只支持在 `Windows + Anaconda` 环境中本地运行和部署。

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

首次部署后，注册 Windows 定时任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_tasks.ps1 -PythonExe "D:\anaconda\envs\ai-radar\python.exe"
```

如果要先手动验证一次飞书推送：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_pipeline.ps1 -PythonExe "D:\anaconda\envs\ai-radar\python.exe" -Task daily -Deliver
```

常用命令：

```powershell
D:\anaconda\envs\ai-radar\python.exe main.py --task ingest
D:\anaconda\envs\ai-radar\python.exe main.py --task tier1
D:\anaconda\envs\ai-radar\python.exe main.py --task daily-curate
D:\anaconda\envs\ai-radar\python.exe main.py --task daily --deliver
D:\anaconda\envs\ai-radar\python.exe main.py --task tier2
D:\anaconda\envs\ai-radar\python.exe main.py --task weekly --deliver
```

## 定时任务与睡眠

当前推荐配置：

- 任务使用 `SYSTEM` 运行
- `WakeToRun = True`
- `StartWhenAvailable = True`

如果你要求早上 `08:00` 准时推送，建议再确认：

```powershell
powercfg /change standby-timeout-ac 0
```

这会把“插电状态下自动睡眠”改成关闭，避免机器在夜里睡过去错过任务。

## 目录结构

- `src/`：源码
- `config/`：静态配置
- `prompts/`：提示词
- `transcripts/`：归一化原始内容
- `state/`：运行状态、候选池、主题和选择结果
- `reports/daily/`：日报归档
- `reports/weekly/`：周报归档

## 当前实现重点

- Daily pipeline 已拆成：
  - `ingest`
  - `tier1`
  - `build candidates`
  - `select themes / selections`
  - `render + deliver`
- 候选池与最终选择分离
- Builder/X 热议与 Editorial 精选分离
- Spotlight 和精选文案都优先要求“讲清楚发生了什么”
