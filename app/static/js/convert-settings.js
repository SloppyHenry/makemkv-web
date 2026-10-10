// Einstellungsabschnitt „Konvertierung & Presets“: Standard je Disc-Art, Preset-Verwaltung, Parallelität/Segmente, Fähigkeiten. Besitzer: PF.
// Presets anlegen/ändern/löschen wirkt sofort (eigene Endpunkte); Standard-Zuordnung, „Gleichzeitige Dateien“ und „Segmente“ speichert die Seite (collect()).
import { $, api, esc, toast } from './core.js';
import { loadMeta, metaNow, reloadMeta, strip } from './convert-meta.js';
import { mountConvertEditor } from './convert-editor.js';
import { registerSettingsSection } from './registry.js';

const KINDS = [['bluray', 'Blu-ray'], ['dvd', 'DVD'], ['uhd', 'UHD-Blu-ray']];
let root = null, saved = {}, editors = {};
const spec = c => `${c.video.codec === 'hw' ? c.video.hw : c.video.codec} ${c.video.bits}-bit · ${c.video.codec === 'copy' ? 'Video kopieren' : (metaNow().codecs[c.video.codec].unit || 'RF') + ' ' + c.quality.crf}${c.video.speed ? ' · ' + c.video.speed : ''}`;

function defaultsHtml(m){
  return `<div><h4 class="cvs-h">Standard je Disc-Art</h4><div class="two" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">${KINDS.map(([k, label]) => {
    const cur = m.defaults[k] ? m.defaults[k].id : '';
    return `<div><label for="cvs-def-${k}">${label}</label><select class="input" id="cvs-def-${k}" data-default="${k}">${cur ? '' : '<option value="">Eigene Vorgabe (aus einer älteren Version)</option>'}${m.presets.map(p => `<option value="${esc(p.id)}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>`;
  }).join('')}</div><p class="help" style="margin:6px 0 0">Dieses Preset ist bei einer neu eingelegten Disc dieser Art vorgewählt und gilt in der Bibliothek als Grundlage der Einsparungs-Schätzung.</p></div>`;
}
function tableHtml(m){
  const open = Object.keys(editors);
  return `<div><h4 class="cvs-h">Presets</h4><div class="table-wrap"><table class="cv-table"><thead><tr><th>Name</th><th>Werte</th><th>Wofür</th><th></th></tr></thead><tbody>${m.presets.map(p => `<tr data-row="${esc(p.id)}">
    <td><b>${esc(p.name)}</b> <span class="tag">${p.builtin ? 'mitgeliefert' : 'eigen'}</span></td><td class="muted">${esc(spec(p.cfg))}</td><td class="muted">${esc(p.desc)}</td>
    <td style="text-align:right;white-space:nowrap"><button type="button" class="secondary" data-view="${esc(p.id)}" aria-expanded="${open.includes(p.id)}">${p.builtin ? 'Ansehen' : 'Bearbeiten'}</button>
    ${p.builtin ? ` <button type="button" class="secondary" data-copy="${esc(p.id)}">Kopieren</button>` : ` <button type="button" class="secondary danger" data-del="${esc(p.id)}">Löschen</button>`}</td></tr>
    <tr class="cvs-edit" data-edit="${esc(p.id)}" ${open.includes(p.id) ? '' : 'hidden'}><td colspan="4"></td></tr>`).join('')}</tbody></table></div></div>`;
}
function capsHtml(m){
  const c = m.caps, names = {x265: 'x265', x264: 'x264', svtav1: 'SVT-AV1'};
  const chips = [...Object.entries(names).map(([k, n]) => `<span>${n} ${c.codecs.includes(k) ? '✓' : '✗ fehlt'}</span>`), `<span>Hardware: ${c.hw.length ? esc(c.hw.join(', ')) : 'keine gemeldet'}</span>`,
    `<span>Opus ${c.audio.includes('opus') ? '✓' : '✗'}</span>`, `<span>HDR→SDR ${c.filters.includes('zscale') ? '✓' : '✗'}</span>`, `<span>${m.stats.count} gemessene Konvertierungen</span>`];
  return `<div><h4 class="cvs-h">Fähigkeiten dieses Rechners</h4><div class="cv-chips">${chips.join('')}</div></div>`;
}

function openEditor(id){
  const m = metaNow(), p = m.presets.find(x => x.id === id), row = $(`tr[data-edit="${CSS.escape(id)}"] td`, root); if(!p || !row) return;
  row.parentElement.hidden = false;
  row.innerHTML = `<div class="cvs-box">${p.builtin ? '<p class="hint" style="margin:0 0 8px">Mitgelieferte Presets lassen sich nicht ändern. Mit „Kopieren“ entsteht ein eigenes Preset, das du anpassen kannst.</p>'
    : `<div class="two" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-bottom:10px"><div><label for="cvs-n-${esc(id)}">Name</label><input class="input" id="cvs-n-${esc(id)}" value="${esc(p.name)}" maxlength="60"></div>
      <div><label for="cvs-d-${esc(id)}">Wofür (kurz)</label><input class="input" id="cvs-d-${esc(id)}" value="${esc(p.desc)}" maxlength="200"></div></div>`}
    <div data-ed></div>${p.builtin ? '' : '<div class="rowend" style="margin-top:10px"><button type="button" class="secondary" data-cancel>Schließen</button><button type="button" class="primary" style="width:auto" data-save>Preset speichern</button></div>'}</div>`;
  let cur = strip(p.cfg);
  editors[id] = {ed: mountConvertEditor($('[data-ed]', row), p.cfg, {mode: 'full', noCards: true, readonly: p.builtin, onChange: c => { cur = c; }}), get: () => cur};
  $(`[data-view="${CSS.escape(id)}"]`, root).setAttribute('aria-expanded', 'true');
}
function closeEditor(id){
  if(editors[id]){ editors[id].ed.destroy(); delete editors[id]; }
  const row = $(`tr[data-edit="${CSS.escape(id)}"]`, root); if(row){ row.hidden = true; row.firstElementChild.innerHTML = ''; }
  const b = $(`[data-view="${CSS.escape(id)}"]`, root); if(b) b.setAttribute('aria-expanded', 'false');
}
async function refresh(){
  const keep = {}; document.querySelectorAll('[data-default]').forEach(s => { keep[s.dataset.default] = s.value; });
  Object.keys(editors).forEach(closeEditor);
  const m = await reloadMeta();
  $('[data-slot=table]', root).innerHTML = tableHtml(m);
  $('[data-slot=defaults]', root).innerHTML = defaultsHtml(m);
  for(const [k, v] of Object.entries(keep)){ const s = $(`[data-default="${k}"]`, root); if(s && [...s.options].some(o => o.value === v)) s.value = v; }
}
async function onClick(e){
  const t = e.target, b = t.closest('button'); if(!b) return;
  try{
    if(b.dataset.view){ const id = b.dataset.view; editors[id] ? closeEditor(id) : openEditor(id); }
    else if(b.dataset.copy){
      const p = metaNow().presets.find(x => x.id === b.dataset.copy), n = await api('/api/convert/presets', 'POST', {name: p.name + ' (Kopie)', desc: p.desc, cfg: strip(p.cfg)});
      await refresh(); openEditor(n.id); toast('Kopie angelegt – jetzt anpassen und speichern.');
    } else if(b.dataset.del){
      const p = metaNow().presets.find(x => x.id === b.dataset.del);
      if(!confirm(`Preset „${p.name}“ löschen?`)) return;
      await api('/api/convert/presets/' + encodeURIComponent(p.id), 'DELETE'); await refresh(); toast('Preset gelöscht ✓');
    } else if(b.hasAttribute('data-save') || b.hasAttribute('data-cancel')){
      const id = b.closest('tr').dataset.edit;
      if(b.hasAttribute('data-save')){
        await api('/api/convert/presets/' + encodeURIComponent(id), 'PATCH', {name: $(`#cvs-n-${CSS.escape(id)}`, root).value, desc: $(`#cvs-d-${CSS.escape(id)}`, root).value, cfg: editors[id].get()});
        toast('Preset gespeichert ✓');
      }
      await refresh();
    }
  }catch{ /* api() zeigt den Fehler an */ }
}

