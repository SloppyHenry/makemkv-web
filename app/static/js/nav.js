// Kopfzeile: Navigation (Reiter aus registerView, Plakette für laufende Aufträge), Laufwerksleiste, Hinweisleisten, Seitentitel.
import { $, S, conn, esc, setHtml } from './core.js';
import { currentView, getViews, on, onState } from './registry.js';

const SETTINGS = 'einstellungen';
let dirty = false;

// ---------- laufende Aufträge (eigener Rechner und erreichbare andere Rechner)
const convActive = o => o.status === 'queued' || o.status === 'running';
const upActive = o => ['queued', 'copying', 'retry'].includes(o.status);
function activeJobs(){
  if(!S) return 0;
  let n = S.drives.filter(d => d.job).length + (S.conversions || []).filter(convActive).length + (S.uploads || []).filter(upActive).length;
  for(const p of (S.peers || [])){
    if(!p.reachable) continue;
    n += (p.conversions || []).filter(convActive).length + (p.uploads || []).filter(upActive).length;
    n += Array.isArray(p.drives) ? p.drives.filter(d => d.job).length : (p.jobs || []).length;
  }
  return n;
}
const badgeOf = v => { try{ return v.badge ? (+v.badge(S) || 0) : v.id === 'laufwerke' ? activeJobs() : 0; }catch{ return 0; } };

// ---------- Reiter
let sig = '';
function renderTabs(){
  const views = getViews(), cur = currentView();
  const rest = views.filter(v => v.id !== SETTINGS), extra = rest.length > 4 ? rest.slice(3).map(v => v.id) : [];   // Handy: ab 6 Ansichten „Mehr“
  const key = JSON.stringify([views.map(v => [v.id, v.label, v.icon]), cur]);
  if(key !== sig){
    sig = key;
    $('#navlist').innerHTML = views.map(v => `<a class="nav-tab${v.id === SETTINGS ? ' end' : ''}${extra.includes(v.id) ? ' extra' : ''}" role="tab" id="tab-${esc(v.id)}" href="#/${esc(v.hash)}" data-view="${esc(v.id)}" aria-controls="view-${esc(v.id)}" aria-selected="${v.id === cur}" tabindex="${v.id === cur ? 0 : -1}"><span class="nav-ico" aria-hidden="true">${esc(v.icon)}</span><span class="nav-label">${esc(v.label)}</span><span class="nav-badge" hidden></span><span class="nav-dot" hidden title="Ungespeicherte Änderungen"></span></a>`).join('')
      + (extra.length ? `<button class="nav-tab nav-more${extra.includes(cur) ? ' on' : ''}" type="button" id="navmore" aria-haspopup="menu" aria-expanded="false" aria-controls="navsheet"><span class="nav-ico" aria-hidden="true">⋯</span><span class="nav-label">Mehr</span></button>` : '');
    $('#navsheet').innerHTML = extra.map(id => { const v = views.find(x => x.id === id); return `<a role="menuitem" href="#/${esc(v.hash)}"><span class="nav-ico" aria-hidden="true">${esc(v.icon)}</span>${esc(v.label)}</a>`; }).join('');
    closeSheet();
    for(const v of views){ const el = document.getElementById('view-' + v.id); if(el){ el.setAttribute('role', 'tabpanel'); el.setAttribute('aria-labelledby', 'tab-' + v.id); } }
  }
  for(const v of views){
    const t = $(`#tab-${CSS.escape(v.id)}`); if(!t) continue;
    const n = badgeOf(v), b = $('.nav-badge', t);
    b.hidden = !n; b.textContent = n > 99 ? '99+' : n; b.setAttribute('aria-label', `${n} laufende${n === 1 ? 'r Auftrag' : ' Aufträge'}`);
    $('.nav-dot', t).hidden = !(v.id === SETTINGS && dirty && v.id !== cur);
  }
  $('#drivebar').hidden = cur !== 'laufwerke';
}

// ---------- Mehr-Blatt (Handy)
const sheet = document.createElement('div');
sheet.className = 'sheet'; sheet.id = 'navsheet'; sheet.hidden = true; sheet.setAttribute('role', 'menu'); sheet.setAttribute('aria-label', 'Weitere Ansichten');
document.body.append(sheet);
function closeSheet(){ sheet.hidden = true; const m = $('#navmore'); if(m) m.setAttribute('aria-expanded', 'false'); }
document.addEventListener('click', e => {
  const m = e.target.closest('#navmore');
  if(m){ sheet.hidden = !sheet.hidden; m.setAttribute('aria-expanded', String(!sheet.hidden)); return; }
  if(!e.target.closest('#navsheet') || e.target.closest('a')) closeSheet();
});
document.addEventListener('keydown', e => { if(e.key === 'Escape' && !sheet.hidden){ closeSheet(); const m = $('#navmore'); if(m) m.focus(); } });

// ---------- Tastatur: ←/→, Pos1/Ende wechseln den Fokus zwischen den sichtbaren Reitern, Leertaste öffnet
$('#navlist').addEventListener('keydown', e => {
  const tabs = [...document.querySelectorAll('#navlist .nav-tab')].filter(t => t.offsetParent);
  const i = tabs.indexOf(document.activeElement);
  if(i < 0) return;
  let to = null;
  if(e.key === 'ArrowRight') to = tabs[(i + 1) % tabs.length];
  else if(e.key === 'ArrowLeft') to = tabs[(i - 1 + tabs.length) % tabs.length];
  else if(e.key === 'Home') to = tabs[0];
  else if(e.key === 'End') to = tabs[tabs.length - 1];
  else if(e.key === ' '){ e.preventDefault(); tabs[i].click(); return; }
  if(to){ e.preventDefault(); tabs.forEach(t => { t.tabIndex = t === to ? 0 : -1; }); to.focus(); }
});
$('#skip').addEventListener('click', () => { const v = document.getElementById('view-' + currentView()) || $('#views'); v.setAttribute('tabindex', '-1'); v.focus(); });

// ---------- Hinweisleisten
function renderBanners(){
  const b = [];
  if(conn.failed) b.push(['err', 'Verbindung zum Server getrennt – verbinde neu …']);
  const o = S && S.output;
  if(o){
    if(o.stalled) b.push(['warn', `Das Ziel ${o.dir} antwortet nur sehr langsam (Netzwerk/NAS überlastet?). Rips laufen dadurch langsamer.`]);
    else if(!o.mounted) b.push(['warn', `${o.preferred} ist nicht eingehängt – es wird vorübergehend lokal auf diesem Server gespeichert (${o.dir}).`]);
  }
  setHtml($('#banners'), b.map(([c, t]) => `<div class="banner ${c}" role="${c === 'err' ? 'alert' : 'status'}">⚠ ${esc(t)}</div>`).join(''));
}

on('view', renderTabs);
on('conn', renderBanners);
on('settings:dirty', d => { dirty = !!d; if(S) renderTabs(); });
onState(S => {
  renderBanners();
  renderTabs();
  let pct = null;
  for(const x of S.drives) if(x.job && x.job.kind !== 'scan') pct = Math.round((x.job.overall || 0) * 100);
  document.title = pct !== null ? `${pct} % – MakeMKV Web` : 'MakeMKV Web';
});
