// Player: Markup (1:1 nach docs/mockups/paket-d.html), Symbole und Menüs. Reine Darstellung ohne Zustand.
import { esc, fmtB, fmtD } from './core.js';

const SPRITE = `<svg class="player-icons" aria-hidden="true">
<symbol id="pi-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/></symbol>
<symbol id="pi-pause" viewBox="0 0 24 24"><path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor" stroke="none"/></symbol>
<symbol id="pi-back" viewBox="0 0 24 24"><path d="M5 12a7 7 0 1 0 2.2-5.1"/><path d="M4 4v4.5h4.5"/><text x="12" y="15.5" font-size="7.5" text-anchor="middle" fill="currentColor" stroke="none" font-weight="700" font-family="Inter,sans-serif">10</text></symbol>
<symbol id="pi-fwd" viewBox="0 0 24 24"><path d="M19 12a7 7 0 1 1-2.2-5.1"/><path d="M20 4v4.5h-4.5"/><text x="12" y="15.5" font-size="7.5" text-anchor="middle" fill="currentColor" stroke="none" font-weight="700" font-family="Inter,sans-serif">10</text></symbol>
<symbol id="pi-vol" viewBox="0 0 24 24"><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" fill="currentColor"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/></symbol>
<symbol id="pi-mute" viewBox="0 0 24 24"><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" fill="currentColor"/><path d="M16 9.5l5 5M21 9.5l-5 5"/></symbol>
<symbol id="pi-cc" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.5 10.2a2.2 2.2 0 1 0 0 3.6M16.5 10.2a2.2 2.2 0 1 0 0 3.6"/></symbol>
<symbol id="pi-list" viewBox="0 0 24 24"><path d="M4 6h2M9 6h11M4 12h2M9 12h11M4 18h2M9 18h11"/></symbol>
<symbol id="pi-gear" viewBox="0 0 24 24"><path d="M4 7h9M19 7h1M4 17h1M11 17h9"/><circle cx="16" cy="7" r="2.5"/><circle cx="8" cy="17" r="2.5"/></symbol>
<symbol id="pi-full" viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></symbol>
<symbol id="pi-unfull" viewBox="0 0 24 24"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></symbol>
<symbol id="pi-close" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="pi-out" viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></symbol>
<symbol id="pi-keys" viewBox="0 0 24 24"><rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/></symbol>
<symbol id="pi-warn" viewBox="0 0 24 24"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></symbol>
<symbol id="pi-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></symbol></svg>`;
export const injectSprite = () => { if(!document.querySelector('.player-icons')) document.body.insertAdjacentHTML('beforeend', SPRITE); };
export const ic = (n, c = '') => `<svg class="${c}" aria-hidden="true"><use href="#pi-${n}"/></svg>`;
export const fmtT = s => fmtD(Math.max(0, s));

const VC = {h264: 'H.264', hevc: 'HEVC', mpeg2video: 'MPEG-2', vc1: 'VC-1', mpeg4: 'MPEG-4', vp9: 'VP9', av1: 'AV1', wmv3: 'WMV'};
const AC = {ac3: 'AC3', eac3: 'E-AC3', dts: 'DTS', truehd: 'TrueHD', aac: 'AAC', mp3: 'MP3', flac: 'FLAC', opus: 'Opus', vorbis: 'Vorbis', pcm_s16le: 'PCM', pcm_dvd: 'PCM'};
const LANG = {deu: 'Deutsch', ger: 'Deutsch', eng: 'English', fra: 'Français', fre: 'Français', spa: 'Español', ita: 'Italiano', nld: 'Nederlands', por: 'Português', rus: 'Русский',
              jpn: '日本語', zho: '中文', kor: '한국어', pol: 'Polski', tur: 'Türkçe', swe: 'Svenska', dan: 'Dansk', nor: 'Norsk', fin: 'Suomi', ces: 'Čeština', hun: 'Magyar', ell: 'Ελληνικά'};
