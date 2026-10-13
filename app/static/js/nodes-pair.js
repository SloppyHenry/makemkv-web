// Pairing: notice bar and confirmation dialog for requests from other machines (on every page), messages about our own requests,
// notice about newly found machines (background search). The machine list itself is in js/nodes.js.
import { $, S, api, delegate, esc, toast } from './core.js';
import { onState } from './registry.js';
import { hostOf } from './nodes-util.js';

const bar = document.createElement('div');
bar.id = 'nodeBanner'; bar.className = 'node-banner'; bar.hidden = true; bar.setAttribute('role', 'status');
const anchor = document.getElementById('banners');
if(anchor) anchor.before(bar); else document.body.prepend(bar);

document.body.insertAdjacentHTML('beforeend', `<dialog id="nodePairDlg" class="node-dlg" aria-labelledby="nodePairTitle"><form method="dialog" onsubmit="return false" id="nodePairBody"></form></dialog>`);
const dlg = $('#nodePairDlg');
let seen = {}, dismissedFound = '';

const mgr = () => (S && S.nodemgr) || {pairing: {incoming: [], outgoing: []}, scan: {found: []}};
const incoming = () => mgr().pairing.incoming;
const newFound = () => (S && S.settings.nodes && S.settings.nodes.auto_search && S.settings.nodes.mode === 'verbund')
  ? (mgr().scan.found || []).filter(f => !f.self && !f.known) : [];

function renderDialog(){
  const inc = incoming()[0];
  if(!inc){ if(dlg.open) dlg.close(); return; }
  $('#nodePairBody').innerHTML = `<h3 id="nodePairTitle">"${esc(inc.name)}" wants to connect</h3>
    <dl><dt>Address</dt><dd>${esc(hostOf(inc.url))}</dd><dt>Version</dt><dd>${esc(inc.version || 'unknown')}</dd>
    <dt>Request</dt><dd>${inc.age < 60 ? inc.age + ' seconds' : Math.round(inc.age / 60) + ' min'} ago</dd>
    <dt>Code</dt><dd><span class="node-code" style="font-size:18px;padding:7px 11px">${esc(inc.code.replace(/^(\d{3})(\d{3})$/, '$1 $2'))}</span></dd></dl>
    <p class="help" style="margin:0;font-size:12px">Check that the same code is shown on ${esc(inc.name)}. Once connected, both machines may hand conversions over to each other, control each other's drives remotely and see each other's jobs. You can unpair at any time.</p>
    <div class="rowend"><button type="button" class="secondary" data-pair="deny" data-rid="${esc(inc.rid)}">Decline</button><button type="button" class="primary" style="width:auto" data-pair="accept" data-rid="${esc(inc.rid)}">Connect</button></div>`;
}

function renderBar(){
  const inc = incoming()[0], found = newFound();
  if(inc){
    bar.innerHTML = `<span class="grow"><strong>${esc(inc.name)}</strong> wants to connect to this machine.</span><button class="secondary" data-pair="open">View</button>`;
    bar.hidden = false;
  }else if(found.length && dismissedFound !== found.map(f => f.id).join()){
    bar.innerHTML = `<span class="grow">Newly found on the network: <strong>${esc(found.map(f => f.name).join(', '))}</strong></span><a class="secondary" href="#/settings/nodes">View</a><button class="secondary" data-pair="dismiss" aria-label="Hide notice">✕</button>`;
    bar.hidden = false;
  }else bar.hidden = true;
}

// Messages about our own requests as soon as their state changes
function announce(){
  for(const o of mgr().pairing.outgoing){
    const was = seen[o.rid]; seen[o.rid] = o.status;
    if(!was || was === o.status || o.status === 'waiting') continue;
    if(o.status === 'ok') toast(`Paired with ${o.name} ✓`);
    else if(o.status !== 'cancelled') toast(`${o.name}: ${o.error || 'Pairing did not succeed.'}`, true);
  }
}

delegate('[data-pair]', 'click', async (e, b) => {
  const act = b.dataset.pair;
  if(act === 'open'){ renderDialog(); if(incoming()[0] && !dlg.open) dlg.showModal(); return; }
  if(act === 'dismiss'){ dismissedFound = newFound().map(f => f.id).join(); renderBar(); return; }
  b.disabled = true;
  try{
    await api(`/api/nodes/pair-incoming/${b.dataset.rid}/${act}`);
    if(act === 'accept') toast('Paired ✓');
    dlg.close();
  }catch{ b.disabled = false; }
});

onState(() => { renderBar(); if(dlg.open) renderDialog(); announce(); });
