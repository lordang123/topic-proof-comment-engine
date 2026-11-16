// Path 2 for finding same-topic videos: type each keyword into the search box on the home page, read the first screen of the "视频" tab.
// Not run directly. collect.py fills __KWS__ (JSON array, at most 6 keywords).
// Gap between keywords: 70% 12–30 s, 30% 30–60 s (random). No scrolling, no paging.
// Known pitfalls, handled here:
//   1. A background tab has a 0x0 viewport: set the device metrics first, or clicks and typing do nothing.
//   2. Start from the home page. Searching from a video page shows results in an overlay and reads the wrong cards.
//   3. The mixed results tab has no links; switch to the "视频" tab to get video ids.
//   4. An empty result is not proof of "no such videos" and not proof of rate limiting: stop the round, do not retry.
// Output: one line `@@RESULT@@ <json>`.
(async () => {
  await useOrCreateTaskSpace(EGO_SPACE)
  const kws = __KWS__
  const gapSec = () => Math.round(Math.random() < 0.7 ? 12 + Math.random() * 18 : 30 + Math.random() * 30)
  const out = { started: new Date().toISOString(), searches: [], stop: null }
  const grab = `(() => {
    const lines = document.body.innerText.split('\\n').map(x => x.trim()).filter(Boolean);
    const nAuthor = lines.filter(l => /^@/.test(l)).length;
    const seen = new Set(), cards = [];
    document.querySelectorAll('a[href*="/video/"]').forEach(a => {
      const m = a.href.match(/\\/video\\/([0-9]+)/); if (!m || seen.has(m[1])) return; seen.add(m[1]);
      const leaves = [...a.querySelectorAll('*')].filter(e => !e.children.length).map(e => (e.innerText || '').trim()).filter(Boolean);
      cards.push({ id: m[1], link: 'https://www.douyin.com/video/' + m[1], txt: (leaves.length ? leaves.join(' | ') : (a.innerText || '')).slice(0, 260) });
    });
    return { nAuthor, nAnchor: cards.length, url: location.href.slice(0, 120), cards };
  })()`
  const BOX = `document.querySelector('[data-e2e="searchbar-input"]')`
  const CLEAR_BOX = `(() => { const i = ${BOX}; i.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, ''); i.dispatchEvent(new Event('input', { bubbles: true })); return i.value; })()`
  const VISIBLE_TAB = `[...document.querySelectorAll('span')].filter(e => e.textContent.trim() === '视频' && e.getBoundingClientRect().width > 0)`
  try {
    await openOrReuseTab('https://www.douyin.com/', { wait: true, timeout: 40 })
    await wait(7)
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
    await wait(2)
    for (let i = 0; i < kws.length; i++) {
      const kw = kws[i], t0 = Date.now(), rec = { idx: i + 1, kw, at: new Date().toISOString() }
      try {
        await click('[data-e2e="searchbar-input"]'); await wait(1)
        rec.boxBefore = await js(CLEAR_BOX)
        if (rec.boxBefore !== '') { rec.boxErr = '清空后框内仍有文字'; out.searches.push(rec); out.stop = '第 ' + (i + 1) + ' 次清空搜索框失败，停'; break }
        await typeText(kw); await wait(1.5)
        rec.boxTyped = await js(`${BOX}.value`)
        if (rec.boxTyped !== kw) { rec.boxErr = '输入后框内文字与搜索词不符'; out.searches.push(rec); out.stop = '第 ' + (i + 1) + ' 次输入校验失败，停'; break }
        await pressKey('Enter')
        let r = { nAuthor: 0 }
        for (let k = 0; k < 8; k++) { await wait(3); r = await js(grab); if (r.nAuthor > 0) break }
        if (r.nAuthor > 0) {
          rec.tabHits = await js(`${VISIBLE_TAB}.length`)
          if (rec.tabHits === 0) rec.tabErr = '没找到可见的「视频」标签'
          else { try { await js(`${VISIBLE_TAB}[0].click()`) } catch (e) { rec.tabErr = String(e.message || e).slice(0, 120) } }
          for (let k = 0; k < 5; k++) { await wait(3); r = await js(grab); if (r.nAnchor > 0) break }
        }
        Object.assign(rec, r, { elapsed_s: Math.round((Date.now() - t0) / 1000) })
        if (r.nAuthor === 0) rec.empty_body = await js('document.body.innerText.slice(0, 300)')
      } catch (e) { rec.err = String(e.message || e).slice(0, 250); out.searches.push(rec); out.stop = '第 ' + (i + 1) + ' 次操作出错'; break }
      out.searches.push(rec)
      if (rec.nAuthor === 0) { out.stop = '第 ' + (i + 1) + ' 次搜索结果为空：停下，记「待补搜」'; break }
      if (i < kws.length - 1) { const g = gapSec(); rec.gap_after_s = g; await wait(g) }
    }
    if (!out.stop) out.stop = '跑完 ' + out.searches.length + ' 次，无异常'
  } catch (e) { out.stop = '错误 ' + String(e.message || e).slice(0, 200) }
  out.ended = new Date().toISOString()
  console.log('@@RESULT@@ ' + JSON.stringify(out))
})();
