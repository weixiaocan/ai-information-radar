You are extracting builder/X hot-pool decisions for an AI Radar daily brief.

Rules:
- Output JSON only.
- Use only facts present in the input posts.
- Decide which posts should enter the builder hot pool.
- Keep at most 10 accepted posts.
- Skip weak, generic, personal, or low-information posts.
- Prefer concrete AI/agent/build/tool/company signals.

For each accepted post output:
- `content_id`
- `source`
- `url`
- `topic_key`: a short Chinese topic key, 4-16 chars

JSON schema:
{{
  "signals": [
    {{
      "content_id": "...",
      "source": "...",
      "url": "...",
      "topic_key": "..."
    }}
  ]
}}

Builder posts ({n_posts}):
{builder_posts}
