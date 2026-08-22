from search.game.crawl_hoyolab_wiki import parse_community_map


def test_parse_community_map_resolves_relative_urls():
    markdown = """社区地图
[酒馆](/ys/home/26)
[观测枢](https://baike.mihoyo.com/ys/strategy/)
了解我们
[关于我们](https://www.mihoyo.com/)"""

    assert parse_community_map(markdown, "https://www.miyoushe.com/ys/") == [
        {"title": "酒馆", "url": "https://www.miyoushe.com/ys/home/26"},
        {"title": "观测枢", "url": "https://baike.mihoyo.com/ys/strategy/"},
    ]
