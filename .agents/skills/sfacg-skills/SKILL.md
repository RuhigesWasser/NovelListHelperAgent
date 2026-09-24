---
name: sfacg-skills
description: 使用书名搜索菠萝包候选，或按书籍 ID、链接读取官方元数据，供小说书单核对。
---

# 菠萝包查询

只有书名时先搜索，有链接时直接读取详情。相近书名不能直接视为同一本书；应同时核对作者。

```text
python .agents/skills/sfacg-skills/scripts/search_novel.py "书名" --page 0
python .agents/skills/sfacg-skills/scripts/fetch_novel_fields.py 小说ID
```

脚本返回 JSON。没有命中、请求失败与可用结果分开处理；不要从错误提示中猜测书籍资料。需要统一处理番茄或 ESJ 时调用 `.agents/scripts/agent.py` 提供的 search_books、book_detail。

字段与接口见 [references/api.md](references/api.md)。归档格式由 ../../AGENT.md 规定。
