"""把浏览器导出的详情数据与榜单 HTML 合并成 data/movies.csv 和 movies.json。

用法（在 tmdb-scraper 目录下）：
    python merge_export.py
    python merge_export.py --details D:/movies_detail.json --list last_render.html --out data

--list 是榜单页渲染后的 HTML（可以是用 scraper.py 的 --keep 存下来的 rendered.html，
也可以是从浏览器 Console 里 copy(document.documentElement.outerHTML) 保存的文件）。
如果没有这个文件，标题/日期/评分/海报会回落到详情 JSON 里能拿到的字段。
"""

import argparse
import csv
import json
import re
from pathlib import Path

from lxml import html

BASE = "https://tmdb-pearl.vercel.app"
CARD_XPATH = "//div[contains(@class,'max-h-[353px]')]"
COLUMNS = ["rank", "title", "year", "date", "rating", "user_score",
           "genres", "cast", "overview", "poster", "url"]

DROP_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e]")


def clean(text):
    return DROP_MARKS.sub("", (text or "")).strip()


def parse_list(list_html):
    """从榜单页 HTML 里取 标题/日期/评分/海报/详情链接。"""
    if not list_html:
        return []
    tree = html.fromstring(list_html)
    rows = []
    for card in tree.xpath(CARD_XPATH):
        hrefs = card.xpath(".//a[contains(@href,'/movie/')]/@href")
        titles = [t.strip() for t in card.xpath(".//a[contains(@href,'/movie/')]//text()") if t.strip()]
        if not hrefs or not titles:
            continue
        posters = [s for s in card.xpath(".//img/@src") if s and not s.startswith("data:")]
        rows.append({
            "title": clean(titles[0]),
            "date": card.xpath("string(.//span[contains(@class,'text-slate-600')])").strip(),
            "rating": card.xpath("string(.//div[contains(@class,'font-semibold')])").strip(),
            "url": BASE + hrefs[0],
            "poster": posters[0] if posters else "",
        })
    return rows


def merge(list_rows, details):
    by_href = {}
    for item in details:
        href = item.get("href", "")
        if href.startswith(BASE):
            href = href[len(BASE):]
        by_href[href] = item

    merged = []
    for row in list_rows:
        href = row["url"][len(BASE):]
        detail = by_href.pop(href, {})
        date = row.get("date", "")
        year = re.search(r"(19|20)\d{2}", date)
        merged.append({
            "title": clean(detail.get("title") or row["title"]),
            "year": year.group(0) if year else "",
            "date": date,
            "rating": row.get("rating", ""),
            "user_score": detail.get("score", ""),
            "genres": re.sub(r"[,，、\s]+$", "", detail.get("genres", "")),
            "cast": detail.get("cast", ""),
            "overview": detail.get("overview", ""),
            "poster": row.get("poster", ""),
            "url": row["url"],
        })

    for href, detail in by_href.items():          # 榜单里没有、但导出里有的
        merged.append({
            "title": clean(detail.get("title", "")), "year": "", "date": "",
            "rating": "", "user_score": detail.get("score", ""),
            "genres": re.sub(r"[,，、\s]+$", "", detail.get("genres", "")), "cast": detail.get("cast", ""),
            "overview": detail.get("overview", ""), "poster": "",
            "url": BASE + href,
        })

    for rank, row in enumerate(merged, 1):
        row["rank"] = rank
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--details", default="movies_detail.json")
    parser.add_argument("--list", default="last_render.html")
    parser.add_argument("--out", default="data")
    args = parser.parse_args()

    details_path = Path(args.details)
    if not details_path.exists():
        raise SystemExit(f"找不到 {details_path}，先在浏览器里跑 browser-export.js")

    details = json.loads(details_path.read_text(encoding="utf-8"))
    list_path = Path(args.list)
    list_rows = parse_list(list_path.read_text(encoding="utf-8", errors="ignore")) if list_path.exists() else []
    if not list_rows:
        print(f"提示：没读到榜单 HTML（{list_path}），只用详情数据，日期/海报会为空")

    rows = merge(list_rows, details)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "movies.csv", "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    with open(out_dir / "movies.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)

    print(f"{len(rows)} 条 -> {out_dir / 'movies.csv'}")
    print("有简介:", sum(1 for r in rows if r["overview"]),
          "| 有演员:", sum(1 for r in rows if r["cast"]),
          "| 有海报:", sum(1 for r in rows if r["poster"]))


if __name__ == "__main__":
    main()
