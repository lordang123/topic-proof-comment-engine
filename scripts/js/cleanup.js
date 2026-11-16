// Cleanup helper called by ego_run.py. Not run directly.
// __MODE__ = 'only'  : close the tabs of space __SPACE__ and finish it. If the user took it over, touch nothing (prints USER_OWNED).
// __MODE__ = 'sweep' : close leftover tp-* spaces owned by the agent (from crashed runs). Never touches user-owned spaces.
// deleteSpaces() can hang, so it is not used. finish({keep: []}) removes a space without closing ego.
(async () => {
  const MODE = '__MODE__', SPACE = '__SPACE__';
  const all = await listTaskSpaces();
  const closeAll = async (s) => {
    await switchTaskSpace(s.name);
    for (const t of await listTabs()) { try { await closeTab(t.id != null ? t.id : t.tabId); } catch (e) {} }
  };
  const finishIfSafe = async (name) => {
    const now = await listTaskSpaces();
    const mine = now.find(s => s.name === name);
    if (!mine) return 'GONE';
    const elsewhere = now.filter(s => s.name !== name).reduce((n, s) => n + (s.recentTabTitles || []).length, 0);
    // Finishing the last space with tabs could close the ego window; keep it in that case.
    if (mine.ownership === 'agent' && elsewhere > 0) { await (await taskSpace(mine.id)).finish({ keep: [] }); return 'FINISHED'; }
    return 'KEEP';
  };
  if (MODE === 'only') {
    const s = all.find(x => x.name === SPACE);
    if (!s) { cliLog('FINISHED ' + SPACE + ' (no space)'); return; }
    if (s.ownership === 'user') { cliLog('USER_OWNED ' + SPACE); return; }
    try { await closeAll(s); cliLog(await finishIfSafe(SPACE) + ' ' + SPACE); }
    catch (e) { cliLog((/does not exist/.test(e.message) ? 'FINISHED ' : 'FINISH ERR ') + SPACE + ' ' + String(e.message).slice(0, 120)); }
    return;
  }
  const stale = all.filter(s => s.name.startsWith('tp-') && s.name !== SPACE && s.ownership === 'agent');
  for (const s of stale) {
    try { await closeAll(s); cliLog('SWEPT ' + s.name + ' ' + await finishIfSafe(s.name)); }
    catch (e) { cliLog('SWEEP ERR ' + s.name + ' ' + String(e.message).slice(0, 100)); }
  }
})()
