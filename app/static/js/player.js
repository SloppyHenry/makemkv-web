// Interner Player: Überlagerung (openPlayer) und eingebettet (mountPlayer), Anmeldung als primäre Bibliotheks-Aktion „Abspielen“.
// Markup und Stile 1:1 nach docs/mockups/paket-d.html (css/player.css); Steuerung in player-engine.js, Markup in player-ui.js.
import { esc, setHtml } from './core.js';
import { Engine, prefs } from './player-engine.js';
import { MODE_PILL, chaptersHtml, fmtT, ic, injectSprite, menuHtml, metaLine, notesHtml, playerHtml, windowHtml } from './player-ui.js';
import { registerLibraryAction } from './registry.js';

const PLAYABLE = /\.(mkv|mp4|m4v|mov|webm|m2ts|ts|mpe?g|avi|wmv)$/i;
const FAIL_TITLE = {409: 'Im Moment nicht möglich', 415: 'Nicht abspielbar', 404: 'Datei nicht gefunden'};
let overlay = null;

class View {
  /** host: Element, in dem das Klick-Handling läuft (Überlagerung: das Fenster, eingebettet: der Player selbst) */
  constructor(host, {alone}){
    this.host = host; this.alone = alone; this.root = host.classList.contains('player') ? host : host.querySelector('.player');
    this.q = s => this.root.querySelector(s); this.dismissed = new Set(); this.menu = ''; this.drag = null; this.shown = {};
    this.e = new Engine(this.q('video'), k => this.paint(k));
    host.addEventListener('click', ev => this.click(ev));
    host.addEventListener('dblclick', ev => this.dbl(ev));
    this.seekEl = this.q('.player-seek');
    this.seekEl.addEventListener('pointerdown', ev => this.seekDown(ev));
    this.seekEl.addEventListener('pointermove', ev => this.seekMove(ev));
    this.seekEl.addEventListener('pointerup', ev => this.seekUp(ev));
    this.seekEl.addEventListener('pointercancel', () => { this.drag = null; this.seekEl.classList.remove('drag'); });
    this.q('.player-vol input').addEventListener('input', ev => { const v = this.e.v; v.volume = ev.target.value / 100; v.muted = v.volume === 0; });
    this.root.addEventListener('mousemove', () => this.wake());
    this.root.addEventListener('fullscreenchange', () => this.paint('full'));
    this.root.addEventListener('webkitfullscreenchange', () => this.paint('full'));
    this.onDocDown = ev => { if(this.menu && !ev.target.closest('.player-menu, [data-a^="m:"]')) this.closeMenu(); };
    document.addEventListener('pointerdown', this.onDocDown);
    if(alone){ this.root.addEventListener('keydown', ev => this.key(ev)); this.root.addEventListener('pointerdown', () => this.root.focus({preventScroll: true})); }
  }
  open(path, start){ this.e.open(path, start); }
  destroy(){ this.e.destroy(); document.removeEventListener('pointerdown', this.onDocDown); clearTimeout(this.idle); }

