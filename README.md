# AI Radar

一个会替我做“看不看”决策的 AI 信息系统。

每天追十几个 AI 信息源，但只推给我最值得花时间的那几条。

它不会把所有来源重写成新的长文，而是先抓取内容、建立候选池，再生成日报和周报，最后通过飞书自动推送。

![AI Radar 日报截图](docs/images/daily_digest.png)

## 它做什么

- 聚合 YouTube、RSS，以及 builder / blog / podcast 聚合源
- 将所有来源统一归一化为 `ContentItem`
- 先建立候选池，再筛出日报和周报里真正值得看的内容
- 每天早上推送前一天的日报，每周日中午推送周报

## 日报和周报

日报分三层：

- `今日热议`
  - 有足够集中讨论时，输出主题
  - 不成主题时，降级为值得看的 builder 帖子
- `今日精选`
  - 从当天内容里挑 5 条最值得看的
- `补充候选`
  - 展示进过候选池但没有入选的内容

周报分两层：

- `本周重要主题`
- `本周最值得亲自看的内容`

其中周报 Top 2 只从完成 Tier 2 评分的 YouTube 内容里选出。

## 信息源

当前仓库显式配置了：

- 9 个 YouTube channels，见 [`config/channels.yaml`](config/channels.yaml)
- 4 个 RSS sources，见 [`config/rss_sources.yaml`](config/rss_sources.yaml)
- 3 个 builder / blog / podcast 聚合 feeds，见 [`config/zara_feed.yaml`](config/zara_feed.yaml)

其中 builder 聚合源的接入思路借鉴自 [`zarazhangrui/follow-builders`](https://github.com/zarazhangrui/follow-builders)，当前项目使用了它的中心 feed 作为上游输入之一。

## 技术栈

- Python
- DeepSeek API
- Feishu webhook
- Windows Task Scheduler
- 本地文件系统 + JSON / JSONL 状态文件

## 如何使用

V1 当前只支持在 `Windows + Anaconda` 环境下本地运行和部署，不保证 Linux、macOS、Docker 或纯系统 Python 环境可直接使用。

```powershell
git clone https://github.com/weixiaocan/ai-information-radar.git
cd ai-information-radar
conda create -n ai-radar python=3.11 -y
D:\anaconda\envs\ai-radar\python.exe -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，至少需要填写这些值：

- `YOUTUBE_API_KEY`
- `DEEPSEEK_API_KEY`
- `SUPADATA_API_KEY`
- `FEISHU_WEBHOOK_URL`

首次部署完成后，注册 Windows 定时任务：

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

如果换到另一台 Windows 电脑，重复上面这套步骤即可。计划任务说明见 `taskscheduler.example.txt`。
