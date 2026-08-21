import time
import random
import requests
import os
import re
import urllib3
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from typing import List
from search.anime.retry_handler import circuit_breaker
from utils.path_tool import get_project_path

# 禁用 SSL 警告（yuc.wiki 证书过期）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 全局配置 ====================
BASE_URL = "https://yuc.wiki"
TIMEOUT = 15
RETRY_TIMES = 3
MIN_SLEEP = 0.8
MAX_SLEEP = 1.5

# 全局 Session 复用，统一重试策略（复用 search/novel/crawl_novel.py 模式）
SESSION = requests.Session()
SESSION.keep_alive = False
SESSION.verify = False  # yuc.wiki SSL 证书过期

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


def get_season_links_from_index() -> List[str]:
    """
    从 yuc.wiki 首页抓取【所有季度新番链接】
    匹配格式：/202601/ /202604/ /202607/ /202510/ ...
    返回完整链接列表：["https://yuc.wiki/202607/", ...]
    """
    time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))

    # 熔断检查
    cb = circuit_breaker("yuc")
    if not cb.is_available():
        print(f"[yuc] 熔断器 OPEN，拒绝请求")
        return []

    try:
        resp = SESSION.get(BASE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        cb.record_success()
        soup = BeautifulSoup(resp.content, "lxml")

        season_urls = []
        # 允许的路径后缀（除季度外）
        SPECIAL_PATHS = {"/new/", "/sp/", "/movie/"}

        # 1) 优先从 td.index_season 里提取季度链接
        for td in soup.select("td.index_season"):
            a_tag = td.find("a")
            if a_tag:
                href = a_tag.get("href", "")
                # href 格式: /YYYYMM/ (如 /202601/)
                if len(href) == 8 \
                    and href.endswith("/") \
                    and href[1:5].isdigit() \
                    and 2010 <= int(href[1:5]) <= 2039 \
                    and href[5:] in ("01/", "04/", "07/", "10/"):
                    season_urls.append(BASE_URL + href)

        # 2) 兜底：遍历所有 <a> 标签（兼顾 /new//sp//movie/ 和漏网季度链接）
        for a_tag in soup.find_all("a"):
            href = a_tag.get("href", "")

            # 季度链接（href 以 / 开头）
            if len(href) == 8 \
                and href.endswith("/") \
                and href[1:5].isdigit() \
                and 2010 <= int(href[1:5]) <= 2039 \
                and href[5:] in ("01/", "04/", "07/", "10/"):
                season_urls.append(BASE_URL + href)

            # 特殊路径
            elif href in SPECIAL_PATHS:
                season_urls.append(BASE_URL + href)

        # 去重
        all_urls = list(set(season_urls))

        # 分离特殊路径和季度链接
        special_urls = [u for u in all_urls if u.endswith(("/new/", "/sp/", "/movie/"))]
        quarter_urls = [u for u in all_urls if u not in special_urls]

        # 特殊路径固定顺序: /new/ → /sp/ → /movie/
        path_order = {"/new/": 0, "/sp/": 1, "/movie/": 2}
        special_urls.sort(key=lambda u: path_order.get("/" + u.split("/")[-2] + "/", 99))

        # 季度链接降序排列（最新在前）
        quarter_urls.sort(reverse=True)

        sorted_urls = special_urls + quarter_urls
        print(f"[yuc季度链接] 共抓取到 {len(sorted_urls)} 个链接")
        return sorted_urls

    except Exception as e:
        cb.record_failure()
        print(f"[yuc爬虫] 抓取季度链接失败: {e}，熔断状态={cb.status()}")
        return []


# ==================== 单季度番剧详情爬取 ====================

def crawl_season_anime(season_url: str) -> dict:
    """爬取某个季度页面下所有番剧的详细信息。

    Returns:
        {"info": {季度, 共收录, ...}, "animes": [{...}, ...]}
    """
    time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))
    animes: List[dict] = []
    info: dict = {}

    # 熔断检查
    cb = circuit_breaker("yuc")
    if not cb.is_available():
        print(f"[yuc] 熔断器 OPEN，拒绝季度请求")
        return {"info": info, "animes": animes}

    try:
        resp = SESSION.get(season_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        cb.record_success()
        soup = BeautifulSoup(resp.content, "lxml")

        # ---- 季度概况 ----
        season_tag = re.search(r'/(\d{6})/', season_url)
        season_tag = season_tag.group(1) if season_tag else "unknown"
        info["季度"] = season_tag

        # 季度概况：先精确匹配 p.intro，不行就搜所有 <p> 含 "本期" 的
        intro_p = soup.select_one("p.intro")
        if not intro_p:
            for p in soup.find_all("p"):
                if "本期" in p.get_text():
                    intro_p = p
                    break
        if intro_p:
            intro_text = intro_p.get_text(" ", strip=True)
            # 季节名: "本期 春季档 共收录 70 部新番动画"
            season_match = re.search(r'本期\s*(\S+档)', intro_text)
            if season_match:
                info["季度"] = f"{season_tag}_{season_match.group(1)}"
            # 总收录数
            total_match = re.search(r'共收录\s*(\d+)', intro_text)
            if total_match:
                info["共收录"] = int(total_match.group(1))
            # 各类型数量: "原创动画×3 漫画改编×45 ..."
            for m in re.finditer(r'([一-龥]+改编|原创动画|其他题材改编)\s*[×xX]\s*(\d+)', intro_text):
                info[m.group(1)] = int(m.group(2))

        # ---- 番剧条目 ----
        tables = soup.select("table[width='500px']")
        print(f"[yuc爬取] 找到 {len(tables)} 个番剧条目")

        for table in tables:
            entry = _parse_anime_entry(table)
            if entry.get("title_cn"):
                animes.append(entry)

        print(f"[yuc爬取] 成功解析 {len(animes)} 部番剧")
        print(f"[yuc爬取] 季度概况: {info}")
        result = {"info": info, "animes": animes}

        # 自动保存到 data/anime/yuc/
        try:
            yuc_dir = get_project_path("data/anime/yuc")
            yuc_dir.mkdir(parents=True, exist_ok=True)
            season_tag = re.search(r'/(\d{6})/', season_url)
            tag = season_tag.group(1) if season_tag else "unknown"
            save_path = yuc_dir / f"yuc_{tag}.json"
            with save_path.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"[yuc] 已保存: {save_path}")
        except Exception as e:
            print(f"[yuc] 保存失败: {e}")

        return result

    except Exception as e:
        cb.record_failure()
        print(f"[yuc爬取] 失败: {e}，熔断状态={cb.status()}")
        return {"info": info, "animes": animes}


