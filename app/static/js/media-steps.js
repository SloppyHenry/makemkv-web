// "Sort" wizard: rendering of the five steps (pure HTML from the state `w`, layout 1:1 after docs/mockups/paket-e.html).
import { baseName, esc, fmtB, fmtDur, pct, shortName } from './media-util.js';

export const STEPS = ['Detected', 'Title', 'Episodes', 'Preview', 'Done'];
const KIND = {series: 'Series', movie: 'Movie', extras: 'Extras for a movie'};
const seg = (name, opts, cur) => `<div class="media-seg full">${opts.map(([v, l]) => `<button type="button" data-act="${name}:${v}" class="${cur === v ? 'on' : ''}">${l}</button>`).join('')}</div>`;
const note = (cls, ico, html) => `<div class="media-note ${cls}"><span class="media-ico">${ico}</span><div>${html}</div></div>`;
const poster = (w, url, title, v = '') => url ? `<div class="media-poster ${v}"><span>${esc(title)}</span><img src="${esc(url)}" alt="" onerror="this.remove()"></div>`
  : `<div class="media-poster none">no poster${w.tmdbOn ? '' : '<br>(no key)'}</div>`;
const variant = i => ['', 'b', 'c'][i % 3];
const nsteps = w => w.kind === 'series' ? 5 : 4;

export function stepper(w){
  const skip3 = w.kind !== 'series';
  const items = STEPS.map((s, i) => { const n = i + 1, cls = n === w.step ? 'cur' : (n < w.step && !(skip3 && n === 3)) ? 'done' : (skip3 && n === 3) ? 'skip' : ''; return `<li class="${cls}"><i>${cls === 'done' ? '✓' : n}</i>${s}</li>`; }).join('');
  const shown = skip3 && w.step >= 4 ? w.step - 1 : w.step;
  return `<ol class="media-steps">${items}</ol><div class="media-stepline"><b>Step ${shown} of ${nsteps(w)} · ${STEPS[w.step - 1]}</b><div class="bar"><i style="width:${shown / nsteps(w) * 100}%"></i></div></div>`;
}

const reasons = d => (d.reasons || []).map(r => `<span class="tag">${esc(r)}</span>`).join('');
const roleLabel = {episode: 'Episode', playall: 'Play-all', movie: 'Main feature', extra: 'Extra', skip: 'left out'};

function filesList(w){
  const rows = w.items.map((it, i) => {
    const take = w.kind !== 'series' && it.role === 'extra' ? `<label class="chk" style="display:inline-flex;margin-right:8px"><input class="check" type="checkbox" data-f="take" data-i="${i}" ${w.skip.has(it.path) ? '' : 'checked'} aria-label="include"></label>` : '';
    return `<li>${take}${esc(baseName(it.path))} <span>${fmtDur(it.dur)}${it.dur ? '' : ' (runtime unknown)'} · ${fmtB(it.size)} · ${roleLabel[it.role] || ''}</span></li>`;
  }).join('');
  return `<details class="media-files"><summary>View ${w.items.length} ${w.items.length === 1 ? 'file' : 'files'}</summary><ul>${rows}</ul></details>`;
}

