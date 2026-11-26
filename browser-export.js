/* 在浏览器里批量导出详情页数据。
 *
 * 背景：目标站是纯前端渲染，且所在网络直连 Vercel 会被重置时，
 * 无头浏览器（--dump-dom）拿不到内容。这个脚本在已打开的榜单页
 * Console 里运行，用同源 iframe 逐个加载详情页、读取渲染后的 DOM，
 * 最后把 JSON 显示成文本框，复制保存为 movies_detail.json 即可。
 *
 * 用法：
 *   1. 打开 https://tmdb-pearl.vercel.app/filter/top_rated，等卡片出现
 *   2. F12 → Console（Edge 首次粘贴需先手动输入 allow pasting）
 *   3. 粘贴本文件全部内容，回车，等待约 1 分钟
 *   4. 页面出现 JSON 文本框 → Ctrl+A / Ctrl+C → 记事本保存为 movies_detail.json
 *   5. python merge_export.py --details movies_detail.json
 */
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();

  const links = [...new Set(
    [...document.querySelectorAll('a[href^="/movie/"]')]
      .map(a => a.getAttribute('href'))
      .filter(h => /^\/movie\/\d+$/.test(h))
  )];
  console.log('找到', links.length, '部电影');
  if (!links.length) return;

  const frame = document.createElement('iframe');
  frame.style.cssText = 'position:fixed;left:-9999px;top:0;width:1280px;height:1200px;';
  document.body.appendChild(frame);

  const out = [];
  for (let i = 0; i < links.length; i++) {
    frame.src = links[i];
    let doc = null;

    // 详情页会先渲染骨架屏，必须等标题有文字且正文足够长
    for (let t = 0; t < 80; t++) {
      await sleep(250);
      try { doc = frame.contentDocument; } catch (e) { doc = null; }
      if (!doc) continue;
      const h2 = doc.querySelector('main h2');
      const title = norm(h2 && h2.textContent);
      const bodyLen = (doc.body && doc.body.innerText || '').length;
      if (title.length > 1 && bodyLen > 500) break;
    }

    const h2 = doc && doc.querySelector('main h2');
    const title = norm(h2 && h2.textContent);
    if (!title) { console.warn('跳过（未渲染）', links[i]); continue; }

    let overview = '';
    const ov = [...doc.querySelectorAll('span')].find(s => norm(s.textContent) === 'Overview');
    if (ov && ov.parentElement) {
      overview = norm([...ov.parentElement.childNodes]
        .filter(n => n.nodeType === Node.TEXT_NODE)
        .map(n => n.textContent).join(' '));
    }

    let score = '';
    for (const d of doc.querySelectorAll('div')) {
      const c = d.className || '';
      if (typeof c === 'string' && c.includes('font-semibold') && c.includes('absolute')) {
        const m = norm(d.textContent).match(/^(\d{1,3})\s*%$/);
        if (m) { score = m[1] + '%'; break; }
      }
    }

    let genres = '';
    const badge = [...doc.querySelectorAll('span')].find(s => {
      const c = s.className || '';
      return typeof c === 'string' && c.includes('border') && c.includes('rounded')
             && /^[A-Z]{1,3}-?\d{0,2}$/.test(norm(s.textContent));
    });
    if (badge && badge.parentElement) {
      genres = norm(badge.parentElement.textContent)
        .replace(norm(badge.textContent), '').replace(/^[，,、\s]+/, '');
    }

    let cast = '';
    const head = [...doc.querySelectorAll('h3')].find(h => norm(h.textContent).includes('Series Cast'));
    if (head) {
      const block = head.closest('div.flex-col') || head.parentElement?.parentElement;
      if (block) {
        const names = [];
        for (const card of block.querySelectorAll('div.min-w-36')) {
          const walker = doc.createTreeWalker(card, NodeFilter.SHOW_TEXT);
          let first = '';
          while (walker.nextNode()) {
            const t = norm(walker.currentNode.textContent);
            if (t) { first = t; break; }
          }
          if (first && !names.includes(first)) names.push(first);
          if (names.length >= 5) break;
        }
        cast = names.join('、');
      }
    }

    out.push({ href: links[i], title, overview, score, genres, cast });
    console.log(`[${i + 1}/${links.length}]`, title, score);
    await sleep(400);
  }

  frame.remove();
  window.__movies = out;

  // 不依赖下载（Edge 会拦截同一站点的重复下载），直接把 JSON 摊在页面上
  const area = document.createElement('textarea');
  area.value = JSON.stringify(out, null, 2);
  area.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:99999;font-size:12px;padding:10px';
  document.body.appendChild(area);
  area.focus();
  area.select();
  console.log('完成：', out.length, '条。按 Ctrl+A / Ctrl+C 复制，保存为 movies_detail.json');
})();
