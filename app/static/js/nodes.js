// Einstellungsabschnitt „Rechner“: Betriebsart, Name, Auffindbarkeit, Rechnerliste, Suche im Netz, Hinzufügen per Adresse.
// Aufbau 1:1 nach docs/mockups/paket-c.html. Die Liste ist kein Formularfeld: ihre Knöpfe rufen eigene Endpunkte auf (/api/nodes, /api/discovery).
// Gespeichert werden über die Einstellungsseite nur Name, Betriebsart, Auffindbarkeit und die Suchoptionen (Namensraum `nodes`).
import { $, S, api, delegate, dec, esc, setHtml, toast } from './core.js';
import { onState, registerSettingsSection } from './registry.js';
import { agoSrv, encoderChips, gb, hostOf, spanTxt } from './nodes-util.js';

let editing = '', scanOpen = false, addRes = null;
const tests = {};                                   // nid -> Ergebnis des letzten Verbindungstests
const mgr = () => (S && S.nodemgr) || {nodes: [], pairing: {incoming: [], outgoing: []}, scan: {found: []}};
const saved = () => (S && S.settings && S.settings.nodes) || {mode: 'standalone', discoverable: false, name: '', scan_nets: '', auto_search: false};
const active = () => saved().mode === 'verbund';
const waitingFor = url => mgr().pairing.outgoing.find(o => o.status === 'waiting' && o.url === url);
const code = c => String(c || '').replace(/^(\d{3})(\d{3})$/, '$1 $2');

