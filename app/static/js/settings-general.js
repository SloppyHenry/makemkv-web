// Einstellungsabschnitte von PB: Allgemein, MakeMKV-Key und (nur bis PF den Abschnitt „convert“ liefert) Konvertierung (alte Felder).
import { $, S, ago, api, esc } from './core.js';
import { onState, registerSettingsSection } from './registry.js';

registerSettingsSection({
  id: 'general', label: 'Allgemein', order: 10, icon: '⚙', description: 'Verhalten beim Einlegen und Rippen von Discs.',
  render(el, s){
    el.innerHTML = `<label class="chk"><input class="check" type="checkbox" id="s-auto_scan"> Eingelegte Disc automatisch analysieren</label>
      <label class="chk"><input class="check" type="checkbox" id="s-auto_eject"> Nach erfolgreichem Rip automatisch auswerfen</label>
      <div class="two"><div><label for="s-minlength">Minimale Titellänge (Sekunden)</label><input type="number" id="s-minlength" min="0" step="10"></div><div></div></div>
      <div class="two"><div><label for="s-audio_langs">Audio-Sprachen behalten</label><input type="text" id="s-audio_langs" placeholder="alle – z. B. deu,eng"></div>
        <div><label for="s-sub_langs">Untertitel behalten</label><input type="text" id="s-sub_langs" placeholder="alle – z. B. deu"></div></div>
      <p class="help" style="margin:0">3-Buchstaben-Sprachcodes (deu, eng, fra …). Video und Spuren ohne Sprachangabe bleiben immer erhalten. Gilt für den nächsten Rip.</p>`;
    $('#s-auto_scan').checked = s.auto_scan; $('#s-auto_eject').checked = s.auto_eject; $('#s-minlength').value = s.minlength;
    $('#s-audio_langs').value = s.audio_langs; $('#s-sub_langs').value = s.sub_langs;
  },
  collect(){
    return { general: { auto_scan: $('#s-auto_scan').checked, auto_eject: $('#s-auto_eject').checked, minlength: +$('#s-minlength').value || 0,
      audio_langs: $('#s-audio_langs').value, sub_langs: $('#s-sub_langs').value } };
  },
});

function keyState(){
  const el = $('#keystate'); if(!el || !S) return;
  const k = S.key;
  el.innerHTML = k.custom ? `<span class="st ok">● aktiv</span><div><strong>Eigener Key</strong><div class="muted" style="font-size:11px">wird verwendet</div></div>`
    : k.beta ? `<span class="st ok">● aktiv</span><div><strong>Öffentlicher Beta-Key</strong><div class="muted" style="font-size:11px">geholt ${esc(ago(k.fetched))}</div></div><span class="spacer"></span><button type="button" class="secondary" id="keyref">Neu holen</button>`
    : `<span class="st warn">● fehlt</span><div><strong>Kein Key vorhanden</strong><div class="muted" style="font-size:11px">${k.error ? esc(k.error) : 'Der Beta-Key wurde noch nicht geholt.'}</div></div><span class="spacer"></span><button type="button" class="secondary" id="keyref">Beta-Key holen</button>`;
  const kr = $('#keyref'); if(kr) kr.onclick = async () => { kr.disabled = true; try{ await api('/api/key/refresh'); }catch{} };
}
registerSettingsSection({
  id: 'key', label: 'MakeMKV-Key', order: 20, icon: '⚷', description: 'Ohne eigenen Key nutzt die App den öffentlichen Beta-Key von MakeMKV.',
  render(el, s){
    el.innerHTML = `<div><label for="s-key">Eigener MakeMKV-Key (optional)</label><input type="text" id="s-key" placeholder="leer = öffentlicher Beta-Key" autocomplete="off" spellcheck="false"></div>
      <div class="set-row" id="keystate"></div>`;
    $('#s-key').value = s.key;
    keyState();
  },
  collect(){ return { general: { key: $('#s-key').value } }; },
});
onState(keyState);

// Übergangsabschnitt mit den zwei alten Feldern; entfällt, sobald PF den Abschnitt „convert“ anmeldet (settings.js blendet ihn dann aus)
registerSettingsSection({
  id: 'convert-basic', label: 'Konvertierung', order: 90, icon: '⎘', description: 'Parallelität und Segmente bei der Konvertierung.',
  render(el, s){
    el.innerHTML = `<div class="two"><div><label for="s-conv_parallel">Gleichzeitige Dateien (Konvertierung)</label><input type="number" id="s-conv_parallel" min="1" max="8" step="1"></div>
      <div><label for="s-conv_segments">Segmente pro Film (0 = automatisch)</label><input type="number" id="s-conv_segments" min="0" max="12" step="1"></div></div>
      <p class="help" style="margin:0">x265 nutzt pro Prozess nur ca. 4–8 Kerne – bei „0“ entscheidet die App vor jeder Konvertierung selbst nach freien Kernen und RAM; 1 = nie teilen.</p>`;
    $('#s-conv_parallel').value = s.conv_parallel; $('#s-conv_segments').value = s.conv_segments;
  },
  collect(){ return { general: { conv_parallel: +$('#s-conv_parallel').value || 1, conv_segments: Math.max(0, +$('#s-conv_segments').value || 0) } }; },
});
