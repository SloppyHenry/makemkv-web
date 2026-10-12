# Status PB (navigation + settings page) – as of 2026-10-10

Mockup done: docs/mockups/paket-b.html (approved by the user: variant A, chips in their own bar without a selection menu, badge on the Laufwerke tab, one section per view)

## Done
- Mockup (overview with tabs; every scene also individually via `?s=<scene>` in full window size). Variants: A tabs on top (recommended), B sidebar, drive chips (wrapping / optional selection menu), settings page (desktop + phone), phone with tab bar and "Mehr", behavior/keyboard.

## Implemented (1:1 after mockup A, checked in the browser at 1440 and 375 px)
- `index.html`, `js/nav.js`, `js/settings.js`, `js/settings-general.js` (new: sections Allgemein, MakeMKV-Key, transitional section Konvertierung), `css/shell.css`. Burger menu and gear dialog are gone.
- Tabs from `getViews()` (also ones registered later), badge = running jobs (own machine + reachable peers), "Mehr" sheet on the phone from 6 views, `role=tablist/tab/tabpanel`, ←/→/Home/End/Space, "skip to content", drive bar `#drivebar` only in "Laufwerke".
- Settings: `#/einstellungen/<section>`, save/discard per section (POST only with the section's `collect()`, then re-render with the response), yellow dot in the list and on the "Einstellungen" tab for unsaved changes, `beforeunload` warning.
- Events: `route` (every hash change, argument = rest after the view), `settings:dirty` (bool). `settings:open` navigates on to the page.
- Development note: with the system Python 3.9, `scripts/dev.sh` needs a newer Python (`PYTHON=/opt/homebrew/bin/python3.14`), otherwise `ext.py` fails on `Callable | None`.

## Interfaces offered
- Expected section IDs for `registerSettingsSection`: `general`, `key` (PB), `nodes` (PC), `media` (PE), `convert` (PF). Order via `order` (PB: 10 and 20).
- Optional fields on sections: `icon`, `description`. PB detects changes from `input`/`change` events in the section and by comparing `collect()`. If you have other ways, trigger `el.dispatchEvent(new Event('change', {bubbles: true}))`.
- Optional on `registerView`: `badge(S)` (number or 0) for a badge on the tab.
- Until PF registers the `convert` section, PB shows "Gleichzeitige Dateien" and "Segmente pro Film" as section `convert-basic` ("Konvertierung"); it disappears as soon as `convert` exists (PF takes over the fields).

## Needs from others
- PA (`drives.js`): nothing mandatory. `#drivechips` and the chip look stay; the element only moves into `#drivebar`. Optional (only if the user wants the selection menu for many drives): a function that renders chips into a container, with a compact look. Status: open/optional.
- PA: the log card is PA's decision; PB needs no view of its own for it. Status: note.
- P0/PZ (`registry.js`): sub-sections in the hash (`#/einstellungen/medien`): `fromHash` should take only the first segment (`split(/[/?]/)[0]`) for the view and provide the rest via a function (e.g. `routeRest()`). Without that only `#/einstellungen` works. Status: done (see below).
- PF: remove `library.js` "← Laufwerke" (`#lib-back`) (PB only removes the call in `files.js`). Register the section as `convert` and take over `conv_parallel`/`conv_segments`. Status: open.
- PC/PE: use the section IDs `nodes` and `media`. Status: open.

## Foreign files touched
- `app/static/js/files.js`: button `#to-lib` and handler removed (agreed).
- `app/static/js/registry.js`: `routeRest()` new, `fromHash` takes only the first hash segment, event `route` on `hashchange` (allowed by the coordinator; PZ takes it over when merging).

## Questions for the user
1. Which navigation: A (tabs on top) or B (sidebar)?
2. Chips below the tabs in their own bar (only in "Laufwerke"): fine? Selection menu wanted for very many drives?
3. Badge of running jobs on the "Laufwerke" tab: fine, or rather separate (e.g. conversions on the "Bibliothek" tab)?
4. Settings: one section at a time with save per section (as in the mockup) or everything on one long page?

## Coordinator's decision (2026-10-10)
- `registry.js` (`fromHash`/sub-routes `#/einstellungen/<section>`): PB may make this **one** change itself in `app/static/js/registry.js` (first hash segment = view, rest via a small exported function, e.g. `routeRest()`), keep it small and note it in this document under "Foreign files touched". PZ takes it over when merging.
- PF/PC/PE are informed: section IDs `convert`, `nodes`, `media`; save per section via `collect()`; PF removes `#lib-back`.
- You may remove `files.js` (button `#to-lib`) during implementation as agreed before.
