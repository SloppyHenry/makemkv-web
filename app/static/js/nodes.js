// Settings section "Machines": mode, name, pairing (optional), machine list, network search, adding by address.
// Layout 1:1 after docs/mockups/paket-c.html. The list is not a form field: its buttons call their own endpoints (/api/nodes, /api/discovery).
// Via the settings page only name, mode, pairing requirement and the search options are saved (namespace `nodes`).
import { $, S, api, delegate, dec, esc, setHtml, toast } from './core.js';
import { onState, registerSettingsSection } from './registry.js';
import { agoSrv, encoderChips, gb, hostOf, spanTxt } from './nodes-util.js';

let editing = '', scanOpen = false, addRes = null;
const tests = {};                                   // nid -> result of the last connection test
const mgr = () => (S && S.nodemgr) || {nodes: [], pairing: {incoming: [], outgoing: []}, scan: {found: []}};
const saved = () => (S && S.settings && S.settings.nodes) || {mode: 'verbund', pairing_required: false, name: '', scan_nets: '', auto_search: false};
const active = () => saved().mode === 'verbund';
const needPair = () => !!saved().pairing_required;   // stored value 'verbund' = cluster mode
const waitingFor = url => mgr().pairing.outgoing.find(o => o.status === 'waiting' && o.url === url);
const code = c => String(c || '').replace(/^(\d{3})(\d{3})$/, '$1 $2');

