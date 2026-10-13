// Hand-over of conversions to another machine (dialog).
import { $, S, api, dec, delegate, esc, toast } from './core.js';
import { onState } from './registry.js';

document.body.insertAdjacentHTML('beforeend', `
<dialog id="hoDlg">
  <form method="dialog" id="hoForm" onsubmit="return false">
    <h3>Hand over to another machine</h3>
    <p class="help" id="hoInfo" style="margin:0"></p>
    <div id="hoPeers" class="peers"></div>
    <div class="rowend"><button type="button" class="secondary" id="ho-cancel">Cancel</button><button type="button" class="primary" style="width:auto" id="ho-go" disabled>Hand over</button></div>
  </form>
</dialog>
`);
const hoDlg = $('#hoDlg');
function peerOption(p, checked){
  const usable = p.reachable && p.has_handover;
  const why = !p.reachable ? 'not reachable' : !p.has_handover ? 'older version – update it first' : `${p.cores} threads · load ${dec((p.load||0).toFixed(1))} · ${p.conv_active} job${p.conv_active===1?'':'s'}${p.conv_paused ? ' · paused' : ''}`;
  return `<label class="peer ${usable?'':'off'}"><input type="radio" name="hopeer" value="${esc(p.name)}" ${checked?'checked':''} ${usable?'':'disabled'}><div><strong>${esc(p.name)}</strong><div class="meta">${esc(why)}</div></div></label>`;
}
function fillHandover(){
  const act = (S.conversions||[]).filter(c => c.status==='queued' || c.status==='running'), running = act.filter(c => c.status==='running').length;
  const busy = S.drives.some(d => d.job);
  $('#hoInfo').textContent = busy ? 'A rip, a backup or an analysis is running on this machine – the drive is attached here and cannot be handed over. Please wait for it or cancel it first.'
    : act.length ? `${act.length} conversion${act.length===1?' is':'s are'} handed over${running ? ` (${running} running – their progress is lost, the other machine starts from the beginning)` : ''}. Files that are still buffered locally are transferred to the NAS first and converted there – please do not shut down until then (shown above when it is safe).`
    : 'There is no conversion here that could be handed over.';
  const usable = (S.peers||[]).filter(p => p.reachable && p.has_handover);
  const best = usable.slice().sort((a,b) => (a.load/(a.cores||1)) - (b.load/(b.cores||1)))[0];
  const chosen = ($('#hoPeers input:checked')||{}).value || (best && best.name);
  $('#hoPeers').innerHTML = (S.peers||[]).map(p => peerOption(p, p.name === chosen)).join('') || '<div class="empty">No other machines added. Under Settings › Machines they can be found on the network and paired.</div>';
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
    if(r.errors.length) alert(`${r.handed.length} handed over, ${r.errors.length} not:\n` + r.errors.map(x => '• ' + x).join('\n'));
    else toast(`${r.handed.length} job${r.handed.length===1?'':'s'} handed over to ${t}.`);
  }catch{ $('#ho-go').disabled = false; }
});

onState(() => {
  if(hoDlg.open) fillHandover();
  const hasPeers = (S.peers||[]).length > 0;
  document.querySelectorAll('.handover-btn').forEach(b => { b.hidden = !hasPeers; });
});
