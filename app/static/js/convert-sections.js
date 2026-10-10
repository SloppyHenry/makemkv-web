// Konvertierungs-Editor: die Abschnitte der Anpassen-Ansicht (Video, Qualität, Geschwindigkeit, Bild, Ton, Untertitel, Experten). Besitzer: PF.
import { esc } from './core.js';
import { crfOf, diffPaths, hasCodec, levelOf, qWord, unitOf } from './convert-meta.js';

const SIZE_NOTE = 'x265/x264 kodieren dafür in zwei Durchgängen (dauert etwa doppelt so lang); SVT-AV1 und Hardware in einem Durchgang mit Zielbitrate.';

export const seg = (path, opts, cur, dis = {}) => `<div class="cv-seg" role="radiogroup">${opts.map(([v, l, s]) =>
  `<button type="button" class="${String(cur) === String(v) ? 'on' : ''}" role="radio" aria-checked="${String(cur) === String(v)}" data-set="${path}" data-v="${esc(v)}" ${dis[v] ? `disabled title="${esc(dis[v])}"` : ''}>${esc(l)}${s ? `<small>${esc(s)}</small>` : ''}</button>`).join('')}</div>`;

export function ctx(cfg, base, caps){ return {cfg, base, caps, ch: new Set(diffPaths(cfg, base))}; }
const chg = (x, ...ps) => ps.some(p => x.ch.has(p));
const dot = (x, ...ps) => chg(x, ...ps) ? '<span class="dot" title="gegenüber dem Preset geändert"></span>' : '';
const reset = (x, ...ps) => chg(x, ...ps) ? `<button type="button" class="cv-link" data-reset="${ps.join(',')}">zurück auf Preset</button>` : '';

function videoBlock(x){
  const {cfg, caps} = x, v = cfg.video, hw = caps && caps.hw ? caps.hw : [];
  const no = c => (hasCodec(caps, c) ? '' : caps ? 'Dieser Rechner meldet das nicht' : 'Älterer Stand: nur x265 mit den bisherigen Optionen');
  const dis = {}; ['x264', 'svtav1', 'hw'].forEach(c => { if(no(c)) dis[c] = no(c); });
  const hwSel = v.codec === 'hw' ? `<div class="cv-row"><label for="cv-hw">Hardware-Encoder</label><select class="input" id="cv-hw" data-set="video.hw" style="max-width:260px">${hw.map(e => `<option ${e === v.hw ? 'selected' : ''}>${esc(e)}</option>`).join('')}</select>
    <span class="hint">Hardware-Encoder sind sehr schnell, bei gleicher Größe aber sichtbar schlechter als Software. Der Segment-Modus ist dafür aus.</span></div>` : '';
  const ten = v.hw.startsWith('h264_');
  return `<div class="cv-row"><label>Codec ${reset(x, 'video.codec')}</label>${seg('video.codec', [['x265', 'H.265 / HEVC', 'x265'], ['x264', 'H.264', 'x264'], ['svtav1', 'AV1', 'SVT-AV1'], ['hw', 'Hardware', hw.length ? 'VAAPI/QSV …' : 'nicht verfügbar'], ['copy', 'Nur remuxen', 'ohne Neukodierung']], v.codec, dis)}</div>${hwSel}
  ${v.codec === 'copy' ? '<p class="hint">Das Bild bleibt unverändert; Ton, Untertitel und Kapitel lassen sich trotzdem anpassen. Qualität, Bild und Geschwindigkeit gelten dann nicht.</p>' : `<div class="cv-row"><label>Bit-Tiefe ${reset(x, 'video.bits')}</label>${seg('video.bits', [[8, '8 Bit', 'läuft überall'], [10, '10 Bit', 'weniger Banding, etwas kleiner']], v.bits, ten ? {10: 'h264 kennt hier nur 8 Bit'} : {})}</div>`}`;
}