registerSettingsSection({
  id: 'nodes', label: 'Machines', order: 30, icon: '⇄', description: 'Cluster, pairing and machine list',
  render(el, s){
    const n = s.nodes || saved(), inst = (S && S.capacity && S.capacity.instance) || '';
    el.innerHTML = `<div class="node-section" id="nodeSection">
      <p class="node-lead">Several installations of Spindle form a cluster: shared jobs, hand-over of conversions, remote control of the drives.</p>
      <section class="panel node-self">
        <div class="node-self-grid">
          <div class="node-field"><label for="nodeName">Name of this machine</label><input class="input" type="text" id="nodeName" maxlength="40" placeholder="${esc(inst)}" value="${esc(n.name)}"><p class="help">This is how the other machines see it. Default: the hostname${inst ? ` (${esc(inst)})` : ''}.</p></div>
          <div class="node-field"><label>Mode</label>
            <div class="node-seg" role="radiogroup" aria-label="Mode"><label><input type="radio" name="nodeMode" value="verbund" ${n.mode === 'verbund' ? 'checked' : ''}>Cluster</label><label><input type="radio" name="nodeMode" value="standalone" ${n.mode !== 'verbund' ? 'checked' : ''}>Standalone</label></div>
            <p class="help">Standalone: no other machines, no search, no cluster buttons.</p></div>
        </div>
        <p class="node-note info" id="nodeStandNote" style="margin:0" hidden><strong>Standalone mode.</strong> This machine works on its own: no connection to other machines, not discoverable, no cluster buttons. The list below stays saved and becomes active again when you switch back.</p>
        <label class="node-opt" id="nodeReqLabel"><input class="check" type="checkbox" id="nodeReq" ${n.pairing_required ? 'checked' : ''}><span>Require pairing with a token<p class="help">Off (default): machines on the network can be added with one click, without confirmation or token. On: new machines are only added through a pairing request confirmed on the other machine. In cluster mode every machine is always discoverable on the network.</p></span></label>
        <p class="help" style="margin:0">Name, mode and pairing requirement are saved by the Save button below. The list takes effect immediately.</p>
      </section>
      <div id="nodeSearchWrap" hidden>
        <section class="panel"><div class="panel-head"><div><h2>Search the network for machines</h2><span class="sub" id="nodeScanSub"></span></div><div class="node-actionsbar" id="nodeScanBtns"></div></div>
          <div id="nodeScanBody"></div></section>
        <p class="node-note info" style="margin:10px 0 0"><strong>Not found?</strong> A machine only shows up if it is running and in cluster mode (not standalone). Machines with an older version can only be added by address. If this machine runs in Docker, it searches the network you opened the page from; enter a different network below.</p>
        <div class="node-field" style="margin-top:10px"><label for="nodeNets">Network to search (optional)</label><input class="input" type="text" id="nodeNets" placeholder="automatic, e.g. 192.168.178.0/24, 10.0.0.0/24" value="${esc(n.scan_nets)}"></div>
        <label class="node-opt" style="margin-top:10px"><input class="check" type="checkbox" id="nodeAuto" ${n.auto_search ? 'checked' : ''}><span>Search regularly in the background<p class="help">Every 10 minutes. New machines are only suggested, never connected automatically.</p></span></label>
      </div>
      <section class="panel node-needs"><div class="panel-head"><div><h2>Machines in the cluster</h2><span class="sub" id="nodeListSub"></span></div>
        <div class="node-actionsbar"><button type="button" class="secondary" data-na="search">Search the network for machines</button><button type="button" class="secondary" data-na="addtoggle">+ Add by address</button></div></div>
        <div class="node-add" id="nodeAdd" hidden>
          <div class="node-field"><label for="nodeAddUrl">Address</label><input class="input" type="text" id="nodeAddUrl" placeholder="192.168.178.189" autocomplete="off"><p class="help">IP or name, optionally with port (default 8780).</p></div>
          <div class="node-field"><label for="nodeAddName">Display name (optional)</label><input class="input" type="text" id="nodeAddName" maxlength="40" placeholder="taken from the machine" autocomplete="off"></div>
          <button type="button" class="primary" style="width:auto" data-na="check">Check</button>
        </div>
        <div class="node-add-result" id="nodeAddRes"></div>
        <div class="node-list" id="nodeList"></div></section>
    </div>`;
    const modeChanged = () => {
      const v = ($('input[name=nodeMode]:checked', el) || {}).value, live = v === 'verbund';
      $('#nodeStandNote').hidden = live; $('#nodeReq').disabled = !live; $('#nodeReqLabel').style.opacity = live ? '' : '.45';
    };
    el.addEventListener('change', e => { if(e.target.name === 'nodeMode') modeChanged(); });
    $('#nodeAddUrl').addEventListener('keydown', e => { if(e.key === 'Enter'){ e.preventDefault(); doCheck(); } });
    modeChanged(); renderAll();
  },
  collect(){
    if(!$('#nodeName')) return {nodes: {}};
    return {nodes: {name: $('#nodeName').value.trim(), mode: ($('input[name=nodeMode]:checked') || {}).value || 'standalone',
      pairing_required: $('#nodeReq').checked, scan_nets: $('#nodeNets').value.trim(), auto_search: $('#nodeAuto').checked}};
  },
});

// ---------- Rendering
function chips(p){
  const out = [], d = p.drives || [];
  out.push(`<span class="node-chip">${d.length ? `${d.length} drive${d.length > 1 ? 's' : ''} · ${esc(d.map(x => x.name).join(', '))}` : 'No drive'}</span>`);
  if(p.cores) out.push(`<span class="node-chip">${p.cores} Threads${p.mem ? ' · ' + gb(p.mem) + ' RAM' : ''}</span>`);
  if(p.cores && p.load != null) out.push(`<span class="node-chip">Load ${dec(Number(p.load).toFixed(1))}</span>`);
  const cv = (p.conversions || []).filter(c => c.status === 'running' || c.status === 'queued'), run = cv.filter(c => c.status === 'running');
  const job = (p.jobs || [])[0];
  if(cv.length) out.push(`<span class="node-chip work">${p.conv_paused ? 'Conversion paused' : 'Converting'} ${cv.length} file${cv.length > 1 ? 's' : ''}${run.length ? ' · ' + Math.round(run.reduce((a, c) => a + (c.pct || 0), 0) / run.length * 100) + ' %' : ''}</span>`);
  if(job) out.push(`<span class="node-chip work">${job.kind === 'scan' ? 'Analyzing' : job.kind === 'backup' ? 'Backup' : 'Ripping'} "${esc(job.title || job.name || '')}" · ${Math.round((job.kind === 'scan' ? job.total : job.overall) * 100)} %</span>`);
  const enc = encoderChips(p);
  out.push(p.legacy ? '<span class="node-chip">x265 only</span>' : enc.length ? `<span class="node-chip">${esc(enc.join(' · '))}</span>` : '');
  return out.join('');
}

