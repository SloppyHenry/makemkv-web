// Bibliothek (Ansicht „Bibliothek“): Filter links, Liste/Raster, Detailbereich, Auswahlleiste. Besitzer: PF.
// Teile: library-model (Zustand, Filter), -render (HTML), -detail, -bar (Auswahlleiste/Konvertieren), -actions (Umbenennen …).
import { $ } from './core.js';
import { jobsPanelHtml } from './jobs.js';
import { getLibraryActions, isActive, on, onState, registerView } from './registry.js';
import { L, byPath, decorate, groups, matches, reconcile, selectable, selectedFiles, setView } from './library-model.js';
import { filterHtml, groupHtml, headHtml, rowHtml, tileHtml } from './library-render.js';
import { clearEst, drawDetail, stopPlayer } from './library-detail.js';
import { closeSide, drawBar, drawSide, refreshEst, setOnChanged, setPreset, startConversion } from './library-bar.js';
import { closed, commitEdit, deleteFile, filesIn, jobAct, saveClosed, setHooks, startEdit, stopEdit } from './library-actions.js';
import { loadMeta } from './convert-meta.js';
import './convert-settings.js';

let box = null, timer = null, loading = false;

async function loadMedia(){
  if(!L.mediaOn) return;
  const todo = L.files.map(f => f.path).filter(p => !L.mediaAsked.has(p));
  if(!todo.length) return;
  todo.forEach(p => L.mediaAsked.add(p));
  try{
    for(let i = 0; i < todo.length; i += 400){
      const r = await fetch('/api/media/infos', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({paths: todo.slice(i, i + 400)})});
      if(!r.ok){ L.mediaOn = false; return; }
      Object.assign(L.media, await r.json());
    }
    draw('all');
  }catch{ L.mediaOn = false; }
}
async function load(){
  if(loading) return; loading = true;
  try{
    const d = await (await fetch('/api/library')).json();
    L.files = d.files; L.dir = d.dir; L.probing = d.probing; L.instance = d.instance; L.summary = d.summary; L.loaded = true;
    const paths = new Set(L.files.map(f => f.path));
    [...L.sel].forEach(p => { if(!paths.has(p)) L.sel.delete(p); });
    if(L.cur && !paths.has(L.cur)) L.cur = '';
    if(!L.edit) draw('all');
    loadMedia(); refreshEst(0);
  }catch{ /* Server nicht erreichbar: beim nächsten Takt erneut */ } finally{ loading = false; }
}
function schedule(){ if(timer) return; timer = setTimeout(() => { timer = null; if(isActive('bibliothek')) draw('rows'); }, 350); }

function draw(what = 'all'){
  if(!box || !L.loaded) return;
  decorate(L.files);
  const vis = L.files.filter(matches), gs = groups(vis), items = [];
  let shown = 0;
  if(L.view === 'list'){
    for(const [dir, fs] of gs){
      if(shown >= L.limit) break;
      const isClosed = closed.has(dir), ed = L.edit && L.edit.kind === 'folder' && L.edit.path === dir ? L.edit : null;
      items.push({key: 'g:' + dir, html: groupHtml(dir, fs, isClosed, ed)});
      if(isClosed) continue;
      for(const f of fs){ if(shown++ >= L.limit) break; const e = L.edit && L.edit.kind === 'file' && L.edit.path === f.path ? L.edit : null; items.push({key: 'f:' + f.path, html: rowHtml(f, e)}); }
    }
  }else for(const [, fs] of gs) for(const f of fs){ if(shown++ >= L.limit) break; items.push({key: 'f:' + f.path, html: tileHtml(f)}); }
  const total = vis.length, list = $('#liblist');
  list.className = L.view === 'grid' ? 'lib-grid' : 'lib-list';
  reconcile(list, items);
  list.querySelectorAll('[data-some="1"]').forEach(c => { c.indeterminate = true; });
  const more = $('#libmore'); more.hidden = shown >= total || L.view === 'list' && shown < L.limit; more.textContent = `Weitere ${Math.min(200, total - shown)} anzeigen (${total - shown} übrig)`;
  $('#libempty').hidden = total > 0 || !L.loaded;
  $('#libempty').textContent = L.files.length ? 'Nichts passt zum Filter.' : 'Keine Videodateien im Ausgabeordner.';
  if(what === 'all'){
    $('#libhead').innerHTML = headHtml();
    const fh = filterHtml(L.files); if($('#libfilter').dataset.h !== fh){ $('#libfilter').dataset.h = fh; $('#libfilter').innerHTML = fh; }
    $('#libfilter').classList.toggle('open', L.filtOpen);
    document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === L.view));
  }
  $('#libcols').classList.toggle('nodetail', !L.cur && !L.cvOpen);
  const side = $('#libside');
  if(L.cvOpen){ $('#libdetail').hidden = true; side.hidden = false; drawSide(side); } else { side.hidden = true; drawSide(side); $('#libdetail').hidden = !L.cur; drawDetail($('#libdetail'), () => draw('rows')); }
  drawBar($('#libbar'));
}
setOnChanged(w => draw(w === 'bar' ? 'bar' : 'all'));
setHooks(load, () => draw('all'));

