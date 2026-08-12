"""
crawl_novel.py 适配 https://www.biquga.com 笔趣阁
修复：搜索表单参数s、正确域名、搜索结果xpath、网络异常捕获
支持关键词搜索、全本爬取txt
"""
import sys
import re
import base64
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from lxml import etree
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ===================== 常量配置 =====================
BASE_URL = "https://www.biquga.com"
SEARCH_PATH = "/search.html"
THREAD_POOL_MAX_WORKERS = 10
SUCCESS_SLEEP = 0.5
FAIL_SLEEP = 3
TIMEOUT = 15
RETRY_TIMES = 3
# ====================================================

# 全局Session复用，减少握手、统一重试
SESSION = requests.Session()
SESSION.keep_alive = False

# 网络重试策略：服务器错误、访问限制自动重试
retry_strategy = Retry(
    total=RETRY_TIMES,
    status_forcelist=[500, 502, 503, 504, 403, 429],
    redirect=3,
    backoff_factor=1
)
adapter = HTTPAdapter(max_retries=retry_strategy)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)

# 模拟浏览器请求头，降低风控拦截
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Referer": f"{BASE_URL}/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome 120.0.0.0 Safari/537.36"
}


def get_xpath_resp(url: str):
    """通用GET请求，返回解析树+响应，捕获网络异常"""
    try:
        resp = SESSION.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "utf-8"
        tree = etree.HTML(resp.text)
        return tree, resp
    except Exception as e:
        print(f"网络访问失败：{str(e)}")
        return None, None


def get_search(keyword: str) -> list:
    """
    搜索核心修复：POST /search.html，表单参数name="s"
    """
    full_search_url = BASE_URL + SEARCH_PATH
    post_data = {"s": keyword}
    try:
        resp = SESSION.post(full_search_url, data=post_data, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"访问搜索页面失败：{e}")
        sys.exit(1)
    tree = etree.HTML(resp.text)

    # biquga 搜索结果实际结构：
    # <ul class="txt-list txt-list-row5"> → <li> → <span class="s1~s5">
    # s1=类型, s2=书名+链接, s3=作者, s4=最新章节, s5=日期
    book_items = tree.xpath('//ul[contains(@class, "txt-list-row5")]/li')
    if not book_items:
        print("❌ 未匹配到任何小说，请更换关键词重试！")
        sys.exit(1)

    print("✅ 搜索成功，仅展示第一页结果：")
    print(f"|{'序号':^4}|{'书名':^26}|{'作者':^12}|{'最新章节':^22}|")
    res_list = [{"article": "书名", "url": ""}]
    idx = 0
    for item in book_items:
        # 书名 + 链接 (span.s2 > a)
        title_a = item.xpath('.//span[@class="s2"]/a')
        if not title_a:
            continue
        book_name = title_a[0].text.strip() if title_a[0].text else "未知书名"
        book_href = title_a[0].attrib.get("href", "")
        # 作者 (span.s3 > a)
        author_ele = item.xpath('.//span[@class="s3"]/a/text()')
        author = author_ele[0].strip() if author_ele else "未知"
        # 最新章节 (span.s4 > a)
        update_ele = item.xpath('.//span[@class="s4"]/a/text()')
        update_text = update_ele[0].strip() if update_ele else "无"
        idx += 1
        full_book_url = BASE_URL + book_href
        res_list.append({"article": book_name, "url": full_book_url})
        print(f"|{idx:^4}|{book_name:^26}|{author:^12}|{update_text:^22}|")
    return res_list


