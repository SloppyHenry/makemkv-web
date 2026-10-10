// Alte Konvertierungs-Felder (Standard-Preset-Formular). PF ersetzt sie durch js/convert-editor.js.
import { esc } from './core.js';

export const CV_FALLBACK = {convert:false, rf:21, preset:'slow', tune:'none', extra:'aq-mode=3:no-sao=1', audio:'copy'};
export const PRESETS = ['ultrafast','fast','medium','slow','slower','veryslow'];
export const TUNES = [['none','keins'],['film','film'],['animation','animation'],['grain','grain'],['stillimage','stillimage']];
export const AUDIOS = [['copy','Original (Passthrough)'],['ac3','AC3 640 kb/s'],['aac','AAC 256 kb/s']];
export const AUDIO_NAMEN = {copy:'Original-Audio', ac3:'AC3 640 kb/s', aac:'AAC 256 kb/s', eac3:'E-AC3 640 kb/s', opus:'Opus'};
export const optsOf = (list, cur) => list.map(([v,l]) => `<option value="${v}" ${String(v)===String(cur)?'selected':''}>${l}</option>`).join('');
export function cvFields(c, attr, dis){
  const rfs = [18,19,20,21,22,23,24,25]; if(!rfs.includes(+c.rf)){ rfs.push(+c.rf); rfs.sort((a,b)=>a-b); }
  const aud = AUDIOS.some(([v]) => v===c.audio) ? AUDIOS : [...AUDIOS, [c.audio, AUDIO_NAMEN[c.audio]||c.audio]];
  return `<div class="field"><label for="${attr}-rf">Qualität (RF)</label><select id="${attr}-rf" data-${attr}="rf" ${dis}>${optsOf(rfs.map(v=>[v,v]), c.rf)}</select></div>
    <div class="field"><label for="${attr}-preset">Preset</label><select id="${attr}-preset" data-${attr}="preset" ${dis}>${optsOf(PRESETS.map(v=>[v,v]), c.preset)}</select></div>
    <div class="field"><label for="${attr}-tune">Tune</label><select id="${attr}-tune" data-${attr}="tune" ${dis}>${optsOf(TUNES, c.tune)}</select></div>
    <div class="field"><label for="${attr}-audio">Audio</label><select id="${attr}-audio" data-${attr}="audio" ${dis}>${optsOf(aud, c.audio)}</select></div>
    <div class="field full"><label for="${attr}-extra">Zusatz-Optionen x265</label><input id="${attr}-extra" data-${attr}="extra" value="${esc(c.extra)}" placeholder="z. B. aq-mode=3:no-sao=1" ${dis}></div>`;
}
export const CV_HELP = 'RF 20–22 ist ein guter Kompromiss. Software-Encoding (CPU), Untertitel und Kapitel bleiben unverändert; schwarze Balken werden automatisch entfernt. x265 rechnet nur auf der CPU. Mit „slow“ kann die Konvertierung deutlich länger als das Rippen dauern. („film“ und „stillimage“ kennt x265 nicht – dann wird kein Tune gesetzt.)';
export const cvSummary = c => c.convert ? `x265 10-bit · RF ${c.rf} · Preset ${c.preset} · Tune ${c.tune==='none'?'keins':c.tune} · ${AUDIO_NAMEN[c.audio]||c.audio}` : 'aus – Original ohne Konvertierung';
