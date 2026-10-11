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
        bleibt sie im Laufwerk: Titel wählen und rippen, die Auswahl merkt sich das Gedächtnis. Das Protokoll steht unter Laufwerke.</div>`;
  },
  collect(){
    return {headless: {enabled: $('#s-hl-enabled').checked, use_db: $('#s-hl-db').checked, convert: $('#s-hl-conv').checked}};
  },
});

function item(e){
  const titles = e.titles.length ? `${e.titles.length} Titel: ${e.titles.slice(0, 4).join(', ')}${e.titles.length > 4 ? ' …' : ''}` : '';
  const what = [e.source, MODE[e.mode], titles].filter(Boolean).join(' · ');
  return `<div class="hl-item">
    <div class="hl-top"><strong title="${esc(e.folder || e.disc)}">${esc(e.disc || e.folder || 'Disc')}</strong><span class="st ${STATE_CLS[e.state] || ''}">${esc(e.state_text)}</span>
      <span class="spacer"></span><span class="muted">${esc(e.drive)} · ${esc(ago(e.t))}${e.ejected ? ' · ausgeworfen' : ''}</span></div>
    ${what ? `<div class="hl-sub">${esc(what)}</div>` : ''}
    ${e.reasons.length ? `<div class="hl-why">${esc(e.reasons.join(' · '))}</div>` : ''}
    ${e.message ? `<div class="hl-why ${e.state === 'error' ? 'err' : ''}">${esc(e.message)}</div>` : ''}
  </div>`;
}

function render(){
  const pn = $('#hlPanel');
  if(!pn || !S) return;
  const h = S.headless;
  pn.hidden = !h;
  if(!h) return;
  const st = $('#hlState');
  st.className = 'st' + (h.enabled ? ' ok' : ''); st.textContent = h.enabled ? 'aktiv' : 'aus';
  const d = curDrive(), ok = !!(d && !d.host && d.disc && !d.job), test = $('#hlTest'), con = $('#hlContrib');
  test.disabled = con.disabled = !ok;
  test.title = d && d.host ? 'Nur für Laufwerke dieses Rechners' : 'Titelwahl für die Disc im gewählten Laufwerk prüfen, ohne zu rippen';
  con.title = d && d.host ? 'Nur für Laufwerke dieses Rechners' : 'Titel dieser Disc an TheDiscDB melden (mit Vorschau, TheDiscDB prüft vor dem Veröffentlichen)';
  $('#hlClear').hidden = !h.history.length;
  const mem = h.memory ? ` Gedächtnis: ${h.memory} Disc${h.memory === 1 ? '' : 's'} von Hand.` : '';
  setHtml($('#hlNote'), esc((h.enabled ? 'Eingelegte Discs werden automatisch erkannt, gerippt und ausgeworfen.'
    : 'Ausgeschaltet (Einstellungen → Headless-Modus). „Erkennung testen“ zeigt, was gerippt würde.') + mem));
  setHtml($('#hlList'), h.history.length ? h.history.map(item).join('') : '<div class="empty">Noch keine Disc im Headless-Modus.</div>');
}
onState(render);

delegate('#hlTest', 'click', async (e, b) => {
  const d = curDrive(); if(!d) return;
  b.disabled = true;
  try{
    const r = await api(`/api/headless/test/${d.id}`);
    toast(`${r.source}: ${MODE[r.mode] || r.mode}${r.picks.length ? ` – ${r.picks.length} Titel` : ''}`);
  }catch{ /* Meldung zeigt api() */ }
  render();
});
delegate('#hlClear', 'click', async () => { try{ await api('/api/headless/clear'); }catch{} });

registerPanel({view: 'laufwerke', slot: 'right', order: 30, id: 'hlPanel', html: `<section class="panel" id="hlPanel" hidden>
  <div class="panel-head"><span class="mini-icon">⏏</span><h2>Headless-Modus</h2><span class="st" id="hlState"></span><span class="spacer"></span>
    <button type="button" class="secondary" id="hlTest">Erkennung testen</button><button type="button" class="secondary" id="hlContrib">An TheDiscDB melden</button>
    <button type="button" class="secondary" id="hlClear" hidden>Leeren</button></div>
  <div class="hl-note muted" id="hlNote"></div>
  <div class="hl-list" id="hlList"></div>
</section>`});
