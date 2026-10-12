# Status PA (UI polish) – as of 2026-10-10

## Done
- **Spinning circle (item 1):** `jobs.js` no longer rebuilds the list via `setHtml()`. New module `js/jobs-list.js` (`reconcileJobs`): one stable DOM element per job (key `c|machine|id`, `u|machine|id`, `d|machine|drive`); only text, bar width, classes and (only on change) the buttons are updated. In addition the rotation phase is tied to the clock (`syncSpin`, `animation-delay: -(Date.now() % 1000)ms`) in case an element is inserted or moved. The progress field (`#prog` in `drives.js`) is also built only once; the indeterminate bar (`@keyframes ind`) now runs via `transform` instead of `margin-left` and does not restart on new messages. There are no other spinners (library and drive chips have no animation; the progress field has no circle).
- **Status icon** always perfectly round: 24 px (even), `aspect-ratio:1/1`, `flex:none`, `box-sizing:border-box`; `prefers-reduced-motion` slows the rotation.
- **Responsive job row (item 2):** container query on the list (`.joblist`, `container: jobs/inline-size`), not on the window. Wide (from 520 px list width): one row with text buttons on the right; medium (360–519 px): buttons below the text; narrow (up to 359 px): icon buttons (⏭ ✕) to the right of the text. Status pill and machine name sit right next to the title (wrapping below if space is short); the text never gets less than about 190 px, long names are shortened (narrow: up to two lines). Checked at 1440, 1280, 1050, 900, 700, 375 px, with machine name and long file names.
- **Log only once (item 3):** `#compactLog` is removed. What remains is the lower card `#fullLog` (slot `bottom`), collapsible, **collapsed by default** (user's decision); the user's choice is remembered in `localStorage` (`logOpen`, with try/catch) and wins. A **new** error opens it (without overwriting the remembered choice); if it is closed on load and contains errors, a red badge "N Fehler" shows in the header. Keyboard operable (`summary`), focus visible.
- **Title list (item 4):** the "Längster"/"Kurz" badge now sits below the file name (`css/titles.css`), the name is no longer cut off. In addition: on phones (up to 700 px) every title row becomes a card (name on top, duration · size · tracks below), no more horizontal scrolling.
- `hidden` now also works on buttons/flex elements in list, toolbar and progress field (`.secondary{display:inline-block}` used to override it).

## Verified (locally, browser, two instances 8800/8801, console free of errors)
- Jerky circle: during a real running conversion (status message about every second, over 14 measurements with 9 different texts) the same circle element stays in the DOM, `getAnimations()[0].currentTime` rises continuously without resets. Same with a script that re-reports all job types (ripping, converting local/foreign, transferring, waiting, paused, error, cancelled, handed over, finished) every second; likewise for the indeterminate analysis bar. Reordering the list only moves the element that actually moves (test of `reconcileJobs`).
- Widths 1440 / 1280 / 1050 / 900 / 700 / 375 px: no horizontal page shift, row text at least 191 px, list widths 463 / 409 / 493 / 418 / 674 / 349 px.
- Buttons (skip/cancel/details) trigger the old handlers; log: open/closed remembered, errors open it or show the badge; title list on desktop and at 375 px.
- Not checked: Safari/Firefox (container queries need Safari 16+/Firefox 110+).

## In progress
- Integrating PF's `mountConvertEditor` into the title list ("Nach dem Rippen konvertieren"): waiting for the offer in PF's status file (`status-paket-f.md` does not exist yet). Until then the old form (`cvform.js`) stays.

## Interfaces offered
- `jobsPanelHtml(id, withDest)` and `data-joblist` in `js/jobs.js` stay **unchanged** (PF can rebuild the library and embed the job list as before). New: the list element carries the class `joblist` (please keep it, it contains the container query); rows are `<div class="job" data-key="…">` (please do not modify them from outside).
- `js/jobs-list.js`: `reconcileJobs(listEl, [{key, model}], emptyText)`, `syncSpin(el, ms)`, `jobBtn(...)` (for your own stable lists with a spinning circle: call `syncSpin` after inserting).
- Log: card `#fullLog` (details element), body `#logFull`; `registerPanel({view:'laufwerke', slot:'bottom', id:'fullLog'})`. If you want to move the log to another view (PB reported no need): change the slot in `logs.js`.
- CSS files of PA: `css/jobs.css`, `css/titles.css` (included automatically). New JS file: `js/jobs-list.js` (loaded automatically; no side effects).

## Needs from others
- PF: `mountConvertEditor(el, value, {target, onChange})` for the title list (see AUFTRAG PF part 1, item 4). Status: open. Wish: value in the format of `convOf(d)`/`cv` (today's `cvform.js` object `{convert, rf, preset, tune, extra, audio}` or the v2 schema), so that `startRip()` in `titles.js` can send it unchanged to `POST /api/drives/{id}/rip` (`convert`).
- PB: nothing. `#drivechips` and its look stay (`drives.js`); the element may move into `#drivebar`.

## Foreign files touched
None.

## Questions for the user
- Answered: log collapsed by default (remembered choice wins; a new error opens it or shows the badge). Implemented and checked in the browser (fresh localStorage: closed; error opens it without saving; opening saves and survives reload; badge on load with existing errors).
