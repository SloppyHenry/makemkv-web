// Log of the selected disc: a single collapsible card at the bottom. Its state (open/closed) is remembered;
// a new error expands the card, and while it is collapsed a badge shows the unseen errors.
import { $, esc, setHtml } from './core.js';
import { curDrive, dkey } from './drives.js';
import { isActive, onState, registerPanel } from './registry.js';

const KEY = 'logOpen';
const stored = () => { try{ return localStorage.getItem(KEY); }catch{ return null; } };     // null = never chosen -> closed
const store = open => { try{ localStorage.setItem(KEY, open ? '1' : '0'); }catch{ /* storage blocked: then without remembering */ } };
const seen = {};        // drive -> number of error messages the user has already seen
const prev = {};        // drive -> number of error messages at the last render (only an increase expands, not errors that were already there)
let auto = false;       // true while we expand it ourselves (that should not be remembered as the user's choice)

const line = l => `<div class="log-line"><span class="log-time">${esc(l.t)}</span><span class="${l.l==='ok'?'log-good':l.l==='error'?'log-error':''}">${esc(l.m)}</span></div>`;

function renderLogs(d){
  const box = $('#logFull'), card = $('#fullLog');
  if(!box || !card) return;
  const log = d ? d.log : [], key = d ? dkey(d) : '', errN = log.filter(l => l.l === 'error').length;
  const end = box.scrollTop + box.clientHeight >= box.scrollHeight - 12;
  setHtml(box, log.map(line).join('') || '<span class="muted">no messages yet</span>');
  if(end) box.scrollTop = box.scrollHeight;
  // new error (not when a log is first shown): expand the card
  if(prev[key] !== undefined && errN > prev[key] && !card.open){ auto = true; card.open = true; }
  prev[key] = errN;
  if(card.open) seen[key] = errN;
  const fresh = card.open ? 0 : Math.max(0, errN - (seen[key] ?? 0));
  const badge = $('#logBadge');
  badge.hidden = !fresh; badge.textContent = fresh === 1 ? '1 error' : `${fresh} errors`;
  $('#logCount').textContent = log.length ? `${log.length} message${log.length === 1 ? '' : 's'}` : '';
}

document.addEventListener('toggle', e => {
  if(!e.target || e.target.id !== 'fullLog') return;
  if(auto) auto = false; else store(e.target.open);
  renderLogs(curDrive());
}, true);

onState(() => { if(isActive('drives')) renderLogs(curDrive()); });

registerPanel({view:'drives', slot:'bottom', order:10, id:'fullLog', html:`<section class="panel bottom-log">
      <details id="fullLog" ${stored() === '1' ? 'open' : ''}>
        <summary class="footerline" aria-label="Expand or collapse the log"><span class="mini-icon">›_</span><h2>Log</h2><span class="pill busypill" id="logBadge" hidden></span><span class="spacer"></span><span class="muted log-count" id="logCount"></span><span class="chev">⌄</span></summary>
        <div class="log-body" id="logFull" role="log" aria-live="off"></div>
      </details>
    </section>`});
