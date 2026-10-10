// Aufträge aller Rechner (Rippen, Konvertieren, Übertragen) als Liste mit Pause/Überspringen/Abbrechen.
import { $, S, api, baseName, dec, delegate, esc, fmtB, fmtD, hostName, setHtml, toast, ui } from './core.js';
import { jobBtn, reconcileJobs } from './jobs-list.js';
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
// Beendete Einträge lassen sich aus der Liste entfernen (ohne Rückfrage; Dateien bleiben). Andere Rechner nur, wenn sie das können (capabilities.jobs_dismiss).
const itemDone = x => x.k==='c' ? ['done','skipped','cancelled','error'].includes(x.o.status) : x.k==='u' ? ['done','error'].includes(x.o.status) : false;
const canDismiss = x => itemDone(x) && (x.local || !!(((S.peers||[]).find(p => p.name===x.host)||{}).capabilities||{}).jobs_dismiss);
const dismissBtn = (x, h) => jobBtn(`data-dismiss="${x.k}:${x.o.id}" data-host="${h}"`, '🗑', 'Entfernen', 'Aus der Liste entfernen (die Datei bleibt)');
const itemActive = x => x.k==='d' ? true : x.k==='c' ? ['queued','running'].includes(x.o.status) : ['queued','copying','retry'].includes(x.o.status);
function jobSpeed(x){        // geglättete Geschwindigkeit eines Rips/Backups (Bytes/s) – auch für Aufträge anderer Rechner
  const o = x.o, key = x.host + ':' + o.dev, done = (o.overall||0)*(o.bytes||0), now = S.now;
  let r = ui.rate[key];
  if(!r || r.job !== o.started){ r = ui.rate[key] = {job:o.started, t:now, b:done, v:0}; }
  else if(now - r.t >= 3){ const inst = Math.max(0,(done-r.b)/(now-r.t)); r.v = r.v ? r.v*0.6+inst*0.4 : inst; r.t = now; r.b = done; }
  return r.v;
}
// Anzeigemodell eines Auftrags (reine Daten, kein HTML); jobs-list.js trägt es ins stabile Zeilen-Element ein
function jobModel(x, multi){
  const o = x.o, m = {iconCls:'', iconTxt:'✓', name:'', title:'', host: multi ? x.host : '', cls:'', txt:'Fertig', small:'', err:false, pct:null, acts:''};
  const run = () => { m.cls = 'run'; m.txt = 'Läuft'; m.iconCls = 'run'; m.iconTxt = ''; };
  const wait = (txt, sym = '…') => { m.cls = 'wait'; m.txt = txt; m.iconCls = 'wait'; m.iconTxt = sym; };
  const fail = (txt, msg) => { m.cls = 'err'; m.txt = txt; m.iconCls = 'err'; m.iconTxt = '!'; m.small = msg; m.err = true; };
  if(x.k === 'd'){
    const ov = o.kind==='scan' ? (o.total||0) : (o.overall||0), p = Math.round(ov*100), v = o.kind==='scan' ? 0 : jobSpeed(x), el = Math.max(1, S.now - o.started);
    const eta = ov > 0.01 ? ((v > 0 && o.bytes) ? o.bytes*(1-ov)/v : el/ov - el) : 0;
    run(); m.pct = p;
    const art = {rip:'Rippen', backup:'Disc-Backup', scan:'Analyse'}[o.kind] || o.kind;
    m.small = `${art} ${p} %${v>0 ? ` · ${fmtB(v)}/s` : ''} · Laufzeit ${fmtD(el)}${eta ? ` · Restzeit ${fmtD(eta)}` : ''}${o.kind==='rip' && o.count ? ` · Titel ${o.index||0}/${o.count}` : ''}`;
    m.name = m.title = (o.disc || o.title || 'Disc') + ' – ' + (o.kind==='backup' ? 'Backup' : o.kind==='scan' ? 'Analyse' : 'Rip');
    return m;
  }
  if(x.k === 'c'){
    const h = x.local ? '' : esc(x.host), pct = Math.round((o.pct||0)*100);
    if(o.cancel && o.status !== 'cancelled'){ wait('Bricht ab'); m.small = 'Wird abgebrochen …'; }
    else if(o.status === 'running' && o.paused){ wait('Pausiert', '⏸'); m.pct = pct; m.small = `Konvertierung pausiert bei ${pct} % – mit „Fortsetzen“ geht es weiter`; }
    else if(o.status === 'running'){
      run(); m.pct = pct;
      m.small = `Konvertierung ${pct} %${o.fps ? ` · ${dec(o.fps.toFixed(1))} fps` : ''}${o.speed ? ` · ${dec(o.speed.toFixed(2))}× Echtzeit` : ''}${o.eta ? ` · Restzeit ${fmtD(o.eta)}` : ''}${o.mode ? ` · ${o.mode}` : ''}`; }
    else if(o.status === 'queued'){ wait('Wartet'); m.small = `Konvertierung eingereiht${(x.local ? S.conv_paused : (S.peers||[]).some(p => p.name===x.host && p.conv_paused)) ? ' (pausiert)' : ''} · ${fmtB(o.size_in)}`; }
    else if(o.status === 'cancelled'){ wait('Abgebrochen', '✕'); m.iconCls = 'skip'; m.small = o.origin === 'library' ? 'Abgebrochen · Original bleibt unverändert' : 'Abgebrochen · gerippte Datei verworfen'; }
    else if(o.status === 'done') m.small = `Konvertiert · ${fmtB(o.size_in)} → ${fmtB(o.size_out)} (−${Math.round((1-o.size_out/o.size_in)*100)} %)`;
    else if(o.status === 'skipped'){ m.iconCls = 'skip'; m.small = o.handed ? `An ${o.handed} übergeben` : 'Konvertierung übersprungen · Original'; if(o.handed) m.txt = 'Übergeben'; }
    else fail('Fehler', o.error || 'Konvertierung fehlgeschlagen');
    if(o.origin === 'library') m.small += ' · Bibliothek';
    m.acts = ((o.status==='queued' || o.status==='running') && !o.cancel)
      ? '<span class="job-btns">' + jobBtn(`data-skip="${o.id}" data-host="${h}"`, '⏭︎', 'Überspringen', 'Ohne Konvertierung weiter: das Original bleibt liegen bzw. wird unverändert übertragen')
        + jobBtn(`data-cancel="${o.id}" data-host="${h}" data-origin="${esc(o.origin||'')}"`, '✕', 'Abbrechen', 'Auftrag ganz beenden', 'danger') + '</span>'
      : (canDismiss(x) ? '<span class="job-btns">' + dismissBtn(x, h) + `<button class="icon-btn job-info" data-info="c:${o.id}:${esc(x.host)}" aria-label="Details">›</button></span>` : `<button class="icon-btn job-info" data-info="c:${o.id}:${esc(x.host)}" aria-label="Details">›</button>`);
  } else {
    const p = o.size ? Math.round(o.copied/o.size*100) : 0;
    if(o.status === 'copying'){ run(); m.pct = p;
      m.small = `Übertragung ${p} % · ${fmtB(o.copied)} / ${fmtB(o.size)}${o.speed>0 ? ` · ${fmtB(o.speed)}/s` : ''}${o.eta>1 ? ` · noch ${fmtD(o.eta)}` : ''}`; }
    else if(o.status === 'queued'){ wait('Wartet'); m.small = `Übertragung eingereiht · ${fmtB(o.size)}`; }
    else if(o.status === 'retry') fail('Neuer Versuch', o.error || 'Übertragung fehlgeschlagen');
    else if(o.status === 'error') fail('Fehler', o.error || 'Übertragung fehlgeschlagen');
    else m.small = `${fmtB(o.size)} · Zielverzeichnis${o.replace ? ' · ersetzt Original' : ''}`;
    const info = `<button class="icon-btn job-info" data-info="u:${o.id}:${esc(x.host)}" aria-label="Details">›</button>`;
    m.acts = canDismiss(x) ? '<span class="job-btns">' + dismissBtn(x, x.local ? '' : esc(x.host)) + info + '</span>' : info;
  }
  m.name = baseName(o.name) + (x.k==='u' ? ' übertragen' : ''); m.title = o.name;
  return m;
}
const itemKey = x => x.k === 'd' ? `d|${x.host}|${x.o.dev}` : `${x.k}|${x.host}|${x.o.id}`;
function renderJobs(){
  const multi = (S.peers||[]).length > 0, items = clusterItems();
  items.sort((a,b) => (itemActive(b)-itemActive(a)) || (itemActive(a) ? (a.host===b.host ? (a.o.id||0)-(b.o.id||0) : a.host.localeCompare(b.host)) : (b.o.t||0)-(a.o.t||0)));
  const rows = items.slice(0,14).map(x => ({key: itemKey(x), model: jobModel(x, multi)}));
  document.querySelectorAll('[data-joblist]').forEach(e => { if(!e.closest('[hidden]')) reconcileJobs(e, rows, 'Keine Aufträge.'); });
  const dest = $('#jobsDest');
  if(dest) dest.textContent = multi ? `Ziel: ${S.output.dir} · alle Rechner` : `Ziel: ${S.output.dir}`;
  const aktiv = (S.conversions||[]).some(c => c.status==='queued' || c.status==='running'), p = !!S.conv_paused;
  const hatPeers = (S.peers||[]).length > 0;
  document.querySelectorAll('.idle-chip').forEach(c => { c.hidden = !hatPeers; c.textContent = S.idle ? '✓ bereit zum Herunterfahren' : 'Arbeit läuft'; c.className = 'pill idle-chip ' + (S.idle ? 'online' : 'busypill'); });
  const nDone = items.filter(canDismiss).length;
  document.querySelectorAll('.clear-btn').forEach(b => { b.hidden = !nDone; b.textContent = `🗑 Erledigte entfernen (${nDone})`; });
  document.querySelectorAll('.pause-btn').forEach(b => { b.hidden = !(aktiv || p); b.textContent = p ? '▶ Fortsetzen' : '⏸ Pausieren'; b.dataset.paused = p ? '1' : ''; });
  const pp = (S.peers||[]).filter(x => x.reachable && ((x.conversions||[]).some(c => ['queued','running'].includes(c.status)) || x.conv_paused))
    .map(x => `<button class="secondary" data-ppause="${esc(x.name)}" data-paused="${x.conv_paused ? '1' : ''}">${x.conv_paused ? '▶' : '⏸'} ${esc(x.name)}</button>`).join('');
  document.querySelectorAll('.peerpause').forEach(e => { e.hidden = !pp; setHtml(e, pp); });
}
function dismissUrl(kind, id, host){ return `${host ? `/api/peer/${host}` : '/api'}/${kind==='c' ? 'conversions' : 'uploads'}/${id}/dismiss`; }
function jobsClick(e){
  const dm = e.target.closest('[data-dismiss]');
  if(dm){ const [k, id] = dm.dataset.dismiss.split(':'); api(dismissUrl(k, id, dm.dataset.host)).catch(() => {}); return; }
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
  if(e.target.closest('.clear-btn')){
    const hosts = (S.peers||[]).filter(p => p.reachable && (p.capabilities||{}).jobs_dismiss).map(p => p.name);
    Promise.all([api('/api/jobs/dismiss-finished'), ...hosts.map(h => api(`/api/peer/${h}/jobs/dismiss-finished`))]).catch(() => {});
    return;
  }
  const pb = e.target.closest('[data-ppause]');
  if(pb){ api(`/api/peer/${pb.dataset.ppause}/conversions/pause`, 'POST', {paused: !pb.dataset.paused}).then(() => toast(pb.dataset.paused ? `${pb.dataset.ppause}: Konvertierung läuft weiter.` : `${pb.dataset.ppause}: Konvertierung pausiert.`)); return; }
  const b = e.target.closest('.pause-btn'); if(!b) return;
  api('/api/conversions/pause', 'POST', {paused: !b.dataset.paused}).then(() => toast(b.dataset.paused ? 'Konvertierung läuft weiter.' : 'Konvertierung pausiert – Prozesse sind angehalten.'));
});