registerSettingsSection({
  id: 'convert', label: 'Konvertierung & Presets', order: 50, icon: '⎘', description: 'Mitgelieferte und eigene Presets, Standard je Disc-Art, Parallelität.',
  async render(el, s){
    root = el; Object.keys(editors).forEach(id => { editors[id].ed.destroy(); }); editors = {}; saved = (s.convert && s.convert.default_for) || {};
    el.innerHTML = '<p class="hint">Lädt …</p>';
    const m = await loadMeta();
    el.innerHTML = `<div data-slot="defaults">${defaultsHtml(m)}</div><div data-slot="table">${tableHtml(m)}</div>
      <div class="two"><div><label for="s-conv_parallel">Gleichzeitige Dateien (Konvertierung)</label><input type="number" id="s-conv_parallel" min="1" max="8" step="1" value="${+s.conv_parallel || 1}">
        <p class="help" style="margin:4px 0 0">Mehr als eine Datei gleichzeitig lohnt nur auf Rechnern mit vielen Kernen.</p></div>
        <div><label for="s-conv_segments">Segmente pro Film (0 = automatisch)</label><input type="number" id="s-conv_segments" min="0" max="12" step="1" value="${+s.conv_segments || 0}">
        <p class="help" style="margin:4px 0 0">Lange Filme werden zeitlich geteilt und parallel kodiert (alle Software-Codecs); 1 = nie teilen. Bei „0“ entscheidet die App nach freien Kernen und RAM.</p></div></div>
      ${capsHtml(m)}`;
    if(!el._cvs){ el._cvs = true; el.addEventListener('click', onClick); }
  },
  collect(){
    const df = {...saved};
    document.querySelectorAll('[data-default]').forEach(sel => { if(sel.value) df[sel.dataset.default] = sel.value; });
    return {general: {conv_parallel: +($('#s-conv_parallel') || {}).value || 1, conv_segments: Math.max(0, +($('#s-conv_segments') || {}).value || 0)}, convert: {default_for: df}};
  },
});
