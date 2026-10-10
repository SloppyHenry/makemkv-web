// Konvertierungs-Editor: Metadaten vom Server (Codecs, Presets, Fähigkeiten) und kleine Rechenhilfen. Besitzer: PF.
import { S, api, hostName } from './core.js';
import { emit, on } from './registry.js';

let meta = null, pending = null;
export const MIRROR = ['rf', 'preset', 'tune', 'extra', 'audio'];       // alte Felder: der Server rechnet sie aus v2 aus, der Editor schickt sie nie mit

export function loadMeta(force = false){
  if(meta && !force) return Promise.resolve(meta);
  if(!pending || force) pending = fetch('/api/convert/meta').then(r => r.json()).then(m => { meta = m; pending = null; return m; }).catch(e => { pending = null; throw e; });
  return pending;
}
export const metaNow = () => meta;
export function reloadMeta(){ return loadMeta(true).then(m => { emit('convert:meta', m); return m; }); }
on('conn', () => { meta = null; });

export const strip = cfg => { const c = JSON.parse(JSON.stringify(cfg || {})); MIRROR.forEach(k => delete c[k]); return c; };
export const clone = o => JSON.parse(JSON.stringify(o));

// ---- Qualitätsskala (0 = klein … 100 = beste): je Codec auf dessen CRF/QP-Bereich abgebildet
const scale = c => (meta && meta.scale[c]) || {worst: 30, best: 14};
export const levelOf = (codec, crf) => { const s = scale(codec); return Math.max(0, Math.min(100, (s.worst - crf) / (s.worst - s.best) * 100)); };
export const crfOf = (codec, level) => { const s = scale(codec); return Math.round(s.worst - (s.worst - s.best) * Math.max(0, Math.min(100, level)) / 100); };
export const qWord = level => ((meta && meta.words) || [[0, '']]).find(([t]) => level >= t)[1];
export const unitOf = cfg => (meta && meta.codecs[cfg.video.codec] ? meta.codecs[cfg.video.codec].unit : 'RF');

// ---- Fähigkeiten eines Rechners ('' oder eigener Name = dieser). null = alter Stand (nur x265 mit den bisherigen Optionen)
export function capsFor(target){
  if(!meta) return null;
  if(!target || target === hostName() || target === meta.instance) return meta.caps;
  const p = ((S && S.peers) || []).find(x => x.name === target);
  const c = p && p.capabilities && p.capabilities.convert;
  return c && c.schema >= 2 ? c : null;
}
export const hasCodec = (caps, c) => c === 'copy' || (caps ? (c === 'hw' ? (caps.hw || []).length > 0 : (caps.codecs || []).includes(c)) : c === 'x265');

// ---- Presets
export const presetById = id => (meta ? meta.presets.find(p => p.id === id) : null) || null;
export async function getDefaultConfig(kind = 'bluray'){
  const m = await loadMeta();
  const d = m.defaults[kind] || m.defaults.bluray;
  return {...clone(d.cfg), convert: false};
}
const AUD = {copy: 'Ton kopieren', aac: 'AAC', opus: 'Opus', ac3: 'AC3', eac3: 'E-AC3'};
/** Kurztext einer Einstellung (v1 oder v2), z. B. „x265 10-bit · RF 20 · slow · Ton kopieren“. */
export function cvSummary(cfg){
  if(!cfg) return '';
  if(!cfg.video){      // v1: fünf Felder
    return cfg.convert === false ? 'aus – Original ohne Konvertierung' : `x265 10-bit · RF ${cfg.rf} · ${cfg.preset} · ${AUD[cfg.audio] || cfg.audio}`;
  }
  const v = cfg.video, q = cfg.quality, p = cfg.picture, a = cfg.sound, name = v.codec === 'hw' ? v.hw : ({x265: 'x265', x264: 'x264', svtav1: 'SVT-AV1', copy: ''})[v.codec];
  const qual = q.mode === 'crf' ? `${unitOf(cfg)} ${q.crf}` : q.mode === 'size' ? `${q.size_gb} GB` : `${q.kbps} kb/s`;
  const bits = [v.codec === 'copy' ? 'Video kopieren' : `${name} ${v.bits}-bit · ${qual}${v.speed ? ' · ' + v.speed : ''}`];
  if(p.scale !== 'keep') bits.push(`≤ ${p.scale}p`);
  if(p.deint !== 'off') bits.push('Deinterlace');
  if(p.denoise !== 'off') bits.push('Entrauschen');
  bits.push(AUD[a.mode] + (a.mode !== 'copy' && a.channels === 'stereo' ? ' Stereo' : ''));
  return bits.join(' · ');
}
// Unterschied zweier Einstellungen (ohne convert/origin/Spiegel): Liste der geänderten Abschnitt.Feld-Pfade
export function diffPaths(a, b){
  const out = [];
  if(!a || !b) return out;
  for(const sec of ['video', 'quality', 'picture', 'sound', 'subs']) for(const k of Object.keys(b[sec] || {})) if(String((a[sec] || {})[k]) !== String(b[sec][k])) out.push(`${sec}.${k}`);
  return out;
}
export const getPath = (o, path) => path.split('.').reduce((x, k) => (x == null ? x : x[k]), o);
export function setPath(o, path, v){ const ks = path.split('.'), last = ks.pop(); ks.reduce((x, k) => x[k], o)[last] = v; }
export { api };
