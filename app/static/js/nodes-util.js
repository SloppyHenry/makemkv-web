// Helpers around the machine list (package C); usable by other modules too (e.g. "Run on" in the library).
import { S, dec } from './core.js';

export const hostOf = url => String(url || '').replace(/^https?:\/\//, '');

// Machine in the cluster that understands new features: reachable and not the old version (without pairing/capability report)
export const peerUsable = p => !!(p && p.reachable && !p.legacy);
// Does the machine report a capability? Old machines never do (when in doubt, grey out).
export const peerCan = (p, name) => peerUsable(p) && !!(p.capabilities && p.capabilities[name]);

// Time since a point in time on the server clock: "2 h ago"
export function agoSrv(ts){
  const s = Math.max(0, ((S && S.now) || Date.now() / 1000) - ts);
  return s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 172800 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
}
// Duration: "3 days", "5 h", "12 min" (for "online for …")
export function spanTxt(sec){
  sec = Math.max(0, sec);
  return sec < 90 ? 'less than 2 min' : sec < 5400 ? `${Math.round(sec / 60)} min` : sec < 172800 ? `${Math.round(sec / 3600)} h` : `${Math.round(sec / 86400)} days`;
}
export const gb = n => n ? `${dec((n / 2 ** 30).toFixed(n < 2 ** 33 ? 1 : 0))} GB` : '';

const ENC = { libx265: 'x265', libx264: 'x264', libsvtav1: 'AV1', libaom_av1: 'AV1' };
// Short list of a machine's encoders from capabilities.encoders (list of names or object); empty if nothing is reported
export function encoderChips(p){
  const e = p.capabilities && p.capabilities.encoders;
  const names = Array.isArray(e) ? e : e && typeof e === 'object' ? Object.keys(e) : [];
  return [...new Set(names.map(n => ENC[n]).filter(Boolean))];
}
