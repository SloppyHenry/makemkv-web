// Titelliste, Dateinamen, „Nach dem Rippen konvertieren“ und das Aktionsfeld (Rippen, Backup, Auswerfen).
import { $, S, api, delegate, esc, fmtB, keyOf, pad, toast, ui } from './core.js';
import { CV_FALLBACK, CV_HELP, cvFields, cvSummary } from './cvform.js';
import { curDrive, driveUrl, dkey, outDir } from './drives.js';
import { isActive, onState, registerPanel } from './registry.js';

export const mainTitleIds = disc => { const max = Math.max(0, ...disc.titles.map(t=>t.duration)); return disc.titles.filter(t => t.duration >= max*0.5).map(t=>t.id); };
export function selOf(d){
  const k = keyOf(d);
  if(!ui.sel[k]){ ui.sel[k] = Object.fromEntries(d.disc.titles.map(t=>[t.id, false])); mainTitleIds(d.disc).forEach(i => ui.sel[k][i] = true); }
  return ui.sel[k];
}
// MakeMKV liefert oft für alle Titel den Disc-Namen -> bei Doppelten die Titelnummer anhängen
export function suggestName(disc, t){
  const base = (t.name || '').trim() || `Titel ${t.id+1}`;
  const dup = disc.titles.filter(x => (x.name||'').trim() === base).length > 1;
  return dup ? `${base} - Titel ${pad(t.id+1)}` : base;
}
export const discKind = d => /blu/i.test(d.disc.type||'') ? 'bluray' : 'dvd';
export function convOf(d){
  const k = keyOf(d);
  // Einstellungen (RF, Preset …) kommen aus dem gespeicherten Standard, der Haken „konvertieren“ ist bei jeder Disc zuerst AUS
  if(!ui.conv[k]) ui.conv[k] = {...CV_FALLBACK, ...((S.settings.presets||{})[discKind(d)]||{}), convert:false};
  return ui.conv[k];
}
// ---- Titelliste + Konvertierung
function renderTitles(d){
  const pn = $('#titlesPanel');
  if(!pn) return;
  if(!d || !d.disc){ pn.hidden = true; ui.sig.titles = ''; return; }
  pn.hidden = false;
  const sig = [dkey(d), d.scan_id, d.job ? d.job.kind : '', outDir(d)].join('|');
  if(ui.sig.titles !== sig){ ui.sig.titles = sig; buildTitles(d); } else updateTitlesLive(d);
}
function buildTitles(d){
  const disc = d.disc, k = keyOf(d), sel = selOf(d), names = ui.names[k] ||= {}, busy = !!d.job, dis = busy ? 'disabled' : '';
  const mainId = disc.titles.reduce((a,t) => t.duration > (a?.duration||0) ? t : a, null)?.id;
  if(ui.folder[k] === undefined) ui.folder[k] = disc.name || disc.volume || 'Disc';
  const c = convOf(d), kind = discKind(d)==='bluray' ? 'Blu-rays' : 'DVDs';
  const rows = disc.titles.map(t => {
    const cnt = ty => t.tracks.filter(x => x.type===ty).length, short = t.duration < 300, mut = short ? 'muted' : '';
    const open = ui.open[k+':'+t.id], nm = names[t.id] ?? suggestName(disc, t);
    const tag = t.id===mainId ? '<span class="tag red">Längster</span>' : short ? '<span class="tag">Kurz</span>' : '';
    const trk = open ? `<tr class="trk"><td colspan="7"><div class="trkgrid">${t.tracks.map(x => `<span>${esc(x.type)}</span><span>${esc(x.info||x.codec)}${x.res?' · '+esc(x.res):''}${x.layout?' · '+esc(x.layout):''}</span><span>${esc(x.lang||x.code)}</span>`).join('')}</div></td></tr>` : '';
    return `<tr data-t="${t.id}" data-short="${short}" class="${short && ui.hideShort ? 'hidden' : ''}">
      <td><input class="check" type="checkbox" data-sel="${t.id}" ${sel[t.id]?'checked':''} ${dis} aria-label="Titel ${t.id+1} auswählen"></td><td class="num">${t.id+1}</td>
      <td><div class="namecell"><input class="nameedit" type="text" data-name="${t.id}" value="${esc(nm)}" ${dis} aria-label="Dateiname Titel ${t.id+1}">${tag}</div></td>
      <td class="${mut}">${esc(t.duration_text)}</td><td class="${mut}">${esc(t.size_text)}</td><td class="${mut}">${t.chapters} Kap.</td>
      <td><button class="row-action" data-trk="${t.id}">${cnt('Video')} V · ${cnt('Audio')} A · ${cnt('Subtitles')} UT${open?'⌃':'⌄'}</button></td></tr>${trk}`;
  }).join('');
  $('#titlesPanel').innerHTML = `
    <div class="panel-head"><span class="mini-icon">☑</span><h2>Titel auswählen</h2><span class="spacer"></span><span class="sub" id="selectedCount"></span><button class="icon-btn" id="filterBtn" title="Kurze Titel (unter 5 Min.) ein-/ausblenden" aria-label="Kurze Titel ein-/ausblenden">▽</button></div>
    <div class="table-wrap"><table><thead><tr><th><input id="selectAll" class="check" type="checkbox" aria-label="Alle Titel auswählen" ${dis}></th><th>#</th><th>Dateiname</th><th>Dauer</th><th>Größe</th><th>Kapitel</th><th>Spuren</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="settings">
      <div class="settings-toggle" id="cvToggle" role="button" tabindex="0" aria-expanded="${ui.cvOpen}"><span class="mini-icon">⚙</span><strong>Nach dem Rippen konvertieren</strong><span class="summary" id="cvSummary"></span><span class="spacer"></span>
        <label class="switch" title="Konvertierung ein-/ausschalten"><input class="check" type="checkbox" data-cv="convert" ${c.convert?'checked':''} ${dis}> aktiv</label><span id="cvChev">${ui.cvOpen?'⌃':'⌄'}</span></div>
      <div class="settings-body ${ui.cvOpen?'':'hidden'} ${c.convert?'':'off'}" id="cvBody"><div class="fields">${cvFields(c,'cv',dis)}</div><p class="help">${esc(CV_HELP)}</p>
        <div style="margin-top:10px"><button class="secondary" data-act="savepreset" ${dis}>Als Standard für ${kind} speichern</button></div></div>
    </div>`;
  updateTitlesLive(d);
}
function updateTitlesLive(d){
  const disc = d.disc, sel = selOf(d), ts = disc.titles.filter(t => sel[t.id]), bytes = ts.reduce((a,t) => a+t.bytes, 0), c = convOf(d);
  const set = (id, v) => { const e = $(id); if(e) e.textContent = v; };
  set('#selectedCount', `${ts.length} ausgewählt`); set('#cvSummary', cvSummary(c));
  const all = $('#selectAll'); if(all){ all.checked = ts.length === disc.titles.length; all.indeterminate = ts.length>0 && ts.length<disc.titles.length; }
  const ac = $('#actionCount'); if(ac) ac.textContent = `${ts.length} Titel · ${fmtB(bytes)}${c.convert ? ' (Rohdaten)' : ''}`;
  const rip = $('#ripBtn'); if(rip) rip.disabled = !!d.job || !ts.length;
}
delegate('#titlesPanel', 'input', e => {
  const d = curDrive(); if(!d || !d.disc) return; const t = e.target, k = keyOf(d);
  if(t.dataset.sel !== undefined){ selOf(d)[t.dataset.sel] = t.checked; updateTitlesLive(d); }
  else if(t.id === 'selectAll'){ const sel = selOf(d); d.disc.titles.forEach(x => sel[x.id] = t.checked); document.querySelectorAll('#titlesPanel [data-sel]').forEach(c => c.checked = t.checked); updateTitlesLive(d); }
  else if(t.dataset.name !== undefined){ (ui.names[k] ||= {})[t.dataset.name] = t.value; }
  else if(t.dataset.cv !== undefined){
    const c = convOf(d), f = t.dataset.cv;
    c[f] = t.type==='checkbox' ? t.checked : f==='rf' ? (+t.value||21) : t.value;
    if(f === 'convert'){ const b = $('#cvBody'); if(b) b.classList.toggle('off', !t.checked); }
    updateTitlesLive(d);
  }
});
function toggleCv(){
  ui.cvOpen = !ui.cvOpen; $('#cvBody').classList.toggle('hidden', !ui.cvOpen); $('#cvChev').textContent = ui.cvOpen ? '⌃' : '⌄'; $('#cvToggle').setAttribute('aria-expanded', ui.cvOpen);
}
delegate('#titlesPanel', 'click', async e => {
  const d = curDrive(); if(!d || !d.disc) return; const t = e.target;
  if(t.closest('#filterBtn')){
    ui.hideShort = !ui.hideShort;
    document.querySelectorAll('#titlesPanel tr[data-short="true"]').forEach(r => r.classList.toggle('hidden', ui.hideShort));
    toast(ui.hideShort ? 'Kurze Titel ausgeblendet.' : 'Alle Titel werden angezeigt.');
  } else if(t.closest('[data-trk]')){ const kk = keyOf(d)+':'+t.closest('[data-trk]').dataset.trk; ui.open[kk] = !ui.open[kk]; buildTitles(d); }
  else if(t.closest('[data-act="savepreset"]')){ await api('/api/settings','POST',{presets:{[discKind(d)]: convOf(d)}}); toast('Als Standard gespeichert ✓'); }
  else if(t.closest('#cvToggle') && !t.closest('.switch')) toggleCv();
});
delegate('#titlesPanel', 'keydown', e => { if((e.key==='Enter'||e.key===' ') && e.target.id==='cvToggle'){ e.preventDefault(); toggleCv(); } });

