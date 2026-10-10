// Einstiegspunkt: lädt alle Module (Liste vom Server, siehe app/ui.py), startet Routing und Verbindung.
import { connect } from './core.js';
import { startRouter } from './registry.js';

for(const m of window.UI_MODULES || []){
  try{ await import(m); }catch(e){ console.error('Modul konnte nicht geladen werden:', m, e); }
}
startRouter();
connect();
