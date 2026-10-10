// Bibliothek: Dateien im Ziel, Ordneransicht, Umbenennen, nachträglich konvertieren. Registriert die Ansicht „Bibliothek“.
import { $, S, api, baseName, dec, delegate, esc, fmtB, hostName, toast } from './core.js';
import { CV_FALLBACK, cvFields } from './cvform.js';
import { loadFiles } from './files.js';
import { jobsPanelHtml } from './jobs.js';
import { getLibraryActions, isActive, navigate, on, registerView } from './registry.js';

const libSel = new Set();
let lib = {files:[], probing:0, dir:'', instance:''}, libCv = null, libFilter = '';
function libInit(){
  if(libCv || !S) return;
  libCv = {...CV_FALLBACK, ...((S.settings.presets||{}).bluray||{}), convert:true};
  $('#libcv').innerHTML = cvFields(libCv, 'lcv', '');
}
delegate('#libcv', 'input', e => { const f = e.target.dataset.lcv; if(f) libCv[f] = f==='rf' ? (+e.target.value||21) : e.target.value; });
async function loadLibrary(){ try{ lib = await (await fetch('/api/library')).json(); renderLibrary(); }catch{} }
setInterval(() => { if(isActive('bibliothek')) loadLibrary(); }, 4000);
delegate('#lib-reload', 'click', loadLibrary);
delegate('#libfilter', 'input', e => { libFilter = e.target.value.toLowerCase(); renderLibrary(); });
const libOk = f => f.state==='ok' && !f.job && !f.locked;
delegate('#lib-allok', 'click', () => { lib.files.filter(libOk).filter(f => f.path.toLowerCase().includes(libFilter)).forEach(f => libSel.add(f.path)); renderLibrary(); });
delegate('#lib-none', 'click', () => { libSel.clear(); renderLibrary(); });
let libEdit = null;                       // laufendes Umbenennen: {kind:'file'|'folder', path, value, ext?}
const libOpen = new Set((() => { try{ return JSON.parse(localStorage.getItem('libOpen') || '[]'); }catch{ return []; } })());
const saveOpen = () => { try{ localStorage.setItem('libOpen', JSON.stringify([...libOpen])); }catch{} };
const dirOf = p => p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';
const matches = f => f.path.toLowerCase().includes(libFilter);
function libGroups(files){
  const m = new Map();
  for(const f of files){ const d = dirOf(f.path); if(!m.has(d)) m.set(d, []); m.get(d).push(f); }
  m.forEach(v => v.sort((a,b) => baseName(a.path).localeCompare(baseName(b.path), 'de')));
  return [...m.entries()].sort((a,b) => a[0].localeCompare(b[0], 'de'));
}
function libStat(f){
  if(f.job) return f.job.status==='replacing' ? '<span class="st busy">ersetzt Original …</span>' : f.job.status==='running' ? `<span class="st busy">konvertiert ${Math.round(f.job.pct*100)} %${f.job.host ? ' (' + esc(f.job.host) + ')' : ''}</span>` : `<span class="st busy">in Warteschlange${f.job.host ? ' (' + esc(f.job.host) + ')' : ''}</span>`;
  if(f.locked) return `<span class="st warn">gesperrt (${esc(f.locked)})</span>`;
  return {ok:'<span class="st ok">Original</span>', hevc:'<span class="st">bereits HEVC</span>', hdr:'<span class="st warn">HDR – nicht umkodiert</span>', probing:'<span class="st">wird geprüft …</span>', other:'<span class="st">—</span>',
          unknown:`<span class="st warn" title="${esc(f.dev_err||'')}">nicht lesbar</span>`}[f.state] || '';
}
const editRow = (id, value, suffix) => `<div class="editrow"><input class="input" id="lib-edit" value="${esc(value)}" aria-label="Neuer Name" style="min-width:220px;height:30px">${suffix ? `<span class="muted">${esc(suffix)}</span>` : ''}<button class="primary" style="width:auto;padding:6px 12px" data-edit-ok>OK</button><button class="secondary" data-edit-cancel>Abbrechen</button></div>`;
function folderRow(dir, fs){
  const open = libOpen.has(dir) || !!libFilter, ok = fs.filter(libOk), sel = ok.filter(f => libSel.has(f.path)).length;
  const count = {}; fs.forEach(f => { const k = f.job ? 'busy' : f.state; count[k] = (count[k]||0)+1; });
  const names = {ok:'Original', hevc:'HEVC', hdr:'HDR', busy:'in Arbeit', other:'andere', probing:'wird geprüft', unknown:'nicht lesbar'};
  const sum = Object.entries(count).map(([k,n]) => `${n} ${names[k]||k}`).join(' · ');
  const editing = libEdit && libEdit.kind==='folder' && libEdit.path===dir;
  const label = dir ? dir.split('/').join(' / ') : '(Hauptordner)';
  const head = editing ? editRow('f', libEdit.value, '') : `<button class="foldertoggle" data-ftoggle="${esc(dir)}" aria-expanded="${open}"><span class="chevb ${open?'open':''}">▸</span><strong>${esc(label)}</strong><span class="pill">${fs.length} Datei${fs.length===1?'':'en'}</span></button>`;
  return `<tr class="folder"><td><input class="check" type="checkbox" data-fsel="${esc(dir)}" data-state="${ok.length && sel===ok.length ? 'all' : sel ? 'some' : 'none'}" ${ok.length && sel===ok.length ? 'checked' : ''} ${ok.length?'':'disabled'} aria-label="Alle Original-Dateien in ${esc(label)} wählen"></td>
    <td colspan="3">${head}</td><td>${fmtB(fs.reduce((a,f) => a+f.size, 0))}</td><td class="muted">${esc(sum)}</td>
    <td>${dir ? `<button class="secondary" data-frename="${esc(dir)}" ${editing?'disabled':''} title="Ordner umbenennen">✎ Umbenennen</button>` : ''}</td></tr>`;
}
// Aktionen anderer Module (registerLibraryAction); die „primäre“ Aktion hängt am Dateinamen
const actionBtns = f => getLibraryActions().filter(a => !a.primary && a.when([f])).map(a => `<button class="secondary" data-lact="${esc(a.id)}" data-path="${esc(f.path)}">${esc(a.icon ? a.icon + ' ' : '')}${esc(a.label)}</button> `).join('');
function fileRow(f){
  const editing = libEdit && libEdit.kind==='file' && libEdit.path===f.path;
  const vid = f.info ? `${esc(f.info.codec)} ${f.info.w}×${f.info.h}${f.info.pix ? ' · '+esc(f.info.pix) : ''}` : '';
  const aud = f.info ? esc((f.info.audio[0]||'') + (f.info.audio.length>1 ? ` (+${f.info.audio.length-1})` : '')) : '';
  const prim = editing ? null : getLibraryActions().find(a => a.primary && a.when([f]));
  const name = editing ? editRow('d', libEdit.value, libEdit.ext) : prim
    ? `<button class="foldertoggle" data-lact="${esc(prim.id)}" data-path="${esc(f.path)}" title="${esc(prim.label)}">${esc(baseName(f.path))}</button>` : esc(baseName(f.path));
  return `<tr class="file"><td><input class="check" type="checkbox" data-lsel="${esc(f.path)}" ${libSel.has(f.path)?'checked':''} ${libOk(f)?'':'disabled'} aria-label="${esc(f.path)} auswählen"></td>
    <td><div class="fileindent">${name}</div></td><td class="muted">${vid}</td><td class="muted">${aud}</td><td>${fmtB(f.size)}</td><td>${libStat(f)}</td>
    <td><button class="secondary" data-rename="${esc(f.path)}" ${(f.job||f.locked||editing)?'disabled':''} title="Datei umbenennen">✎</button> ${actionBtns(f)}<a class="secondary" href="/api/download?path=${encodeURIComponent(f.path)}">Download</a> <button class="secondary danger" data-del="${esc(f.path)}" ${f.job||f.locked?'disabled':''}>Löschen</button>${f.job && f.job.id && ['queued','running'].includes(f.job.status) ? ` <button class="secondary danger" data-fcancel="${f.job.id}" data-host="${esc(f.job.host||'')}" title="Konvertierung abbrechen – das Original bleibt unverändert">Abbrechen</button>` : ''}</td></tr>`;
}
function fillLibTarget(){
  const sel = $('#lib-target'); if(!sel || !S) return;
  const cur = sel.value || 'local';
  const opts = [`<option value="local">Dieser Rechner (${esc(hostName())})</option>`].concat((S.peers||[]).filter(p => p.reachable).map(p =>
    `<option value="${esc(p.name)}">${esc(p.name)} · ${p.cores} Threads · Last ${dec((p.load||0).toFixed(1))} · ${p.conv_active} Aufträge</option>`)).join('');
  if(sel.dataset.h !== opts){ sel.innerHTML = opts; sel.dataset.h = opts; sel.value = [...sel.options].some(o => o.value === cur) ? cur : 'local'; }
}
function renderLibrary(force=false){
  if(!$('#liblist')) return;
  fillLibTarget();
  if(libEdit && !force) return;           // beim Umbenennen nicht neu zeichnen (sonst ginge die Eingabe verloren)
  $('#filesdir').textContent = lib.dir || '';
  $('#libinfo').textContent = `${lib.files.length} Dateien${lib.probing ? ' · '+lib.probing+' werden geprüft …' : ''}`;
  const rows = lib.files.filter(matches), groups = libGroups(rows);
  $('#nolib').hidden = rows.length > 0;
  $('#liblist').innerHTML = groups.map(([dir, fs]) => folderRow(dir, fs) + ((libOpen.has(dir) || libFilter) ? fs.map(fileRow).join('') : '')).join('');
  $('#liblist').querySelectorAll('[data-state="some"]').forEach(c => c.indeterminate = true);
  const n = [...libSel].filter(p => lib.files.some(f => f.path===p && libOk(f))).length;
  $('#lib-go').disabled = !n; $('#lib-go').textContent = n ? `${n} Datei${n>1?'en':''} konvertieren` : 'Auswahl konvertieren';
  const tot = lib.files.filter(f => libSel.has(f.path)).reduce((a,f) => a+f.size, 0);
  $('#lib-sel').textContent = n ? `${fmtB(tot)} Originale – danach ersetzt durch die kleinere Datei` : '';
  if(libEdit){ const i = $('#lib-edit'); if(i && document.activeElement !== i){ i.focus(); i.select(); } }
}
function startEdit(kind, path){
  if(kind === 'file'){ const nm = baseName(path), i = nm.lastIndexOf('.'); libEdit = {kind, path, value: i > 0 ? nm.slice(0, i) : nm, ext: i > 0 ? nm.slice(i) : ''}; }
  else libEdit = {kind, path, value: baseName(path)};
  renderLibrary(true);
}
function stopEdit(){ libEdit = null; renderLibrary(true); }
async function commitEdit(){
  const e = libEdit; if(!e) return;
  const value = e.value.trim(); if(!value || value === (e.kind==='file' ? baseName(e.path).replace(/\.[^.]*$/, '') : baseName(e.path))){ stopEdit(); return; }
  try{
    const r = await api(e.kind==='file' ? '/api/library/rename' : '/api/library/rename-folder', 'POST', {path: e.path, name: value});
    const old = e.path, neu = r.path;                       // Auswahl und Ordnerzustand auf den neuen Pfad umstellen
    [...libSel].forEach(p => { if(p === old || p.startsWith(old + '/')){ libSel.delete(p); libSel.add(neu + p.slice(old.length)); } });
    [...libOpen].forEach(p => { if(p === old || p.startsWith(old + '/')){ libOpen.delete(p); libOpen.add(neu + p.slice(old.length)); } }); saveOpen();
    toast(e.kind==='file' ? 'Datei umbenannt ✓' : 'Ordner umbenannt ✓');
    libEdit = null; await loadLibrary(); loadFiles(); renderLibrary(true);
  }catch{ /* api() zeigt die Meldung; die Eingabe bleibt zum Korrigieren offen */ }
}
delegate('#liblist', 'change', e => {
  const t = e.target;
  if(t.dataset.lsel !== undefined){ t.checked ? libSel.add(t.dataset.lsel) : libSel.delete(t.dataset.lsel); renderLibrary(); }
  else if(t.dataset.fsel !== undefined){
    lib.files.filter(f => dirOf(f.path) === t.dataset.fsel && libOk(f) && matches(f)).forEach(f => t.checked ? libSel.add(f.path) : libSel.delete(f.path));
    renderLibrary();
  }
});
delegate('#liblist', 'input', e => { if(e.target.id === 'lib-edit' && libEdit) libEdit.value = e.target.value; });
delegate('#liblist', 'keydown', e => {
  if(e.target.id !== 'lib-edit') return;
  if(e.key === 'Enter'){ e.preventDefault(); commitEdit(); } else if(e.key === 'Escape'){ e.preventDefault(); stopEdit(); }
});
delegate('#liblist', 'click', async e => {
  const t = e.target;
  const la = t.closest('[data-lact]');
  if(la){ const a = getLibraryActions().find(x => x.id === la.dataset.lact), f = lib.files.find(x => x.path === la.dataset.path); if(a && f) a.run([f]); return; }
  const tog = t.closest('[data-ftoggle]');
  if(tog){ const d = tog.dataset.ftoggle; libOpen.has(d) ? libOpen.delete(d) : libOpen.add(d); saveOpen(); renderLibrary(); return; }
  const fc = t.closest('[data-fcancel]');
  if(fc){
    if(confirm('Konvertierung abbrechen? Das Original bleibt unverändert.')){ const h = fc.dataset.host; api(h ? `/api/peer/${h}/conversions/${fc.dataset.fcancel}/cancel` : `/api/conversions/${fc.dataset.fcancel}/cancel`).then(() => loadLibrary()); }
    return;
  }
  const rn = t.closest('[data-rename]'); if(rn){ startEdit('file', rn.dataset.rename); return; }
  const fr = t.closest('[data-frename]'); if(fr){ startEdit('folder', fr.dataset.frename); return; }
  if(t.closest('[data-edit-ok]')){ commitEdit(); return; }
  if(t.closest('[data-edit-cancel]')){ stopEdit(); return; }
  const p = t.dataset.del; if(!p) return;
  if(confirm(`„${p}“ endgültig löschen?`)){
    const r = await fetch('/api/files?path='+encodeURIComponent(p), {method:'DELETE'});
    if(!r.ok){ let m = 'Löschen fehlgeschlagen'; try{ m = (await r.json()).detail || m }catch{} toast(m, true); }
    loadLibrary(); loadFiles();
  }
});
delegate('#lib-go', 'click', async () => {
  const paths = [...libSel];
  const target = $('#lib-target').value || 'local', wo = target === 'local' ? 'auf diesem Rechner' : `auf ${target}`;
  if(!confirm(`${paths.length} Datei(en) ${wo} konvertieren?\n\nDas Original wird nach bestandener Prüfung GELÖSCHT und durch die konvertierte Datei ersetzt.`)) return;
  const r = await api(target === 'local' ? '/api/library/convert' : `/api/peer/${target}/library/convert`, 'POST', {paths, convert: libCv});
  libSel.clear();
  if(r.skipped && r.skipped.length) alert(`${r.started.length} gestartet, ${r.skipped.length} übersprungen:\n` + r.skipped.map(x => `• ${x.path}: ${x.why}`).join('\n'));
  else toast(`${r.started.length} Datei(en) in die Warteschlange gestellt.`);
  loadLibrary();
});

