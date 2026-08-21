# 游戏资料采集说明

`crawl_hoyolab_wiki.py` 仅采集无需登录的公开页面元数据、JSON-LD 和链接，不绕过访问限制。

示例：

```powershell
python -m search.game.crawl_hoyolab_wiki
```

推荐来源：官方 Wiki、官方公告页、Steam Web API/商店公开页、IGDB（需自行申请免费 API Key）。

请遵守各站点 robots.txt、服务条款和版权规则；不要批量镜像或采集用户私密内容。
