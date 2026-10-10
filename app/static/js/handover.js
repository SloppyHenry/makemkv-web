// Übergabe von Konvertierungen an einen anderen Rechner (Dialog).
import { $, S, api, dec, delegate, esc, toast } from './core.js';
import { onState } from './registry.js';

document.body.insertAdjacentHTML('beforeend', `
<dialog id="hoDlg">
  <form method="dialog" id="hoForm" onsubmit="return false">
    <h3>Übergabe an einen anderen Rechner</h3>
    <p class="help" id="hoInfo" style="margin:0"></p>
    <div id="hoPeers" class="peers"></div>
    <div class="rowend"><button type="button" class="secondary" id="ho-cancel">Abbrechen</button><button type="button" class="primary" style="width:auto" id="ho-go" disabled>Übergeben</button></div>
  </form>
</dialog>
`);
const hoDlg = $('#hoDlg');
function peerOption(p, checked){
  const usable = p.reachable && p.has_handover;
  const why = !p.reachable ? 'nicht erreichbar' : !p.has_handover ? 'ältere Version – erst aktualisieren' : `${p.cores} Threads · Last ${dec((p.load||0).toFixed(1))} · ${p.conv_active} Auftrag${p.conv_active===1?'':'e'}${p.conv_paused ? ' · pausiert' : ''}`;
  return `<label class="peer ${usable?'':'off'}"><input type="radio" name="hopeer" value="${esc(p.name)}" ${checked?'checked':''} ${usable?'':'disabled'}><div><strong>${esc(p.name)}</strong><div class="meta">${esc(why)}</div></div></label>`;
}
function fillHandover(){
  const act = (S.conversions||[]).filter(c => c.status==='queued' || c.status==='running'), running = act.filter(c => c.status==='running').length;
  const busy = S.drives.some(d => d.job);
  $('#hoInfo').textContent = busy ? 'Auf diesem Rechner läuft ein Rip, ein Backup oder eine Analyse – das Laufwerk hängt hier und lässt sich nicht übergeben. Bitte erst abwarten oder abbrechen.'
    : act.length ? `${act.length} Konvertierung${act.length===1?'':'en'} werden übergeben${running ? ` (${running} laufend – ihr Fortschritt geht verloren, der andere Rechner beginnt von vorn)` : ''}. Dateien, die noch lokal zwischengespeichert sind, werden zuerst ins NAS übertragen und dann dort konvertiert – bitte so lange nicht herunterfahren (oben steht, wann es soweit ist).`
    : 'Hier liegt keine Konvertierung an, die sich übergeben ließe.';
  const usable = (S.peers||[]).filter(p => p.reachable && p.has_handover);
  const best = usable.slice().sort((a,b) => (a.load/(a.cores||1)) - (b.load/(b.cores||1)))[0];
  const chosen = ($('#hoPeers input:checked')||{}).value || (best && best.name);
  $('#hoPeers').innerHTML = (S.peers||[]).map(p => peerOption(p, p.name === chosen)).join('') || '<div class="empty">Keine anderen Rechner eingetragen. Unter Einstellungen › Rechner lassen sie sich im Netz suchen und koppeln.</div>';
  $('#ho-go').disabled = busy || !act.length || !usable.length;
}
delegate('.handover-btn', 'click', () => { fillHandover(); hoDlg.showModal(); });
delegate('#ho-cancel', 'click', () => hoDlg.close());
delegate('#ho-go', 'click', async () => {
  const t = ($('#hoPeers input:checked')||{}).value; if(!t) return;
  $('#ho-go').disabled = true;
  try{
    const r = await api('/api/handover', 'POST', {target: t});
    hoDlg.close();
    if(r.errors.length) alert(`${r.handed.length} übergeben, ${r.errors.length} nicht:\n` + r.errors.map(x => '• ' + x).join('\n'));
    else toast(`${r.handed.length} Auftrag${r.handed.length===1?'':'e'} an ${t} übergeben.`);
  }catch{ $('#ho-go').disabled = false; }
});

onState(() => {
  if(hoDlg.open) fillHandover();
  const hatPeers = (S.peers||[]).length > 0;
  document.querySelectorAll('.handover-btn').forEach(b => { b.hidden = !hatPeers; });
});
