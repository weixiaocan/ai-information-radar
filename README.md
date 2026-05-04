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

## 输出示例

<p align="center">
  <img src="docs/images/daily_digest.png" alt="AI Radar daily digest screenshot" width="820" />
</p>

## 目录结构

- `src/`：代码
- `config/`：来源配置
- `prompts/`：提示词
- `transcripts/`：标准化内容仓
- `state/`：运行状态、候选池、主题、选择结果
- `reports/`：日报 / 周报归档