function qualityBlock(x, probe){
  const {cfg} = x, q = cfg.quality, v = cfg.video, l = levelOf(v.codec, q.crf), bl = x.base ? levelOf(x.base.video.codec, x.base.quality.crf) : null;
  const ticks = [[0, 'sehr klein'], [14, 'klein'], [38, 'ausgewogen'], [64, 'hoch'], [88, 'optisch verlustfrei']];
  const mode = `<div class="cv-row"><label>Wie soll die Qualität bestimmt werden?</label>${seg('quality.mode', [['crf', 'Qualität', 'empfohlen'], ['size', 'Zielgröße', 'ca. 2-Pass'], ['bitrate', 'Bitrate', 'ca. 2-Pass']], q.mode)}</div>`;
  if(q.mode === 'size') return mode + `<div class="cv-row"><label for="cv-size">Zielgröße je Datei (GB)</label><input class="input" id="cv-size" type="number" min="0.1" step="0.1" value="${q.size_gb || ''}" data-num="quality.size_gb" style="max-width:160px"><span class="hint">${SIZE_NOTE}</span></div>`;
  if(q.mode === 'bitrate') return mode + `<div class="cv-row"><label for="cv-kbps">Video-Bitrate (kb/s)</label><input class="input" id="cv-kbps" type="number" min="100" step="100" value="${q.kbps || ''}" data-num="quality.kbps" style="max-width:160px"><span class="hint">${SIZE_NOTE}</span></div>`;
  return mode + `<div class="cv-q"><div class="cv-qhead"><span class="val"><span data-b="crf">${esc(unitOf(cfg))} ${q.crf}</span><small>${esc(v.codec === 'hw' ? v.hw : v.codec)}</small></span><span class="word" data-b="qword">${esc(qWord(l))}</span>
    <span style="flex:1"></span><span class="muted" style="font-size:12px">≈ <b data-b="out" style="color:var(--text)">…</b> ${probe ? 'für diese Datei' : 'für einen 24-GB-Film'}</span></div>
    <input class="cv-range" type="range" min="0" max="100" step="1" value="${Math.round(l)}" data-q aria-label="Qualität: kleiner bis besser"><div class="cv-band"></div>
    <div class="cv-scale">${ticks.map(([t, w]) => `<span class="${t === 88 ? 'lossless' : ''}" style="left:${Math.min(Math.max(t, 4), 92)}%">${w}</span>`).join('')}${bl != null && chg(x, 'quality.crf') ? `<span class="here" style="left:${Math.max(3, Math.min(97, bl))}%;top:20px">▲ Preset</span>` : ''}</div>
    <div class="cv-ends"><span>← kleinere Datei</span><span>bessere Qualität →</span></div></div>`;
}

function speedBlock(x, meta){
  const v = x.cfg.video, sp = meta.codecs[v.codec].speeds, i = Math.max(0, sp.indexOf(v.speed));
  if(v.codec === 'hw' || v.codec === 'copy') return `<p class="hint">${v.codec === 'hw' ? 'Hardware-Encoder haben keine Stufen.' : 'Beim Remuxen gibt es keine Stufen.'}</p>`;
  return `<div class="cv-q"><div class="cv-qhead"><span class="val" style="font-size:18px">${esc(v.speed)}</span><span class="word" style="color:var(--blue)" data-b="dur"></span></div>
    <input class="cv-range" type="range" min="0" max="${sp.length - 1}" value="${i}" data-sp aria-label="Geschwindigkeit"><div class="cv-ends"><span>← schneller</span><span>kleiner bei gleicher Qualität →</span></div>
    <p class="hint">Jede Stufe langsamer spart etwa 3–6 % Platz bei gleicher Qualität, dauert aber etwa doppelt so lang.${v.codec === 'svtav1' ? ' (SVT-AV1: 13 = schnell … 0 = langsam)' : ''}</p></div>`;
}

