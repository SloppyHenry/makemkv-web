// Hilfen rund um die Rechnerliste (Paket C); auch für andere Module nutzbar (z. B. „Ausführen auf“ in der Bibliothek).
import { S, dec } from './core.js';

export const hostOf = url => String(url || '').replace(/^https?:\/\//, '');

// Rechner im Verbund, der neue Funktionen versteht: erreichbar und nicht der alte Stand (ohne Kopplung/Fähigkeitsmeldung)
export const peerUsable = p => !!(p && p.reachable && !p.legacy);
// Meldet der Rechner eine Fähigkeit? Alte Rechner nie (im Zweifel ausgrauen).
export const peerCan = (p, name) => peerUsable(p) && !!(p.capabilities && p.capabilities[name]);

// Zeit seit einem Zeitpunkt der Serveruhr: „vor 2 Std.“
export function agoSrv(ts){
  const s = Math.max(0, ((S && S.now) || Date.now() / 1000) - ts);
  return s < 90 ? 'gerade eben' : s < 5400 ? `vor ${Math.round(s / 60)} Min.` : s < 172800 ? `vor ${Math.round(s / 3600)} Std.` : `vor ${Math.round(s / 86400)} Tagen`;
}
// Dauer: „3 Tagen“, „5 Std.“, „12 Min.“ (für „online seit …“)
export function spanTxt(sec){
  sec = Math.max(0, sec);
  return sec < 90 ? 'weniger als 2 Min.' : sec < 5400 ? `${Math.round(sec / 60)} Min.` : sec < 172800 ? `${Math.round(sec / 3600)} Std.` : `${Math.round(sec / 86400)} Tagen`;
}
export const gb = n => n ? `${dec((n / 2 ** 30).toFixed(n < 2 ** 33 ? 1 : 0))} GB` : '';

const ENC = { libx265: 'x265', libx264: 'x264', libsvtav1: 'AV1', libaom_av1: 'AV1' };
// Kurzliste der Encoder eines Rechners aus capabilities.encoders (Text-Liste oder Objekt); leer, wenn nichts gemeldet wird
export function encoderChips(p){
  const e = p.capabilities && p.capabilities.encoders;
  const names = Array.isArray(e) ? e : e && typeof e === 'object' ? Object.keys(e) : [];
  return [...new Set(names.map(n => ENC[n]).filter(Boolean))];
}
