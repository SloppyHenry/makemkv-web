// Dialog „Disc an TheDiscDB melden“ (Knopf im Feld Headless-Modus): Vorschlag laden, Zuordnung prüfen, Vorschau, senden.
import { $, api, delegate, esc, toast } from './core.js';
import { curDrive } from './drives.js';

const TYPES = [['', '– nicht melden –'], ['MainMovie', 'Hauptfilm'], ['Episode', 'Folge'], ['Extra', 'Extra'], ['Trailer', 'Trailer'], ['DeletedScene', 'Entfallene Szene']];

document.body.insertAdjacentHTML('beforeend', `
<dialog id="hlcDlg" class="hlc-dlg" aria-labelledby="hlcTitle">
  <form method="dialog" onsubmit="return false">
    <h3 id="hlcTitle">Disc an TheDiscDB melden</h3>
    <p class="help" style="margin:0">Gesendet werden der Inhalts-Hash, das Volume-Label, die Titelliste (Laufzeiten, Größen, Segmente, Spuren) und deine Zuordnung –
      keine Dateien, keine Rechner- oder Laufwerksdaten. TheDiscDB prüft jede Einreichung von Hand, bevor sie erscheint. <span id="hlcSrc"></span></p>
    <div class="two"><div><label for="hlc-kind">Art</label><select id="hlc-kind"><option value="movie">Film</option><option value="series">Serie</option></select></div>
      <div><label for="hlc-season">Staffel</label><input type="number" id="hlc-season" min="0" max="99"></div></div>
    <div class="hlc-search"><div><label for="hlc-title">Titel</label><input type="text" id="hlc-title" autocomplete="off"></div>
      <div><label for="hlc-tmdb">TMDB-ID</label><input type="number" id="hlc-tmdb" min="1"></div>
      <button type="button" class="secondary" id="hlc-find">TMDB suchen</button></div>
    <select id="hlc-hits" hidden aria-label="TMDB-Treffer"></select>
    <div class="two"><div><label for="hlc-discno">Disc-Nummer (optional)</label><input type="number" id="hlc-discno" min="1" max="99"></div>
      <div><label for="hlc-upc">EAN/UPC vom Barcode (optional)</label><input type="text" id="hlc-upc" inputmode="numeric" autocomplete="off"></div></div>
    <div class="table-wrap hlc-table"><table><thead><tr><th>Titel</th><th>Dauer</th><th>Größe</th><th>Art</th><th>Folge</th></tr></thead><tbody id="hlc-rows"></tbody></table></div>
    <pre class="hlc-prev" id="hlc-prev" hidden></pre>
    <div class="rowend"><button type="button" class="secondary" id="hlc-cancel">Abbrechen</button><button type="button" class="secondary" id="hlc-preview">Vorschau</button>
      <button type="button" class="primary" style="width:auto" id="hlc-send">Senden</button></div>
  </form>
</dialog>`);
const dlg = $('#hlcDlg');
let drive = null;

function rows(disc, pre){
  const by = Object.fromEntries((pre.titles || []).map(t => [t.id, t]));
  $('#hlc-rows').innerHTML = disc.titles.map(t => {
    const p = by[t.id] || {};
    return `<tr data-id="${t.id}"><td title="${esc(p.name || t.name)}">${t.id + 1}${p.name ? ` · ${esc(p.name)}` : ''}</td><td>${esc(t.duration_text)}</td><td>${esc(t.size_text)}</td>
      <td><select data-type aria-label="Art von Titel ${t.id + 1}">${TYPES.map(([v, l]) => `<option value="${v}" ${v === (p.type || '') ? 'selected' : ''}>${l}</option>`).join('')}</select></td>
      <td><input type="text" data-ep value="${esc(p.episode || '')}" aria-label="Folge von Titel ${t.id + 1}" ${p.type === 'Episode' ? '' : 'disabled'}></td></tr>`;
  }).join('');
}

function syncKind(){ $('#hlc-season').disabled = $('#hlc-kind').value !== 'series'; }

