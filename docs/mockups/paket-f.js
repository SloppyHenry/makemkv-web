// Mockup Paket F: Daten und kleine Interaktionen (nur zur Ansicht; Zahlen sind Beispiele, die echte App rechnet im Server).
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const GB = 1024 ** 3, dec = s => String(s).replace('.', ',');
const fmtG = b => dec((b / GB).toFixed(b / GB < 100 ? 1 : 0)) + ' GB';
const fmtT = s => { const h = Math.floor(s / 3600), m = Math.round(s % 3600 / 60); return h >= 24 ? `${Math.floor(h / 24)} T ${h % 24} Std.` : h ? `${h}:${String(m).padStart(2, '0')} Std.` : `${m} Min.`; };

// ---- Codecs: Qualitätsskala 0..100 ("kleiner" bis "besser") wird je Codec auf dessen CRF/QP-Bereich abgebildet
const CODECS = {
  x265: {name: 'H.265 / HEVC', enc: 'x265', worst: 30, best: 14, bpp: 1, speeds: ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'], rel: [.12, .2, .35, .5, .7, 1, 2.3, 5, 8], unit: 'RF'},
  x264: {name: 'H.264', enc: 'x264', worst: 28, best: 12, bpp: 1.55, speeds: ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'], rel: [.05, .08, .15, .25, .5, 1, 1.7, 3, 6], unit: 'CRF', fast: 3.5},
  av1: {name: 'AV1', enc: 'SVT-AV1', worst: 45, best: 18, bpp: .8, speeds: ['13', '12', '10', '8', '7', '6', '5', '4', '2'], rel: [.05, .08, .15, .3, .5, .8, 1.2, 2.2, 6], unit: 'CRF', fast: 1.1},
  hw: {name: 'Hardware (VAAPI)', enc: 'hevc_vaapi', worst: 34, best: 16, bpp: 1.7, speeds: ['—'], rel: [.03], unit: 'QP', fast: 14},
};
const lvl = (c, q) => (CODECS[c].worst - q) / (CODECS[c].worst - CODECS[c].best) * 100;
const crfOf = (c, l) => Math.round(CODECS[c].worst - (CODECS[c].worst - CODECS[c].best) * l / 100);
const QWORDS = [[80, 'optisch verlustfrei'], [56, 'hoch'], [33, 'ausgewogen'], [12, 'klein'], [0, 'sehr klein']];
const qword = l => QWORDS.find(([t]) => l >= t)[1];

const PRESETS = [
  {id: 'dvd', name: 'DVD optimal', ic: '◎', desc: 'Für DVD-Rips (SD): erkennt Zeilensprung selbst, entrauscht leicht, Ton bleibt.', std: 'DVD', cfg: {codec: 'x265', bits: 10, crf: 19, speed: 'slow', tune: 'none', scale: 'keep', deint: 'auto', denoise: 'light', hdr: 'keep', audio: 'copy', ch: 'keep', subs: 'all', extra: 'aq-mode=3:no-sao=1'}},
  {id: 'bluray', name: 'Blu-ray optimal', ic: '◉', desc: 'Der Standard für 1080p-Discs: sieht aus wie das Original, braucht etwa ein Drittel.', std: 'Blu-ray', cfg: {codec: 'x265', bits: 10, crf: 20, speed: 'slow', tune: 'none', scale: 'keep', deint: 'off', denoise: 'off', hdr: 'keep', audio: 'copy', ch: 'keep', subs: 'all', extra: 'aq-mode=3:no-sao=1'}},
  {id: 'anim', name: 'Blu-ray Animation', ic: '✦', desc: 'Zeichentrick und Anime: glatte Flächen brauchen weniger Bits.', cfg: {codec: 'x265', bits: 10, crf: 22, speed: 'slow', tune: 'animation', scale: 'keep', deint: 'off', denoise: 'off', hdr: 'keep', audio: 'copy', ch: 'keep', subs: 'all', extra: 'aq-mode=3:no-sao=1'}},
  {id: 'grain', name: 'Film mit starkem Korn', ic: '░', desc: 'Altes Filmmaterial: Korn bleibt erhalten, die Datei wird größer.', cfg: {codec: 'x265', bits: 10, crf: 19, speed: 'slow', tune: 'grain', scale: 'keep', deint: 'off', denoise: 'off', hdr: 'keep', audio: 'copy', ch: 'keep', subs: 'all', extra: ''}},
  {id: 'uhd', name: 'UHD / HDR erhalten', ic: '◆', desc: '4K-Discs: HDR10-Angaben werden durchgereicht, 10 Bit ist Pflicht.', cfg: {codec: 'x265', bits: 10, crf: 22, speed: 'slow', tune: 'none', scale: 'keep', deint: 'off', denoise: 'off', hdr: 'keep', audio: 'copy', ch: 'keep', subs: 'all', extra: 'aq-mode=3:no-sao=1'}},
  {id: 'small', name: 'Klein & schnell', ic: '▾', desc: 'Für unterwegs: höchstens 720p, schnell, Stereo-Ton (AAC).', cfg: {codec: 'x265', bits: 10, crf: 26, speed: 'faster', tune: 'none', scale: '720', deint: 'auto', denoise: 'off', hdr: 'keep', audio: 'aac', ch: 'stereo', subs: 'all', extra: ''}},
  {id: 'u1', name: 'Serien sparsam', ic: '✎', user: true, desc: 'Eigenes Preset: Serien-Discs, x265 mittel, Ton als Opus.', cfg: {codec: 'x265', bits: 10, crf: 23, speed: 'medium', tune: 'none', scale: 'keep', deint: 'auto', denoise: 'light', hdr: 'keep', audio: 'opus', ch: 'keep', subs: 'langs', extra: ''}},
];
let preset = 'bluray', cfg = {...PRESETS[1].cfg};
const base = () => PRESETS.find(p => p.id === preset).cfg;
const changed = k => String(cfg[k]) !== String(base()[k]);
const nChanged = () => Object.keys(cfg).filter(changed).length;

// ---- Beispieldatei für die Vorhersage
const SRC = {name: 'Dune (2021).mkv', size: 24.6 * GB, dur: 9300, w: 1920, h: 1080, fps: 23.976, audio: 4.1 * GB};
const NODES = [
  {n: 'maintux', info: '32 Threads', thr: 32, ok: true},
  {n: 'vierstein', info: '4 Kerne · VAAPI', thr: 4, ok: true, hw: true},
  {n: 'secondtux', info: 'älterer Stand', thr: 8, ok: false, why: 'versteht die neuen Einstellungen nicht'},
];
function estimate(c = cfg) {
  const cd = CODECS[c.codec], px = SRC.w * SRC.h * (c.scale === '720' ? (1280 * 720) / (1920 * 1080) : c.scale === '480' ? .27 : 1);
  const l = lvl(c.codec, c.crf), eq = CODECS.x265.worst - (CODECS.x265.worst - CODECS.x265.best) * l / 100;
  let bpp = .09 * cd.bpp * Math.pow(2, (20 - eq) / 6);
  bpp *= {grain: 1.35, animation: .8}[c.tune] || 1;
  bpp *= {light: .93, medium: .85}[c.denoise] || 1;
  const i = cd.speeds.indexOf(c.speed); bpp *= 1 - (i - 5) * .025;
  const vid = Math.min(px * SRC.fps * bpp * SRC.dur / 8, SRC.size * .75);
  const aud = c.audio === 'copy' ? SRC.audio : SRC.dur * (c.ch === 'stereo' ? 128e3 : 256e3) / 8;
  const out = vid + aud;
  const rel = cd.rel[Math.max(0, i)], pxr = px / (1920 * 1080);
  const secs = n => SRC.dur * SRC.fps / (Math.pow(n.thr, .95) * .95 * (c.codec === 'hw' ? 14 : cd.fast || 1) / rel / pxr);
  return {out, times: NODES.map(n => n.ok && (c.codec !== 'hw' || n.hw) ? secs(n) : 0)};
}

// ---- Teile des Editors
const seg = (key, opts, cur, dis = []) => `<div class="cv-seg" role="radiogroup">${opts.map(([v, l, s]) => `<button type="button" class="${String(cur) === String(v) ? 'on' : ''}" data-set="${key}" data-v="${v}" ${dis.includes(v) ? 'disabled title="Dieser Rechner meldet das nicht"' : ''}>${l}${s ? `<small>${s}</small>` : ''}</button>`).join('')}</div>`;
const dot = (...ks) => ks.some(changed) ? '<span class="dot" title="gegenüber dem Preset geändert"></span>' : '';
const reset = ks => ks.some(changed) ? `<button class="cv-link" data-reset="${ks.join(',')}">zurück auf Preset</button>` : '';

function cards(strip) {
  const c = PRESETS.map(p => `<button type="button" class="cv-card ${p.id === preset ? 'sel' : ''}" data-preset="${p.id}"><span class="ic">${p.ic}</span><strong>${p.name}</strong>${p.std ? `<span class="tag">Standard ${p.std}</span>` : p.user ? '<span class="tag">eigen</span>' : ''}<p>${p.desc}</p><small>${CODECS[p.cfg.codec].enc} ${p.cfg.bits}-bit · ${CODECS[p.cfg.codec].unit} ${p.cfg.crf} · ${p.cfg.speed}</small></button>`).join('');
  return `<div class="${strip ? 'cv-strip' : 'cv-cards'}">${c}<button type="button" class="cv-card add"><span class="ic">+</span><strong>Eigenes Preset</strong><p>aus der aktuellen Anpassung speichern</p></button></div>`;
}
const miniCards = () => `<div class="cv-strip wrap">${PRESETS.map(p => `<button type="button" class="cv-card ${p.id === preset ? 'sel' : ''}" data-preset="${p.id}" title="${p.desc}"><span class="ic">${p.ic}</span><strong>${p.name}</strong></button>`).join('')}</div>`;
const summary = () => {
  const c = cfg, p = PRESETS.find(x => x.id === preset), n = nChanged();
  const chips = [`${CODECS[c.codec].enc} ${c.codec === 'hw' ? '' : c.bits + '-bit'}`, `${CODECS[c.codec].unit} ${c.crf}`, c.speed, c.scale === 'keep' ? 'Auflösung bleibt' : c.scale + 'p', c.audio === 'copy' ? 'Ton kopieren' : 'Ton ' + c.audio.toUpperCase() + (c.ch === 'stereo' ? ' Stereo' : '')];
  return `<div class="cv-sum"><span class="name">${p.name}</span><div class="cv-chips">${chips.map((x, i) => `<span class="${(i === 0 && changed('codec')) || (i === 1 && changed('crf')) || (i === 2 && changed('speed')) ? 'chg' : ''}">${x}</span>`).join('')}</div><span class="grow"></span>${n ? `<span class="st warn">${n} Wert${n > 1 ? 'e' : ''} geändert</span><button class="cv-link" data-reset="all">zurück auf Preset</button>` : '<span class="st ok">wie Preset</span>'}<button class="secondary" data-saveas>Als Preset speichern …</button></div>`;
};
function qualityBlock() {
  const l = lvl(cfg.codec, cfg.crf), bl = lvl(cfg.codec, base().crf), cd = CODECS[cfg.codec];
  const ticks = [[0, 'sehr klein'], [14, 'klein'], [38, 'ausgewogen'], [64, 'hoch'], [88, 'optisch verlustfrei']];
  return `<div class="cv-q"><div class="cv-qhead"><span class="val"><span data-b="crf">${cd.unit} ${cfg.crf}</span><small>${cd.enc}</small></span><span class="word" data-b="qword">${qword(l)}</span><span class="grow" style="flex:1"></span><span class="muted" style="font-size:12px">≈ <b data-b="out" style="color:var(--text)"></b> für <i style="font-style:normal">${SRC.name}</i></span></div>
  <input class="cv-range" type="range" min="0" max="100" step="1" value="${Math.round(l)}" data-q aria-label="Qualität"><div class="cv-band"></div>
  <div class="cv-scale">${ticks.map(([t, w], i) => `<span class="${t === 88 ? 'lossless' : ''}" style="left:${Math.min(Math.max(t, 4), 92)}%">${w}</span>`).join('')}${changed('crf') ? `<span class="here" style="left:${Math.max(3, Math.min(97, bl))}%;top:20px">▲ Preset</span>` : ''}</div>
  <div class="cv-ends"><span>← kleinere Datei</span><span>bessere Qualität →</span></div></div>`;
}
const speedBlock = () => {
  const cd = CODECS[cfg.codec], i = Math.max(0, cd.speeds.indexOf(cfg.speed));
  if (cfg.codec === 'hw') return '<p class="hint">Hardware-Encoder haben keine Stufen; sie sind sehr schnell, aber bei gleicher Größe sichtbar schlechter als Software.</p>';
  return `<div class="cv-q"><div class="cv-qhead"><span class="val" style="font-size:18px">${cfg.speed}</span><span class="word" style="color:var(--blue)" data-b="dur">—</span></div>
  <input class="cv-range" type="range" min="0" max="${cd.speeds.length - 1}" value="${i}" data-sp aria-label="Geschwindigkeit"><div class="cv-ends"><span>← schneller</span><span>kleiner bei gleicher Qualität →</span></div>
  <p class="hint">Jede Stufe langsamer spart etwa 3–6 % Platz bei gleicher Qualität, dauert aber etwa doppelt so lang.${cfg.codec === 'av1' ? ' (SVT-AV1: 13 = schnell … 2 = langsam)' : ''}</p></div>`;
};
const videoBlock = () => `<div class="cv-row"><label>Codec ${reset(['codec'])}</label>${seg('codec', [['x265', 'H.265 / HEVC', 'x265'], ['x264', 'H.264', 'x264'], ['av1', 'AV1', 'SVT-AV1'], ['hw', 'Hardware', 'VAAPI'], ['copy', 'Nur remuxen', 'ohne Neukodierung']], cfg.codec, [])}</div>
  ${cfg.codec === 'hw' ? '<p class="hint">Hardware gibt es nur auf Rechnern, die sie melden: vierstein (VAAPI, /dev/dri/renderD128). maintux meldet keine Hardware und ist ausgegraut.</p>' : ''}
  <div class="cv-row"><label>Bit-Tiefe ${reset(['bits'])}</label>${seg('bits', [[8, '8 Bit', 'läuft überall'], [10, '10 Bit', 'weniger Banding, etwas kleiner']], cfg.bits)}</div>`;
const pictureBlock = () => `<div class="cv-2"><div class="cv-row"><label>Auflösung ${reset(['scale'])}</label>${seg('scale', [['keep', 'beibehalten'], ['1080', '≤ 1080p'], ['720', '≤ 720p'], ['480', '≤ 480p']], cfg.scale)}</div>
  <div class="cv-row"><label>Zuschneiden</label>${seg('crop', [['auto', 'automatisch'], ['off', 'aus'], ['man', 'manuell']], 'auto')}</div>
  <div class="cv-row"><label>Zeilensprung (Deinterlace) ${reset(['deint'])}</label>${seg('deint', [['auto', 'automatisch'], ['off', 'aus'], ['on', 'immer']], cfg.deint)}</div>
  <div class="cv-row"><label>Entrauschen ${reset(['denoise'])}</label>${seg('denoise', [['off', 'aus'], ['light', 'leicht'], ['medium', 'mittel']], cfg.denoise)}</div>
  <div class="cv-row"><label>HDR ${reset(['hdr'])}</label>${seg('hdr', [['keep', 'erhalten'], ['tonemap', 'nach SDR umrechnen']], cfg.hdr)}</div></div>`;
const audioBlock = () => `<div class="cv-2"><div class="cv-row"><label>Ton ${reset(['audio'])}</label>${seg('audio', [['copy', 'kopieren'], ['aac', 'AAC'], ['opus', 'Opus'], ['ac3', 'AC3']], cfg.audio)}</div>
  <div class="cv-row"><label>Kanäle ${reset(['ch'])}</label>${seg('ch', [['keep', 'wie Quelle'], ['51', '5.1'], ['stereo', 'Stereo-Downmix']], cfg.ch)}</div></div>
  <p class="hint">Gilt für jede Tonspur. Welche Sprachen behalten werden, steht in Einstellungen → Allgemein (jetzt: deu, eng).${cfg.audio === 'copy' ? ' Beim Kopieren bleibt DTS-HD / TrueHD unverändert (groß).' : ''}</p>`;
const subsBlock = () => `<div class="cv-row"><label>Untertitel ${reset(['subs'])}</label>${seg('subs', [['all', 'alle behalten'], ['forced', 'nur erzwungene'], ['langs', 'nur Sprachen …'], ['none', 'keine']], cfg.subs)}</div>${cfg.subs === 'langs' ? '<div class="cv-row"><label>Sprachen</label><input class="input" value="deu,eng" style="max-width:220px"></div>' : ''}`;
const expertBlock = () => `<div class="cv-row"><label>Freie Encoder-Parameter (${CODECS[cfg.codec].enc}) ${reset(['extra'])}</label><input class="input" data-extra value="${cfg.extra}" placeholder="z. B. aq-mode=3:no-sao=1"></div>
  <div class="cv-row"><label>Erzeugter ffmpeg-Befehl (nur zum Lesen)</label><pre class="cv-cmd" data-b="cmd"></pre></div>`;
const qualityMode = () => `<div class="cv-row"><label>Wie soll die Qualität bestimmt werden?</label>${seg('qmode', [['crf', 'Qualität', 'empfohlen'], ['size', 'Zielgröße', '2-Pass'], ['kbps', 'Bitrate', '2-Pass']], 'crf')}</div>`;

const SECS = [
  ['video', '▣', 'Video', () => `${CODECS[cfg.codec].name} · ${cfg.codec === 'hw' ? '' : cfg.bits + ' Bit'}`, ['codec', 'bits'], videoBlock],
  ['quality', '◐', 'Qualität', () => `${CODECS[cfg.codec].unit} ${cfg.crf} · ${qword(lvl(cfg.codec, cfg.crf))}`, ['crf'], () => qualityMode() + qualityBlock()],
  ['speed', '⏱', 'Geschwindigkeit', () => cfg.codec === 'hw' ? 'Hardware' : cfg.speed, ['speed'], speedBlock],
  ['pic', '▭', 'Bild', () => `${cfg.scale === 'keep' ? 'Auflösung bleibt' : '≤ ' + cfg.scale + 'p'} · Deinterlace ${{auto: 'auto', off: 'aus', on: 'an'}[cfg.deint]}${cfg.denoise !== 'off' ? ' · Entrauschen ' + {light: 'leicht', medium: 'mittel'}[cfg.denoise] : ''}`, ['scale', 'deint', 'denoise', 'hdr'], pictureBlock],
  ['audio', '♪', 'Ton', () => cfg.audio === 'copy' ? 'kopieren' : `${cfg.audio.toUpperCase()}${cfg.ch === 'stereo' ? ' Stereo' : ''}`, ['audio', 'ch'], audioBlock],
  ['subs', '☰', 'Untertitel', () => ({all: 'alle behalten', forced: 'nur erzwungene', langs: 'nur Sprachen', none: 'keine'})[cfg.subs], ['subs'], subsBlock],
  ['expert', '⌘', 'Experten', () => cfg.extra || 'keine freien Parameter', ['extra'], expertBlock],
];
const openSecs = new Set(['quality']);
const accordion = () => `<div class="cv-acc">${SECS.map(([id, ic, t, sm, ks, body]) => `<div class="cv-sec ${openSecs.has(id) ? 'open' : ''}" data-sec="${id}"><header data-toggle="${id}"><span class="mini-icon">${ic}</span><strong>${t}</strong>${dot(...ks)}<span class="sm">${sm()}</span><span class="chev">⌄</span></header><div>${body()}</div></div>`).join('')}</div>`;
let tab = 'quality', compactOpen = false;
const tabs = () => `<div class="cv-tabs" role="tablist">${SECS.map(([id, , t, , ks]) => `<button role="tab" class="${tab === id ? 'on' : ''}" data-tab="${id}">${t}${ks.some(changed) ? '<span class="dot"></span>' : ''}</button>`).join('')}</div>${SECS.map(([id, , , , , body]) => `<div class="cv-pane ${tab === id ? 'on' : ''}">${tab === id ? body() : ''}</div>`).join('')}`;
const prediction = (probe = true) => `<div class="cv-pred"><h4>Vorhersage <span class="st">für ${SRC.name} · ${fmtG(SRC.size)} · ${fmtT(SRC.dur)}</span><span class="sp"></span></h4>
  <div class="cv-big"><b>${fmtG(SRC.size)}</b><span class="arrow">→</span><b data-b="out">—</b><span class="minus" data-b="save"></span></div><div class="cv-sizebar"><i data-w="outw"></i></div>
  <div class="cv-nodes">${NODES.map((n, i) => `<div class="cv-node ${n.ok ? '' : 'off'}" data-nodeidx="${i}"><span><b>${n.n}</b> <em>${n.info}</em></span><div class="bar"><i data-w="w${i}"></i></div><span data-b="t${i}">—</span></div>`).join('')}</div>
  <p class="hint" style="margin:0">Berechnet aus 9 früheren Konvertierungen (x265, 1080p) und der Kernzahl; ohne Statistik steht dort „Schätzung“.</p>
  ${probe ? `<div class="cv-probe"><div class="rowend" style="justify-content:flex-start"><button class="secondary">Probe starten (2 × 25 s)</button><span class="hint">kodiert zwei kurze Ausschnitte und rechnet genauer hoch</span></div>
  <div class="cv-cmp" style="--p:50%"><div class="before"></div><div class="after"></div><span class="lab" style="left:8px">Original</span><span class="lab" style="right:8px">Ergebnis</span><div class="bar"></div><input type="range" min="0" max="100" value="50" data-cmp aria-label="Vorher/Nachher"></div><p class="hint" style="margin:0">Platzhalterbild: Hier erscheint das Standbild von der Probe, mit Schieberegler.</p></div>` : ''}</div>`;

// ---- Zahlen in die Bindungen schreiben
function binds() {
  const e = estimate(), c = cfg, cd = CODECS[c.codec], l = lvl(c.codec, c.crf), B = {};
  B.crf = `${cd.unit} ${c.crf}`; B.qword = qword(l); B.out = fmtG(e.out); B.save = `−${Math.round((1 - e.out / SRC.size) * 100)} %`; B.outw = e.out / SRC.size * 100 + '%';
  const mx = Math.max(...e.times, 1);
  e.times.forEach((t, i) => { B['t' + i] = !NODES[i].ok ? NODES[i].why : t ? '≈ ' + fmtT(t) : 'nicht verfügbar'; B['w' + i] = Math.min(100, t / mx * 100) + '%'; });
  B.dur = e.times[0] ? `ca. ${fmtT(e.times[0])} auf maintux` : '';
  const img = cd.enc, pre = c.codec === 'x265' ? `-preset ${c.speed} -crf ${c.crf} -pix_fmt yuv420p${c.bits === 10 ? '10le' : ''}${c.tune !== 'none' ? ' -tune ' + c.tune : ''} -x265-params "log-level=error${c.extra ? ':' + c.extra : ''}"` : `-preset ${c.speed} -crf ${c.crf}`;
  B.cmd = `ffmpeg -i Eingang.mkv -map 0:v:0 -map 0:a? -map 0:s? -map_chapters 0${c.denoise !== 'off' ? ' -vf hqdn3d=' + (c.denoise === 'light' ? '2:1:2:3' : '3:2:2:3') : ''} -c:v lib${img} ${pre} -c:a ${c.audio === 'copy' ? 'copy' : c.audio === 'opus' ? 'libopus' : c.audio} -c:s copy Ausgang.mkv`;
  $$('[data-b]').forEach(el => { if (B[el.dataset.b] != null) el.textContent = B[el.dataset.b]; });
  $$('[data-w]').forEach(el => { if (B[el.dataset.w] != null) el.style.width = B[el.dataset.w]; });
  // Bibliothek: Summen der Auswahl
  libBar();
}

// ---- Wiederverwendbare Editor-Ansichten
function render() {
  $$('[data-editor]').forEach(el => {
    const k = el.dataset.editor, keep = el.querySelector('.cv-tabs,.cv-acc') && el.scrollTop;
    if (k === 'acc') el.innerHTML = `<div class="cv">${cards()}${summary()}<div class="cap" style="margin:0">Anpassen: geänderte Werte sind mit einem Punkt markiert, „zurück auf Preset“ setzt einzelne Werte oder alles zurück.</div>${accordion()}${prediction()}</div>`;
    else if (k === 'studio') el.innerHTML = `<div class="cv">${cards(true)}${summary()}<div class="cv-studio"><div>${tabs()}</div><div>${prediction()}</div></div></div>`;
    else if (k === 'side') el.innerHTML = `<div class="cv">${miniCards()}${summary()}${tabs()}${prediction(false)}</div>`;
    else if (k === 'compact') el.innerHTML = `<div class="cv">${miniCards()}${summary()}<div class="rowend" style="justify-content:flex-start"><button class="secondary" data-compact>Anpassen ${compactOpen ? '▴' : '▾'}</button><span class="hint" style="margin:0">Dateien werden direkt nach dem Rippen konvertiert; Rechner und Vorhersage stehen unter „Anpassen“.</span></div>${compactOpen ? accordion() + prediction(false) : ''}</div>`;
  });
  binds();
}
document.addEventListener('click', e => {
  const t = e.target, q = s => t.closest(s);
  let el;
  if ((el = q('[data-preset]'))) { preset = el.dataset.preset; cfg = {...base()}; render(); }
  else if ((el = q('[data-set]'))) {
    const k = el.dataset.set, v = el.dataset.v;
    if (k === 'codec') { const l = lvl(cfg.codec, cfg.crf); cfg.codec = v; if (v !== 'copy') { cfg.crf = crfOf(v, l); cfg.speed = CODECS[v].speeds.includes(cfg.speed) ? cfg.speed : CODECS[v].speeds[v === 'av1' ? 5 : 5]; } }
    else if (k in cfg) cfg[k] = k === 'bits' ? +v : v;
    render();
  } else if ((el = q('[data-reset]'))) { (el.dataset.reset === 'all' ? Object.keys(cfg) : el.dataset.reset.split(',')).forEach(k => cfg[k] = base()[k]); render(); }
  else if ((el = q('[data-toggle]'))) { const id = el.dataset.toggle; openSecs.has(id) ? openSecs.delete(id) : openSecs.add(id); el.parentElement.classList.toggle('open'); }
  else if ((el = q('[data-tab]'))) { tab = el.dataset.tab; render(); }
  else if (q('[data-compact]')) { compactOpen = !compactOpen; render(); }
  else if ((el = q('[data-mk]'))) show(el.dataset.mk);
  else if ((el = q('[data-phone]'))) { $('#frame').classList.toggle('phone'); el.textContent = $('#frame').classList.contains('phone') ? 'Desktop' : 'Handy (375 px)'; }
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.matches('[data-q]')) { cfg.crf = crfOf(cfg.codec, +t.value); binds(); $$('.cv-sum .cv-chips span:nth-child(2)').forEach(s => s.textContent = CODECS[cfg.codec].unit + ' ' + cfg.crf); }
  else if (t.matches('[data-sp]')) { cfg.speed = CODECS[cfg.codec].speeds[+t.value]; $$('.cv-sec[data-sec=speed] .val,.cv-pane.on .val').forEach(s => { if (s.closest('.cv-q') === t.closest('.cv-q')) s.textContent = cfg.speed; }); binds(); }
  else if (t.matches('[data-cmp]')) t.closest('.cv-cmp').style.setProperty('--p', t.value + '%');
  else if (t.matches('[data-extra]')) { cfg.extra = t.value; binds(); }
});
document.addEventListener('change', e => { if (e.target.matches('[data-q],[data-sp]')) render(); });

// ---- Bibliothek (Teil 2)
const C = (a, b) => `--c1:${a};--c2:${b}`;
const FILES = [
  {id: 1, f: 'Filme', t: 'Dune (2021)', size: 24.6, v: 'H.264', r: '1080p', a: 'TrueHD 7.1', col: C('#7a5b3a', '#2a3a4d'), st: 'orig', dur: '2:35 h'},
  {id: 2, f: 'Filme', t: 'Blade Runner 2049 (2017)', size: 58.3, v: 'HEVC', r: 'UHD', hdr: 'HDR10', a: 'TrueHD Atmos', col: C('#c4693a', '#23324a'), st: 'orig', dur: '2:43 h', n: 'UHD-Original: HEVC bleibt, Preset „UHD“ spart wenig'},
  {id: 3, f: 'Filme', t: 'Der Herr der Ringe – Die Gefährten (2001)', size: 31.2, v: 'VC-1', r: '1080p', a: 'DTS-HD MA', col: C('#4a6b3a', '#2a2a3a'), st: 'run', pct: 0.46, host: 'maintux', eta: '1:12 Std.', dur: '3:48 h'},
  {id: 4, f: 'Filme', t: 'Metropolis (1927)', size: 18.9, v: 'H.264', r: '1080p', a: 'FLAC 2.0', col: C('#6b6b6b', '#222'), st: 'orig', dur: '2:33 h', korn: true},
  {id: 5, f: 'Filme', t: 'Beispielfilm (2019)', size: 1.2, v: 'H.264', r: 'SD', a: 'AC3 2.0', col: C('#3a5b7a', '#5a3a4a'), st: 'conv', dur: '2:00 min', before: 3.4},
  {id: 6, f: 'Filme', t: 'Wallace & Gromit – Der Fluch (2005)', size: 7.9, v: 'MPEG-2', r: 'SD', a: 'AC3 5.1', col: C('#b99a3a', '#4a3a2a'), st: 'orig', dur: '1:25 h', anim: true},
  {id: 7, f: 'The Walking Dead – Staffel 1', t: 'The Walking Dead S01E01', size: 4.1, v: 'H.264', r: '1080p', a: 'DTS-HD MA', col: C('#5a2a2a', '#1a1a1a'), st: 'run', pct: 0, host: 'vierstein', q: true, dur: '44 min'},
  {id: 8, f: 'The Walking Dead – Staffel 1', t: 'The Walking Dead S01E02', size: 4.0, v: 'H.264', r: '1080p', a: 'DTS-HD MA', col: C('#5a2a2a', '#1a1a1a'), st: 'orig', dur: '43 min'},
  {id: 9, f: 'The Walking Dead – Staffel 1', t: 'The Walking Dead S01E03', size: 4.2, v: 'H.264', r: '1080p', a: 'DTS-HD MA', col: C('#5a2a2a', '#1a1a1a'), st: 'orig', dur: '45 min'},
  {id: 10, f: 'The Walking Dead – Staffel 1', t: 'The Walking Dead S01E04', size: 3.9, v: 'H.264', r: '1080p', a: 'DTS-HD MA', col: C('#5a2a2a', '#1a1a1a'), st: 'err', dur: '43 min', err: 'ffmpeg beendet (Segment 2/3) – Original unverändert'},
  {id: 11, f: 'Unsortiert', t: 'Titel 05 (Hochzeit 1998)', size: 6.3, v: 'MPEG-2', r: 'SD', a: 'AC3 2.0', col: C('#8a6a8a', '#3a2a3a'), st: 'orig', dur: '1:12 h', new: true},
  {id: 12, f: 'Unsortiert', t: 'Ärger & Übung – Tschüß Fußball', size: 0.2, v: 'H.264', r: '360p', a: 'AAC 2.0', col: C('#3a7a5a', '#2a3a3a'), st: 'lock', host: 'secondtux', dur: '20 s'},
];
const fl = {play: 0, q: 'all', kind: 'all', sel: new Set([1, 4, 6]), cur: 1, view: 'list', cvOpen: false, filt: false};
const std = f => f.r === 'SD' || f.r === '360p' ? 'dvd' : f.korn ? 'grain' : f.anim ? 'anim' : f.hdr ? 'uhd' : 'bluray';
const estF = f => { const p = PRESETS.find(x => x.id === (libPreset === 'auto' ? std(f) : libPreset)); const r = f.v === 'HEVC' ? .85 : f.r === 'SD' ? .28 : p.id === 'grain' ? .42 : p.id === 'small' ? .1 : p.id === 'anim' ? .17 : .23; return f.size * r; };
let libPreset = 'auto';
const stBadge = f => ({orig: '<span class="lib-b old">Original</span>', conv: '<span class="lib-b ok">konvertiert</span>', run: '<span class="lib-b err" style="background:#351b24">in Arbeit</span>', err: '<span class="lib-b err">Fehler</span>', lock: '<span class="lib-b">gesperrt</span>'})[f.st];
const badges = f => `<div class="lib-badges"><span class="lib-b ${f.v === 'HEVC' ? 'ok' : 'old'}">${f.v}</span><span class="lib-b ${f.r === 'SD' || f.r === '360p' ? 'sd' : ''}">${f.r}</span>${f.hdr ? `<span class="lib-b hdr">${f.hdr}</span>` : ''}<span class="lib-b">${f.a}</span>${stBadge(f)}</div>`;
const visible = () => FILES.filter(f => (fl.q === 'all' || (fl.q === 'orig' && f.st === 'orig') || (fl.q === 'conv' && f.st === 'conv') || (fl.q === 'run' && f.st === 'run') || (fl.q === 'err' && f.st === 'err')) &&
  (fl.kind === 'all' || (fl.kind === 'film' && f.f === 'Filme') || (fl.kind === 'serie' && /Staffel/.test(f.f)) || (fl.kind === 'uns' && f.f === 'Unsortiert')));
const runBlock = f => f.st !== 'run' ? '' : `<div class="lib-run"><div class="t"><span class="status-check run" style="width:15px;height:15px;border-width:2px"></span>${f.q ? 'wartet bei' : 'konvertiert auf'} <b>${f.host}</b>${f.q ? '' : ` · ${Math.round(f.pct * 100)} % · Restzeit ${f.eta}`}<span class="btns"><button class="secondary">Überspringen</button><button class="secondary danger">Abbrechen</button></span></div><div class="mini-bar"><div style="width:${Math.round(f.pct * 100)}%"></div></div></div>`;
function row(f) {
  const sv = f.st === 'orig' ? `<small>−${fmtG(f.size * GB - estF(f) * GB).replace(' GB', '')} GB</small>` : f.st === 'conv' ? `<small>war ${fmtG(f.before * GB)}</small>` : '';
  return `<div class="lib-row ${fl.sel.has(f.id) ? 'sel' : ''} ${fl.cur === f.id ? 'cur' : ''}" data-file="${f.id}"><input class="check" type="checkbox" data-fsel="${f.id}" ${fl.sel.has(f.id) ? 'checked' : ''} ${f.st === 'orig' ? '' : 'disabled'} aria-label="auswählen"><div class="lib-thumb" style="${f.col}">${f.r}</div>
    <div class="nm"><strong>${f.t}</strong><small>${f.f} · ${f.dur}${f.n ? ' · ' + f.n : ''}${f.err ? ' · ' + f.err : ''}${f.st === 'lock' ? ' · wird von ' + f.host + ' bearbeitet' : ''}</small></div>${badges(f)}<div class="sz">${fmtG(f.size * GB)}${sv}</div>${runBlock(f)}</div>`;
}
function tile(f) {
  return `<div class="lib-tile ${fl.sel.has(f.id) ? 'sel' : ''}" data-file="${f.id}"><div class="poster" style="${f.col}"><div class="lib-badges"><span class="lib-b ${f.v === 'HEVC' ? 'ok' : 'old'}">${f.v}</span><span class="lib-b">${f.r}</span>${f.hdr ? '<span class="lib-b hdr">HDR</span>' : ''}</div>${f.t.replace(/ \(\d{4}\)$/, '')}${f.st === 'orig' ? `<input class="check chk" type="checkbox" data-fsel="${f.id}" ${fl.sel.has(f.id) ? 'checked' : ''}>` : ''}${f.st === 'run' ? `<span class="runtag">${f.q ? 'wartet' : Math.round(f.pct * 100) + ' % · ' + f.host}</span><div class="prog"><i style="width:${f.pct * 100}%"></i></div>` : ''}</div>
    <div class="cap2"><strong>${f.t}</strong><span>${fmtG(f.size * GB)} ${f.st === 'orig' ? `· <span style="color:#75e6b3">−${fmtG(f.size * GB - estF(f) * GB).replace(' GB', '')} GB möglich</span>` : stBadge(f)}</span></div></div>`;
}
function listHtml(v) {
  const fs = visible(), groups = [...new Set(fs.map(f => f.f))];
  if (v === 'grid') return `<div class="lib-grid">${fs.map(tile).join('')}</div>`;
  return `<div class="lib-list">${groups.map(g => { const gf = fs.filter(f => f.f === g); return `<div class="lib-grp"><span>▾</span><strong>${g}</strong><span class="pill">${gf.length} Dateien</span><span class="pill">${fmtG(gf.reduce((a, f) => a + f.size * GB, 0))}</span><span class="sp"></span><button class="secondary">✎ Umbenennen</button></div>${gf.map(row).join('')}`; }).join('')}</div>`;
}
const cnt = k => FILES.filter(f => f.st === k).length;
const filterHtml = () => `<h5>Status</h5>${[['all', 'Alle', FILES.length], ['orig', 'Original', cnt('orig')], ['conv', 'Konvertiert', cnt('conv')], ['run', 'In Arbeit', cnt('run')], ['err', 'Fehler', cnt('err')]].map(([k, l, n]) => `<button class="lib-fi ${fl.q === k ? 'on' : ''}" data-q="${k}">${l}<span class="n">${n}</span></button>`).join('')}
  <div><h5>Art</h5>${[['all', 'Alles'], ['film', 'Filme'], ['serie', 'Serien'], ['uns', 'Unsortiert']].map(([k, l]) => `<button class="lib-fi ${fl.kind === k ? 'on' : ''}" data-kind="${k}">${l}</button>`).join('')}<p class="hint" style="margin:6px 8px 0">Art und Poster erscheinen, sobald Jellyfin-Ablage (PE) Metadaten liefert.</p></div>
  <div><h5>Ordner</h5><button class="lib-fi on">▾ Alle Ordner</button><button class="lib-fi sub">Filme <span class="n">6</span></button><button class="lib-fi sub">The Walking Dead – Staffel 1 <span class="n">4</span></button><button class="lib-fi sub">Unsortiert <span class="n">2</span></button></div>
  <div><h5>Rechner</h5><button class="lib-fi">alle</button><button class="lib-fi">arbeitet: maintux <span class="n">1</span></button><button class="lib-fi">arbeitet: vierstein <span class="n">1</span></button></div>`;
function detailHtml() {
  const f = FILES.find(x => x.id === fl.cur); if (!f) return '<p class="muted" style="font-size:12px">Datei wählen, um Einzelheiten zu sehen.</p>';
  const e = estF(f), p = PRESETS.find(x => x.id === (libPreset === 'auto' ? std(f) : libPreset));
  return `<div><div style="display:flex;gap:10px"><div class="lib-thumb" style="width:56px;height:80px;${f.col}">${f.r}</div><div style="min-width:0"><h3>${f.t}</h3><div class="sub">${f.f}/${f.t}.mkv</div><div style="margin-top:6px">${stBadge(f)}</div></div></div></div>
  <dl class="lib-kv"><dt>Video</dt><dd>${f.v} · ${f.r === 'SD' ? '720×576' : f.r === 'UHD' ? '3840×2160' : '1920×1080'} · ${f.hdr ? '10 Bit ' + f.hdr : '8 Bit'}</dd><dt>Bitrate</dt><dd>${dec((f.size * 8 * 1024 / (f.dur.includes('h') ? 9300 : 2640)).toFixed(1))} Mb/s</dd><dt>Dauer</dt><dd>${f.dur}</dd><dt>Größe</dt><dd>${fmtG(f.size * GB)}</dd></dl>
  <div class="lib-tracks"><div><span>Ton</span>${f.a} · deu</div><div><span>Ton</span>${f.a.split(' ')[0]} 2.0 · eng</div><div><span>Unter.</span>deu, eng, fra (3 PGS)</div><div><span>Kapitel</span>24</div></div>
  ${f.st === 'orig' ? `<div class="lib-save"><small>Mit „${p.name}“</small><b>≈ ${fmtG(e * GB)} <span style="font-size:12px;font-weight:500;color:#8ab8a3">(−${Math.round((1 - e / f.size) * 100)} %)</span></b><small>Ersparnis ca. ${fmtG((f.size - e) * GB)} · Dauer auf maintux ca. ${fmtT(f.size * 900)}</small></div>` : ''}
  <div class="lib-player" ${fl.play === f.id ? '' : 'hidden'}><div class="pl-screen">Player (PD) · eingebettet im Detailbereich<br><small>mountPlayer(el, path, {compact:true})</small></div><div class="pl-ctl"><span>▶</span><i><b></b></i><span>0:42 / ${f.dur}</span><span>🔊</span><span>⛶</span></div></div>
  <div class="lib-acts"><button class="primary" data-play="${f.id}">▶ ${fl.play === f.id ? 'Player schließen' : 'Abspielen'}</button><button class="secondary" data-cvopen ${f.st !== 'orig' ? 'disabled' : ''}>Konvertieren …</button><button class="secondary">In Filme einsortieren …</button><button class="secondary">✎ Umbenennen</button><a class="secondary" href="#">Download</a><button class="secondary danger">Löschen</button></div>
  <p class="hint" style="margin:0">„Abspielen“ (Player, PD) und „Einsortieren“ (PE) melden sich über <code>registerLibraryAction</code> an; ihre Knöpfe stehen hier, in der Zeile und in der Auswahlleiste.</p>`;
}
function libBar() {
  const bar = $('[data-libbar]'); if (!bar) return;
  const fs = FILES.filter(f => fl.sel.has(f.id)), tot = fs.reduce((a, f) => a + f.size, 0), sv = fs.reduce((a, f) => a + f.size - estF(f), 0);
  $$('[data-libbar]').forEach(b => {
    b.hidden = !fs.length;
    b.innerHTML = `<b>${fs.length} Datei${fs.length === 1 ? '' : 'en'} · ${fmtG(tot * GB)}</b><span class="sv">≈ ${fmtG(sv * GB)} Ersparnis</span><span class="grow"></span>
    <select aria-label="Preset"><option>Preset: automatisch je Disc-Art</option>${PRESETS.map(p => `<option>${p.name}</option>`).join('')}</select>
    <select aria-label="Ausführen auf"><option>auf maintux · ≈ ${fmtT(tot * 900)}</option><option>auf vierstein · ≈ ${fmtT(tot * 5200)}</option><option disabled>secondtux · versteht die Einstellungen nicht</option></select>
    <button class="secondary" data-cvopen>Anpassen …</button><button class="primary" style="width:auto">Konvertieren</button><button class="secondary" data-clear>Auswahl aufheben</button>`;
  });
}
function renderLib() {
  const A = $('#libA'); if (A) {
    A.innerHTML = `<div class="app-top"><div class="brand"><span class="brand-mark"></span>MakeMKV Web</div><div class="app-nav"><span>Laufwerke</span><span class="on">Bibliothek</span><span>Einstellungen</span></div></div>
    <div class="lib-head"><h2>Bibliothek</h2><span class="pill">/mnt/datenstein/dump</span><div class="lib-stat"><div>Frei im Ziel<br><b>2,4 TB</b> von 20 TB<div class="lib-meter"><i style="width:88%"></i></div></div><div>Originale<br><b>${fmtG(FILES.filter(f => f.st === 'orig').reduce((a, f) => a + f.size * GB, 0))}</b> in ${cnt('orig')} Dateien</div><div class="save">Mögliche Einsparung<br><b>≈ ${fmtG(FILES.filter(f => f.st === 'orig').reduce((a, f) => a + (f.size - estF(f)) * GB, 0))}</b></div></div></div>
    <div class="lib-cols ${fl.cvOpen || fl.cur ? '' : 'nodetail'}"><aside class="lib-filter ${fl.filt ? 'open' : ''}">${filterHtml()}</aside>
    <div class="lib-main"><div class="lib-tools"><button class="secondary lib-filterbtn" data-filt>☰ Filter</button><input class="input" placeholder="Filtern …"><div class="lib-view"><button class="${fl.view === 'list' ? 'on' : ''}" data-view="list">☰ Liste</button><button class="${fl.view === 'grid' ? 'on' : ''}" data-view="grid">▦ Raster</button></div><span class="muted" style="font-size:11px">12 Dateien · 0 werden geprüft</span><span style="flex:1"></span><button class="secondary" data-all>Alle „Original“ wählen</button></div>${listHtml(fl.view)}</div>
    ${fl.cvOpen ? `<aside class="lib-sidecv"><h3>Konvertieren <span class="sp"></span><button class="secondary" data-cvclose>Schließen</button></h3><div data-editor="side"></div></aside>` : `<aside class="lib-detail">${detailHtml()}</aside>`}</div>
    <div class="lib-bar" data-libbar hidden></div>`;
    render();
  }
  const B = $('#libB'); if (B) {
    const fs = visible();
    B.innerHTML = `<div class="app-top"><div class="brand"><span class="brand-mark"></span>MakeMKV Web</div><div class="app-nav"><span>Laufwerke</span><span class="on">Bibliothek</span><span>Einstellungen</span></div></div>
    <div class="lib-head"><h2>Bibliothek</h2><div class="lib-stat"><div>Frei im Ziel<br><b>2,4 TB</b> von 20 TB</div><div class="save">Mögliche Einsparung<br><b>≈ ${fmtG(FILES.filter(f => f.st === 'orig').reduce((a, f) => a + (f.size - estF(f)) * GB, 0))}</b></div></div></div>
    <div class="lib-chips">${[['all', 'Alle'], ['orig', 'Original'], ['conv', 'Konvertiert'], ['run', 'In Arbeit'], ['err', 'Fehler']].map(([k, l]) => `<button class="${fl.q === k ? 'on' : ''}" data-q="${k}">${l}</button>`).join('')}<span style="width:1px;background:var(--line);margin:0 4px"></span>${[['all', 'Alles'], ['film', 'Filme'], ['serie', 'Serien'], ['uns', 'Unsortiert']].map(([k, l]) => `<button class="${fl.kind === k ? 'on' : ''}" data-kind="${k}">${l}</button>`).join('')}</div>
    <div class="lib-tools"><input class="input" placeholder="Filtern …"><div class="lib-view"><button class="${fl.view === 'list' ? 'on' : ''}" data-view="list">☰ Liste</button><button class="${fl.view === 'grid' ? 'on' : ''}" data-view="grid">▦ Raster</button></div></div>
    ${listHtml(fl.view === 'list' ? 'list' : 'grid')}
    ${fl.cur ? `<div class="lib-sheet">${detailHtml()}</div>` : ''}<div class="lib-bar" data-libbar hidden></div>`;
  }
  binds();
}
document.addEventListener('click', e => {
  const t = e.target, q = s => t.closest(s); let el;
  if ((el = q('[data-fsel]'))) { const id = +el.dataset.fsel; el.checked ? fl.sel.add(id) : fl.sel.delete(id); e.stopPropagation(); renderLib(); }
  else if ((el = q('[data-file]'))) { fl.cur = +el.dataset.file; fl.cvOpen = false; renderLib(); }
  else if ((el = q('[data-q]')) && !el.matches('input')) { fl.q = el.dataset.q; renderLib(); }
  else if ((el = q('[data-kind]'))) { fl.kind = el.dataset.kind; renderLib(); }
  else if ((el = q('[data-view]'))) { fl.view = el.dataset.view; renderLib(); }
  else if (q('[data-all]')) { FILES.filter(f => f.st === 'orig').forEach(f => fl.sel.add(f.id)); renderLib(); }
  else if (q('[data-clear]')) { fl.sel.clear(); renderLib(); }
  else if (q('[data-cvopen]')) { fl.cvOpen = true; renderLib(); }
  else if ((el = q('[data-play]'))) { fl.play = fl.play === +el.dataset.play ? 0 : +el.dataset.play; renderLib(); }
  else if (q('[data-cvclose]')) { fl.cvOpen = false; renderLib(); }
  else if (q('[data-filt]')) { fl.filt = !fl.filt; renderLib(); }
});

// ---- Ansichten umschalten
const SECTIONS = {
  p1a: ['Teil 1 · A: Karten + Akkordeon', 'acc'], p1b: ['Teil 1 · B: Karten + Reiter + Vorhersage-Spalte', 'studio'], p1c: ['Teil 1 · C: Einstellungen „Konvertierung & Presets“', null], p1d: ['Teil 1 · D: Titelliste „Nach dem Rippen konvertieren“', 'compact'],
  p2a: ['Teil 2 · A: Liste mit Filter, Detail und Auswahlleiste', null], p2b: ['Teil 2 · B: Raster/Poster mit Filter-Chips und Schublade', null],
};
const NOTES = {
  p1a: 'Eine Spalte, in jeder Breite gleich: Preset-Karten, Zusammenfassung mit Änderungsmarken, darunter die sieben Abschnitte zum Aufklappen (Video · Qualität · Geschwindigkeit · Bild · Ton · Untertitel · Experten) und die Vorhersage. Gut für schmale Orte (Titelliste, Seitenleiste, Handy).',
  p1b: 'Breite Variante: Reiter statt Akkordeon, die Vorhersage steht immer sichtbar rechts, während man regelt. Unter 1180 px rutscht sie unter die Reiter. Gedacht für den Einstellungsabschnitt und die Bibliothek-Seitenleiste.',
  p1c: 'Einstellungsabschnitt: mitgelieferte Presets (nicht löschbar), eigene Presets (umbenennen, löschen), Standard-Zuordnung je Disc-Art, Segmente und Parallelität. „Bearbeiten“ öffnet denselben Editor wie oben.',
  p1d: 'Kompakte Form im Panel „Nach dem Rippen konvertieren“ der Titelliste: eine Reihe Karten + Zusammenfassung; „Anpassen“ klappt den Editor (Variante A) darunter auf. Ersetzt das heutige Formular.',
  p2a: 'Drei Bereiche: Filter links (Status, Art, Ordner, Rechner), Dateien mittig, Detail rechts. Auswahl (Häkchen oder „Alle Original wählen“) blendet unten die Leiste mit Summe, Preset, „Ausführen auf“ (mit Dauer je Rechner) ein; „Anpassen …“ ersetzt das Detail durch den Editor. Laufende Arbeit steht direkt an der Datei. Unter 760 px: Filter hinter „Filter“, Detail unter der Liste. Poster/Art erscheinen, sobald PE Metadaten liefert.',
  p2b: 'Raster mit Postern für Sammlungen mit Metadaten (sonst Farbfläche mit Titel); Filter als Chips oben (spart Breite), Detail als Schublade unter dem Raster, dieselbe Auswahlleiste. Umschalter Liste/Raster gibt es in beiden Varianten.',
};
function show(id) {
  $$('.mk-frame>section').forEach(s => s.classList.toggle('on', s.id === id));
  $$('[data-mk]').forEach(b => b.classList.toggle('on', b.dataset.mk === id));
  $('#note').textContent = NOTES[id]; history.replaceState(null, '', '#' + id);
  if (id.startsWith('p2')) renderLib(); else render();
}
$('#tabs').innerHTML = Object.entries(SECTIONS).map(([id, [l]]) => `<button data-mk="${id}">${l}</button>`).join('');
$$('.mk-frame>section[data-editor]').forEach(() => { });
(() => {
  const set = (id, html) => { $('#' + id).innerHTML = html; };
  const top = '<div class="app-top"><div class="brand"><span class="brand-mark"></span>MakeMKV Web</div><div class="app-nav"><span>Laufwerke</span><span>Bibliothek</span><span class="on">Einstellungen</span></div></div>';
  set('p1a', `${top}<div class="app-pad"><section class="panel"><div class="panel-head"><span class="mini-icon">⚙</span><h2>Konvertierung einstellen</h2><span class="sub">gleicher Editor in Titelliste, Bibliothek und Einstellungen</span></div><div class="app-pad" data-editor="acc"></div></section></div>`);
  set('p1b', `${top}<div class="app-pad"><section class="panel"><div class="panel-head"><span class="mini-icon">⚙</span><h2>Konvertierung einstellen</h2></div><div class="app-pad" data-editor="studio"></div></section></div>`);
  set('p1c', `${top}<div class="app-pad"><div class="set-grid"><div class="set-list"><span>Allgemein</span><span class="on">Konvertierung &amp; Presets</span><span>Rechner</span><span>Medien / Jellyfin</span><span>MakeMKV-Key</span></div>
    <section class="panel"><div class="panel-head"><span class="mini-icon">⚙</span><h2>Konvertierung &amp; Presets</h2><span class="spacer"></span><button class="primary" style="width:auto">Speichern</button></div><div class="app-pad" style="display:grid;gap:18px">
    <div><h4 style="margin:0 0 8px;font-size:12.5px">Standard je Disc-Art</h4><div class="cv-2"><div class="cv-row"><label>Blu-ray</label><select class="input"><option>Blu-ray optimal</option><option>Blu-ray Animation</option><option>Serien sparsam (eigen)</option></select></div><div class="cv-row"><label>DVD</label><select class="input"><option>DVD optimal</option></select></div><div class="cv-row"><label>UHD-Blu-ray</label><select class="input"><option>UHD / HDR erhalten</option></select></div></div></div>
    <div><h4 style="margin:0 0 8px;font-size:12.5px">Presets</h4><div class="table-wrap"><table class="cv-table"><thead><tr><th>Name</th><th>Werte</th><th>Wofür</th><th></th></tr></thead><tbody>${PRESETS.map(p => `<tr><td><b>${p.name}</b> ${p.user ? '<span class="tag">eigen</span>' : '<span class="tag">mitgeliefert</span>'}</td><td class="muted">${CODECS[p.cfg.codec].enc} ${p.cfg.bits}-bit · ${CODECS[p.cfg.codec].unit} ${p.cfg.crf} · ${p.cfg.speed}</td><td class="muted">${p.desc}</td><td style="text-align:right;white-space:nowrap"><button class="secondary">Ansehen / Anpassen</button> ${p.user ? '<button class="secondary">✎</button> <button class="secondary danger">Löschen</button>' : '<button class="secondary">Kopieren</button>'}</td></tr>`).join('')}</tbody></table></div></div>
    <div class="cv-2"><div class="cv-row"><label>Gleichzeitige Dateien</label><input class="input" type="number" value="1" min="1" max="8"><span class="hint">Mehr als 1 parallel nur auf Rechnern mit vielen Kernen sinnvoll (jetzt 4 Kerne: 1).</span></div><div class="cv-row"><label>Segmente je Film (0 = automatisch)</label><input class="input" type="number" value="0"><span class="hint">Lange Filme werden zeitlich geteilt und parallel kodiert; funktioniert mit allen Software-Codecs.</span></div></div>
    <div><h4 style="margin:0 0 8px;font-size:12.5px">Fähigkeiten dieses Rechners</h4><div class="cv-chips"><span>x265 ✓</span><span>x264 ✓</span><span>SVT-AV1 ✓</span><span>VAAPI (renderD128) ✓</span><span>QSV ✓</span><span>Opus ✓</span></div></div>
    </div></section></div></div>`);
  set('p1d', `<div class="app-top"><div class="brand"><span class="brand-mark"></span>MakeMKV Web</div><div class="app-nav"><span class="on">Laufwerke</span><span>Bibliothek</span><span>Einstellungen</span></div></div><div class="app-pad"><section class="panel" style="max-width:760px"><div class="panel-head"><span class="mini-icon">▤</span><h2>The Walking Dead – Disc 1</h2><span class="pill">5 Titel gewählt</span></div><div class="app-pad">
    <div class="settings flat"><div class="settings-toggle" style="cursor:default"><span class="mini-icon">⚙</span><strong>Nach dem Rippen konvertieren</strong><span class="spacer"></span><label class="switch"><input class="check" type="checkbox" checked> an</label></div><div class="settings-body"><div data-editor="compact"></div></div></div></div></section></div>`);
  const p2 = id => { $('#' + id).innerHTML = ''; };
  p2('libA'); p2('libB');
})();
$('#ctl').innerHTML = '<button data-phone>Handy (375 px)</button>';
const start = () => { const h = (location.hash || '#p1a').slice(1); return SECTIONS[h] ? h : 'p1a'; };
show(start());
window.addEventListener('hashchange', () => { if (start() !== $('.mk-frame>section.on').id) show(start()); });