export function stepDetect(w){
  const d = w.det.detect, t = w.det.tmdb, c = w.chosen;
  const sure = d.confidence >= 0.8, none = d.kind === 'unknown';
  const b = t => `<b style="color:var(--text)">${t}</b>`;
  const kindWord = none ? (w.kind === 'series' ? 'a series' : 'a movie') : w.kind === 'series' ? 'a series' : w.kind === 'movie' ? 'a movie' : 'extras for a movie';
  const meta = w.kind === 'series' ? `Season ${w.season} · ${w.disc ? 'Disc ' + w.disc + ' · ' : ''}${w.items.filter(i => i.role === 'episode').length} episodes${w.items.some(i => i.role === 'playall') ? ' + play-all' : ''}`
    : `${w.items.length} ${w.items.length === 1 ? 'title' : 'titles'}${w.items[0] ? ' · ' + fmtDur(Math.max(...w.items.map(i => i.dur))) : ''}`;
  const ids = c ? ` · TMDB ${c.tmdb}${c.imdb ? ' · IMDb ' + esc(c.imdb) : ''}` : '';
  let h = `<div class="media-detect">${poster(w, c && c.poster_url, w.title)}<div>
    <p class="media-meta" style="margin:0 0 2px">${none ? `Not detected with certainty, maybe ${b(kindWord)}` : `This looks like ${b(kindWord)}`}</p>
    <h4>${esc(w.title || 'Unknown title')} ${w.year ? `<span class="muted" style="font-weight:450">(${w.year})</span>` : ''}</h4>
    <p class="media-meta">${esc(meta)}${esc(ids)}</p>
    <div class="media-conf ${sure ? '' : 'mid'}"><strong>${pct(d.confidence)} %</strong><div class="bar"><i style="width:${pct(d.confidence)}%"></i></div><span class="muted">${sure ? 'certain' : 'please check'}</span></div>
    <div class="media-why">${reasons(d)}</div></div></div>`;
  if(!w.tmdbOn) h += note('info', 'i', 'Without a TMDB key the name cannot be checked against TMDB. Please confirm title and year or change them by hand in the next step.');
  else if(t.error) h += note('err', '!', esc(t.error));
  else if(!c) h += note('', '!', '<b>No match on TMDB.</b> In the next step you can search or enter the IMDb ID.');
  if(w.tmdbOn && !sure && c) h += note('', '!', '<b>Not quite certain.</b> The year or the title does not match unambiguously. Other options:');
  if(w.tmdbOn && (!sure || !c) && t.candidates.length) h += `<div class="media-hits">${t.candidates.filter(x => !c || x.tmdb !== c.tmdb).slice(0, 3).map((x, i) => hit(x, i, false, 'use-cand:' + x.tmdb)).join('')}</div>`;
  h += filesList(w);
  h += `<div class="media-or">or it is something else</div>${seg('kind', Object.entries(KIND), w.kind)}`;
  h += `<div><button type="button" class="media-link" data-act="history">Recent actions / undo …</button></div>`;
  return {body: h, footer: `<button type="button" class="secondary" data-act="close">Cancel</button><span class="sp"></span><button type="button" class="secondary" data-act="goto:2">Search for another title</button><button type="button" class="primary" data-act="next">Looks right, next</button>`};
}

const hit = (x, i, sel, act) => `<button type="button" class="media-hit ${sel ? 'sel' : ''}" data-act="${act}">${poster({tmdbOn: true}, x.poster_url, x.title, variant(i))}
  <div><h5>${esc(x.title)}<small>${x.year || ''}</small></h5><p>${esc(x.overview || 'No description.')}</p><div class="ids"><span class="tag" style="margin:0">tmdb ${x.tmdb}</span>${x.imdb ? `<span class="tag" style="margin:0">${esc(x.imdb)}</span>` : ''}</div></div>
  <span class="tag go">${sel ? 'chosen' : 'choose'}</span></button>`;

