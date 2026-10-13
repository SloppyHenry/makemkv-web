// Media / Jellyfin (PE): small helpers. Own request function, because the toast in core.js does not show validation errors (422) readably.
import { esc, fmtB, toast } from './core.js';

export { esc, fmtB };

/** FastAPI error detail (text, list of validation errors or object) as a readable sentence. */
export function errText(d){
  if(!d) return 'Unknown error';
  if(typeof d === 'string') return d;
  if(Array.isArray(d)) return d.map(errText).join('; ');
  if(d.msg) return (d.loc && d.loc.length ? d.loc.filter(x => x !== 'body').join('.') + ': ' : '') + d.msg;
  return Object.entries(d).map(([k, v]) => `${k}: ${errText(v)}`).join('; ');
}

/** Request to /api/media/… ; throws on errors (with a readable message) and shows them as a toast, unless `quiet`. */
export async function mapi(path, method = 'GET', body, quiet = false){
  const r = await fetch('/api/media' + path, {method, headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  if(!r.ok){
    let m = r.statusText;
    try{ m = errText((await r.json()).detail) || m; }catch{ /* no JSON response */ }
    if(!quiet) toast(m, true);
    throw new Error(m);
  }
  return r.json();
}

export const baseName = p => String(p).split('/').pop();
export const fmtDur = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`; };
export const pct = c => Math.round((c || 0) * 100);
/** "Title 01" from long file names ("… - Disc 1 - Title 01.mkv") for narrow tables. */
export const shortName = p => { const n = baseName(p).replace(/\.[^.]+$/, ''); const m = n.match(/((?:Titel|Title|Track|t)[ _-]?\d+)$/i); return m ? m[1] : n; };
export const changed = el => el.dispatchEvent(new Event('change', {bubbles: true}));
