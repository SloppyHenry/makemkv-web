// Bibliothek: Umbenennen (Datei/Ordner), Löschen, Überspringen/Abbrechen von Aufträgen. Besitzer: PF.
import { $, api, baseName, toast } from './core.js';
import { L, byPath, dirOf } from './library-model.js';
import { emit } from './registry.js';

let refresh = async () => {}, redraw = () => {};
export const setHooks = (r, d) => { refresh = r; redraw = d; };
export const closed = new Set((() => { try{ return JSON.parse(localStorage.getItem('libClosed') || '[]'); }catch{ return []; } })());
export const saveClosed = () => { try{ localStorage.setItem('libClosed', JSON.stringify([...closed])); }catch{ /* ohne Speicher */ } };

export function startEdit(kind, path){
  if(kind === 'file'){ const nm = baseName(path), i = nm.lastIndexOf('.'); L.edit = {kind, path, initial: i > 0 ? nm.slice(0, i) : nm, ext: i > 0 ? nm.slice(i) : ''}; }
  else L.edit = {kind, path, initial: baseName(path), ext: ''};
  redraw(); const i = $('#lib-edit'); if(i){ i.focus(); i.select(); }
}
export function stopEdit(){ L.edit = null; redraw(); }
export async function commitEdit(){
  const e = L.edit, inp = $('#lib-edit'); if(!e || !inp) return;
  const value = inp.value.trim(); if(!value || value === e.initial){ stopEdit(); return; }
  try{
    const r = await api(e.kind === 'file' ? '/api/library/rename' : '/api/library/rename-folder', 'POST', {path: e.path, name: value});
    const old = e.path, neu = r.path, mv = p => (p === old || p.startsWith(old + '/') ? neu + p.slice(old.length) : p);
    [...L.sel].forEach(p => { if(mv(p) !== p){ L.sel.delete(p); L.sel.add(mv(p)); } });
    [...closed].forEach(p => { if(mv(p) !== p){ closed.delete(p); closed.add(mv(p)); } }); saveClosed();
    if(L.cur) L.cur = mv(L.cur);
    toast(e.kind === 'file' ? 'Datei umbenannt ✓' : 'Ordner umbenannt ✓');
    L.edit = null; await refresh(); emit('files-changed');
  }catch{ /* api() zeigt die Meldung; die Eingabe bleibt zum Korrigieren offen */ }
}
async function delOne(path){
  const r = await fetch('/api/files?path=' + encodeURIComponent(path), {method: 'DELETE'});
  if(r.ok) return '';
  let m = 'Löschen fehlgeschlagen'; try{ m = (await r.json()).detail || m; }catch{ /* ohne Text */ }
  return m;
}
/** Eine oder mehrere Dateien endgültig löschen (eine Rückfrage für alle). */
export async function deleteFiles(paths, folder = ''){
  if(!paths.length) return;
  const one = paths.length === 1 && !folder;
  if(!confirm(one ? `„${paths[0]}“ endgültig löschen?` : `${folder ? `Ordner „${folder}“ mit ` : ''}${paths.length} Datei${paths.length === 1 ? '' : 'en'} endgültig löschen?\n\n` + paths.slice(0, 8).map(p => '• ' + baseName(p)).join('\n') + (paths.length > 8 ? `\n… und ${paths.length - 8} weitere` : ''))) return;
  const failed = [];
  for(const p of paths){
    const m = await delOne(p);
    if(m) failed.push(`${baseName(p)}: ${m}`); else { L.sel.delete(p); if(L.cur === p) L.cur = ''; }
  }
  if(failed.length) toast(one ? failed[0] : `${paths.length - failed.length} gelöscht, ${failed.length} fehlgeschlagen – ${failed[0]}`, true);
  else if(!one) toast(`${paths.length} Dateien gelöscht ✓`);
  if(!L.sel.size){ L.est = null; L.cfg = null; L.preset = 'auto'; }
  await refresh(); emit('files-changed');
}
/** Alle nicht gesperrten Dateien eines Ordners löschen; der leere Ordner verschwindet mit der letzten Datei. */
export const deleteFolder = dir => deleteFiles(filesIn(dir).filter(f => !f.live && !f.locked).map(f => f.path), dir);
export const deleteFile = path => deleteFiles([path]);
export async function jobAct(kind, id, host){
  if(kind === 'cancel' && !confirm('Konvertierung abbrechen? Das Original bleibt unverändert.')) return;
  try{ await api(host ? `/api/peer/${host}/conversions/${id}/${kind}` : `/api/conversions/${id}/${kind}`); }catch{ /* api() zeigt die Meldung */ }
  await refresh();
}
/** Alle Dateien genau dieses Ordners (unabhängig vom Filter). */
export const filesIn = dir => L.files.filter(f => dirOf(f.path) === dir);
export { byPath };
