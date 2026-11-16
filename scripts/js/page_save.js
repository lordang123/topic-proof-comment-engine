// Save the media of the video you are watching, for personal study and research only.
// Not run directly. save_media.py fills __ID__, __WANT__ ('audio' | 'all') and __CHUNK__ (bytes per transfer piece).
//
// How it works (and what it does not do):
//   1. Before the page loads, a small hook records the addresses that the page's own player requests (fetch / XHR).
//      It records addresses only. It does not change any request.
//   2. The video page opens in a tab of your own ego browser, logged in as you, and plays as usual.
//   3. In that same page, the script asks for the whole file at a recorded address with a Range request,
//      the same kind of request the player itself sends. The browser sends its own headers.
//   It does not call platform APIs, does not compute or touch signatures, does not export cookies,
//   does not set User-Agent or Referer, does not open tabs in parallel, and handles one video per run.
//   If the page has no plain media stream (encrypted, image post, private, removed), it stops with an error. No workaround.
//
// Output lines: `@@CHUNK@@ <key> <seq> <base64>` for file data, then one `@@RESULT@@ <json>`.
(async () => {
  await useOrCreateTaskSpace(EGO_SPACE)
  const task = await taskSpace(EGO_SPACE)
  const page = await task.newPage()
  const ID = '__ID__', WANT = '__WANT__', CHUNK = __CHUNK__
  const out = { id: ID, at: new Date().toISOString(), stop: null, streams: [], saved: [] }
  const HOOK = `(() => { if (window.__tpReq) return; window.__tpReq = [];
    const rec = (u, via) => { try { if (window.__tpReq.length < 2000) window.__tpReq.push({ u: String(u), via }); } catch (e) {} };
    const of = window.fetch; window.fetch = function (i) { rec(i && i.url ? i.url : i, 'fetch'); return of.apply(this, arguments); };
    const oo = XMLHttpRequest.prototype.open; XMLHttpRequest.prototype.open = function (m, u) { rec(u, 'xhr'); return oo.apply(this, arguments); };
  })();`
  const ev = async expr => {
    const r = await page.cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text)
    return r.result ? r.result.value : null
  }
  const META = `(() => {
    const q = s => { const e = document.querySelector('[data-e2e="' + s + '"]'); return e ? (e.innerText || '').trim() : null; };
    const v = document.querySelector('video');
    const pick = root => [...root.querySelectorAll('a[href*="/user/MS4w"]')].filter(a => !(a.getAttribute('href') || '').includes('?'));
    const vi = document.querySelector('[data-e2e="video-info"]');
    const links = (vi ? pick(vi) : []).concat(pick(document));
    const author = links.find(a => (a.innerText || '').trim()) || links[0] || null;
    const media = (window.__tpReq || []).filter(x => /douyinvod|mime_type=video|mime_type=audio|video_mp4|\\.mp4|\\.m4a|\\.m4s/i.test(x.u) && /^https?:/.test(x.u));
    const bases = {}; media.forEach(x => { const b = x.u.split('?')[0]; if (!bases[b]) bases[b] = { url: x.u, via: x.via }; });
    return { title: document.title.slice(0, 80), desc: (q('video-desc') || '').slice(0, 300),
             author_name: author ? author.innerText.trim().slice(0, 40) : null, author_href: author ? author.href.split('?')[0] : null,
             digg: q('video-player-digg'), comment: q('feed-comment-icon'), collect: q('video-player-collect'), share: q('video-player-share'),
             pub: q('detail-video-publish-time'), duration: v ? v.duration : null, hasVideo: !!v, hook: !!window.__tpReq, href: location.href,
             streams: Object.values(bases).slice(0, 4),
             blocked: /验证|请完成|滑动|页面不见/.test(document.body.innerText.slice(0, 400)) };
  })()`
  // Read the first 64 KB of a stream: total size from content-range, track kinds from the mp4 'hdlr' boxes,
  // and whether the samples are encrypted ('encv' / 'enca'). Nothing is kept.
  const HEAD = url => `(async () => {
    const r = await fetch(${JSON.stringify(url)}, { headers: { Range: 'bytes=0-65535' } });
    const buf = new Uint8Array(await r.arrayBuffer());
    const cr = r.headers.get('content-range') || '';
    const total = parseInt(cr.split('/')[1] || '0') || (r.status === 200 ? buf.length : 0);
    const s = String.fromCharCode.apply(null, buf.subarray(0, Math.min(buf.length, 65536)));
    const scan = (str, kinds) => { let i = -1; while ((i = str.indexOf('hdlr', i + 1)) >= 0) { const k = str.substr(i + 12, 4); if ((k === 'soun' || k === 'vide') && !kinds.includes(k)) kinds.push(k); } return kinds; };
    const kinds = scan(s, []);
    let enc = /encv|enca|sinf|tenc/.test(s);
    // A non-streaming mp4 keeps its index ('moov') at the end: read the last 512 KB too.
    if (!kinds.length && total > 65536) {
      const t = await fetch(${JSON.stringify(url)}, { headers: { Range: 'bytes=' + Math.max(65536, total - 524288) + '-' + (total - 1) } });
      const tb = new Uint8Array(await t.arrayBuffer()); let ts = '';
      for (let j = 0; j < tb.length; j += 0x8000) ts += String.fromCharCode.apply(null, tb.subarray(j, j + 0x8000));
      scan(ts, kinds); enc = enc || /encv|enca|sinf|tenc/.test(ts);
    }
    return { status: r.status, ctype: r.headers.get('content-type'), total, kinds,
             mp4: /ftyp|styp|moov/.test(s.slice(0, 64)), encrypted: enc };
  })()`
  try {
    await page.cdp('Page.addScriptToEvaluateOnNewDocument', { source: HOOK })
    await page.goto('https://www.douyin.com/video/' + ID)
    let m = null
    for (let k = 0; k < 25; k++) { await page.waitForTimeout(1000); m = await ev(META); if (k >= 8 && m.comment && m.streams.length) break }
    const { streams, ...meta } = m
    Object.assign(out, meta)
    if (m.blocked || !m.comment) throw new Error('读不到评论数：疑似受限，或视频已删除、设为私密')
    // A removed or wrong id can land on another video (feed or ad). Only save when this page is the requested video.
    if (!String(m.href || '').includes('/video/' + ID) || !m.pub) throw new Error('当前页面不是这条视频的详情页（可能已删除或链接有误），不保存')
    if (!m.hasVideo) throw new Error('页面上没有视频播放器：可能是图文作品，不支持')
    if (!m.hook) throw new Error('记录请求的脚本没有生效，停')
    if (!streams.length) throw new Error('播放器没有请求明文媒体流，不支持本条')
    for (const st of streams) {
      try { Object.assign(st, await ev(HEAD(st.url))) } catch (e) { st.err = String(e.message || e).slice(0, 120) }
      st.kind = st.kinds ? (st.kinds.length === 2 ? 'av' : st.kinds[0] === 'soun' ? 'audio' : st.kinds[0] === 'vide' ? 'video' : 'unknown') : 'unknown'
      out.streams.push({ via: st.via, status: st.status, ctype: st.ctype, total: st.total, kind: st.kind, mp4: st.mp4, encrypted: st.encrypted, err: st.err || null })
    }
    const ok = streams.filter(s => !s.err && (s.status === 206 || s.status === 200) && s.mp4 && !s.encrypted && s.total > 0)
    if (streams.some(s => s.encrypted)) throw new Error('媒体流是加密的，不支持本条（不做任何绕过）')
    const by = k => ok.filter(s => s.kind === k).sort((a, b) => b.total - a.total)[0]
    let pick = []
    if (WANT === 'audio') pick = by('audio') ? [by('audio')] : by('av') ? [by('av')] : []
    else pick = by('av') ? [by('av')] : (by('audio') && by('video')) ? [by('audio'), by('video')] : []
    if (!pick.length) throw new Error('没有找到可用的明文' + (WANT === 'audio' ? '音轨' : '音画') + '流，不支持本条')
    for (const st of pick) {
      const key = st.kind
      const got = await ev(`(async () => {
        const r = await fetch(${JSON.stringify(st.url)}, { headers: { Range: 'bytes=0-${st.total - 1}' } });
        const b = new Uint8Array(await r.arrayBuffer());
        window.__tpBuf = window.__tpBuf || {}; window.__tpBuf[${JSON.stringify(key)}] = b;
        return { status: r.status, len: b.length, cr: r.headers.get('content-range') };
      })()`)
      if (got.len !== st.total) throw new Error('取回 ' + got.len + ' 字节，content-range 总长 ' + st.total + '，不完整')
      let seq = 0
      for (let off = 0; off < got.len; off += CHUNK, seq++) {
        const b64 = await ev(`(() => { const b = window.__tpBuf[${JSON.stringify(key)}].subarray(${off}, ${off + CHUNK}); let s = '';
          for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000)); return btoa(s); })()`)
        console.log('@@CHUNK@@ ' + key + ' ' + seq + ' ' + b64)
      }
      await ev(`(() => { delete window.__tpBuf[${JSON.stringify(key)}]; return 1 })()`)
      out.saved.push({ kind: key, bytes: got.len, total: st.total, pieces: seq })
    }
  } catch (e) { out.stop = String(e.message || e).slice(0, 200) }
  out.ended = new Date().toISOString()
  console.log('@@RESULT@@ ' + JSON.stringify(out))
})();
