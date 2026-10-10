// Bibliothek: Auswahlleiste unten (Summe, Preset, „Ausführen auf“, Konvertieren), Editor als Seitenleiste und der Start der Konvertierung. Besitzer: PF.
import { $, api, baseName, esc, fmtB, toast } from './core.js';
import { L, saveOf, selectedFiles } from './library-model.js';
import { fmtT } from './convert-predict.js';
import { clone, loadMeta, metaNow } from './convert-meta.js';
import { mountConvertEditor } from './convert-editor.js';
import { getLibraryActions } from './registry.js';

let editor = null, timer = null, onChanged = () => {};
export const setOnChanged = f => { onChanged = f; };
const DISC = {sd: 'dvd', hd: 'bluray', uhd: 'uhd'};

// ---- Einstellungen je Datei: gewähltes/angepasstes Preset, sonst Standard je Disc-Art
export function cfgFor(f){
  if(L.cfg) return L.cfg;
  const m = metaNow(), d = m && (m.defaults[DISC[f.kind] || 'bluray'] || m.defaults.bluray);
  return d ? {...clone(d.cfg), convert: true} : null;
}
function cfgGroups(files){
  const g = new Map();
  for(const f of files){ const c = cfgFor(f); if(!c) continue; const k = JSON.stringify(c); if(!g.has(k)) g.set(k, {cfg: c, files: []}); g.get(k).files.push(f); }
  return [...g.values()];
}
export function refreshEst(delay = 350){
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const fs = selectedFiles(); if(!fs.length){ L.est = null; return; }
    const cfg = cfgFor(fs[0]); if(!cfg) return;
    try{ L.est = await api('/api/convert/estimate', 'POST', {cfg, paths: fs.map(f => f.path)}); }catch{ return; }
    if(L.est.nodes && !L.est.nodes.some(n => (n.local ? 'local' : n.name) === L.target && n.ok)) L.target = 'local';
    onChanged('bar');
  }, delay);
}

