---
name: season-overview
description: >
  季度新番总览。当用户想看"本季新番"、"2026年7月新番"、"这个季度有什么番"、
  "新番推荐"时触发。调用 get_season_anime 获取整季数据并分类整理展示。
metadata:
  emoji: 📺
  category: anime
  priority: 7
  output_schema: season_overview
---

# 季度新番总览

## 触发条件
- 用户说"本季新番"、"这个季度有什么"、"X年X月新番"
- 用户想看"全部新番"而非特定类型推荐
- 用户问"最近在播什么"

## 执行步骤
1. 确定季度：
   - 用户指定了年份/月份 → 构造 season_url（如用户说"2026年7月" → `https://yuc.wiki/202607/`）
   - 用户说"本季"/"最近" → 使用当前年月构造 URL
2. 调 `get_season_anime(season_url=url)` 获取该季度全部新番数据
3. 分析返回数据：收录总数、各类型（TV/剧场版/OVA/SP）数量
4. 按评分降序排列，选取 Top 10 展示
5. 标注值得关注的高分作品和热门续作

## 输出格式
- 开头：季度概况（"2026年7月新番共收录 XX 部，TV动画 YY 部..."）
- 正片：表格或列表展示 Top 10
  - 排名 | 中文名 | 类型 | 评分 | 放送日期 | 一句话看点
- 结尾：可追问"想看哪部的详细介绍？"

## 注意事项
- 数据必须来自 get_season_anime 的返回结果
- 评分列空的标注"暂无评分"
- 如果 yuc.wiki 无该季度数据，尝试用 search_anime 搜索代替
