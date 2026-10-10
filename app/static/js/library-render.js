// Bibliothek: HTML der Kopfzeile, Filterspalte, Zeilen, Kacheln und Ordnerköpfe (reine Darstellung, kein Zustand außer L). Besitzer: PF.
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
  if(j) return `<span class="lib-b busy">${j.status === 'replacing' ? 'ersetzt Original' : 'in Arbeit'}</span>`;
  return {orig: '<span class="lib-b old">Original</span>', conv: '<span class="lib-b ok">konvertiert</span>', err: `<span class="lib-b err" title="${esc(f.errText)}">Fehler</span>`, lock: `<span class="lib-b">gesperrt (${esc(f.locked || '')})</span>`,
    probing: '<span class="lib-b">wird geprüft …</span>', other: '<span class="lib-b">—</span>'}[f.status] || '';
}
export function badges(f, withStatus = true){
  const i = f.info; if(!i) return `<div class="lib-badges">${withStatus ? stBadge(f) : ''}</div>`;
  const r = resName(i), a = audioName((i.alist || [])[0]);
  return `<div class="lib-badges"><span class="lib-b ${i.codec === 'hevc' || i.codec === 'av1' ? 'ok' : 'old'}">${esc(codecName(i.codec))}</span><span class="lib-b ${r === 'SD' ? 'sd' : ''}">${esc(r)}</span>${i.hdr_fmt ? `<span class="lib-b hdr">${esc(i.hdr_fmt)}</span>` : ''}${i.dovi ? '<span class="lib-b hdr" title="Dolby Vision geht bei der Konvertierung verloren">DV</span>' : ''}${i.interlaced ? '<span class="lib-b">interlaced</span>' : ''}${a ? `<span class="lib-b">${esc(a)}</span>` : ''}${withStatus ? stBadge(f) : ''}</div>`;
}
const thumb = f => `<div class="lib-thumb" style="${f.m && f.m.poster ? `background:url('${esc(f.m.poster)}') center/cover` : grad(f)}">${f.m && f.m.poster ? '' : esc(f.info ? resName(f.info) : '')}</div>`;

function runBlock(f){
  const j = f.live; if(!j) return f.status === 'err' && f.errText ? `<div class="lib-run"><div class="t err">${esc(f.errText)}</div></div>` : '';
  const q = j.status === 'queued', rep = j.status === 'replacing', host = j.host || hostName();
  const btns = j.id && !rep ? `<span class="btns"><button type="button" class="secondary" data-fskip="${j.id}" data-host="${esc(j.host || '')}" title="Ohne Konvertierung weiter: das Original bleibt unverändert">Überspringen</button><button type="button" class="secondary danger" data-fcancel="${j.id}" data-host="${esc(j.host || '')}" title="Auftrag beenden – das Original bleibt unverändert">Abbrechen</button></span>` : '';
  return `<div class="lib-run"><div class="t"><span class="status-check run"></span>${rep ? 'ersetzt das Original …' : q ? `wartet bei <b>${esc(host)}</b>${j.paused ? ' (pausiert)' : ''}` : `konvertiert auf <b>${esc(host)}</b> · ${pct(f)} %${j.eta ? ` · Restzeit ${fmtD(j.eta)}` : ''}${j.paused ? ' (pausiert)' : ''}`}${btns}</div>
    ${q ? '' : `<div class="mini-bar"><div style="width:${rep ? 100 : pct(f)}%"></div></div>`}</div>`;
}
const nameBtn = (f, text) => { const p = getLibraryActions().find(a => a.primary && a.when([f], {where: 'row'})); return p ? `<button type="button" class="lib-namebtn" data-lact="${esc(p.id)}" data-path="${esc(f.path)}" title="${esc(p.label)}">${esc(text)}</button>` : esc(text); };

