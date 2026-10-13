// Settings sections from PB: general, MakeMKV key, about (credits and support for MakeMKV) and (only until PF provides the "convert" section) conversion (old fields).
import { $, S, ago, api, esc } from './core.js';
import { onState, registerSettingsSection } from './registry.js';

registerSettingsSection({
  id: 'general', label: 'General', order: 10, icon: '⚙', description: 'Behavior when inserting and ripping discs.',
  render(el, s){
    el.innerHTML = `<label class="chk"><input class="check" type="checkbox" id="s-auto_scan"> Analyze inserted discs automatically</label>
      <label class="chk"><input class="check" type="checkbox" id="s-auto_eject"> Eject automatically after a successful rip</label>
      <div class="two"><div><label for="s-minlength">Minimum title length (seconds)</label><input type="number" id="s-minlength" min="0" step="10"></div><div></div></div>
      <div class="two"><div><label for="s-audio_langs">Keep audio languages</label><input type="text" id="s-audio_langs" placeholder="all – e.g. eng,deu"></div>
        <div><label for="s-sub_langs">Keep subtitles</label><input type="text" id="s-sub_langs" placeholder="all – e.g. eng"></div></div>
      <p class="help" style="margin:0">Three-letter language codes (eng, deu, fra …). Video and tracks without a language are always kept. Applies to the next rip.</p>`;
    $('#s-auto_scan').checked = s.auto_scan; $('#s-auto_eject').checked = s.auto_eject; $('#s-minlength').value = s.minlength;
    $('#s-audio_langs').value = s.audio_langs; $('#s-sub_langs').value = s.sub_langs;
  },
  collect(){
    return { general: { auto_scan: $('#s-auto_scan').checked, auto_eject: $('#s-auto_eject').checked, minlength: +$('#s-minlength').value || 0,
      audio_langs: $('#s-audio_langs').value, sub_langs: $('#s-sub_langs').value } };
  },
});

// Spindle only drives MakeMKV; reading and decrypting discs is MakeMKV's work. Point people to its makers.
const MAKEMKV = 'https://www.makemkv.com/', MAKEMKV_BUY = 'https://www.makemkv.com/buy/';
const SUPPORT = `<p class="help" style="margin:0">Reading and decrypting discs is done by <a href="${MAKEMKV}" target="_blank" rel="noopener">MakeMKV</a> (GuinpinSoft). If it is useful to you, consider supporting it by <a href="${MAKEMKV_BUY}" target="_blank" rel="noopener">buying a registration key</a>.</p>`;

function keyState(){
  const el = $('#keystate'); if(!el || !S) return;
  const k = S.key;
  el.innerHTML = k.custom ? `<span class="st ok">● active</span><div><strong>Your own key</strong><div class="muted" style="font-size:11px">in use</div></div>`
    : k.beta ? `<span class="st ok">● active</span><div><strong>Public beta key</strong><div class="muted" style="font-size:11px">fetched ${esc(ago(k.fetched))}</div></div><span class="spacer"></span><button type="button" class="secondary" id="keyref">Fetch again</button>`
    : `<span class="st warn">● missing</span><div><strong>No key available</strong><div class="muted" style="font-size:11px">${k.error ? esc(k.error) : 'The beta key has not been fetched yet.'}</div></div><span class="spacer"></span><button type="button" class="secondary" id="keyref">Fetch beta key</button>`;
  const kr = $('#keyref'); if(kr) kr.onclick = async () => { kr.disabled = true; try{ await api('/api/key/refresh'); }catch{} };
}
registerSettingsSection({
  id: 'key', label: 'MakeMKV key', order: 20, icon: '⚷', description: 'Without a key of your own, the app uses the public MakeMKV beta key.',
  render(el, s){
    el.innerHTML = `<div><label for="s-key">Your own MakeMKV key (optional)</label><input type="text" id="s-key" placeholder="empty = public beta key" autocomplete="off" spellcheck="false"></div>
      <div class="set-row" id="keystate"></div>${SUPPORT}`;
    $('#s-key').value = s.key;
    keyState();
  },
  collect(){ return { general: { key: $('#s-key').value } }; },
});
onState(keyState);

// Interim section with the two old fields; it goes away as soon as PF registers the "convert" section (settings.js then hides it)
registerSettingsSection({
  id: 'convert-basic', label: 'Conversion', order: 90, icon: '⎘', description: 'Parallelism and segments during conversion.',
  render(el, s){
    el.innerHTML = `<div class="two"><div><label for="s-conv_parallel">Files at the same time (conversion)</label><input type="number" id="s-conv_parallel" min="1" max="8" step="1"></div>
      <div><label for="s-conv_segments">Segments per movie (0 = automatic)</label><input type="number" id="s-conv_segments" min="0" max="12" step="1"></div></div>
      <p class="help" style="margin:0">x265 uses only about 4–8 cores per process – with "0" the app decides before every conversion based on free cores and RAM; 1 = never split.</p>`;
    $('#s-conv_parallel').value = s.conv_parallel; $('#s-conv_segments').value = s.conv_segments;
  },
  collect(){ return { general: { conv_parallel: +$('#s-conv_parallel').value || 1, conv_segments: Math.max(0, +$('#s-conv_segments').value || 0) } }; },
});

registerSettingsSection({
  id: 'about', label: 'About', order: 990, icon: 'ⓘ', readonly: true, description: 'What Spindle does itself and what comes from MakeMKV.',
  render(el){
    el.innerHTML = `<p style="margin:0"><strong>Spindle</strong> is a browser interface around <a href="${MAKEMKV}" target="_blank" rel="noopener">MakeMKV</a>. It is not affiliated with MakeMKV or endorsed by its maker.</p>
      <div class="two"><div><h3 style="font-size:13px;margin:4px 0">From MakeMKV</h3><p class="help" style="margin:0">Reading DVDs and Blu-rays, decryption, the title and track list, ripping titles to MKV and the decrypted disc backup.</p></div>
        <div><h3 style="font-size:13px;margin:4px 0">From Spindle</h3><p class="help" style="margin:0">Web interface, drive detection, title preselection and headless mode, staging and transfer to the NAS, conversion with ffmpeg, library and player, sorting for Jellyfin, cluster of several machines.</p></div></div>
      <p class="help" style="margin:0">MakeMKV is shareware: DVDs are free, Blu-ray support needs a registration key after the trial (the public beta key works meanwhile). Buying a key is the way to support its developer.</p>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><a class="primary" style="width:auto;text-decoration:none" href="${MAKEMKV_BUY}" target="_blank" rel="noopener">Support MakeMKV ↗</a><a class="secondary" href="${MAKEMKV}" target="_blank" rel="noopener">makemkv.com ↗</a></div>`;
  },
  collect(){ return {}; },
});
