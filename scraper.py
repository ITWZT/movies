"""TMDB Top Rated 影视数据抓取器。

目标站：https://tmdb-pearl.vercel.app/filter/top_rated
该站是纯前端渲染（SPA），服务器只返回空壳，所以用本机 Edge 的无头模式
执行 JS，拿到渲染后的 DOM，再交给 lxml 解析。

用法：
    python scraper.py                 # 抓列表 + 全部详情页
    python scraper.py --no-detail     # 只抓列表
    python scraper.py --limit 3       # 只处理前 3 部，调试用
    python scraper.py --archive       # 额外保存每页原始 HTML（detail_pages/）

输出：
    data/movies.csv   表格数据，Excel 可直接打开
    data/movies.json  完整数据，含简介
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lxml import html

BASE = "https://tmdb-pearl.vercel.app"
LIST_URL = f"{BASE}/filter/top_rated"

# --- 列表页结构（实测）---
LIST_CARD_XPATH = "//div[contains(@class,'max-h-[353px]')]"
LIST_MARKER = "max-h-[353px]"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

DATA_DIR = Path("data")
ARCHIVE_DIR = Path("detail_pages")


# ---------------------------------------------------------------- 渲染
def find_browser() -> str | None:
    for path in BROWSER_CANDIDATES:
        if Path(path).exists():
            return path
    import shutil
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def render(url: str, budget: int = 30000) -> str:
    """用无头浏览器执行 JS，返回渲染后的 HTML。

    每次都用全新的临时 profile：Edge 已经运行时，复用同一个 --user-data-dir
    会把命令转交给已有实例，stdout 直接是空的（这是踩过的坑）。
    """
    exe = find_browser()
    if not exe:
        raise RuntimeError("没找到 Edge/Chrome")

    errors = []
    last_text = ""
    for _ in range(2):                                  # 整体重试一次
        # 第一项 --headless 是关键：Edge 132+ 只认这个写法，
        # =new/=old 在 158 版会直接退出、不产生任何输出
        for flag in ("--headless", "--headless=new", "--headless=old"):
            profile = tempfile.mkdtemp(prefix="edge_profile_")
            sink = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
            out_path = Path(sink.name)
            cmd = [exe, flag,
                   f"--virtual-time-budget={budget}",
                   "--window-size=1920,1080",
                   f"--user-agent={USER_AGENT}",
                   "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   f"--user-data-dir={profile}",
                   "--dump-dom", url]
            try:
                # stdout 直接重定向到文件，避免 GUI 程序写管道时丢内容
                proc = subprocess.run(cmd, stdout=sink, stderr=subprocess.PIPE, timeout=180)
                sink.close()
                text = out_path.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")
                stderr = proc.stderr.decode("utf-8", "ignore").strip()
            except subprocess.TimeoutExpired:
                sink.close()
                errors.append(f"{flag} 超时")
                continue
            finally:
                shutil.rmtree(profile, ignore_errors=True)
                out_path.unlink(missing_ok=True)

            if text:
                last_text = text
                if "</html>" in text or "/movie/" in text:
                    return text
                errors.append(f"{flag} 输出 {len(text)} 字节，但没有电影链接")
            else:
                errors.append(f"{flag} 无输出" +
                              (f"（stderr: {stderr[-300:]}）" if stderr else ""))

    if last_text:
        Path("last_render.html").write_text(last_text, encoding="utf-8")
        errors.append("已保存 last_render.html 供排查")
    raise RuntimeError("；".join(errors[-4:]) or "未知原因")


# ---------------------------------------------------------------- 解析：列表
def parse_list(html_text: str) -> list[dict]:
    tree = html.fromstring(html_text)
    rows = []
    for card in tree.xpath(LIST_CARD_XPATH):
        hrefs = card.xpath(".//a[contains(@href,'/movie/')]/@href")
        if not hrefs:
            continue
        titles = [t.strip() for t in
                  card.xpath(".//a[contains(@href,'/movie/')]//text()") if t.strip()]
        if not titles:
            continue
        posters = [s for s in card.xpath(".//img/@src")
                   if s and not s.startswith("data:")]
        rows.append({
            "title": titles[0],
            "date": card.xpath("string(.//span[contains(@class,'text-slate-600')])").strip(),
            "rating": card.xpath("string(.//div[contains(@class,'font-semibold')])").strip(),
            "url": BASE + hrefs[0],
            "poster": posters[0] if posters else "",
        })

    if not rows:                                # 结构变化时的兜底
        seen = set()
        for anchor in tree.xpath("//a[contains(@href,'/movie/')]"):
            href = anchor.get("href") or ""
            title = " ".join(t.strip() for t in anchor.xpath(".//text()") if t.strip())
            if not title or href in seen:
                continue
            seen.add(href)
            rows.append({"title": title, "date": "", "rating": "",
                         "url": BASE + href, "poster": ""})
    return rows


# ---------------------------------------------------------------- 解析：详情
def parse_detail(html_text: str) -> dict:
    """详情页解析（按 2026-11 实测 DOM 写的）。

    结构：
        标题   <main> 里第一个 h2（class 含 text-lg font-bold）
        简介   <p> 包着 <span>Overview</span>，正文是 p 的直接文本
        评分   圆环内 <div class="font-semibold absolute">9%</div>
        类型   TV-14 徽章所在容器的直接文本，按逗号切
        演员   "Series Cast" 区块里的卡片，首行是演员名
    """
    tree = html.fromstring(html_text)
    data = {}

    titles = [t.strip() for t in
              tree.xpath("//main//h2[contains(@class,'text-lg')]//text()") if t.strip()]
    if not titles:
        titles = [t.strip() for t in tree.xpath("(//main//h2)[1]//text()") if t.strip()]
    title = titles[0] if titles else ""
    data["title"] = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", title).strip()

    overview = ""
    for paragraph in tree.xpath("//main//p[.//span[normalize-space(text())='Overview']]"):
        overview = " ".join(t.strip() for t in paragraph.xpath("./text()") if t.strip())
        break
    data["overview"] = overview

    score = ""
    for node in tree.xpath(
            "//main//div[contains(@class,'font-semibold') and contains(@class,'absolute')]"):
        matched = re.fullmatch(r"(\d{1,3})\s*%", node.text_content().strip())
        if matched:
            score = f"{matched.group(1)}%"
            break
    data["user_score"] = score

    genres = []
    badges = tree.xpath("//main//span[contains(@class,'border') and contains(@class,'rounded')]")
    if badges:
        header = badges[0].getparent()
        rest = header.text_content().replace(badges[0].text_content(), "", 1)
        genres = [g.strip() for g in rest.split(",") if g.strip()]
    data["genres"] = "、".join(genres)

    cast = []
    blocks = tree.xpath(
        "//h3[contains(.,'Series Cast')]/ancestor::div[contains(@class,'flex-col')][1]")
    if blocks:
        for card in blocks[0].xpath(".//div[contains(@class,'min-w-36')]"):
            lines = [t.strip() for t in card.xpath(".//text()") if t.strip()]
            if lines and lines[0] not in cast:
                cast.append(lines[0])
            if len(cast) >= 5:
                break
    data["cast"] = "、".join(cast)
    return data

# ---------------------------------------------------------------- 主流程
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-detail", action="store_true", help="只抓列表")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 部")
    parser.add_argument("--archive", action="store_true", help="保存详情页原始 HTML")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    print("① 渲染列表页 …")
    movies = parse_list(render(LIST_URL))
    if args.limit:
        movies = movies[:args.limit]
    print(f"   解析出 {len(movies)} 部")

    if not args.no_detail:
        ARCHIVE_DIR.mkdir(exist_ok=True)
        print("② 逐部解析详情页（已有存档直接复用，失败可重跑续传）…")
        for index, movie in enumerate(movies, 1):
            print(f"   [{index}/{len(movies)}] {movie['title']}")
            movie_id = movie["url"].rstrip("/").split("/")[-1]
            cached = ARCHIVE_DIR / f"{movie_id}.html"
            try:
                if cached.exists() and cached.stat().st_size > 2000:
                    page_html = cached.read_text(encoding="utf-8", errors="ignore")
                    print("       复用已存 HTML")
                else:
                    page_html = render(movie["url"], budget=25000)
                    cached.write_text(page_html, encoding="utf-8")
                movie.update({k: v for k, v in parse_detail(page_html).items() if v})
            except Exception as exc:
                print(f"       ! 失败，跳过：{exc}")
            time.sleep(0.8)

    for rank, movie in enumerate(movies, 1):
        movie["rank"] = rank
        if not movie.get("year"):
            found = re.search(r"(19|20)\d{2}", movie.get("date", ""))
            movie["year"] = found.group(0) if found else ""

    columns = ["rank", "title", "year", "date", "rating", "user_score",
               "genres", "cast", "overview", "poster", "url"]
    with open(DATA_DIR / "movies.csv", "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(movies)

    with open(DATA_DIR / "movies.json", "w", encoding="utf-8") as fh:
        json.dump(movies, fh, ensure_ascii=False, indent=2)

    filled = sum(1 for m in movies if m.get("overview"))
    print(f"③ 完成：{len(movies)} 条，其中 {filled} 条有简介")
    print(f"   {DATA_DIR / 'movies.csv'} / {DATA_DIR / 'movies.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
