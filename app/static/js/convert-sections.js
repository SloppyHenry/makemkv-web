// Conversion editor: the sections of the adjust view (video, quality, speed, picture, audio, subtitles, expert). Owner: PF.
import { esc } from './core.js';
import { crfOf, diffPaths, hasCodec, levelOf, qWord, unitOf } from './convert-meta.js';

const SIZE_NOTE = 'x265/x264 encode in two passes for this (takes about twice as long); SVT-AV1 and hardware in one pass with a target bitrate.';

export const seg = (path, opts, cur, dis = {}) => `<div class="cv-seg" role="radiogroup">${opts.map(([v, l, s]) =>
  `<button type="button" class="${String(cur) === String(v) ? 'on' : ''}" role="radio" aria-checked="${String(cur) === String(v)}" data-set="${path}" data-v="${esc(v)}" ${dis[v] ? `disabled title="${esc(dis[v])}"` : ''}>${esc(l)}${s ? `<small>${esc(s)}</small>` : ''}</button>`).join('')}</div>`;

export function ctx(cfg, base, caps){ return {cfg, base, caps, ch: new Set(diffPaths(cfg, base))}; }
const chg = (x, ...ps) => ps.some(p => x.ch.has(p));
const dot = (x, ...ps) => chg(x, ...ps) ? '<span class="dot" title="changed compared to the preset"></span>' : '';
const reset = (x, ...ps) => chg(x, ...ps) ? `<button type="button" class="cv-link" data-reset="${ps.join(',')}">back to preset</button>` : '';

function videoBlock(x){
  const {cfg, caps} = x, v = cfg.video, hw = caps && caps.hw ? caps.hw : [];
  const no = c => (hasCodec(caps, c) ? '' : caps ? 'This machine does not report it' : 'Older version: only x265 with the previous options');
  const dis = {}; ['x264', 'svtav1', 'hw'].forEach(c => { if(no(c)) dis[c] = no(c); });
  const hwSel = v.codec === 'hw' ? `<div class="cv-row"><label for="cv-hw">Hardware encoder</label><select class="input" id="cv-hw" data-set="video.hw" style="max-width:260px">${hw.map(e => `<option ${e === v.hw ? 'selected' : ''}>${esc(e)}</option>`).join('')}</select>
    <span class="hint">Hardware encoders are very fast, but visibly worse than software at the same size. Segment mode is off for them.</span></div>` : '';
  const ten = v.hw.startsWith('h264_');
  return `<div class="cv-row"><label>Codec ${reset(x, 'video.codec')}</label>${seg('video.codec', [['x265', 'H.265 / HEVC', 'x265'], ['x264', 'H.264', 'x264'], ['svtav1', 'AV1', 'SVT-AV1'], ['hw', 'Hardware', hw.length ? 'VAAPI/QSV …' : 'not available'], ['copy', 'Remux only', 'no re-encoding']], v.codec, dis)}</div>${hwSel}
  ${v.codec === 'copy' ? '<p class="hint">The picture stays unchanged; audio, subtitles and chapters can still be adjusted. Quality, picture and speed do not apply then.</p>' : `<div class="cv-row"><label>Bit depth ${reset(x, 'video.bits')}</label>${seg('video.bits', [[8, '8 bit', 'plays everywhere'], [10, '10 bit', 'less banding, a bit smaller']], v.bits, ten ? {10: 'h264 only supports 8 bit here'} : {})}</div>`}`;
}

