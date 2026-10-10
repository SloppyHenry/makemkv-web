// Protokoll der gewählten Disc (kompakt rechts und ausführlich unten).
import { $, esc, setHtml } from './core.js';
import { curDrive } from './drives.js';
import { isActive, onState, registerPanel } from './registry.js';

function renderLogs(d){
  const log = d ? d.log : [];
  if(!$('#logFull')) return;
  const line = l => `<div class="log-line"><span class="log-time">${esc(l.t)}</span><span class="${l.l==='ok'?'log-good':l.l==='error'?'log-error':''}">${esc(l.m)}</span></div>`;
  const put = (el, h) => { const end = el.scrollTop + el.clientHeight >= el.scrollHeight - 12; setHtml(el, h); if(end) el.scrollTop = el.scrollHeight; };
  put($('#logFull'), log.map(line).join('') || '<span class="muted">noch keine Meldungen</span>');
  put($('#logCompact'), log.slice(-4).map(line).join('') || '<span class="muted">noch keine Meldungen</span>');
}

onState(() => { if(isActive('laufwerke')) renderLogs(curDrive()); });

registerPanel({view:'laufwerke', slot:'right', order:30, id:'compactLog', html:`<section class="panel">
          <details id="compactLog">
            <summary class="panel-head"><span class="mini-icon">›_</span><h2>Protokoll anzeigen</h2><span class="chev">⌄</span></summary>
            <div class="log-body" id="logCompact"></div>
          </details>
        </section>`});
registerPanel({view:'laufwerke', slot:'bottom', order:10, id:'fullLog', html:`<section class="panel bottom-log">
      <details open id="fullLog">
        <summary class="footerline"><span class="mini-icon">›_</span><h2>Protokoll</h2><span class="spacer"></span><span class="muted" style="font-size:12px">Letzte Meldungen</span><span class="chev">⌃</span></summary>
        <div class="log-body" id="logFull" style="max-height:220px"></div>
      </details>
    </section>`});