registerSettingsSection({
  id: 'nodes', label: 'Rechner', order: 30, icon: '⇄', description: 'Verbund, Auffindbarkeit und gekoppelte Rechner',
  render(el, s){
    const n = s.nodes || saved(), inst = (S && S.capacity && S.capacity.instance) || '';
    el.innerHTML = `<div class="node-section" id="nodeSection">
      <p class="node-lead">Mehrere Installationen von MakeMKV-Web bilden einen Verbund: gemeinsame Aufträge, Übergabe von Konvertierungen, Fernsteuerung der Laufwerke.</p>
      <section class="panel node-self">
        <div class="node-self-grid">
          <div class="node-field"><label for="nodeName">Name dieses Rechners</label><input class="input" type="text" id="nodeName" maxlength="40" placeholder="${esc(inst)}" value="${esc(n.name)}"><p class="help">So sehen ihn die anderen Rechner. Standard: der Hostname${inst ? ` (${esc(inst)})` : ''}.</p></div>
          <div class="node-field"><label>Betriebsart</label>
            <div class="node-seg" role="radiogroup" aria-label="Betriebsart"><label><input type="radio" name="nodeMode" value="verbund" ${n.mode === 'verbund' ? 'checked' : ''}>Im Verbund</label><label><input type="radio" name="nodeMode" value="standalone" ${n.mode !== 'verbund' ? 'checked' : ''}>Eigenständig</label></div>
            <p class="help">Eigenständig: keine anderen Rechner, keine Suche, keine Verbund-Knöpfe.</p></div>
        </div>
        <p class="node-note info" id="nodeStandNote" style="margin:0" hidden><strong>Eigenständiger Betrieb.</strong> Dieser Rechner arbeitet für sich: keine Verbindung zu anderen Rechnern, nicht auffindbar, keine Verbund-Knöpfe. Die Liste unten bleibt gespeichert und wird beim Zurückschalten wieder aktiv.</p>
        <label class="node-opt" id="nodeDiscLabel"><input class="check" type="checkbox" id="nodeDisc" ${n.discoverable ? 'checked' : ''}><span>Im Netz auffindbar<p class="help">Andere Rechner können diesen hier bei „Rechner im Netz suchen“ finden und eine Kopplung anfragen. Gekoppelt wird nur nach deiner Bestätigung. Aus = nur per Adresse erreichbar.</p></span></label>
        <p class="help" style="margin:0">Name, Betriebsart und Auffindbarkeit speichert der Speichern-Knopf unten. Die Liste wirkt sofort.</p>
      </section>
      <div id="nodeSearchWrap" hidden>
        <section class="panel"><div class="panel-head"><div><h2>Rechner im Netz suchen</h2><span class="sub" id="nodeScanSub"></span></div><div class="node-actionsbar" id="nodeScanBtns"></div></div>
          <div id="nodeScanBody"></div></section>
        <p class="node-note info" style="margin:10px 0 0"><strong>Nicht gefunden?</strong> Ein Rechner taucht nur auf, wenn bei ihm unter Einstellungen › Rechner „Im Netz auffindbar“ eingeschaltet ist. Rechner mit älterer Version lassen sich nur per Adresse hinzufügen. Läuft dieser Rechner in Docker, durchsucht er das Netz, über das du die Seite aufgerufen hast; ein anderes Netz trägst du unten ein.</p>
        <div class="node-field" style="margin-top:10px"><label for="nodeNets">Netz für die Suche (optional)</label><input class="input" type="text" id="nodeNets" placeholder="automatisch, z. B. 192.168.178.0/24, 10.0.0.0/24" value="${esc(n.scan_nets)}"></div>
        <label class="node-opt" style="margin-top:10px"><input class="check" type="checkbox" id="nodeAuto" ${n.auto_search ? 'checked' : ''}><span>Im Hintergrund regelmäßig suchen<p class="help">Alle 10 Minuten. Neue Rechner werden nur vorgeschlagen, nie automatisch verbunden.</p></span></label>
      </div>
      <section class="panel node-needs"><div class="panel-head"><div><h2>Rechner im Verbund</h2><span class="sub" id="nodeListSub"></span></div>
        <div class="node-actionsbar"><button type="button" class="secondary" data-na="search">Rechner im Netz suchen</button><button type="button" class="secondary" data-na="addtoggle">+ Adresse hinzufügen</button></div></div>
        <div class="node-add" id="nodeAdd" hidden>
          <div class="node-field"><label for="nodeAddUrl">Adresse</label><input class="input" type="text" id="nodeAddUrl" placeholder="192.168.178.189" autocomplete="off"><p class="help">IP oder Name, optional mit Port (Standard 8780).</p></div>
          <div class="node-field"><label for="nodeAddName">Anzeigename (optional)</label><input class="input" type="text" id="nodeAddName" maxlength="40" placeholder="wird vom Rechner übernommen" autocomplete="off"></div>
          <button type="button" class="primary" style="width:auto" data-na="check">Prüfen</button>
        </div>
        <div class="node-add-result" id="nodeAddRes"></div>
        <div class="node-list" id="nodeList"></div></section>
    </div>`;
    const modeChanged = () => {
      const v = ($('input[name=nodeMode]:checked', el) || {}).value, live = v === 'verbund';
      $('#nodeStandNote').hidden = live; $('#nodeDisc').disabled = !live; $('#nodeDiscLabel').style.opacity = live ? '' : '.45';
    };
    el.addEventListener('change', e => { if(e.target.name === 'nodeMode') modeChanged(); });
    $('#nodeAddUrl').addEventListener('keydown', e => { if(e.key === 'Enter'){ e.preventDefault(); doCheck(); } });
    modeChanged(); renderAll();
  },
  collect(){
    if(!$('#nodeName')) return {nodes: {}};
    return {nodes: {name: $('#nodeName').value.trim(), mode: ($('input[name=nodeMode]:checked') || {}).value || 'standalone',
      discoverable: $('#nodeDisc').checked, scan_nets: $('#nodeNets').value.trim(), auto_search: $('#nodeAuto').checked}};
  },
});

