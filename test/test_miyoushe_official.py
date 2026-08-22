from search.game.crawl_hoyolab_wiki import parse_official_articles


def test_parse_official_articles_limit_and_category():
    markdown = """活动
* [活动一](/ys/article/1)
* [活动二](/ys/article/2)
公告
* [公告一](/ys/article/3)
资讯
* [资讯一](/ys/article/4)"""
    result = parse_official_articles(markdown, "https://www.miyoushe.com/ys/home/28?type=2", "活动", 1)
    assert result == [{"title": "活动一", "url": "https://www.miyoushe.com/ys/article/1"}]


def test_parse_official_articles_handles_shared_filter_navigation():
    markdown = """[![](/avatar.png)](/account)
* 活动
* 公告
* 资讯
### [公告一 08-21](/sr/article/77649746)
### [公告二 08-20](/sr/article/77649744)"""
    result = parse_official_articles(markdown, "https://www.miyoushe.com/sr/home/53?type=1", "公告", 2)
    assert len(result) == 2
    assert result[0]["url"].endswith("77649746")