function qualityBlock(x, probe){
  const {cfg} = x, q = cfg.quality, v = cfg.video, l = levelOf(v.codec, q.crf), bl = x.base ? levelOf(x.base.video.codec, x.base.quality.crf) : null;
  const ticks = [[0, 'very small'], [14, 'small'], [38, 'balanced'], [64, 'high'], [88, 'visually lossless']];
  const mode = `<div class="cv-row"><label>How should the quality be determined?</label>${seg('quality.mode', [['crf', 'Quality', 'recommended'], ['size', 'Target size', 'approx. 2-pass'], ['bitrate', 'Bitrate', 'approx. 2-pass']], q.mode)}</div>`;
  if(q.mode === 'size') return mode + `<div class="cv-row"><label for="cv-size">Target size per file (GB)</label><input class="input" id="cv-size" type="number" min="0.1" step="0.1" value="${q.size_gb || ''}" data-num="quality.size_gb" style="max-width:160px"><span class="hint">${SIZE_NOTE}</span></div>`;
  if(q.mode === 'bitrate') return mode + `<div class="cv-row"><label for="cv-kbps">Video bitrate (kb/s)</label><input class="input" id="cv-kbps" type="number" min="100" step="100" value="${q.kbps || ''}" data-num="quality.kbps" style="max-width:160px"><span class="hint">${SIZE_NOTE}</span></div>`;
  return mode + `<div class="cv-q"><div class="cv-qhead"><span class="val"><span data-b="crf">${esc(unitOf(cfg))} ${q.crf}</span><small>${esc(v.codec === 'hw' ? v.hw : v.codec)}</small></span><span class="word" data-b="qword">${esc(qWord(l))}</span>
    <span style="flex:1"></span><span class="muted" style="font-size:12px">≈ <b data-b="out" style="color:var(--text)">…</b> ${probe ? 'for this file' : 'for a 24 GB movie'}</span></div>
    <input class="cv-range" type="range" min="0" max="100" step="1" value="${Math.round(l)}" data-q aria-label="Quality: smaller to better"><div class="cv-band"></div>
    <div class="cv-scale">${ticks.map(([t, w]) => `<span class="${t === 88 ? 'lossless' : ''}" style="left:${Math.min(Math.max(t, 4), 92)}%">${w}</span>`).join('')}${bl != null && chg(x, 'quality.crf') ? `<span class="here" style="left:${Math.max(3, Math.min(97, bl))}%;top:20px">▲ Preset</span>` : ''}</div>
    <div class="cv-ends"><span>← smaller file</span><span>better quality →</span></div></div>`;
}

function speedBlock(x, meta){
  const v = x.cfg.video, sp = meta.codecs[v.codec].speeds, i = Math.max(0, sp.indexOf(v.speed));
  if(v.codec === 'hw' || v.codec === 'copy') return `<p class="hint">${v.codec === 'hw' ? 'Hardware encoders have no levels.' : 'There are no levels when remuxing.'}</p>`;
  return `<div class="cv-q"><div class="cv-qhead"><span class="val" style="font-size:18px">${esc(v.speed)}</span><span class="word" style="color:var(--blue)" data-b="dur"></span></div>
    <input class="cv-range" type="range" min="0" max="${sp.length - 1}" value="${i}" data-sp aria-label="Speed"><div class="cv-ends"><span>← faster</span><span>smaller at the same quality →</span></div>
    <p class="hint">Each slower level saves about 3–6 % of space at the same quality, but takes about twice as long.${v.codec === 'svtav1' ? ' (SVT-AV1: 13 = fast … 0 = slow)' : ''}</p></div>`;
}

