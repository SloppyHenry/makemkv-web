// Settings section "Conversion & presets": default per disc type, preset management, parallelism/segments, capabilities. Owner: PF.
// Creating/changing/deleting presets takes effect immediately (own endpoints); default assignment, "Files at the same time" and "Segments" are saved by the page (collect()).
import { $, api, esc, toast } from './core.js';
import { loadMeta, metaNow, reloadMeta, strip } from './convert-meta.js';
import { mountConvertEditor } from './convert-editor.js';
import { registerSettingsSection } from './registry.js';

const KINDS = [['bluray', 'Blu-ray'], ['dvd', 'DVD'], ['uhd', 'UHD Blu-ray']];
let root = null, saved = {}, editors = {};
const spec = c => `${c.video.codec === 'hw' ? c.video.hw : c.video.codec} ${c.video.bits}-bit · ${c.video.codec === 'copy' ? 'Copy video' : (metaNow().codecs[c.video.codec].unit || 'RF') + ' ' + c.quality.crf}${c.video.speed ? ' · ' + c.video.speed : ''}`;

function defaultsHtml(m){
  return `<div><h4 class="cvs-h">Default per disc type</h4><div class="two" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">${KINDS.map(([k, label]) => {
    const cur = m.defaults[k] ? m.defaults[k].id : '';
    return `<div><label for="cvs-def-${k}">${label}</label><select class="input" id="cvs-def-${k}" data-default="${k}">${cur ? '' : '<option value="">Custom default (from an older version)</option>'}${m.presets.map(p => `<option value="${esc(p.id)}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>`;
  }).join('')}</div><p class="help" style="margin:6px 0 0">This preset is preselected for a newly inserted disc of this type and is the basis of the savings estimate in the library.</p></div>`;
}
function tableHtml(m){
  const open = Object.keys(editors);
  return `<div><h4 class="cvs-h">Presets</h4><div class="table-wrap"><table class="cv-table"><thead><tr><th>Name</th><th>Values</th><th>Purpose</th><th></th></tr></thead><tbody>${m.presets.map(p => `<tr data-row="${esc(p.id)}">
    <td><b>${esc(p.name)}</b> <span class="tag">${p.builtin ? 'built-in' : 'custom'}</span></td><td class="muted">${esc(spec(p.cfg))}</td><td class="muted">${esc(p.desc)}</td>
    <td style="text-align:right;white-space:nowrap"><button type="button" class="secondary" data-view="${esc(p.id)}" aria-expanded="${open.includes(p.id)}">${p.builtin ? 'View' : 'Edit'}</button>
    ${p.builtin ? ` <button type="button" class="secondary" data-copy="${esc(p.id)}">Copy</button>` : ` <button type="button" class="secondary danger" data-del="${esc(p.id)}">Delete</button>`}</td></tr>
    <tr class="cvs-edit" data-edit="${esc(p.id)}" ${open.includes(p.id) ? '' : 'hidden'}><td colspan="4"></td></tr>`).join('')}</tbody></table></div></div>`;
}
function capsHtml(m){
  const c = m.caps, names = {x265: 'x265', x264: 'x264', svtav1: 'SVT-AV1'};
  const chips = [...Object.entries(names).map(([k, n]) => `<span>${n} ${c.codecs.includes(k) ? '✓' : '✗ missing'}</span>`), `<span>Hardware: ${c.hw.length ? esc(c.hw.join(', ')) : 'none reported'}</span>`,
    `<span>Opus ${c.audio.includes('opus') ? '✓' : '✗'}</span>`, `<span>HDR→SDR ${c.filters.includes('zscale') ? '✓' : '✗'}</span>`, `<span>${m.stats.count} measured conversions</span>`];
  return `<div><h4 class="cvs-h">Capabilities of this machine</h4><div class="cv-chips">${chips.join('')}</div></div>`;
}

function openEditor(id){
  const m = metaNow(), p = m.presets.find(x => x.id === id), row = $(`tr[data-edit="${CSS.escape(id)}"] td`, root); if(!p || !row) return;
  row.parentElement.hidden = false;
  row.innerHTML = `<div class="cvs-box">${p.builtin ? '<p class="hint" style="margin:0 0 8px">Built-in presets cannot be changed. "Copy" creates a preset of your own that you can adjust.</p>'
    : `<div class="two" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-bottom:10px"><div><label for="cvs-n-${esc(id)}">Name</label><input class="input" id="cvs-n-${esc(id)}" value="${esc(p.name)}" maxlength="60"></div>
      <div><label for="cvs-d-${esc(id)}">Purpose (short)</label><input class="input" id="cvs-d-${esc(id)}" value="${esc(p.desc)}" maxlength="200"></div></div>`}
    <div data-ed></div>${p.builtin ? '' : '<div class="rowend" style="margin-top:10px"><button type="button" class="secondary" data-cancel>Close</button><button type="button" class="primary" style="width:auto" data-save>Save preset</button></div>'}</div>`;
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
      const p = metaNow().presets.find(x => x.id === b.dataset.copy), n = await api('/api/convert/presets', 'POST', {name: p.name + ' (copy)', desc: p.desc, cfg: strip(p.cfg)});
      await refresh(); openEditor(n.id); toast('Copy created – now adjust and save it.');
    } else if(b.dataset.del){
      const p = metaNow().presets.find(x => x.id === b.dataset.del);
      if(!confirm(`Delete preset "${p.name}"?`)) return;
      await api('/api/convert/presets/' + encodeURIComponent(p.id), 'DELETE'); await refresh(); toast('Preset deleted ✓');
    } else if(b.hasAttribute('data-save') || b.hasAttribute('data-cancel')){
      const id = b.closest('tr').dataset.edit;
      if(b.hasAttribute('data-save')){
        await api('/api/convert/presets/' + encodeURIComponent(id), 'PATCH', {name: $(`#cvs-n-${CSS.escape(id)}`, root).value, desc: $(`#cvs-d-${CSS.escape(id)}`, root).value, cfg: editors[id].get()});
        toast('Preset saved ✓');
      }
      await refresh();
    }
  }catch{ /* api() shows the error */ }
}

