// Assistent „Einsortieren“: Ablauf, Zustand und Ereignisse (Darstellung: media-steps.js).
import { toast } from './core.js';
import { emit } from './registry.js';
import { baseName, esc, mapi } from './media-util.js';
import { stepDetect, stepEpisodes, stepPreview, stepResult, stepSearch, stepper } from './media-steps.js';

let dlg = null, w = null, poll = 0;
const RENDER = {1: stepDetect, 2: stepSearch, 3: stepEpisodes, 4: stepPreview, 5: stepResult};
const noteErr = t => `<div class="media-note err"><span class="media-ico">!</span><div>${esc(t)}</div></div>`;

function draw(){
  if(!dlg || !w) return;
  const keep = document.activeElement && document.activeElement.id, pos = keep ? document.activeElement.selectionStart : null;
  const s = w.loading ? {body: `<div class="empty">${esc(w.loading)}</div>`, footer: '<button type="button" class="secondary" data-act="close">Abbrechen</button>'}
    : w.fatal ? {body: noteErr(w.fatal), footer: '<button type="button" class="secondary" data-act="close">Schließen</button>'} : RENDER[w.step](w);
  dlg.innerHTML = `<div class="media-root"><div class="media-dlg"><header><h3>Einsortieren</h3><span class="pill">${w.title && w.step > 1 ? esc(w.title) : w.paths.length + (w.paths.length === 1 ? ' Datei' : ' Dateien')}</span><span class="sp"></span><button type="button" class="icon-btn" data-act="close" aria-label="Schließen">✕</button></header>
    ${stepper(w)}<div class="media-dbody">${s.body}</div><footer>${s.footer}</footer></div></div>`;
  const el = keep && dlg.querySelector('#' + CSS.escape(keep));
  if(el){ el.focus(); if(pos != null && el.setSelectionRange) try{ el.setSelectionRange(pos, pos); }catch{ /* Feldtyp ohne Auswahl */ } }
}

function ensureDialog(){
  if(dlg) return;
  dlg = document.createElement('dialog'); dlg.className = 'media-modal'; dlg.setAttribute('aria-label', 'Einsortieren');
  document.body.append(dlg);
  dlg.addEventListener('click', onClick); dlg.addEventListener('change', onChange);
  dlg.addEventListener('input', e => { const f = e.target.dataset.f; if(!w || !f) return; if(f.startsWith('s-')) w.s[f.slice(2)] = e.target.value; if(f.startsWith('m-')) onManual(e.target, false); });
  dlg.addEventListener('keydown', e => {
    if(e.key !== 'Enter') return;
    if(e.target.dataset.f === 's-q'){ e.preventDefault(); search(); }
    if(e.target.dataset.f === 's-imdb'){ e.preventDefault(); findImdb(); }
  });
  dlg.addEventListener('close', () => { w = null; clearTimeout(poll); });
}

// ---- Start
export async function openWizard(paths){
  ensureDialog();
  w = {paths, step: 1, hist: [], loading: 'Ich schaue mir die Dateien an …', det: null, tmdbOn: false, kind: 'movie', title: '', year: null, tmdb: null, imdb: '', chosen: null, season: 1, disc: null,
       start: {episode: 1, known: false, estimated: false}, items: [], skip: new Set(), epList: [], epError: '', s: {type: 'tv', q: '', year: '', imdb: '', results: null, error: ''}, manual: false,
       plan: null, planError: '', decisions: {}, op: null, history: null};
  if(!dlg.open) dlg.showModal();
  draw();
  try{ const res = await mapi('/detect', 'POST', {paths}, true); if(!w) return; apply(res); w.loading = ''; }
  catch(e){ if(w){ w.loading = ''; w.fatal = e.message; } }
  draw();
}

