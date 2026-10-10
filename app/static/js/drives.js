// Laufwerke aller Rechner: Auswahl, Chips in der Kopfzeile, Fortschrittsfeld. Registriert die Ansicht „Laufwerke“.
import { $, S, delegate, esc, fmtB, fmtD, hostName, pad, setHtml, ui } from './core.js';
import { syncSpin } from './jobs-list.js';
import { buildLayout, isActive, onState, registerPanel, registerView, rerender } from './registry.js';

export const driveUrl = (d, act) => d.host ? `/api/peer/${d.host}/drives/${d.id}/${act}` : `/api/drives/${d.id}/${act}`;
export const nowOf = d => (d.host && d._now) ? d._now : S.now;
export const outDir = d => (d.host && d._out && d._out.dir) || S.output.dir;
export const dkey = d => (d.host || '') + '|' + d.id;
export function allDrives(){          // Laufwerke aller Rechner: zuerst die eigenen, dann die der anderen
  const list = S.drives.map(d => ({...d, host: ''}));
  for(const p of (S.peers||[])) if(p.reachable) (p.drives||[]).forEach(d => list.push({...d, host: p.name, _now: p.now, _out: p.output}));
  return list;
}
let selDrive = null;
export const setSelDrive = k => { selDrive = k; };
export function curDrive(){
  if(!S) return null;
  const all = allDrives();
  let d = all.find(x => dkey(x) === selDrive);
  if(!d){ d = all.find(x => !x.host && (x.job || x.disc)) || all.find(x => x.job || x.disc) || all[0] || null; selDrive = d ? dkey(d) : null; }
  return d;
}
const STATUSTXT = { empty:'Laufwerk verbunden', open:'Schublade offen', loading:'Laufwerk lädt …', ready:'Disc erkannt', unknown:'…' };
function renderChips(){
  const cur = curDrive(), all = allDrives();
  if(!all.length){ setHtml($('#drivechips'), '<div class="drive"><span>Kein Laufwerk</span><span class="pill warnpill">● nicht verbunden</span></div>'); return; }
  setHtml($('#drivechips'), all.map(d => {
    const busy = d.job ? (d.job.kind==='scan' ? 'analysiert …' : d.job.kind==='backup' ? 'Backup läuft' : 'rippt …') : null;
    const cls = busy ? 'busypill' : (d.status==='open'||d.status==='loading') ? 'warnpill' : 'online';
    return `<button class="drive ${cur && dkey(d)===dkey(cur)?'sel':''}" data-drive="${esc(dkey(d))}">${esc(d.name)} <span class="pill">${esc(d.dev)}</span>${d.host ? `<span class="pill">${esc(d.host)}</span>` : (all.some(x => x.host) ? `<span class="pill">${esc(hostName())}</span>` : '')}<span class="pill ${cls}">● ${busy || STATUSTXT[d.status] || '…'}</span></button>`;
  }).join(''));
}

function rate(d){        // geglättete Geschwindigkeit aus dem Fortschritt (Bytes/s)
  const j = d.job, done = (j.overall||0)*(j.bytes||0), now = nowOf(d), rk = dkey(d);
  let r = ui.rate[rk];
  if(!r || r.job !== j.started){ r = ui.rate[rk] = {job:j.started, t:now, b:done, v:0}; }
  else if(now - r.t >= 3){ const inst = Math.max(0,(done-r.b)/(now-r.t)); r.v = r.v ? r.v*0.6+inst*0.4 : inst; r.t = now; r.b = done; }
  return r.v;
}