// ---------- Darstellung
function chips(p){
  const out = [], d = p.drives || [];
  out.push(`<span class="node-chip">${d.length ? `${d.length} Laufwerk${d.length > 1 ? 'e' : ''} · ${esc(d.map(x => x.name).join(', '))}` : 'Kein Laufwerk'}</span>`);
  if(p.cores) out.push(`<span class="node-chip">${p.cores} Threads${p.mem ? ' · ' + gb(p.mem) + ' RAM' : ''}</span>`);
  if(p.cores && p.load != null) out.push(`<span class="node-chip">Last ${dec(Number(p.load).toFixed(1))}</span>`);
  const cv = (p.conversions || []).filter(c => c.status === 'running' || c.status === 'queued'), run = cv.filter(c => c.status === 'running');
  const job = (p.jobs || [])[0];
  if(cv.length) out.push(`<span class="node-chip work">${p.conv_paused ? 'Konvertierung pausiert' : 'Konvertiert'} ${cv.length} Datei${cv.length > 1 ? 'en' : ''}${run.length ? ' · ' + Math.round(run.reduce((a, c) => a + (c.pct || 0), 0) / run.length * 100) + ' %' : ''}</span>`);
  if(job) out.push(`<span class="node-chip work">${job.kind === 'scan' ? 'Analysiert' : job.kind === 'backup' ? 'Backup' : 'Rippt'} „${esc(job.title || job.name || '')}“ · ${Math.round((job.kind === 'scan' ? job.total : job.overall) * 100)} %</span>`);
  const enc = encoderChips(p);
  out.push(p.legacy ? '<span class="node-chip">nur x265</span>' : enc.length ? `<span class="node-chip">${esc(enc.join(' · '))}</span>` : '');
  return out.join('');
}

function note(rec, p, on, known, old, lost, wait){
  const t = tests[rec.nid], out = [];
  if(t) out.push(t.ok ? `<p class="node-note"><span class="node-test">Verbindung ok · ${t.ms} ms</span></p>` : `<p class="node-note err">${esc(t.error)}</p>`);
  if(wait) out.push(`<p class="node-note info"><strong>Bitte auf ${esc(wait.name)} bestätigen.</strong> Dort erscheint die Anfrage mit diesem Code:<span class="node-code-inline"><span class="node-code">${esc(code(wait.code))}</span></span></p>`);
  else if(lost) out.push(`<p class="node-note err">${esc(rec.name)} hat die Kopplung gelöst oder abgelehnt. Aufträge und Fernsteuerung sind aus, bis ihr euch neu koppelt.</p>`);
  else if(p && p.id_mismatch) out.push('<p class="node-note warn">Unter dieser Adresse meldet sich ein anderer Rechner (Adresse neu vergeben?). Entfernen und neu koppeln.</p>');
  else if(!on && known) out.push(`<p class="node-note">Nicht erreichbar. Rechner aus, im Ruhezustand oder Netzwerk getrennt?${rec.paired ? ' Die Kopplung bleibt bestehen, sobald er wieder da ist, geht es weiter.' : ''}</p>`);
  else if(old) out.push('<p class="node-note warn">Läuft noch auf dem alten Stand: ohne Kopplung und ohne Fähigkeitsmeldung. Aufträge sehen, Übergabe und Fernsteuerung gehen wie bisher; neue Konvertier-Einstellungen (Codec, AV1 …) sind für diesen Rechner ausgegraut.</p>');
  else if(on && !rec.paired) out.push(`<p class="node-note info">${rec.origin === 'peers' ? 'Aus der früheren Einstellung <code>PEERS</code> übernommen und wie bisher ohne Prüfung genutzt. ' : 'Noch nicht gekoppelt, wird ohne Prüfung genutzt. '}„Koppeln“ ersetzt das durch ein Token, das nur ihr beide kennt.</p>`);
  return out.join('');
}

