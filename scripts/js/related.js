// Path 1 for finding same-topic videos: read the "related videos" panel on the benchmark video page. No search.
// Not run directly. collect.py fills __VID__ and __MAXN__ (pages to read, including the benchmark; default 2).
// A page without a comment count or without the related panel = possible restriction: stop, do not retry.
// The panel also holds a few unrelated trending items; judging "same topic" is the analyst's job.
// Output: one line `@@RESULT@@ <json>`.
(async () => {
  await useOrCreateTaskSpace(EGO_SPACE)
  const START = '__VID__', MAXN = __MAXN__
  const out = { started: new Date().toISOString(), visits: [], stop: null }
  const read = `(() => {
    const q = s => { const e = document.querySelector('[data-e2e="' + s + '"]'); return e ? (e.innerText || '').trim() : null; };
    const rel = [], seen = new Set();
    const panel = document.querySelector('[data-e2e="related-video"]') || document.querySelector('[data-e2e="aweme-relate"]');
    (panel || document.body).querySelectorAll('a[href*="/video/"]').forEach(a => {
      const m = a.href.match(/\\/video\\/([0-9]+)/); if (!m || seen.has(m[1])) return; seen.add(m[1]);
      let box = a, d = 0; while (box.parentElement && d < 4 && (box.innerText || '').length < 30) { box = box.parentElement; d++; }
      // Join leaf texts with ' | ' so duration, title, likes and author stay separate (the card's innerText runs them together).
      const leaves = [...box.querySelectorAll('*')].filter(e => !e.children.length).map(e => (e.innerText || '').trim()).filter(Boolean);
      rel.push({ id: m[1], txt: (leaves.length ? leaves.join(' | ') : (box.innerText || '')).slice(0, 160) });
    });
    return { title: document.title.slice(0, 60), digg: q('video-player-digg'), comment: q('feed-comment-icon'), collect: q('video-player-collect'),
             share: q('video-player-share'), pub: q('detail-video-publish-time'), hasPanel: !!panel, nrel: rel.length, rel: rel.slice(0, 12),
             blocked: /验证|请完成|滑动|页面不见/.test(document.body.innerText.slice(0, 400)) };
  })()`
  const queue = [START], visited = new Set(); let first = true
  try {
    while (queue.length && out.visits.length < MAXN) {
      const id = queue.shift(); if (visited.has(id)) continue; visited.add(id)
      const t0 = Date.now(), u = 'https://www.douyin.com/video/' + id
      try { if (first) { first = false; await openOrReuseTab(u, { wait: true, timeout: 40 }) } else await gotoAndWait(u) }
      catch (e) { out.stop = '打开页面出错 ' + String(e.message || e).slice(0, 100); break }
      let r = null
      for (let k = 0; k < 15; k++) { await wait(1); r = await js(read); if (r.comment && /^[0-9.,万亿]+$/.test(r.comment) && r.hasPanel && r.nrel > 0) break }
      await wait(1.5 + Math.random() * 2)
      out.visits.push({ n: out.visits.length + 1, id, at: new Date().toISOString(), load_s: Math.round((Date.now() - t0) / 1000), ...r })
      if (!r.comment || !r.hasPanel || r.blocked || r.nrel === 0) { out.stop = '第 ' + out.visits.length + ' 次读不到评论数或推荐面板：疑似受限'; break }
      if (out.visits.length === 1) r.rel.forEach(x => queue.push(x.id))
      if (queue.length && out.visits.length < MAXN) await wait(Math.round(8 + Math.random() * 7))
    }
    if (!out.stop) out.stop = '跑完 ' + out.visits.length + ' 次，无异常'
  } catch (e) { out.stop = '错误 ' + String(e.message || e).slice(0, 200) }
  out.ended = new Date().toISOString()
  console.log('@@RESULT@@ ' + JSON.stringify(out))
})();
