// Settings page ("settings" view): the list of sections on the left, the selected section with its own save button on the right.
// Sections register via registerSettingsSection (general/key/conversion: settings-general.js, machines/media/…: other packages).
// The page detects unsaved changes by comparing collect() with the state at render time (input/change inside the section).
import { $, S, api, esc, toast } from './core.js';
import { emit, getSettingsSections, on, onState, registerView, routeRest } from './registry.js';

const panes = {};            // section id → {s, tab, el, body, base, sig, rendered, dirty}
let root = null, active = null;
const lsGet = () => { try{ return localStorage.getItem('setSection'); }catch{ return null; } };
const lsSet = v => { try{ localStorage.setItem('setSection', v); }catch{} };
// "convert-basic" (old fields) is only a stand-in as long as no "convert" section (PF) is registered
const visible = () => { const all = getSettingsSections(); return all.filter(s => !(s.id === 'convert-basic' && all.some(x => x.id === 'convert'))); };
const anyDirty = () => Object.values(panes).some(p => p.dirty);

function isDirty(p){
  if(p.base == null) return false;
  try{ return JSON.stringify(p.s.collect()) !== p.base; }catch{ return false; }
}
function update(p){
  const was = anyDirty(), d = isDirty(p);
  p.dirty = d;
  $('.set-dot', p.tab).hidden = !d;
  const st = $('.set-state', p.el); st.textContent = d ? '● Unsaved changes' : 'Saved'; st.classList.toggle('dirty', d);
  $('[data-act=save]', p.el).disabled = !d; $('[data-act=discard]', p.el).disabled = !d;
  if(was !== anyDirty()) emit('settings:dirty', anyDirty());
}
function rebase(p){ try{ p.base = JSON.stringify(p.s.collect()); }catch{ p.base = null; } update(p); }

async function renderPane(p, settings){
  p.sig = JSON.stringify(settings);
  try{ await p.s.render(p.body, settings); }
  catch(e){ console.error(`Settings ${p.s.id}:`, e); p.body.textContent = 'This section could not be loaded.'; }
  await Promise.resolve();
  rebase(p);
}
async function save(p){
  const btn = $('[data-act=save]', p.el); btn.disabled = true;
  try{
    const res = await api('/api/settings', 'POST', p.s.collect());
    toast(`${p.s.label}: saved ✓`);
    await renderPane(p, res);
  }catch{ /* api() shows the error */ }
  update(p);
}

function buildPane(s){
  const tab = document.createElement('a');
  tab.className = 'set-tab'; tab.id = 'settab-' + s.id; tab.href = '#/settings/' + s.id; tab.dataset.sec = s.id;
  tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', 'set-' + s.id);
  tab.innerHTML = `<span class="nav-ico" aria-hidden="true">${esc(s.icon || '•')}</span>${esc(s.label)}<span class="set-dot" hidden title="Unsaved changes"></span>`;
  const el = document.createElement('section');
  el.className = 'panel set-card'; el.id = 'set-' + s.id; el.hidden = true; el.setAttribute('role', 'tabpanel'); el.setAttribute('aria-labelledby', tab.id);
  el.innerHTML = `<div class="panel-head"><div><h2>${esc(s.label)}</h2>${s.description ? `<div class="sub">${esc(s.description)}</div>` : ''}</div></div>
    <div class="set-body"></div>
    <div class="set-foot"${s.readonly ? ' style="display:none"' : ''}><span class="set-state" role="status">Saved</span><span class="spacer"></span>
      <button type="button" class="secondary" data-act="discard" disabled>Discard</button><button type="button" class="primary" data-act="save" disabled>Save</button></div>`;
  const p = panes[s.id] = {s, tab, el, body: $('.set-body', el), base: null, sig: '', rendered: false, dirty: false};
  const check = () => update(p);
  el.addEventListener('input', check); el.addEventListener('change', check);
  const lock = () => { if(!p.dirty && p.rendered) rebase(p); };      // record the state before the first interaction (in case a section finishes rendering later)
  for(const ev of ['focusin', 'pointerdown', 'keydown']) el.addEventListener(ev, lock, true);
  el.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if(!b) return;
    if(b.dataset.act === 'save') save(p); else if(S) renderPane(p, S.settings);
  });
  return p;
}

// Build the section list and panes, or add newly registered sections
function sync(){
  const list = visible(), nav = $('#setnav'), host = $('#setpanes');
  for(const s of list) if(!panes[s.id]){ const p = buildPane(s); nav.append(p.tab); host.append(p.el); }
  for(const [id, p] of Object.entries(panes)) if(!list.some(s => s.id === id)){ p.tab.hidden = true; p.el.hidden = true; }
  list.forEach(s => { nav.append(panes[s.id].tab); host.append(panes[s.id].el); });          // order by `order`
  const ids = list.map(s => s.id);
  if(!ids.includes(active)) select(null);
}
function select(id){
  const ids = visible().map(s => s.id);
  id = ids.includes(id) ? id : ids.includes(lsGet()) ? lsGet() : ids[0];
  active = id;
  for(const i of ids){ const p = panes[i], on_ = i === id; p.el.hidden = !on_; p.tab.setAttribute('aria-selected', on_); p.tab.tabIndex = on_ ? 0 : -1; }
}
function ensure(){          // render sections as soon as the state is there (and again when the settings changed and nothing is unsaved)
  if(!S || !root) return;
  for(const p of Object.values(panes)) if(!p.rendered){ p.rendered = true; renderPane(p, S.settings); }
}

registerView({
  id: 'settings', label: 'Settings', icon: '⚙', order: 900,
  mount(el){
    if(!el.dataset.built){
      el.dataset.built = '1'; root = el;
      el.innerHTML = `<div class="page"><div class="page-head"><h1>Settings</h1><p>Each section is saved separately.</p></div>
        <div class="set-layout"><div class="panel set-nav" id="setnav" role="tablist" aria-orientation="vertical" aria-label="Settings sections"></div><div id="setpanes"></div></div></div>`;
      $('#setnav').addEventListener('keydown', e => {
        const tabs = [...document.querySelectorAll('#setnav .set-tab')].filter(t => !t.hidden), i = tabs.indexOf(document.activeElement);
        if(i < 0) return;
        const to = {ArrowDown: tabs[(i + 1) % tabs.length], ArrowRight: tabs[(i + 1) % tabs.length], ArrowUp: tabs[(i - 1 + tabs.length) % tabs.length],
          ArrowLeft: tabs[(i - 1 + tabs.length) % tabs.length], Home: tabs[0], End: tabs[tabs.length - 1]}[e.key];
        if(to){ e.preventDefault(); tabs.forEach(t => { t.tabIndex = t === to ? 0 : -1; }); to.focus(); }
        else if(e.key === ' '){ e.preventDefault(); tabs[i].click(); }
      });
    }
    sync(); select(routeRest().split('/')[0]); ensure();
    // When opened again: redraw unchanged sections with the current state
    if(S) for(const p of Object.values(panes)) if(p.rendered && !p.dirty && p.sig !== JSON.stringify(S.settings)) renderPane(p, S.settings);
  },
});
on('route', rest => { const id = rest.split('/')[0]; if(root && !root.hidden){ select(id); if(panes[id]) lsSet(id); } });
on('settings:open', () => { location.hash = '#/settings'; });
onState(ensure);
addEventListener('beforeunload', e => { if(anyDirty()){ e.preventDefault(); e.returnValue = ''; } });
