// Schlüsselweise aktualisierte Auftragsliste: pro Auftrag bleibt ein DOM-Element bestehen, es ändern sich nur Text, Balken und Knöpfe.
// So wird der drehende Kreis nie neu erzeugt (die CSS-Animation würde sonst bei jeder Statusmeldung bei 0° beginnen).
import { esc } from './core.js';

// Drehphase an die Uhr koppeln: alle Kreise laufen im Gleichtakt, und ein neu eingefügtes oder verschobenes Element
// springt nicht auf 0° zurück (die Animation beginnt dann dort, wo sie nach der Uhr gerade stünde).
export const syncSpin = (el, ms = 1000) => { if(el) el.style.animationDelay = `-${Date.now() % ms}ms`; };

const ROW = `<span class="status-check" aria-hidden="true"></span>
  <div class="job-main">
    <div class="job-head"><strong class="job-name"></strong><span class="st job-host" hidden></span><span class="status"></span></div>
    <small class="job-small"></small>
    <div class="mini-bar" hidden><div></div></div>
  </div>
  <div class="job-act"></div>`;

function makeRow(key){
  const el = document.createElement('div');
  el.className = 'job'; el.dataset.key = key; el.innerHTML = ROW;
  el._r = { ic: el.querySelector('.status-check'), name: el.querySelector('.job-name'), host: el.querySelector('.job-host'), pill: el.querySelector('.status'),
            small: el.querySelector('.job-small'), bar: el.querySelector('.mini-bar'), fill: el.querySelector('.mini-bar > div'), act: el.querySelector('.job-act') };
  el._v = {};
  return el;
}

// Wert nur schreiben, wenn er sich geändert hat (kein unnötiger Eingriff ins DOM)
const changed = (el, k, v) => { if(el._v[k] === v) return false; el._v[k] = v; return true; };

// m: {iconCls, iconTxt, name, title, host, cls, txt, small, err, pct, acts}
function updateRow(el, m){
  const r = el._r;
  if(changed(el, 'ic', m.iconCls + '|' + m.iconTxt)){
    const was = r.ic.classList.contains('run');
    r.ic.className = 'status-check' + (m.iconCls ? ' ' + m.iconCls : ''); r.ic.textContent = m.iconTxt;
    if(m.iconCls === 'run' && !was) syncSpin(r.ic);
  }
  if(changed(el, 'name', m.name)) r.name.textContent = m.name;
  if(changed(el, 'title', m.title)) r.name.title = m.title;
  if(changed(el, 'host', m.host)){ r.host.hidden = !m.host; r.host.textContent = m.host || ''; }
  if(changed(el, 'pill', m.cls + '|' + m.txt)){ r.pill.className = 'status' + (m.cls ? ' ' + m.cls : ''); r.pill.textContent = m.txt; }
  if(changed(el, 'small', m.small)) r.small.textContent = m.small;
  if(changed(el, 'err', m.err)) r.small.classList.toggle('err', m.err);
  if(changed(el, 'bar', m.pct === null ? -1 : m.pct)){
    r.bar.hidden = m.pct === null;
    if(m.pct !== null){ r.fill.style.width = m.pct + '%'; r.bar.setAttribute('role', 'progressbar'); r.bar.setAttribute('aria-valuenow', m.pct); r.bar.setAttribute('aria-label', 'Fortschritt'); }
  }
  if(changed(el, 'acts', m.acts)) r.act.innerHTML = m.acts;
}

// Knöpfe einer Zeile: Text und Symbol, je nach Breite der Liste (css/jobs.css, Container Query) wird eins von beiden gezeigt
export const jobBtn = (attrs, symbol, label, title, extra = '') =>
  `<button class="secondary job-btn ${extra}" ${attrs} title="${esc(title)}" aria-label="${esc(label)}"><span class="bi" aria-hidden="true">${symbol}</span><span class="bl">${label}</span></button>`;

// Liste `list` auf `items` bringen. items: [{key, model}]. Gleiche Schlüssel behalten ihr Element.
export function reconcileJobs(list, items, emptyText){
  const rows = list._rows ||= new Map();
  const want = new Set(items.map(i => i.key));
  for(const [k, el] of rows) if(!want.has(k)){ el.remove(); rows.delete(k); }
  let empty = list._empty;
  if(!items.length){
    if(!empty){ empty = list._empty = document.createElement('div'); empty.className = 'empty'; empty.textContent = emptyText; }
    if(empty.parentNode !== list) list.append(empty);
    return;
  }
  if(empty && empty.parentNode) empty.remove();
  const els = items.map(i => {
    let el = rows.get(i.key);
    if(!el){ el = makeRow(i.key); rows.set(i.key, el); }
    updateRow(el, i.model);
    return el;
  });
  // Reihenfolge herstellen: von hinten her, damit möglichst nur das Element bewegt wird, das wirklich woanders hin soll
  let next = null;
  for(let i = els.length - 1; i >= 0; i--){
    const el = els[i];
    if(el.parentNode !== list || el.nextSibling !== next){ list.insertBefore(el, next); syncSpin(el._r.ic); }
    next = el;
  }
}