export function rowHtml(f, edit){
  const sel = L.sel.has(f.path), ok = selectable(f), s = f.size;
  const name = edit ? `<div class="editrow"><input class="input" id="lib-edit" value="${esc(edit.initial)}" aria-label="Neuer Name" style="min-width:200px;height:30px"><span class="muted">${esc(edit.ext)}</span><button type="button" class="primary" style="width:auto;padding:6px 12px" data-edit-ok>OK</button><button type="button" class="secondary" data-edit-cancel>Abbrechen</button></div>`
    : `<strong title="${esc(f.path)}">${nameBtn(f, nameOf(f))}</strong>`;
  const dur = f.info && f.info.dur ? fmtD(f.info.dur) : '';
  const sv = saveOf(f), sub = f.status === 'conv' ? '' : sv ? `<small>−${esc(fmtB(sv))}</small>` : '';
  return `<div class="lib-row ${sel ? 'sel' : ''} ${L.cur === f.path ? 'cur' : ''}" data-key="f:${esc(f.path)}" data-file="${esc(f.path)}"><input class="check" type="checkbox" data-fsel="${esc(f.path)}" ${sel ? 'checked' : ''} ${ok ? '' : 'disabled'} aria-label="${esc(baseName(f.path))} auswählen">${thumb(f)}
    <div class="nm">${name}<small>${esc(dur)}${f.locked ? ` · wird von ${esc(f.locked)} bearbeitet` : ''}${f.m && f.m.episode_name ? ' · ' + esc(f.m.episode_name) : ''}</small></div>${badges(f)}<div class="sz">${fmtB(s)}${sub}</div>${runBlock(f)}</div>`;
}
export function tileHtml(f){
  const sel = L.sel.has(f.path), ok = selectable(f), j = f.live, sv = saveOf(f);
  return `<div class="lib-tile ${sel ? 'sel' : ''} ${L.cur === f.path ? 'cur' : ''}" data-key="f:${esc(f.path)}" data-file="${esc(f.path)}"><div class="poster" style="${f.m && f.m.poster ? `background:url('${esc(f.m.poster)}') center/cover` : grad(f)}">${f.m && f.m.poster ? '' : esc(nameOf(f))}
    <div class="lib-badges">${f.info ? `<span class="lib-b ${f.info.codec === 'hevc' ? 'ok' : 'old'}">${esc(codecName(f.info.codec))}</span><span class="lib-b">${esc(resName(f.info))}</span>${f.info.hdr_fmt ? '<span class="lib-b hdr">HDR</span>' : ''}${f.info.dovi ? '<span class="lib-b hdr">DV</span>' : ''}` : ''}</div>
    ${ok ? `<input class="check chk" type="checkbox" data-fsel="${esc(f.path)}" ${sel ? 'checked' : ''} aria-label="${esc(baseName(f.path))} auswählen">` : ''}${j ? `<span class="runtag">${j.status === 'queued' ? 'wartet' : pct(f) + ' % · ' + esc(j.host || hostName())}</span><div class="prog"><i style="width:${pct(f)}%"></i></div>` : ''}</div>
    <div class="cap2"><strong title="${esc(f.path)}">${esc(nameOf(f))}</strong><span>${fmtB(f.size)} ${sv ? `· <span class="sv">−${esc(fmtB(sv))} möglich</span>` : f.status === 'conv' ? '· konvertiert' : f.status === 'err' ? '· <span class="svr">Fehler</span>' : ''}</span></div></div>`;
}
export function groupHtml(dir, fs, closed, edit){
  const ok = fs.filter(selectable), n = ok.filter(f => L.sel.has(f.path)).length, label = dir ? dir.split('/').join(' / ') : '(Hauptordner)';
  const head = edit ? `<div class="editrow"><input class="input" id="lib-edit" value="${esc(edit.initial)}" aria-label="Neuer Ordnername" style="min-width:200px;height:30px"><button type="button" class="primary" style="width:auto;padding:6px 12px" data-edit-ok>OK</button><button type="button" class="secondary" data-edit-cancel>Abbrechen</button></div>`
    : `<button type="button" class="foldertoggle" data-ftoggle="${esc(dir)}" aria-expanded="${!closed}"><span class="chevb ${closed ? '' : 'open'}">▸</span><strong>${esc(label)}</strong></button><span class="pill">${fs.length} Datei${fs.length === 1 ? '' : 'en'}</span><span class="pill">${fmtB(fs.reduce((a, f) => a + f.size, 0))}</span>`;
  const acts = getLibraryActions().filter(a => !a.primary && a.when(fs, {where: 'folder', folder: dir})).map(a => `<button type="button" class="secondary" data-folderact="${esc(a.id)}" data-dir="${esc(dir)}" title="${esc(a.label)}">${esc(a.icon ? a.icon + ' ' : '')}<span class="lbl">${esc(a.label)}</span></button>`).join('');
  return `<div class="lib-grp" data-key="g:${esc(dir)}"><input class="check" type="checkbox" data-gsel="${esc(dir)}" ${n && n === ok.length ? 'checked' : ''} ${ok.length ? '' : 'disabled'} data-some="${n && n < ok.length ? 1 : 0}" aria-label="Alle Dateien in ${esc(label)} wählen">${head}<span class="sp"></span>${edit ? '' : acts}${dir && !edit ? `<button type="button" class="secondary" data-frename="${esc(dir)}" title="Ordner umbenennen">✎<span class="lbl"> Umbenennen</span></button>` : ''}</div>`;
}

