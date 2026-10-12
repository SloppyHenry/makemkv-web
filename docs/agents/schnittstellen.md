# Interfaces and structure (state after phase 2, all packages merged)

Applies to all packages. Complements `AUFTRAG.md`; in case of conflict, `AUFTRAG.md` section 4 (ground rules) wins.

## 0. Conventions
- **No file with more than 400 lines of code** (Python, JS, CSS, shell). If a module gets too big, split it sensibly (example: `convert.py` and `ffmpeg.py`). Run `wc -l` on the changed files before every commit.
- The user interface and code comments are in German; documentation is in English. No npm, no bundler, no framework: native ES modules, FastAPI.
- One module, one job. New functions go into new files of your own package; reach other packages' modules only through the extension points below.
- Backend: `python -m py_compile` or `pyflakes` clean. Frontend: no errors in the browser console.

## 1. Structure

### Backend (`app/`, Python package, start: `uvicorn app.main:app`)
| Module | Contents | Owner |
|---|---|---|
| `main.py` | creates the app, includes routers, loads optional modules, starts background tasks | P0/PZ |
| `ext.py` | **all extension points** (registration functions), imports nothing from `app` | P0/PZ |
| `config.py` | environment variables, paths, constants, `DEFAULTS`, `VERSION`/`FEATURES` | P0/PZ |
| `state.py` | runtime state (`settings`, `drives`, `uploads`, `conversions`, `peers_state` …), `broadcast()`, `snapshot()`, `/api/state`, `/api/events` | P0/PZ |
| `settings.py` | load/save, `GET/POST /api/settings` with namespaces | P0/PZ |
| `auth.py` | password protection (HTTP Basic) as middleware | P0 (PC adds token check) |
| `ui.py` | serves `index.html` and `/static`; registers CSS/JS files automatically | P0/PZ |
| `util.py` | pure helper functions (`safe_name`, `fmt_bytes`, `unique_path`, `valid_name` …) | P0 |
| `files.py` | output target (`out_dir`), path check `inside_out`, lock files, `busy_reason`, file API (`/api/files`, `/api/download`) | P0 |
| `makemkv.py` | `makemkvcon` call and robot parser, beta key | P0 |
| `drives.py` | drives (ioctl), analysis, eject, poller | P0 |
| `rip.py` | rip/backup into the staging buffer, rip hooks | P0 |
| `upload.py` | staging buffer and transfer to the target, upload hooks | P0 |
| `ffmpeg.py` | ffmpeg/ffprobe: arguments, progress, segments, pause | PF |
| `convert.py` | conversion: queue, worker, cancel/skip, `clean_convert` | PF |
| `library.py` | library: scan, cache, convert after the fact, rename | PF |
| `cluster.py` | query other machines, proxy `/api/peer/…`, hand-over | PC |

Dependencies run bottom-up (`ext`/`config`/`util` → `state` → `files`/`makemkv` → `drives`/`upload`/`ffmpeg` → `convert` → `rip`/`library`/`cluster`). Where two modules need each other (`upload` ↔ `convert` ↔ `cluster`), the younger one imports the other as a module (`from app import convert`) and calls `convert.x()` at run time, never `from app.convert import x` in a cycle.

### Frontend (`app/static/`, no build)
- `index.html` scaffold (header, `#banners`, `#views`, placeholder `<!--ASSETS-->`; PB).
- `css/*.css`: `base` (basics) · `layout` · `components` · `shell` (PB) · `jobs` (PA) · `library` (PF); **every further `*.css` is included by the server automatically** (alphabetically after those named).
- `js/*.js`: native ES modules. **Every `js/<name>.js` is loaded automatically** (order of the core modules: see `JS_ORDER` in `ui.py`, others alphabetically). A module registers itself on import; `main.py`/`app.js` do not have to be touched for that.
- Shared: `core.js` (`$`, `esc`, `api`, `toast`, `setHtml`, `S`, `ui`, `delegate`, connection) and `registry.js` (all extension points).
- Ownership: `drives.js`/`titles.js`/`jobs.js`/`logs.js` PA · `nav.js`/`settings.js` PB · `handover.js` PC · `files.js` (only the "files-changed" event is left, the "finished files" tile is gone)/`core.js`/`registry.js`/`app.js` P0/PZ · `library.js`/`cvform.js` PF (`cvform.js` is replaced by `convert-editor.js`).
- Everything is served with `Cache-Control: no-cache` (ETag): browsers fetch afresh after an update, nothing gets mixed.