export const langName = l => LANG[(l || '').toLowerCase()] || (l && l !== 'und' ? l : '');
const layout = a => a.channels === 1 ? '1.0' : a.channels === 2 ? '2.0' : a.channels === 6 ? '5.1' : a.channels === 8 ? '7.1' : a.channels ? `${a.channels} Kanäle` : '';
export const audioName = a => {
  const c = a.codec === 'dts' && /MA/.test(a.profile || '') ? 'DTS-HD MA' : a.codec === 'truehd' ? 'TrueHD' : AC[a.codec] || a.codec.toUpperCase();
  return `${langName(a.lang) || 'Tonspur ' + (a.i + 1)}${a.title ? ' – ' + a.title : ''} – ${c} ${layout(a)}`.trim();
};
export const subName = s => `${langName(s.lang) || 'Untertitel ' + (s.i + 1)}${s.forced ? ' – erzwungen' : ''}${s.title ? ' – ' + s.title : ''}`;
export const metaLine = (info, dir) => [dir, fmtT(info.duration), fmtB(info.size), info.video ? `${VC[info.video.codec] || info.video.codec} ${info.video.h ? info.video.h + 'p' : ''}${info.video.hdr ? ' HDR' : ''}` : '',
  info.audio[0] ? audioName(info.audio[Math.max(0, info.preferred.audio ?? 0)] || info.audio[0]).split(' – ').slice(1).join(' ') : ''].filter(Boolean).join(' · ');

export const MODE_PILL = {direct: '<span class="st ok">Direkt</span>', remux: '<span class="st">Remux</span>', transcode: '<span class="st warn">Transkodiert</span>'};

export function playerHtml(alone){
  return `<div class="player${alone ? ' alone' : ''}" data-state="loading" tabindex="-1">
  <div class="player-notes"></div>
  <div class="player-stage"><video class="player-video" playsinline preload="auto"></video><div class="player-subs"></div>
    <div class="player-center"><button type="button" class="player-bigplay" aria-label="Wiedergabe" data-a="toggle">${ic('play')}</button>
      <div class="player-wait"><div class="player-spin"></div><span class="player-waittext">Starte …</span></div><div class="player-fail"></div></div></div>
  <div class="player-controls">
    <div class="player-seek" role="slider" aria-label="Position" tabindex="0" aria-valuemin="0"><div class="player-track" style="--p:0;--b:0"><div class="player-buf"></div><div class="player-played"></div><div class="player-ticks"></div><div class="player-thumb"></div></div><div class="player-tip" style="--x:0"></div></div>
    <div class="player-row">
      <button type="button" class="player-btn" data-a="toggle" aria-label="Wiedergabe">${ic('play')}</button>
      <button type="button" class="player-btn player-skip" data-a="back" aria-label="10 Sekunden zurück">${ic('back')}</button><button type="button" class="player-btn player-skip" data-a="fwd" aria-label="10 Sekunden vor">${ic('fwd')}</button>
      <span class="player-vol"><button type="button" class="player-btn" data-a="mute" aria-label="Ton aus">${ic('vol')}</button><input type="range" min="0" max="100" value="100" aria-label="Lautstärke"></span>
      <span class="player-time"><b>0:00</b> / 0:00</span><span class="spacer"></span>
      <button type="button" class="player-btn" data-a="m:chapters" aria-label="Kapitel" hidden>${ic('list')}</button>
      <button type="button" class="player-btn" data-a="m:tracks" aria-label="Ton und Untertitel">${ic('cc')}</button>
      <button type="button" class="player-btn" data-a="m:mode" aria-label="Geschwindigkeit und Info">${ic('gear')}</button>
      ${alone ? `<button type="button" class="player-btn player-out" data-a="overlay" aria-label="In Überlagerung öffnen" title="In Überlagerung öffnen">${ic('out')}</button>` : ''}
      <button type="button" class="player-btn" data-a="full" aria-label="Vollbild">${ic('full')}</button>
    </div>
  </div></div>`;
}

export const windowHtml = () => `<div class="player-overlay"><div class="player-window nochapters" role="dialog" aria-modal="true" aria-label="Player" tabindex="-1">
  <div class="player-head"><div class="titles"><h3></h3><span class="sub"></span></div><span class="spacer"></span><span class="pillhost"></span>
    <button type="button" class="player-btn" data-a="m:keys" aria-label="Tastenkürzel" title="Tastenkürzel (?)">${ic('keys')}</button><button type="button" class="player-btn" data-a="close" aria-label="Schließen (Esc)" title="Schließen (Esc)">${ic('close')}</button></div>
  <div class="player-body">${playerHtml(false)}<aside class="player-chapters" aria-label="Kapitel" hidden></aside></div></div></div>`;

