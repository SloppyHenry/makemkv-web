// Erweiterungspunkte der Oberfläche (ohne Abhängigkeiten, von allen Modulen nutzbar).
// Beschreibung und Beispiele: docs/agenten/schnittstellen.md
const views = [], panels = [], sections = [], actions = [], stateFns = [], handlers = {};
let current = null, lastState = null;

// ---- Ereignisse zwischen Modulen: on('files-changed', fn) / emit('files-changed', daten)
export function on(evt, fn){ (handlers[evt] ||= []).push(fn); }
export function emit(evt, data){ (handlers[evt] || []).slice().forEach(fn => { try{ fn(data); }catch(e){ console.error(`Ereignis ${evt}:`, e); } }); }

// ---- Statusänderungen (jede Meldung des Servers): onState(S => …)
export function onState(fn){ stateFns.push(fn); }
export function notifyState(S){
  lastState = S;
  stateFns.forEach(fn => { try{ fn(S); }catch(e){ console.error('onState:', e); } });
}
export const rerender = () => { if(lastState) notifyState(lastState); };

// ---- Ansichten: registerView({id, label, icon, order, hash?, mount(el), unmount()})
export function registerView(v){
  views.push({order: 100, hash: v.id, icon: '', ...v});
  views.sort((a, b) => a.order - b.order);
}
export const getViews = () => views.slice();
export const isActive = id => current === id;
export const currentView = () => current;
// Rest der Adresse nach der Ansicht: #/einstellungen/media → 'media' (für Unterabschnitte; Ereignis 'route' bei jeder Hash-Änderung)
export const routeRest = () => location.hash.replace(/^#\//, '').split('/').slice(1).join('/').split('?')[0];
export const navigate = id => { const v = views.find(x => x.id === id); if(v && location.hash !== '#/' + v.hash) location.hash = '#/' + v.hash; else if(v) show(v.id); };

function container(id){
  let el = document.getElementById('view-' + id);
  if(!el){ el = document.createElement('section'); el.id = 'view-' + id; el.className = 'view'; el.hidden = true; document.getElementById('views').append(el); }
  return el;
}
function show(id){
  const v = views.find(x => x.id === id) || views[0];
  if(!v || current === v.id) return;
  if(current){ const old = views.find(x => x.id === current); try{ old.unmount && old.unmount(); }catch(e){ console.error(e); } container(current).hidden = true; }
  current = v.id;
  const el = container(v.id); el.hidden = false;
  try{ v.mount && v.mount(el); }catch(e){ console.error(`Ansicht ${v.id}:`, e); }
  emit('view', v.id);
  rerender();
}
export function startRouter(){
  const fromHash = () => { const h = location.hash.replace(/^#\//, '').split(/[/?]/)[0]; return (views.find(v => v.hash === h) || views[0] || {}).id; };
  window.addEventListener('hashchange', () => { show(fromHash()); emit('route', routeRest()); });
  show(fromHash());
}

// ---- Felder einer Ansicht: registerPanel({view, slot:'left'|'right'|'bottom', order, id, html})
// Ansichten mit Zwei-Spalten-Aufbau rufen buildLayout(el, viewId) auf; das HTML jedes Feldes ist ein komplettes <section class="panel">.
export function registerPanel(p){ panels.push({order: 100, ...p}); }
export const panelsFor = (view, slot) => panels.filter(p => p.view === view && p.slot === slot).sort((a, b) => a.order - b.order);
export function buildLayout(el, viewId){
  if(el.dataset.built) return false;
  el.dataset.built = '1';
  const slot = s => panelsFor(viewId, s).map(p => p.html).join('');
  el.innerHTML = `<div class="layout"><section class="left">${slot('left')}</section><aside class="right">${slot('right')}</aside></div>${slot('bottom')}`;
  return true;
}

// ---- Einstellungsabschnitte: registerSettingsSection({id, label, order, render(el, settings), collect() -> {namespace: {...}}})
export function registerSettingsSection(s){ sections.push({order: 100, ...s}); sections.sort((a, b) => a.order - b.order); }
export const getSettingsSections = () => sections.slice();

// ---- Bibliotheks-Aktionen: registerLibraryAction({id, label, icon, primary?, when(files), run(files)})
export function registerLibraryAction(a){ actions.push({icon: '', primary: false, ...a}); }
export const getLibraryActions = () => actions.slice();