// ---- Aktionen anderer Pakete (registerLibraryAction): Datei, Auswahl, Ordner
const runAct = (id, files, ctx) => { const a = getLibraryActions().find(x => x.id === id); if(a && files.length) a.run(files, ctx); };
let lastClicked = '';
function selectPath(p, on, range){
  const order = [...box.querySelectorAll('[data-fsel]')].map(c => c.dataset.fsel);
  const paths = range && lastClicked && order.includes(lastClicked) ? order.slice(Math.min(order.indexOf(lastClicked), order.indexOf(p)), Math.max(order.indexOf(lastClicked), order.indexOf(p)) + 1) : [p];
  paths.forEach(x => { const f = byPath(x); if(f && selectable(f)) on ? L.sel.add(x) : L.sel.delete(x); });
  lastClicked = p; refreshEst(); draw('all');
}
function onClick(e){
  const t = e.target, q = s => t.closest(s); let b;
  if((b = q('[data-fsel]'))){ selectPath(b.dataset.fsel, b.checked, e.shiftKey); return; }
  if((b = q('[data-gsel]'))){ filesIn(b.dataset.gsel).filter(f => selectable(f) && matches(f)).forEach(f => b.checked ? L.sel.add(f.path) : L.sel.delete(f.path)); refreshEst(); draw('all'); return; }
  if((b = q('[data-lact]'))){ const f = byPath(b.dataset.path); if(f) runAct(b.dataset.lact, [f], {where: b.closest('.lib-detail') ? 'detail' : 'row'}); return; }
  if((b = q('[data-folderact]'))) { runAct(b.dataset.folderact, filesIn(b.dataset.dir), {where: 'folder', folder: b.dataset.dir}); return; }
  if((b = q('[data-baract]'))) { runAct(b.dataset.baract, selectedFiles(), {where: 'bar'}); return; }
  if((b = q('[data-playtoggle]'))){ L.play = L.play === b.dataset.playtoggle ? '' : b.dataset.playtoggle; draw('rows'); return; }
  if((b = q('[data-fcancel]'))){ jobAct('cancel', b.dataset.fcancel, b.dataset.host); return; }
  if((b = q('[data-fskip]'))){ jobAct('skip', b.dataset.fskip, b.dataset.host); return; }
  if((b = q('[data-rename]'))){ startEdit('file', b.dataset.rename); return; }
  if((b = q('[data-frename]'))){ startEdit('folder', b.dataset.frename); return; }
  if((b = q('[data-del]'))){ deleteFile(b.dataset.del); return; }
  if(q('[data-edit-ok]')){ commitEdit(); return; }
  if(q('[data-edit-cancel]')){ stopEdit(); return; }
  if((b = q('[data-ftoggle]'))){ const d = b.dataset.ftoggle; closed.has(d) ? closed.delete(d) : closed.add(d); saveClosed(); draw('rows'); return; }
  if((b = q('[data-q]'))){ L.q = b.dataset.q; L.limit = 200; draw('all'); return; }
  if((b = q('[data-kind]'))){ L.kind = b.dataset.kind; L.limit = 200; draw('all'); return; }
  if((b = q('[data-folder]'))){ L.folder = b.dataset.folder; L.limit = 200; draw('all'); return; }
  if((b = q('[data-node]'))){ L.node = b.dataset.node; draw('all'); return; }
  if((b = q('[data-view]'))){ setView(b.dataset.view); draw('all'); return; }
  if(q('[data-filt]')){ L.filtOpen = !L.filtOpen; draw('all'); return; }
  if(q('[data-all]')){ L.files.filter(f => f.status === 'orig' && selectable(f) && matches(f)).forEach(f => L.sel.add(f.path)); refreshEst(); draw('all'); return; }
  if(q('[data-clear]')){ L.sel.clear(); L.est = null; L.cfg = null; L.preset = 'auto'; draw('all'); return; }
  if(q('[data-reload]')){ load(); return; }
  if(q('#libmore')){ L.limit += 200; draw('rows'); return; }
  if(q('[data-start]')){ startConversion(); return; }
  if(q('[data-cvopen]')){ if(!L.sel.size && L.cur){ const f = byPath(L.cur); if(f && selectable(f)) L.sel.add(L.cur); } if(!selectedFiles().length) return; L.cvOpen = true; refreshEst(0); draw('all'); if(innerWidth <= 700) setTimeout(() => $('#libside').scrollIntoView({block:'start'}), 50); return; }
  if(q('[data-cvclose]')){ closeSide(); draw('all'); return; }
  if((b = q('[data-file]')) && !q('input,button,a,select')){ L.cur = b.dataset.file; if(L.cvOpen) closeSide(); L.cvOpen = false; draw('rows'); }
}
function onChange(e){
  const t = e.target;
  if(t.matches('[data-barpreset]')) setPreset(t.value);
  else if(t.matches('[data-bartarget]')){ L.target = t.value; refreshEst(0); }
}
function onInput(e){ if(e.target.id === 'libtext'){ L.text = e.target.value; L.limit = 200; draw('rows'); } }
function onKey(e){
  if(e.target.id !== 'lib-edit') return;
  if(e.key === 'Enter'){ e.preventDefault(); commitEdit(); } else if(e.key === 'Escape'){ e.preventDefault(); stopEdit(); }
}