function rowHtml(rec, live){
  const p = live ? (S.peers || []).find(x => x.name === rec.name) : null, wait = waitingFor(rec.url);
  const on = !!(p && p.reachable), known = !!(p && p.last_seen > 0), old = !!(on && p.legacy), lost = !!(p && p.trust === 'lost');
  const badges = [];
  if(live && !on) badges.push('<span class="st">Offline</span>');
  badges.push(wait ? '<span class="st warn">Wartet auf Bestätigung</span>' : lost ? '<span class="st warn">Kopplung gelöst</span>' : rec.paired ? '<span class="st ok">Gekoppelt</span>'
    : old || (known && p.legacy) ? '<span class="st warn">Ältere Version</span>' : '<span class="st warn">Nicht gekoppelt</span>');
  if(old && rec.paired) badges.pop();
  const meta = [`<span>${esc(hostOf(rec.url))}</span>`];
  if(on) meta.push(`<span>online seit <b>${spanTxt((p.started ? p.now - p.started : S.now - p.online_since))}</b></span>`);
  else if(known) meta.push(`<span>zuletzt gesehen <b>${agoSrv(p.last_seen)}</b></span>`);
  if(p && (on || known)) meta.push(`<span>Version <b>${esc(p.version || (p.legacy ? 'unbekannt (alt)' : '?'))}</b></span>`);
  const b = (a, t, cls = 'secondary') => `<button type="button" class="${cls}" data-na="${a}" data-nid="${esc(rec.nid)}" data-url="${esc(rec.url)}">${t}</button>`;
  const btns = !live ? '' : [b('test', 'Verbindung testen'), editing === rec.nid ? '' : b('rename', 'Umbenennen'),
    wait ? `<button type="button" class="secondary" data-na="withdraw" data-rid="${esc(wait.rid)}">Anfrage zurückziehen</button>`
      : lost ? b('pair', 'Neu koppeln', 'primary" style="width:auto') + b('remove', 'Entfernen', 'secondary danger')
      : rec.paired ? b('unpair', 'Entkoppeln', 'secondary danger')
      : old || (known && p.legacy) ? b('remove', 'Entfernen', 'secondary danger') : b('pair', 'Koppeln', 'primary" style="width:auto') + b('remove', 'Entfernen', 'secondary danger')].join('');
  const name = editing === rec.nid ? `<span class="node-name-edit"><input class="input" type="text" id="nodeRen" maxlength="40" value="${esc(rec.name)}" data-nid="${esc(rec.nid)}"><button type="button" class="primary" style="width:auto;padding:7px 12px" data-na="renok" data-nid="${esc(rec.nid)}">OK</button><button type="button" class="secondary" data-na="renx">Abbrechen</button></span>`
    : `<span class="node-name">${esc(rec.name)}</span>`;
  return `<article class="node ${on ? (old ? 'on old' : 'on') : 'off'}"><div class="node-head"><span class="node-dot" title="${on ? 'Online' : 'Offline'}"></span>${name}<span class="node-badges">${badges.join('')}</span><div class="node-btns">${btns}</div></div>
    <div class="node-meta">${meta.join('')}</div>${on ? `<div class="node-facts">${chips(p)}</div>` : ''}${live ? note(rec, p, on, known, old, lost, wait) : ''}</article>`;
}