function pictureBlock(x){
  const p = x.cfg.picture, caps = x.caps, no = f => (caps && caps.filters && !caps.filters.includes(f) ? 'Dem Rechner fehlt der Filter ' + f : '');
  const dd = {}; if(no('bwdif')) { dd.auto = no('bwdif'); dd.on = no('bwdif'); } if(no('fieldmatch')) dd.ivtc = no('fieldmatch');
  const hd = no('zscale') ? {tonemap: no('zscale')} : {};
  return `<div class="cv-2"><div class="cv-row"><label>Auflösung ${reset(x, 'picture.scale')}</label>${seg('picture.scale', [['keep', 'beibehalten'], ['1080', '≤ 1080p'], ['720', '≤ 720p'], ['576', '≤ 576p'], ['480', '≤ 480p']], p.scale)}<span class="hint">Es wird nie hochskaliert.</span></div>
    <div class="cv-row"><label>Zuschneiden ${reset(x, 'picture.crop')}</label>${seg('picture.crop', [['auto', 'automatisch'], ['off', 'aus'], ['manual', 'manuell']], p.crop)}
      ${p.crop === 'manual' ? `<input class="input" data-text="picture.crop_manual" value="${esc(p.crop_manual)}" placeholder="Breite:Höhe:x:y, z. B. 1920:800:0:140" aria-label="Zuschnitt manuell" style="max-width:300px">` : ''}</div>
    <div class="cv-row"><label>Zeilensprung (Deinterlace) ${reset(x, 'picture.deint')}</label>${seg('picture.deint', [['auto', 'automatisch'], ['off', 'aus'], ['on', 'immer'], ['ivtc', 'Telecine (IVTC)']], p.deint, dd)}</div>
    <div class="cv-row"><label>Entrauschen ${reset(x, 'picture.denoise')}</label>${seg('picture.denoise', [['off', 'aus'], ['light', 'leicht'], ['medium', 'mittel']], p.denoise, no('hqdn3d') ? {light: no('hqdn3d'), medium: no('hqdn3d')} : {})}</div>
    <div class="cv-row"><label>HDR ${reset(x, 'picture.hdr')}</label>${seg('picture.hdr', [['keep', 'erhalten'], ['tonemap', 'nach SDR umrechnen']], p.hdr, hd)}<span class="hint">HDR10 bleibt bei x265 und Hardware-HEVC erhalten. Dolby Vision geht verloren (die HDR10-Basis bleibt).</span></div></div>`;
}

const KBPS = [0, 96, 128, 160, 192, 256, 320, 384, 448, 640];
function soundBlock(x){
  const a = x.cfg.sound;
  return `<div class="cv-2"><div class="cv-row"><label>Ton ${reset(x, 'sound.mode')}</label>${seg('sound.mode', [['copy', 'kopieren'], ['aac', 'AAC'], ['opus', 'Opus'], ['ac3', 'AC3'], ['eac3', 'E-AC3']], a.mode)}</div>
    <div class="cv-row"><label>Kanäle ${reset(x, 'sound.channels')}</label>${seg('sound.channels', [['keep', 'wie Quelle'], ['51', 'höchstens 5.1'], ['stereo', 'Stereo-Downmix']], a.channels, a.mode === 'copy' ? {51: 'beim Kopieren nicht änderbar', stereo: 'beim Kopieren nicht änderbar'} : {})}</div>
    ${a.mode === 'copy' ? '' : `<div class="cv-row"><label for="cv-kb">Bitrate je Spur</label><select class="input" id="cv-kb" data-numsel="sound.kbps" style="max-width:200px">${KBPS.map(k => `<option value="${k}" ${k === a.kbps ? 'selected' : ''}>${k ? k + ' kb/s' : 'automatisch'}</option>`).join('')}</select></div>`}</div>
    <p class="hint">Gilt für jede Tonspur. Welche Sprachen schon beim Rippen behalten werden, steht unter Einstellungen → Allgemein.${a.mode === 'copy' ? ' Beim Kopieren bleiben DTS-HD und TrueHD unverändert (groß).' : ''}</p>`;
}

function subsBlock(x){
  const s = x.cfg.subs;
  return `<div class="cv-row"><label>Untertitel ${reset(x, 'subs.mode')}</label>${seg('subs.mode', [['all', 'alle behalten'], ['forced', 'nur erzwungene'], ['langs', 'nur Sprachen …'], ['none', 'keine']], s.mode)}
    ${s.mode === 'langs' ? `<input class="input" data-text="subs.langs" value="${esc(s.langs)}" placeholder="3-Buchstaben-Codes, z. B. deu,eng" aria-label="Untertitel-Sprachen" style="max-width:260px"><span class="hint">Spuren ohne Sprachangabe bleiben erhalten.</span>` : ''}</div>`;
}

