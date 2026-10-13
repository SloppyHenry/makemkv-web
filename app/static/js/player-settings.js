// Settings section "Player" (namespace player). Shown by the settings page (PB) via registerSettingsSection.
import { S, esc } from './core.js';
import { registerSettingsSection } from './registry.js';

const HEIGHTS = [[0, 'Original'], [1080, '1080p'], [720, '720p'], [480, '480p']];

registerSettingsSection({
  id: 'player', label: 'Player', icon: '▶', order: 70, description: 'Built-in player in the library',
  render(el, s){
    const p = {transcode: true, max_height: 0, crf: 24, audio_lang: '', sub_lang: '', ...(s.player || {})};
    const cap = (S && S.capabilities && S.capabilities.player) || {};
    el.innerHTML = `<label class="chk"><input class="check" type="checkbox" id="s-pl-transcode" ${p.transcode ? 'checked' : ''}> Allow transcoding when the browser cannot play the video</label>
      <div class="two field"><div><label for="s-pl-audio">Preferred audio language</label><input type="text" id="s-pl-audio" value="${esc(p.audio_lang)}" placeholder="e.g. eng, deu (empty: the file's default)"></div>
        <div><label for="s-pl-sub">Preferred subtitle language</label><input type="text" id="s-pl-sub" value="${esc(p.sub_lang)}" placeholder="e.g. eng (empty: none, except forced)"></div></div>
      <div class="two field"><div><label for="s-pl-height">Maximum resolution when transcoding</label><select id="s-pl-height">${HEIGHTS.map(([v, l]) => `<option value="${v}" ${v === p.max_height ? 'selected' : ''}>${l}</option>`).join('')}${HEIGHTS.some(([v]) => v === p.max_height) ? '' : `<option value="${p.max_height}" selected>${p.max_height}p</option>`}</select></div>
        <div><label for="s-pl-crf">Quality when transcoding (CRF, smaller = better)</label><input type="number" id="s-pl-crf" min="16" max="35" step="1" value="${p.crf}"></div></div>
      <p class="help" style="margin:-4px 0 0">The original file is played whenever possible. Transcoding only happens when the browser cannot play the video (e.g. MPEG-2, VC-1), then at the lowest priority and with few cores while a rip, conversion or transfer is running.
        Languages as a list in order of preference (three-letter codes, e.g. eng, deu); empty for audio uses the language list from "General", otherwise the file's default.</p>
      <div class="muted" style="font-size:11px">${cap.v ? `This machine: ${(cap.modes || []).includes('transcode') ? 'transcoding with ' + esc((cap.encoders || []).join(', ')) : 'no transcoding (no x264 in ffmpeg)'}${cap.tonemap ? ' · tone mapping for HDR available' : ''}` : 'This machine reports no player capabilities.'}</div>`;
  },
  collect(){
    const g = id => document.getElementById(id);
    return {player: {transcode: g('s-pl-transcode').checked, audio_lang: g('s-pl-audio').value.trim(), sub_lang: g('s-pl-sub').value.trim(),
      max_height: +g('s-pl-height').value || 0, crf: Math.min(35, Math.max(16, +g('s-pl-crf').value || 24))}};
  },
});