function apply(res){
  const d = res.detect;
  w.det = res; w.tmdbOn = res.tmdb.available; w.chosen = res.tmdb.chosen;
  w.kind = d.kind === 'series' ? 'series' : 'movie';
  w.title = w.chosen ? w.chosen.title : d.title; w.year = w.chosen ? w.chosen.year : d.year;
  w.tmdb = w.chosen ? w.chosen.tmdb : null; w.imdb = w.chosen ? w.chosen.imdb : '';
  w.season = d.season || 1; w.disc = d.disc;
  w.s.q = w.title || ''; w.s.year = w.year || ''; w.s.type = w.kind === 'series' ? 'tv' : 'movie';
  w.items = d.items.map(it => ({...it, size: it.size || 0}));
  if(d.kind === 'unknown') w.items.forEach((it, i) => { it.role = i === 0 ? 'movie' : 'extra'; });
  if(res.start) w.start = res.start;
  w.epList = res.episodes ? res.episodes.episode_list : [];
  w.epError = res.episodes ? res.episodes.error : '';
  if(res.episodes) applyAssigned(res.episodes.assigned);
}

function applyAssigned(assigned){
  const by = Object.fromEntries(assigned.map(a => [a.path, a]));
  for(const it of w.items){ const a = by[it.path]; if(a) Object.assign(it, {season: a.season, episodes: a.episodes, name: a.name, runtime: a.runtime, delta: a.delta}); }
}

async function reassign(){
  const items = w.items.filter(i => i.role === 'episode').map(i => ({path: i.path, role: 'episode', dur: i.dur}));
  try{
    const r = await mapi('/episodes', 'POST', {items, season: w.season, start: w.start.episode, tmdb: w.tmdb}, true);
    w.epList = r.episode_list; w.epError = r.error; applyAssigned(r.assigned);
  }catch(e){ w.epError = e.message; }
}

// ---- Anfrage für Plan und Ausführen
const stem = p => baseName(p).replace(/\.[^.]+$/, '');
function planReq(){
  const items = w.items.map(it => {
    if(w.skip.has(it.path)) return {path: it.path, role: 'skip', why: 'nicht mitgenommen'};
    if(w.kind === 'series'){
      if(it.role === 'episode') return {path: it.path, role: 'episode', season: it.season, episodes: it.episodes, name: it.name};
      return it.keep === 'extra' ? {path: it.path, role: 'extra', season: w.season, extra_kind: 'extras', name: stem(it.path)} : {path: it.path, role: 'skip', why: it.role === 'playall' ? 'Play-All' : 'ausgelassen'};
    }
    if(w.kind === 'extras' || it.role === 'extra') return {path: it.path, role: 'extra', extra_kind: 'extras', name: stem(it.path)};
    return {path: it.path, role: 'movie'};
  });
  return {kind: w.kind === 'series' ? 'series' : 'movie', title: w.title, year: w.year, tmdb: w.tmdb, imdb: w.imdb || null, poster: w.chosen ? w.chosen.poster : null,
          season: w.kind === 'series' ? w.season : null, disc: w.disc, items, decisions: w.decisions};
}

async function loadPlan(){
  w.loading = 'Vorschau wird berechnet …'; draw();
  try{ w.plan = await mapi('/plan', 'POST', planReq(), true); w.planError = ''; }catch(e){ w.plan = null; w.planError = e.message; }
  w.loading = '';
}

// ---- Navigation
async function go(step, push = true){
  if(push) w.hist.push(w.step);
  w.step = step;
  if(step === 4) await loadPlan();
  draw();
}
async function next(){
  if(w.step === 1){
    if((w.tmdbOn && !w.chosen && !w.manual) || !w.title) return go(2);
    return go(w.kind === 'series' ? 3 : 4);
  }
  if(w.step === 2){
    if(!(w.title || '').trim()){ toast('Bitte einen Titel eingeben', true); return; }
    if(w.year && !/^\d{4}$/.test(String(w.year))){ toast('Jahr bitte vierstellig eingeben', true); return; }
    if(w.kind === 'series'){ w.loading = 'Episoden werden zugeordnet …'; draw(); await reassign(); w.loading = ''; return go(3); }
    return go(4);
  }
  if(w.step === 3) return go(4);
}
function back(){
  const prev = w.hist.pop();
  if(prev === undefined) return;
  w.step = prev; draw();
}

