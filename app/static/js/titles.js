// Title list, file names, "Convert after ripping" and the action panel (rip, backup, eject).
import { $, S, api, delegate, esc, fmtB, keyOf, pad, toast, ui } from './core.js';
import { cvSummary, getDefaultConfig, mountConvertEditor } from './convert-editor.js';
import { curDrive, driveUrl, dkey, outDir } from './drives.js';
import { isActive, onState, registerPanel } from './registry.js';

// Preselection = the server's title choice (disc.suggest: memory → TheDiscDB → TMDB → structure, as in headless mode) including names and folder.
// Until it arrives, the long titles (mainTitleIds); it is applied only as long as nothing was changed by hand.
export const mainTitleIds = disc => { const max = Math.max(0, ...disc.titles.map(t=>t.duration)); return disc.titles.filter(t => t.duration >= max*0.5).map(t=>t.id); };
export function selOf(d){
  const k = keyOf(d), sg = d.disc.suggest;
  if(!ui.sel[k] || (sg && ui.pre[k] === 'wait')){
    const ids = sg ? sg.picks : mainTitleIds(d.disc);
    ui.sel[k] = Object.fromEntries(d.disc.titles.map(t => [t.id, ids.includes(t.id)]));
    if(sg){ ui.names[k] = {...sg.names}; if(sg.folder) ui.folder[k] = sg.folder; }
    ui.pre[k] = sg ? 'done' : 'wait';
  }
  return ui.sel[k];
}
const touched = d => { ui.pre[keyOf(d)] = 'user'; };
const suggestNote = disc => {
  const sg = disc.suggest;
  return `<div class="suggest-note">${sg ? `Preselection${sg.source ? ` (${esc(sg.source)})` : ''}: ${esc(sg.reasons[0] || '')}` : 'Determining preselection …'}</div>`;
};
// MakeMKV often returns the disc name for every title -> append the title number to duplicates
export function suggestName(disc, t){
  const base = (t.name || '').trim() || `Title ${t.id+1}`;
  const dup = disc.titles.filter(x => (x.name||'').trim() === base).length > 1;
  return dup ? `${base} - Title ${pad(t.id+1)}` : base;
}
export const discKind = d => /blu/i.test(d.disc.type||'') ? 'bluray' : 'dvd';
export function convOf(d){
  const k = keyOf(d);
  // cfg (settings) comes from the convert editor (null = default for the disc type); the "convert" switch starts OFF for every disc
  if(!ui.conv[k]) ui.conv[k] = {convert:false, cfg:null};
  return ui.conv[k];
}
let editor = null;
const killEditor = () => { if(editor){ editor.destroy(); editor = null; } };
function mountEditor(d, dis){
  killEditor();
  const el = $('#cvEditor'); if(!el) return;
  const c = convOf(d);
  editor = mountConvertEditor(el, c.cfg, {mode:'compact', discKind:discKind(d), readonly:!!dis, onChange: cfg => { c.cfg = cfg; updateTitlesLive(curDrive() || d); }});
  getDefaultConfig(discKind(d)).then(def => { if(!c.cfg){ c.cfg = def; updateTitlesLive(curDrive() || d); } });
}
// ---- Title list + conversion
function renderTitles(d){
  const pn = $('#titlesPanel');
  if(!pn) return;
  if(!d || !d.disc){ pn.hidden = true; ui.sig.titles = ''; killEditor(); return; }
  pn.hidden = false;
  const sig = [dkey(d), d.scan_id, d.job ? d.job.kind : '', outDir(d), !!d.disc.suggest].join('|');
  if(ui.sig.titles !== sig){ ui.sig.titles = sig; buildTitles(d); } else updateTitlesLive(d);
}
function buildTitles(d){
  const disc = d.disc, sel = selOf(d), k = keyOf(d), names = ui.names[k] ||= {}, busy = !!d.job, dis = busy ? 'disabled' : '';
  const mainId = disc.titles.reduce((a,t) => t.duration > (a?.duration||0) ? t : a, null)?.id;
  if(ui.folder[k] === undefined) ui.folder[k] = disc.name || disc.volume || 'Disc';
  const c = convOf(d);
  const rows = disc.titles.map(t => {
    const cnt = ty => t.tracks.filter(x => x.type===ty).length, short = t.duration < 300, mut = short ? 'muted' : '';
    const open = ui.open[k+':'+t.id], nm = names[t.id] ?? suggestName(disc, t);
    const tag = t.id===mainId ? '<span class="tag red">Longest</span>' : short ? '<span class="tag">Short</span>' : '';
    const trk = open ? `<tr class="trk"><td colspan="7"><div class="trkgrid">${t.tracks.map(x => `<span>${esc(x.type)}</span><span>${esc(x.info||x.codec)}${x.res?' · '+esc(x.res):''}${x.layout?' · '+esc(x.layout):''}</span><span>${esc(x.lang||x.code)}</span>`).join('')}</div></td></tr>` : '';
    return `<tr data-t="${t.id}" data-short="${short}" class="${short && ui.hideShort ? 'hidden' : ''}">
      <td><input class="check" type="checkbox" data-sel="${t.id}" ${sel[t.id]?'checked':''} ${dis} aria-label="Select title ${t.id+1}"></td><td class="num">${t.id+1}</td>
      <td><div class="namecell"><input class="nameedit" type="text" data-name="${t.id}" value="${esc(nm)}" ${dis} aria-label="File name of title ${t.id+1}">${tag}</div></td>
      <td class="${mut}">${esc(t.duration_text)}</td><td class="${mut}">${esc(t.size_text)}</td><td class="${mut}">${t.chapters} ch.</td>
      <td><button class="row-action" data-trk="${t.id}">${cnt('Video')} V · ${cnt('Audio')} A · ${cnt('Subtitles')} S${open?'⌃':'⌄'}</button></td></tr>${trk}`;
  }).join('');
  $('#titlesPanel').innerHTML = `
    <div class="panel-head"><span class="mini-icon">☑</span><h2>Choose titles</h2><span class="spacer"></span><span class="sub" id="selectedCount"></span><button class="icon-btn" id="filterBtn" title="Show/hide short titles (under 5 min)" aria-label="Show/hide short titles">▽</button></div>${suggestNote(disc)}
    <div class="table-wrap"><table><thead><tr><th><input id="selectAll" class="check" type="checkbox" aria-label="Select all titles" ${dis}></th><th>#</th><th>File name</th><th>Duration</th><th>Size</th><th>Chapters</th><th>Tracks</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="settings">
      <div class="settings-toggle" id="cvToggle" role="button" tabindex="0" aria-expanded="${ui.cvOpen}"><span class="mini-icon">⚙</span><strong>Convert after ripping</strong><span class="summary" id="cvSummary"></span><span class="spacer"></span>
        <label class="switch" title="Turn conversion on/off"><input class="check" type="checkbox" data-cv="convert" ${c.convert?'checked':''} ${dis}> on</label><span id="cvChev">${ui.cvOpen?'⌃':'⌄'}</span></div>
      <div class="settings-body ${ui.cvOpen?'':'hidden'} ${c.convert?'':'off'}" id="cvBody"><div id="cvEditor"></div></div>
    </div>`;
  mountEditor(d, dis);
  updateTitlesLive(d);
}
function updateTitlesLive(d){
  const disc = d.disc, sel = selOf(d), ts = disc.titles.filter(t => sel[t.id]), bytes = ts.reduce((a,t) => a+t.bytes, 0), c = convOf(d);
  const set = (id, v) => { const e = $(id); if(e) e.textContent = v; };
  set('#selectedCount', `${ts.length} selected`); set('#cvSummary', c.cfg ? cvSummary(c.cfg) : '');
  const all = $('#selectAll'); if(all){ all.checked = ts.length === disc.titles.length; all.indeterminate = ts.length>0 && ts.length<disc.titles.length; }
  const ac = $('#actionCount'); if(ac) ac.textContent = `${ts.length} title${ts.length === 1 ? '' : 's'} · ${fmtB(bytes)}${c.convert ? ' (raw)' : ''}`;
  const rip = $('#ripBtn'); if(rip) rip.disabled = !!d.job || !ts.length;
}
delegate('#titlesPanel', 'input', e => {
  const d = curDrive(); if(!d || !d.disc) return; const t = e.target, k = keyOf(d);
  if(t.dataset.sel !== undefined || t.id === 'selectAll' || t.dataset.name !== undefined) touched(d);
  if(t.dataset.sel !== undefined){ selOf(d)[t.dataset.sel] = t.checked; updateTitlesLive(d); }
  else if(t.id === 'selectAll'){ const sel = selOf(d); d.disc.titles.forEach(x => sel[x.id] = t.checked); document.querySelectorAll('#titlesPanel [data-sel]').forEach(c => c.checked = t.checked); updateTitlesLive(d); }
  else if(t.dataset.name !== undefined){ (ui.names[k] ||= {})[t.dataset.name] = t.value; }
  else if(t.dataset.cv === 'convert'){
    convOf(d).convert = t.checked; const b = $('#cvBody'); if(b) b.classList.toggle('off', !t.checked);
    updateTitlesLive(d);
  }
});
function toggleCv(){
  ui.cvOpen = !ui.cvOpen; $('#cvBody').classList.toggle('hidden', !ui.cvOpen); $('#cvChev').textContent = ui.cvOpen ? '⌃' : '⌄'; $('#cvToggle').setAttribute('aria-expanded', ui.cvOpen);
}
delegate('#titlesPanel', 'click', e => {
  const d = curDrive(); if(!d || !d.disc) return; const t = e.target;
  if(t.closest('#filterBtn')){
    ui.hideShort = !ui.hideShort;
    document.querySelectorAll('#titlesPanel tr[data-short="true"]').forEach(r => r.classList.toggle('hidden', ui.hideShort));
    toast(ui.hideShort ? 'Short titles hidden.' : 'Showing all titles.');
  } else if(t.closest('[data-trk]')){ const kk = keyOf(d)+':'+t.closest('[data-trk]').dataset.trk; ui.open[kk] = !ui.open[kk]; buildTitles(d); }
  else if(t.closest('#cvToggle') && !t.closest('.switch')) toggleCv();
});
delegate('#titlesPanel', 'keydown', e => { if((e.key==='Enter'||e.key===' ') && e.target.id==='cvToggle'){ e.preventDefault(); toggleCv(); } });

