// Jobs of all machines (rip, convert, transfer) as a list with pause/skip/cancel.
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
// Finished entries can be removed from the list (without asking; files stay). Other machines only if they support it (capabilities.jobs_dismiss).
const itemDone = x => x.k==='c' ? ['done','skipped','cancelled','error'].includes(x.o.status) : x.k==='u' ? ['done','error'].includes(x.o.status) : false;
const canDismiss = x => itemDone(x) && (x.local || !!(((S.peers||[]).find(p => p.name===x.host)||{}).capabilities||{}).jobs_dismiss);
const dismissBtn = (x, h) => jobBtn(`data-dismiss="${x.k}:${x.o.id}" data-host="${h}"`, '🗑', 'Remove', 'Remove from the list (the file stays)');
const itemActive = x => x.k==='d' ? true : x.k==='c' ? ['queued','running'].includes(x.o.status) : ['queued','copying','retry'].includes(x.o.status);
function jobSpeed(x){        // smoothed speed of a rip/backup (bytes/s) – also for jobs of other machines
  const o = x.o, key = x.host + ':' + o.dev, done = (o.overall||0)*(o.bytes||0), now = S.now;
  let r = ui.rate[key];
  if(!r || r.job !== o.started){ r = ui.rate[key] = {job:o.started, t:now, b:done, v:0}; }
  else if(now - r.t >= 3){ const inst = Math.max(0,(done-r.b)/(now-r.t)); r.v = r.v ? r.v*0.6+inst*0.4 : inst; r.t = now; r.b = done; }
  return r.v;
}
// Display model of a job (pure data, no HTML); jobs-list.js writes it into the stable row element
function jobModel(x, multi){
  const o = x.o, m = {iconCls:'', iconTxt:'✓', name:'', title:'', host: multi ? x.host : '', cls:'', txt:'Done', small:'', err:false, pct:null, acts:''};
  const run = () => { m.cls = 'run'; m.txt = 'Running'; m.iconCls = 'run'; m.iconTxt = ''; };
  const wait = (txt, sym = '…') => { m.cls = 'wait'; m.txt = txt; m.iconCls = 'wait'; m.iconTxt = sym; };
  const fail = (txt, msg) => { m.cls = 'err'; m.txt = txt; m.iconCls = 'err'; m.iconTxt = '!'; m.small = msg; m.err = true; };
  if(x.k === 'd'){
    const ov = o.kind==='scan' ? (o.total||0) : (o.overall||0), p = Math.round(ov*100), v = o.kind==='scan' ? 0 : jobSpeed(x), el = Math.max(1, S.now - o.started);
    const eta = ov > 0.01 ? ((v > 0 && o.bytes) ? o.bytes*(1-ov)/v : el/ov - el) : 0;
    run(); m.pct = p;
    const art = {rip:'Ripping', backup:'Disc backup', scan:'Analysis'}[o.kind] || o.kind;
    m.small = `${art} ${p} %${v>0 ? ` · ${fmtB(v)}/s` : ''} · elapsed ${fmtD(el)}${eta ? ` · remaining ${fmtD(eta)}` : ''}${o.kind==='rip' && o.count ? ` · title ${o.index||0}/${o.count}` : ''}`;
    m.name = m.title = (o.disc || o.title || 'Disc') + ' – ' + (o.kind==='backup' ? 'Backup' : o.kind==='scan' ? 'Analysis' : 'Rip');
    return m;
  }
  if(x.k === 'c'){
    const h = x.local ? '' : esc(x.host), pct = Math.round((o.pct||0)*100);
    if(o.cancel && o.status !== 'cancelled'){ wait('Cancelling'); m.small = 'Being cancelled …'; }
    else if(o.status === 'running' && o.paused){ wait('Paused', '⏸'); m.pct = pct; m.small = `Conversion paused at ${pct} % – "Resume" continues it`; }
    else if(o.status === 'running'){
      run(); m.pct = pct;
      m.small = `Converting ${pct} %${o.fps ? ` · ${dec(o.fps.toFixed(1))} fps` : ''}${o.speed ? ` · ${dec(o.speed.toFixed(2))}× realtime` : ''}${o.eta ? ` · remaining ${fmtD(o.eta)}` : ''}${o.mode ? ` · ${o.mode}` : ''}`; }
    else if(o.status === 'queued'){ wait('Waiting'); m.small = `Conversion queued${(x.local ? S.conv_paused : (S.peers||[]).some(p => p.name===x.host && p.conv_paused)) ? ' (paused)' : ''} · ${fmtB(o.size_in)}`; }
    else if(o.status === 'cancelled'){ wait('Cancelled', '✕'); m.iconCls = 'skip'; m.small = o.origin === 'library' ? 'Cancelled · original left unchanged' : 'Cancelled · ripped file discarded'; }
    else if(o.status === 'done') m.small = `Converted · ${fmtB(o.size_in)} → ${fmtB(o.size_out)} (−${Math.round((1-o.size_out/o.size_in)*100)} %)`;
    else if(o.status === 'skipped'){ m.iconCls = 'skip'; m.small = o.handed ? `Handed over to ${o.handed}` : 'Conversion skipped · original'; if(o.handed) m.txt = 'Handed over'; }
    else fail('Error', o.error || 'Conversion failed');
    if(o.origin === 'library') m.small += ' · library';
    m.acts = ((o.status==='queued' || o.status==='running') && !o.cancel)
      ? '<span class="job-btns">' + jobBtn(`data-skip="${o.id}" data-host="${h}"`, '⏭︎', 'Skip', 'Continue without conversion: the original stays in place or is transferred unchanged')
        + jobBtn(`data-cancel="${o.id}" data-host="${h}" data-origin="${esc(o.origin||'')}"`, '✕', 'Cancel', 'End the job completely', 'danger') + '</span>'
      : (canDismiss(x) ? '<span class="job-btns">' + dismissBtn(x, h) + `<button class="icon-btn job-info" data-info="c:${o.id}:${esc(x.host)}" aria-label="Details">›</button></span>` : `<button class="icon-btn job-info" data-info="c:${o.id}:${esc(x.host)}" aria-label="Details">›</button>`);
  } else {
    const p = o.size ? Math.round(o.copied/o.size*100) : 0;
    if(o.status === 'copying'){ run(); m.pct = p;
      m.small = `Transfer ${p} % · ${fmtB(o.copied)} / ${fmtB(o.size)}${o.speed>0 ? ` · ${fmtB(o.speed)}/s` : ''}${o.eta>1 ? ` · ${fmtD(o.eta)} left` : ''}`; }
    else if(o.status === 'queued'){ wait('Waiting'); m.small = `Transfer queued · ${fmtB(o.size)}`; }
    else if(o.status === 'retry') fail('Retrying', o.error || 'Transfer failed');
    else if(o.status === 'error') fail('Error', o.error || 'Transfer failed');
    else m.small = `${fmtB(o.size)} · target folder${o.replace ? ' · replaces original' : ''}`;
    const info = `<button class="icon-btn job-info" data-info="u:${o.id}:${esc(x.host)}" aria-label="Details">›</button>`;
    m.acts = canDismiss(x) ? '<span class="job-btns">' + dismissBtn(x, x.local ? '' : esc(x.host)) + info + '</span>' : info;
  }
  m.name = baseName(o.name) + (x.k==='u' ? ' transferred' : ''); m.title = o.name;
  return m;
}
const itemKey = x => x.k === 'd' ? `d|${x.host}|${x.o.dev}` : `${x.k}|${x.host}|${x.o.id}`;
function renderJobs(){
  const multi = (S.peers||[]).length > 0, items = clusterItems();
  items.sort((a,b) => (itemActive(b)-itemActive(a)) || (itemActive(a) ? (a.host===b.host ? (a.o.id||0)-(b.o.id||0) : a.host.localeCompare(b.host)) : (b.o.t||0)-(a.o.t||0)));
  const rows = items.slice(0,14).map(x => ({key: itemKey(x), model: jobModel(x, multi)}));
  document.querySelectorAll('[data-joblist]').forEach(e => { if(!e.closest('[hidden]')) reconcileJobs(e, rows, 'No jobs.'); });
  const dest = $('#jobsDest');
  if(dest) dest.textContent = multi ? `Target: ${S.output.dir} · all machines` : `Target: ${S.output.dir}`;
  const active = (S.conversions||[]).some(c => c.status==='queued' || c.status==='running'), p = !!S.conv_paused;
  const hasPeers = (S.peers||[]).length > 0;
  document.querySelectorAll('.idle-chip').forEach(c => { c.hidden = !hasPeers; c.textContent = S.idle ? '✓ ready to shut down' : 'work in progress'; c.className = 'pill idle-chip ' + (S.idle ? 'online' : 'busypill'); });
  const nDone = items.filter(canDismiss).length;
  document.querySelectorAll('.clear-btn').forEach(b => { b.hidden = !nDone; b.textContent = `🗑 Remove finished (${nDone})`; });
  document.querySelectorAll('.pause-btn').forEach(b => { b.hidden = !(active || p); b.textContent = p ? '▶ Resume' : '⏸ Pause'; b.dataset.paused = p ? '1' : ''; });
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
    if(confirm('Cancel the conversion? The original stays unchanged or is transferred unchanged.')){
      const h = sk.dataset.host; api(h ? `/api/peer/${h}/conversions/${sk.dataset.skip}/skip` : `/api/conversions/${sk.dataset.skip}/skip`);
    }
    return;
  }
  const cn = e.target.closest('[data-cancel]');
  if(cn){
    const lib = cn.dataset.origin === 'library';
    const msg = lib ? 'Cancel the conversion? The original stays unchanged and the job is ended.'
      : 'Cancel the job? The freshly ripped file will be DISCARDED and would have to be ripped again.\n\n("Skip" instead transfers it to the target without conversion.)';
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
  if(pb){ api(`/api/peer/${pb.dataset.ppause}/conversions/pause`, 'POST', {paused: !pb.dataset.paused}).then(() => toast(pb.dataset.paused ? `${pb.dataset.ppause}: conversion resumed.` : `${pb.dataset.ppause}: conversion paused.`)); return; }
  const b = e.target.closest('.pause-btn'); if(!b) return;
  api('/api/conversions/pause', 'POST', {paused: !b.dataset.paused}).then(() => toast(b.dataset.paused ? 'Conversion resumed.' : 'Conversion paused – processes are suspended.'));
});

