import re
import time
import random
import json
import requests
import os
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from typing import List
from anime.retry_handler import retry_with_backoff, circuit_breaker

# 数据保存路径
_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "anime", "bangumi"))
os.makedirs(_DATA_DIR, exist_ok=True)

# 禁用 SSL 警告（证书过期）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 全局配置 ====================
BASE_URL = "https://bangumi.lol"
TIMEOUT = 15
RETRY_TIMES = 3
MIN_SLEEP = 0.8
MAX_SLEEP = 1.5

# 全局 Session 复用，统一重试策略（复用 novels/crawl_novel.py 模式）
SESSION = requests.Session()
SESSION.keep_alive = False
SESSION.verify = False  # bangumi.tv SSL 证书过期

retry_strategy = Retry(
    total=RETRY_TIMES,
    status_forcelist=[500, 502, 503, 504, 403, 429],
    redirect=3,
    backoff_factor=1,
)
adapter = HTTPAdapter(max_retries=retry_strategy)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Referer": f"{BASE_URL}/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome 120.0.0.0 Safari/537.36",
}


# ==================== 搜索 ====================

def search_bangumi(keyword: str, top_n: int = 10) -> List[dict]:
    """搜索番剧，返回前 N 条结果。

    URL 编码规则：中文 → UTF-8 百分号编码，空格 → ``+``。
    使用 ``urllib.parse.quote_plus`` 自动处理。

    Args:
        keyword: 搜索关键词，如 ``"无职转生 第3期"``
        top_n:  返回结果数，默认 10

    Returns:
        [{"id": 序号, "title": 标题, "url": 链接, "info": 简介}, ...]
    """
    import urllib.parse

    time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))
    results: List[dict] = []

    # URL 编码（空格 → +，中文 → %XX）
    encoded = urllib.parse.quote_plus(keyword)
    search_url = f"{BASE_URL}/subject_search/{encoded}?cat=all"

    # 熔断检查
    cb = circuit_breaker("bangumi")
    if not cb.is_available():
        print(f"[bangumi] 熔断器 OPEN，拒绝搜索请求")
        return results

    try:
        resp = SESSION.get(search_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        cb.record_success()
        soup = BeautifulSoup(resp.content, "lxml")

        # 搜索结果容器: ul#browserItemList > li.item
        items = soup.select("#browserItemList > li.item")
        if not items:
            items = soup.select("#browserItemList li")
        if not items:
            print("[bangumi] 未找到搜索结果")
            return results

        print(f"[bangumi] 搜索 '{keyword}' → 找到 {len(items)} 个条目")

        count = 0
        for item in items:
            if count >= top_n:
                break

            inner = item.select_one("div.inner")
            if not inner:
                continue

            # 标题: h3 a.l
            title_a = inner.select_one("h3 a.l")
            title_cn = title_a.get_text(strip=True) if title_a else ""

            # 日文标题: h3 small.grey
            title_jp = ""
            h3 = inner.select_one("h3")
            if h3:
                jp_el = h3.select_one("small.grey")
                title_jp = jp_el.get_text(strip=True) if jp_el else ""

            # 链接
            href = title_a.get("href", "") if title_a else ""
            if href and not href.startswith("http"):
                href = BASE_URL + href

            if not title_cn:
                continue

            # 简介/放送信息: p.info.tip
            info_el = inner.select_one("p.info.tip")
            info = info_el.get_text(strip=True) if info_el else ""

            # 评分: p.rateInfo small.fade
            rating_el = inner.select_one("p.rateInfo small.fade")
            rating = rating_el.get_text(strip=True) if rating_el else ""

            # 评分人数: p.rateInfo span.tip_j
            score_count_el = inner.select_one("p.rateInfo span.tip_j")
            score_count = score_count_el.get_text(strip=True) if score_count_el else ""

            # 排名: span.rank
            rank_el = inner.select_one("span.rank")
            rank = rank_el.get_text(strip=True) if rank_el else ""

            count += 1
            results.append({
                "id": count,
                "title_cn": title_cn,
                "title_jp": title_jp,
                "url": href,
                "info": info,
                "rating": rating,
                "score_count": score_count,
                "rank": rank,
            })

        return results

    except Exception as e:
        cb.record_failure()
        print(f"[bangumi] 搜索失败: {e}，熔断状态={cb.status()}")
        return results


# ==================== 详情页爬取（占位，等格式确定后补充） ====================

def crawl_subject(subject_url: str, title_cn: str = "", title_jp: str = "") -> dict | None:
    """爬取单个番剧详情页。

    提取：章节列表（中/日文标题）、日文简介、标签 Top5。

    Args:
        subject_url: 如 ``"/subject/501963"`` 或完整 URL
        title_cn:    搜索得到的中文标题（页面通常不直接提供）
        title_jp:    搜索得到的日文标题

    Returns:
        Ordered dict，字段顺序: title_cn, title_jp, url, rating, rank,
        rating_desc, tags, summary_jp, episodes, characters
    """

    if subject_url.startswith("/"):
        subject_url = BASE_URL + subject_url

    time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))

    # 熔断检查
    cb = circuit_breaker("bangumi")
    if not cb.is_available():
        print(f"[bangumi] 熔断器 OPEN，拒绝详情请求")
        return None

    try:
        resp = SESSION.get(subject_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        cb.record_success()
        soup = BeautifulSoup(resp.content, "lxml")

        result: dict = {}

        # 标题：从页面 ul#infobox 提取 "中文名" 和 "日文名"
        if not title_cn:
            for li in soup.select("ul#infobox li"):
                tip = li.select_one("span.tip")
                if tip and "中文名" in tip.get_text():
                    # 取 span 之后的文本（即中文名本身）
                    title_cn = list(li.stripped_strings)[-1] if list(li.stripped_strings) else ""
                    break
        if not title_jp:
            # 从封面图 title 属性提取日文名（格式: "日文名 中文名"）
            cover_link = soup.select_one("a.thickbox.cover")
            if cover_link:
                cover_title = cover_link.get("title", "")
                if cover_title:
                    # 日文名在前，中文名在后，用空格分隔
                    parts = cover_title.rsplit(" ", 1)
                    title_jp = parts[0].strip() if len(parts) > 1 else cover_title.strip()
        if not title_cn:
            m = re.search(r'/subject/(\d+)', subject_url)
            title_cn = f"subject_{m.group(1)}" if m else "anime_detail"

        result["title_cn"] = title_cn
        result["title_jp"] = title_jp
        result["url"] = subject_url

        # ---- 评分 ----
        score_el = soup.select_one("span.number[property='v:average']")
        rank_el = soup.select_one("small.alarm")
        desc_el = soup.select_one("span.description")
        result["stats"] = {
            "rating": score_el.get_text(strip=True) if score_el else "",
            "rank": rank_el.get_text(strip=True) if rank_el else "",
            "rating_desc": desc_el.get_text(strip=True) if desc_el else "",
        }

        # ---- 标签（取人数最多的 5 个） ----
        tags: list[dict] = []
        tag_section = soup.select_one("div.subject_tag_section div.inner")
        if tag_section:
            for a_tag in tag_section.find_all("a"):
                span = a_tag.select_one("span")
                small = a_tag.select_one("small.grey")
                if span and small:
                    name = span.get_text(strip=True)
                    count = int(small.get_text(strip=True))
                    tags.append({"name": name, "count": count})
            tags.sort(key=lambda t: t["count"], reverse=True)
            tags = tags[:5]
        result["tags"] = tags
        print(f"[bangumi] 标签 top5: {[t['name'] for t in tags]}")

        # ---- 日文简介（保留换行） ----
        summary_el = soup.select_one("div#subject_summary")
        summary_jp = ""
        if summary_el:
            lines: list[str] = []
            for child in summary_el.descendants:
                if child.name == "br":
                    lines.append("\n")
                elif isinstance(child, str):
                    lines.append(child)
            summary_jp = "".join(lines).strip()
        result["summary_jp"] = summary_jp
        print(f"[bangumi] 简介: {len(summary_jp)} 字")

        # ---- 章节列表 ----
        episodes: list[dict] = []
        ep_links = soup.select("ul.prg_list li a")
        for a_tag in ep_links:
            ep_num = a_tag.get_text(strip=True)
            title_raw = a_tag.get("title", "")
            title_jp = re.sub(r'^ep\.\d+\s*', '', title_raw).strip()

            ep_id = a_tag.get("id", "")
            title_cn = ""
            air_date = ""
            if ep_id:
                popup = soup.select_one(f"div#prginfo_{ep_id.replace('prg_', '')}")
                if popup:
                    popup_html = str(popup)
                    cn_match = re.search(r'中文标题:\s*(.+?)(?:<br|$)', popup_html)
                    if cn_match:
                        title_cn = cn_match.group(1).strip()
                    date_match = re.search(r'首播:\s*(\d{4}-\d{2}-\d{2})', popup_html)
                    if date_match:
                        air_date = date_match.group(1)

            episodes.append({
                "ep": int(ep_num) if ep_num.isdigit() else ep_num,
                "title_cn": title_cn,
                "title_jp": title_jp,
                "air_date": air_date,
            })

        result["episodes"] = episodes
        print(f"[bangumi] 章节: {len(episodes)} 话")

        # ---- 角色列表 ----
        characters: list[dict] = []
        cast_list = soup.select("ul.castTypeFilterList li.item")
        if not cast_list:
            cast_list = soup.select("#browserItemList.castTypeFilterList li.item")
        for li in cast_list:
            thumb = li.select_one("a.thumbTip")
            name_cn = thumb.get("title", "") if thumb else ""

            title_a = li.select_one("p.title a.title")
            name_jp = title_a.get_text(strip=True) if title_a else ""

            job_el = li.select_one("span.badge_job_tip")
            role = job_el.get_text(strip=True) if job_el else ""

            cv_el = li.select_one("p.badge_actor a")
            cv = cv_el.get_text(strip=True) if cv_el else ""

            char_url = title_a.get("href", "") if title_a else ""
            if char_url and not char_url.startswith("http"):
                char_url = BASE_URL + char_url

            characters.append({
                "name_cn": name_cn,
                "name_jp": name_jp,
                "role": role,
                "cv": cv,
                "url": char_url,
            })

        result["characters"] = characters
        print(f"[bangumi] 角色: {len(characters)} 人")

        # 自动保存详情（用 result 中的 title_cn，确保经过页面提取）
        try:
            safe_name = re.sub(r'[\\/:*?"<>|]', '', result.get("title_cn", "") or "anime")[:50].strip()
            if not safe_name:
                safe_name = "anime_detail"
            save_path = os.path.join(_DATA_DIR, f"{safe_name}.json")
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"[bangumi] 详情已保存: {save_path}")
        except Exception as e:
            print(f"[bangumi] 详情保存失败: {e}")

        return result

    except Exception as e:
        cb.record_failure()
        print(f"[bangumi] 详情页爬取失败: {e}，熔断状态={cb.status()}")
        return None


