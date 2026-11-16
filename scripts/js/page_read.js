// Read each video page once: counts, publish date, author link, and (when qualified) a comment sample.
// Not run directly. collect.py fills __IDS__ and __CFG__ and runs it through ego_run.py.
// Per page:
//   1. Poll once a second (max 15 s) until the comment count and publish date appear.
//   2. Read likes / comments / saves / shares / publish date / title / description / author link.
//   3. If comments > commentMin and the publish year qualifies, scroll the comment panel on this page and sample.
//      Only the replies of the replyTop most-liked comments are expanded.
//   4. Wait between pages: 85% 8–15 s, 15% 20–40 s (random). Time already spent scrolling is deducted, min 3–6 s.
// A page with no readable comment count = possible restriction: stop at once, do not retry.
// No commenter nickname, avatar or IP region is saved. Only the relative time ("3天前") is kept.
// Output: one `@@VISIT@@ <json>` line per page, then `@@END@@ <json>`.
(async () => {
  await useOrCreateTaskSpace(EGO_SPACE)
  const IDS = __IDS__
  const CFG = Object.assign({ commentMin: 500, minYear: new Date().getFullYear() - 1, maxTop: 200, hotK: 45, posM: 45, replyTop: 3, readOnly: false }, __CFG__)
  const SEL = '[data-e2e="comment-item"]'
  const rnd = (a, b) => a + Math.random() * (b - a)
  const num = s => { if (s == null) return null; const m = String(s).replace(/,/g, '').trim().match(/^([0-9.]+)(万|亿)?$/); return m ? Math.round(parseFloat(m[1]) * (m[2] === '万' ? 1e4 : m[2] === '亿' ? 1e8 : 1)) : null }
  const out = { started: new Date().toISOString(), stop: null, remaining: [] }

  const read = `(() => {
    const q = s => { const e = document.querySelector('[data-e2e="' + s + '"]'); return e ? (e.innerText || '').trim() : null; };
    const pick = root => [...root.querySelectorAll('a[href*="/user/MS4w"]')].map(a => ({ href: a.getAttribute('href') || '', txt: (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 40) }));
    const vi = document.querySelector('[data-e2e="video-info"]');
    let au = vi ? pick(vi) : [];
    if (!au.length) au = pick(document);
    // Recommended videos' author links carry ?author_id= and come later; the current author's link has no query.
    const clean = au.filter(x => !x.href.includes('?'));
    if (clean.length) au = clean;
    const a0 = au.filter(x => x.txt)[0] || au[0] || null;
    const m = a0 && a0.href.match(/\\/user\\/(MS4w[\\w-]+)/);
    return { title: document.title.slice(0, 60), desc: (q('video-desc') || '').slice(0, 200), digg: q('video-player-digg'), comment: q('feed-comment-icon'),
             collect: q('video-player-collect'), share: q('video-player-share'), pub: q('detail-video-publish-time'),
             author_name: a0 ? a0.txt : null, author_sec: m ? m[1] : null,
             blocked: /验证|请完成|滑动|页面不见/.test(document.body.innerText.slice(0, 400)) };
  })()`

  const pollRead = async () => {
    let r = null, prev = null
    for (let i = 0; i < 15; i++) {
      await wait(1)
      r = await js(read)
      const ok = num(r.comment) != null && r.pub
      if (ok && prev === r.comment) return r
      prev = ok ? r.comment : null
      if (r.blocked) return r
    }
    return r
  }

  const SCROLL = `(() => {
    let el = document.querySelector('${SEL}');
    for (let k = 0; k < 14 && el && el.parentElement; k++) {
      const p = el.parentElement, s = getComputedStyle(p);
      if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight + 50) { p.scrollTop = p.scrollHeight; return p.scrollTop; }
      el = p;
    }
    return -1;
  })()`
  const EXPAND_RE = '^展开\\\\d+条回复$'

  const grabComments = async () => {
    let n = 0
    for (let i = 0; i < 10; i++) { n = await js(`document.querySelectorAll('${SEL}').length`); if (n > 0) break; await wait(1) }
    if (!n) {
      const pb = await js(`(() => (document.title + ' ' + (document.body ? document.body.innerText : '').slice(0, 400)))()`)
      const why = /验证码|安全验证|请完成验证|滑块|访问过于频繁/.test(pb || '') ? '疑似验证页或限流' : '评论区 10 秒内没有评论项'
      return { items: [], loaded: 0, err: why }
    }
    let last = 0, stall = 0
    for (let i = 0; i < 200; i++) {
      const c = await js(`document.querySelectorAll('${SEL}').length`)
      if (c === last) stall++; else { stall = 0; last = c }
      if (stall >= 5) break
      if (CFG.maxTop > 0 && c >= CFG.maxTop) break
      await js(SCROLL)
      await wait(rnd(1.0, 1.6))
    }
    if (CFG.replyTop > 0) {
      const clicked = await js(`(() => {
        const re = new RegExp('${EXPAND_RE}');
        const tops = [...document.querySelectorAll('${SEL}')].filter(el => !el.parentElement.closest('${SEL}'));
        const rows = tops.map(el => {
          const t = el.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
          if (!t.some(s => re.test(s))) return null;
          const tIdx = t.findIndex(s => s.includes('·') && /(分钟|小时|天|周|月|年|昨天|前)/.test(s));
          const d = tIdx >= 0 ? t.slice(tIdx + 1).find(s => /^[0-9.]+万?$/.test(s)) : null;
          return { el, digg: d ? (d.includes('万') ? parseFloat(d) * 10000 : parseInt(d)) : 0 };
        }).filter(Boolean).sort((a, b) => b.digg - a.digg).slice(0, ${CFG.replyTop});
        let k = 0;
        rows.forEach(({ el }) => { const b = [...el.querySelectorAll('span,div')].filter(e => re.test((e.innerText || '').trim())).pop(); if (b) { b.click(); k++; } });
        return k;
      })()`)
      if (clicked) await wait(rnd(2.0, 3.0))
    }
    // t[0] is the nickname: it is read only to locate the text and is never returned.
    const data = await js(`(() => {
      return [...document.querySelectorAll('${SEL}')].map((el, i) => {
        const t = el.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
        const isAuthor = t[1] === '作者'; const authorLiked = t.includes('作者赞过');
        const tIdx = t.findIndex(s => s.includes('·') && /(分钟|小时|天|周|月|年|昨天|前)/.test(s));
        const when = tIdx >= 0 ? t[tIdx].split('·')[0].trim() : '';
        const drop = ['作者', '...', '作者赞过', '分享', '回复', '展开', '收起'];
        const text = t.slice(1, tIdx >= 0 ? tIdx : t.length).filter(s => !drop.includes(s) && !/^展开\\d+条回复$/.test(s)).join(' ');
        let digg = 0;
        if (tIdx >= 0) { const d = t.slice(tIdx + 1).find(s => /^[0-9.]+万?$/.test(s)); if (d) digg = d.includes('万') ? Math.round(parseFloat(d) * 10000) : parseInt(d); }
        const rep = t.find(s => /^展开\\d+条回复$/.test(s));
        const isReply = !!el.parentElement.closest('${SEL}');
        return { i, isAuthor, authorLiked, isReply, text, when, digg, replies: rep ? parseInt(rep.match(/\\d+/)[0]) : 0 };
      }).filter(c => c.text);
    })()`)
    const N = data.length
    let picked = data.map((c, p) => ({ ...c, pos: p + 1, stratum: '' }))
    if (CFG.hotK > 0 || CFG.posM > 0) {
      const keep = new Map()
      ;[...picked].sort((a, b) => b.digg - a.digg).slice(0, CFG.hotK).forEach(c => { c.stratum = '赞高'; keep.set(c.pos, c) })
      for (let m = 0; m < CFG.posM && N > 0; m++) {
        const t = CFG.posM === 1 ? 1 : Math.round(1 + m * (N - 1) / (CFG.posM - 1))
        for (let d = 0; d < N; d++) {
          const hit = [picked[t - 1 + d], picked[t - 1 - d]].find(c => c && !keep.has(c.pos))
          if (hit) { hit.stratum = '位置'; keep.set(hit.pos, hit); break }
        }
      }
      picked = [...keep.values()].sort((a, b) => a.pos - b.pos)
    }
    return { items: picked, loaded: N, err: picked.length ? null : '加载 ' + N + ' 项，解析出 0 条有文字的评论' }
  }

  const queue = IDS.slice(); const visited = new Set(); let first = true; let k = 0
  try {
    while (queue.length) {
      const id = queue.shift(); if (visited.has(id)) continue; visited.add(id)
      const t0 = Date.now(); const u = 'https://www.douyin.com/video/' + id
      try { if (first) { first = false; await openOrReuseTab(u, { wait: true, timeout: 40 }) } else await gotoAndWait(u) }
      catch (e) { out.stop = '打开页面出错 ' + String(e.message || e).slice(0, 100); queue.unshift(id); visited.delete(id); break }
      const r = await pollRead()
      const rec = { n: ++k, id, at: new Date().toISOString(), load_s: Math.round((Date.now() - t0) / 1000), ...r }
      rec.comment_n = num(r.comment); rec.digg_n = num(r.digg)
      const ym = (r.pub || '').match(/(\d{4})-\d{2}-\d{2}/); rec.pub_year = ym ? +ym[1] : null
      rec.year_ok = rec.pub_year != null && rec.pub_year >= CFG.minYear
      if (rec.comment_n == null || r.blocked) { rec.stop_here = true; out.stop = '第 ' + k + ' 次读不到评论数：疑似受限，或视频已删除'; console.log('@@VISIT@@ ' + JSON.stringify(rec)); break }
      await wait(rnd(1.5, 3.5))
      let active = 0
      if (CFG.readOnly) rec.comments_skip = '只读数'
      else if (rec.comment_n <= CFG.commentMin) rec.comments_skip = '评论数 ≤' + CFG.commentMin
      else if (!rec.year_ok) rec.comments_skip = '发布年份 ' + rec.pub_year + ' 不合格'
      else {
        const tc = Date.now(); const g = await grabComments(); active = (Date.now() - tc) / 1000
        rec.comments = g.items; rec.comments_loaded = g.loaded; rec.comments_s = Math.round(active); if (g.err) rec.comments_err = g.err
      }
      console.log('@@VISIT@@ ' + JSON.stringify(rec))
      if (queue.length) {
        const base = Math.random() < 0.15 ? rnd(20, 40) : rnd(8, 15)
        await wait(active > 0 ? Math.max(rnd(3, 6), base - active) : base)
      }
    }
    if (!out.stop) out.stop = '跑完 ' + k + ' 次，无异常'
  } catch (e) { out.stop = '错误 ' + String(e.message || e).slice(0, 200) }
  out.remaining = queue.filter(x => !visited.has(x))
  out.ended = new Date().toISOString(); out.visited = k
  console.log('@@END@@ ' + JSON.stringify(out))
})();
