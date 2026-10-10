// Bibliothek: Detailbereich zur gewählten Datei (Spuren, Einsparung, Aktionen, eingebetteter Player von PD). Besitzer: PF.
import { api, baseName, esc, fmtB, fmtD } from './core.js';
import { L, audioName, byPath, codecName, resName, saveOf, selectable } from './library-model.js';
import { stBadge, titleOf } from './library-render.js';
import { fmtT } from './convert-predict.js';
import { getLibraryActions } from './registry.js';

let handle = null, handlePath = '', est = {};          // eingebetteter Player, Dauer-Schätzungen je Datei

export function stopPlayer(){ if(handle){ try{ handle.destroy(); }catch{ /* Player schon weg */ } handle = null; handlePath = ''; } }
async function loadEst(f, cb){
  if(est[f.path] !== undefined) return; est[f.path] = null;
  try{
    const m = await (await fetch('/api/convert/meta')).json(), cfg = (m.defaults[({sd: 'dvd', hd: 'bluray', uhd: 'uhd'})[f.kind] || 'bluray'] || m.defaults.bluray).cfg;
    const r = await api('/api/convert/estimate', 'POST', {cfg, paths: [f.path]}); est[f.path] = r.nodes; cb();
  }catch{ est[f.path] = []; }
}
export const clearEst = () => { est = {}; };

