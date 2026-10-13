// Settings section "Media / Jellyfin" (id `media`). Saving is done by the settings page (PB) via collect().
import { registerSettingsSection } from './registry.js';
import { changed, esc, fmtB, mapi } from './media-util.js';

const LANGS = [['en-US', 'English (en-US)'], ['de-DE', 'German (de-DE)'], ['fr-FR', 'French (fr-FR)'], ['es-ES', 'Spanish (es-ES)'], ['it-IT', 'Italian (it-IT)']];
const seg = (name, opts, cur) => `<div class="media-seg full" data-seg="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" class="${cur === v ? 'on' : ''}" aria-pressed="${cur === v}">${l}</button>`).join('')}</div>`;
const chk = (id, on, label, extra = '') => `<label class="chk"><input class="check" type="checkbox" id="media-${id}" ${on ? 'checked' : ''}> <span>${label} ${extra}</span></label>`;

function example(st){
  if(st.naming === 'unveraendert') return '<span>Files and folders keep their names and are only moved into the movies or series folder.</span>';
  const mt = st.id_tags ? ' [imdbid-tt1856101]' : '', stg = st.id_tags ? ' [tmdbid-1402]' : '', en = st.episode_names ? ' - Days Gone Bye' : '';
  return `<span>Movie:</span> Movies/<em>Blade Runner 2049 (2017)${mt}</em>/<em>Blade Runner 2049 (2017)${mt}.mkv</em><br><span>Series:</span> Series/<em>The Walking Dead (2010)${stg}</em>/Season 01/<em>The Walking Dead S01E01${en}.mkv</em>`;
}

function render(el, settings){
  const m = {movies_dir: '', series_dir: '', naming: 'jellyfin', action: 'verschieben', language: 'en-US', id_tags: true, episode_names: false, jellyfin_url: '', jellyfin_scan: false, auto: false, ...(settings.media || {})};
  const st = {...m, clearTmdb: false, clearJf: false, browse: null};
  const tmdbSet = () => m.tmdb_key_set && !st.clearTmdb, jfSet = () => m.jellyfin_key_set && !st.clearJf;
  el.innerHTML = `<div class="media-root">
    <div class="media-card"><header><h4>Storage</h4><span class="sp"></span><span class="st" id="media-dirpill">checking …</span></header><div class="media-body">
      <div class="media-grid">
        ${['movies', 'series'].map(k => `<div class="field"><label for="media-${k}_dir">${k === 'movies' ? 'Movies' : 'Series'} folder</label>
          <div class="media-row"><input class="input" id="media-${k}_dir" value="${esc(st[k + '_dir'])}" autocomplete="off"><button type="button" class="secondary" data-browse="${k}">Choose …</button></div>
          <div class="media-stat" id="media-stat-${k}"></div></div>`).join('')}
      </div>
      <div class="media-browse hidden" id="media-browse" aria-label="Folder selection"></div>
      <p class="help" style="margin:0">Only folders within the mounted NAS can be chosen. When choosing, it is checked whether writing there is allowed.</p>
    </div></div>
    <div class="media-card"><header><h4>Naming &amp; action</h4></header><div class="media-body">
      <div class="media-grid"><div class="field"><label>Naming</label>${seg('naming', [['jellyfin', 'Jellyfin style'], ['unveraendert', 'Unchanged']], st.naming)}</div>
        <div class="field"><label>Action</label>${seg('action', [['verschieben', 'Move'], ['kopieren', 'Copy']], st.action)}</div></div>
      ${chk('id_tags', st.id_tags, 'Add the ID to the name', '<span class="muted">(<code>[tmdbid-…]</code> or <code>[imdbid-tt…]</code>, helps Jellyfin match the title)</span>')}
      ${chk('episode_names', st.episode_names, 'Append episode names', '<span class="muted">(<code>S01E01 - Days Gone Bye</code>)</span>')}
      <div class="field"><label>The files will then be named like this (example)</label><div class="media-ex" id="media-example"></div></div>
      <p class="help" style="margin:0">"Unchanged": files and folders keep their names and are only moved into the movies or series folder.</p>
    </div></div>
    <div class="media-card"><header><h4>Metadata (TMDB)</h4><span class="sp"></span><span class="st" id="media-tmdbpill"></span></header><div class="media-body">
      <div class="media-note" id="media-nokey"><span class="media-ico">!</span><div><b>Without a TMDB key</b> there are no title suggestions, no posters and no runtime matching. You then enter title and year by hand; everything else works as usual. You get the (free) key in your account at themoviedb.org under Settings → API.</div></div>
      <div class="field"><label for="media-tmdb_key">TMDB API key</label>
        <div class="media-key"><input class="input" id="media-tmdb_key" type="password" autocomplete="off"><button type="button" class="secondary" id="media-tmdb-test">Test</button><button type="button" class="secondary hidden" id="media-tmdb-del">Delete</button></div>
        <div class="media-stat" id="media-tmdb-stat"></div></div>
      <div class="media-grid"><div class="field"><label for="media-language">Language for titles and descriptions</label><select id="media-language">${LANGS.map(([v, l]) => `<option value="${v}" ${v === st.language ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
        <div class="field"><label>Cache</label><div class="media-row"><div class="muted" style="font-size:12px;align-self:center;flex:1" id="media-cache">…</div><button type="button" class="secondary" id="media-cache-clear">Clear</button></div></div></div>
    </div></div>
    <div class="media-card"><header><h4>Jellyfin (optional)</h4><span class="sp"></span><span class="st" id="media-jfpill"></span></header><div class="media-body">
      <div class="media-grid"><div class="field"><label for="media-jellyfin_url">Server address</label><input class="input" id="media-jellyfin_url" placeholder="http://jellyfin.lan:8096" value="${esc(st.jellyfin_url)}"></div>
        <div class="field"><label for="media-jellyfin_key">API key</label><div class="media-key"><input class="input" id="media-jellyfin_key" type="password" autocomplete="off"><button type="button" class="secondary" id="media-jf-test">Test</button><button type="button" class="secondary hidden" id="media-jf-del">Delete</button></div><div class="media-stat" id="media-jf-stat"></div></div></div>
      ${chk('jellyfin_scan', st.jellyfin_scan, 'Have Jellyfin refresh its library after sorting')}
    </div></div>
    <div class="media-card"><header><h4>Automation</h4></header><div class="media-body">
      ${chk('auto', st.auto, 'Sort automatically when detected unambiguously', '<span class="pill">Default: off</span>')}
      <p class="help" style="margin:0">Only for matches of 95 % or more with unambiguous episodes, never on conflicts or locked files. Everything automatic is listed for undo. Needs the TMDB key (without it, everything stays where it is).</p>
    </div></div></div>`;
  const $ = s => el.querySelector(s);
  const keyUi = () => {
    $('#media-tmdb_key').placeholder = tmdbSet() ? '•••••••••••• (saved, enter a new one to change it)' : 'Paste the key here (v3 or v4)';
    $('#media-jellyfin_key').placeholder = jfSet() ? '•••••••••••• (saved, enter a new one to change it)' : 'Jellyfin → Dashboard → API keys';
    $('#media-tmdb-del').classList.toggle('hidden', !tmdbSet()); $('#media-jf-del').classList.toggle('hidden', !jfSet());
    $('#media-nokey').classList.toggle('hidden', tmdbSet() || !!$('#media-tmdb_key').value.trim());
    const t = $('#media-tmdbpill'), j = $('#media-jfpill');
    t.className = 'st ' + (tmdbSet() ? 'ok' : 'warn'); t.textContent = tmdbSet() ? 'key saved' : 'no key';
    j.className = 'st' + (st.jellyfin_scan && jfSet() ? ' ok' : ''); j.textContent = st.jellyfin_scan && jfSet() ? 'on' : 'off';
    $('#media-example').innerHTML = example(st);
  };
  const stat = (id, ok, text) => { const e = $(id); e.className = 'media-stat ' + (ok === null ? '' : ok ? 'ok' : 'bad'); e.textContent = text; };
  const check = async k => {
    const v = $(`#media-${k}_dir`).value.trim();
    try{
      const r = await mapi('/check-dir?path=' + encodeURIComponent(v), 'GET', null, true);
      stat('#media-stat-' + k, r.ok, r.ok ? `${r.exists ? 'writable' : r.why}${r.free ? ' · ' + fmtB(r.free) + ' free' : ''}` : r.why);
      return r.ok;
    }catch(e){ stat('#media-stat-' + k, false, e.message); return false; }
  };
  const checkBoth = async () => {
    const [a, b] = await Promise.all([check('movies'), check('series')]);
    const p = $('#media-dirpill'); p.className = 'st ' + (a && b ? 'ok' : 'warn'); p.textContent = a && b ? 'both writable' : 'check folders';
  };
  let timer; const later = () => { clearTimeout(timer); timer = setTimeout(checkBoth, 500); };
  // folder selection within the mounted target
  const drawBrowse = d => {
    const b = $('#media-browse'), rel = d.path.slice(d.root.length).split('/').filter(Boolean);
    b.innerHTML = `<div class="media-crumb"><span>${esc(d.root)}</span>${rel.map(x => `›<b>${esc(x)}</b>`).join('')}</div>
      <div class="media-dirs">${d.parent ? `<button type="button" class="media-dir" data-dir="${esc(d.parent)}"><span class="media-fold"></span>..<small>one level up</small></button>` : ''}
        ${d.dirs.map(x => `<button type="button" class="media-dir" data-dir="${esc(x.path)}"><span class="media-fold"></span>${esc(x.name)}</button>`).join('') || '<div class="empty">no subfolders</div>'}</div>
      <footer><span id="media-mk"><button type="button" class="secondary" data-mkdir>Create a new folder …</button></span><span class="actions2" style="margin:0"><button type="button" class="secondary" data-close>Close</button><button type="button" class="primary" style="width:auto" data-pick="${esc(d.path)}">Choose this folder</button></span></footer>`;
  };
  const browse = async path => {
    try{ const d = await mapi('/browse?path=' + encodeURIComponent(path || ''), 'GET', null, true); st.browse.path = d.path; drawBrowse(d); }
    catch{ if(path) browse(''); }
  };
  el.addEventListener('click', async e => {
    const t = e.target.closest('button'); if(!t) return;
    if(t.dataset.v && t.parentElement.dataset.seg){ st[t.parentElement.dataset.seg] = t.dataset.v; t.parentElement.querySelectorAll('button').forEach(b => { b.classList.toggle('on', b === t); b.setAttribute('aria-pressed', b === t); }); keyUi(); changed(t); }
    else if(t.dataset.browse){ const k = t.dataset.browse; st.browse = {field: k}; $('#media-browse').classList.remove('hidden'); browse($(`#media-${k}_dir`).value.trim()); }
    else if(t.dataset.dir !== undefined) browse(t.dataset.dir);
    else if(t.dataset.close !== undefined) $('#media-browse').classList.add('hidden');
    else if(t.dataset.pick){ const i = $(`#media-${st.browse.field}_dir`); i.value = t.dataset.pick; $('#media-browse').classList.add('hidden'); changed(i); checkBoth(); }
    else if(t.dataset.mkdir !== undefined){
      $('#media-mk').innerHTML = '<input class="input" id="media-mkname" placeholder="Name of the new folder" style="height:30px;width:180px"> <button type="button" class="secondary" data-mkok>Create</button>'; $('#media-mkname').focus();
    }else if(t.dataset.mkok !== undefined){
      try{ const r = await mapi('/mkdir', 'POST', {path: st.browse.path, name: $('#media-mkname').value}); browse(r.path); }catch{ /* message shown as a toast */ }
    }else if(t.id === 'media-tmdb-test'){
      const key = $('#media-tmdb_key').value.trim(); stat('#media-tmdb-stat', null, 'checking …');
      try{ const r = await mapi('/tmdb/test', 'POST', {key: key || null}, true); stat('#media-tmdb-stat', r.ok, r.ok ? r.message : r.message); }catch(x){ stat('#media-tmdb-stat', false, x.message); }
    }else if(t.id === 'media-jf-test'){
      stat('#media-jf-stat', null, 'checking …');
      try{ const r = await mapi('/jellyfin/test', 'POST', {key: $('#media-jellyfin_key').value.trim() || null, url: $('#media-jellyfin_url').value.trim() || null}, true); stat('#media-jf-stat', r.ok, r.message); }catch(x){ stat('#media-jf-stat', false, x.message); }
    }else if(t.id === 'media-tmdb-del'){ st.clearTmdb = true; $('#media-tmdb_key').value = ''; keyUi(); changed(t); }
    else if(t.id === 'media-jf-del'){ st.clearJf = true; $('#media-jellyfin_key').value = ''; keyUi(); changed(t); }
    else if(t.id === 'media-cache-clear'){ await mapi('/cache/clear', 'POST', {}); loadCache(); }
  });
  el.addEventListener('input', e => {
    if(e.target.id === 'media-movies_dir' || e.target.id === 'media-series_dir') later();
    if(e.target.id === 'media-tmdb_key'){ st.clearTmdb = false; keyUi(); }
    if(e.target.id === 'media-jellyfin_key') st.clearJf = false;
  });
  el.addEventListener('change', e => {
    const id = e.target.id;
    if(id === 'media-id_tags' || id === 'media-episode_names' || id === 'media-jellyfin_scan'){ st[id.slice(6)] = e.target.checked; keyUi(); }
    if(id === 'media-jellyfin_url') later();
  });
  const loadCache = async () => { try{ $('#media-cache').textContent = (await mapi('/cache', 'GET', null, true)).entries + ' entries'; }catch{ $('#media-cache').textContent = ''; } };
  keyUi(); checkBoth(); loadCache();
  el._mediaState = {st, field: id => $('#media-' + id)};
  el._mediaCollect = () => {
    const v = id => $('#media-' + id).value.trim();
    const key = (id, clear) => clear ? '' : (v(id) || null);
    return {media: {movies_dir: v('movies_dir'), series_dir: v('series_dir'), naming: st.naming, action: st.action, language: $('#media-language').value, id_tags: $('#media-id_tags').checked,
      episode_names: $('#media-episode_names').checked, jellyfin_url: v('jellyfin_url'), jellyfin_scan: $('#media-jellyfin_scan').checked, auto: $('#media-auto').checked,
      tmdb_key: key('tmdb_key', st.clearTmdb), jellyfin_key: key('jellyfin_key', st.clearJf)}};
  };
}

let current = null;
registerSettingsSection({
  id: 'media', label: 'Media / Jellyfin', order: 40, icon: '▦',
  description: 'Where finished movies and series are sorted to and how they should be named.',
  render(el, settings){ current = el; render(el, settings); },
  collect(){ return current && current._mediaCollect ? current._mediaCollect() : {}; },
});
