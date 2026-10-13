// Media / Jellyfin (PE): registers the settings section (media-settings.js) and the library action "Sort into movies/series …".
import { registerLibraryAction } from './registry.js';
import './media-settings.js';
import { openWizard } from './media-wizard.js';

// run(files) takes one or more files (selection) or all files of a folder; the server resolves folder paths itself.
registerLibraryAction({
  id: 'organize', label: 'Sort into movies/series …', icon: '⇢',
  when: files => files.length >= 1 && files.every(f => !f.job && !f.locked && /\.(mkv|m2ts|iso)$/i.test(f.path)),
  run: files => openWizard(files.map(f => f.path)),
});
export { openWizard };
