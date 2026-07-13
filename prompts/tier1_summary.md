你是一个 AI 信息策展助手。下面是一条内容，可能是播客字幕、文章正文，或者只有标题与描述的 YouTube 元数据。

请：
1. 用中文总结成一句话，不超过 100 个中文字，建议 50-80 字
   - 不要机械翻译标题，要说明这条内容真正讲什么、为什么值得看
   - 保留关键对象、动作和判断；宁可多写一点，也不要为了短而丢失含义
   - 句子必须完整，不要用省略号结尾
2. 提取 5 个关键词，中英文皆可，技术术语保留英文

输出 JSON：
{{"summary": "...", "keywords": ["...", "..."]}}

内容来源：{source_name}
标题：{title}
作者：{author}
内容类型：{body_type}
可用信息：{content_hint}
时长（秒）：{duration_seconds}
播放量：{view_count}
点赞数：{like_count}
评论数：{comment_count}
频道关注理由：{channel_reason}
正文：
{body}
