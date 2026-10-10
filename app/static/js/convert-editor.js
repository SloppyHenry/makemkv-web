// Konvertierungs-Editor (wiederverwendbar): Preset-Karten, Anpassen in Ebenen, Vorhersage, Probe. Besitzer: PF.
//   const ed = mountConvertEditor(el, value, {target, onChange, mode, discKind, files, readonly})
//   value  Einstellungen v1 oder v2 (null = Standard der discKind); das Feld `convert` (an/aus) wird unverändert durchgereicht
//   target Name des Rechners für Fähigkeiten (''/dieser = lokal)         files  Beispieldateien für die Vorhersage ([{path}] oder [{size,dur,w,h,fps,audio}])
//   mode   'full' (Karten + Anpassen + Vorhersage) | 'compact' (Karten-Reihe, „Anpassen“ klappt auf) | 'side' (Seitenleiste der Bibliothek)
//   onChange(cfg): vollständige v2-Einstellung ohne die alten Spiegelfelder; Rückgabe: {get(), set(value), refresh(), destroy()}
import { $, api, esc, toast } from './core.js';
import { clone, crfOf, diffPaths, getPath, levelOf, loadMeta, capsFor, metaNow, presetById, qWord, reloadMeta, setPath, strip, unitOf } from './convert-meta.js';
import { accordion, ctx } from './convert-sections.js';
import { Predictor, predictHtml } from './convert-predict.js';
export { getDefaultConfig, cvSummary, loadMeta } from './convert-meta.js';

const ICONS = {dvd: '◎', bluray: '◉', animation: '✦', grain: '░', uhd: '◆', small: '▾'};
const KIND_NAME = {bluray: 'Blu-ray', dvd: 'DVD', uhd: 'UHD'};

class Editor {
  constructor(el, value, opts){
    this.el = el; this.opts = {mode: 'full', target: '', files: [], ...opts}; this.cfg = null; this.base = null; this.open = new Set(['quality']);
    this.compactOpen = false; this.naming = false; this.dead = false; this.value = value;
    this.pred = new Predictor(el, () => this.cfg, this.opts);
    this.handlers = {click: e => this.click(e), input: e => this.input(e), change: e => this.change(e), keydown: e => this.key(e)};
    for(const [t, f] of Object.entries(this.handlers)) el.addEventListener(t, f);
    el.classList.toggle('ro', !!this.opts.readonly);
    el.innerHTML = '<div class="cv"><p class="hint" style="margin:0">Lädt …</p></div>';
    this.init(value);
  }
  async init(value){
    try{
      const m = await loadMeta();
      if(this.dead) return;
      let v = value;
      if(!v) v = clone((m.defaults[this.opts.discKind] || m.defaults.bluray).cfg), v.convert = false;
      else if(!v.video) v = (await api('/api/convert/normalize', 'POST', {cfg: v})).cfg;    // alte fünf Felder: der Server migriert
      this.cfg = strip(v); this.syncBase(); this.render(); this.pred.schedule(0);
    }catch{ if(!this.dead) this.el.innerHTML = '<div class="cv"><p class="hint warn">Die Konvertierungs-Einstellungen konnten nicht geladen werden.</p></div>'; }
  }
  syncBase(){ const p = this.cfg && presetById(this.cfg.origin); this.base = p ? p.cfg : null; }
  emit(){ if(this.opts.onChange) this.opts.onChange(strip(this.cfg)); this.pred.schedule(); }
  change_(fn){ fn(); this.syncBase(); this.render(); this.emit(); }