function note(rec, p, on, known, old, lost, wait){
  const t = tests[rec.nid], out = [];
  if(t) out.push(t.ok ? `<p class="node-note"><span class="node-test">Connection ok · ${t.ms} ms</span></p>` : `<p class="node-note err">${esc(t.error)}</p>`);
  if(wait) out.push(`<p class="node-note info"><strong>Please confirm on ${esc(wait.name)}.</strong> The request appears there with this code:<span class="node-code-inline"><span class="node-code">${esc(code(wait.code))}</span></span></p>`);
  else if(lost) out.push(`<p class="node-note err">${esc(rec.name)} dissolved or declined the pairing. Jobs and remote control are off until you pair again.</p>`);
  else if(p && p.id_mismatch) out.push('<p class="node-note warn">A different machine answers at this address (address reassigned?). Remove it and pair again.</p>');
  else if(!on && known) out.push(`<p class="node-note">Not reachable. Machine off, asleep or disconnected from the network?${rec.paired ? ' The pairing stays in place; things continue as soon as it is back.' : ''}</p>`);
  else if(old) out.push('<p class="node-note warn">Still runs the old version: without pairing and without a capability report. Seeing jobs, hand-over and remote control work as before; new conversion settings (codec, AV1 …) are greyed out for this machine.</p>');
  else if(on && !rec.paired && needPair()) out.push(`<p class="node-note info">${rec.origin === 'peers' ? 'Taken over from the former <code>PEERS</code> setting and used without verification as before. ' : 'Not paired yet, used without verification. '}"Pair" replaces that with a token only the two of you know.</p>`);
  return out.join('');
}

function rowHtml(rec, live){
  const p = live ? (S.peers || []).find(x => x.name === rec.name) : null, wait = waitingFor(rec.url);
  const on = !!(p && p.reachable), known = !!(p && p.last_seen > 0), old = !!(on && p.legacy), lost = !!(p && p.trust === 'lost');
  const badges = [];
  if(live && !on) badges.push('<span class="st">Offline</span>');
  badges.push(wait ? '<span class="st warn">Waiting for confirmation</span>' : lost ? '<span class="st warn">Pairing dissolved</span>' : rec.paired ? '<span class="st ok">Paired</span>'
    : old || (known && p.legacy) ? '<span class="st warn">Older version</span>' : needPair() ? '<span class="st warn">Not paired</span>' : '<span class="st">No token</span>');
  if(old && rec.paired) badges.pop();
  const meta = [`<span>${esc(hostOf(rec.url))}</span>`];
  if(on) meta.push(`<span>online for <b>${spanTxt((p.started ? p.now - p.started : S.now - p.online_since))}</b></span>`);
  else if(known) meta.push(`<span>last seen <b>${agoSrv(p.last_seen)}</b></span>`);
  if(p && (on || known)) meta.push(`<span>Version <b>${esc(p.version || (p.legacy ? 'unknown (old)' : '?'))}</b></span>`);
  const b = (a, t, cls = 'secondary') => `<button type="button" class="${cls}" data-na="${a}" data-nid="${esc(rec.nid)}" data-url="${esc(rec.url)}">${t}</button>`;
  const btns = !live ? '' : [b('test', 'Test connection'), editing === rec.nid ? '' : b('rename', 'Rename'),
    wait ? `<button type="button" class="secondary" data-na="withdraw" data-rid="${esc(wait.rid)}">Withdraw request</button>`
      : lost ? b('pair', 'Pair again', 'primary" style="width:auto') + b('remove', 'Remove', 'secondary danger')
      : rec.paired ? b('unpair', 'Unpair', 'secondary danger')
      : old || (known && p.legacy) ? b('remove', 'Remove', 'secondary danger') : b('pair', 'Pair', needPair() ? 'primary" style="width:auto' : 'secondary') + b('remove', 'Remove', 'secondary danger')].join('');
  const name = editing === rec.nid ? `<span class="node-name-edit"><input class="input" type="text" id="nodeRen" maxlength="40" value="${esc(rec.name)}" data-nid="${esc(rec.nid)}"><button type="button" class="primary" style="width:auto;padding:7px 12px" data-na="renok" data-nid="${esc(rec.nid)}">OK</button><button type="button" class="secondary" data-na="renx">Cancel</button></span>`
    : `<span class="node-name">${esc(rec.name)}</span>`;
  return `<article class="node ${on ? (old ? 'on old' : 'on') : 'off'}"><div class="node-head"><span class="node-dot" title="${on ? 'Online' : 'Offline'}"></span>${name}<span class="node-badges">${badges.join('')}</span><div class="node-btns">${btns}</div></div>
    <div class="node-meta">${meta.join('')}</div>${on ? `<div class="node-facts">${chips(p)}</div>` : ''}${live ? note(rec, p, on, known, old, lost, wait) : ''}</article>`;
}

