---
name: search-novel
description: 搜索起点中文网小说并获取指定作品的最新详情，适用于小说名称、作者、分类和最新章节查询。
metadata:
  emoji: 📚
  category: novel
  priority: 6
---

# 小说搜索

## 工作流

1. 用户只提供书名或作者关键词时，调用 `search_novel(keyword, limit=10)`。
2. 从结果中选择与用户问题最匹配的 `url`，再调用 `fetch_novel(book_url)` 获取作者、简介、标签、最新章节和推荐数据。
3. 不下载小说正文；只有用户明确要求离线阅读时，才使用独立的 `download_novel` 工具。
4. 搜索失败、结果为空或数据过期时调用 `web_search` 兜底，并标明来源和不确定性。

## 回答要求

- 不把搜索摘要当作完整详情；具体作品问题优先完成两步查询。
- 保留来源 URL，不臆造更新时间、章节或评分。