# ==================== 对外接口 ====================

def search_anime(keyword: str) -> List[dict]:
    """搜索番剧，打印并返回结果列表。

    Args:
        keyword: 搜索关键词

    Returns:
        搜索结果列表，每项含 id/title_cn/title_jp/url/info/rating/...
    """
    results = search_bangumi(keyword, top_n=10)
    if not results:
        print(f"\n未找到 '{keyword}' 的搜索结果。")
        return []

    print(f"\n搜索 '{keyword}' 结果（共 {len(results)} 条）:\n")
    for r in results:
        print(f"  {r['id']:2}. {r['title_cn']}")
        if r["title_jp"]:
            print(f"      {r['title_jp']}")
        if r["info"]:
            print(f"      {r['info'][:100]}")
        extras = []
        if r["rating"]:
            extras.append(f"评分: {r['rating']}")
        if r["score_count"]:
            extras.append(r["score_count"])
        if r["rank"]:
            extras.append(r["rank"])
        if extras:
            print(f"      {' | '.join(extras)}")
        print(f"      {r['url']}")
    return results


def fetch_anime(result_item: dict) -> str:
    """根据搜索结果中的条目爬取详情，保存为 JSON。

    Args:
        result_item: ``search_anime`` 返回列表中的单个条目

    Returns:
        JSON 文件路径，失败返回空字符串
    """
    print(f"\n已选择: {result_item['title_cn']}")
    print(f"链接: {result_item['url']}")
    detail = crawl_subject(
        result_item["url"],
        title_cn=result_item["title_cn"],
        title_jp=result_item["title_jp"],
    )
    if not detail:
        return ""

    safe_name = re.sub(r'[\\/:*?"<>|]', '', result_item["title_cn"]).strip()
    output_path = os.path.join(os.path.dirname(__file__), f"{safe_name}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2)
    print(f"已保存: {output_path}")
    return output_path


# ==================== 测试入口 ====================
if __name__ == "__main__":
    keyword = input("请输入搜索关键词: ").strip()
    if not keyword:
        keyword = "无职转生 第3期"

    results = search_anime(keyword)

    if results:
        print()
        c = input("输入编号查看详情（0=退出）: ").strip()
        if c.isdigit() and 1 <= int(c) <= len(results):
            fetch_anime(results[int(c) - 1])
