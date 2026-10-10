// Einstellungen (vorerst als Dialog). Abschnitte melden sich über registerSettingsSection an; PB ersetzt den Dialog durch eine Seite.
import { $, S, ago, api, esc, toast } from './core.js';
import { getSettingsSections, on, registerSettingsSection } from './registry.js';

document.body.insertAdjacentHTML('beforeend', `<dialog id="dlg">
  <form method="dialog" id="setform">
    <h3>Einstellungen</h3>
    <div id="setsections" style="display:contents"></div>
    <div class="rowend"><button type="button" class="secondary" id="s-cancel">Schließen</button><button type="submit" class="primary" style="width:auto" id="s-save" value="save">Speichern</button></div>
  </form>
</dialog>`);
const dlg = $('#dlg');

// Abschnitt „Allgemein“: die heutigen Felder (Namensraum general) samt MakeMKV-Key
registerSettingsSection({
  id: 'general', label: 'Allgemein', order: 10,
  render(el, s){
    el.innerHTML = `    <label class="chk"><input class="check" type="checkbox" id="s-auto_scan"> Eingelegte Disc automatisch analysieren</label>
    <label class="chk"><input class="check" type="checkbox" id="s-auto_eject"> Nach erfolgreichem Rip automatisch auswerfen</label>
    <div class="two field"><div><label for="s-minlength">Minimale Titellänge (Sekunden)</label><input type="number" id="s-minlength" min="0" step="10"></div>
      <div><label for="s-conv_segments">Segmente pro Film (0 = automatisch)</label><input type="number" id="s-conv_segments" min="0" max="12" step="1"></div></div>
    <div class="two field"><div><label for="s-audio_langs">Audio-Sprachen behalten</label><input type="text" id="s-audio_langs" placeholder="alle – z. B. deu,eng"></div>
      <div><label for="s-sub_langs">Untertitel behalten</label><input type="text" id="s-sub_langs" placeholder="alle – z. B. deu"></div></div>
    <p class="help" style="margin:-6px 0 0">3-Buchstaben-Sprachcodes (deu, eng, fra …). Video und Spuren ohne Sprachangabe bleiben immer erhalten. Gilt für den nächsten Rip.
      Segmente: x265 nutzt pro Prozess nur ca. 4–8 Kerne – bei „0“ entscheidet die App vor jeder Konvertierung selbst nach freien Kernen und RAM; 1 = nie teilen.</p>
    <div class="two field"><div><label for="s-conv_parallel">Gleichzeitige Dateien (Konvertierung)</label><input type="number" id="s-conv_parallel" min="1" max="8" step="1"></div>
      <div><label for="s-key">Eigener MakeMKV-Key (optional)</label><input type="text" id="s-key" placeholder="leer = öffentlicher Beta-Key"></div></div>
    <div class="muted" style="font-size:11px" id="keystate"></div>`;
    $('#s-auto_scan').checked = s.auto_scan; $('#s-auto_eject').checked = s.auto_eject; $('#s-minlength').value = s.minlength;
    $('#s-conv_parallel').value = s.conv_parallel; $('#s-conv_segments').value = s.conv_segments;
    $('#s-audio_langs').value = s.audio_langs; $('#s-sub_langs').value = s.sub_langs; $('#s-key').value = s.key;
    const k = S.key;
    $('#keystate').innerHTML = k.custom ? 'Eigener Key wird verwendet.' : k.beta ? `Öffentlicher Beta-Key aktiv (geholt ${ago(k.fetched)}). <button type="button" class="secondary" id="keyref">Neu holen</button>` : `Kein Key vorhanden${k.error ? ': '+esc(k.error) : ''}. <button type="button" class="secondary" id="keyref">Beta-Key holen</button>`;
    const kr = $('#keyref'); if(kr) kr.onclick = async () => { kr.disabled = true; try{ await api('/api/key/refresh'); }catch{} dlg.close(); };
  },
  collect(){
    return { general: { auto_scan: $('#s-auto_scan').checked, auto_eject: $('#s-auto_eject').checked, minlength: +$('#s-minlength').value || 0,
      conv_parallel: +$('#s-conv_parallel').value || 1, conv_segments: Math.max(0, +$('#s-conv_segments').value || 0),
      audio_langs: $('#s-audio_langs').value, sub_langs: $('#s-sub_langs').value, key: $('#s-key').value } };
  },
});

function openSettings(){
  if(!S) return;
  $('#setsections').innerHTML = getSettingsSections().map(s => `<div class="set-section" data-section="${esc(s.id)}"></div>`).join('');
  getSettingsSections().forEach(s => s.render($(`#setsections [data-section="${s.id}"]`), S.settings));
  dlg.showModal();
}
on('settings:open', openSettings);
$('#s-cancel').addEventListener('click', () => dlg.close());
$('#setform').addEventListener('submit', async () => {
  const body = {};
  for(const s of getSettingsSections()) for(const [ns, vals] of Object.entries(s.collect())) body[ns] = {...(body[ns] || {}), ...vals};
  await api('/api/settings', 'POST', body);
  toast('Einstellungen gespeichert ✓');
});