export function filterHtml(files){
  const c = counts(files), live = new Map();
  files.forEach(f => { if(f.live) live.set(f.live.host || hostName(), (live.get(f.live.host || hostName()) || 0) + 1); });
  const fi = (attr, v, label, n, on, sub) => `<button type="button" class="lib-fi ${on ? 'on' : ''} ${sub ? 'sub' : ''}" ${attr}="${esc(v)}">${esc(label)}${n != null ? `<span class="n">${n}</span>` : ''}</button>`;
  const known = files.some(f => f.m), k = {film: 0, serie: 0, uns: 0}; files.forEach(f => k[kindOf(f)]++);
  const tops = new Map(); files.forEach(f => { const t = topOf(f.path) || '/'; tops.set(t, (tops.get(t) || 0) + 1); });
  return `<h5>Status</h5>${[['all', 'Alle'], ['orig', 'Original'], ['conv', 'Konvertiert'], ['run', 'In Arbeit'], ['err', 'Fehler']].map(([q, l]) => fi('data-q', q, l, c[q], L.q === q)).join('')}
    ${known ? `<div><h5>Art</h5>${[['all', 'Alles', null], ['film', 'Filme', k.film], ['serie', 'Serien', k.serie], ['uns', 'Unsortiert', k.uns]].map(([v, l, n]) => fi('data-kind', v, l, n, L.kind === v)).join('')}</div>`
      : '<div><h5>Art</h5><p class="hint">Filme und Serien erscheinen, sobald das Einsortieren (Medien/Jellyfin) Angaben zu den Dateien kennt.</p></div>'}
    <div><h5>Ordner</h5>${fi('data-folder', '', 'Alle Ordner', null, L.folder === '')}${[...tops.entries()].sort((a, b) => a[0].localeCompare(b[0], 'de')).slice(0, 80).map(([t, n]) => fi('data-folder', t, t === '/' ? '(Hauptordner)' : t, n, L.folder === t, true)).join('')}</div>
    ${live.size ? `<div><h5>Rechner</h5>${fi('data-node', '', 'alle', null, !L.node)}${[...live.entries()].map(([h, n]) => fi('data-node', h, 'arbeitet: ' + h, n, L.node === h)).join('')}</div>` : ''}`;
}
export function headHtml(){
  const s = L.summary || {}, free = S && S.output ? S.output.free : s.free;
  return `<h2>Bibliothek</h2><span class="pill" title="Ausgabeordner">${esc(L.dir)}</span><span class="pill" id="libinfo">${L.files.length} Dateien${L.probing ? ` · ${L.probing} werden geprüft …` : ''}</span>
    <div class="lib-stat"><div>Frei im Ziel<br><b>${free ? fmtB(free) : '—'}</b></div><div>Originale<br><b>${fmtB(s.orig_bytes || 0)}</b> in ${s.orig_count || 0} Dateien</div><div class="save" title="Geschätzt mit dem Standard-Preset je Disc-Art">Mögliche Einsparung<br><b>≈ ${fmtB(s.save_bytes || 0)}</b></div></div>`;
}
export { groups, dirOf };
