// Player: Wiedergabe-Steuerung für ein <video> (Probe, Sitzung, Neustart beim Suchen, Untertitel, Wiederaufnahme). Keine Darstellung.
// Server: app/player.py (/api/player/…). Konzept: docs/agenten/status-paket-d.md
import { fmtT } from './player-ui.js';

const KEY = 'player.v1';
const store = { get(){ try{ return JSON.parse(localStorage.getItem(KEY) || '{}'); }catch{ return {}; } }, set(o){ try{ localStorage.setItem(KEY, JSON.stringify({...store.get(), ...o})); }catch{} } };
export const prefs = store;

let capsCache = null;
export function detectCaps(){
  if(capsCache) return capsCache;
  const v = document.createElement('video'), ok = t => !!v.canPlayType(t), c = new Set(['aac']);
  const add = (n, t) => { if(ok(t)) c.add(n); };
  add('mkv', 'video/x-matroska;codecs="avc1.640028,mp4a.40.2"'); add('h264', 'video/mp4;codecs="avc1.640028"'); add('h264_10', 'video/mp4;codecs="avc1.6e0028"');
  add('hevc', 'video/mp4;codecs="hvc1.1.6.L120.B0"'); add('hevc10', 'video/mp4;codecs="hvc1.2.4.L120.B0"'); add('vp9', 'video/mp4;codecs="vp09.00.10.08"'); add('av1', 'video/mp4;codecs="av01.0.05M.08"');
  add('opus', 'video/mp4;codecs="opus"'); add('flac', 'video/mp4;codecs="flac"'); add('ac3', 'video/mp4;codecs="ac-3"'); add('eac3', 'video/mp4;codecs="ec-3"');
  return capsCache = c;
}

const detailText = d => typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg || JSON.stringify(x)).join('; ') : 'Unbekannter Fehler';
async function call(url, body){
  const r = await fetch(url, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined);
  const j = await r.json().catch(() => ({}));
  if(!r.ok) throw Object.assign(new Error(detailText(j.detail) || r.statusText), {status: r.status});
  return j;
}

function parseVtt(text){
  const t = s => { const p = s.trim().replace(',', '.').split(':').map(Number); return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1]; };
  const out = [];
  for(const blk of text.replace(/\r/g, '').split(/\n\n+/)){
    const lines = blk.split('\n'), i = lines.findIndex(l => l.includes('-->'));
    if(i < 0) continue;
    const [a, b] = lines[i].split('-->');
    const txt = lines.slice(i + 1).join('\n').replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim();
    if(txt) out.push({a: t(a), b: t(b.trim().split(' ')[0]), t: txt});
  }
  return out.sort((x, y) => x.a - y.a);
}

export class Engine {
  constructor(video, onUpdate){
    this.v = video; this.up = onUpdate; this.client = Math.random().toString(36).slice(2, 10); this.caps = detectCaps();
    this.info = null; this.sess = null; this.plan = null; this.start = 0; this.native = false; this.gen = 0; this.state = 'loading'; this.wait = 'Starte …';
    this.audio = null; this.sub = -1; this.cues = []; this.cueCache = new Map(); this.subLoading = false; this.speed = 1; this.err = null; this.fails = []; this.want = true; this.dead = false;
    const p = store.get(); video.volume = p.vol ?? 1; video.muted = !!p.muted;
    const on = (e, f) => video.addEventListener(e, f);
    on('playing', () => { this.err = null; this.set('playing'); });
    on('pause', () => { if(!video.ended && this.state === 'playing') this.set('paused'); });
    on('waiting', () => { if(this.state === 'playing') this.set('loading', 'Lädt …'); });
    on('canplay', () => { if(this.state === 'loading' && !this.starting && !video.paused) this.set('playing'); });
    on('timeupdate', () => this.up('tick'));
    on('volumechange', () => { store.set({vol: video.volume, muted: video.muted}); this.up('vol'); });
    on('ended', () => { if(!this.native && this.info && this.time() < this.info.duration - 3) this.recover('Verbindung beendet'); else this.set('ended'); });
    on('error', () => { if(this.src) this.recover('Wiedergabefehler'); });
    this.beat = setInterval(() => this.up('tick'), 250);
    this.onHide = () => this.beacon(); window.addEventListener('pagehide', this.onHide);
  }
  set(s, wait){ if(this.dead) return; this.state = s; if(wait) this.wait = wait; this.up('state'); }
  time(){ return (this.native ? 0 : this.start) + (this.v.currentTime || 0); }
  duration(){ return this.info ? this.info.duration : 0; }
  audioIndex(){ return this.audio ?? this.info.preferred.audio ?? 0; }
  chapterIndex(){ const t = this.time(), c = this.info ? this.info.chapters : []; let k = -1; c.forEach((x, i) => { if(x.start <= t + 0.2) k = i; }); return k; }
  bufferedEnd(){   // gepufferter Bereich um die aktuelle Stelle, absolut in Sekunden
    const v = this.v, base = this.native ? 0 : this.start;
    for(let i = 0; i < v.buffered.length; i++) if(v.currentTime >= v.buffered.start(i) - 0.3 && v.currentTime <= v.buffered.end(i) + 0.3) return base + v.buffered.end(i);
    return base + v.currentTime;
  }
  cueNow(){
    const t = this.time(), c = this.cues; let lo = 0, hi = c.length - 1, hit = null;
    while(lo <= hi){ const m = (lo + hi) >> 1; if(c[m].a > t) hi = m - 1; else { if(c[m].b > t) hit = c[m]; lo = m + 1; } }
    for(let i = Math.max(0, lo - 3); i < Math.min(c.length, lo + 1); i++) if(c[i].a <= t && c[i].b > t) hit = c[i];   // überlappende Zeilen
    return hit ? hit.t : '';
  }

