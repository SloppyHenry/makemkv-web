// Headless-Modus: Einstellungsabschnitt und Feld „Headless-Modus“ in der Ansicht Laufwerke (Zustand, Protokoll, Erkennung testen).
import { $, S, ago, api, delegate, esc, setHtml, toast } from './core.js';
import { curDrive } from './drives.js';
import { onState, registerPanel, registerSettingsSection } from './registry.js';

const MODE = {movie: 'Film', series: 'Serie', unsure: 'unsicher – alle Titel', manual: 'von Hand', memory: 'wie zuletzt von Hand'};
const STATE_CLS = {done: 'ok', error: 'busy', manual: 'warn', cancelled: 'warn', waiting: 'warn'};

registerSettingsSection({
  id: 'headless', label: 'Headless-Modus', order: 15, icon: '⏏', description: 'Disc einlegen, fertig: richtige Titel rippen und auswerfen, ohne Bedienung.',
  render(el, s){
    const h = {enabled: false, use_db: true, convert: false, ...(s.headless || {})};
    el.innerHTML = `<label class="chk"><input class="check" type="checkbox" id="s-hl-enabled" ${h.enabled ? 'checked' : ''}> Headless-Modus einschalten</label>
      <label class="chk"><input class="check" type="checkbox" id="s-hl-db" ${h.use_db ? 'checked' : ''}> Titel über TheDiscDB bestimmen (Internet, es wird nur die Kennung der Disc gesendet)</label>
      <label class="chk"><input class="check" type="checkbox" id="s-hl-conv" ${h.convert ? 'checked' : ''}> Nach dem Rippen konvertieren (Standard-Preset der Disc-Art)</label>
      <div class="help hl-help">Eingelegte Discs werden sofort analysiert. Die Titel werden in dieser Reihenfolge bestimmt:
        <ol><li><b>Gedächtnis</b>: dieselbe Disc wurde schon einmal von Hand gerippt (auch an einem anderen Rechner) – dieselben Titel und Namen.</li>
        <li><b>TheDiscDB</b>: genau der Hauptfilm bzw. die Folgen, mit Namen wie „Serie S01E02“.</li>
        <li><b>TMDB</b> (mit Schlüssel unter Medien): der Titel mit der Filmlaufzeit bzw. die Titel mit der Folgenlänge.</li>
        <li><b>Struktur</b>: ein langer Titel = Film, mehrere gleich lange Titel = Serie (ohne Play-All). Nicht eindeutig: alle Titel ohne Duplikate und Play-All;
        wären das mehr als doppelt so viele Daten wie auf der Disc, wird nichts gerippt („von Hand“).</li></ol>
        Danach wird die Disc immer ausgeworfen, auch bei Fehlern – nur wenn du selbst abbrichst, bleibt sie drin. Legst du eine „von Hand“-Disc wieder ein,
        bleibt sie im Laufwerk: Titel wählen und rippen, die Auswahl merkt sich das Gedächtnis. Schalter und Protokoll stehen auch direkt unter Laufwerke.</div>`;
  },
  collect(){
    return {headless: {enabled: $('#s-hl-enabled').checked, use_db: $('#s-hl-db').checked, convert: $('#s-hl-conv').checked}};
  },
});

function item(e){
  const picked = e.picked ? (e.picked.length ? e.picked.join(', ') : '–') : (e.titles.length ? `${e.titles.length} Titel` : '–');
  const skipped = (e.skipped || []).map(([n, why]) => `${n}: ${why}`).join(' · ');
  const head = [e.source, MODE[e.mode]].filter(Boolean).join(' · ');
  return `<div class="hl-item" title="${esc(e.reasons.join(' · '))}">
    <div class="hl-top"><strong title="${esc(e.folder || e.disc)}">${esc(e.disc || e.folder || 'Disc')}</strong><span class="st ${STATE_CLS[e.state] || ''}">${esc(e.state_text)}</span>
      <span class="spacer"></span><span class="muted">${esc(e.drive)} · ${esc(ago(e.t))}${e.ejected ? ' · ausgeworfen' : ''}</span></div>
    ${head ? `<div class="hl-why">${esc(head)}</div>` : ''}
    ${e.mode && e.mode !== 'manual' || e.picked ? `<div class="hl-sub"><b>Übernommen:</b> ${esc(picked)}</div>` : ''}
    ${skipped ? `<div class="hl-why"><b>Nicht übernommen:</b> ${esc(skipped)}</div>` : ''}
    ${e.message ? `<div class="hl-why ${e.state === 'error' ? 'err' : ''}">${esc(e.message)}</div>` : ''}
  </div>`;
}

// Rechner des gewählten Laufwerks: dessen Headless-Modus wird angezeigt und geschaltet (null = alter Stand ohne Headless)
function target(){
  const d = curDrive();
  if(d && d.host){ const p = (S.peers || []).find(x => x.name === d.host); return {d, host: d.host, base: `/api/peer/${d.host}`, h: (p && p.headless) || null}; }
  return {d, host: '', base: '/api', h: S.headless};
}