delegate('#lib-back', 'click', () => navigate('laufwerke'));
on('files-changed', () => { if(isActive('bibliothek')) loadLibrary(); });

const LIB_HTML = `    <section class="panel">
      <div class="panel-head"><button class="secondary" id="lib-back" title="Zurück zu den Laufwerken">← Laufwerke</button><span class="mini-icon">▤</span><h2>Bibliothek</h2><span class="pill" id="filesdir"></span><span class="pill" id="libinfo"></span><span class="spacer"></span>
        <input class="input" id="libfilter" placeholder="Filtern …" style="width:200px;height:30px"><button class="secondary" id="lib-reload">Aktualisieren</button></div>
      <div class="lib-body">
        <div class="settings flat">
          <div class="settings-toggle" style="cursor:default"><span class="mini-icon">⚙</span><strong>Nachträglich konvertieren</strong><span class="summary">Das Original wird nach bestandener Prüfung (Länge, Spurzahl) durch die kleinere x265-Datei ersetzt. Gelesen wird direkt vom NAS.</span></div>
          <div class="settings-body"><div class="fields" id="libcv"></div>
            <div class="libtools"><label class="muted" style="font-size:11px;display:flex;align-items:center;gap:6px">Ausführen auf <select id="lib-target" class="input" style="width:auto;height:30px;min-width:200px"></select></label><button class="primary" id="lib-go" style="width:auto" disabled>Auswahl konvertieren</button>
              <button class="secondary" id="lib-allok">Alle „Original“ wählen</button><button class="secondary" id="lib-none">Keine</button><span class="muted" style="font-size:11px" id="lib-sel"></span></div></div>
        </div>
        <div class="table-wrap"><table><thead><tr><th></th><th>Datei</th><th>Video</th><th>Audio</th><th>Größe</th><th>Status</th><th></th></tr></thead><tbody id="liblist"></tbody></table></div>
        <div class="empty" id="nolib" hidden>Keine Videodateien im Ausgabeordner.</div>
      </div>
    </section>
    ${jobsPanelHtml('jobs2', false)}`;
registerView({id:'bibliothek', label:'Bibliothek', icon:'▤', order:20, mount(el){
  if(!el.dataset.built){ el.dataset.built = '1'; el.innerHTML = LIB_HTML; }
  libInit(); loadLibrary();
}});
