// Einstellungsabschnitt „Player“ (Namensraum player). Wird von der Einstellungsseite (PB) über registerSettingsSection angezeigt.
import { S, esc } from './core.js';
import { registerSettingsSection } from './registry.js';

const HEIGHTS = [[0, 'Original'], [1080, '1080p'], [720, '720p'], [480, '480p']];

registerSettingsSection({
  id: 'player', label: 'Player', icon: '▶', order: 70, description: 'Interner Player in der Bibliothek',
  render(el, s){
    const p = {transcode: true, max_height: 0, crf: 24, audio_lang: '', sub_lang: '', ...(s.player || {})};
    const cap = (S && S.capabilities && S.capabilities.player) || {};
    el.innerHTML = `<label class="chk"><input class="check" type="checkbox" id="s-pl-transcode" ${p.transcode ? 'checked' : ''}> Umwandeln erlauben, wenn der Browser das Video nicht kann</label>
      <div class="two field"><div><label for="s-pl-audio">Bevorzugte Tonsprache</label><input type="text" id="s-pl-audio" value="${esc(p.audio_lang)}" placeholder="z. B. deu, eng (leer: Vorgabe der Datei)"></div>
        <div><label for="s-pl-sub">Bevorzugte Untertitelsprache</label><input type="text" id="s-pl-sub" value="${esc(p.sub_lang)}" placeholder="z. B. deu (leer: keine, außer erzwungene)"></div></div>
      <div class="two field"><div><label for="s-pl-height">Höchste Auflösung beim Umwandeln</label><select id="s-pl-height">${HEIGHTS.map(([v, l]) => `<option value="${v}" ${v === p.max_height ? 'selected' : ''}>${l}</option>`).join('')}${HEIGHTS.some(([v]) => v === p.max_height) ? '' : `<option value="${p.max_height}" selected>${p.max_height}p</option>`}</select></div>
        <div><label for="s-pl-crf">Qualität beim Umwandeln (CRF, kleiner = besser)</label><input type="number" id="s-pl-crf" min="16" max="35" step="1" value="${p.crf}"></div></div>
      <p class="help" style="margin:-4px 0 0">Es wird möglichst die Originaldatei abgespielt. Umgewandelt wird nur, wenn der Browser das Video nicht kann (z. B. MPEG-2, VC-1), dann mit niedrigster Priorität und wenigen Kernen, solange Rip, Konvertierung oder Übertragung laufen.
        Sprachen als Liste in Rangfolge (3-Buchstaben-Codes, z. B. deu, eng); leer beim Ton nimmt die Sprachliste aus „Allgemein“, sonst die Vorgabe der Datei.</p>
      <div class="muted" style="font-size:11px">${cap.v ? `Dieser Rechner: ${(cap.modes || []).includes('transcode') ? 'Umwandeln mit ' + esc((cap.encoders || []).join(', ')) : 'ohne Umwandeln (kein x264 im ffmpeg)'}${cap.tonemap ? ' · Tonemapping für HDR verfügbar' : ''}` : 'Dieser Rechner meldet keine Player-Fähigkeiten.'}</div>`;
  },
  collect(){
    const g = id => document.getElementById(id);
    return {player: {transcode: g('s-pl-transcode').checked, audio_lang: g('s-pl-audio').value.trim(), sub_lang: g('s-pl-sub').value.trim(),
      max_height: +g('s-pl-height').value || 0, crf: Math.min(35, Math.max(16, +g('s-pl-crf').value || 24))}};
  },
});
