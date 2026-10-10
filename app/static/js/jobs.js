// Aufträge aller Rechner (Rippen, Konvertieren, Übertragen) als Liste mit Pause/Überspringen/Abbrechen.
import { $, S, api, baseName, dec, delegate, esc, fmtB, fmtD, hostName, setHtml, toast, ui } from './core.js';
import { onState, registerPanel } from './registry.js';

function clusterItems(){
  const items = [], me = hostName();
  (S.conversions||[]).forEach(o => items.push({k:'c', o, host:me, local:true}));
  (S.uploads||[]).forEach(o => items.push({k:'u', o, host:me, local:true}));
  S.drives.filter(d => d.job).forEach(d => items.push({k:'d', o:{...d.job, dev:d.dev, disc:d.disc && d.disc.name}, host:me, local:true}));
  for(const p of (S.peers||[])){
    if(!p.reachable) continue;
    (p.conversions||[]).forEach(o => items.push({k:'c', o, host:p.name, local:false}));
    (p.uploads||[]).forEach(o => items.push({k:'u', o, host:p.name, local:false}));
    if(Array.isArray(p.drives)) p.drives.filter(d => d.job).forEach(d => items.push({k:'d', o:{...d.job, dev:d.dev, disc:d.disc && d.disc.name}, host:p.name, local:false}));
    else (p.jobs||[]).forEach(o => items.push({k:'d', o:{...o, disc:o.title}, host:p.name, local:false}));
  }
  return items;
}
const itemActive = x => x.k==='d' ? true : x.k==='c' ? ['queued','running'].includes(x.o.status) : ['queued','copying','retry'].includes(x.o.status);
function jobSpeed(x){        // geglättete Geschwindigkeit eines Rips/Backups (Bytes/s) – auch für Aufträge anderer Rechner
  const o = x.o, key = x.host + ':' + o.dev, done = (o.overall||0)*(o.bytes||0), now = S.now;
  let r = ui.rate[key];
  if(!r || r.job !== o.started){ r = ui.rate[key] = {job:o.started, t:now, b:done, v:0}; }
  else if(now - r.t >= 3){ const inst = Math.max(0,(done-r.b)/(now-r.t)); r.v = r.v ? r.v*0.6+inst*0.4 : inst; r.t = now; r.b = done; }
  return r.v;
}
function jobRow(x, multi){
  const o = x.o; let cls = '', txt = 'Fertig', icon = '<span class="status-check">✓</span>', small = '', err = false, bar = '', btn = '';
  if(x.k === 'd'){
    const ov = o.kind==='scan' ? (o.total||0) : (o.overall||0), p = Math.round(ov*100), v = o.kind==='scan' ? 0 : jobSpeed(x), el = Math.max(1, S.now - o.started);
    const eta = ov > 0.01 ? ((v > 0 && o.bytes) ? o.bytes*(1-ov)/v : el/ov - el) : 0;
    cls = 'run'; txt = 'Läuft'; icon = '<span class="status-check run"></span>';
    const art = {rip:'Rippen', backup:'Disc-Backup', scan:'Analyse'}[o.kind] || o.kind;
    small = `${art} ${p} %${v>0 ? ` · ${fmtB(v)}/s` : ''} · Laufzeit ${fmtD(el)}${eta ? ` · Restzeit ${fmtD(eta)}` : ''}${o.kind==='rip' && o.count ? ` · Titel ${o.index||0}/${o.count}` : ''}`;
    bar = `<div class="mini-bar"><div style="width:${p}%"></div></div>`;
    const nm = (o.disc || o.title || 'Disc') + ' – ' + (o.kind==='backup' ? 'Backup' : o.kind==='scan' ? 'Analyse' : 'Rip');
    return `<div class="job">${icon}<div class="job-main"><strong title="${esc(nm)}">${esc(nm)}${multi ? ` <span class="st">${esc(x.host)}</span>` : ''}</strong><small>${esc(small)}</small>${bar}</div><span class="status ${cls}">${txt}</span></div>`;
  }
  if(x.k === 'c'){
    if(o.cancel && o.status !== 'cancelled'){ cls = 'wait'; txt = 'Bricht ab'; icon = '<span class="status-check wait">…</span>'; small = 'Wird abgebrochen …'; }
    else if(o.status === 'running' && o.paused){ const p = Math.round(o.pct*100); cls = 'wait'; txt = 'Pausiert'; icon = '<span class="status-check wait">⏸</span>';
      small = `Konvertierung pausiert bei ${p} % – mit „Fortsetzen“ geht es weiter`; bar = `<div class="mini-bar"><div style="width:${p}%"></div></div>`; }
    else if(o.status === 'running'){ const p = Math.round(o.pct*100); cls = 'run'; txt = 'Läuft'; icon = '<span class="status-check run"></span>';
      small = `Konvertierung ${p} %${o.fps ? ` · ${dec(o.fps.toFixed(1))} fps` : ''}${o.speed ? ` · ${dec(o.speed.toFixed(2))}× Echtzeit` : ''}${o.eta ? ` · Restzeit ${fmtD(o.eta)}` : ''}${o.mode ? ` · ${o.mode}` : ''}`;
      bar = `<div class="mini-bar"><div style="width:${p}%"></div></div>`; }
    else if(o.status === 'queued'){ cls = 'wait'; txt = 'Wartet'; icon = '<span class="status-check wait">…</span>'; small = `Konvertierung eingereiht${(x.local ? S.conv_paused : (S.peers||[]).some(p => p.name===x.host && p.conv_paused)) ? ' (pausiert)' : ''} · ${fmtB(o.size_in)}`; }
    else if(o.status === 'cancelled'){ cls = 'wait'; txt = 'Abgebrochen'; icon = '<span class="status-check skip">✕</span>'; small = o.origin === 'library' ? 'Abgebrochen · Original bleibt unverändert' : 'Abgebrochen · gerippte Datei verworfen'; }
    else if(o.status === 'done') small = `Konvertiert · ${fmtB(o.size_in)} → ${fmtB(o.size_out)} (−${Math.round((1-o.size_out/o.size_in)*100)} %)`;
    else if(o.status === 'skipped'){ icon = '<span class="status-check skip">✓</span>'; small = o.handed ? `An ${o.handed} übergeben` : 'Konvertierung übersprungen · Original'; if(o.handed) txt = 'Übergeben'; }
    else { cls = 'err'; txt = 'Fehler'; icon = '<span class="status-check err">!</span>'; small = o.error || 'Konvertierung fehlgeschlagen'; err = true; }
    if(o.origin === 'library') small += ' · Bibliothek';
    const h = x.local ? '' : esc(x.host);
    btn = ((o.status==='queued' || o.status==='running') && !o.cancel)
      ? `<span class="btns"><button class="secondary" data-skip="${o.id}" data-host="${h}" title="Ohne Konvertierung weiter: das Original bleibt liegen bzw. wird unverändert übertragen">Überspringen</button><button class="secondary danger" data-cancel="${o.id}" data-host="${h}" data-origin="${esc(o.origin||'')}" title="Auftrag ganz beenden">Abbrechen</button></span>`
      : `<button class="icon-btn" data-info="c:${o.id}:${esc(x.host)}" aria-label="Details">›</button>`;
  } else {
    const p = o.size ? Math.round(o.copied/o.size*100) : 0;
    if(o.status === 'copying'){ cls = 'run'; txt = 'Läuft'; icon = '<span class="status-check run"></span>';
      small = `Übertragung ${p} % · ${fmtB(o.copied)} / ${fmtB(o.size)}${o.speed>0 ? ` · ${fmtB(o.speed)}/s` : ''}${o.eta>1 ? ` · noch ${fmtD(o.eta)}` : ''}`; bar = `<div class="mini-bar"><div style="width:${p}%"></div></div>`; }
    else if(o.status === 'queued'){ cls = 'wait'; txt = 'Wartet'; icon = '<span class="status-check wait">…</span>'; small = `Übertragung eingereiht · ${fmtB(o.size)}`; }
    else if(o.status === 'retry'){ cls = 'err'; txt = 'Neuer Versuch'; icon = '<span class="status-check err">!</span>'; small = o.error || 'Übertragung fehlgeschlagen'; err = true; }
    else if(o.status === 'error'){ cls = 'err'; txt = 'Fehler'; icon = '<span class="status-check err">!</span>'; small = o.error || 'Übertragung fehlgeschlagen'; err = true; }
    else small = `${fmtB(o.size)} · Zielverzeichnis${o.replace ? ' · ersetzt Original' : ''}`;
    btn = `<button class="icon-btn" data-info="u:${o.id}:${esc(x.host)}" aria-label="Details">›</button>`;
  }
  const name = baseName(o.name) + (x.k==='u' ? ' übertragen' : '');
  return `<div class="job">${icon}<div class="job-main"><strong title="${esc(o.name)}">${esc(name)}${multi ? ` <span class="st">${esc(x.host)}</span>` : ''}</strong><small class="${err?'err':''}">${esc(small)}</small>${bar}</div><span class="status ${cls}">${txt}</span>${btn}</div>`;
}
function renderJobs(){
  const multi = (S.peers||[]).length > 0, items = clusterItems();
  items.sort((a,b) => (itemActive(b)-itemActive(a)) || (itemActive(a) ? (a.host===b.host ? (a.o.id||0)-(b.o.id||0) : a.host.localeCompare(b.host)) : (b.o.t||0)-(a.o.t||0)));
  const h = items.slice(0,14).map(x => jobRow(x, multi)).join('') || '<div class="empty">Keine Aufträge.</div>';
  document.querySelectorAll('[data-joblist]').forEach(e => { if(!e.closest('[hidden]')) setHtml(e, h); });
  const dest = $('#jobsDest');
  if(dest) dest.textContent = multi ? `Ziel: ${S.output.dir} · alle Rechner` : `Ziel: ${S.output.dir}`;
  const aktiv = (S.conversions||[]).some(c => c.status==='queued' || c.status==='running'), p = !!S.conv_paused;
  const hatPeers = (S.peers||[]).length > 0;
  document.querySelectorAll('.idle-chip').forEach(c => { c.hidden = !hatPeers; c.textContent = S.idle ? '✓ bereit zum Herunterfahren' : 'Arbeit läuft'; c.className = 'pill idle-chip ' + (S.idle ? 'online' : 'busypill'); });
  document.querySelectorAll('.pause-btn').forEach(b => { b.hidden = !(aktiv || p); b.textContent = p ? '▶ Fortsetzen' : '⏸ Pausieren'; b.dataset.paused = p ? '1' : ''; });
  const pp = (S.peers||[]).filter(x => x.reachable && ((x.conversions||[]).some(c => ['queued','running'].includes(c.status)) || x.conv_paused))
    .map(x => `<button class="secondary" data-ppause="${esc(x.name)}" data-paused="${x.conv_paused ? '1' : ''}">${x.conv_paused ? '▶' : '⏸'} ${esc(x.name)}</button>`).join('');
  document.querySelectorAll('.peerpause').forEach(e => { e.hidden = !pp; setHtml(e, pp); });
}
function jobsClick(e){
  const sk = e.target.closest('[data-skip]');
  if(sk){
    if(confirm('Konvertierung abbrechen? Das Original bleibt unverändert bzw. wird unverändert übertragen.')){
      const h = sk.dataset.host; api(h ? `/api/peer/${h}/conversions/${sk.dataset.skip}/skip` : `/api/conversions/${sk.dataset.skip}/skip`);
    }
    return;
  }
  const cn = e.target.closest('[data-cancel]');
  if(cn){
    const lib = cn.dataset.origin === 'library';
    const msg = lib ? 'Konvertierung abbrechen? Das Original bleibt unverändert, der Auftrag wird beendet.'
      : 'Auftrag abbrechen? Die frisch gerippte Datei wird VERWORFEN und müsste neu gerippt werden.\n\n(„Überspringen“ überträgt sie dagegen unkonvertiert ins Ziel.)';
    if(confirm(msg)){ const h = cn.dataset.host; api(h ? `/api/peer/${h}/conversions/${cn.dataset.cancel}/cancel` : `/api/conversions/${cn.dataset.cancel}/cancel`); }
    return;
  }
  const inf = e.target.closest('[data-info]');
  if(inf){
    const [k, id, host] = inf.dataset.info.split(':'), me = hostName();
    const src = host === me ? (k==='c' ? S.conversions : S.uploads) : (((S.peers||[]).find(p => p.name===host)||{})[k==='c' ? 'conversions' : 'uploads'] || []);
    const o = src.find(x => x.id === +id);
    if(o) toast(`${o.name}${o.error ? ' – ' + o.error : ''}`, !!o.error);
  }
}
document.addEventListener('click', e => {
  const pb = e.target.closest('[data-ppause]');
  if(pb){ api(`/api/peer/${pb.dataset.ppause}/conversions/pause`, 'POST', {paused: !pb.dataset.paused}).then(() => toast(pb.dataset.paused ? `${pb.dataset.ppause}: Konvertierung läuft weiter.` : `${pb.dataset.ppause}: Konvertierung pausiert.`)); return; }
  const b = e.target.closest('.pause-btn'); if(!b) return;
  api('/api/conversions/pause', 'POST', {paused: !b.dataset.paused}).then(() => toast(b.dataset.paused ? 'Konvertierung läuft weiter.' : 'Konvertierung pausiert – Prozesse sind angehalten.'));
});

