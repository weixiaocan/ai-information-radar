你会收到已经固定 membership 的主题，请只生成展示文案，不要改变主题成员。

要求：
- 保持 decided_themes_json 中的 theme_id 一致
- 为每个主题生成 `theme_title`、`theme_summary`
- `evidence` 最多 4 条，格式为 `{{source, excerpt, url}}`
- `theme_summary`、`excerpt` 必须是自然中文
- `evidence` 只能使用已经属于该主题成员的 builder/X 内容
- `evidence.excerpt` 只写事实句，不要再重复作者名，也不要写成“某某表示/认为/指出”

输出 JSON：
{{
  "themes": [
    {{
      "theme_id": "theme_1",
      "theme_title": "...",
      "theme_summary": "...",
      "evidence": [
        {{"source": "...", "excerpt": "...", "url": "..."}}
      ]
    }}
  ]
}}

decided themes:
{decided_themes_json}

builder posts:
{builder_posts}

theme signals:
{theme_signals_json}