export function stepSearch(w){
  const s = w.s, series = w.kind === 'series';
  const kindSeg = `<div class="media-seg"><button type="button" data-act="s-type:tv" class="${s.type === 'tv' ? 'on' : ''}">Series</button><button type="button" data-act="s-type:movie" class="${s.type === 'movie' ? 'on' : ''}">Movie</button></div>`;
  let h = '';
  if(w.tmdbOn && !w.manual){
    h += `<div class="media-search">${kindSeg}<div class="field"><label for="media-s-q">Title</label><input class="input" id="media-s-q" data-f="s-q" value="${esc(s.q)}"></div>
      <div class="field"><label for="media-s-year">Year</label><input class="input" id="media-s-year" data-f="s-year" value="${esc(s.year)}" placeholder="optional" inputmode="numeric"></div><button type="button" class="primary" data-act="s-go">Search</button></div>`;
    if(s.error) h += note('err', '!', esc(s.error));
    if(s.results) h += s.results.length ? `<div class="media-hits">${s.results.map((x, i) => hit(x, i, w.chosen && w.chosen.tmdb === x.tmdb && w.chosen.kind === x.kind, 's-pick:' + i)).join('')}</div>` : '<div class="empty">No results. Try another title or enter it by hand.</div>';
    h += `<div class="media-or">or with an IMDb ID</div><div class="media-row"><div class="field"><label for="media-s-imdb">IMDb ID</label><input class="input" id="media-s-imdb" data-f="s-imdb" value="${esc(s.imdb)}" placeholder="tt1520211"></div><button type="button" class="secondary" data-act="s-find">Look up</button></div>`;
    h += `<div><button type="button" class="media-link" data-act="manual:1">Not there? Enter title and year by hand</button></div>`;
  }else{
    if(!w.tmdbOn) h += note('', '!', '<b>No TMDB key set.</b> That is why there are no suggestions, posters or episode names. Enter title and year yourself. You can add the key later under Settings → Media / Jellyfin.');
    h += `<div class="media-seg"><button type="button" data-act="kind:series" class="${w.kind === 'series' ? 'on' : ''}">Series</button><button type="button" data-act="kind:movie" class="${w.kind !== 'series' ? 'on' : ''}">Movie</button></div>
      <div class="media-grid"><div class="field"><label for="media-m-title">Title</label><input class="input" id="media-m-title" data-f="m-title" value="${esc(w.title)}"></div>
      <div class="field"><label for="media-m-year">Year${series ? ' (first aired)' : ''}</label><input class="input" id="media-m-year" data-f="m-year" value="${w.year || ''}" inputmode="numeric"></div></div>
      <div class="media-grid"><div class="field"><label for="media-m-imdb">IMDb ID <span class="muted">(optional, for the name tag)</span></label><input class="input" id="media-m-imdb" data-f="m-imdb" value="${esc(w.imdb || '')}" placeholder="tt1520211"></div>
      <div class="field"><label for="media-m-tmdb">TMDB ID <span class="muted">(optional)</span></label><input class="input" id="media-m-tmdb" data-f="m-tmdb" value="${w.tmdb || ''}" placeholder="1402" inputmode="numeric"></div></div>
      <div class="media-ex"><span>Will be named:</span> ${exampleName(w)}</div>`;
    if(w.tmdbOn) h += `<div><button type="button" class="media-link" data-act="manual:0">Back to the search</button></div>`;
  }
  return {body: h, footer: `<button type="button" class="secondary" data-act="back">Back</button><span class="sp"></span><button type="button" class="primary" data-act="next">Next</button>`};
}

function exampleName(w){
  const t = esc(w.title || 'Title'), y = w.year ? ` (${w.year})` : '';
  return w.kind === 'series' ? `<em>${t}${y}</em>/Season 01/<em>${t} S01E01.mkv</em>` : `<em>${t}${y}</em>/<em>${t}${y}.mkv</em>`;
}

