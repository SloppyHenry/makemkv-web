// Medien / Jellyfin (PE): meldet Einstellungsabschnitt (media-settings.js) und die Bibliotheks-Aktion „In Filme/Serien einsortieren …“ an.
import { registerLibraryAction } from './registry.js';
import './media-settings.js';
import { openWizard } from './media-wizard.js';

// run(files) nimmt eine oder mehrere Dateien (Auswahl) bzw. alle Dateien eines Ordners; der Server löst Ordnerpfade selbst auf.
registerLibraryAction({
  id: 'organize', label: 'In Filme/Serien einsortieren …', icon: '⇢',
  when: files => files.length >= 1 && files.every(f => !f.job && !f.locked && /\.(mkv|m2ts|iso)$/i.test(f.path)),
  run: files => openWizard(files.map(f => f.path)),
});
export { openWizard };