def _parse_staff(staff_text: str) -> dict:
    """将 staff_r 原文按 <br> 拆分为 {原作, 音乐, 动画制作}。

    处理多行值：无关键字的行视为上一字段的延续，用 ``/`` 拼接。
    如 "动画制作：Passione\\nHayabusa Film" → "Passione/Hayabusa Film"
    """
    result = {"原作": "", "音乐": "", "动画制作": ""}
    if not staff_text:
        return result

    fields = {"原作": "原作", "音乐": "音乐", "动画制作": "动画制作"}
    last_key: str | None = None

    for line in staff_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 去掉包裹的括号说明，如 "(SQEX Novel/Square Enix)"
        if line.startswith("(") and line.endswith(")"):
            continue

        matched = False
        for key, label in fields.items():
            if m := re.match(rf'{label}[：:]\s*(.+)', line):
                result[key] = m.group(1).strip()
                last_key = key
                matched = True
                break

        # 未匹配时：
        # - 含冒号 → 其他字段（导演/编剧/插画等），跳过
        # - 不含冒号 → 上一字段的延续行（如多行公司名），追加
        if not matched:
            if "：" not in line and ":" not in line:
                if last_key and result[last_key]:
                    result[last_key] += "/" + line

    return result


def _parse_anime_entry(table) -> dict | None:
    """从单个 ``<table width="500px">`` 提取番剧字段。

    字段与 HTML class 精确对应：
    - p.title_cn_r  / p.title_jp_r
    - td.type_a_r   / td.type_tag_r
    - td.staff_r
    - td.link_a_r 内 a[href] (按链接文本区分 动画官网 / PV)
    - p.broadcast_r
    """
    def _text(sel: str, default: str = "") -> str:
        el = table.select_one(sel)
        return el.get_text(strip=True) if el else default

    # type_a~e 互斥，取第一个非空值
    type_r = (
        _text("td.type_a_r") or _text("td.type_b_r") or
        _text("td.type_c_r") or _text("td.type_d_r") or _text("td.type_e_r")
    )

    # staff_r 细分——遍历子节点，<br> 视为换行
    # staff_r 兼容 r1/r2 变体
    staff_cell = (
        table.select_one("td.staff_r") or
        table.select_one("td[class^='staff_r']")
    )
    staff_lines: list[str] = []
    if staff_cell:
        for child in staff_cell.descendants:
            if child.name == "br":
                staff_lines.append("\n")
            elif isinstance(child, str):
                staff_lines.append(child)
        staff_raw = "".join(staff_lines)
        # 去掉全角空格和多余空白
        staff_raw = "\n".join(
            line.strip().replace("　", "") for line in staff_raw.split("\n") if line.strip()
        )
    else:
        staff_raw = ""
    staff_parsed = _parse_staff(staff_raw)

    # title_cn_r 兼容 r2/r3/r4… 变体
    title_cn = (
        _text("p.title_cn_r") or
        _text("p[class^='title_cn_r']")  # 匹配 title_cn_r2 等
    )
    # title_jp_r 兼容 r1/r2/r3… 变体
    title_jp = (
        _text("p.title_jp_r") or
        _text("p[class^='title_jp_r']")  # 匹配 title_jp_r1 等
    )

    # type_tag_r：<br> 视为分隔符
    type_tag = ""
    tag_cell = table.select_one("td.type_tag_r")
    if tag_cell:
        for br in tag_cell.find_all("br"):
            br.replace_with("/")
        type_tag = tag_cell.get_text(strip=True)

    entry = {
        "title_cn":      title_cn,
        "title_jp":      title_jp,
        "type":           type_r,
        "tag":            type_tag,
        "staff":          staff_parsed,
        "broadcast":      _text("p.broadcast_r"),
        "anime_official_link": "",
        "PV_link":             "",
    }

    # link_a_r 里的链接：按文本区分 "动画官网" 和 "PV"
    link_cell = table.select_one("td.link_a_r")
    if link_cell:
        for a_tag in link_cell.find_all("a"):
            href = a_tag.get("href", "")
            text = a_tag.get_text(strip=True)
            if "动画官网" in text or "公式" in text:
                entry["anime_official_link"] = href
            elif "PV" in text:
                entry["PV_link"] = href

    # broadcast_ex_r 并入 broadcast（如 "(2季度/分割)" "(年番)"）
    ex_text = _text("p.broadcast_ex_r")
    if ex_text:
        br = entry["broadcast"]
        entry["broadcast"] = f"{br} {ex_text}".strip() if br else ex_text

    return entry