export function stepEpisodes(w){
  const eps = w.items.map((it, i) => ({it, i})).filter(x => x.it.role === 'episode');
  const others = w.items.map((it, i) => ({it, i})).filter(x => x.it.role === 'playall' || x.it.role === 'extra');
  const epStr = it => it.episodes.length > 1 ? `${it.episodes[0]}-${it.episodes[it.episodes.length - 1]}` : String(it.episodes[0]);
  const cmp = it => it.runtime ? `<span class="${Math.abs(it.delta) <= 6 ? 'dur-ok' : 'dur-off'}">${Math.abs(it.delta) <= 6 ? '✓' : '≈'} ${Math.round(it.runtime)} min${Math.abs(it.delta) > 6 ? ` (Δ ${Math.round(Math.abs(it.delta))} min)` : ''}</span>` : '<span class="muted">not checked</span>';
  const inp = (i, f, v) => `<input class="input num-in" data-f="${f}" data-i="${i}" value="${esc(v)}" inputmode="numeric" aria-label="${f === 'season' ? 'Season' : 'Episode'}">`;
  const paSeg = i => `<div class="media-seg ${''}"><button type="button" data-act="pa:${i}:skip" class="${w.items[i].keep === 'extra' ? '' : 'on'}">Leave out</button><button type="button" data-act="pa:${i}:extra" class="${w.items[i].keep === 'extra' ? 'on' : ''}">As extra</button></div>`;
  const rows = eps.map(({it, i}) => `<tr><td>${esc(shortName(it.path))}</td><td>${fmtDur(it.dur)}</td><td>${inp(i, 'season', it.season)}</td><td>${inp(i, 'ep', epStr(it))}</td><td><span class="nm">${esc(it.name || '—')}</span></td><td>${cmp(it)}</td></tr>`).join('')
    + others.map(({it, i}) => `<tr class="playall"><td>${esc(shortName(it.path))}</td><td>${fmtDur(it.dur)}</td><td colspan="3"><span class="nm">${it.role === 'playall' ? 'Sum of several titles' : 'short title'}</span><small>${it.role === 'playall' ? 'Play-all: not sorted as an episode' : 'Extra, not sorted as an episode'}</small></td><td>${paSeg(i)}</td></tr>`).join('');
  const cards = eps.map(({it, i}) => `<div class="media-ecard"><div class="top"><b>${esc(shortName(it.path))}</b><span class="muted">${fmtDur(it.dur)} ${it.runtime ? (Math.abs(it.delta) <= 6 ? '<span class="dur-ok">✓</span>' : '<span class="dur-off">≈</span>') : ''}</span></div>
    <div class="ins">S${inp(i, 'season', it.season)} E${inp(i, 'ep', epStr(it))}<span style="color:var(--text)">${esc(it.name || '')}</span></div></div>`).join('')
    + others.map(({it, i}) => `<div class="media-ecard playall"><div class="top"><b>${esc(shortName(it.path))} · ${it.role === 'playall' ? 'Play-all' : 'Extra'}</b><span class="muted">${fmtDur(it.dur)}</span></div><div class="muted" style="font-size:12px">${it.role === 'playall' ? 'Sum of several titles, not sorted as an episode.' : 'Short title, not sorted as an episode.'}</div>${paSeg(i).replace('media-seg ', 'media-seg full ')}</div>`).join('');
  const start = w.start.known ? 'Suggestion: <b style="color:var(--text)">continue from episode ' + w.start.episode + '</b> (progress of this series remembered).' : w.start.estimated ? `Estimate from the disc number: from episode ${w.start.episode}. Please check.` : 'Suggestion: consecutive from episode 1.';
  return {body: `<div class="media-follow"><span>${start}</span><span class="sp"></span>
      <div class="field" style="display:flex;gap:6px;align-items:center"><label style="margin:0" for="media-st-season">Season for all</label><input class="input" id="media-st-season" data-f="all-season" style="width:60px;height:30px;text-align:center" value="${w.season}" inputmode="numeric"></div>
      <div class="field" style="display:flex;gap:6px;align-items:center"><label style="margin:0" for="media-st-start">Start at episode</label><input class="input" id="media-st-start" data-f="start" style="width:60px;height:30px;text-align:center" value="${w.start.episode}" inputmode="numeric"></div></div>
    <div class="media-eps-table table-wrap" style="border:1px solid var(--line);border-radius:10px"><table class="media-eps"><thead><tr><th>File</th><th>Runtime</th><th>Season</th><th>Episode</th><th>Name${w.tmdbOn ? '' : ' (empty without a key)'}</th><th>Match</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="media-cards">${cards}</div>
    ${w.tmdbOn ? (w.epError ? note('', '!', esc(w.epError)) : '') : note('info', 'i', 'Without a TMDB key there are no episode names and expected runtimes. Season and episode come from the disc number and the order and can be changed.')}`,
    footer: `<button type="button" class="secondary" data-act="back">Back</button><span class="sp"></span><button type="button" class="primary" data-act="next">On to the preview</button>`};
}

