// Entry point: loads all modules (list from the server, see app/ui.py), starts routing and the connection.
import { connect } from './core.js';
import { startRouter } from './registry.js';

for(const m of window.UI_MODULES || []){
  try{ await import(m); }catch(e){ console.error('Could not load module:', m, e); }
}
startRouter();
connect();
