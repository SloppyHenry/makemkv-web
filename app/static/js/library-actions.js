// Library: rename (file/folder), delete, skip/cancel jobs. Owner: PF.
import { $, api, baseName, toast } from './core.js';
import { L, byPath, dirOf } from './library-model.js';
import { emit } from './registry.js';

let refresh = async () => {}, redraw = () => {};
export const setHooks = (r, d) => { refresh = r; redraw = d; };
export const closed = new Set((() => { try{ return JSON.parse(localStorage.getItem('libClosed') || '[]'); }catch{ return []; } })());
export const saveClosed = () => { try{ localStorage.setItem('libClosed', JSON.stringify([...closed])); }catch{ /* no storage */ } };

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
    const old = e.path, renamed = r.path, mv = p => (p === old || p.startsWith(old + '/') ? renamed + p.slice(old.length) : p);
    [...L.sel].forEach(p => { if(mv(p) !== p){ L.sel.delete(p); L.sel.add(mv(p)); } });
    [...closed].forEach(p => { if(mv(p) !== p){ closed.delete(p); closed.add(mv(p)); } }); saveClosed();
    if(L.cur) L.cur = mv(L.cur);
    toast(e.kind === 'file' ? 'File renamed ✓' : 'Folder renamed ✓');
    L.edit = null; await refresh(); emit('files-changed');
  }catch{ /* api() shows the message; the input stays open for correction */ }
}
async function delOne(path){
  const r = await fetch('/api/files?path=' + encodeURIComponent(path), {method: 'DELETE'});
  if(r.ok) return '';
  let m = 'Delete failed'; try{ m = (await r.json()).detail || m; }catch{ /* no text */ }
  return m;
}
/** Permanently delete one or more files (one confirmation for all). */
export async function deleteFiles(paths, folder = ''){
  if(!paths.length) return;
  const one = paths.length === 1 && !folder;
  if(!confirm(one ? `Permanently delete "${paths[0]}"?` : `Permanently delete ${folder ? `folder "${folder}" with ` : ''}${paths.length} file${paths.length === 1 ? '' : 's'}?\n\n` + paths.slice(0, 8).map(p => '• ' + baseName(p)).join('\n') + (paths.length > 8 ? `\n… and ${paths.length - 8} more` : ''))) return;
  const failed = [];
  for(const p of paths){
    const m = await delOne(p);
    if(m) failed.push(`${baseName(p)}: ${m}`); else { L.sel.delete(p); if(L.cur === p) L.cur = ''; }
  }
  if(failed.length) toast(one ? failed[0] : `${paths.length - failed.length} deleted, ${failed.length} failed – ${failed[0]}`, true);
  else if(!one) toast(`${paths.length} files deleted ✓`);
  if(!L.sel.size){ L.est = null; L.cfg = null; L.preset = 'auto'; }
  await refresh(); emit('files-changed');
}
/** Delete all unlocked files of a folder; the empty folder disappears with the last file. */
export const deleteFolder = dir => deleteFiles(filesIn(dir).filter(f => !f.live && !f.locked).map(f => f.path), dir);
export const deleteFile = path => deleteFiles([path]);
export async function jobAct(kind, id, host){
  if(kind === 'cancel' && !confirm('Cancel the conversion? The original stays unchanged.')) return;
  try{ await api(host ? `/api/peer/${host}/conversions/${id}/${kind}` : `/api/conversions/${id}/${kind}`); }catch{ /* api() shows the message */ }
  await refresh();
}
/** All files of exactly this folder (regardless of the filter). */
export const filesIn = dir => L.files.filter(f => dirOf(f.path) === dir);
export { byPath };