function targetOptions(){
  const nodes = (L.est && L.est.nodes) || [{name: 'dieser Rechner', local: true, ok: true, secs: 0}];
  return nodes.map(n => { const v = n.local ? 'local' : n.name, t = n.ok ? `${n.local ? 'Dieser Rechner (' + n.name + ')' : n.name}${n.secs ? ' · ≈ ' + fmtT(n.secs) : ''}` : `${n.name} – ${n.reason.length > 60 ? n.reason.slice(0, 58) + ' …' : n.reason}`;
    return `<option value="${esc(v)}" ${n.ok ? '' : 'disabled'} ${v === L.target ? 'selected' : ''}>${esc(t)}</option>`; }).join('');
}
export function barHtml(){
  const fs = selectedFiles(), tot = fs.reduce((a, f) => a + f.size, 0), m = metaNow();
  const sv = L.cfg && L.est ? Math.max(0, L.est.in_bytes - L.est.out_bytes) : fs.reduce((a, f) => a + saveOf(f), 0);
  const acts = getLibraryActions().filter(a => !a.primary && a.when(fs, {where: 'bar'})).map(a => `<button type="button" class="secondary" data-baract="${esc(a.id)}">${esc(a.icon ? a.icon + ' ' : '')}${esc(a.label)}</button>`).join('');
  const presets = m ? m.presets.map(p => `<option value="${esc(p.id)}" ${L.preset === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('') : '';
  return `<b>${fs.length} Datei${fs.length === 1 ? '' : 'en'} · ${fmtB(tot)}</b><span class="sv">≈ ${fmtB(sv)} Ersparnis</span><span class="grow"></span>
    <select data-barpreset aria-label="Preset" title="Preset für die Konvertierung"><option value="auto" ${L.preset === 'auto' ? 'selected' : ''}>Preset: automatisch je Disc-Art</option>${presets}${L.preset === 'custom' ? '<option value="custom" selected>Angepasste Einstellung</option>' : ''}</select>
    <select data-bartarget aria-label="Ausführen auf" title="Auf welchem Rechner konvertiert wird">${targetOptions()}</select>${acts}
    <button type="button" class="secondary" data-cvopen>Anpassen …</button><button type="button" class="primary" style="width:auto" data-start ${fs.length ? '' : 'disabled'}>Konvertieren</button><button type="button" class="secondary" data-clear>Auswahl aufheben</button>`;
}
export function drawBar(box){
  const fs = selectedFiles();
  box.hidden = !fs.length;
  if(!fs.length){ box.dataset.h = ''; return; }
  if(box.contains(document.activeElement) && document.activeElement.tagName === 'SELECT') return;      // offene Auswahl nicht wegreißen
  const h = barHtml(); if(box.dataset.h !== h){ box.dataset.h = h; box.innerHTML = h; }
}

// ---- Seitenleiste mit dem Editor
export function drawSide(box){
  if(!L.cvOpen){ if(editor){ editor.destroy(); editor = null; } box.dataset.open = ''; return; }
  const fs = selectedFiles(), files = fs.map(f => ({path: f.path}));
  if(!editor){
    box.dataset.open = '1';
    box.innerHTML = '<h3>Konvertieren <span class="sp"></span><button type="button" class="secondary" data-cvclose>Schließen</button></h3><div data-ed></div>';
    const first = fs[0], start = (L.cfg || (first && cfgFor(first)) || null);
    editor = mountConvertEditor($('[data-ed]', box), start, {mode: 'side', files, target: L.target === 'local' ? '' : L.target,
      onChange: c => { L.cfg = {...c, convert: true}; L.preset = 'custom'; onChanged('bar'); refreshEst(); },
      onPrediction: est => { L.est = est; onChanged('bar'); }});
  }else editor.setFiles(files);
}
export function syncEditorToPreset(){
  if(editor && L.cvOpen){ const m = metaNow(), p = m && m.presets.find(x => x.id === L.preset); if(p) editor.set({...clone(p.cfg), convert: true}); }
}
export function closeSide(){ L.cvOpen = false; if(editor){ editor.destroy(); editor = null; } }

// ---- Start
export async function setPreset(id){
  L.preset = id;
  if(id === 'auto') L.cfg = null;
  else { const m = await loadMeta(), p = m.presets.find(x => x.id === id); if(p) L.cfg = {...clone(p.cfg), convert: true}; }
  syncEditorToPreset(); refreshEst(0); onChanged('bar');
}
export async function startConversion(){
  const fs = selectedFiles(); if(!fs.length) return;
  const groups = cfgGroups(fs), target = L.target, wo = target === 'local' ? 'auf diesem Rechner' : `auf ${target}`;
  const dv = fs.filter(f => f.info && f.info.dovi && groups.some(g => g.files.includes(f) && g.cfg.video.codec !== 'copy'));
  if(dv.length && !confirm(`Dolby Vision: ${dv.length === 1 ? '„' + baseName(dv[0].path) + '“ enthält' : dv.length + ' Dateien enthalten'} Dolby Vision.\n\nBei der Konvertierung geht diese Ebene verloren; die HDR10-Basisschicht bleibt erhalten. Trotzdem konvertieren?`)) return;
  if(!confirm(`${fs.length} Datei${fs.length === 1 ? '' : 'en'} ${wo} konvertieren?\n\nDas Original wird nach bestandener Prüfung (Länge, Spurzahl) GELÖSCHT und durch die konvertierte Datei ersetzt.`)) return;
  let started = 0; const skipped = [];
  for(const g of groups){
    try{ const r = await api('/api/convert/start', 'POST', {target, paths: g.files.map(f => f.path), convert: g.cfg}); started += r.started.length; skipped.push(...r.skipped); r.started.forEach(p => L.sel.delete(p)); }
    catch{ /* api() zeigt den Fehler an */ }
  }
  if(skipped.length) alert(`${started} gestartet, ${skipped.length} übersprungen:\n` + skipped.map(x => `• ${x.path}: ${x.why}`).join('\n'));
  else if(started) toast(`${started} Datei${started === 1 ? '' : 'en'} in die Warteschlange gestellt.`);
  onChanged('all');
}