// ---- Aktionsfeld
function renderAction(d){
  const el = $('#actionPanel');
  if(!el) return;
  const disc = d && d.disc, busy = !!(d && d.job);
  const sig = [d?dkey(d):'', d?d.scan_id:'', busy, d?d.status:'', !!disc, d?outDir(d):S.output.dir].join('|');
  if(ui.sig.action !== sig){
    ui.sig.action = sig;
    const k = d && keyOf(d);
    el.innerHTML = `<div class="destination"><span>♧</span><span><strong id="actionCount">${disc ? '' : 'Keine Disc'}</strong> · ${esc(d ? outDir(d) : S.output.dir)}${d && d.host ? ` · Laufwerk an ${esc(d.host)}` : ''}</span></div>
      ${disc ? `<div class="folderrow"><label for="folder">Ordner</label><input class="input" id="folder" value="${esc(ui.folder[k]||'')}" ${busy?'disabled':''}></div>` : ''}
      <button class="primary" id="ripBtn" data-act="rip" ${(!disc||busy)?'disabled':''}>${busy ? 'Läuft …' : '▶ &nbsp; Auswahl rippen'}</button>
      <div class="actions2"><button class="secondary" id="backupBtn" data-act="backup" title="Entschlüsselte Kopie der ganzen Disc als Ordner (BDMV/VIDEO_TS), keine MKV-Dateien" ${(!disc||busy)?'disabled':''}>Disc-Backup</button>${d && d.status==='ready' && !busy ? '<button class="secondary" data-act="scan">Neu analysieren</button>' : ''}${d && d.status==='open' ? '<button class="secondary" data-act="close">Schublade schließen</button>' : ''}${d ? `<button class="secondary" data-act="eject" ${busy?'disabled':''}>Auswerfen</button>` : ''}</div>`;
  }
  if(disc) updateTitlesLive(d);
}
delegate('#actionPanel', 'input', e => { const d = curDrive(); if(d && e.target.id==='folder') ui.folder[keyOf(d)] = e.target.value; });
async function startRip(d, mode){
  const k = keyOf(d), sel = selOf(d), names = ui.names[k]||{}, cv = convOf(d);
  const titles = mode==='mkv' ? d.disc.titles.filter(t => sel[t.id]).map(t => ({id:t.id, name:(names[t.id] ?? suggestName(d.disc, t)).trim()})) : [];
  if(mode==='mkv' && !titles.length){ toast('Bitte mindestens einen Titel auswählen.', true); return; }
  await api(driveUrl(d, 'rip'), 'POST', {titles, folder: ui.folder[k]||'', mode, convert: (mode==='mkv' && cv.convert) ? cv : null});
}
async function driveAction(ev){
  const b = ev.target.closest('[data-act]'); if(!b) return; const d = curDrive(); if(!d) return; const a = b.dataset.act;
  if(a==='scan') api(driveUrl(d, 'scan'));
  else if(a==='eject') api(driveUrl(d, 'eject'));
  else if(a==='close') api(driveUrl(d, 'close'));
  else if(a==='cancel'){ if(confirm('Laufenden Vorgang abbrechen?')) api(driveUrl(d, 'cancel')); }
  else if(a==='rip') startRip(d, 'mkv');
  else if(a==='backup'){ if(confirm('Disc-Backup = entschlüsselte Kopie der ganzen Disc als Ordner (keine MKV-Dateien). Das braucht den vollen Platz der Disc. Fortfahren?')) startRip(d, 'backup'); }
}
delegate('#actionPanel', 'click', driveAction);
delegate('#prog', 'click', driveAction);

onState(() => {
  if(!isActive('laufwerke')) return;
  const d = curDrive();
  renderTitles(d);
  renderAction(d);
});

registerPanel({view:'laufwerke', slot:'left', order:20, id:'titlesPanel', html:'<section class="panel" id="titlesPanel" hidden></section>'});
registerPanel({view:'laufwerke', slot:'right', order:40, id:'actionPanel', html:'<section class="panel action-panel" id="actionPanel"></section>'});