// ---- Suche
async function search(){
  const s = w.s; if(!s.q.trim()) return;
  s.error = ''; s.results = null; w.loading = 'Suche …'; draw();
  try{ s.results = (await mapi(`/search?type=${s.type}&q=${encodeURIComponent(s.q.trim())}${/^\d{4}$/.test(s.year) ? '&year=' + s.year : ''}`, 'GET', null, true)).results; }catch(e){ s.error = e.message; }
  w.loading = ''; draw();
}
async function pick(x){
  w.loading = 'Details werden geholt …'; draw();
  let d = x;
  try{ d = {...x, ...(await mapi(`/title?type=${x.kind}&id=${x.tmdb}`, 'GET', null, true))}; }catch{ /* ohne IMDb-ID weiter */ }
  w.chosen = d; w.title = d.title; w.year = d.year; w.tmdb = d.tmdb; w.imdb = d.imdb || '';
  const was = w.kind;
  if(d.kind === 'tv' && was !== 'series'){ retag('series'); await reassign(); }
  else if(d.kind !== 'tv' && was === 'series') retag('movie');
  else if(d.kind === 'tv') await reassign();
  w.loading = '';
}
async function findImdb(){
  w.loading = 'Wird nachgeschlagen …'; draw();
  try{
    const r = await mapi('/find?imdb=' + encodeURIComponent(w.s.imdb.trim()), 'GET', null, true);
    if(r.result) await pick(r.result); else toast('Zu dieser IMDb-ID gibt es keinen Treffer', true);
  }catch(e){ toast(e.message, true); }
  w.loading = ''; draw();
}
function onManual(t, redraw){
  const f = t.dataset.f.slice(2), v = t.value.trim();
  if(f === 'title') w.title = v; else if(f === 'year') w.year = /^\d{4}$/.test(v) ? +v : (v || null); else if(f === 'imdb') w.imdb = v; else if(f === 'tmdb') w.tmdb = /^\d+$/.test(v) ? +v : null;
  if(w.chosen && (w.chosen.tmdb !== w.tmdb || w.chosen.title !== w.title)) w.chosen = null;
  const ex = dlg.querySelector('.media-ex');
  if(ex && !redraw){ const y = w.year ? ` (${esc(w.year)})` : '', t2 = esc(w.title);
    ex.innerHTML = '<span>Wird so heißen:</span> ' + (w.kind === 'series' ? `<em>${t2}${y}</em>/Season 01/<em>${t2} S01E01.mkv</em>` : `<em>${t2}${y}</em>/<em>${t2}${y}.mkv</em>`); }
}
/** Art gewechselt: Rollen der Dateien neu setzen (Serie: lange Titel = Folgen; Film: längster Titel = Hauptfilm). */
function retag(kind){
  w.kind = kind;
  if(kind === 'series'){
    const eps = w.items.filter(i => i.role !== 'playall' && i.dur >= 900 && i.dur <= 4800);
    w.items.forEach(i => { if(i.role !== 'playall') i.role = eps.includes(i) ? 'episode' : 'extra'; });
    let n = w.start.episode || 1;
    w.items.filter(i => i.role === 'episode').forEach(i => { Object.assign(i, {season: w.season, episodes: [n], name: (w.epList.find(e => e.n === n) || {}).name || '', runtime: null, delta: null}); n++; });
  }else{
    const main = w.items.filter(i => i.role !== 'playall').reduce((a, i) => (!a || i.dur > a.dur) ? i : a, null);
    w.items.forEach(i => { if(i.role !== 'playall') i.role = i === main ? 'movie' : 'extra'; });
  }
}