delegate('[data-joblist]', 'click', jobsClick);
onState(renderJobs);

// Werkzeugleiste über der Auftragsliste (Übergabe-Knopf: js/handover.js)
const JOBTOOLS = '<div class="jobtools"><span class="pill idle-chip" hidden></span><button class="secondary handover-btn" hidden title="Laufende und wartende Konvertierungen an einen anderen Rechner übergeben, z. B. vor dem Herunterfahren">⇄ Übergabe</button><button class="secondary pause-btn" hidden></button><button class="secondary clear-btn" hidden title="Alle fertigen, übersprungenen, abgebrochenen und fehlgeschlagenen Einträge aus der Liste entfernen (Dateien bleiben)">🗑 Erledigte entfernen</button><span class="peerpause" hidden style="display:contents"></span></div>';
const BRAND = '<span class="brand-mark" style="width:20px;height:20px;border-width:4px"></span>';
// HTML des Auftragsfeldes. Das Feld der Laufwerksansicht zeigt zusätzlich das Ziel; `id` ist die Kennung der Liste.
export const jobsPanelHtml = (id, withDest) => `<section class="panel"${withDest ? '' : ' style="margin-top:12px"'}>
          <div class="panel-head">${BRAND}${withDest ? '<div><h2>Aufträge</h2><span class="sub" id="jobsDest"></span></div>' : '<h2>Aufträge</h2>'}</div>
          ${JOBTOOLS}
          <div class="section-content joblist" id="${id}" data-joblist></div>
        </section>`;
registerPanel({view:'laufwerke', slot:'right', order:10, id:'jobs', html: jobsPanelHtml('jobs', true)});