delegate('[data-joblist]', 'click', jobsClick);
onState(renderJobs);

// Toolbar above the job list (hand-over button: js/handover.js)
const JOBTOOLS = '<div class="jobtools"><span class="pill idle-chip" hidden></span><button class="secondary handover-btn" hidden title="Hand running and waiting conversions over to another machine, e.g. before shutting down">⇄ Hand over</button><button class="secondary pause-btn" hidden></button><button class="secondary clear-btn" hidden title="Remove all finished, skipped, cancelled and failed entries from the list (files stay)">🗑 Remove finished</button><span class="peerpause" hidden style="display:contents"></span></div>';
const BRAND = '<span class="brand-mark" style="width:20px;height:20px;border-width:4px"></span>';
// HTML of the jobs panel. The panel in the drives view also shows the target; `id` is the list's identifier.
export const jobsPanelHtml = (id, withDest) => `<section class="panel"${withDest ? '' : ' style="margin-top:12px"'}>
          <div class="panel-head">${BRAND}${withDest ? '<div><h2>Jobs</h2><span class="sub" id="jobsDest"></span></div>' : '<h2>Jobs</h2>'}</div>
          ${JOBTOOLS}
          <div class="section-content joblist" id="${id}" data-joblist></div>
        </section>`;
registerPanel({view:'drives', slot:'right', order:10, id:'jobs', html: jobsPanelHtml('jobs', true)});