function body(send){
  const titles = [...document.querySelectorAll('#hlc-rows tr')].map(tr => ({id: +tr.dataset.id, type: tr.querySelector('[data-type]').value,
    episode: tr.querySelector('[data-ep]').value.trim()})).filter(t => t.type);
  const num = id => { const v = $(id).value; return v === '' ? null : +v; };
  return {kind: $('#hlc-kind').value, tmdb_id: num('#hlc-tmdb'), title: $('#hlc-title').value.trim(), season: num('#hlc-season'),
    disc_number: num('#hlc-discno'), upc: $('#hlc-upc').value, titles, send};
}

delegate('#hlContrib', 'click', async (e, b) => {
  const d = curDrive(); if(!d || d.host || !d.disc) return;
  b.disabled = true;
  try{
    const pre = await api(`/api/headless/contribute/${d.id}/prefill`);
    drive = d;
    $('#hlc-kind').value = pre.kind; $('#hlc-season').value = pre.season ?? ''; $('#hlc-title').value = pre.title || '';
    $('#hlc-tmdb').value = pre.tmdb_id ?? ''; $('#hlc-discno').value = ''; $('#hlc-upc').value = '';
    $('#hlcSrc').textContent = pre.source ? `Vorschlag aus: ${pre.source}.` : '';
    $('#hlc-hits').hidden = true; $('#hlc-prev').hidden = true;
    rows(d.disc, pre); syncKind();
    dlg.showModal();
  }catch{ /* Meldung zeigt api() */ }
  b.disabled = false;
});
dlg.addEventListener('change', e => {
  if(e.target.id === 'hlc-kind') syncKind();
  if(e.target.matches('[data-type]')){ const ep = e.target.closest('tr').querySelector('[data-ep]'); ep.disabled = e.target.value !== 'Episode'; }
  if(e.target.id === 'hlc-hits' && e.target.value){ const o = e.target.selectedOptions[0]; $('#hlc-tmdb').value = o.value; $('#hlc-title').value = o.dataset.title; }
});
delegate('#hlc-find', 'click', async () => {
  const q = $('#hlc-title').value.trim(); if(!q) return toast('Erst einen Titel eingeben.', true);
  try{
    const type = $('#hlc-kind').value === 'series' ? 'tv' : 'movie';
    const r = await (await fetch(`/api/media/search?q=${encodeURIComponent(q)}&type=${type}`)).json();
    if(!r.available) return toast('Ohne TMDB-Schlüssel (Einstellungen → Medien) bitte die TMDB-ID von themoviedb.org eintragen.', true);
    const hits = r.results || [];
    $('#hlc-hits').innerHTML = hits.length ? '<option value="">Treffer wählen …</option>' + hits.map(h => `<option value="${h.tmdb}" data-title="${esc(h.title)}">${esc(h.title)}${h.year ? ` (${h.year})` : ''}</option>`).join('')
      : '<option value="">Keine Treffer</option>';
    $('#hlc-hits').hidden = false;
  }catch{ toast('TMDB-Suche fehlgeschlagen.', true); }
});
delegate('#hlc-cancel', 'click', () => dlg.close());
delegate('#hlc-preview', 'click', async () => {
  if(!drive) return;
  try{
    const r = await api(`/api/headless/contribute/${drive.id}`, 'POST', body(false));
    const pv = $('#hlc-prev'); pv.textContent = JSON.stringify(r.payload, null, 2) + `\n\n+ MakeMKV-Scanprotokoll: ${r.log_lines} Zeilen (nur Titel- und Spurangaben)`; pv.hidden = false;
  }catch{}
});
delegate('#hlc-send', 'click', async (e, b) => {
  if(!drive) return;
  b.disabled = true;
  try{
    const r = await api(`/api/headless/contribute/${drive.id}`, 'POST', body(true));
    toast(`An TheDiscDB gemeldet${r.updated ? ' (Einreichung aktualisiert)' : ''} – danke! TheDiscDB prüft sie, bevor sie erscheint.`);
    dlg.close();
  }catch{}
  b.disabled = false;
});