## 2. Backend extension points (`from app import ext`)
Your module is **loaded automatically** if it has one of the names in `OPTIONAL_MODULES` (`main.py`): `app.nodes`, `app.player`, `app.media` (package with `__init__.py`), `app.convert_presets`, `app.headless` (package). You register everything on import. If the module is missing, it is skipped; an error inside it aborts startup.

| Call | Purpose |
|---|---|
| `ext.register_router(router)` | your own `APIRouter` (prefix per AUFTRAG 4.3, e.g. `/api/player`) |
| `ext.register_settings(ns, Model, defaults, secret=(), on_change=None)` | settings namespace (see 4) |
| `ext.register_snapshot(key, fn)` | `fn()` ends up in every status message under `key` (fast, JSON-serializable, no network) |
| `ext.register_capability(name, value)` | capability of this machine, visible in the cluster (`/api/state` → `capabilities`) |
| `ext.register_startup(async_fn)` | background task, starts after the settings are loaded |
| `ext.register_rip_hook(fn)` | after every title that has finished ripping (sync or async) |
| `ext.register_scan_hook(fn, force_auto_scan=None)` | after every disc analysis (also failed ones): `fn({drive, auto})`, `auto` = started by the poller on insertion; `force_auto_scan()` → True analyzes inserted discs even when `auto_scan` is switched off |
| `ext.register_upload_hook(fn)` | after every file transferred to the target (sync or async) |
| `ext.allow_proxy(regex)` | allows `POST /api/peer/{name}/<path>` for paths (without `/api/`) that match completely |

Errors in hooks and snapshot functions are logged and disturb nothing else.

Rip hook: `info = {dev, disc, title, rel, folder, file, mode, converting}` (`disc` = name/type/volume/all titles as in `/api/state`; `title` = the ripped title with `id`, `name`, `duration`, `bytes`, `chapters`, `tracks`; `rel` = target path in the output folder, as the transfer requests it; `file` = file in the staging buffer; `converting` = still has to go through conversion). Upload hook: `item["name"]` is the requested path (= `rel`), `item["dest"]` the real one (may differ because of `unique_path`).

Example (`app/player.py`):
```python
from fastapi import APIRouter
from app import ext
router = APIRouter(prefix="/api/player")

@router.get("/probe")
def probe(path: str): ...

ext.register_router(router)
ext.register_capability("player", {"modes": ["direct", "remux"]})
ext.allow_proxy(r"player/probe")
```

Useful existing helpers: `files.out_dir()`, `files.inside_out(rel)` (path escape → 400), `files.busy_reason(rel, is_dir, abs)`, `files.acquire_lock/release_lock`, `state.broadcast()`, `state.settings`.

## 3. Frontend extension points (`import … from './registry.js'`)
```js
registerView({id, label, icon, order, hash?, mount(el), unmount()})   // view; route #/<hash|id>; appears in the menu automatically
registerPanel({view, slot, order, id, html})                           // field in a two-column view ('laufwerke'): slot 'left' | 'right' | 'bottom'
registerSettingsSection({id, label, order, render(el, settings), collect()})   // collect() returns {namespace: {...}}
registerLibraryAction({id, label, icon, primary?, when(files), run(files)})    // file action in the library; primary = click on the file name
onState(fn)                                                            // fn(S) on every status message
on(evt, fn) / emit(evt, data)                                          // events: 'view' (new view), 'files-changed', 'conn' (connection), 'settings:open'
navigate(id)                                                           // switch to a view (sets the hash)
```
- `mount(el)` runs on **every** activation; the container persists (build the content only the first time, e.g. `if(el.dataset.built) return`). `unmount()` on leaving. After `mount`, all `onState` functions are called again with the latest state.
- `registerPanel`: `html` is a complete `<section class="panel" id="…">`. The field exists only once the view has been shown for the first time: render functions must check `if(!$('#myfield')) return;`. Attach events to such elements with `delegate('#myfield', 'click', (e, root) => …)` (from `core.js`).
- Access to the state: `import { S } from './core.js'` (live binding). State of the interface: `ui` (`core.js`). Third-party modules should reuse the `drives.js` functions (`curDrive`, `allDrives`, `driveUrl`) instead of looking up drives themselves.
- Library: `when(files)` receives the affected files (`{path, size, mtime, state, info, job, locked}`), `run(files)` executes. Today `library.js` renders row buttons and the primary action on the file name; selection actions (several files) are added by PF in `library.js`.
- Settings: until PB builds the page, `settings.js` renders all sections one below the other in the dialog; `collect()` is called on save.

