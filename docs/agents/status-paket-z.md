# Status PZ (merge, overall test, rollout) – as of 2026-10-10

Nothing is pushed, nothing is rolled out to maintux, vierstein or secondtux. Roll out only after explicit approval.

## Merged
Branch `paket-z` = `main` + `paket-a` … `paket-f` (PF last, state `2e3fe50`). The only conflict: `files.js` (PB against PD), resolved: play on the file name, no "Nachträglich konvertieren" button any more (the library replaces it).

## Own changes in PZ
- The title list (`titles.js`) embeds `mountConvertEditor(…, {mode:'compact'})` (PA should have done it), `cvform.js` removed. The rip gets the v2 settings.
- Hand-over to other machines (`cluster.cfg_for_peer`): checks `convert_caps.peer_ok`; old machines only get the five old fields (`to_v1`), and only if the job can be expressed that way, otherwise the reason goes into the error list. Applies to `/api/handover`, the hand-over after uploading and `/api/convert/start`.
- **Bug fixed:** `/api/convert/start` to another machine returned 500 (async `peer_call` called via `asyncio.to_thread`, a coroutine came back). Regression test in `tests/test_handover_caps.py`.
- `core.js`: 422 responses (list of error objects) are displayed readably instead of "[object Object]".
- `main.py`: `peer_prober` always starts (even without `PEERS`, because the machine list can be filled later).
- `scripts/dev.sh`: looks for a Python 3.10 or newer.
- Media folders (PE): preset `OUTPUT_MOUNT/Filme` and `/Serien` instead of a fixed `/mnt/datenstein/…` (inside the container the NAS is named like `NAS_MOUNT` in `.env`).
- Dockerfile: `intel-media-va-driver` and `vainfo` (hardware encoding, i5-7300U only 8-bit HEVC). Compose: `group_add` extended by `RENDER_GID`, device rule `c 226:*` (`/dev/dri`); `.env.example` and `install.sh` know `RENDER_GID`. Existing `.env` files without `RENDER_GID` keep working (default 105).
- Phone (375 px): settings overflowed at "Konvertierung & Presets" (grid columns `1fr` → `minmax(0,1fr)`, `shell.css`); the library's selection bar was too wide and covered the tab bar (`library.css`); the editor scrolls into view when opened (`library.js`).
- Tests: `tests/__init__.py` sets the shared environment (before, 15 tests failed only in the shared run).
- Docs: `schnittstellen.md` (§7 package modules, §8 limitations), README.

## Checked (locally, `scripts/dev.sh`, browser)
- Three instances: two new ones in a cluster (8900/8901) and one on the old version `ae4603e` (8902, as "secondtux"). The old one appears as reachable/`legacy`; in the library it is greyed out for customized jobs with a reason and selectable with "Blu-ray optimal".
- Conversion from 8900 to the old instance (five fields, done, HEVC 10-bit) and to the new one (x264, done, H.264); x264 to the old one is rejected with 409 and a reason.
- All views and all settings sections at desktop and 375 px without horizontal overflow; player (remux, plays); filing up to the plan (not executed); title list with editor on the phone.
- `python3 -m unittest discover -s tests -t .`: green (9 skipped, without a real media source). `pyflakes` clean (apart from one old unused variable in `upload.py`). No file over 400 lines.

## Not checked / open
- Full Docker build with the MakeMKV stage (requires `ACCEPT_EULA=yes`, only with approval).
- Hardware encoding (VAAPI), HDR→SDR, real Dolby Vision file, test encode with a real Blu-ray file, Safari/Firefox.
- Test encode in the browser only at backend level.

## Rollout (after approval)
1. Merge `paket-z` into `main` (locally), then push on request.
2. **maintux** (Git clone, no sudo without a password): check the state (`/api/state` without running jobs), back up `data/` and `.env`, `git pull`, `docker compose up -d --build` (EULA via `.env`/`install.sh` as before).
3. **vierstein** (no Git repo, sudo without a password): clarify the approach (clone next to `~/makemkv-web` or rsync), same backup, build and restart.
4. **secondtux** stays untouched and appears in the cluster as the old version.
5. Way back: previous image/commit back (`git checkout <old commit>`, `docker compose up -d --build`), `data/` and `.env` from the backup.