function renderList(){
  const m = mgr(), live = active(), recs = m.nodes, urls = new Set(recs.map(r => r.url));
  const pending = m.pairing.outgoing.filter(o => o.status === 'waiting' && !urls.has(o.url)).map(o => `<article class="node"><div class="node-head"><span class="node-dot" style="background:var(--amber)"></span><span class="node-name">${esc(o.name)}</span><span class="node-badges"><span class="st warn">Waiting for confirmation</span></span><div class="node-btns"><button type="button" class="secondary" data-na="withdraw" data-rid="${esc(o.rid)}">Withdraw request</button></div></div>
    <div class="node-meta"><span>${esc(hostOf(o.url))}</span></div><p class="node-note info"><strong>Please confirm on ${esc(o.name)}.</strong> The request "${esc((S.node || {}).name || '')} wants to connect" appears there with this code:<span class="node-code-inline"><span class="node-code">${esc(code(o.code))}</span></span></p></article>`);
  const on = live ? recs.filter(r => (S.peers || []).some(p => p.name === r.name && p.reachable)).length : 0;
  $('#nodeListSub').textContent = live ? `${recs.length} added · ${on} online` : `idle · ${recs.length} added`;
  const list = $('#nodeList');
  list.closest('.panel').classList.toggle('node-dim', !live);
  list.closest('.panel').setAttribute('aria-disabled', !live);
  setHtml(list, pending.join('') + recs.map(r => rowHtml(r, live)).join('') || '<div class="empty">No machines added yet. Search the network or add one by address.</div>');
}

