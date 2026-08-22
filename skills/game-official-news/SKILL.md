---
name: game-official-news
description: 查询原神、崩坏：星穹铁道和绝区零米游社官方公告、资讯、活动与社区地图。
metadata:
  emoji: 🎮
  category: game
  priority: 6
---

# 游戏官方资讯

## 工作流

1. 根据用户提到的游戏传入 `ys`、`sr` 或 `zzz` 调用 `search_game_official(game, limit=5)`。
2. 用户未指定游戏时可以省略 `game`，工具会查询三个游戏。
3. 按公告、资讯、活动的分类阅读 `articles`，需要导航信息时使用 `community_map`。
4. 结果为空、抓取失败或包含 `websearch_fallback_required: true` 时调用 `web_search`，并说明哪些内容来自官方页面、哪些来自搜索结果。

## 回答要求

- 优先报告文章标题、链接和采集时间，不把活动、公告和资讯混为一类。
- 不凭记忆补充未出现在结果中的版本日期或活动规则。
