// Headless mode: settings section and the "Headless mode" panel in the drives view (state, log, test detection).
import { $, S, ago, api, delegate, esc, setHtml, toast } from './core.js';
import { curDrive } from './drives.js';
import { onState, registerPanel, registerSettingsSection } from './registry.js';

const MODE = {movie: 'movie', series: 'series', unsure: 'unsure – all titles', manual: 'by hand', memory: 'as last picked by hand'};
const STATE_CLS = {done: 'ok', error: 'busy', manual: 'warn', cancelled: 'warn', waiting: 'warn'};

registerSettingsSection({
  id: 'headless', label: 'Headless mode', order: 15, icon: '⏏', description: 'Insert a disc, done: rip the right titles and eject, without any interaction.',
  render(el, s){
    const h = {enabled: false, use_db: true, convert: false, ...(s.headless || {})};
    el.innerHTML = `<label class="chk"><input class="check" type="checkbox" id="s-hl-enabled" ${h.enabled ? 'checked' : ''}> Turn on headless mode</label>
      <label class="chk"><input class="check" type="checkbox" id="s-hl-db" ${h.use_db ? 'checked' : ''}> Determine titles via TheDiscDB (internet, only the disc's identifier is sent)</label>
      <label class="chk"><input class="check" type="checkbox" id="s-hl-conv" ${h.convert ? 'checked' : ''}> Convert after ripping (default preset for the disc type)</label>
      <div class="help hl-help">Inserted discs are analyzed right away. The titles are determined in this order:
        <ol><li><b>Memory</b>: the same disc was ripped by hand before (also on another machine) – the same titles and names.</li>
        <li><b>TheDiscDB</b>: exactly the main feature or the episodes, with names like "Series S01E02".</li>
        <li><b>TMDB</b> (with a key under Media): the title with the movie's runtime or the titles with the episode length.</li>
        <li><b>Structure</b>: one long title = movie, several titles of equal length = series (without play-all). Not clear-cut: all titles without duplicates and play-all;
        if that would be more than twice the data on the disc, nothing is ripped ("by hand").</li></ol>
        Afterwards the disc is always ejected, even on errors – only if you cancel yourself does it stay in. If you insert a "by hand" disc again,
        it stays in the drive: choose titles and rip, the memory remembers the selection. The switch and the log are also shown directly under Drives.</div>`;
  },
  collect(){
    return {headless: {enabled: $('#s-hl-enabled').checked, use_db: $('#s-hl-db').checked, convert: $('#s-hl-conv').checked}};
  },
});

function item(e){
  const picked = e.picked ? (e.picked.length ? e.picked.join(', ') : '–') : (e.titles.length ? `${e.titles.length} title${e.titles.length === 1 ? '' : 's'}` : '–');
  const skipped = (e.skipped || []).map(([n, why]) => `${n}: ${why}`).join(' · ');
  const head = [e.source, MODE[e.mode]].filter(Boolean).join(' · ');
  return `<div class="hl-item" title="${esc(e.reasons.join(' · '))}">
    <div class="hl-top"><strong title="${esc(e.folder || e.disc)}">${esc(e.disc || e.folder || 'Disc')}</strong><span class="st ${STATE_CLS[e.state] || ''}">${esc(e.state_text)}</span>
      <span class="spacer"></span><span class="muted">${esc(e.drive)} · ${esc(ago(e.t))}${e.ejected ? ' · ejected' : ''}</span></div>
    ${head ? `<div class="hl-why">${esc(head)}</div>` : ''}
    ${e.mode && e.mode !== 'manual' || e.picked ? `<div class="hl-sub"><b>Taken:</b> ${esc(picked)}</div>` : ''}
    ${skipped ? `<div class="hl-why"><b>Not taken:</b> ${esc(skipped)}</div>` : ''}
    ${e.message ? `<div class="hl-why ${e.state === 'error' ? 'err' : ''}">${esc(e.message)}</div>` : ''}
  </div>`;
}

// Machine of the selected drive: its headless mode is shown and switched (null = old version without headless)
function target(){
  const d = curDrive();
  if(d && d.host){ const p = (S.peers || []).find(x => x.name === d.host); return {d, host: d.host, base: `/api/peer/${d.host}`, h: (p && p.headless) || null}; }
  return {d, host: '', base: '/api', h: S.headless};
}