export const notesHtml = ns => ns.map(n => `<div class="player-note ${n.k || ''}" data-id="${n.id}">${ic(n.k === 'warn' || n.k === 'err' ? 'warn' : 'info')}<div class="grow">${n.t}</div><button type="button" class="x" data-a="note-x" aria-label="Schließen">×</button></div>`).join('');

export const chaptersHtml = (chs, cur, head = true) => (head ? `<h4>Kapitel · ${chs.length}</h4>` : '') + chs.map((c, i) =>
  `<button type="button" class="player-chap" data-a="chap:${i}" ${i === cur ? 'aria-current="true"' : ''}><time>${fmtT(c.start)}</time><span>${esc(c.title || 'Kapitel ' + (i + 1))}</span></button>`).join('');

const opt = (a, label, sub, o = {}) => `<button type="button" class="player-opt" role="menuitemradio" aria-checked="${!!o.on}" data-a="${a}" ${o.dis ? 'disabled' : ''}><span class="lbl">${esc(label)}${sub ? `<small>${esc(sub)}</small>` : ''}</span>${o.tag ? `<span class="st ${o.tagk || ''}">${o.tag}</span>` : ''}</button>`;

export function menuHtml(kind, e){
  const info = e.info;
  if(kind === 'tracks'){
    const cur = e.audioIndex();
    const conv = a => !(['aac', 'mp3'].includes(a.codec) || e.caps.has(a.codec));
    const aud = info.audio.map(a => opt('audio:' + a.i, audioName(a), conv(a) ? 'wird in AAC Stereo umgewandelt' : '', {on: a.i === cur, tag: conv(a) ? 'Remux' : ''})).join('');
    const subs = info.subs.map(s => s.supported ? opt('sub:' + s.i, subName(s), `${s.codec.toUpperCase()} · Text`, {on: e.sub === s.i}) : opt('x', subName(s), `${s.codec === 'hdmv_pgs_subtitle' ? 'PGS' : s.codec.toUpperCase()} · Bilduntertitel werden nicht unterstützt`, {dis: 1, tag: 'nicht unterstützt', tagk: 'warn'})).join('');
    return `<div class="player-menu" role="menu">${info.audio.length ? '<h4>Tonspur</h4>' + aud : ''}<h4>Untertitel</h4>${opt('sub:-1', 'Aus', '', {on: e.sub < 0})}${subs}</div>`;
  }
  if(kind === 'mode'){
    const p = e.plan || info.plan;
    const how = {direct: ['Direkt', 'Die Originaldatei wird unverändert abgespielt.'], remux: ['Remux', 'Video unverändert, ' + (p.reasons.filter(r => r.startsWith('Ton')).join(' ') || 'Container neu verpackt') + ' Ein Sprung außerhalb des Gepufferten startet kurz neu.'],
      transcode: ['Transkodiert', 'Das Video wird in H.264 umgewandelt, weil der Browser das Original nicht kann. ' + (info.busy.busy ? 'Läuft gerade Arbeit: niedrigste Priorität, Wiedergabe kann ruckeln.' : '')]}[p.mode];
    return `<div class="player-menu" role="menu"><h4>Geschwindigkeit</h4>${[0.75, 1, 1.25, 1.5, 2].map(v => opt('speed:' + v, String(v).replace('.', ',') + '×', '', {on: e.speed === v})).join('')}<hr><h4>So wird abgespielt</h4><p class="help" style="margin:2px 10px 8px"><b style="color:var(--text)">${how[0]}</b> – ${esc(how[1])}</p></div>`;
  }
  if(kind === 'chapters') return `<div class="player-menu" role="menu">${chaptersHtml(info.chapters, e.chapterIndex())}</div>`;
  return `<div class="player-menu" role="menu"><h4>Tastenkürzel</h4><div class="player-keys"><kbd>Leertaste</kbd><span>Wiedergabe / Pause (auch K)</span><kbd>← →</kbd><span>10 s zurück / vor (mit Umschalt 60 s)</span><kbd>↑ ↓</kbd><span>Lautstärke</span><kbd>M</kbd><span>Ton aus</span><kbd>F</kbd><span>Vollbild (auch Doppelklick)</span><kbd>C</kbd><span>Untertitel an/aus</span><kbd>A</kbd><span>nächste Tonspur</span><kbd>B N</kbd><span>Kapitel zurück / vor</span><kbd>0–9</kbd><span>an 0–90 % springen</span><kbd>Esc</kbd><span>Schließen</span></div></div>`;
}
