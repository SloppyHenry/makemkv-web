// Bibliothek: gemeinsamer Zustand, Einordnung der Dateien, Filter, Gruppen und kleine Formatierhelfer. Besitzer: PF.
import { S, baseName, hostName } from './core.js';

export const L = {files: [], dir: '', probing: 0, instance: '', summary: null, loaded: false, media: {}, mediaAsked: new Set(), mediaOn: true, sel: new Set(), cur: '', q: 'all', kind: 'all', folder: '', node: '', text: '',
  view: 'list', limit: 200, edit: null, cvOpen: false, filtOpen: false, play: '', preset: 'auto', target: 'local', cfg: null, est: null};
try{ L.view = localStorage.getItem('libView') === 'grid' ? 'grid' : 'list'; }catch{ /* ohne Speicher */ }
export const setView = v => { L.view = v; try{ localStorage.setItem('libView', v); }catch{ /* ohne Speicher */ } };

export const dirOf = p => p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';
export const topOf = p => p.includes('/') ? p.slice(0, p.indexOf('/')) : '';
const CODEC = {h264: 'H.264', hevc: 'HEVC', vc1: 'VC-1', mpeg2video: 'MPEG-2', mpeg4: 'MPEG-4', av1: 'AV1', wmv3: 'WMV'};
export const codecName = c => CODEC[c] || (c || '?').toUpperCase();
export const resName = i => (!i.h ? '' : i.h >= 1600 || i.w >= 3000 ? 'UHD' : i.h >= 1000 || i.w >= 1800 ? '1080p' : i.h >= 650 ? '720p' : i.h > 0 && i.h <= 600 ? 'SD' : i.h + 'p');
export function audioName(a){
  if(!a) return '';
  const c = String(a.codec || '').toLowerCase(), pr = String(a.profile || ''), ch = a.ch >= 6 ? ` ${a.ch - 1}.1` : a.ch === 2 ? ' 2.0' : a.ch === 1 ? ' 1.0' : '';
  const n = c === 'truehd' ? 'TrueHD' : c === 'dts' ? (/MA/.test(pr) ? 'DTS-HD MA' : /HRA|HD/.test(pr) ? 'DTS-HD' : 'DTS') : c === 'eac3' ? 'E-AC3' : c === 'ac3' ? 'AC3' : c === 'flac' ? 'FLAC' : c.startsWith('pcm') ? 'PCM' : c.toUpperCase();
  return n + ch;
}

// Jobs und Fehler aus dem Live-Status (Aufträge dieses und anderer Rechner): Pfad -> {status, pct, host, id}
export function liveJobs(){
  const m = new Map(), me = hostName();
  const add = (c, host) => { if(c.origin !== 'library') return; const k = c.name; if(c.status === 'queued' || c.status === 'running') m.set(k, {job: {status: c.status, pct: c.pct || 0, host: host === me ? '' : host, id: c.id, eta: c.eta, paused: c.paused, cancel: c.cancel}});
    else if(c.status === 'error' && !m.has(k)) m.set(k, {err: c.error || 'Konvertierung fehlgeschlagen'}); };
  if(S){ (S.conversions || []).forEach(c => add(c, me)); (S.peers || []).forEach(p => p.reachable && (p.conversions || []).forEach(c => add(c, p.name))); }
  return m;
}
export function statusOf(f, live){
  const lv = live.get(f.path), job = (lv && lv.job) || f.job;
  if(job) return 'run';
  if(f.locked) return 'lock';
  if(lv && lv.err) return 'err';
  if(f.state === 'probing') return 'probing';
  if(f.state === 'unknown') return 'err';
  if(!f.info) return 'other';
  return f.info.codec === 'hevc' || f.info.codec === 'av1' ? 'conv' : 'orig';
}
export function decorate(files){
  const live = liveJobs();
  for(const f of files){
    const lv = live.get(f.path);
    f.live = (lv && lv.job) || f.job || null;
    f.errText = lv && lv.err ? lv.err : f.state === 'unknown' ? (f.dev_err || 'nicht lesbar') : '';
    f.status = statusOf(f, live);
    f.m = L.media[f.path] || null;
  }
  return files;
}
export const selectable = f => !f.live && !f.locked && f.state !== 'probing' && f.state !== 'unknown' && f.state !== 'other' && !!f.info;

export function counts(files){
  const c = {all: files.length, orig: 0, conv: 0, run: 0, err: 0};
  for(const f of files){ if(c[f.status] != null) c[f.status]++; }
  return c;
}
export function matches(f){
  const t = L.text.trim().toLowerCase();
  if(t && !(f.path.toLowerCase().includes(t) || (f.m && String(f.m.title || '').toLowerCase().includes(t)))) return false;
  if(L.q !== 'all' && f.status !== L.q) return false;
  if(L.kind !== 'all' && kindOf(f) !== L.kind) return false;
  if(L.folder !== '' && !(L.folder === '/' ? dirOf(f.path) === '' : f.path === L.folder || f.path.startsWith(L.folder + '/'))) return false;
  if(L.node && !(f.live && (f.live.host || hostName()) === L.node)) return false;
  return true;
}
export const kindOf = f => (f.m && f.m.kind === 'movie' ? 'film' : f.m && f.m.kind === 'series' ? 'serie' : 'uns');
export function groups(files){
  const m = new Map();
  for(const f of files){ const d = dirOf(f.path); if(!m.has(d)) m.set(d, []); m.get(d).push(f); }
  m.forEach(v => v.sort((a, b) => baseName(a.path).localeCompare(baseName(b.path), 'de', {numeric: true})));
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], 'de'));
}
export const saveOf = f => (f.est && !f.est.issue && f.status !== 'conv' ? Math.max(0, f.size - f.est.bytes) : 0);
export const byPath = p => L.files.find(f => f.path === p);
export const selectedFiles = () => L.files.filter(f => L.sel.has(f.path) && selectable(f));

// Stabile Liste: nur geänderte Elemente werden ersetzt (Fokus, Auswahl, Maus und laufende Animationen bleiben)
export function reconcile(box, items){
  const old = new Map([...box.children].map(el => [el.dataset.key, el]));
  let prev = null;
  for(const it of items){
    let el = old.get(it.key); old.delete(it.key);
    if(!el || el._h !== it.html){
      const t = document.createElement('template'); t.innerHTML = it.html.trim();
      const n = t.content.firstElementChild; n._h = it.html;
      n.querySelectorAll('.status-check.run').forEach(sp => { sp.style.animationDelay = -(Date.now() % 1000) + 'ms'; });       // Drehphase an die Uhr koppeln
      if(el) el.replaceWith(n);
      el = n;
    }
    const want = prev ? prev.nextElementSibling : box.firstElementChild;
    if(el !== want) box.insertBefore(el, want);
    prev = el;
  }
  old.forEach(el => el.remove());
}
