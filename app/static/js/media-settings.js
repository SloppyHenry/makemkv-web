// Einstellungsabschnitt „Medien / Jellyfin“ (Kennung `media`). Speichern macht die Einstellungsseite (PB) über collect().
import { registerSettingsSection } from './registry.js';
import { changed, esc, fmtB, mapi } from './media-util.js';

const LANGS = [['de-DE', 'Deutsch (de-DE)'], ['en-US', 'Englisch (en-US)'], ['fr-FR', 'Französisch (fr-FR)'], ['es-ES', 'Spanisch (es-ES)'], ['it-IT', 'Italienisch (it-IT)']];
const seg = (name, opts, cur) => `<div class="media-seg full" data-seg="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" class="${cur === v ? 'on' : ''}" aria-pressed="${cur === v}">${l}</button>`).join('')}</div>`;
const chk = (id, on, label, extra = '') => `<label class="chk"><input class="check" type="checkbox" id="media-${id}" ${on ? 'checked' : ''}> <span>${label} ${extra}</span></label>`;

function example(st){
  if(st.naming === 'unveraendert') return '<span>Dateien und Ordner behalten ihre Namen und werden nur in den Filme- bzw. Serien-Ordner gelegt.</span>';
  const mt = st.id_tags ? ' [imdbid-tt1856101]' : '', stg = st.id_tags ? ' [tmdbid-1402]' : '', en = st.episode_names ? ' - Days Gone Bye' : '';
  return `<span>Film:</span> Filme/<em>Blade Runner 2049 (2017)${mt}</em>/<em>Blade Runner 2049 (2017)${mt}.mkv</em><br><span>Serie:</span> Serien/<em>The Walking Dead (2010)${stg}</em>/Season 01/<em>The Walking Dead S01E01${en}.mkv</em>`;
}

function render(el, settings){
  const m = {movies_dir: '', series_dir: '', naming: 'jellyfin', action: 'verschieben', language: 'de-DE', id_tags: true, episode_names: false, jellyfin_url: '', jellyfin_scan: false, auto: false, ...(settings.media || {})};
  const st = {...m, clearTmdb: false, clearJf: false, browse: null};
  const tmdbSet = () => m.tmdb_key_set && !st.clearTmdb, jfSet = () => m.jellyfin_key_set && !st.clearJf;
  el.innerHTML = `<div class="media-root">
    <div class="media-card"><header><h4>Ablage</h4><span class="sp"></span><span class="st" id="media-dirpill">wird geprüft …</span></header><div class="media-body">
      <div class="media-grid">
        ${['movies', 'series'].map(k => `<div class="field"><label for="media-${k}_dir">${k === 'movies' ? 'Filme' : 'Serien'}-Ordner</label>
          <div class="media-row"><input class="input" id="media-${k}_dir" value="${esc(st[k + '_dir'])}" autocomplete="off"><button type="button" class="secondary" data-browse="${k}">Wählen …</button></div>
          <div class="media-stat" id="media-stat-${k}"></div></div>`).join('')}
      </div>
      <div class="media-browse hidden" id="media-browse" aria-label="Ordnerauswahl"></div>
      <p class="help" style="margin:0">Auswahl nur innerhalb des eingehängten NAS. Beim Wählen wird geprüft, ob dort geschrieben werden darf.</p>
    </div></div>
    <div class="media-card"><header><h4>Benennung &amp; Aktion</h4></header><div class="media-body">
      <div class="media-grid"><div class="field"><label>Benennung</label>${seg('naming', [['jellyfin', 'Nach Jellyfin'], ['unveraendert', 'Unverändert']], st.naming)}</div>
        <div class="field"><label>Aktion</label>${seg('action', [['verschieben', 'Verschieben'], ['kopieren', 'Kopieren']], st.action)}</div></div>
      ${chk('id_tags', st.id_tags, 'ID im Namen ergänzen', '<span class="muted">(<code>[tmdbid-…]</code> bzw. <code>[imdbid-tt…]</code>, hilft Jellyfin bei der Zuordnung)</span>')}
      ${chk('episode_names', st.episode_names, 'Episodennamen anhängen', '<span class="muted">(<code>S01E01 - Days Gone Bye</code>)</span>')}
      <div class="field"><label>So heißen die Dateien dann (Beispiel)</label><div class="media-ex" id="media-example"></div></div>
      <p class="help" style="margin:0">„Unverändert“: Dateien und Ordner behalten ihre Namen und werden nur in den Filme- bzw. Serien-Ordner gelegt.</p>
    </div></div>
    <div class="media-card"><header><h4>Metadaten (TMDB)</h4><span class="sp"></span><span class="st" id="media-tmdbpill"></span></header><div class="media-body">
      <div class="media-note" id="media-nokey"><span class="media-ico">!</span><div><b>Ohne TMDB-Schlüssel</b> gibt es keine Titelvorschläge, keine Poster und keinen Laufzeit-Abgleich. Titel und Jahr trägst du dann von Hand ein, alles andere funktioniert wie sonst. Den Schlüssel (kostenlos) bekommst du in deinem Konto bei themoviedb.org unter Einstellungen → API.</div></div>
      <div class="field"><label for="media-tmdb_key">TMDB-API-Schlüssel</label>
        <div class="media-key"><input class="input" id="media-tmdb_key" type="password" autocomplete="off"><button type="button" class="secondary" id="media-tmdb-test">Testen</button><button type="button" class="secondary hidden" id="media-tmdb-del">Löschen</button></div>
        <div class="media-stat" id="media-tmdb-stat"></div></div>
      <div class="media-grid"><div class="field"><label for="media-language">Sprache für Titel und Beschreibung</label><select id="media-language">${LANGS.map(([v, l]) => `<option value="${v}" ${v === st.language ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
        <div class="field"><label>Zwischenspeicher</label><div class="media-row"><div class="muted" style="font-size:12px;align-self:center;flex:1" id="media-cache">…</div><button type="button" class="secondary" id="media-cache-clear">Leeren</button></div></div></div>
    </div></div>
    <div class="media-card"><header><h4>Jellyfin (optional)</h4><span class="sp"></span><span class="st" id="media-jfpill"></span></header><div class="media-body">
      <div class="media-grid"><div class="field"><label for="media-jellyfin_url">Server-Adresse</label><input class="input" id="media-jellyfin_url" placeholder="http://jellyfin.lan:8096" value="${esc(st.jellyfin_url)}"></div>
        <div class="field"><label for="media-jellyfin_key">API-Schlüssel</label><div class="media-key"><input class="input" id="media-jellyfin_key" type="password" autocomplete="off"><button type="button" class="secondary" id="media-jf-test">Testen</button><button type="button" class="secondary hidden" id="media-jf-del">Löschen</button></div><div class="media-stat" id="media-jf-stat"></div></div></div>
      ${chk('jellyfin_scan', st.jellyfin_scan, 'Nach dem Einsortieren die Jellyfin-Bibliothek aktualisieren lassen')}
    </div></div>
    <div class="media-card"><header><h4>Automatik</h4></header><div class="media-body">
      ${chk('auto', st.auto, 'Automatisch einsortieren, wenn eindeutig erkannt', '<span class="pill">Standard: aus</span>')}
      <p class="help" style="margin:0">Nur bei Treffern ab 95 % mit eindeutigen Episoden, nie bei Konflikten oder gesperrten Dateien. Alles Automatische steht in der Rückgängig-Liste. Braucht den TMDB-Schlüssel (ohne ihn bleibt alles liegen).</p>
    </div></div></div>`;
  const $ = s => el.querySelector(s);
  const keyUi = () => {
    $('#media-tmdb_key').placeholder = tmdbSet() ? '•••••••••••• (gespeichert, zum Ändern neu eingeben)' : 'Schlüssel (v3) oder Zugriffstoken (v4) hier einfügen';
    $('#media-jellyfin_key').placeholder = jfSet() ? '•••••••••••• (gespeichert, zum Ändern neu eingeben)' : 'Jellyfin → Dashboard → API-Schlüssel';
    $('#media-tmdb-del').classList.toggle('hidden', !tmdbSet()); $('#media-jf-del').classList.toggle('hidden', !jfSet());
    $('#media-nokey').classList.toggle('hidden', tmdbSet() || !!$('#media-tmdb_key').value.trim());
    const t = $('#media-tmdbpill'), j = $('#media-jfpill');
    t.className = 'st ' + (tmdbSet() ? 'ok' : 'warn'); t.textContent = tmdbSet() ? 'Schlüssel gespeichert' : 'kein Schlüssel';
    j.className = 'st' + (st.jellyfin_scan && jfSet() ? ' ok' : ''); j.textContent = st.jellyfin_scan && jfSet() ? 'an' : 'aus';
    $('#media-example').innerHTML = example(st);
  };
  const stat = (id, ok, text) => { const e = $(id); e.className = 'media-stat ' + (ok === null ? '' : ok ? 'ok' : 'bad'); e.textContent = text; };
  const check = async k => {
    const v = $(`#media-${k}_dir`).value.trim();
    try{
      const r = await mapi('/check-dir?path=' + encodeURIComponent(v), 'GET', null, true);
      stat('#media-stat-' + k, r.ok, r.ok ? `${r.exists ? 'beschreibbar' : r.why}${r.free ? ' · ' + fmtB(r.free) + ' frei' : ''}` : r.why);
      return r.ok;
    }catch(e){ stat('#media-stat-' + k, false, e.message); return false; }
  };
  const checkBoth = async () => {
    const [a, b] = await Promise.all([check('movies'), check('series')]);
    const p = $('#media-dirpill'); p.className = 'st ' + (a && b ? 'ok' : 'warn'); p.textContent = a && b ? 'beide beschreibbar' : 'Ordner prüfen';
  };
  let timer; const later = () => { clearTimeout(timer); timer = setTimeout(checkBoth, 500); };
  // Ordnerauswahl innerhalb des eingehängten Ziels
  const drawBrowse = d => {
    const b = $('#media-browse'), rel = d.path.slice(d.root.length).split('/').filter(Boolean);
    b.innerHTML = `<div class="media-crumb"><span>${esc(d.root)}</span>${rel.map(x => `›<b>${esc(x)}</b>`).join('')}</div>
      <div class="media-dirs">${d.parent ? `<button type="button" class="media-dir" data-dir="${esc(d.parent)}"><span class="media-fold"></span>..<small>eine Ebene hoch</small></button>` : ''}
        ${d.dirs.map(x => `<button type="button" class="media-dir" data-dir="${esc(x.path)}"><span class="media-fold"></span>${esc(x.name)}</button>`).join('') || '<div class="empty">keine Unterordner</div>'}</div>
      <footer><span id="media-mk"><button type="button" class="secondary" data-mkdir>Neuen Ordner anlegen …</button></span><span class="actions2" style="margin:0"><button type="button" class="secondary" data-close>Schließen</button><button type="button" class="primary" style="width:auto" data-pick="${esc(d.path)}">Diesen Ordner wählen</button></span></footer>`;
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
      $('#media-mk').innerHTML = '<input class="input" id="media-mkname" placeholder="Name des neuen Ordners" style="height:30px;width:180px"> <button type="button" class="secondary" data-mkok>Anlegen</button>'; $('#media-mkname').focus();
    }else if(t.dataset.mkok !== undefined){
      try{ const r = await mapi('/mkdir', 'POST', {path: st.browse.path, name: $('#media-mkname').value}); browse(r.path); }catch{ /* Meldung als Toast */ }
    }else if(t.id === 'media-tmdb-test'){
      const key = $('#media-tmdb_key').value.trim(); stat('#media-tmdb-stat', null, 'wird geprüft …');
      try{ const r = await mapi('/tmdb/test', 'POST', {key: key || null}, true); stat('#media-tmdb-stat', r.ok, r.ok ? r.message : r.message); }catch(x){ stat('#media-tmdb-stat', false, x.message); }
    }else if(t.id === 'media-jf-test'){
      stat('#media-jf-stat', null, 'wird geprüft …');
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
  const loadCache = async () => { try{ $('#media-cache').textContent = (await mapi('/cache', 'GET', null, true)).entries + ' Einträge'; }catch{ $('#media-cache').textContent = ''; } };
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
  id: 'media', label: 'Medien / Jellyfin', order: 40, icon: '▦',
  description: 'Wohin fertige Filme und Serien sortiert werden und wie sie heißen sollen.',
  render(el, settings){ current = el; render(el, settings); },
  collect(){ return current && current._mediaCollect ? current._mediaCollect() : {}; },
});
