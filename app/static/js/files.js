// Emits "files-changed" when a rip ends or a transfer finishes; the library and others reload then.
// (The former "Finished files" tile under Drives is gone – the library shows all files.)
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