  // ---- Darstellung
  cards(){
    const m = metaNow(), mini = this.opts.mode !== 'full', def = {};
    for(const [k, d] of Object.entries(m.defaults)) if(d.id) (def[d.id] ||= []).push(KIND_NAME[k] || k);
    const card = p => mini
      ? `<button type="button" class="cv-card ${p.id === this.cfg.origin ? 'sel' : ''}" data-preset="${esc(p.id)}" title="${esc(p.desc)}" aria-pressed="${p.id === this.cfg.origin}"><span class="ic">${ICONS[p.id] || '✎'}</span><strong>${esc(p.name)}</strong></button>`
      : `<button type="button" class="cv-card ${p.id === this.cfg.origin ? 'sel' : ''}" data-preset="${esc(p.id)}" aria-pressed="${p.id === this.cfg.origin}"><span class="ic">${ICONS[p.id] || '✎'}</span><strong>${esc(p.name)}</strong>
        ${def[p.id] ? `<span class="tag">Standard ${esc(def[p.id].join(' · '))}</span>` : p.builtin ? '' : '<span class="tag">eigen</span>'}<p>${esc(p.desc)}</p><small>${esc(this.spec(p.cfg))}</small></button>`;
    return `<div class="${mini ? 'cv-strip wrap' : 'cv-cards'}" role="group" aria-label="Preset wählen">${m.presets.map(card).join('')}</div>`;
  }
  spec(c){ return `${c.video.codec === 'hw' ? c.video.hw : c.video.codec} ${c.video.bits}-bit · ${unitOf(c)} ${c.quality.crf}${c.video.speed ? ' · ' + c.video.speed : ''}`; }
  summary(){
    const c = this.cfg, p = presetById(c.origin), n = this.base ? diffPaths(c, this.base).length : 0, v = c.video, ch = new Set(this.base ? diffPaths(c, this.base) : []);
    const q = c.quality, chips = [[`${v.codec === 'hw' ? v.hw : v.codec === 'copy' ? 'Video kopieren' : v.codec + ' ' + v.bits + '-bit'}`, ch.has('video.codec') || ch.has('video.bits')],
      ...(v.codec === 'copy' ? [] : [[q.mode === 'crf' ? `${unitOf(c)} ${q.crf}` : q.mode === 'size' ? `${q.size_gb} GB` : `${q.kbps} kb/s`, ch.has('quality.crf') || ch.has('quality.mode'), 'quality'], [v.speed || 'Hardware', ch.has('video.speed')],
        [c.picture.scale === 'keep' ? 'Auflösung bleibt' : '≤ ' + c.picture.scale + 'p', ch.has('picture.scale')]]), [c.sound.mode === 'copy' ? 'Ton kopieren' : 'Ton ' + c.sound.mode.toUpperCase() + (c.sound.channels === 'stereo' ? ' Stereo' : ''), ch.has('sound.mode')]];
    const save = this.naming ? `<span class="cv-inline"><input class="input" data-name placeholder="Name des Presets" maxlength="60" aria-label="Name des neuen Presets" autofocus><button type="button" class="primary" style="width:auto;padding:7px 12px" data-savenow>Speichern</button><button type="button" class="secondary" data-saveno>Abbrechen</button></span>`
      : '<button type="button" class="secondary" data-saveas>Als Preset speichern …</button>';
    return `<div class="cv-sum"><span class="name">${p ? esc(p.name) : 'Eigene Einstellung'}</span><div class="cv-chips">${chips.map(([t, g, k]) => `<span class="${g ? 'chg' : ''}" ${k ? `data-chip="${k}"` : ''}>${esc(t)}</span>`).join('')}</div><span class="grow"></span>
      ${this.base ? (n ? `<span class="st warn">${n} Wert${n > 1 ? 'e' : ''} geändert</span><button type="button" class="cv-link" data-reset="all">zurück auf Preset</button>` : '<span class="st ok">wie Preset</span>') : ''}${this.opts.readonly ? '' : save}</div>`;
  }
  render(){
    if(this.dead || !this.cfg) return;
    const m = metaNow(), mode = this.opts.mode, caps = capsFor(this.opts.target), x = ctx(this.cfg, this.base, caps), one = this.opts.files.some(f => f.path);
    const adj = () => accordion(x, m, this.open, one);
    const body = mode === 'compact'
      ? `<div class="cv-inline"><button type="button" class="secondary" data-compact aria-expanded="${this.compactOpen}">Anpassen ${this.compactOpen ? '▴' : '▾'}</button><span class="hint">Dateien werden direkt nach dem Rippen konvertiert; Rechner und Vorhersage stehen unter „Anpassen“.</span></div>${this.compactOpen ? adj() + predictHtml(false, false) : ''}`
      : `${adj()}${predictHtml(one, true)}`;
    const keep = [this.el.scrollTop, document.activeElement && document.activeElement.id];
    this.el.innerHTML = `<div class="cv"><div class="cv-in">${this.opts.noCards ? '' : this.cards()}${this.summary()}${body}</div></div>`;
    this.pred.paint();
    if(keep[1]) { const f = document.getElementById(keep[1]); if(f && this.el.contains(f)) f.focus({preventScroll: true}); }
  }

