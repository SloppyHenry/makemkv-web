// „Fertige Dateien“ (kompakte Liste der letzten Dateien im Ziel).
import { $, ago, baseName, delegate, esc, fmtB, setHtml, toast, ui } from './core.js';
import { emit, getLibraryActions, on, onState, registerPanel } from './registry.js';

export async function loadFiles(){
  try{ ui.files = (await (await fetch('/api/files')).json()).files; }catch{ return; }
  if(!$('#filesBody')) return;
  const f = ui.files.slice(0,6);
  $('#nofiles').hidden = f.length > 0;
  const prim = x => getLibraryActions().find(a => a.primary && a.when([x]));      // primäre Aktion (Abspielen) am Dateinamen
  setHtml($('#filesBody'), f.map(x => `<tr><td class="file-name" title="${esc(x.path)}">${prim(x) ? `<button type="button" class="player-link" data-fprim="${esc(x.path)}">${esc(baseName(x.path))}</button>` : esc(baseName(x.path))}</td><td>${fmtB(x.size)}</td><td class="muted">${ago(x.mtime)}</td>
    <td><a class="file-action" title="Download" aria-label="Download" href="/api/download?path=${encodeURIComponent(x.path)}">↓</a></td></tr>`).join(''));
}
delegate('#filesBody', 'click', e => {
  const b = e.target.closest('[data-fprim]'), x = b && ui.files.find(f => f.path === b.dataset.fprim), a = x && getLibraryActions().find(a => a.primary && a.when([x]));
  if(a) a.run([x]);
});
delegate('#files-reload', 'click', () => { loadFiles(); toast('Dateiliste aktualisiert.'); });

// Listen neu laden, wenn ein Rip endet oder eine Übertragung fertig wird; Bibliothek u. a. hören auf „files-changed“
const wasBusy = {};
let upDone = -1;
onState(S => {
  let changed = false;
  for(const x of S.drives){ const was = wasBusy[x.id]; wasBusy[x.id] = !!x.job; if(was && !x.job) changed = true; }
  const done = (S.uploads||[]).filter(u => u.status==='done').length;
  if(done !== upDone){ upDone = done; changed = true; }
  if(changed){ loadFiles(); emit('files-changed'); }
});
on('view', id => { if(id === 'laufwerke') loadFiles(); });
loadFiles(); setInterval(loadFiles, 60000);

registerPanel({view:'laufwerke', slot:'right', order:20, id:'files', html:`<section class="panel">
          <div class="panel-head"><span class="mini-icon">▱</span><h2>Fertige Dateien</h2><span class="spacer"></span><button class="secondary" id="files-reload">Aktualisieren</button></div>
          <div class="table-wrap"><table class="file-table"><thead><tr><th>Dateiname</th><th>Größe</th><th>Status</th><th></th></tr></thead><tbody id="filesBody"></tbody></table></div>
          <div class="empty" id="nofiles" hidden>Noch nichts im Ausgabeordner.</div>
        </section>`});