  // ---------------------------------------------------------------- Darstellung
  paint(kind){
    const e = this.e, info = e.info, v = e.v, dur = e.duration();
    if(kind === 'info' || kind === 'subs' || kind === 'state') this.paintStatic(kind);
    const state = e.state === 'playing' && v.paused ? 'paused' : e.state;
    this.root.dataset.state = state;
    const wt = this.q('.player-waittext'); if(wt.textContent !== e.wait) wt.textContent = e.wait;
    const playing = state === 'playing' || (state === 'loading' && e.want);
    const pb = this.root.querySelector('.player-row [data-a=toggle]'), want = playing ? 'pause' : 'play';
    if(pb.dataset.i !== want){ pb.dataset.i = want; pb.innerHTML = ic(want); pb.setAttribute('aria-label', playing ? 'Pause' : 'Wiedergabe'); }
    const t = this.drag != null ? this.drag * dur : e.time();
    const track = this.q('.player-track');
    track.style.setProperty('--p', dur ? Math.min(1, t / dur) : 0); track.style.setProperty('--b', dur ? Math.min(1, e.bufferedEnd() / dur) : 0);
    const tt = `<b>${fmtT(t)}</b> / ${fmtT(dur)}`; setHtml(this.q('.player-time'), tt);
    this.seekEl.setAttribute('aria-valuenow', Math.round(t)); this.seekEl.setAttribute('aria-valuemax', Math.round(dur)); this.seekEl.setAttribute('aria-valuetext', `${fmtT(t)} von ${fmtT(dur)}`);
    const cue = e.sub >= 0 && info ? e.cueNow() : '';
    if(this.shown.cue !== cue){ this.shown.cue = cue; const s = this.q('.player-subs'); s.textContent = ''; if(cue){ const sp = document.createElement('span'); sp.textContent = cue; s.append(sp); } }
    const vol = this.q('.player-vol input'), mu = v.muted || v.volume === 0, val = mu ? 0 : Math.round(v.volume * 100);
    if(+vol.value !== val) vol.value = val;
    const mb = this.q('[data-a=mute]'), mi = mu ? 'mute' : 'vol'; if(mb.dataset.i !== mi){ mb.dataset.i = mi; mb.innerHTML = ic(mi); mb.setAttribute('aria-label', mu ? 'Ton an' : 'Ton aus'); }
    const full = this.isFull(), fb = this.q('[data-a=full]'), fi = full ? 'unfull' : 'full'; if(fb.dataset.i !== fi){ fb.dataset.i = fi; fb.innerHTML = ic(fi); }
    this.q('[data-a="m:tracks"]').classList.toggle('on', e.sub >= 0 || this.menu === 'tracks');
    this.q('[data-a="m:mode"]').classList.toggle('on', this.menu === 'mode');
    const ci = info ? e.chapterIndex() : -1;
    if(ci !== this.shown.chap){ this.shown.chap = ci; this.paintChapters(); }
  }
  paintStatic(kind){
    const e = this.e, info = e.info;
    if(info && this.shown.info !== info.path + '|' + info.chapters.length){
      this.shown.info = info.path + '|' + info.chapters.length;
      const dur = info.duration;
      this.q('.player-ticks').innerHTML = info.chapters.slice(1).map(c => `<i style="--at:${dur ? c.start / dur : 0}"></i>`).join('');
      this.q('[data-a="m:chapters"]').hidden = !info.chapters.length;
      const win = this.host.classList.contains('player-window');
      if(win){ this.host.classList.toggle('nochapters', !info.chapters.length); this.paintChapters(); }
      this.paintHead();
    }
    if(info) this.paintHead();
    const notes = this.notes();
    setHtml(this.q('.player-notes'), notesHtml(notes));
    const f = this.q('.player-fail');
    if(e.state === 'error' && e.err){
      const st = e.err.status;
      setHtml(f, `<b>${esc(FAIL_TITLE[st] || 'Wiedergabe nicht möglich')}</b>${esc(e.err.text)}<br>${[404, 415].includes(st) ? '' : '<button type="button" class="secondary" data-a="retry">Erneut versuchen</button> '}${e.path ? `<a class="secondary" href="/api/download?path=${encodeURIComponent(e.path)}">Datei herunterladen</a>` : ''}`);
    } else if(f.dataset.h) setHtml(f, '');
    if(this.menu && kind !== 'state') this.renderMenu();
  }
  paintHead(){
    const info = this.e.info, h = this.host.querySelector('.player-head'); if(!h) return;
    const p = this.e.plan || info.plan, dir = info.path.includes('/') ? info.path.slice(0, info.path.lastIndexOf('/')) : '';
    setHtml(h.querySelector('h3'), esc(info.name)); setHtml(h.querySelector('.sub'), esc(metaLine(info, dir)));
    setHtml(h.querySelector('.pillhost'), MODE_PILL[p.mode] || '');
  }
  paintChapters(){
    const e = this.e, aside = this.host.querySelector('.player-chapters');
    if(aside && e.info){
      aside.hidden = !e.info.chapters.length || prefs.get().chap === false;
      setHtml(aside, aside.hidden ? '' : chaptersHtml(e.info.chapters, this.shown.chap));
    }
    if(this.menu === 'chapters') this.renderMenu();
  }
  notes(){
    const e = this.e, info = e.info, n = []; if(!info) return n;
    const p = e.plan || info.plan, reasons = p.reasons || [], busy = info.busy || {};
    if(info.locked) n.push({id: 'lock', k: 'warn', t: `<b>Diese Datei ${esc(info.locked.reason)}</b>${info.locked.by ? ` (Rechner ${esc(info.locked.by)})` : ''}. Du kannst sie ansehen; sie kann sich dabei noch ändern oder verschwinden.`});
    if(p.mode === 'transcode') n.push({id: 'tr', k: 'warn', t: `<b>Wird umgewandelt</b> – ${esc(reasons.join(' '))} Das braucht Rechenleistung dieses Rechners.${busy.busy ? ` Gerade läuft ${busy.rip ? 'ein Rip' : busy.convert ? 'eine Konvertierung' : 'eine Übertragung'}: ffmpeg nutzt nur wenig Leistung mit niedrigster Priorität, die Wiedergabe kann ruckeln.` : ''}`});
    else if(p.mode === 'remux') n.push({id: 'rx', t: `<b>Remux:</b> Das Video wird unverändert durchgereicht. ${esc(reasons.filter(r => r.startsWith('Ton')).join(' '))} Springen im nicht Gepufferten startet kurz neu.`});
    if(e.subLoading) n.push({id: 'sl', t: 'Untertitel werden geladen … (bei großen Dateien am Netzlaufwerk kann das etwas dauern)'});
    if(e.subErr) n.push({id: 'se', k: 'warn', t: esc(e.subErr)});
    return n.filter(x => !this.dismissed.has(x.id));
  }

