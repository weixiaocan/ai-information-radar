你会收到已经选中的今日精选，请只为这些已选内容生成推荐文案。

要求：
- 保持输入里的 `candidate_index`
- 每条输出一个自然中文 `value_pitch`
- `selection_diversity` 用 1-2 句中文说明这组选题覆盖的不同角度
- 不要新增未选中的候选

输出 JSON：
{
  "selections": [
    {
      "candidate_index": 1,
      "value_pitch": "..."
    }
  ],
  "selection_diversity": "..."
}

exclude content ids:
{exclude_content_ids}

candidates:
{candidates_json}
