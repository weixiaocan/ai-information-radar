# AI Radar

中文 | [English](#english)

AI Radar 是一个本地优先的 AI 信息雷达，用来每天筛选“今天最值得看什么”，而不是把所有内容重写成替代品。它会抓取 YouTube、RSS 和 Zara feed，生成日报与周报，并通过飞书推送。

## 中文

### 项目简介

每天 AI 内容很多，但真正值得看的通常只有少数几条。AI Radar 的目标不是做一个“AI 内容归档器”，而是做一个有明确层级的推荐系统：

- `今日热议`：优先看 builder / X 上有没有形成真实讨论主题
- `今日精选`：从播客、视频、文章里挑出最值得看的 5 条
- `补充候选`：轻量展示进过候选池但没进最终推荐的内容
- `周报`：总结一周重要主题，并给出最值得亲自看的 Top 2 长视频

### 当前能力

- 抓取 YouTube channels、RSS feeds、Zara feed
- 统一归一化为 `ContentItem`
- Tier 1 轻摘要：给所有内容生成一句话摘要和关键词
- 日报两阶段推荐：
  - 先构建显式候选池
  - 再做热议 / 精选最终入选
- 周报两层输出：
  - `本周重要主题`
  - `本周最值得亲自看的内容`
- 飞书卡片推送
- Windows Task Scheduler 本地调度

### 日报逻辑

日报不是“直接让模型写一篇日报”，而是拆成几步：

1. `ingest`
   抓取当天所有内容
2. `tier1`
   为所有内容生成基础摘要
3. `daily-curate`
   先建立候选池：
   - `builder_hot_candidates`
   - `editorial_candidates`
   
   再做最终入选：
   - `今日热议`
   - `今日精选`
   - `补充候选`
4. `daily`
   只读取结构化结果并渲染推送

### 周报逻辑

周报分成两层：

- `本周重要主题`
  从一周的归一化内容里总结主题
- `本周最值得亲自看的内容`
  只从完成 Tier 2 打分的 YouTube 内容里选 Top 2

### 技术默认设置

- LLM provider: `DeepSeek API`
- Runtime: `Windows local machine`
- Scheduler: `Windows Task Scheduler`
- Delivery: `Feishu webhook`
- Storage: local filesystem + JSON/JSONL

### 项目结构

- `src/`: 主逻辑
- `config/`: 静态配置
- `prompts/`: prompt 模板
- `tests/`: 单元测试
- `transcripts/`: 归一化内容存储，按 `YYYY-MM-DD/source_type/` 组织
- `state/`: 运行状态、候选池、主题、精选结果
- `reports/`: 日报 / 周报 markdown 归档

### 快速开始

1. 创建 Python 3.11 环境
2. 安装依赖
3. 复制 `.env.example` 为 `.env`
4. 填入 API keys 和 Feishu webhook
5. 运行以下命令

```bash
python main.py --task ingest
python main.py --task tier1
python main.py --task daily-curate
python main.py --task daily --deliver
python main.py --task tier2
python main.py --task weekly --deliver
```

### 常用命令

```bash
python main.py --task ingest
python main.py --task tier1
python main.py --task daily-curate
python main.py --task daily --deliver
python main.py --task tier2
python main.py --task weekly --deliver
```

### 推荐调度

- Daily `07:00`: `ingest`
- Daily `07:30`: `tier1`
- Daily `07:50`: `daily-curate`
- Daily `08:00`: `daily --deliver`
- Sunday `11:00`: `tier2`
- Sunday `12:00`: `weekly --deliver`

### 换电脑使用

在另一台电脑上使用时：

```bash
git clone https://github.com/weixiaocan/ai-information-radar.git
cd ai-information-radar
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

然后把你自己的：

- DeepSeek API key
- Feishu webhook
- 其他本地配置

写进 `.env` 即可。

### 公开仓库说明

以下内容不上传到 GitHub：

- 产品 PRD 文档
- `.env`
- `state/`
- `transcripts/`
- `reports/`

公开仓库保留的是代码、配置模板、prompt、测试和文档，不包含你的私有运行数据。

---

## English

AI Radar is a local-first AI information radar for deciding what is actually worth reading or watching each day. It aggregates YouTube, RSS, and Zara feeds, builds daily and weekly digests, and delivers them to Feishu.

### Overview

AI content volume is high, but the number of truly worthwhile items is usually small. AI Radar is not intended to be a passive archive. It is designed as a layered recommendation system:

- `Daily Hot Discussion`: detect whether builder / X posts form real discussion themes
- `Daily Picks`: choose the top 5 pieces from videos, podcasts, and articles
- `Supplementary Candidates`: lightly expose worthwhile candidates that did not make the final picks
- `Weekly Digest`: summarize the week’s important themes and recommend the top 2 long-form videos worth watching directly

### Current capabilities

- Ingest YouTube channels, RSS feeds, and Zara feeds
- Normalize everything into a shared `ContentItem`
- Tier 1 lightweight summarization for all content
- Two-stage daily curation:
  - build explicit candidate pools first
  - then choose final hot items and featured picks
- Two-layer weekly digest:
  - `Important Themes of the Week`
  - `Top 2 Worth Watching Yourself`
- Feishu card delivery
- Local scheduling via Windows Task Scheduler

### Daily logic

The daily digest is not generated as one monolithic AI-written report. It is split into stages:

1. `ingest`
   fetch all new content
2. `tier1`
   generate lightweight summaries for all items
3. `daily-curate`
   build candidate pools first:
   - `builder_hot_candidates`
   - `editorial_candidates`
   
   then select final outputs:
   - `Daily Hot Discussion`
   - `Daily Picks`
   - `Supplementary Candidates`
4. `daily`
   render and deliver from structured outputs only

### Weekly logic

The weekly digest has two layers:

- `Important Themes of the Week`
  generated from the normalized weekly content set
- `Top 2 Worth Watching Yourself`
  selected only from YouTube items that completed Tier 2 scoring

### Technical defaults

- LLM provider: `DeepSeek API`
- Runtime: `Windows local machine`
- Scheduler: `Windows Task Scheduler`
- Delivery: `Feishu webhook`
- Storage: local filesystem + JSON/JSONL state

### Project layout

- `src/`: implementation
- `config/`: static configuration
- `prompts/`: prompt templates
- `tests/`: unit tests
- `transcripts/`: normalized content store, organized by `YYYY-MM-DD/source_type/`
- `state/`: runtime state, candidates, themes, and selections
- `reports/`: archived markdown outputs

### Quick start

1. Create a Python 3.11 environment
2. Install dependencies
3. Copy `.env.example` to `.env`
4. Fill in API keys and Feishu webhook
5. Run:

```bash
python main.py --task ingest
python main.py --task tier1
python main.py --task daily-curate
python main.py --task daily --deliver
python main.py --task tier2
python main.py --task weekly --deliver
```

### Common commands

```bash
python main.py --task ingest
python main.py --task tier1
python main.py --task daily-curate
python main.py --task daily --deliver
python main.py --task tier2
python main.py --task weekly --deliver
```

### Suggested schedule

- Daily `07:00`: `ingest`
- Daily `07:30`: `tier1`
- Daily `07:50`: `daily-curate`
- Daily `08:00`: `daily --deliver`
- Sunday `11:00`: `tier2`
- Sunday `12:00`: `weekly --deliver`

### Using it on another machine

```bash
git clone https://github.com/weixiaocan/ai-information-radar.git
cd ai-information-radar
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then fill in your own:

- DeepSeek API key
- Feishu webhook
- any other local configuration

### Public repo notes

The public GitHub repo should not include:

- product PRD documents
- `.env`
- `state/`
- `transcripts/`
- `reports/`

The public repository contains code, config templates, prompts, tests, and documentation, but not private runtime data.
