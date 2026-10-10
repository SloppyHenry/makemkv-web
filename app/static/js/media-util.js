// Medien / Jellyfin (PE): kleine Hilfen. Eigene Anfrage-Funktion, weil der Toast in core.js Validierungsfehler (422) nicht lesbar zeigt.
import { esc, fmtB, toast } from './core.js';

export { esc, fmtB };

/** FastAPI-Fehlerdetail (Text, Liste von Prüffehlern oder Objekt) als lesbarer Satz. */
export function errText(d){
  if(!d) return 'Unbekannter Fehler';
  if(typeof d === 'string') return d;
  if(Array.isArray(d)) return d.map(errText).join('; ');
  if(d.msg) return (d.loc && d.loc.length ? d.loc.filter(x => x !== 'body').join('.') + ': ' : '') + d.msg;
  return Object.entries(d).map(([k, v]) => `${k}: ${errText(v)}`).join('; ');
}

/** Anfrage an /api/media/… ; wirft bei Fehlern (mit lesbarer Meldung) und zeigt sie als Toast, außer `quiet`. */
export async function mapi(path, method = 'GET', body, quiet = false){
  const r = await fetch('/api/media' + path, {method, headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  if(!r.ok){
    let m = r.statusText;
    try{ m = errText((await r.json()).detail) || m; }catch{ /* keine JSON-Antwort */ }
    if(!quiet) toast(m, true);
    throw new Error(m);
  }
  return r.json();
}

export const baseName = p => String(p).split('/').pop();
export const fmtDur = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`; };
export const pct = c => Math.round((c || 0) * 100);
/** „Titel 01“ aus langen Dateinamen („… - Disc 1 - Titel 01.mkv“) für enge Tabellen. */
export const shortName = p => { const n = baseName(p).replace(/\.[^.]+$/, ''); const m = n.match(/((?:Titel|Title|Track|t)[ _-]?\d+)$/i); return m ? m[1] : n; };
export const changed = el => el.dispatchEvent(new Event('change', {bubbles: true}));