function renderList(){
  const m = mgr(), live = active(), recs = m.nodes, urls = new Set(recs.map(r => r.url));
  const pending = m.pairing.outgoing.filter(o => o.status === 'waiting' && !urls.has(o.url)).map(o => `<article class="node"><div class="node-head"><span class="node-dot" style="background:var(--amber)"></span><span class="node-name">${esc(o.name)}</span><span class="node-badges"><span class="st warn">Wartet auf Bestätigung</span></span><div class="node-btns"><button type="button" class="secondary" data-na="withdraw" data-rid="${esc(o.rid)}">Anfrage zurückziehen</button></div></div>
    <div class="node-meta"><span>${esc(hostOf(o.url))}</span></div><p class="node-note info"><strong>Bitte auf ${esc(o.name)} bestätigen.</strong> Dort erscheint die Anfrage „${esc((S.node || {}).name || '')} möchte sich verbinden“ mit diesem Code:<span class="node-code-inline"><span class="node-code">${esc(code(o.code))}</span></span></p></article>`);
  const on = live ? recs.filter(r => (S.peers || []).some(p => p.name === r.name && p.reachable)).length : 0;
  $('#nodeListSub').textContent = live ? `${recs.length} eingetragen · ${on} online` : `ruht · ${recs.length} eingetragen`;
  const list = $('#nodeList');
  list.closest('.panel').classList.toggle('node-dim', !live);
  list.closest('.panel').setAttribute('aria-disabled', !live);
  setHtml(list, pending.join('') + recs.map(r => rowHtml(r, live)).join('') || '<div class="empty">Noch keine Rechner eingetragen. Suche im Netz oder füge einen per Adresse hinzu.</div>');
}

function renderScan(){
  const wrap = $('#nodeSearchWrap'); wrap.hidden = !(scanOpen && active());
  if(wrap.hidden) return;
  const sc = mgr().scan, found = sc.found || [];
  $('#nodeScanSub').textContent = sc.nets && sc.nets.length ? `Netz ${sc.nets.join(', ')}` : '';
  setHtml($('#nodeScanBtns'), sc.running ? '<button type="button" class="secondary" data-na="scancancel">Abbrechen</button>' : '<button type="button" class="secondary" data-na="search">Erneut suchen</button><button type="button" class="secondary" data-na="scanclose">Schließen</button>');
  const head = sc.running ? `<div class="node-scan-head"><span class="spin"></span><span>Suche läuft … ${sc.done} von ${sc.total} Adressen geprüft</span></div><div class="node-scanbar"><div style="width:${sc.total ? Math.round(sc.done / sc.total * 100) : 0}%"></div></div>`
    : `<div class="node-scan-head"><span>Suche beendet · ${found.length ? found.length + ' gefunden' : 'nichts gefunden'}${sc.error ? ' · ' + esc(sc.error) : ''}</span></div>`;
  const rows = found.map(f => {
    const w = waitingFor(f.url);
    const act = f.self ? '<span class="st">Das bist du</span>' : w ? '<span class="st warn">Wartet auf Bestätigung</span>' : f.paired ? '<span class="st ok">Gekoppelt</span>'
      : `<button type="button" class="primary" style="width:auto" data-na="pair" data-url="${esc(f.url)}">${f.known ? 'Koppeln' : 'Verbinden'}</button>`;
    return `<div class="node-found"><span class="node-dot" style="background:${f.self ? '#4a5568' : 'var(--green)'}"></span><div class="grow"><strong>${esc(f.name)}</strong><small>${esc(hostOf(f.url))}${f.self ? ' · dieser Rechner' : ` · Version ${esc(f.version || '?')}${f.cores ? ' · ' + f.cores + ' Threads' : ''}${f.mem ? ' · ' + gb(f.mem) + ' RAM' : ''}${f.known && !f.paired ? ' · schon in der Liste' : ''}`}</small></div>${act}</div>`;
  }).join('');
  setHtml($('#nodeScanBody'), head + (rows ? `<div class="node-list">${rows}</div>` : ''));
}