def save_to_json(result: dict, season_url: str):
    """将番剧列表（含季度概况）写入 JSON 文件。"""
    anime_list = result.get("animes", [])
    if not anime_list:
        print("[yuc JSON] 无数据，跳过写入")
        return

    
    match = re.search(r'/(\d{6})/', season_url)
    season_tag = match.group(1) if match else "unknown"

    output_path = get_project_path(f"data/anime/yuc/yuc_{season_tag}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # info 在前，animes 在后
    data = {"info": result.get("info", {}), "animes": anime_list}
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[yuc JSON] 已写入: {output_path} ({len(anime_list)} 条)")


# ==================== 对外接口 ====================

def fetch_season_links() -> str:
    """获取所有季度链接，保存为 JSON 文件。

    Returns:
        输出文件路径，失败返回空字符串。
    """
    links = get_season_links_from_index()
    if not links:
        print("[yuc] 未获取到季度链接")
        return ""
    output_path = get_project_path("data/anime/yuc/yuc_wiki.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=2)
    print(f"[yuc] 季度链接已写入: {output_path} ({len(links)} 条)")
    return str(output_path)


def fetch_season_anime(season_url: str) -> str:
    """爬取指定季度番剧详情，保存为 JSON 文件。

    Args:
        season_url: 如 ``"https://yuc.wiki/202607/"``

    Returns:
        输出文件路径，失败返回空字符串。
    """
    result = crawl_season_anime(season_url)
    animes = result.get("animes", [])
    if not animes:
        print("[yuc] 未获取到番剧数据")
        return ""
    for a in animes[:3]:
        print(f"  {a.get('title_cn', '?')[:30]} | {a.get('type', '?')}")
    save_to_json(result, season_url)

    match = re.search(r'/(\d{6})/', season_url)
    tag = match.group(1) if match else "unknown"
    return str(get_project_path(f"data/anime/yuc/yuc_{tag}.json"))


# ==================== 测试入口 ====================
if __name__ == "__main__":
    # 测试1: 获取季度链接
    # fetch_season_links()

    # # 测试2: 爬取 202607 季度番剧
    fetch_season_anime("https://yuc.wiki/202607/")