// small switch at the top of the drive bar (immediately visible on every screen)
function barSwitch(){
  const bar = $('#drivebar');
  if(!bar || !S || !S.headless) return;
  let el = $('#hlBar');
  if(!el){
    bar.insertAdjacentHTML('beforeend', `<label class="hl-switch hl-bar" id="hlBar" title="Headless mode: rip inserted discs automatically and eject them">
      <span class="hl-bar-lbl">Headless</span><input type="checkbox" class="hl-toggle" role="switch" aria-label="Headless mode"><span class="hl-knob" aria-hidden="true"></span></label>`);
    el = $('#hlBar');
  }
  const cb = el.querySelector('input');
  const t = target();
  el.hidden = !t.h;
  el.title = `Headless mode${t.host ? ' on ' + t.host : ''}: rip inserted discs automatically and eject them`;
  el.querySelector('.hl-bar-lbl').textContent = t.host ? `Headless ${t.host}` : 'Headless';
  if(!cb.dataset.busy && t.h) cb.checked = t.h.enabled;
}

function render(){
  barSwitch();
  const pn = $('#hlPanel');
  if(!pn || !S) return;
  const t = target(), h = t.h;
  pn.hidden = !h;
  if(!h) return;
  setHtml($('#hlHost'), t.host ? '· ' + esc(t.host) : '');
  const st = $('#hlState');
  st.className = 'st' + (h.enabled ? ' ok' : ''); st.textContent = h.enabled ? 'on' : 'off';
  document.querySelectorAll('.hl-toggle').forEach(cb => { if(!cb.dataset.busy) cb.checked = h.enabled; });
  const d = t.d, ok = !!(d && d.disc && !d.job), test = $('#hlTest'), con = $('#hlContrib');
  test.disabled = !ok; con.disabled = !ok || !!t.host;
  test.title = 'Check the title choice for the disc in the selected drive without ripping';
  con.title = d && d.host ? 'Only for drives of this machine' : 'Report the titles of this disc to TheDiscDB (with preview, TheDiscDB reviews before publishing)';
  $('#hlClear').hidden = !h.history.length;
  const mem = h.memory ? ` Memory: ${h.memory} disc${h.memory === 1 ? '' : 's'} picked by hand.` : '';
  setHtml($('#hlNote'), esc((h.enabled ? 'Inserted discs are detected, ripped and ejected automatically.'
    : 'Off. Turn it on with the switch; "Test detection" shows what would be ripped.') + mem));
  setHtml($('#hlList'), h.history.length ? h.history.map(item).join('') : '<div class="empty">No disc in headless mode yet.</div>');
}
onState(render);

delegate('#hlTest', 'click', async (e, b) => {
  const t = target(); if(!t.d) return;
  b.disabled = true;
  try{
    const r = await api(`${t.base}/headless/test/${t.d.id}`);
    toast(`${r.source}: ${MODE[r.mode] || r.mode}${r.picks.length ? ` – ${r.picks.length} title${r.picks.length === 1 ? '' : 's'}` : ''}`);
  }catch{ /* api() shows the message */ }
  render();
});
delegate('.hl-toggle', 'change', async (e, cb) => {
  const want = cb.checked;
  cb.dataset.busy = '1'; cb.disabled = true;
  try{
    const t = target();
    await api(`${t.base}/headless/enable`, 'POST', {enabled: want});
    const on = t.host ? ` on ${t.host}` : '';
    toast(want ? `Headless mode${on} on: from the next inserted disc on, it is ripped and ejected automatically.` : `Headless mode${on} off.`);
  }catch{ cb.checked = !want; }
  delete cb.dataset.busy; cb.disabled = false;
  render();
});
delegate('#hlClear', 'click', async () => { const t = target(); try{ await api(`${t.base}/headless/clear`); }catch{} });

registerPanel({view: 'drives', slot: 'right', order: 5, id: 'hlPanel', html: `<section class="panel" id="hlPanel" hidden>
  <div class="panel-head"><span class="mini-icon">⏏</span><h2>Headless mode <span class="sub" id="hlHost"></span></h2>
    <label class="hl-switch" title="Turn headless mode on or off"><input type="checkbox" class="hl-toggle" role="switch" aria-label="Headless mode"><span class="hl-knob" aria-hidden="true"></span><span class="st" id="hlState"></span></label>
    <span class="spacer"></span>
    <button type="button" class="secondary" id="hlTest">Test detection</button><button type="button" class="secondary" id="hlContrib">Report to TheDiscDB</button>
    <button type="button" class="secondary" id="hlClear" hidden>Clear</button></div>
  <div class="hl-note muted" id="hlNote"></div>
  <div class="hl-list" id="hlList"></div>
</section>`});