function expertBlock(x){
  const v = x.cfg.video, enc = {x265: 'x265-params', x264: 'x264-params', svtav1: 'svtav1-params'}[v.codec];
  return `${enc ? `<div class="cv-row"><label for="cv-extra">Freie Encoder-Parameter (${enc}) ${reset(x, 'video.extra')}</label><input class="input" id="cv-extra" data-text="video.extra" value="${esc(v.extra)}" placeholder="z. B. aq-mode=3:no-sao=1" spellcheck="false">
    <span class="hint">Nur Buchstaben, Ziffern und = : . , - _. Falsche Parameter lassen die Konvertierung fehlschlagen (das Original bleibt dann unverändert).</span></div>` : '<p class="hint">Für diesen Codec gibt es keine freien Parameter.</p>'}
  <div class="cv-row"><label>Erzeugter ffmpeg-Befehl (nur zum Lesen; Zuschnitt und Zeilensprung werden erst beim Konvertieren erkannt)</label><pre class="cv-cmp-cmd cv-cmd" data-b="cmd">…</pre></div>`;
}

export function sections(x, meta, probe){
  const q = x.cfg.quality, v = x.cfg.video, p = x.cfg.picture, a = x.cfg.sound, s = x.cfg.subs;
  const copy = v.codec === 'copy';
  return [
    ['video', '▣', 'Video', `${meta.codecs[v.codec].label.replace(/ \(.*/, '')}${copy ? '' : ' · ' + v.bits + ' Bit'}`, ['video.codec', 'video.bits', 'video.hw'], () => videoBlock(x)],
    ...(copy ? [] : [
      ['quality', '◐', 'Qualität', q.mode === 'crf' ? `${unitOf(x.cfg)} ${q.crf} · ${qWord(levelOf(v.codec, q.crf))}` : q.mode === 'size' ? `Zielgröße ${q.size_gb} GB` : `${q.kbps} kb/s`, ['quality.crf', 'quality.mode', 'quality.size_gb', 'quality.kbps'], () => qualityBlock(x, probe)],
      ['speed', '⏱', 'Geschwindigkeit', v.codec === 'hw' ? 'Hardware' : v.speed, ['video.speed'], () => speedBlock(x, meta)],
      ['pic', '▭', 'Bild', `${p.scale === 'keep' ? 'Auflösung bleibt' : '≤ ' + p.scale + 'p'} · Deinterlace ${({auto: 'auto', off: 'aus', on: 'an', ivtc: 'IVTC'})[p.deint]}${p.denoise !== 'off' ? ' · Entrauschen ' + ({light: 'leicht', medium: 'mittel'})[p.denoise] : ''}${p.hdr === 'tonemap' ? ' · HDR→SDR' : ''}`, ['picture.scale', 'picture.crop', 'picture.deint', 'picture.denoise', 'picture.hdr'], () => pictureBlock(x)],
    ]),
    ['audio', '♪', 'Ton', a.mode === 'copy' ? 'kopieren' : `${a.mode.toUpperCase()}${a.channels === 'stereo' ? ' Stereo' : ''}${a.kbps ? ' · ' + a.kbps + ' kb/s' : ''}`, ['sound.mode', 'sound.channels'], () => soundBlock(x)],
    ['subs', '☰', 'Untertitel', ({all: 'alle behalten', forced: 'nur erzwungene', langs: 'nur ' + s.langs, none: 'keine'})[s.mode], ['subs.mode', 'subs.langs'], () => subsBlock(x)],
    ['expert', '⌘', 'Experten', v.extra || 'keine freien Parameter', ['video.extra'], () => expertBlock(x)],
  ];
}

export function accordion(x, meta, open, probe){
  return `<div class="cv-acc">${sections(x, meta, probe).map(([id, ic, t, sm, ps, body]) => `<div class="cv-sec ${open.has(id) ? 'open' : ''}" data-sec="${id}">
    <header data-toggle="${id}" tabindex="0" role="button" aria-expanded="${open.has(id)}"><span class="mini-icon">${ic}</span><strong>${t}</strong>${dot(x, ...ps)}<span class="sm">${esc(sm)}</span><span class="chev">⌄</span></header>
    <div>${open.has(id) ? body() : ''}</div></div>`).join('')}</div>`;
}
export { crfOf };