// kleiner Schalter oben in der Laufwerksleiste (auf jedem Bildschirm sofort sichtbar)
function barSwitch(){
  const bar = $('#drivebar');
  if(!bar || !S || !S.headless) return;
  let el = $('#hlBar');
  if(!el){
    bar.insertAdjacentHTML('beforeend', `<label class="hl-switch hl-bar" id="hlBar" title="Headless-Modus: eingelegte Discs automatisch rippen und auswerfen">
      <span class="hl-bar-lbl">Headless</span><input type="checkbox" class="hl-toggle" role="switch" aria-label="Headless-Modus"><span class="hl-knob" aria-hidden="true"></span></label>`);
    el = $('#hlBar');
  }
  const cb = el.querySelector('input');
  const t = target();
  el.hidden = !t.h;
  el.title = `Headless-Modus${t.host ? ' auf ' + t.host : ''}: eingelegte Discs automatisch rippen und auswerfen`;
  el.querySelector('.hl-bar-lbl').textContent = t.host ? `Headless ${t.host}` : 'Headless';
  if(!cb.dataset.busy && t.h) cb.checked = t.h.enabled;
}

function render(){
  barSwitch();
  const pn = $('#hlPanel');
  if(!pn || !S) return;
  const t = target(), h = t.h;
  pn.hidden = !h;
  if(!h) return;
  setHtml($('#hlHost'), t.host ? '· ' + esc(t.host) : '');
  const st = $('#hlState');
  st.className = 'st' + (h.enabled ? ' ok' : ''); st.textContent = h.enabled ? 'an' : 'aus';
  document.querySelectorAll('.hl-toggle').forEach(cb => { if(!cb.dataset.busy) cb.checked = h.enabled; });
  const d = t.d, ok = !!(d && d.disc && !d.job), test = $('#hlTest'), con = $('#hlContrib');
  test.disabled = !ok; con.disabled = !ok || !!t.host;
  test.title = 'Titelwahl für die Disc im gewählten Laufwerk prüfen, ohne zu rippen';
  con.title = d && d.host ? 'Nur für Laufwerke dieses Rechners' : 'Titel dieser Disc an TheDiscDB melden (mit Vorschau, TheDiscDB prüft vor dem Veröffentlichen)';
  $('#hlClear').hidden = !h.history.length;
  const mem = h.memory ? ` Gedächtnis: ${h.memory} Disc${h.memory === 1 ? '' : 's'} von Hand.` : '';
  setHtml($('#hlNote'), esc((h.enabled ? 'Eingelegte Discs werden automatisch erkannt, gerippt und ausgeworfen.'
    : 'Aus. Mit dem Schalter einschalten; „Erkennung testen“ zeigt, was gerippt würde.') + mem));
  setHtml($('#hlList'), h.history.length ? h.history.map(item).join('') : '<div class="empty">Noch keine Disc im Headless-Modus.</div>');
}
onState(render);

delegate('#hlTest', 'click', async (e, b) => {
  const t = target(); if(!t.d) return;
  b.disabled = true;
  try{
    const r = await api(`${t.base}/headless/test/${t.d.id}`);
    toast(`${r.source}: ${MODE[r.mode] || r.mode}${r.picks.length ? ` – ${r.picks.length} Titel` : ''}`);
  }catch{ /* Meldung zeigt api() */ }
  render();
});
delegate('.hl-toggle', 'change', async (e, cb) => {
  const want = cb.checked;
  cb.dataset.busy = '1'; cb.disabled = true;
  try{
    const t = target();
    await api(`${t.base}/headless/enable`, 'POST', {enabled: want});
    const on = t.host ? ` auf ${t.host}` : '';
    toast(want ? `Headless-Modus${on} an: ab der nächsten eingelegten Disc wird automatisch gerippt und ausgeworfen.` : `Headless-Modus${on} aus.`);
  }catch{ cb.checked = !want; }
  delete cb.dataset.busy; cb.disabled = false;
  render();
});
delegate('#hlClear', 'click', async () => { const t = target(); try{ await api(`${t.base}/headless/clear`); }catch{} });

registerPanel({view: 'laufwerke', slot: 'right', order: 5, id: 'hlPanel', html: `<section class="panel" id="hlPanel" hidden>
  <div class="panel-head"><span class="mini-icon">⏏</span><h2>Headless-Modus <span class="sub" id="hlHost"></span></h2>
    <label class="hl-switch" title="Headless-Modus an- oder ausschalten"><input type="checkbox" class="hl-toggle" role="switch" aria-label="Headless-Modus"><span class="hl-knob" aria-hidden="true"></span><span class="st" id="hlState"></span></label>
    <span class="spacer"></span>
    <button type="button" class="secondary" id="hlTest">Erkennung testen</button><button type="button" class="secondary" id="hlContrib">An TheDiscDB melden</button>
    <button type="button" class="secondary" id="hlClear" hidden>Leeren</button></div>
  <div class="hl-note muted" id="hlNote"></div>
  <div class="hl-list" id="hlList"></div>
</section>`});