Example (`js/player.js`):
```js
import { registerLibraryAction } from './registry.js';
registerLibraryAction({id:'play', label:'Abspielen', icon:'▶', primary:true,
  when: fs => fs.length === 1 && /\.(mkv|mp4)$/i.test(fs[0].path), run: fs => openPlayer(fs[0].path)});
```

## 4. Settings with namespaces
- `GET /api/settings` and `POST /api/settings`. Flat fields (`minlength`, `auto_eject`, …) belong to the namespace `general` and keep working; `{"general": {...}}` works as well. Extensions: `{"media": {"movies_dir": "…"}}`. In `config.json` they are nested.
- `ext.register_settings("media", MediaSettings, {"movies_dir": ""}, secret=("tmdb_key",))`. The value is then in `state.settings["media"]` (validated, filled up with defaults). On POST it is **merged** with the existing value and checked against the model (error → 422).
- `secret`: these fields do **not** appear in `/api/state` (which also goes to other machines!) and `GET /api/settings`, only `<field>_set: true`. On POST, `null`/missing means "unchanged", `""` means "delete".
- `on_change(old, new)` (sync or async) runs after a change.
- Unknown namespaces in `config.json` (module currently missing) are kept on save.

## 5. Cluster and backward compatibility
- `/api/state` reports `capabilities` (`version`, `features`, plus everything modules register). Older machines (e.g. secondtux) do not have the field: `peers[i].capabilities` is then `{}`; trust capabilities only with reservations and grey them out when in doubt.
- Existing endpoints, paths and response shapes stay (AUFTRAG 4.3). Only add fields.
- New endpoints that should be reachable in the cluster: `ext.allow_proxy(...)` in your own module.

## 6. Development and testing (`scripts/dev.sh`)
- `scripts/dev.sh` starts an instance on http://127.0.0.1:8790 (name `dev-a`), `scripts/dev.sh pair` two (8790/8791) in a cluster, `stop`/`status`, `--port`, `--name`, `--peers`, `--bg`, `--reset`. Data in `$TMPDIR/spindle-dev/` (`MKW_DEV_DIR` changes that); **never the real NAS**.
- The "NAS" (`output/`) is filled with sample files (film H.264+AC3 with subtitles and chapters, series disc "The Walking Dead – Disc 1" with five episodes and a Play-All title, HEVC 10-bit, MPEG-2 DVD, folder with umlauts).
- Fake drive `sr0` (file in `<name>/drives/`) with a stub `makemkvcon` (`scripts/dev-bin`): the disc is "analyzed", rip/backup run in seconds and produce tiny files. `scripts/dev.sh disc --name dev-a ready|empty|open` inserts/removes the disc/opens the tray. Your own disc: `<name>/drives/sr0.json` (`type`, `name`, `volume`, `titles[{name,secs,bytes,chapters,source?,segments?,fail?}]`; `fail: true` makes the title fail while ripping). For headless mode the app reads the disc identifiers from `<name>/drives/sr0.iso` (UDF image, e.g. from `tests/udf_build.py`); without an image the structure decides.
- Check in the browser: desktop (1440) and phone (375), console free of errors.