export function stepPreview(w){
  const p = w.plan;
  if(w.planError) return {body: note('err', '!', esc(w.planError)), footer: `<button type="button" class="secondary" data-act="back">Back</button><span class="sp"></span>`};
  const sm = p.summary, rows = p.rows;
  const verb = p.action === 'kopieren' ? 'to be copied' : 'to be moved';
  const pills = `<span class="st ok">${sm.move} ${verb}</span>${sm.conflict ? `<span class="st busy">${sm.conflict} conflict${sm.conflict > 1 ? 's' : ''}</span>` : ''}${sm.locked ? `<span class="st warn">${sm.locked} locked</span>` : ''}${sm.skip ? `<span class="st">${sm.skip} left out</span>` : ''}${sm.missing + sm.error ? `<span class="st busy">${sm.missing + sm.error} error${sm.missing + sm.error > 1 ? 's' : ''}</span>` : ''}`;
  const dirExists = Object.fromEntries(p.dirs.map(d => [d.rel, d.exists])), shown = new Set();
  const old = r => { const parts = r.src.split('/'); return parts.length > 1 ? `${parts[parts.length - 2]}/…${shortName(r.src)}.mkv` : parts[0]; };
  let tree = `<div class="media-tr head"><span>New (target tree)</span><span>Before</span></div><div class="media-tr"><span class="n"><span class="dir">${esc(p.root.split('/').pop())}/</span></span><span class="o">${esc(p.root)}</span></div>`;
  const files = rows.filter(r => r.dst && r.status !== 'skip').sort((a, b) => a.dst.localeCompare(b.dst, 'en'));
  for(const r of files){
    const parts = r.dst.split('/');
    for(let i = 1; i < parts.length; i++){ const d = parts.slice(0, i).join('/'); if(!shown.has(d)){ shown.add(d); tree += `<div class="media-tr"><span class="n d${i}"><span class="dir">${esc(parts[i - 1])}/</span></span><span class="o">${dirExists[d] ? 'folder already exists' : 'new folder'}</span></div>`; } }
    const cls = r.status === 'conflict' || w.decisions[r.src] === 'rename' ? 'bad' : r.status === 'locked' ? 'lock' : '';
    let why = '';
    if(r.status === 'conflict' || w.decisions[r.src] === 'rename') why = `<span class="why"><b>${esc(r.status === 'conflict' ? r.why : 'Already exists in the target')}</b> – never overwritten. <span class="media-seg"><button type="button" data-act="conf:${w.items.findIndex(x => x.path === r.src)}:skip" class="${w.decisions[r.src] === 'rename' ? '' : 'on'}">Skip</button><button type="button" data-act="conf:${w.items.findIndex(x => x.path === r.src)}:rename" class="${w.decisions[r.src] === 'rename' ? 'on' : ''}">Store as "… - 2"</button></span></span>`;
    else if(r.status === 'locked') why = `<span class="why">Locked: ${esc(r.why[0].toLowerCase() + r.why.slice(1))}. Stays where it is; sort it again later.</span>`;
    else if(r.why) why = `<span class="why muted">${esc(r.why)}</span>`;
    tree += `<div class="media-tr ${cls}"><span class="n d${parts.length - 1}">${esc(parts[parts.length - 1])}</span><span class="o f">${esc(old(r))}</span>${why}</div>`;
  }
  for(const r of rows.filter(r => r.status === 'skip' || r.status === 'missing' || r.status === 'error')) tree += `<div class="media-tr skip"><span class="n d1">–</span><span class="o f">${esc(old(r))}</span><span class="why">${esc(r.why || 'left out')}. Stays where it is.</span></div>`;
  const how = p.action === 'kopieren' ? 'The files are <b>copied</b>, the originals stay where they are.' : p.same_fs ? 'Source and target are on the same drive: <b>move = rename</b>, instant and without copying.' : 'Source and target are on different drives: the files are <b>copied, verified and only then removed from the old location</b> (can take a while).';
  return {body: `<div class="media-sum">${pills}</div><div class="media-tree" role="table" aria-label="Target tree">${tree}</div>${note('info', 'i', how + (p.new_dirs.length ? '' : ''))}`,
    footer: `<button type="button" class="secondary" data-act="back">Back</button><span class="sp"></span><button type="button" class="primary" data-act="run" ${p.ok ? '' : 'disabled'}>Run (${sm.move} file${sm.move === 1 ? '' : 's'})</button>`};
}

