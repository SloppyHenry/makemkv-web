// Kopfzeile: Menü der Ansichten (aus registerView), Einstellungen-Knopf, Hinweisleisten, Seitentitel. PB ersetzt das Menü durch eine Navigation.
import { $, S, conn, delegate, esc, setHtml } from './core.js';
import { currentView, emit, getViews, navigate, on, onState } from './registry.js';

function renderBanners(){
  const b = [];
  if(conn.failed) b.push(['err','Verbindung zum Server getrennt – verbinde neu …']);
  const o = S && S.output;
  if(o){
    if(o.stalled) b.push(['warn',`Das Ziel ${o.dir} antwortet nur sehr langsam (Netzwerk/NAS überlastet?). Rips laufen dadurch langsamer.`]);
    else if(!o.mounted) b.push(['warn',`${o.preferred} ist nicht eingehängt – es wird vorübergehend lokal auf diesem Server gespeichert (${o.dir}).`]);
  }
  setHtml($('#banners'), b.map(([c,t]) => `<div class="banner ${c}">⚠ ${esc(t)}</div>`).join(''));
}

function renderMenu(){
  const cur = currentView();
  $('#menu').innerHTML = getViews().map(v => `<button role="menuitem" data-view="${esc(v.id)}" class="${v.id === cur ? 'on' : ''}">${esc(v.label)}</button>`).join('');
}
on('view', renderMenu);
on('conn', renderBanners);
$('#btn-menu').addEventListener('click', e => { e.stopPropagation(); $('#menu').classList.toggle('hidden'); });
document.addEventListener('click', e => { if(!e.target.closest('.menuwrap')) $('#menu').classList.add('hidden'); });
delegate('#menu [data-view]', 'click', (e, b) => { navigate(b.dataset.view); $('#menu').classList.add('hidden'); });
$('#btn-set').addEventListener('click', () => emit('settings:open'));

onState(S => {
  renderBanners();
  let pct = null;
  for(const x of S.drives) if(x.job && x.job.kind!=='scan') pct = Math.round((x.job.overall||0)*100);
  document.title = pct!==null ? `${pct} % – MakeMKV Web` : 'MakeMKV Web';
});