  // ---------------------------------------------------------------- Menüs
  renderMenu(){
    this.root.querySelectorAll('.player-menu').forEach(m => m.remove());
    if(!this.menu || !this.e.info) return;
    this.root.insertAdjacentHTML('beforeend', menuHtml(this.menu, this.e));
  }
  openMenu(k){ this.menu = this.menu === k ? '' : k; this.renderMenu(); this.paint('menu'); }
  closeMenu(){ if(!this.menu) return false; this.menu = ''; this.renderMenu(); this.paint('menu'); return true; }

  // ---------------------------------------------------------------- Bedienung
  isFull(){ return (document.fullscreenElement || document.webkitFullscreenElement) === this.root; }
  toggleFull(){
    if(this.isFull()){ (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
    const r = this.root, f = r.requestFullscreen || r.webkitRequestFullscreen;
    if(f) Promise.resolve(f.call(r)).catch(() => {}); else if(this.e.v.webkitEnterFullscreen) this.e.v.webkitEnterFullscreen();     // iPhone: nur das Video
  }
  wake(){ this.root.classList.remove('idle'); clearTimeout(this.idle); if(this.isFull()) this.idle = setTimeout(() => { if(this.e.state === 'playing') this.root.classList.add('idle'); }, 3000); }
  click(ev){
    const a = ev.target.closest('[data-a]'), e = this.e;
    if(!a){ if(ev.target.closest('.player-stage') && !ev.target.closest('.player-fail, .player-notes, .player-menu')){ this.closeMenu() || e.toggle(); } return; }
    const [k, arg] = a.dataset.a.split(/:(.*)/);
    if(k === 'toggle') e.toggle();
    else if(k === 'back') e.skip(-10);
    else if(k === 'fwd') e.skip(10);
    else if(k === 'mute'){ e.v.muted = !e.v.muted; if(!e.v.muted && e.v.volume === 0) e.v.volume = 0.5; }
    else if(k === 'full') this.toggleFull();
    else if(k === 'retry') e.retry();
    else if(k === 'close') this.onClose && this.onClose();
    else if(k === 'overlay'){ const t = e.time(), p = e.path; e.destroy(); openPlayer(p, {start: t}); }
    else if(k === 'note-x'){ this.dismissed.add(a.closest('.player-note').dataset.id); this.paint('state'); }
    else if(k === 'm'){
      if(arg === 'chapters' && this.host.querySelector('.player-chapters')){ prefs.set({chap: prefs.get().chap === false}); this.paintChapters(); }
      else this.openMenu(arg);
    }
    else if(k === 'audio'){ this.closeMenu(); e.setAudio(+arg); }
    else if(k === 'sub'){ this.closeMenu(); e.setSub(+arg); }
    else if(k === 'speed'){ e.setSpeed(+arg); this.renderMenu(); }
    else if(k === 'chap'){ this.closeMenu(); e.seek(e.info.chapters[+arg].start); }
  }
  dbl(ev){
    if(!ev.target.closest('.player-stage') || ev.target.closest('.player-fail, .player-notes')) return;
    if(matchMedia('(pointer:coarse)').matches){ const r = this.q('.player-stage').getBoundingClientRect(); this.e.skip(ev.clientX < r.left + r.width / 2 ? -10 : 10); }
    else this.toggleFull();
  }
  frac(ev){ const r = this.q('.player-track').getBoundingClientRect(); return Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)); }
  seekDown(ev){ if(!this.e.info) return; this.seekEl.setPointerCapture(ev.pointerId); this.seekEl.classList.add('drag'); this.drag = this.frac(ev); this.paint('tick'); }
  seekMove(ev){
    const f = this.frac(ev), e = this.e; if(!e.info) return;
    if(this.drag != null){ this.drag = f; this.paint('tick'); }
    const t = f * e.duration(), ch = e.info.chapters.filter(c => c.start <= t).pop(), tip = this.q('.player-tip');
    tip.style.setProperty('--x', f); tip.innerHTML = `${fmtT(t)}${ch ? `<small>${esc(ch.title || 'Kapitel ' + (e.info.chapters.indexOf(ch) + 1))}</small>` : ''}`;
  }
  seekUp(ev){ if(this.drag == null) return; const f = this.frac(ev); this.drag = null; this.seekEl.classList.remove('drag'); this.e.seek(f * this.e.duration()); }
  key(ev){
    const e = this.e, t = ev.target;
    if(!e.info || ev.ctrlKey || ev.metaKey || ev.altKey || t.tagName === 'INPUT' || t.tagName === 'SELECT') return;
    const k = ev.key, step = ev.shiftKey ? 60 : 10; let used = true;
    if(k === ' ' || k === 'k' || k === 'K'){ if(t.tagName === 'BUTTON' && k === ' ') return; e.toggle(); }
    else if(k === 'ArrowLeft') e.skip(-step); else if(k === 'ArrowRight') e.skip(step);
    else if(k === 'ArrowUp' || k === 'ArrowDown'){ const v = e.v; v.muted = false; v.volume = Math.min(1, Math.max(0, v.volume + (k === 'ArrowUp' ? 0.05 : -0.05))); }
    else if(k === 'm' || k === 'M') e.v.muted = !e.v.muted;
    else if(k === 'f' || k === 'F') this.toggleFull();
    else if(k === 'c' || k === 'C'){ if(e.sub >= 0){ this.lastSub = e.sub; e.setSub(-1); } else { const s = this.lastSub ?? e.info.subs.find(x => x.supported)?.i; if(s != null) e.setSub(s); } }
    else if(k === 'a' || k === 'A'){ const n = e.info.audio.length; if(n > 1) e.setAudio((e.audioIndex() + 1) % n); }
    else if(k === 'b' || k === 'B' || k === 'n' || k === 'N'){
      const cs = e.info.chapters, i = e.chapterIndex(), back = k.toLowerCase() === 'b';
      if(cs.length){ const j = back ? (e.time() - cs[Math.max(0, i)].start > 3 ? i : i - 1) : i + 1; if(j >= 0 && j < cs.length) e.seek(cs[j].start); else if(back) e.seek(0); }
    }
    else if(/^[0-9]$/.test(k)) e.seek(e.duration() * (+k / 10));
    else if(k === '?') this.openMenu('keys');
    else if(k === 'Escape'){ if(!this.closeMenu() && this.onClose && !this.isFull()) this.onClose(); }
    else used = false;
    if(used){ ev.preventDefault(); ev.stopPropagation(); }
    this.wake();
  }
}