// ---- Ereignisse
async function onClick(e){
  const b = e.target.closest('[data-act]'); if(!b || b.disabled || !w) return;
  const [act, a, c] = b.dataset.act.split(':');
  if(act === 'close'){ dlg.close(); return; }
  if(act === 'next') return next();
  if(act === 'back') return back();
  if(act === 'goto') return go(+a);
  if(act === 'kind'){
    if(a === 'extras'){ w.kind = 'extras'; w.items.forEach(i => { i.role = 'extra'; }); }
    else{
      const was = w.kind; retag(a); w.s.type = a === 'series' ? 'tv' : 'movie';
      if(a === 'series' && was !== 'series') await reassign();
      if(w.chosen && ((a === 'series') !== (w.chosen.kind === 'tv'))){ w.chosen = null; w.tmdb = null; w.imdb = ''; }
    }
    return draw();
  }
  if(act === 'use-cand'){ const x = w.det.tmdb.candidates.find(c2 => String(c2.tmdb) === a); if(x) await pick(x); return draw(); }
  if(act === 's-type'){ w.s.type = a; w.s.results = null; return draw(); }
  if(act === 's-go') return search();
  if(act === 's-find') return findImdb();
  if(act === 's-pick'){ await pick(w.s.results[+a]); return draw(); }
  if(act === 'manual'){ w.manual = a === '1'; return draw(); }
  if(act === 'pa'){ w.items[+a].keep = c; return draw(); }
  if(act === 'conf'){ w.decisions[w.items[+a].path] = c === 'rename' ? 'rename' : 'skip'; return go(4, false); }
  if(act === 'history'){ w.hist.push(1); w.step = 5; w.op = null; w.history = null; draw(); return loadHistory(); }
  if(act === 'run') return run();
  if(act === 'undo') return undo(a);
}
function onChange(e){
  const t = e.target, f = t.dataset.f; if(!f || !w) return;
  const i = +t.dataset.i;
  if(f === 'take'){ if(t.checked) w.skip.delete(w.items[i].path); else w.skip.add(w.items[i].path); return; }
  if(f === 'season'){ const v = parseInt(t.value, 10); if(v >= 0) w.items[i].season = v; return draw(); }
  if(f === 'ep') return editEpisode(w.items[i], t.value);
  if(f === 'all-season'){
    const v = parseInt(t.value, 10); if(!(v >= 0)) return;
    w.season = v; w.start = {...w.start, episode: 1, known: false, estimated: false}; w.loading = 'Neu zuordnen …'; draw();
    return reassign().then(() => { w.loading = ''; draw(); });
  }
  if(f === 'start'){ const v = parseInt(t.value, 10); if(v > 0){ w.start = {...w.start, episode: v, known: false, estimated: false}; reassign().then(draw); } return; }
  if(f.startsWith('m-')) onManual(t, true);
}
function editEpisode(it, text){
  const m = text.trim().match(/^(\d+)(?:\s*[-–]\s*(\d+))?$/);
  if(!m || (m[2] && +m[2] < +m[1])){ toast('Episode als Zahl oder Bereich eingeben, z. B. 3 oder 3-4', true); return draw(); }
  const a = +m[1], z = +(m[2] || m[1]), look = n => w.epList.find(x => x.n === n) || {};
  it.episodes = Array.from({length: z - a + 1}, (_, k) => a + k);
  it.name = it.episodes.map(n => look(n).name).filter(Boolean).join(' & ');
  const rt = it.episodes.reduce((s, n) => s + (look(n).runtime || 0), 0);
  it.runtime = rt || null; it.delta = rt ? Math.round((it.dur / 60 - rt) * 10) / 10 : null;
  draw();
}

// ---- Ausführen, Verlauf, Rückgängig
async function run(){
  w.hist.push(w.step); w.step = 5; w.op = {status: 'running', copied: 0, total: 0, rows: []}; w.history = null; draw();
  try{ watch((await mapi('/run', 'POST', planReq())).id); }
  catch(err){ w.op = {status: 'failed', error: err.message, rows: []}; draw(); }
}
async function watch(id){
  try{
    const op = await mapi('/run/' + id, 'GET', null, true);
    if(!w) return;
    w.op = op; draw();
    if(op.status === 'running'){ poll = setTimeout(() => watch(id), 600); return; }
    emit('files-changed'); await loadHistory();
  }catch(e){ if(w){ w.op = {status: 'failed', error: e.message, rows: []}; draw(); } }
}
async function loadHistory(){ try{ const h = await mapi('/history', 'GET', null, true); if(w){ w.history = h; draw(); } }catch{ /* Liste bleibt leer */ } }
async function undo(id){
  try{
    const r = await mapi('/undo/' + id, 'POST', {});
    toast(r.ok ? 'Rückgängig gemacht ✓' : 'Nicht alles ließ sich zurücknehmen: ' + r.results.filter(x => !x.ok).map(x => x.why).join('; '), !r.ok);
    emit('files-changed'); await loadHistory();
  }catch{ /* Meldung als Toast */ }
}