  // ---- Bedienung
  selectPreset(id){
    const p = presetById(id); if(!p) return;
    this.change_(() => { const keepConv = this.cfg.convert; this.cfg = {...strip(p.cfg), convert: keepConv, origin: p.id}; });
  }
  setCodec(c){
    const m = metaNow(), old = this.cfg.video.codec, caps = capsFor(this.opts.target), lvl = old !== 'copy' ? levelOf(old, this.cfg.quality.crf) : (this.base ? levelOf(this.base.video.codec, this.base.quality.crf) : 62);
    this.cfg.video.codec = c;
    if(c !== 'copy') this.cfg.quality.crf = crfOf(c, lvl);
    const same = this.base && this.base.video.codec === c;
    this.cfg.video.speed = same ? this.base.video.speed : m.codecs[c].speed_def;
    this.cfg.video.extra = same ? this.base.video.extra : '';
    this.cfg.video.hw = c === 'hw' ? ((caps && caps.hw && (caps.hw.find(e => e.startsWith('hevc_')) || caps.hw[0])) || 'hevc_vaapi') : '';
    if(c === 'hw' && this.cfg.video.hw.startsWith('h264_')) this.cfg.video.bits = 8;
  }
  set(path, v){
    if(path === 'video.codec') return this.change_(() => this.setCodec(v));
    this.change_(() => {
      if(path === 'video.bits') v = +v;
      setPath(this.cfg, path, v);
      if(path === 'video.hw' && v.startsWith('h264_')) this.cfg.video.bits = 8;
      if(path === 'sound.mode' && v === 'copy'){ this.cfg.sound.channels = 'keep'; this.cfg.sound.kbps = 0; }
      if(path === 'quality.mode' && v === 'size' && !this.cfg.quality.size_gb){ const l = this.pred.last; this.cfg.quality.size_gb = l ? Math.max(0.1, Math.round(l.out_bytes / l.files / 1024 ** 3 * 10) / 10) : 5; }
      if(path === 'quality.mode' && v === 'bitrate' && !this.cfg.quality.kbps) this.cfg.quality.kbps = 3000;
    });
  }
  click(e){
    if(this.opts.readonly) return;
    const t = e.target, q = s => t.closest(s); let b;
    if((b = q('[data-preset]'))) this.selectPreset(b.dataset.preset);
    else if((b = q('[data-set]')) && b.tagName === 'BUTTON') this.set(b.dataset.set, b.dataset.v);
    else if((b = q('[data-reset]'))){
      this.change_(() => { const paths = b.dataset.reset === 'all' ? diffPaths(this.cfg, this.base) : b.dataset.reset.split(','); paths.forEach(p => setPath(this.cfg, p, getPath(this.base, p))); });
    }
    else if((b = q('[data-toggle]'))) this.toggle(b.dataset.toggle);
    else if(q('[data-compact]')){ this.compactOpen = !this.compactOpen; this.render(); this.pred.schedule(0); }
    else if(q('[data-saveas]')){ this.naming = true; this.render(); const i = $('[data-name]', this.el); if(i) i.focus(); }
    else if(q('[data-saveno]')){ this.naming = false; this.render(); }
    else if(q('[data-savenow]')) this.savePreset();
    else if(q('[data-probe]')) this.pred.startProbe();
    else if(q('[data-probe-cancel]')) this.pred.cancelProbe();
  }
  toggle(id){ this.open.has(id) ? this.open.delete(id) : this.open.add(id); this.render(); this.pred.paint(); this.pred.schedule(0); }
  key(e){
    const h = e.target.closest && e.target.closest('[data-toggle]');
    if(h && (e.key === 'Enter' || e.key === ' ')){ e.preventDefault(); this.toggle(h.dataset.toggle); }
    else if(e.key === 'Enter' && e.target.matches('[data-name]')){ e.preventDefault(); this.savePreset(); }
  }
  input(e){
    if(this.opts.readonly) return;
    const t = e.target;
    if(t.matches('[data-q]')){
      this.cfg.quality.crf = crfOf(this.cfg.video.codec, +t.value);
      const l = levelOf(this.cfg.video.codec, this.cfg.quality.crf);
      this.el.querySelectorAll('[data-b=crf]').forEach(s => { s.textContent = `${unitOf(this.cfg)} ${this.cfg.quality.crf}`; });
      this.el.querySelectorAll('[data-b=qword]').forEach(s => { s.textContent = qWord(l); });
      const chip = $('[data-chip=quality]', this.el); if(chip) chip.textContent = `${unitOf(this.cfg)} ${this.cfg.quality.crf}`;
      this.emit();
    } else if(t.matches('[data-sp]')){ this.cfg.video.speed = metaNow().codecs[this.cfg.video.codec].speeds[+t.value]; const v = $('.cv-sec[data-sec=speed] .val', this.el); if(v) v.textContent = this.cfg.video.speed; this.emit(); }
    else if(t.matches('[data-cmp]')) t.closest('.cv-cmp').style.setProperty('--p', t.value + '%');
    else if(t.matches('[data-text]')){ setPath(this.cfg, t.dataset.text, t.value.trim()); this.emit(); }
    else if(t.matches('[data-num]')){ setPath(this.cfg, t.dataset.num, +t.value || 0); this.emit(); }
  }
  change(e){
    if(this.opts.readonly) return;
    const t = e.target;
    if(t.matches('[data-q],[data-sp],[data-text],[data-num]')){ this.syncBase(); this.render(); }
    else if(t.matches('[data-numsel]')) this.change_(() => setPath(this.cfg, t.dataset.numsel, +t.value));
    else if(t.matches('select[data-set]')) this.set(t.dataset.set, t.value);
  }
  async savePreset(){
    const name = ($('[data-name]', this.el) || {}).value;
    if(!name || !name.trim()){ toast('Bitte einen Namen eingeben.', true); return; }
    try{
      const p = await api('/api/convert/presets', 'POST', {name: name.trim(), cfg: strip(this.cfg)});
      await reloadMeta(); this.naming = false; this.cfg.origin = p.id; this.syncBase(); this.render(); this.emit(); toast(`Preset „${p.name}“ gespeichert ✓`);
    }catch{ /* api() zeigt den Fehler an */ }
  }
  destroy(){
    this.dead = true; this.pred.destroy();
    for(const [t, f] of Object.entries(this.handlers)) this.el.removeEventListener(t, f);
    this.el.innerHTML = '';
  }
}

export function mountConvertEditor(el, value, opts = {}){
  const ed = new Editor(el, value, opts);
  return {
    get: () => (ed.cfg ? strip(ed.cfg) : null),
    set: v => { ed.value = v; ed.init(v); },
    refresh: () => { ed.pred.schedule(0); },
    setFiles: files => { ed.opts.files = files || []; ed.render(); ed.pred.schedule(0); },
    destroy: () => ed.destroy(),
  };
}
