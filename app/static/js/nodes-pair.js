// Kopplung: Hinweisleiste und Bestätigungsdialog für Anfragen anderer Rechner (auf jeder Seite), Meldungen zu eigenen Anfragen,
// Hinweis auf neu gefundene Rechner (Hintergrundsuche). Die Rechnerliste selbst steht in js/nodes.js.
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
  $('#nodePairBody').innerHTML = `<h3 id="nodePairTitle">„${esc(inc.name)}“ möchte sich verbinden</h3>
    <dl><dt>Adresse</dt><dd>${esc(hostOf(inc.url))}</dd><dt>Version</dt><dd>${esc(inc.version || 'unbekannt')}</dd>
    <dt>Anfrage</dt><dd>vor ${inc.age < 60 ? inc.age + ' Sekunden' : Math.round(inc.age / 60) + ' Min.'}</dd>
    <dt>Code</dt><dd><span class="node-code" style="font-size:18px;padding:7px 11px">${esc(inc.code.replace(/^(\d{3})(\d{3})$/, '$1 $2'))}</span></dd></dl>
    <p class="help" style="margin:0;font-size:12px">Prüfe, dass derselbe Code auf ${esc(inc.name)} steht. Nach dem Verbinden dürfen beide Rechner einander Konvertierungen übergeben, Laufwerke fernsteuern und Aufträge sehen. Entkoppeln geht jederzeit.</p>
    <div class="rowend"><button type="button" class="secondary" data-pair="deny" data-rid="${esc(inc.rid)}">Ablehnen</button><button type="button" class="primary" style="width:auto" data-pair="accept" data-rid="${esc(inc.rid)}">Verbinden</button></div>`;
}

function renderBar(){
  const inc = incoming()[0], found = newFound();
  if(inc){
    bar.innerHTML = `<span class="grow"><strong>${esc(inc.name)}</strong> möchte sich mit diesem Rechner verbinden.</span><button class="secondary" data-pair="open">Ansehen</button>`;
    bar.hidden = false;
  }else if(found.length && dismissedFound !== found.map(f => f.id).join()){
    bar.innerHTML = `<span class="grow">Neu im Netz gefunden: <strong>${esc(found.map(f => f.name).join(', '))}</strong></span><a class="secondary" href="#/einstellungen/nodes">Ansehen</a><button class="secondary" data-pair="dismiss" aria-label="Hinweis ausblenden">✕</button>`;
    bar.hidden = false;
  }else bar.hidden = true;
}

// Meldungen zu eigenen Anfragen, sobald sich ihr Zustand ändert
function announce(){
  for(const o of mgr().pairing.outgoing){
    const was = seen[o.rid]; seen[o.rid] = o.status;
    if(!was || was === o.status || o.status === 'waiting') continue;
    if(o.status === 'ok') toast(`Mit ${o.name} gekoppelt ✓`);
    else if(o.status !== 'cancelled') toast(`${o.name}: ${o.error || 'Kopplung nicht zustande gekommen.'}`, true);
  }
}

delegate('[data-pair]', 'click', async (e, b) => {
  const act = b.dataset.pair;
  if(act === 'open'){ renderDialog(); if(incoming()[0] && !dlg.open) dlg.showModal(); return; }
  if(act === 'dismiss'){ dismissedFound = newFound().map(f => f.id).join(); renderBar(); return; }
  b.disabled = true;
  try{
    await api(`/api/nodes/pair-incoming/${b.dataset.rid}/${act}`);
    if(act === 'accept') toast('Gekoppelt ✓');
    dlg.close();
  }catch{ b.disabled = false; }
});

onState(() => { renderBar(); if(dlg.open) renderDialog(); announce(); });