function renderProgress(d){
  let title, line = '', lineErr = false, pct = null, bar = 0, indet = false, cancel = false, m = ['–','–','–','–'];
  const remote = d && d.host ? ` · auf ${d.host}` : '';
  if(!d){ title = 'Kein Laufwerk gefunden'; line = 'USB-Laufwerk anstecken – es erscheint hier automatisch.'; }
  else if(d.job && d.job.kind==='scan'){
    const j = d.job; title = 'Disc wird analysiert'; line = j.text || '…'; indet = !(j.total>0); pct = indet ? null : Math.round(j.total*100); bar = pct||0; cancel = true;
    m = ['–', fmtD(nowOf(d)-j.started), '–', '–'];
  } else if(d.job){
    const j = d.job, el = Math.max(1, nowOf(d)-j.started), ov = j.overall||0, v = rate(d);
    title = (d.disc && d.disc.name) || 'Rip';
    line = (j.title ? `Titel ${pad(j.index||0)} von ${j.count}: ${j.title}` : 'Starte …') + (j.text ? ` – ${j.text}` : '');
    pct = Math.round(ov*100); bar = pct; cancel = true;
    const eta = ov>0.01 ? ((v>0 && j.bytes) ? j.bytes*(1-ov)/v : el/ov-el) : 0;
    m = [v>0 ? `${fmtB(v)}/s` : '–', fmtD(el), eta ? fmtD(eta) : '–', j.kind==='backup' ? 'Backup' : `${j.index||0} / ${j.count}`];
  } else if(d.disc){
    title = d.disc.name || 'Unbenannte Disc'; lineErr = !!d.error;
    line = d.error || `${d.disc.type} · ${d.disc.titles.length} Titel – Titel auswählen und rippen`;
  } else if(d.error){ title = 'Analyse fehlgeschlagen'; line = d.error; lineErr = true; }
  else {
    title = {ready:'Disc erkannt', open:'Schublade ist offen', loading:'Laufwerk liest die Disc ein …'}[d.status] || 'Bitte eine DVD oder Blu-ray einlegen';
    line = {empty:'Sie wird automatisch erkannt und analysiert.', open:'Disc einlegen oder Schublade schließen.', ready:'Die Analyse startet gleich.'}[d.status] || '';
  }
  paintProgress({title, line: line + (line ? remote : ''), lineErr, pct, bar, indet, cancel, m});
}

// Das Fortschrittsfeld wird nur einmal aufgebaut; danach ändern sich Text, Balkenbreite und Knopf (Animationen laufen ungestört weiter).
const METS = [['◉','Geschwindigkeit'],['◴','Laufzeit'],['◷','Restzeit'],['▤','Titel']];
function buildProgress(el){
  el.innerHTML = `<div class="progress-title"><div><h1></h1><p></p></div><div class="percent"><span class="pct"></span><button class="secondary danger" data-act="cancel" hidden>Abbrechen</button></div></div>
    <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-label="Fortschritt"><div class="progress-fill"></div></div>
    <div class="metrics">${METS.map(([s,l]) => `<div class="metric"><span class="symbol">${s}</span><div><strong></strong><small>${l}</small></div></div>`).join('')}</div>`;
  el._r = {h1: el.querySelector('h1'), p: el.querySelector('p'), pctBox: el.querySelector('.percent'), pct: el.querySelector('.pct'), cancel: el.querySelector('[data-act=cancel]'),
           track: el.querySelector('.progress-track'), fill: el.querySelector('.progress-fill'), mv: [...el.querySelectorAll('.metric strong')]};
  el._v = {};
}
function paintProgress(v){
  const el = $('#prog'); if(!el.querySelector('.progress-title')) buildProgress(el);
  const r = el._r, last = el._v, put = (k, val, fn) => { if(last[k] !== val){ last[k] = val; fn(val); } };
  put('title', v.title, x => r.h1.textContent = x);
  put('line', v.line, x => r.p.textContent = x);
  put('err', v.lineErr, x => r.p.classList.toggle('err', x));
  put('box', (v.pct!==null || v.cancel) ? 1 : 0, x => r.pctBox.hidden = !x);
  put('pct', v.pct===null ? '' : v.pct + ' %', x => r.pct.textContent = x);
  put('cancel', v.cancel, x => r.cancel.hidden = !x);
  put('indet', v.indet, x => { r.track.classList.toggle('indet', x); if(x) syncSpin(r.fill, 1200); });
  put('bar', v.bar, x => { r.fill.style.width = x + '%'; r.track.setAttribute('aria-valuenow', x); });
  v.m.forEach((t, i) => put('m' + i, t, x => r.mv[i].textContent = x));
}

delegate('#drivechips', 'click', (e) => { const b = e.target.closest('[data-drive]'); if(b){ selDrive = b.dataset.drive; ui.sig.titles = ''; ui.sig.action = ''; rerender(); } });

onState(() => {
  renderChips();
  if(isActive('laufwerke') && $('#prog')) renderProgress(curDrive());
});

registerPanel({view:'laufwerke', slot:'left', order:10, id:'prog', html:'<section class="panel progress-panel" id="prog"></section>'});
registerView({id:'laufwerke', label:'Laufwerke', icon:'▣', order:10, mount(el){ buildLayout(el, 'laufwerke'); }});