def get_book_info(book_url: str):
    """
    获取小说基础信息 + 第一章链接
    """
    tree, resp = get_xpath_resp(book_url)
    if tree is None:
        raise Exception("小说主页无法访问")

    # --- 书名 ---
    novel_name = tree.xpath('//div[@class="detail-box"]//h1/text()')
    if not novel_name:
        raise Exception("小说信息解析失败，页面结构变更")
    novel = novel_name[0].strip()

    # --- 作者 ---
    author_ele = tree.xpath('//p[@class="p_author"]/a/text()')
    author = author_ele[0].strip() if author_ele else "未知作者"

    # --- 简介 ---
    desc_ele = tree.xpath('//div[@class="detail-box"]//div[contains(@class, "desc")]/text()')
    intro = "\n".join([d.strip() for d in desc_ele]) if desc_ele else "暂无简介"

    # --- 找第一章链接 ---
    # 优先用「开始阅读」按钮，其次用 fix section-list 的第一章
    first_chapter_url = ""
    start_read = tree.xpath('//a[contains(text(), "开始阅读")]/@href')
    if start_read:
        first_chapter_url = start_read[0]
    else:
        # 回退：从 fix section-list（正文章节列表）取第一个
        for a in tree.xpath('//ul[@class="fix section-list"]/li/a[@href]'):
            href = a.attrib.get("href", "")
            if href:
                first_chapter_url = href
                break

    if not first_chapter_url:
        raise Exception("未找到第一章链接")

    if not first_chapter_url.startswith("http"):
        first_chapter_url = BASE_URL + first_chapter_url

    return novel, author, intro, first_chapter_url


def _follow_subpages(start_url: str):
    """从当前页沿 kkehvov 收集所有续页URL（_1 _2 等），直到下一章或末尾"""
    sub_urls = []
    url = start_url
    seen = set()
    while url and url not in seen:
        seen.add(url)
        tree, resp = get_xpath_resp(url)
        if tree is None:
            break
        m = re.search(r"var\s+kkehvov\s*=\s*'([^']+)'", resp.text)
        next_url = m.group(1).strip() if m else ""
        is_next_sub = bool(re.search(r'_\d+\.html', next_url)) if next_url else False
        if next_url and is_next_sub:
            if not next_url.startswith("http"):
                next_url = (BASE_URL + next_url) if next_url.startswith("/") else (BASE_URL + "/" + next_url)
            sub_urls.append(next_url)
            url = next_url
            time.sleep(0.15)
        else:
            break
    return sub_urls


def _validate_chapter(url: str):
    """验证单个章节URL，返回 (title, [main_url, sub_urls...]) 或 None"""
    try:
        time.sleep(0.2)  # 限速：避免并发请求太快被服务器拒绝
        tree, resp = get_xpath_resp(url)
        if tree is None:
            return None
        h3_match = re.search(r'<h3>([^<]+)</h3>', resp.text)
        if not h3_match:
            return None
        title = re.sub(r'（第\d+页）$', '', h3_match.group(1).strip())
        sub_urls = _follow_subpages(url)
        return (title, [url] + sub_urls)
    except Exception:
        return None


def _chain_follow_one(url: str):
    """链式跟踪一个章节页，返回 (title, [urls], next_url, chapter_id) 或 None"""
    tree, resp = get_xpath_resp(url)
    if tree is None:
        return None
    h3_match = re.search(r'<h3>([^<]+)</h3>', resp.text)
    if not h3_match:
        return None
    title = re.sub(r'（第\d+页）$', '', h3_match.group(1).strip())
    m = re.search(r"var\s+kkehvov\s*=\s*'([^']+)'", resp.text)
    next_url = m.group(1).strip() if m else ""
    if next_url and not next_url.startswith("http"):
        next_url = (BASE_URL + next_url) if next_url.startswith("/") else (BASE_URL + "/" + next_url)
    sub_urls = _follow_subpages(url)
    cid_match = re.search(r'/(\d+)\.html$', url)
    cid = int(cid_match.group(1)) if cid_match else 0
    return (title, [url] + sub_urls, next_url, cid)


def _chain_to_next_chapter(url: str, max_hops: int = 20):
    """
    从当前章沿 kkehvov 链跳转，跳过所有续页（_N.html），
    直到找到下一章的非续页URL。防止被多页章节卡住。
    返回: (title, [urls], chapter_id) 或 None
    """
    current = url
    for _ in range(max_hops):
        tree, resp = get_xpath_resp(current)
        if tree is None:
            return None
        m = re.search(r"var\s+kkehvov\s*=\s*'([^']+)'", resp.text)
        next_url = m.group(1).strip() if m else ""
        if not next_url:
            return None
        if not next_url.startswith("http"):
            next_url = (BASE_URL + next_url) if next_url.startswith("/") else (BASE_URL + "/" + next_url)

        is_sub = bool(re.search(r'_\d+\.html$', next_url))
        if is_sub:
            current = next_url
            time.sleep(0.15)
            continue  # 跳过续页

        # 非续页 = 真正的下一章
        result = _chain_follow_one(next_url)
        if result:
            return (result[0], result[1], result[3])
        return None

    return None  # 超过最大跳数