export function stepResult(w){
  const op = w.op, h = w.history;
  let top = '';
  if(op && op.status === 'running'){
    const pc = op.total ? Math.min(100, Math.round(op.copied / op.total * 100)) : 0;
    top = `<div class="media-done"><div><h4>Sorting files …</h4><p>${op.total ? `${fmtB(op.copied)} of ${fmtB(op.total)}` : 'one moment'}</p></div></div><div class="media-bar"><i style="width:${pc}%"></i></div>`;
  }else if(op){
    const done = op.rows.filter(r => r.status === 'done'), left = op.rows.filter(r => !['done', 'skip'].includes(r.status));
    top = `<div class="media-done"><div class="big">${done.length ? '✓' : '!'}</div><div><h4>${done.length} file${done.length === 1 ? '' : 's'} sorted</h4><p>${esc(w.plan && done[0] ? w.plan.root + '/' + done[0].dst.split('/').slice(0, -1).join('/') : '')} · ${fmtB(done.reduce((a, r) => a + (r.size || 0), 0))}${done.some(r => r.how === 'rename') ? ' · renamed' : ''}</p></div></div>`;
    if(op.error) top += note('err', '!', esc(op.error));
    if(op.jellyfin) top += note(op.jellyfin.ok ? 'ok' : '', op.jellyfin.ok ? '✓' : '!', esc(op.jellyfin.message));
    if(left.length) top += note('', '!', `<b>${left.length} file${left.length === 1 ? ' stays' : 's stay'} where ${left.length === 1 ? 'it is' : 'they are'}:</b> ${left.map(r => esc(shortName(r.src)) + ' (' + esc(r.why || r.status) + ')').join(', ')}. Sorting again later picks ${left.length === 1 ? 'it' : 'them'} up.`);
  }
  const log = h ? `<h4 style="margin:6px 0 0;font-size:13px">Recent actions</h4><div class="media-log">${h.items.length ? h.items.slice(0, 8).map(x => `<div class="it"><b>${esc(x.title || '–')}</b><small>${new Date(x.t * 1000).toLocaleString('en-GB', {dateStyle: 'short', timeStyle: 'short'})} · ${x.files} file${x.files === 1 ? '' : 's'} ${x.action === 'kopieren' ? 'copied' : 'moved'}${x.auto ? ' · automatic' : ''}${x.undone ? ' · undone' : ''}</small><span class="sp"></span>${x.can_undo ? `<button type="button" class="secondary danger" data-act="undo:${x.id}">Undo</button>` : `<span class="muted" style="font-size:11px">${x.undone ? '' : 'can no longer be undone'}</span>`}</div>`).join('') : '<div class="it muted">No actions yet.</div>'}</div>
    <p class="help" style="margin:0">Undo moves the files back to their old location and removes the new folders that became empty. With "Copy" only the copy is deleted.</p>` : '';
  const running = op && op.status === 'running';
  return {body: top + log, footer: `<button type="button" class="secondary" data-act="close" ${running ? 'disabled' : ''}>Sort more files</button><span class="sp"></span><button type="button" class="primary" data-act="close" ${running ? 'disabled' : ''}>Done</button>`};
}
