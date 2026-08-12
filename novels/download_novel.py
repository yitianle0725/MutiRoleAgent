"""
download_novel.py 适配 https://www.qishuxia.com 奇书网
直接搜索 + TXT下载，无需逐章爬取
"""
import sys
import os
import re
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from lxml import etree
from layout_novel import clean_text

# ===================== 常量配置 =====================
BASE_URL = "https://www.qishuxia.com"
SEARCH_PATH = "/modules/article/search.php"
TXT_DOWNLOAD_PATH = "/modules/article/txtarticle.php"
TIMEOUT = 15
RETRY_TIMES = 3
# ====================================================

SESSION = requests.Session()
SESSION.keep_alive = False

retry_strategy = Retry(
    total=RETRY_TIMES,
    status_forcelist=[500, 502, 503, 504, 429],
    redirect=3,
    backoff_factor=1,
    raise_on_status=False  # 403 不重试，qishuxia 用 403 做反爬
)
adapter = HTTPAdapter(max_retries=retry_strategy)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": f"{BASE_URL}/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome 120.0.0.0 Safari/537.36"
}


def get_search(keyword: str) -> list:
    """
    搜索小说（站点使用 GBK 编码）
    返回: [{"name": 书名, "url": 书籍链接, "author": 作者, "book_id": ID}, ...]
    """
    keyword_quoted = urllib.parse.quote(keyword, encoding="gbk")
    search_url = f"{BASE_URL}{SEARCH_PATH}?searchkey={keyword_quoted}"

    try:
        resp = SESSION.get(search_url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "gbk"
    except Exception as e:
        print(f"搜索失败：{e}")
        sys.exit(1)

    tree = etree.HTML(resp.text)
    # 结构: li > span.s1(分类) span.s2>a(书名) span.s3>a(最新章节) span.s4(作者) span.s5(日期)
    book_items = tree.xpath('//li[span[@class="s2"]/a[contains(@href, "/book/")]]')

    if not book_items:
        print("❌ 未匹配到任何小说，请更换关键词重试！")
        sys.exit(1)

    print("✅ 搜索成功：")
    print(f"|{'序号':^4}|{'书名':^26}|{'作者':^12}|{'最新章节':^22}|")
    res_list = []

    for idx, item in enumerate(book_items, 1):
        # 书名 + 链接 (span.s2 > a)
        title_a = item.xpath('.//span[@class="s2"]/a')
        book_name = title_a[0].text.strip() if title_a[0].text else "未知书名"
        book_url = title_a[0].get("href", "")

        # book ID
        id_match = re.search(r'/book/(\d+)/', book_url)
        book_id = id_match.group(1) if id_match else ""

        # 作者 (span.s4)
        author_ele = item.xpath('.//span[@class="s4"]/text()')
        author = author_ele[0].strip() if author_ele else "未知"

        # 最新章节 (span.s3 > a)
        update_ele = item.xpath('.//span[@class="s3"]/a/text()')
        update_text = update_ele[0].strip() if update_ele else "无"

        res_list.append({
            "name": book_name,
            "url": book_url if book_url.startswith("http") else BASE_URL + book_url,
            "author": author,
            "book_id": book_id,
        })
        print(f"|{idx:^4}|{book_name:^26}|{author:^10}|{update_text:^22}|")

    return res_list


def get_book_info(book_id: str):
    """获取书名和作者"""
    book_url = f"{BASE_URL}/book/{book_id}/"
    try:
        resp = SESSION.get(book_url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "gbk"
    except Exception:
        return "未知书名", "未知作者"

    tree = etree.HTML(resp.text)

    title = tree.xpath('//title/text()')
    novel = "未知书名"
    author = "未知作者"
    if title:
        # 格式: 书名(作者)_... - 奇书网
        title_text = title[0]
        m = re.search(r'(.+?)\((.+?)\)', title_text)
        if m:
            novel = m.group(1).strip()
            author = m.group(2).strip()

    return novel, author


def download_txt(book_id: str, save_path: str):
    """
    直接下载 TXT 文件
    """
    download_url = f"{BASE_URL}{TXT_DOWNLOAD_PATH}?id={book_id}"
    print(f"\n📥 正在下载 TXT...")

    try:
        resp = SESSION.get(download_url, headers=HEADERS, timeout=30)
        resp.encoding = "gbk"

        # 清洗排版后再保存
        text = clean_text(resp.text)

        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)

        size_kb = len(text.encode("utf-8")) / 1024
        print(f"✅ 下载完成！")
        print(f"💾 保存路径：{save_path}")
        print(f"📏 文件大小：{size_kb:.1f} KB")
    except Exception as e:
        print(f"❌ 下载失败：{e}")
        sys.exit(1)


if __name__ == "__main__":
    # 1. 首页预热（获取 cookie，403 是正常的反爬机制）
    HEADERS["Referer"] = "https://www.google.com/"
    SESSION.get(BASE_URL, headers=HEADERS, timeout=TIMEOUT)
    HEADERS["Referer"] = f"{BASE_URL}/"

    # 2. 搜索
    keyword_input = input("请输入小说/作者关键词：")
    print("\n🔍 正在搜索，请稍候...")
    book_list = get_search(keyword_input)
    max_num = len(book_list) + 1

    # 3. 选择书籍
    while True:
        num_str = input("\n输入书籍序号开始下载（0=退出）：").strip()
        if num_str == "0":
            print("👋 已退出")
            sys.exit(0)
        if num_str.isdigit():
            num = int(num_str)
            if 0 < num < max_num:
                break
        print("❌ 请输入列表内有效数字！")

    target = book_list[num - 1]
    book_id = target["book_id"]

    # 4. 获取书名
    novel, author = get_book_info(book_id)
    print(f"\n📚 《{novel}》作者：{author}")

    # 5. 下载 TXT
    save_file = os.path.join(os.path.dirname(__file__), f"{novel}.txt")
    download_txt(book_id, save_file)