const HTML = `<section class="panel lib" id="lib">
  <div class="lib-head" id="libhead"></div>
  <div class="lib-cols nodetail" id="libcols"><aside class="lib-filter" id="libfilter" aria-label="Filter"></aside>
    <div class="lib-main"><div class="lib-tools"><button type="button" class="secondary lib-filterbtn" data-filt>☰ Filter</button><input class="input" id="libtext" placeholder="Filtern …" aria-label="Dateien filtern">
      <div class="lib-view" role="group" aria-label="Darstellung"><button type="button" data-view="list">☰ Liste</button><button type="button" data-view="grid">▦ Raster</button></div><span style="flex:1"></span>
      <button type="button" class="secondary" data-all title="Alle sichtbaren Originale auswählen">Alle „Original“ wählen</button><button type="button" class="secondary" data-reload>Aktualisieren</button></div>
      <div id="liblist" class="lib-list"></div><button type="button" class="secondary lib-more" id="libmore" hidden></button><div class="empty" id="libempty" hidden></div></div>
    <aside class="lib-detail" id="libdetail" hidden aria-live="polite"></aside><aside class="lib-sidecv" id="libside" hidden></aside></div>
  <div class="lib-bar" id="libbar" hidden role="region" aria-label="Auswahl"></div></section>
  ${jobsPanelHtml('jobs2', false)}`;

registerView({id: 'bibliothek', label: 'Bibliothek', icon: '▤', order: 20, mount(el){
  if(!el.dataset.built){
    el.dataset.built = '1'; el.innerHTML = HTML; box = $('#lib');
    box.addEventListener('click', onClick); box.addEventListener('change', onChange); box.addEventListener('input', onInput); box.addEventListener('keydown', onKey);
  }
  loadMeta().then(() => draw('all')).catch(() => {}); load();
}, unmount(){ stopPlayer(); L.play = ''; }});
setInterval(() => { if(isActive('bibliothek') && !L.edit) load(); }, 4000);
on('files-changed', () => { if(isActive('bibliothek')) { clearEst(); load(); } });
onState(() => { if(isActive('bibliothek')) schedule(); });