def discover_chapters_generator(first_url: str):
    """
    生成器：gap 试探（step=1 连续扫描） + 链式兜底
    - 每轮从 last_id 往后扫描一段连续 ID，并行验证，命中率极高
    - 遇到大间隙（连续多个 ID 无效）→ 链式跳过续页到下一章 → 继续扫描
    yield: [(title, [page1_url, page2_url, ...]), ...]
    """
    BATCH_SIZE = 100
    SCAN_RANGE = 150   # 每轮扫描的 ID 范围（太大容易被封）
    SCAN_WORKERS = 6   # 扫描用适度线程，平衡速度与反爬

    prefix_match = re.match(r'(https?://[^/]+/\d+_\d+/)', first_url)
    url_prefix = prefix_match.group(1) if prefix_match else first_url.rsplit("/", 1)[0] + "/"

    first_cid = re.search(r'/(\d+)\.html$', first_url)
    last_id = int(first_cid.group(1)) if first_cid else 0
    total = 0
    batch = []

    print(f"🔗 正在发现章节（gap扫描 + 链式兜底）...")

    while True:
        # === 生成候选 ID：从 last_id+1 开始连续扫描 ===
        candidates = list(range(last_id + 1, last_id + 1 + SCAN_RANGE))

        # === 并行验证 ===
        found = []  # [(cid, title, urls), ...]
        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
            future_to_cid = {
                pool.submit(_validate_chapter, f"{url_prefix}{cid}.html"): cid
                for cid in candidates
            }
            for future in future_to_cid:
                cid = future_to_cid[future]
                result = future.result()
                if result:
                    found.append((cid, result[0], result[1]))  # (cid, title, urls)

        if found:
            # 按 ID 排序，即为正确的章节顺序
            found.sort(key=lambda x: x[0])

            for cid, title, urls in found:
                batch.append((title, urls))
                last_id = cid
                total += 1
                print(f"\r  ✅ 已发现 {total} 章: {title}", end="", flush=True)
                if len(batch) >= BATCH_SIZE:
                    yield batch
                    batch = []

            # 扫描范围内全部命中 → 间隙稳定，继续扫描
            continue

        # === 扫描全空 → 遇到大间隙，链式跳过续页到下一章 ===
        current_url = f"{url_prefix}{last_id}.html"
        rescue_count = 0
        for _ in range(10):  # 链式跟进最多 10 章
            result = _chain_to_next_chapter(current_url)
            if not result:
                break
            title, urls, cid = result
            batch.append((title, urls))
            last_id = cid
            total += 1
            rescue_count += 1
            current_url = urls[0]
            print(f"\r  🔗 链式 {total}: {title}", end="", flush=True)
            time.sleep(0.3)
            if len(batch) >= BATCH_SIZE:
                yield batch
                batch = []

        if rescue_count == 0:
            # 链式也找不到 → 到末尾了
            break

    if batch:
        yield batch

    print(f"\n📋 章节发现完毕，共 {total} 章")


