// Meldet „files-changed“, wenn ein Rip endet oder eine Übertragung fertig wird; die Bibliothek u. a. laden dann neu.
// (Die frühere Kachel „Fertige Dateien“ in Laufwerke ist entfallen – alle Dateien zeigt die Bibliothek.)
import { emit, onState } from './registry.js';

const wasBusy = {};
let upDone = -1;
onState(S => {
  let changed = false;
  for(const x of S.drives){ const was = wasBusy[x.id]; wasBusy[x.id] = !!x.job; if(was && !x.job) changed = true; }
  const done = (S.uploads||[]).filter(u => u.status==='done').length;
  if(done !== upDone){ upDone = done; changed = true; }
  if(changed) emit('files-changed');
});