export function actionButtons(f, where, rest = ''){
  return getLibraryActions().filter(a => a.id !== 'play' && !a.primary && a.when([f], {where})).map(a => `<button type="button" class="secondary" data-lact="${esc(a.id)}" data-path="${esc(f.path)}">${esc(a.icon ? a.icon + ' ' : '')}${esc(a.label)}</button>`).join(' ') + rest;
}
export function detailHtml(f){
  if(!f) return '<p class="muted" style="font-size:12px;margin:0">Datei wählen, um Einzelheiten zu sehen.</p>';
  const i = f.info, ok = selectable(f), play = getLibraryActions().find(a => a.id === 'play' && a.when([f], {where: 'detail'})), sv = saveOf(f), n = est[f.path];
  const loc = n && n.find(x => x.local), nm = f.m && f.m.title ? `${f.m.title}${f.m.year ? ' (' + f.m.year + ')' : ''}` : '';
  const kv = i ? `<dl class="lib-kv"><dt>Video</dt><dd>${esc(codecName(i.codec))} · ${i.w}×${i.h}${i.pix ? ' · ' + (/10/.test(i.pix) ? '10 Bit' : '8 Bit') : ''}${i.hdr_fmt ? ' · ' + esc(i.hdr_fmt) : ''}${i.interlaced ? ' · interlaced' : ''}</dd>
    <dt>Bitrate</dt><dd>${i.bitrate ? (i.bitrate / 1e6).toFixed(1).replace('.', ',') + ' Mb/s' : '—'}${i.fps ? ' · ' + String(i.fps).replace('.', ',') + ' Bilder/s' : ''}</dd><dt>Dauer</dt><dd>${i.dur ? fmtD(i.dur) : '—'}${i.chapters ? ` · ${i.chapters} Kapitel` : ''}</dd><dt>Größe</dt><dd>${fmtB(f.size)}</dd></dl>
    <div class="lib-tracks">${(i.alist || []).map(a => `<div><span>Ton</span>${esc(audioName(a))}${a.lang ? ' · ' + esc(a.lang) : ''}${a.title ? ' · ' + esc(a.title) : ''}</div>`).join('')}${(i.slist || []).length ? `<div><span>Unter.</span>${esc([...new Set(i.slist.map(s => s.lang || '?'))].join(', '))} (${i.slist.length}${i.slist.some(s => s.forced) ? ', erzwungen' : ''})</div>` : ''}</div>` : '';
  const savebox = i && sv ? `<div class="lib-save"><small>Mit dem Standard-Preset${f.est && f.est.preset ? ' „' + esc(f.est.preset) + '“' : ''}</small><b>≈ ${fmtB(f.est.bytes)} <span>(−${Math.round((1 - f.est.bytes / f.size) * 100)} %)</span></b>
    <small>Ersparnis ca. ${fmtB(sv)}${loc && loc.ok ? ` · Dauer hier ca. ${fmtT(loc.secs)}` : ''}${f.est.samples >= 2 ? ` · aus ${f.est.samples} Konvertierungen` : ' · Schätzung'}</small></div>` : '';
  const done = i && i.enc_note ? `<p class="hint" style="margin:0">Konvertiert mit: ${esc(i.enc_note)}</p>` : '';
  const warn = i && i.dovi ? '<p class="hint warn" style="margin:0">Enthält Dolby Vision: bei der Konvertierung geht diese Ebene verloren (die HDR10-Basis bleibt). Vor dem Start fragt die Bibliothek nach.</p>' : '';
  const run = f.live && f.live.id ? `<button type="button" class="secondary" data-fskip="${f.live.id}" data-host="${esc(f.live.host || '')}">Überspringen</button> <button type="button" class="secondary danger" data-fcancel="${f.live.id}" data-host="${esc(f.live.host || '')}">Abbrechen</button>` : '';
  const rest = `${f.live || f.locked ? '' : `<button type="button" class="secondary" data-rename="${esc(f.path)}">✎ Umbenennen</button>`} <a class="secondary" href="/api/download?path=${encodeURIComponent(f.path)}">Download</a> ${f.live || f.locked ? '' : `<button type="button" class="secondary danger" data-del="${esc(f.path)}">Löschen</button>`} ${run}`;
  return `<div style="display:flex;gap:10px"><div class="lib-thumb big" style="${f.m && f.m.poster ? `background:url('${esc(f.m.poster)}') center/cover` : ''}">${f.m && f.m.poster ? '' : esc(i ? resName(i) : '')}</div>
    <div style="min-width:0"><h3>${esc(nm || baseName(f.path))}</h3><div class="sub">${esc(f.path)}</div><div style="margin-top:6px">${stBadge(f)}</div></div></div>${kv}${done}${warn}${savebox}
    ${play ? `<div class="lib-player" data-playslot ${L.play === f.path ? '' : 'hidden'}></div>` : ''}
    <div class="lib-acts">${play ? `<button type="button" class="primary" data-playtoggle="${esc(f.path)}">${L.play === f.path ? '■ Player schließen' : '▶ Abspielen'}</button>` : ''}<button type="button" class="secondary" data-cvopen ${ok ? '' : 'disabled'}>Konvertieren …</button>
      ${actionButtons(f, 'detail', rest)}</div>${i ? '' : `<p class="hint" style="margin:0">${esc(f.errText || 'Die Datei wird geprüft oder lässt sich nicht lesen.')}</p>`}`;
}
/** Detailbereich zeichnen; zeichnet nur bei Änderung neu (der eingebettete Player läuft weiter). */
export function drawDetail(box, onLoaded){
  const f = byPath(L.cur);
  if(f) loadEst(f, onLoaded);
  const sig = f ? [f.path, f.status, f.live && f.live.status, f.live ? Math.round(f.live.pct * 20) : '', f.size, f.est && f.est.bytes, L.play === f.path, est[f.path] ? 1 : 0, f.m && f.m.title, f.errText].join('|') : '';
  if(box.dataset.sig === sig) return;
  if(!f || handlePath !== f.path || L.play !== f.path) stopPlayer();
  const live = handle && handlePath === (f && f.path) ? box.querySelector('[data-playslot]') : null;          // laufenden Player behalten
  box.dataset.sig = sig; box.innerHTML = detailHtml(f);
  let slot = box.querySelector('[data-playslot]');
  if(live && slot){ slot.replaceWith(live); slot = live; }
  if(f && slot && L.play === f.path && handlePath !== f.path){
    handlePath = f.path;
    import('./player.js').then(m => { if(L.play === f.path && handlePath === f.path && document.contains(slot)) handle = m.mountPlayer(slot, f.path); }).catch(() => { slot.textContent = 'Der Player ist nicht verfügbar.'; });
  }
}
export { titleOf };