def get_content(chap_title, page_urls):
    """
    单章正文爬取（支持多页章节合并）、清洗广告
    适配 biquga 新版加密：正文通过 qsbs.bb(base64) 动态加载
    :param chap_title: 章节标题
    :param page_urls: 章节所有页面的URL列表 [url1, url2, ...]
    """
    all_content = []

    for i, url in enumerate(page_urls):
        try:
            tree, _ = get_xpath_resp(url)
            if tree is None:
                continue

            # 新版章节内容：base64 加密在 <script>document.writeln(qsbs.bb('...'))</script> 中
            content_parts = []
            for script_text in tree.xpath('//script[contains(text(), "qsbs.bb")]/text()'):
                m = re.search(r"qsbs\.bb\('([^']+)'\)", script_text)
                if m:
                    try:
                        decoded = base64.b64decode(m.group(1)).decode("utf-8")
                        frag = etree.HTML(decoded)
                        if frag is not None:
                            t = frag.xpath("string()")
                            if t:
                                content_parts.append(t.strip())
                    except Exception:
                        continue

            if not content_parts:
                # 回退：尝试旧版 XPath（兼容未加密的老章节/其他站点）
                content_texts = tree.xpath('//div[@id="content"]/text()')
                if content_texts:
                    content_parts = [t.strip() for t in content_texts]

            if content_parts:
                page_content = "\n".join(content_parts)
                all_content.append(page_content)

            time.sleep(SUCCESS_SLEEP)

        except Exception as e:
            print(f"\n❌ 章节失败【{chap_title}】第{i+1}页：{str(e)}")
            time.sleep(FAIL_SLEEP)
            continue

    if not all_content:
        return None

    content = "\n".join(all_content)

    # 广告、垃圾文本清洗规则
    clean_rules = [
        ("笔趣阁", ""),
        ("biquga.com", ""),
        ("最新章节！", ""),
        ("无弹窗", ""),
        ("\n\n\n", "\n\n")
    ]
    for old, new in clean_rules:
        content = content.replace(old, new)

    page_info = f"（{len(page_urls)}页）" if len(page_urls) > 1 else ""
    print(f"\r✅ 已完成：{chap_title}{page_info}", end="", flush=True)
    return {"title": chap_title, "content": content}


if __name__ == "__main__":
    keyword_input = input("请输入小说/作者关键词：")
    print("\n🔍 正在搜索，请稍候...")
    try:
        book_list = get_search(keyword_input)
    except SystemExit:
        sys.exit()
    max_num = len(book_list)

    # 输入序号校验循环
    while True:
        num_str = input("\n输入书籍序号开始爬取（0=退出）：").strip()
        if num_str == "0":
            print("👋 已退出")
            sys.exit(0)
        if num_str.isdigit():
            num = int(num_str)
            if 0 < num < max_num:
                break
        print("❌ 请输入列表内有效数字！")

    target_book = book_list[num]
    book_url = target_book["url"]
    print(f"\n📚 开始爬《{target_book['article']}》...")

    # 1. 获取书籍信息 + 第一章链接，立即写入文件
    try:
        novel, author, intro, first_chapter_url = get_book_info(book_url)
    except Exception as err:
        print(f"书籍信息获取失败：{err}")
        sys.exit(1)

    print(f"书名：《{novel}》")
    print(f"作者：{author}")

    save_file = f"{novel}.txt"
    with open(save_file, "w", encoding="utf-8") as f:
        f.write(f"书名：《{novel}》\n作者：{author}\n简介：\n{intro}\n\n\n")
    print(f"📄 已创建文件：{save_file}")

    start_time = datetime.now()

    # 2. 边发现边下载：每发现 100 章就提交到线程池下载
    completed = 0
    with ThreadPoolExecutor(max_workers=THREAD_POOL_MAX_WORKERS) as pool:
        for batch in discover_chapters_generator(first_chapter_url):
            batch_num = completed // 100 + 1
            print(f"\n📥 第{batch_num}批：开始下载 {len(batch)} 章...")

            task_map = {
                pool.submit(get_content, title, urls): title
                for title, urls in batch
            }
            for task in task_map:
                res = task.result()
                if res:
                    with open(save_file, "a", encoding="utf-8") as f:
                        f.write(f"【{completed + 1} {res['title']}】\n{res['content']}\n\n\n")
                    completed += 1

    # 结束标记
    with open(save_file, "a", encoding="utf-8") as f:
        f.write("========== 全书完 ==========\n")

    end_time = datetime.now()
    print(f"\n\n🎉 《{novel}》爬取完成！共写入 {completed} 章")
    print(f"⏱️ 总耗时：{end_time - start_time}")
    print(f"💾 保存路径：{save_file}")
