// Protokoll der gewählten Disc: eine einzige, einklappbare Karte unten. Der Zustand (auf/zu) wird gemerkt;
// ein neuer Fehler klappt die Karte auf, und solange sie zu ist, zeigt eine Plakette die ungesehenen Fehler.
import { $, esc, setHtml } from './core.js';
import { curDrive, dkey } from './drives.js';
import { isActive, onState, registerPanel } from './registry.js';

const KEY = 'logOpen';
const stored = () => { try{ return localStorage.getItem(KEY); }catch{ return null; } };     // null = nie gewählt -> offen
const store = open => { try{ localStorage.setItem(KEY, open ? '1' : '0'); }catch{ /* Speicher gesperrt: dann eben ohne Merken */ } };
const seen = {};        // Laufwerk -> Zahl der Fehlermeldungen, die der Nutzer schon gesehen hat
const prev = {};        // Laufwerk -> Zahl der Fehlermeldungen beim letzten Zeichnen (nur ein Anstieg klappt auf, nicht schon vorhandene Fehler)
let auto = false;       // true, solange wir selbst aufklappen (das soll nicht als Wahl des Nutzers gemerkt werden)

const line = l => `<div class="log-line"><span class="log-time">${esc(l.t)}</span><span class="${l.l==='ok'?'log-good':l.l==='error'?'log-error':''}">${esc(l.m)}</span></div>`;

function renderLogs(d){
  const box = $('#logFull'), card = $('#fullLog');
  if(!box || !card) return;
  const log = d ? d.log : [], key = d ? dkey(d) : '', errN = log.filter(l => l.l === 'error').length;
  const end = box.scrollTop + box.clientHeight >= box.scrollHeight - 12;
  setHtml(box, log.map(line).join('') || '<span class="muted">noch keine Meldungen</span>');
  if(end) box.scrollTop = box.scrollHeight;
  // neuer Fehler (nicht beim ersten Anzeigen eines Protokolls): Karte aufklappen
  if(prev[key] !== undefined && errN > prev[key] && !card.open){ auto = true; card.open = true; }
  prev[key] = errN;
  if(card.open) seen[key] = errN;
  const fresh = card.open ? 0 : Math.max(0, errN - (seen[key] ?? 0));
  const badge = $('#logBadge');
  badge.hidden = !fresh; badge.textContent = fresh === 1 ? '1 Fehler' : `${fresh} Fehler`;
  $('#logCount').textContent = log.length ? `${log.length} Meldung${log.length === 1 ? '' : 'en'}` : '';
}

document.addEventListener('toggle', e => {
  if(!e.target || e.target.id !== 'fullLog') return;
  if(auto) auto = false; else store(e.target.open);
  renderLogs(curDrive());
}, true);

onState(() => { if(isActive('laufwerke')) renderLogs(curDrive()); });

registerPanel({view:'laufwerke', slot:'bottom', order:10, id:'fullLog', html:`<section class="panel bottom-log">
      <details id="fullLog" ${stored() === '0' ? '' : 'open'}>
        <summary class="footerline" aria-label="Protokoll ein- oder ausklappen"><span class="mini-icon">›_</span><h2>Protokoll</h2><span class="pill busypill" id="logBadge" hidden></span><span class="spacer"></span><span class="muted log-count" id="logCount"></span><span class="chev">⌄</span></summary>
        <div class="log-body" id="logFull" role="log" aria-live="off"></div>
      </details>
    </section>`});