registerSettingsSection({
  id: 'convert', label: 'Conversion & presets', order: 50, icon: '⎘', description: 'Built-in and custom presets, default per disc type, parallelism.',
  async render(el, s){
    root = el; Object.keys(editors).forEach(id => { editors[id].ed.destroy(); }); editors = {}; saved = (s.convert && s.convert.default_for) || {};
    el.innerHTML = '<p class="hint">Loading …</p>';
    const m = await loadMeta();
    el.innerHTML = `<div data-slot="defaults">${defaultsHtml(m)}</div><div data-slot="table">${tableHtml(m)}</div>
      <div class="two"><div><label for="s-conv_parallel">Files at the same time (conversion)</label><input type="number" id="s-conv_parallel" min="1" max="8" step="1" value="${+s.conv_parallel || 1}">
        <p class="help" style="margin:4px 0 0">More than one file at a time only pays off on machines with many cores.</p></div>
        <div><label for="s-conv_segments">Segments per movie (0 = automatic)</label><input type="number" id="s-conv_segments" min="0" max="12" step="1" value="${+s.conv_segments || 0}">
        <p class="help" style="margin:4px 0 0">Long movies are split in time and encoded in parallel (all software codecs); 1 = never split. With "0" the app decides based on free cores and RAM.</p></div></div>
      ${capsHtml(m)}`;
    if(!el._cvs){ el._cvs = true; el.addEventListener('click', onClick); }
  },
  collect(){
    const df = {...saved};
    document.querySelectorAll('[data-default]').forEach(sel => { if(sel.value) df[sel.dataset.default] = sel.value; });
    return {general: {conv_parallel: +($('#s-conv_parallel') || {}).value || 1, conv_segments: Math.max(0, +($('#s-conv_segments') || {}).value || 0)}, convert: {default_for: df}};
  },
});
