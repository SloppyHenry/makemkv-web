// Shared helpers, state (S), connection to the server (server-sent events).
import { emit, notifyState } from './registry.js';

export const $ = (s, r=document) => r.querySelector(s);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const dec = s => String(s);
export const fmtB = n => { if(!n) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<4){n/=1024;i++} return dec(i?n.toFixed(i>2?2:1):n)+' '+u[i]; };
export const pad = n => String(n).padStart(2,'0');
export const fmtD = s => { s=Math.max(0,Math.round(s)); const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60; return h?`${h}:${pad(m)}:${pad(x)}`:`${m}:${pad(x)}`; };
export const ago = ts => { const s=Date.now()/1000-ts; return s<90?'just now':s<5400?`${Math.round(s/60)} min ago`:s<172800?`${Math.round(s/3600)} h ago`:`${Math.round(s/86400)} days ago`; };
export const setHtml = (el, h) => { if(el && el.dataset.h !== h){ el.innerHTML = h; el.dataset.h = h; } };
export const baseName = p => String(p).split('/').pop();

// Global state from the last server message (live binding: `import { S }` always sees the current value)
export let S = null;
export const conn = { failed: false };
// Shared UI state (selection, names, expanded sections …)
export const ui = { sel:{}, pre:{}, names:{}, folder:{}, open:{}, conv:{}, sig:{}, hideShort:false, cvOpen:true, rate:{}, files:[] };
export const keyOf = d => `${d.host||''}|${d.id}:${d.scan_id}`;
export const hostName = () => ((S.capacity && S.capacity.instance) || '').toLowerCase();

export function toast(msg, err=false){
  const el = $('#toast'); el.textContent = msg; el.classList.toggle('err', err); el.style.display = 'block';
  clearTimeout(toast.t); toast.t = setTimeout(() => el.style.display = 'none', err ? 6000 : 2800);
}
// FastAPI returns a list of error objects instead of text on 422
const detailText = d => Array.isArray(d) ? d.map(x => [(x.loc||[]).slice(1).join('.'), x.msg].filter(Boolean).join(': ')).join('; ') : (d && typeof d === 'object') ? (d.message || d.msg || JSON.stringify(d)) : d;
export async function api(path, method='POST', body){
  const r = await fetch(path, {method, headers: body?{'Content-Type':'application/json'}:{}, body: body?JSON.stringify(body):undefined});
  if(!r.ok){ let m=r.statusText; try{ m=detailText((await r.json()).detail) || m }catch{} toast(m, true); throw new Error(m); }
  return r.json();
}

// Event handling for elements that only appear in the DOM later: delegate('#jobs', 'click', (e, root) => …)
export function delegate(selector, type, handler){
  document.addEventListener(type, e => { const root = e.target.closest && e.target.closest(selector); if(root) handler(e, root); });
}

// ---------- Connection (server-sent events)
export function connect(){
  const es = new EventSource('/api/events');
  es.onmessage = e => { S = JSON.parse(e.data); conn.failed = false; notifyState(S); };
  es.onerror = () => { conn.failed = true; es.close(); emit('conn'); setTimeout(connect, 2500); };
}