## 7. Package modules (phase 2)
| Package | Backend | Interface | Interface to the outside |
|---|---|---|---|
| PA UI polish | – | `jobs.js`, `jobs-list.js` (stable rows), `logs.js`, `drives.js`, `titles.js`, `css/jobs.css`, `css/titles.css` | title list embeds `mountConvertEditor(…, {mode:'compact'})` |
| PB Navigation, settings | – | `nav.js`, `settings.js`, `settings-general.js`, `css/shell.css` | tabs from `getViews()`; settings `#/einstellungen/<section>` with save per section; events `route`, `settings:dirty` |
| PC Machines | `nodes*.py`, `cluster.py` | `nodes*.js`, `css/nodes.css` | `DATA/nodes.json`, token pairing, search in the /24, `peers[i].legacy/trust/version`; `cluster.cfg_for_peer(cfg, peer)` for hand-overs |
| PD Player | `player.py`, `player_probe.py`, `player_stream.py` | `player*.js`, `css/player.css` | `/api/player/*`; `openPlayer(path)` (overlay), `mountPlayer(el, path, {compact})` (embedded); decision direct/remux/transcode, ffmpeg restart on seek (no HLS) |
| PE Jellyfin filing | `app/media/*` | `media*.js`, `css/media.css` | `/api/media/*` (incl. `POST /api/media/infos`); library action "Einsortieren"; folder prefill from `OUTPUT_MOUNT` |
| PF Conversion, library | `convert_schema.py` (schema v2, v1 stays valid), `ffmpeg_args.py`, `convert_caps.py`, `convert_stats.py`, `convert_builtin.py`, `convert_presets.py`, `convert_probe.py`, `library_info.py` | `convert-*.js`, `library*.js`, `css/convert.css`, `css/library.css` | `/api/convert/*` (meta, estimate, start, presets, probe); `capabilities.convert`; `mountConvertEditor(el, value, {target, onChange, mode:'full'\|'compact'\|'side', discKind, files, readonly})` → `{get, set, setFiles, refresh, destroy}`; library actions with `ctx.where` = `row`/`detail`/`bar`/`folder` |

Cluster and conversion: before a hand-over, `convert_caps.peer_ok` checks the target. Machines with an old version only get the five old fields (`convert_schema.to_v1`), and only if the job can be expressed that way; otherwise the job stays here and the reason is reported. Converted files carry `MKW_CONVERTED` in the container; "converted" in the library means this marker or HEVC/AV1.

Headless mode (PG): `app/headless/` – `udf.py` (UDF reader straight from the device, without mounting; UDF 1.02–2.60 with metadata partition), `discid.py` (disc ID and content hash like TheDiscDB), `plan.py` (title choice: memory → TheDiscDB → TMDB runtimes → structure; identifiers cached per analysis), `memory.py` (selection ripped by hand, per disc, `DATA/headless-memory.json`, can be queried by other machines via `POST /api/headless/memory/lookup`, capability `headless_memory`), `discdb.py` (query `GET https://thediscdb.com/api/discid/<id>` or `/api/dischash/<hash>`, matching by runtime + playlist or size), `tmdbmatch.py` (name unambiguous at TMDB → film or episode runtime), `choose.py` (structure), `contribute.py` (report to TheDiscDB via `POST /api/engram/disc` and `/api/engram/disc/<hash>/logs/scan`, only on button press, with preview), `run.py` (flow, rip hook for the memory, log `DATA/headless.json`). Namespace `headless` (`enabled`, `use_db`, `convert`), state `headless` in `/api/state` (`enabled`, `memory`, `history`), `POST /api/headless/test/{drive}`, `/clear`, `/memory/forget`, `/contribute/{drive}/prefill`, `/contribute/{drive}` (`send: false` = preview). Interface: `js/headless.js` (field at the top right of Laufwerke and switch "Headless" in the drive bar, both toggle `headless.enabled`), `js/headless-contribute.js`, `css/headless.css`. Core: `rip.prepare_rip()`, `makemkv` delivers `segments` per title (attribute 26) and `Parser.raw` (CINFO/TINFO/SINFO/TCOUNT, ends up in `Drive.scan_raw`).

Job list: `app/joblist.py` removes finished entries without asking (`POST /api/conversions/{id}/dismiss`, `/api/uploads/{id}/dismiss`, `/api/jobs/dismiss-finished`, also via `/api/peer/…`); the capability `jobs_dismiss` shows whether a machine can do that (old machines: no button).

Tests: `python3 -m unittest discover -s tests -t .` (the shared environment is set up by `tests/__init__.py`).

## 8. Known limitations
- Duration forecasts are estimates without statistics and get more accurate with every finished conversion.
- Hardware encoding (VAAPI), HDR→SDR (`zscale`) and real Dolby Vision files are only tested at backend level, not with real hardware/sources.
- Container queries need Safari 16+ or Firefox 110+.
- Headless mode: the UDF reader is tested against images (macOS hdiutil UDF 1.02/1.50, own UDF 2.50 image) and the content hash against real TheDiscDB entries; the test with a real disc in the drive (DVD, Blu-ray, UHD) is still outstanding. TheDiscDB mostly knows US releases; German discs often fall back to structure detection.
- (fixed by PF: `convert.ensure_conv_workers()` never started further workers.)