  async open(path, start = 0){
    this.path = path; this.set('loading', 'Prüfe Datei …');
    try{
      this.info = await call(`/api/player/probe?path=${encodeURIComponent(path)}&caps=${[...this.caps].join(',')}`);
    }catch(e){ return this.fail(e); }
    if(this.dead) return;
    this.plan = this.info.plan; this.sub = this.info.preferred.sub ?? -1; this.up('info');
    if(!this.info.plan.ok) return this.fail(new Error(this.info.plan.error));
    this.startAt(start);
    if(this.sub >= 0) this.loadSub(this.sub);
  }
  async startAt(t, play = this.want, wait = 'Starte …'){
    const my = ++this.gen; this.starting = true; this.want = play; this.set('loading', wait);
    let r;
    try{
      r = await call('/api/player/session', {path: this.path, caps: [...this.caps].join(','), client: this.client, start: Math.max(0, t), audio: this.audio});
    }catch(e){ if(my === this.gen) this.fail(e); return; }
    if(my !== this.gen || this.dead) return;
    this.sess = r; this.plan = r.plan; this.start = r.start; this.native = r.native_seek; this.info.locked = r.locked; this.info.busy = r.busy; this.up('info');
    const v = this.v; this.src = r.url; v.src = r.url; v.playbackRate = this.speed; this.starting = false;
    if(this.native && t > 0) v.addEventListener('loadedmetadata', () => { v.currentTime = t; }, {once: true});
    if(play) v.play().catch(() => this.set('paused')); else this.set('paused');
  }
  fail(e){ this.err = {status: e.status || 0, text: e.message}; this.starting = false; this.src = ''; this.set('error'); }
  retry(){ this.err = null; if(!this.info || !this.info.plan.ok) return this.open(this.path); this.startAt(this.time()); }
  recover(why){   // Strom abgerissen (Leerlauf, Server-Neustart): an derselben Stelle neu starten, höchstens 3x in 30 s
    if(this.dead || this.starting) return;
    const now = Date.now(); this.fails = this.fails.filter(x => now - x < 30000); this.fails.push(now);
    if(this.fails.length > 3) return this.fail(new Error('Die Wiedergabe wurde mehrfach unterbrochen. Bitte erneut versuchen.'));
    this.startAt(this.time(), this.want, `${why} – setze bei ${fmtT(this.time())} fort …`);
  }

  toggle(){ if(this.state === 'error') return this.retry(); const v = this.v; if(v.paused || v.ended){ this.want = true; if(v.ended) this.seek(0); v.play().catch(() => {}); } else { this.want = false; v.pause(); } }
  seek(t){
    if(!this.info) return;
    t = Math.min(Math.max(0, t), Math.max(0, this.info.duration - 0.3));
    if(this.native){ this.v.currentTime = t; this.up('tick'); return; }
    const rel = t - this.start, v = this.v;
    for(let i = 0; i < v.buffered.length; i++) if(rel >= v.buffered.start(i) && rel <= v.buffered.end(i) - 0.5){ v.currentTime = rel; this.up('tick'); return; }
    this.startAt(t, this.want || !v.paused, `Starte bei ${fmtT(t)} …`);
  }
  skip(d){ this.seek(this.time() + d); }
  setAudio(i){ if(i === this.audioIndex()) return; this.audio = i; this.startAt(this.time(), this.want, 'Wechsle Tonspur …'); }
  setSpeed(s){ this.speed = s; this.v.playbackRate = s; this.up('state'); }
  async setSub(i){
    this.sub = i; this.cues = []; this.up('subs');
    if(i >= 0) await this.loadSub(i);
  }
  async loadSub(i){
    if(this.cueCache.has(i)){ this.cues = this.cueCache.get(i); this.up('subs'); return; }
    this.subLoading = true; this.up('subs');
    try{
      const r = await fetch(`/api/player/subtitle?path=${encodeURIComponent(this.path)}&index=${i}`);
      if(!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Untertitel nicht lesbar');
      const c = parseVtt(await r.text()); this.cueCache.set(i, c);
      if(this.sub === i) this.cues = c;
    }catch(e){ if(this.sub === i){ this.sub = -1; this.subErr = e.message; } }
    this.subLoading = false; this.up('subs');
  }
  beacon(){ try{ navigator.sendBeacon('/api/player/stop', new Blob([JSON.stringify({client: this.client})], {type: 'text/plain'})); }catch{} }
  destroy(){
    this.dead = true; this.gen++; clearInterval(this.beat); window.removeEventListener('pagehide', this.onHide);
    try{ this.v.pause(); this.v.removeAttribute('src'); this.v.load(); }catch{}
    this.beacon();
  }
}