// ------------------------------------------------------------------ öffentliche Funktionen
export function openPlayer(path, {start = 0} = {}){
  injectSprite(); closePlayer();
  const prev = document.activeElement;
  document.body.insertAdjacentHTML('beforeend', windowHtml());
  const el = document.body.lastElementChild, win = el.querySelector('.player-window'), view = new View(win, {alone: false});
  const onKey = ev => { if(ev.key === 'Tab' && !win.contains(document.activeElement)){ ev.preventDefault(); win.focus(); return; } view.key(ev); }, onHash = () => closePlayer();
  const prevOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
  document.addEventListener('keydown', onKey, true); window.addEventListener('hashchange', onHash);
  el.addEventListener('click', ev => { if(ev.target === el) closePlayer(); });
  view.onClose = closePlayer;
  overlay = {el, view, destroy(){
    view.destroy(); document.removeEventListener('keydown', onKey, true); window.removeEventListener('hashchange', onHash);
    document.body.style.overflow = prevOverflow; el.remove(); if(prev && prev.focus && document.contains(prev)) prev.focus({preventScroll: true});
  }};
  win.focus({preventScroll: true});
  view.open(path, start);
  return overlay;
}
export function closePlayer(){ if(overlay){ const o = overlay; overlay = null; o.destroy(); } }

/** Player in ein Element einbetten (Detailbereich der Bibliothek). Rückgabe: {destroy(), engine}. */
export function mountPlayer(el, path, {start = 0} = {}){
  injectSprite(); el.classList.add('player-embed'); el.innerHTML = playerHtml(true);
  const view = new View(el.querySelector('.player'), {alone: true});
  view.open(path, start);
  return {engine: view.e, destroy(){ view.destroy(); el.innerHTML = ''; }};
}

registerLibraryAction({id: 'play', label: 'Abspielen', icon: '▶', primary: true, when: fs => fs.length === 1 && PLAYABLE.test(fs[0].path), run: fs => openPlayer(fs[0].path)});
export const playable = path => PLAYABLE.test(path);
window.addEventListener('beforeunload', () => overlay && overlay.view.e.beacon());
