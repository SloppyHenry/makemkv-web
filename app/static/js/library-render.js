// Library: HTML of the header, filter column, rows, tiles and folder heads (pure rendering, no state except L). Owner: PF.
import { S, baseName, esc, fmtB, fmtD, hostName } from './core.js';
import { L, audioName, codecName, counts, dirOf, groups, kindOf, resName, saveOf, selectable, topOf } from './library-model.js';
import { getLibraryActions } from './registry.js';

const hue = s => { let h = 0; for(const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const grad = f => `--c1:hsl(${hue(topOf(f.path) || f.path)} 28% 34%);--c2:hsl(${(hue(topOf(f.path) || f.path) + 50) % 360} 24% 22%)`;
const nameOf = f => { const m = f.m; if(m && m.title){ const ep = m.kind === 'series' && m.episode ? ` S${String(m.season || 0).padStart(2, '0')}E${String(m.episode).padStart(2, '0')}` : ''; return m.title + (m.year && m.kind === 'movie' ? ` (${m.year})` : '') + ep; } return baseName(f.path).replace(/\.[^.]+$/, ''); };
export const titleOf = nameOf;
const pct = f => Math.round(((f.live && f.live.pct) || 0) * 100);

export function stBadge(f){
  const j = f.live;
  if(j) return `<span class="lib-b busy">${j.status === 'replacing' ? 'replacing original' : 'in progress'}</span>`;
  return {orig: '<span class="lib-b old">Original</span>', conv: '<span class="lib-b ok">converted</span>', err: `<span class="lib-b err" title="${esc(f.errText)}">Error</span>`, lock: `<span class="lib-b">locked (${esc(f.locked || '')})</span>`,
    probing: '<span class="lib-b">checking …</span>', other: '<span class="lib-b">—</span>'}[f.status] || '';
}
export function badges(f, withStatus = true){
  const i = f.info; if(!i) return `<div class="lib-badges">${withStatus ? stBadge(f) : ''}</div>`;
  const r = resName(i), a = audioName((i.alist || [])[0]);
  return `<div class="lib-badges"><span class="lib-b ${i.codec === 'hevc' || i.codec === 'av1' ? 'ok' : 'old'}">${esc(codecName(i.codec))}</span><span class="lib-b ${r === 'SD' ? 'sd' : ''}">${esc(r)}</span>${i.hdr_fmt ? `<span class="lib-b hdr">${esc(i.hdr_fmt)}</span>` : ''}${i.dovi ? '<span class="lib-b hdr" title="Dolby Vision is lost during conversion">DV</span>' : ''}${i.interlaced ? '<span class="lib-b">interlaced</span>' : ''}${a ? `<span class="lib-b">${esc(a)}</span>` : ''}${withStatus ? stBadge(f) : ''}</div>`;
}
const thumb = f => `<div class="lib-thumb" style="${f.m && f.m.poster ? `background:url('${esc(f.m.poster)}') center/cover` : grad(f)}">${f.m && f.m.poster ? '' : esc(f.info ? resName(f.info) : '')}</div>`;

function runBlock(f){
  const j = f.live; if(!j) return f.status === 'err' && f.errText ? `<div class="lib-run"><div class="t err">${esc(f.errText)}</div></div>` : '';
  const q = j.status === 'queued', rep = j.status === 'replacing', host = j.host || hostName();
  const btns = j.id && !rep ? `<span class="btns"><button type="button" class="secondary" data-fskip="${j.id}" data-host="${esc(j.host || '')}" title="Continue without conversion: the original stays unchanged">Skip</button><button type="button" class="secondary danger" data-fcancel="${j.id}" data-host="${esc(j.host || '')}" title="End the job – the original stays unchanged">Cancel</button></span>` : '';
  return `<div class="lib-run"><div class="t"><span class="status-check run"></span>${rep ? 'replacing the original …' : q ? `waiting on <b>${esc(host)}</b>${j.paused ? ' (paused)' : ''}` : `converting on <b>${esc(host)}</b> · ${pct(f)} %${j.eta ? ` · remaining ${fmtD(j.eta)}` : ''}${j.paused ? ' (paused)' : ''}`}${btns}</div>
    ${q ? '' : `<div class="mini-bar"><div style="width:${rep ? 100 : pct(f)}%"></div></div>`}</div>`;
}
const nameBtn = (f, text) => { const p = getLibraryActions().find(a => a.primary && a.when([f], {where: 'row'})); return p ? `<button type="button" class="lib-namebtn" data-lact="${esc(p.id)}" data-path="${esc(f.path)}" title="${esc(p.label)}">${esc(text)}</button>` : esc(text); };

export function rowHtml(f, edit){
  const sel = L.sel.has(f.path), ok = selectable(f), s = f.size;
  const name = edit ? `<div class="editrow"><input class="input" id="lib-edit" value="${esc(edit.initial)}" aria-label="New name" style="min-width:200px;height:30px"><span class="muted">${esc(edit.ext)}</span><button type="button" class="primary" style="width:auto;padding:6px 12px" data-edit-ok>OK</button><button type="button" class="secondary" data-edit-cancel>Cancel</button></div>`
    : `<strong title="${esc(f.path)}">${nameBtn(f, nameOf(f))}</strong>`;
  const dur = f.info && f.info.dur ? fmtD(f.info.dur) : '';
  const sv = saveOf(f), sub = f.status === 'conv' ? '' : sv ? `<small>−${esc(fmtB(sv))}</small>` : '';
  return `<div class="lib-row ${sel ? 'sel' : ''} ${L.cur === f.path ? 'cur' : ''}" data-key="f:${esc(f.path)}" data-file="${esc(f.path)}"><input class="check" type="checkbox" data-fsel="${esc(f.path)}" ${sel ? 'checked' : ''} ${ok ? '' : 'disabled'} aria-label="Select ${esc(baseName(f.path))}">${thumb(f)}
    <div class="nm">${name}<small>${esc(dur)}${f.locked && !f.live ? ` · being processed by ${esc(f.locked)}` : ''}${f.m && f.m.episode_name ? ' · ' + esc(f.m.episode_name) : ''}</small></div>${badges(f)}<div class="sz">${f.live || f.locked ? '' : `<button type="button" class="rowdel" data-del="${esc(f.path)}" title="Delete file" aria-label="Delete ${esc(baseName(f.path))}">🗑</button>`}${fmtB(s)}${sub}</div>${runBlock(f)}</div>`;
}
export function tileHtml(f){
  const sel = L.sel.has(f.path), ok = selectable(f), j = f.live, sv = saveOf(f);
  return `<div class="lib-tile ${sel ? 'sel' : ''} ${L.cur === f.path ? 'cur' : ''}" data-key="f:${esc(f.path)}" data-file="${esc(f.path)}"><div class="poster" style="${f.m && f.m.poster ? `background:url('${esc(f.m.poster)}') center/cover` : grad(f)}">${f.m && f.m.poster ? '' : esc(nameOf(f))}
    <div class="lib-badges">${f.info ? `<span class="lib-b ${f.info.codec === 'hevc' ? 'ok' : 'old'}">${esc(codecName(f.info.codec))}</span><span class="lib-b">${esc(resName(f.info))}</span>${f.info.hdr_fmt ? '<span class="lib-b hdr">HDR</span>' : ''}${f.info.dovi ? '<span class="lib-b hdr">DV</span>' : ''}` : ''}</div>
    ${ok ? `<input class="check chk" type="checkbox" data-fsel="${esc(f.path)}" ${sel ? 'checked' : ''} aria-label="Select ${esc(baseName(f.path))}">` : ''}${j ? `<span class="runtag">${j.status === 'queued' ? 'waiting' : pct(f) + ' % · ' + esc(j.host || hostName())}</span><div class="prog"><i style="width:${pct(f)}%"></i></div>` : ''}</div>
    <div class="cap2"><strong title="${esc(f.path)}">${esc(nameOf(f))}</strong><span>${fmtB(f.size)} ${sv ? `· <span class="sv">−${esc(fmtB(sv))} possible</span>` : f.status === 'conv' ? '· converted' : f.status === 'err' ? '· <span class="svr">Error</span>' : ''}</span></div></div>`;
}
export function groupHtml(dir, fs, closed, edit){
  const ok = fs.filter(selectable), n = ok.filter(f => L.sel.has(f.path)).length, label = dir ? dir.split('/').join(' / ') : '(top folder)';
  const head = edit ? `<div class="editrow"><input class="input" id="lib-edit" value="${esc(edit.initial)}" aria-label="New folder name" style="min-width:200px;height:30px"><button type="button" class="primary" style="width:auto;padding:6px 12px" data-edit-ok>OK</button><button type="button" class="secondary" data-edit-cancel>Cancel</button></div>`
    : `<button type="button" class="foldertoggle" data-ftoggle="${esc(dir)}" aria-expanded="${!closed}"><span class="chevb ${closed ? '' : 'open'}">▸</span><strong>${esc(label)}</strong></button><span class="pill">${fs.length} file${fs.length === 1 ? '' : 's'}</span><span class="pill">${fmtB(fs.reduce((a, f) => a + f.size, 0))}</span>`;
  const acts = getLibraryActions().filter(a => !a.primary && a.when(fs, {where: 'folder', folder: dir})).map(a => `<button type="button" class="secondary" data-folderact="${esc(a.id)}" data-dir="${esc(dir)}" title="${esc(a.label)}">${esc(a.icon ? a.icon + ' ' : '')}<span class="lbl">${esc(a.label)}</span></button>`).join('');
  return `<div class="lib-grp" data-key="g:${esc(dir)}"><input class="check" type="checkbox" data-gsel="${esc(dir)}" ${n && n === ok.length ? 'checked' : ''} ${ok.length ? '' : 'disabled'} data-some="${n && n < ok.length ? 1 : 0}" aria-label="Select all files in ${esc(label)}">${head}<span class="sp"></span>${edit ? '' : acts}${dir && !edit ? `<button type="button" class="secondary" data-frename="${esc(dir)}" title="Rename folder">✎<span class="lbl"> Rename</span></button><button type="button" class="secondary danger" data-fdel="${esc(dir)}" title="Delete all files in the folder">🗑<span class="lbl"> Delete</span></button>` : ''}</div>`;
}

export function filterHtml(files){
  const c = counts(files), live = new Map();
  files.forEach(f => { if(f.live) live.set(f.live.host || hostName(), (live.get(f.live.host || hostName()) || 0) + 1); });
  const fi = (attr, v, label, n, on, sub) => `<button type="button" class="lib-fi ${on ? 'on' : ''} ${sub ? 'sub' : ''}" ${attr}="${esc(v)}">${esc(label)}${n != null ? `<span class="n">${n}</span>` : ''}</button>`;
  const known = files.some(f => f.m), k = {film: 0, serie: 0, uns: 0}; files.forEach(f => k[kindOf(f)]++);
  const tops = new Map(); files.forEach(f => { const t = topOf(f.path) || '/'; tops.set(t, (tops.get(t) || 0) + 1); });
  return `<h5>Status</h5>${[['all', 'All'], ['orig', 'Original'], ['conv', 'Converted'], ['run', 'In progress'], ['err', 'Error']].map(([q, l]) => fi('data-q', q, l, c[q], L.q === q)).join('')}
    ${known ? `<div><h5>Type</h5>${[['all', 'Everything', null], ['film', 'Movies', k.film], ['serie', 'Series', k.serie], ['uns', 'Unsorted', k.uns]].map(([v, l, n]) => fi('data-kind', v, l, n, L.kind === v)).join('')}</div>`
      : '<div><h5>Type</h5><p class="hint">Movies and series appear as soon as sorting (Media/Jellyfin) knows details about the files.</p></div>'}
    <div><h5>Folder</h5>${fi('data-folder', '', 'All folders', null, L.folder === '')}${[...tops.entries()].sort((a, b) => a[0].localeCompare(b[0], 'en')).slice(0, 80).map(([t, n]) => fi('data-folder', t, t === '/' ? '(top folder)' : t, n, L.folder === t, true)).join('')}</div>
    ${live.size ? `<div><h5>Machine</h5>${fi('data-node', '', 'all', null, !L.node)}${[...live.entries()].map(([h, n]) => fi('data-node', h, 'working: ' + h, n, L.node === h)).join('')}</div>` : ''}`;
}
export function headHtml(){
  const s = L.summary || {}, free = S && S.output ? S.output.free : s.free;
  return `<h2>Library</h2><span class="pill" title="Output folder">${esc(L.dir)}</span><span class="pill" id="libinfo">${L.files.length} files${L.probing ? ` · checking ${L.probing} …` : ''}</span>
    <div class="lib-stat"><div>Free in target<br><b>${free ? fmtB(free) : '—'}</b></div><div>Originals<br><b>${fmtB(s.orig_bytes || 0)}</b> in ${s.orig_count || 0} files</div><div class="save" title="Estimated with the default preset per disc type">Possible savings<br><b>≈ ${fmtB(s.save_bytes || 0)}</b></div></div>`;
}
export { groups, dirOf };
