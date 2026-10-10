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
export async function deleteFile(path){
  if(!confirm(`„${path}“ endgültig löschen?`)) return;
  const r = await fetch('/api/files?path=' + encodeURIComponent(path), {method: 'DELETE'});
  if(!r.ok){ let m = 'Löschen fehlgeschlagen'; try{ m = (await r.json()).detail || m; }catch{ /* ohne Text */ } toast(m, true); return; }
  L.sel.delete(path); if(L.cur === path) L.cur = '';
  await refresh(); emit('files-changed');
}
export async function jobAct(kind, id, host){
  if(kind === 'cancel' && !confirm('Konvertierung abbrechen? Das Original bleibt unverändert.')) return;
  try{ await api(host ? `/api/peer/${host}/conversions/${id}/${kind}` : `/api/conversions/${id}/${kind}`); }catch{ /* api() zeigt die Meldung */ }
  await refresh();
}
/** Alle Dateien genau dieses Ordners (unabhängig vom Filter). */
export const filesIn = dir => L.files.filter(f => dirOf(f.path) === dir);
export { byPath };