delegate('[data-joblist]', 'click', jobsClick);
onState(renderJobs);

// Werkzeugleiste über der Auftragsliste (Übergabe-Knopf: js/handover.js)
const JOBTOOLS = '<div class="jobtools"><span class="pill idle-chip" hidden></span><button class="secondary handover-btn" hidden title="Laufende und wartende Konvertierungen an einen anderen Rechner übergeben, z. B. vor dem Herunterfahren">⇄ Übergabe</button><button class="secondary pause-btn" hidden></button><span class="peerpause" hidden style="display:contents"></span></div>';
const BRAND = '<span class="brand-mark" style="width:20px;height:20px;border-width:4px"></span>';
// HTML des Auftragsfeldes. Das Feld der Laufwerksansicht zeigt zusätzlich das Ziel; `id` ist die Kennung der Liste.
export const jobsPanelHtml = (id, withDest) => `<section class="panel"${withDest ? '' : ' style="margin-top:12px"'}>
          <div class="panel-head">${BRAND}${withDest ? '<div><h2>Aufträge</h2><span class="sub" id="jobsDest"></span></div>' : '<h2>Aufträge</h2>'}</div>
          ${JOBTOOLS}
          <div class="section-content" id="${id}" data-joblist></div>
        </section>`;
registerPanel({view:'laufwerke', slot:'right', order:10, id:'jobs', html: jobsPanelHtml('jobs', true)});