function renderScan(){
  const wrap = $('#nodeSearchWrap'); wrap.hidden = !(scanOpen && active());
  if(wrap.hidden) return;
  const sc = mgr().scan, found = sc.found || [];
  $('#nodeScanSub').textContent = sc.nets && sc.nets.length ? `Network ${sc.nets.join(', ')}` : '';
  setHtml($('#nodeScanBtns'), sc.running ? '<button type="button" class="secondary" data-na="scancancel">Cancel</button>' : '<button type="button" class="secondary" data-na="search">Search again</button><button type="button" class="secondary" data-na="scanclose">Close</button>');
  const head = sc.running ? `<div class="node-scan-head"><span class="spin"></span><span>Searching … ${sc.done} of ${sc.total} addresses checked</span></div><div class="node-scanbar"><div style="width:${sc.total ? Math.round(sc.done / sc.total * 100) : 0}%"></div></div>`
    : `<div class="node-scan-head"><span>Search finished · ${found.length ? found.length + ' found' : 'nothing found'}${sc.error ? ' · ' + esc(sc.error) : ''}</span></div>`;
  const rows = found.map(f => {
    const w = waitingFor(f.url);
    const act = f.self ? '<span class="st">That is you</span>' : w ? '<span class="st warn">Waiting for confirmation</span>' : f.paired ? '<span class="st ok">Paired</span>'
      : f.known ? `<button type="button" class="${needPair() ? 'primary" style="width:auto' : 'secondary'}" data-na="pair" data-url="${esc(f.url)}">Pair</button>`
      : needPair() ? `<button type="button" class="primary" style="width:auto" data-na="pair" data-url="${esc(f.url)}">Connect</button>`
      : `<button type="button" class="primary" style="width:auto" data-na="adddirect" data-url="${esc(f.url)}" data-name="${esc(f.name)}">Add</button><button type="button" class="secondary" data-na="pair" data-url="${esc(f.url)}">Pair</button>`;
    return `<div class="node-found"><span class="node-dot" style="background:${f.self ? '#4a5568' : 'var(--green)'}"></span><div class="grow"><strong>${esc(f.name)}</strong><small>${esc(hostOf(f.url))}${f.self ? ' · this machine' : ` · version ${esc(f.version || '?')}${f.cores ? ' · ' + f.cores + ' threads' : ''}${f.mem ? ' · ' + gb(f.mem) + ' RAM' : ''}${f.known && !f.paired ? ' · already in the list' : ''}`}</small></div>${act}</div>`;
  }).join('');
  setHtml($('#nodeScanBody'), head + (rows ? `<div class="node-list">${rows}</div>` : ''));
}

function renderAdd(){
  const r = addRes, el = $('#nodeAddRes');
  if(!r){ setHtml(el, ''); return; }
  const name = esc(r.name || hostOf(r.url || ''));
  const body = !r.ok ? `<p class="node-note err" style="margin:0">${esc(r.error)}</p>` : r.self ? '<p class="node-note" style="margin:0">That is this machine.</p>'
    : r.known ? `<p class="node-note" style="margin:0">Already in the list (as "${esc(r.known)}").</p>`
    : r.legacy ? `<div class="node-head"><span class="node-dot" style="background:var(--amber)"></span><span class="node-name">${name}</span><span class="node-badges"><span class="st warn">Older version</span></span><div class="node-btns"><button type="button" class="secondary" data-na="addold">Add without pairing</button></div></div>
      <p class="node-note warn" style="margin:8px 0 0 20px"><strong>Cannot be paired.</strong> ${name} does not know pairing yet. It can still be used as before (see jobs, control drives, hand-over), but without a token and without newer features; password protection there would block access.</p>`
    : `<div class="node-head"><span class="node-dot" style="background:var(--green)"></span><span class="node-name">${name}</span><span class="node-badges"><span class="st ok">Reachable</span></span><div class="node-btns">${needPair() ? '' : `<button type="button" class="primary" style="width:auto" data-na="adddirect" data-url="${esc(r.url)}" data-name="${esc(r.name || '')}">Add</button>`}<button type="button" class="${needPair() ? 'primary" style="width:auto' : 'secondary'}" data-na="pair" data-url="${esc(r.url)}">Request pairing</button></div></div>
      <div class="node-meta"><span>${esc(hostOf(r.url))}</span><span>Version <b>${esc(r.version || '?')}</b></span></div>`;
  setHtml(el, `<div class="node" style="border-bottom:0">${body}</div>`);
}

function renderAll(){
  if(!$('#nodeList') || !S) return;
  $('#nodeSection').dataset.mode = saved().mode;
  for(const b of document.querySelectorAll('#nodeSection [data-na=search], #nodeSection [data-na=addtoggle]')) b.disabled = !active();
  if(!editing) renderList();
  renderScan(); renderAdd();
}
onState(renderAll);