// ---- Action panel
function renderAction(d){
  const el = $('#actionPanel');
  if(!el) return;
  const disc = d && d.disc, busy = !!(d && d.job);
  const sig = [d?dkey(d):'', d?d.scan_id:'', busy, !!(disc && disc.suggest), d?d.status:'', !!disc, d?outDir(d):S.output.dir].join('|');
  if(ui.sig.action !== sig){
    ui.sig.action = sig;
    const k = d && keyOf(d);
    el.innerHTML = `<div class="destination"><span>♧</span><span><strong id="actionCount">${disc ? '' : 'No disc'}</strong> · ${esc(d ? outDir(d) : S.output.dir)}${d && d.host ? ` · drive on ${esc(d.host)}` : ''}</span></div>
      ${disc ? `<div class="folderrow"><label for="folder">Folder</label><input class="input" id="folder" value="${esc(ui.folder[k]||'')}" ${busy?'disabled':''}></div>` : ''}
      <button class="primary" id="ripBtn" data-act="rip" ${(!disc||busy)?'disabled':''}>${busy ? 'Running …' : '▶ &nbsp; Rip selection'}</button>
      <div class="actions2"><button class="secondary" id="backupBtn" data-act="backup" title="Decrypted copy of the whole disc as a folder (BDMV/VIDEO_TS), no MKV files" ${(!disc||busy)?'disabled':''}>Disc backup</button>${d && d.status==='ready' && !busy ? '<button class="secondary" data-act="scan">Analyze again</button>' : ''}${d && d.status==='open' ? '<button class="secondary" data-act="close">Close tray</button>' : ''}${d ? `<button class="secondary" data-act="eject" ${busy?'disabled':''}>Eject</button>` : ''}</div>`;
  }
  if(disc) updateTitlesLive(d);
}
delegate('#actionPanel', 'input', e => { const d = curDrive(); if(d && e.target.id==='folder'){ ui.folder[keyOf(d)] = e.target.value; touched(d); } });
async function startRip(d, mode){
  const k = keyOf(d), sel = selOf(d), names = ui.names[k]||{}, cv = convOf(d);
  const cfg = (mode==='mkv' && cv.convert) ? {...(cv.cfg || await getDefaultConfig(discKind(d))), convert:true} : null;
  const titles = mode==='mkv' ? d.disc.titles.filter(t => sel[t.id]).map(t => ({id:t.id, name:(names[t.id] ?? suggestName(d.disc, t)).trim()})) : [];
  if(mode==='mkv' && !titles.length){ toast('Please select at least one title.', true); return; }
  await api(driveUrl(d, 'rip'), 'POST', {titles, folder: ui.folder[k]||'', mode, convert: cfg});
}
async function driveAction(ev){
  const b = ev.target.closest('[data-act]'); if(!b) return; const d = curDrive(); if(!d) return; const a = b.dataset.act;
  if(a==='scan') api(driveUrl(d, 'scan'));
  else if(a==='eject') api(driveUrl(d, 'eject'));
  else if(a==='close') api(driveUrl(d, 'close'));
  else if(a==='cancel'){ if(confirm('Cancel the running operation?')) api(driveUrl(d, 'cancel')); }
  else if(a==='rip') startRip(d, 'mkv');
  else if(a==='backup'){ if(confirm('Disc backup = decrypted copy of the whole disc as a folder (no MKV files). It needs the full size of the disc. Continue?')) startRip(d, 'backup'); }
}
delegate('#actionPanel', 'click', driveAction);
delegate('#prog', 'click', driveAction);

onState(() => {
  if(!isActive('drives')) return;
  const d = curDrive();
  renderTitles(d);
  renderAction(d);
});

registerPanel({view:'drives', slot:'left', order:20, id:'titlesPanel', html:'<section class="panel" id="titlesPanel" hidden></section>'});
registerPanel({view:'drives', slot:'right', order:1, id:'actionPanel', html:'<section class="panel action-panel" id="actionPanel"></section>'});