function pictureBlock(x){
  const p = x.cfg.picture, caps = x.caps, no = f => (caps && caps.filters && !caps.filters.includes(f) ? 'The machine lacks the filter ' + f : '');
  const dd = {}; if(no('bwdif')) { dd.auto = no('bwdif'); dd.on = no('bwdif'); } if(no('fieldmatch')) dd.ivtc = no('fieldmatch');
  const hd = no('zscale') ? {tonemap: no('zscale')} : {};
  return `<div class="cv-2"><div class="cv-row"><label>Resolution ${reset(x, 'picture.scale')}</label>${seg('picture.scale', [['keep', 'keep'], ['1080', '≤ 1080p'], ['720', '≤ 720p'], ['576', '≤ 576p'], ['480', '≤ 480p']], p.scale)}<span class="hint">Never upscaled.</span></div>
    <div class="cv-row"><label>Crop ${reset(x, 'picture.crop')}</label>${seg('picture.crop', [['auto', 'automatic'], ['off', 'off'], ['manual', 'manual']], p.crop)}
      ${p.crop === 'manual' ? `<input class="input" data-text="picture.crop_manual" value="${esc(p.crop_manual)}" placeholder="width:height:x:y, e.g. 1920:800:0:140" aria-label="Manual crop" style="max-width:300px">` : ''}</div>
    <div class="cv-row"><label>Interlacing (deinterlace) ${reset(x, 'picture.deint')}</label>${seg('picture.deint', [['auto', 'automatic'], ['off', 'off'], ['on', 'always'], ['ivtc', 'Telecine (IVTC)']], p.deint, dd)}</div>
    <div class="cv-row"><label>Denoise ${reset(x, 'picture.denoise')}</label>${seg('picture.denoise', [['off', 'off'], ['light', 'light'], ['medium', 'medium']], p.denoise, no('hqdn3d') ? {light: no('hqdn3d'), medium: no('hqdn3d')} : {})}</div>
    <div class="cv-row"><label>HDR ${reset(x, 'picture.hdr')}</label>${seg('picture.hdr', [['keep', 'keep'], ['tonemap', 'convert to SDR']], p.hdr, hd)}<span class="hint">HDR10 is kept with x265 and hardware HEVC. Dolby Vision is lost (the HDR10 base stays).</span></div></div>`;
}

const KBPS = [0, 96, 128, 160, 192, 256, 320, 384, 448, 640];
function soundBlock(x){
  const a = x.cfg.sound;
  return `<div class="cv-2"><div class="cv-row"><label>Audio ${reset(x, 'sound.mode')}</label>${seg('sound.mode', [['copy', 'copy'], ['aac', 'AAC'], ['opus', 'Opus'], ['ac3', 'AC3'], ['eac3', 'E-AC3']], a.mode)}</div>
    <div class="cv-row"><label>Channels ${reset(x, 'sound.channels')}</label>${seg('sound.channels', [['keep', 'as source'], ['51', 'at most 5.1'], ['stereo', 'stereo downmix']], a.channels, a.mode === 'copy' ? {51: 'cannot be changed when copying', stereo: 'cannot be changed when copying'} : {})}</div>
    ${a.mode === 'copy' ? '' : `<div class="cv-row"><label for="cv-kb">Bitrate per track</label><select class="input" id="cv-kb" data-numsel="sound.kbps" style="max-width:200px">${KBPS.map(k => `<option value="${k}" ${k === a.kbps ? 'selected' : ''}>${k ? k + ' kb/s' : 'automatic'}</option>`).join('')}</select></div>`}</div>
    <p class="hint">Applies to every audio track. Which languages are already kept when ripping is set under Settings → General.${a.mode === 'copy' ? ' When copying, DTS-HD and TrueHD stay unchanged (large).' : ''}</p>`;
}

function subsBlock(x){
  const s = x.cfg.subs;
  return `<div class="cv-row"><label>Subtitles ${reset(x, 'subs.mode')}</label>${seg('subs.mode', [['all', 'keep all'], ['forced', 'forced only'], ['langs', 'only languages …'], ['none', 'none']], s.mode)}
    ${s.mode === 'langs' ? `<input class="input" data-text="subs.langs" value="${esc(s.langs)}" placeholder="three-letter codes, e.g. eng,deu" aria-label="Subtitle languages" style="max-width:260px"><span class="hint">Tracks without a language are kept.</span>` : ''}</div>`;
}