// ---------- Actions
async function doCheck(){
  const url = $('#nodeAddUrl').value.trim(); if(!url) return;
  try{ addRes = await api('/api/nodes/check', 'POST', {url}); }catch{ return; }
  addRes.name = addRes.name || ''; renderAdd();
}
const pair = async url => { try{ const r = await api('/api/nodes/pair', 'POST', {url}); toast(`Request sent to ${r.name}. Please confirm there (code ${code(r.code)}).`); addRes = null; $('#nodeAdd').hidden = true; }catch{} renderAll(); };

delegate('#nodeSection [data-na]', 'click', async (e, b) => {
  const a = b.dataset.na, nid = b.dataset.nid, name = () => ((mgr().nodes.find(n => n.nid === nid) || {}).name || '');
  if(a === 'search'){ scanOpen = true; try{ await api('/api/discovery/scan'); }catch{} renderAll(); }
  else if(a === 'scancancel') api('/api/discovery/scan/cancel');
  else if(a === 'scanclose'){ scanOpen = false; renderAll(); }
  else if(a === 'addtoggle'){ const f = $('#nodeAdd'); f.hidden = !f.hidden; if(!f.hidden) $('#nodeAddUrl').focus(); }
  else if(a === 'check') doCheck();
  else if(a === 'addold'){
    try{ await api('/api/nodes', 'POST', {url: addRes.url, name: $('#nodeAddName').value.trim() || addRes.name}); toast('Machine added (without pairing).'); addRes = null; $('#nodeAdd').hidden = true; $('#nodeAddUrl').value = ''; }catch{}
    renderAll();
  }
  else if(a === 'adddirect'){
    b.disabled = true;
    try{ await api('/api/nodes', 'POST', {url: b.dataset.url, name: ($('#nodeAddName').value.trim() && addRes) ? $('#nodeAddName').value.trim() : b.dataset.name}); toast('Machine added.'); addRes = null; $('#nodeAdd').hidden = true; $('#nodeAddUrl').value = ''; }catch{}
    renderAll();
  }
  else if(a === 'pair') pair(b.dataset.url);
  else if(a === 'withdraw'){ try{ await api(`/api/nodes/pair-outgoing/${b.dataset.rid}/cancel`); }catch{} }
  else if(a === 'test'){
    b.disabled = true; try{ tests[nid] = await api(`/api/nodes/${nid}/test`); }catch{ tests[nid] = {ok: false, error: 'Test failed.'}; }
    setTimeout(() => { delete tests[nid]; renderAll(); }, 10000); renderAll();
  }
  else if(a === 'rename'){ editing = nid; renderList(); const i = $('#nodeRen'); if(i){ i.focus(); i.select(); } }
  else if(a === 'renx'){ editing = ''; renderAll(); }
  else if(a === 'renok') await rename(nid);
  else if(a === 'unpair'){ if(confirm(`Dissolve the pairing with ${name()}? The machine stays in the list; you then trust each other without a token again.`)){ try{ await api(`/api/nodes/${nid}/unpair`); toast('Unpaired.'); }catch{} } }
  else if(a === 'remove'){ if(confirm(`Remove ${name()} from the list?`)){ try{ await api(`/api/nodes/${nid}`, 'DELETE'); }catch{} } }
});
async function rename(nid){
  const v = ($('#nodeRen') || {}).value || '';
  try{ await api(`/api/nodes/${nid}`, 'PATCH', {name: v}); editing = ''; }catch{ return; }
  renderAll();
}
document.addEventListener('keydown', e => {
  if(e.target.id !== 'nodeRen') return;
  if(e.key === 'Enter'){ e.preventDefault(); rename(e.target.dataset.nid); } else if(e.key === 'Escape'){ editing = ''; renderAll(); }
});
