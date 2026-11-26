# TMDB Top Rated 抓取器

抓取 [tmdb-pearl.vercel.app](https://tmdb-pearl.vercel.app/filter/top_rated) 的高分影视榜单与详情页，输出 CSV / JSON。

> 数据版权归原站点与 TMDB 所有。本项目仅用于学习网页抓取，请勿商用，也不要高频请求。

## 这个站为什么难抓

它是 React + Vite 的纯前端应用，服务器只返回 528 字节空壳：

```html
<body class="bg-dark_blue">
  <div id="root"></div>
  <div id="popup_wrapper"></div>
</body>
```

`requests` 拿到的 HTML 里没有任何电影数据。项目提供两条路：

| 方案 | 依赖 | 适用 |
| --- | --- | --- |
| A. 无头浏览器 `scraper.py` | Edge/Chrome | 网络能直连该站时，全自动 |
| B. 浏览器导出 `browser-export.js` | 只要浏览器 | 直连被重置、无头浏览器报 `ERR_CONNECTION_CLOSED` 时 |

方案 B 是本项目实际产出数据的方式，因为某些网络下 Vercel 直连会被 RST。

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 方案 A：无头浏览器

```bash
python scraper.py                # 列表 + 全部详情页（约 2 分钟）
python scraper.py --no-detail    # 只抓列表
python scraper.py --limit 3      # 只跑前 3 部
```

要点：

- 必须用 `--headless`（Edge 132+ 已移除 `--headless=new/old`，传错会秒退无输出）
- 每次渲染用全新的临时 `--user-data-dir`，否则 Edge 会把命令转交给已有实例，stdout 为空
- `--dump-dom` 的输出重定向到文件，避免 GUI 程序写管道丢内容
- 详情页 HTML 存到 `detail_pages/`，重跑时自动复用（断点续传）

## 方案 B：浏览器导出（推荐在受限网络下用）

1. 浏览器打开 `https://tmdb-pearl.vercel.app/filter/top_rated`，等卡片出现
2. `F12` → Console（Edge 首次粘贴需先手动输入 `allow pasting`）
3. 粘贴 [browser-export.js](browser-export.js) 全部内容，回车，等约 1 分钟
4. 页面出现 JSON 文本框 → `Ctrl+A` / `Ctrl+C` → 记事本保存为 `movies_detail.json`
5. 合并成表格：

```bash
python merge_export.py --details movies_detail.json --list last_render.html
```

`--list` 是榜单页渲染后的 HTML：在榜单页 Console 里执行
`copy(document.documentElement.outerHTML)` 后保存即可。没有它也能跑，只是日期和海报会为空。

## 输出

| 文件 | 内容 |
| --- | --- |
| `data/movies.csv` | 表格数据，UTF-8 BOM，Excel 直接打开 |
| `data/movies.json` | 完整字段 |

## 字段

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `rank` | 列表顺序 | 1 起 |
| `title` | 详情页 `<main>` 第一个 `h2` | 站点本地化标题（实测为法语） |
| `year` / `date` | 列表卡片 | `year` 从日期文本截取 |
| `rating` | 列表卡片圆环 | 如 `91%` |
| `user_score` | 详情页圆环 | 站点详情页对全部条目都显示 `9%`，属站点自身的数据问题 |
| `genres` | 详情页分级徽章旁文本 | `Animation, Action, Aventure, Drame` |
| `cast` | 详情页 “Series Cast” 区块 | 前 5 位演员，部分页面加载慢会为空 |
| `overview` | 详情页 Overview 段落 | 简介 |
| `poster` | 列表卡片 `img[src]` | 海报地址 |
| `url` | 列表卡片 `a[href]` | 详情页地址 |

## 页面结构（2026-11 实测）

| 内容 | 选择器 |
| --- | --- |
| 列表卡片 | `//div[contains(@class,'max-h-[353px]')]` |
| 列表片名 | `.//a[contains(@href,'/movie/')]//text()`（**不在 h2 里**） |
| 列表日期 | `string(.//span[contains(@class,'text-slate-600')])` |
| 列表评分 | `string(.//div[contains(@class,'font-semibold')])` |
| 详情标题 | `//main//h2`（第一个） |
| 详情简介 | 包含 `<span>Overview</span>` 的 `<p>` 的直接文本 |
| 详情评分 | `//main//div[contains(@class,'font-semibold') and contains(@class,'absolute')]` |

## 已知限制

- 只抓榜单第一页（20 部），站点的 “Load More” 走 XHR。
- 详情页会先渲染骨架屏，必须等标题有文字再解析，否则拿到空数据。
- 站点改版后选择器会失效；用 `--archive` 或浏览器导出保留 HTML 便于重新核对。

## 目录

```
tmdb-scraper/
├─ scraper.py          方案 A：无头浏览器全自动抓取
├─ browser-export.js   方案 B：浏览器 Console 内导出
├─ merge_export.py     方案 B：合并导出 JSON + 榜单 HTML
├─ requirements.txt
├─ data/               运行后生成，不进 Git
├─ detail_pages/       方案 A 的存档，不进 Git
└─ last_render.html    榜单页 DOM，不进 Git
```