function expertBlock(x){
  const v = x.cfg.video, nv = v.codec === 'hw' && (v.hw || '').endsWith('_nvenc'), enc = nv ? 'NVENC options' : {x265: 'x265-params', x264: 'x264-params', svtav1: 'svtav1-params'}[v.codec];
  return `${enc ? `<div class="cv-row"><label for="cv-extra">Free encoder parameters (${enc}) ${reset(x, 'video.extra')}</label><input class="input" id="cv-extra" data-text="video.extra" value="${esc(v.extra)}" placeholder="${nv ? 'e.g. preset=p7:tune=hq:bf=4' : 'e.g. aq-mode=3:no-sao=1'}" spellcheck="false">
    <span class="hint">Only letters, digits and = : . , - _. Wrong parameters make the conversion fail (the original then stays unchanged).</span></div>` : '<p class="hint">There are no free parameters for this codec.</p>'}
  <div class="cv-row"><label>Generated ffmpeg command (read only; crop and interlacing are only detected when converting)</label><pre class="cv-cmp-cmd cv-cmd" data-b="cmd">…</pre></div>`;
}

export function sections(x, meta, probe){
  const q = x.cfg.quality, v = x.cfg.video, p = x.cfg.picture, a = x.cfg.sound, s = x.cfg.subs;
  const copy = v.codec === 'copy';
  return [
    ['video', '▣', 'Video', `${meta.codecs[v.codec].label.replace(/ \(.*/, '')}${copy ? '' : ' · ' + v.bits + ' bit'}`, ['video.codec', 'video.bits', 'video.hw'], () => videoBlock(x)],
    ...(copy ? [] : [
      ['quality', '◐', 'Quality', q.mode === 'crf' ? `${unitOf(x.cfg)} ${q.crf} · ${qWord(levelOf(v.codec, q.crf))}` : q.mode === 'size' ? `Target size ${q.size_gb} GB` : `${q.kbps} kb/s`, ['quality.crf', 'quality.mode', 'quality.size_gb', 'quality.kbps'], () => qualityBlock(x, probe)],
      ['speed', '⏱', 'Speed', v.codec === 'hw' ? 'Hardware' : v.speed, ['video.speed'], () => speedBlock(x, meta)],
      ['pic', '▭', 'Picture', `${p.scale === 'keep' ? 'Resolution kept' : '≤ ' + p.scale + 'p'} · deinterlace ${({auto: 'auto', off: 'off', on: 'on', ivtc: 'IVTC'})[p.deint]}${p.denoise !== 'off' ? ' · denoise ' + ({light: 'light', medium: 'medium'})[p.denoise] : ''}${p.hdr === 'tonemap' ? ' · HDR→SDR' : ''}`, ['picture.scale', 'picture.crop', 'picture.deint', 'picture.denoise', 'picture.hdr'], () => pictureBlock(x)],
    ]),
    ['audio', '♪', 'Audio', a.mode === 'copy' ? 'copy' : `${a.mode.toUpperCase()}${a.channels === 'stereo' ? ' stereo' : ''}${a.kbps ? ' · ' + a.kbps + ' kb/s' : ''}`, ['sound.mode', 'sound.channels'], () => soundBlock(x)],
    ['subs', '☰', 'Subtitles', ({all: 'keep all', forced: 'forced only', langs: 'only ' + s.langs, none: 'none'})[s.mode], ['subs.mode', 'subs.langs'], () => subsBlock(x)],
    ['expert', '⌘', 'Expert', v.extra || 'no free parameters', ['video.extra'], () => expertBlock(x)],
  ];
}

export function accordion(x, meta, open, probe){
  return `<div class="cv-acc">${sections(x, meta, probe).map(([id, ic, t, sm, ps, body]) => `<div class="cv-sec ${open.has(id) ? 'open' : ''}" data-sec="${id}">
    <header data-toggle="${id}" tabindex="0" role="button" aria-expanded="${open.has(id)}"><span class="mini-icon">${ic}</span><strong>${t}</strong>${dot(x, ...ps)}<span class="sm">${esc(sm)}</span><span class="chev">⌄</span></header>
    <div>${open.has(id) ? body() : ''}</div></div>`).join('')}</div>`;
}
export { crfOf };
