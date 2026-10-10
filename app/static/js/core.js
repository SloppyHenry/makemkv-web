// Gemeinsame Hilfen, Status (S), Verbindung zum Server (Server-Sent Events).
import { emit, notifyState } from './registry.js';

export const $ = (s, r=document) => r.querySelector(s);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const dec = s => String(s).replace('.', ',');
export const fmtB = n => { if(!n) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<4){n/=1024;i++} return dec(i?n.toFixed(i>2?2:1):n)+' '+u[i]; };
export const pad = n => String(n).padStart(2,'0');
export const fmtD = s => { s=Math.max(0,Math.round(s)); const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60; return h?`${h}:${pad(m)}:${pad(x)}`:`${m}:${pad(x)}`; };
export const ago = ts => { const s=Date.now()/1000-ts; return s<90?'gerade eben':s<5400?`vor ${Math.round(s/60)} Min.`:s<172800?`vor ${Math.round(s/3600)} Std.`:`vor ${Math.round(s/86400)} Tagen`; };
export const setHtml = (el, h) => { if(el && el.dataset.h !== h){ el.innerHTML = h; el.dataset.h = h; } };
export const baseName = p => String(p).split('/').pop();

// Globaler Status der letzten Serverantwort (live-gebunden: `import { S }` sieht immer den aktuellen Wert)
export let S = null;
export const conn = { failed: false };
// Gemeinsamer Zustand der Oberfläche (Auswahl, Namen, geöffnete Bereiche …)
export const ui = { sel:{}, names:{}, folder:{}, open:{}, conv:{}, sig:{}, hideShort:false, cvOpen:true, rate:{}, files:[] };
export const keyOf = d => `${d.host||''}|${d.id}:${d.scan_id}`;
export const hostName = () => ((S.capacity && S.capacity.instance) || '').toLowerCase();

export function toast(msg, err=false){
  const el = $('#toast'); el.textContent = msg; el.classList.toggle('err', err); el.style.display = 'block';
  clearTimeout(toast.t); toast.t = setTimeout(() => el.style.display = 'none', err ? 6000 : 2800);
}
export async function api(path, method='POST', body){
  const r = await fetch(path, {method, headers: body?{'Content-Type':'application/json'}:{}, body: body?JSON.stringify(body):undefined});
  if(!r.ok){ let m=r.statusText; try{ m=(await r.json()).detail||m }catch{} toast(m, true); throw new Error(m); }
  return r.json();
}

// Ereignisbehandlung für Elemente, die erst später im DOM entstehen: delegate('#jobs', 'click', (e, root) => …)
export function delegate(selector, type, handler){
  document.addEventListener(type, e => { const root = e.target.closest && e.target.closest(selector); if(root) handler(e, root); });
}

// ---------- Verbindung (Server-Sent Events)
export function connect(){
  const es = new EventSource('/api/events');
  es.onmessage = e => { S = JSON.parse(e.data); conn.failed = false; notifyState(S); };
  es.onerror = () => { conn.failed = true; es.close(); emit('conn'); setTimeout(connect, 2500); };
}