function renderAdd(){
  const r = addRes, el = $('#nodeAddRes');
  if(!r){ setHtml(el, ''); return; }
  const name = esc(r.name || hostOf(r.url || ''));
  const body = !r.ok ? `<p class="node-note err" style="margin:0">${esc(r.error)}</p>` : r.self ? '<p class="node-note" style="margin:0">Das ist dieser Rechner.</p>'
    : r.known ? `<p class="node-note" style="margin:0">Schon in der Liste (als „${esc(r.known)}“).</p>`
    : r.legacy ? `<div class="node-head"><span class="node-dot" style="background:var(--amber)"></span><span class="node-name">${name}</span><span class="node-badges"><span class="st warn">Ältere Version</span></span><div class="node-btns"><button type="button" class="secondary" data-na="addold">Ohne Kopplung hinzufügen</button></div></div>
      <p class="node-note warn" style="margin:8px 0 0 20px"><strong>Kann nicht gekoppelt werden.</strong> ${name} kennt die Kopplung noch nicht. Er lässt sich trotzdem wie bisher nutzen (Aufträge sehen, Laufwerke steuern, Übergabe), aber ohne Token und ohne neuere Funktionen; Passwortschutz dort würde den Zugriff verhindern.</p>`
    : `<div class="node-head"><span class="node-dot" style="background:var(--green)"></span><span class="node-name">${name}</span><span class="node-badges"><span class="st ok">Erreichbar</span></span><div class="node-btns"><button type="button" class="primary" style="width:auto" data-na="pair" data-url="${esc(r.url)}">Kopplung anfragen</button></div></div>
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

// ---------- Aktionen
async function doCheck(){
  const url = $('#nodeAddUrl').value.trim(); if(!url) return;
  try{ addRes = await api('/api/nodes/check', 'POST', {url}); }catch{ return; }
  addRes.name = addRes.name || ''; renderAdd();
}
const pair = async url => { try{ const r = await api('/api/nodes/pair', 'POST', {url}); toast(`Anfrage an ${r.name} gesendet. Bitte dort bestätigen (Code ${code(r.code)}).`); addRes = null; $('#nodeAdd').hidden = true; }catch{} renderAll(); };

delegate('#nodeSection [data-na]', 'click', async (e, b) => {
  const a = b.dataset.na, nid = b.dataset.nid, name = () => ((mgr().nodes.find(n => n.nid === nid) || {}).name || '');
  if(a === 'search'){ scanOpen = true; try{ await api('/api/discovery/scan'); }catch{} renderAll(); }
  else if(a === 'scancancel') api('/api/discovery/scan/cancel');
  else if(a === 'scanclose'){ scanOpen = false; renderAll(); }
  else if(a === 'addtoggle'){ const f = $('#nodeAdd'); f.hidden = !f.hidden; if(!f.hidden) $('#nodeAddUrl').focus(); }
  else if(a === 'check') doCheck();
  else if(a === 'addold'){
    try{ await api('/api/nodes', 'POST', {url: addRes.url, name: $('#nodeAddName').value.trim() || addRes.name}); toast('Rechner hinzugefügt (ohne Kopplung).'); addRes = null; $('#nodeAdd').hidden = true; $('#nodeAddUrl').value = ''; }catch{}
    renderAll();
  }
  else if(a === 'pair') pair(b.dataset.url);
  else if(a === 'withdraw'){ try{ await api(`/api/nodes/pair-outgoing/${b.dataset.rid}/cancel`); }catch{} }
  else if(a === 'test'){
    b.disabled = true; try{ tests[nid] = await api(`/api/nodes/${nid}/test`); }catch{ tests[nid] = {ok: false, error: 'Test fehlgeschlagen.'}; }
    setTimeout(() => { delete tests[nid]; renderAll(); }, 10000); renderAll();
  }
  else if(a === 'rename'){ editing = nid; renderList(); const i = $('#nodeRen'); if(i){ i.focus(); i.select(); } }
  else if(a === 'renx'){ editing = ''; renderAll(); }
  else if(a === 'renok') await rename(nid);
  else if(a === 'unpair'){ if(confirm(`Kopplung mit ${name()} lösen? Der Rechner bleibt in der Liste, ihr vertraut euch dann wieder ohne Token.`)){ try{ await api(`/api/nodes/${nid}/unpair`); toast('Entkoppelt.'); }catch{} } }
  else if(a === 'remove'){ if(confirm(`${name()} aus der Liste entfernen?`)){ try{ await api(`/api/nodes/${nid}`, 'DELETE'); }catch{} } }
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
