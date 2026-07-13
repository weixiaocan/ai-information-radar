你会收到已经选中的今日精选，请只为这些已选内容生成推荐文案。

要求：
- 保持输入里的 `candidate_index`
- 每条输出一个自然中文 `value_pitch`，不超过 100 个中文字，建议 50-80 字
- `value_pitch` 要说明“为什么值得看”或“读者能获得什么”，不要机械翻译标题
- 句子必须完整，不要用省略号结尾
- `selection_diversity` 用 1-2 句中文说明这组选题覆盖的不同角度
- 不要新增未选中的候选

输出 JSON：
{{
  "selections": [
    {{
      "candidate_index": 1,
      "value_pitch": "..."
    }}
  ],
  "selection_diversity": "..."
}}

exclude content ids:
{exclude_content_ids}

candidates:
{candidates_json}
