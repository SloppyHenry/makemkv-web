# Spindle – expansion with several parallel agents

> Historical work order, written when the project was still called MakeMKV-Web (hence the old repo name and paths below).
>
> **Read this document completely before you change anything.**
> You are **not alone**: several Claude agents work on this tool **at the same time**, each on its own work package, each in its
> own Git worktree. Everything you do must be built so that the other packages can grow undisturbed beside it and be merged cleanly at the end.

---

## 1. The project in brief

- Repo: `~/Projekte/makemkv-web` (GitHub `SloppyHenry/makemkv-web`, branch `main`)
- Headless MakeMKV with a browser interface. Runs via Docker Compose on **vierstein** (`ssh vierstein`, user `henry`,
  `~/makemkv-web`, port 8780, http://192.168.178.7:8780). Output goes to datenstein's NFS: `/mnt/datenstein/dump`.
- Several machines form a cluster: jobs of all machines are shown together, conversions can be handed over, foreign drives
  can be remote-controlled. Today the machines know each other only through the environment variable
  `PEERS` (`name=http://host:8780,…`), calls go through `/api/peer/{name}/…` (allow list `PROXY_ERLAUBT`).
- Backend: `app/main.py` (FastAPI, `makemkvcon -r`, ffmpeg/x265, server-sent events, lock files against double processing).
- Frontend: `app/index.html` – single-page UI **without a build step** (this stays: no npm, no bundler).
- Language of the interface, comments and commit messages: **German**, in the style of the existing code.
- Before starting, read: `README.md`, `git log --oneline | head -30`, and the status files of the other packages (section 4).

### 1.1 Machines the tool runs on (as of 2026-10-10)

| Machine | Address | Installation | Hardware | Notes |
|---|---|---|---|---|
| **vierstein** | 192.168.178.7 (`ssh vierstein`) | `~/makemkv-web`, **no Git**: files were copied in, state = `main` ae4603e | 4 cores, 7 GB RAM, `/dev/dri/renderD128` | The BD drive is attached here (MATSHITA BD-MLT UJ240AS, USB, sometimes disconnects). `sudo` without a password. |
| **maintux** | 192.168.178.189, Wi-Fi only (`ssh maintux`) | `~/makemkv-web`, Git clone from GitHub, state ae4603e | Ryzen 5950X (32 threads), 31 GB RAM, RTX 3080 | Strong conversion machine. `sudo` **only with a password**: the user enters those commands themself. Docker has **no** NVIDIA runtime. A llama.cpp server (port 8080) also runs on the GPU, so NVENC only after consultation. Staging on `/mnt/SSD/makemkv-staging`. |
| **secondtux** | 192.168.178.160 | – | – | **Stays out for now**: no rollout, no access. It is in `PEERS` of both machines though and may reappear at any time with the **old version**. Everything must cope with an old machine in the cluster. |

All machines write to the same NFS target `/mnt/datenstein/dump` (datenstein 192.168.178.4).

## 2. What the user wants (overall picture)

1. The loading/working circle does not rotate cleanly.
2. The buttons on the right of the job list do not adapt when the window gets narrower (the text is squashed into a
   one-word column, see screenshot: "Konverti / erung / 56 % · …").
3. No more burger menu, but a clean, visible navigation instead.
4. The log card exists twice on the main page.
5. Machine management in the settings: add machines manually and find machines automatically. A machine is
   discoverable only if that is switched on in its settings. It can also work standalone.
6. Click on files in the library and an internal player plays them.
7. Move finished files into a movies or series folder. Folders, subfolders and files are named
   automatically according to the Jellyfin scheme. The tool first tries to recognize what kind of medium it is;
   otherwise it asks for a title or IMDb ID and shows suggestions for the title. The settings define:
   movies folder, series folder, and whether to rename by Jellyfin or only copy/move unchanged.
8. More options for MKV conversion: ready-made, optimal presets for DVD and Blu-ray, and beyond that choosing codec,
   quality etc. yourself. Find a good presentation for it. The library overview may be rebuilt completely.
   A mockup first.
9. **Most important:** in the end everything runs on the machines in the cluster. Right now these are **maintux and vierstein**;
   secondtux stays out for now (see 1.1).

## 3. Phases and packages

```
Phase 1 (alone, first):  P0  Foundation – split into modules, extension points, dev environment
Phase 2 (parallel):      PA  UI polish (circle, responsive jobs, one log)
                         PB  Navigation + settings page (frame)
                         PC  Machine management + automatic discovery
                         PD  Internal player
                         PE  Jellyfin filing (detect, metadata, name, move)
                         PF  Conversion settings + new library
Phase 3 (alone, last):   PZ  Integration, overall test, rollout to maintux + vierstein
```

Phase 2 starts only when P0 is merged into `main`. Until then no other agent works on the code.

---

## 4. Ground rules for all agents (binding)

### 4.1 Git and worktrees
- Every agent works in **its own worktree** on **its own branch**, never directly in the main folder:
  ```bash
  git -C ~/Projekte/makemkv-web worktree add ~/Projekte/makemkv-web-wt/<package> -b <package> main
  ```
  `<package>` is `paket-a`, `paket-b`, … If the worktree already exists, continue working there.
- Small, self-contained commits with a German message in the style of the existing `git log`.
- **Do not push, do not merge into `main`.** PZ or the user does the merge. Exception: P0 is approved by the
  user and then merged into `main`.
- Regularly fetch the state of `main` (`git rebase main`), above all before reporting your package as done.

### 4.2 Files and responsibilities
- Every package **owns** certain files (table in section 6). Only the owner changes them.
- If you need a change in a foreign file, do **not** make it yourself. Enter it in your status file under
  "Needs from others" and notify the owner (4.4). Exception: a single line with which you register your module
  at a P0 extension point (import and registration in `app/main.py` or `app/static/js/app.js`).
  Such one-line changes are allowed and low on conflicts.
- New functions go into **new files** of your own package, not into existing foreign modules.

### 4.3 Namespaces (so that nothing collides)
| Package | API prefix | Settings namespace | CSS prefix | Frontend module |
|---|---|---|---|---|
| PA | – (existing) | – | `.job…`, `.log…` | `js/jobs.js`, `js/logs.js` |
| PB | – | `general` (takes over today's fields) | `.nav…`, `.page…`, `.set…` | `js/nav.js`, `js/settings.js` |
| PC | `/api/nodes/…`, `/api/discovery/…` | `nodes` | `.node…` | `js/nodes.js` |
| PD | `/api/player/…` | `player` | `.player…` | `js/player.js` |
| PE | `/api/media/…` | `media` | `.media…` | `js/media.js` |
| PF | `/api/convert/…`, `/api/library/…` (existing ones stay) | `convert` (takes over `presets`, `conv_*`) | `.cv…`, `.lib…` | `js/convert-editor.js`, `js/library.js` |

- Existing endpoints keep their paths and response shapes, because older instances in the cluster keep calling them
  during the rollout. Fields are only **added**, nothing is renamed or removed.
- What should be reachable in the cluster is registered through P0's proxy extension point. The old `PROXY_ERLAUBT`
  is not edited directly.

### 4.4 Knowing about each other
- Every package keeps **`docs/agents/status-<package>.md`** in its worktree; only the package itself writes this file.
  Keep it current after every milestone:
  ```markdown
  # Status <package> – as of <date time>
  ## Done
  ## In progress
  ## Interfaces offered   (endpoints with example JSON, JS functions, events, settings keys)
  ## Needs from others    (who, what, why – with status: open/done)
  ## Foreign files touched (should be empty, otherwise justify)
  ## Questions for the user
  ```
- **Before every bigger step, read the status files of the others** under
  `~/Projekte/makemkv-web-wt/paket-*/docs/agents/status-*.md`. That way you learn what exists and what is planned.
  Do not build twice what another package offers. Use its interface (against a stub for now, if it does not exist yet).
- If you have the tools `ListAgents`/`SendMessage`, write to the affected agents directly for interface questions,
  briefly and with a reference to the status file. Otherwise: an entry under "Needs from others" and point the user to it.
- If an interface that another package uses changes: announce it in the status file first, then change it.

### 4.5 Way of working
- **Mockup first, then build** (explicit requirement of the user): every package with a visible new interface
  (PB, PC, PD, PE, PF) first creates a static mockup as `docs/mockups/<package>.html`. It uses the same colors and
  components as the app. Show it to the user and **wait for approval**. Backend work may continue meanwhile.
  Approved mockups are implemented **1:1**. What cannot be done is named beforehand and not silently dropped.
- **Check in the browser**, not only with `curl`: start locally with `scripts/dev.sh` (from P0), open in the built-in
  browser and look at desktop as well as phone width (375 px). A console without errors is mandatory.
- **Roll out nothing** on vierstein, maintux or secondtux and do not restart containers there. Real
  rips and conversions run there. Only PZ does that, after asking. Read-only queries (e.g. `ffmpeg -encoders`,
  `/api/state`) are allowed if you need to know hardware capabilities or real data.
- **Backward compatibility in the cluster is mandatory:** new machines must work together with machines on the old version
  (secondtux!). If a machine lacks a capability, it is greyed out in the interface for that, not served with wrong
  data. Every machine reports its capabilities (version, codecs, features) in `/api/state`.
- On the NAS (`/mnt/datenstein/…`) **do not delete, move or rename anything** while you develop. Testing is done with
  the sample files from `scripts/dev.sh` in a temporary folder.
- Ask the user real questions (taste, privacy, API keys) instead of guessing. Decide everything else yourself
  and justify the decision in the status file.
- Done means: function checked in the browser, `python -m py_compile` clean, status file current, branch rebased
  onto `main`, short summary to the user with what they should test themselves.

---

## 5. The work packages

### P0 – Foundation (phase 1, one agent, before all others)

**Goal:** split the code so that five agents can work in parallel without constantly wrecking the same two files.
**No visible change in behavior.** After P0 the app must work exactly as before.

1. **Split the backend** into a package `app/` with modules, e.g. `config.py` (environment, paths, `DEFAULTS`),
   `state.py` (runtime state, `broadcast`, `snapshot`), `drives.py`, `rip.py`, `convert.py`, `upload.py`, `library.py`,
   `cluster.py` (today's peers, proxy, hand-over), `settings.py`, `files.py`. `main.py` only creates the app, includes the
   routers and starts the background tasks. Pure moving, no rewriting of logic.
2. Create and document **extension points**:
   - `register_router(router)`: new modules bring their own `APIRouter`.
   - `register_settings(namespace, PydanticModel, defaults)`: `GET/POST /api/settings` accepts nested
     namespaces (`{"media": {...}}`). Today's flat fields stay valid, they belong to `general`.
   - `register_snapshot(key, fn)`: modules attach their own data to `/api/state` or the SSE message without
     touching `snapshot()`.
   - `allow_proxy(regex)`: replaces editing `PROXY_ERLAUBT` directly.
   - `register_startup(coro)`: background tasks of a module.
3. **Split the frontend:** `app/static/index.html` (scaffold), `app/static/css/{base,layout,components}.css`,
   `app/static/js/` as native ES modules (`<script type="module">`, no build): `core.js` (`$`, `api`, `esc`, `toast`,
   `setHtml`, SSE connection, global state `S`), `drives.js`, `titles.js`, `jobs.js`, `logs.js`, `library.js`,
   `handover.js`, `settings.js`, `app.js` (loads and registers the modules). Serve static files through FastAPI.
   Pay attention to no-cache or version parameters, so that browsers do not mix old modules after the rollout.
4. **Frontend extension points:**
   - `registerView({id, label, icon, order, mount(el), unmount()})` with hash routing (`#/laufwerke`, `#/bibliothek`,
     `#/einstellungen`, …). The back button and reload keep the view. Today's burger menu stays **for now**
     as the presentation, PB replaces it.
   - `registerSettingsSection({id, label, order, render(el, settings), collect() -> {namespace: {...}}})`.
   - `onState(fn)`: subscription to state changes instead of direct calls from `render()`.
   - `registerLibraryAction({id, label, icon, primary?, when(files), run(files)})`: actions for files in the
     library (play from PD, file from PE, convert from PF). That way nobody except PF has to touch `library.js`.
     `primary: true` means: a click on the file name triggers this action (PD: play).
   - Backend: `register_rip_hook(fn)` (called after every finished title with disc info, for PE) and
     `register_capability(name, value)` (ends up in `/api/state` under `capabilities`, for cluster checks).
5. **Dev environment** `scripts/dev.sh`: starts the app locally on the Mac (uvicorn) with `DATA_DIR`/`OUTPUT_DIR` in a
   temporary folder and generates sample files via ffmpeg, e.g. a 2-min film H.264+AC3,
   `The Walking Dead - Disc 1 - Titel 01…05` with episode length, an HEVC 10-bit file and a folder with umlauts.
   Optionally `--port`/`--name`, so that two instances can be started side by side (needs PC to test the cluster).
6. Commit `docs/agents/AUFTRAG.md` (this file) as well, and create `docs/agents/schnittstellen.md` with the description of all
   extension points including an example.
7. Check: all existing endpoints answer the same (before/after comparison of `/api/state` and `/api/library`
   against the dev instance), click through the interface in the browser, the Docker image builds (`docker build .`).

**Hand-over:** status file and a message to the user that P0 can be merged into `main` and phase 2 starts.

---

### PA – UI polish

**Owns:** `js/jobs.js`, `js/logs.js`, parts of `css/` for jobs/log (create a separate file `css/jobs.css`).

1. **Spinning circle (`.status-check.run`) is jerky.** The cause has already been found: `renderJob()` rebuilds the whole list via
   `setHtml()` as soon as percent, fps or remaining time change, i.e. several times per second. That recreates the
   circle element and the CSS animation starts at 0° again every time. Solution: update jobs **by key**
   (one stable DOM element per job, only text, bar width and buttons change). As additional
   safeguard tie the phase to the clock (`animation-delay: -(Date.now() % 1000)ms`). Check all other rotating or
   running elements right away: indeterminate progress bar (`@keyframes ind`), circle in the progress panel,
   spinner in the library. The circle must stay perfectly round (`aspect-ratio`, `flex:none`) and must not wobble at subpixels
   (even sizes, `box-sizing`).
2. **Responsive job row.** Today the status pill, "Überspringen" and "Abbrechen" sit rigidly on the right and squash the
   text to word width. Solution with **container queries** on the jobs panel (the width depends on the layout, not on the
   window): wide, then everything in one row; medium, then buttons below the text; narrow, then buttons as
   icon buttons or in a "⋯" menu. Attach the status pill to the title. The text must never fall below about 180 px.
   Check at 1440, 1280, 1050, 900, 700 and 375 px, also with the machine-name badge and long file names.
3. **Log only once.** Today there is `#compactLog` ("Protokoll anzeigen", right) **and** `#fullLog` (bottom).
   Only one card stays. Recommendation: the lower one, collapsible; the state is remembered (localStorage with try/catch). A
   new error opens it or shows a badge. Briefly align this with PB in case PB wants the log as a view of its own
   in the navigation.
4. Found, smaller: in the title list the badge "Längster" cuts off the file name ("…Disc 1 – Tit"). Put the badge
   next to the number or below the name. The title list actually belongs to P0/`titles.js`; after P0 it has no
   owner any more, PA takes it over.

---

### PB – Navigation and settings page

**Owns:** `static/index.html` (scaffold/header), `js/nav.js`, `js/settings.js`, `css/shell.css`.

1. **Replace the burger menu (☰) and the gear dialog** with a visible navigation with the views
   *Laufwerke · Bibliothek · Einstellungen* (further views register via `registerView` and appear
   automatically). Proposal to align on in the mockup: desktop with tabs in the header next to the logo (active view
   underlined in red, number of running jobs as a badge), phone with a tab bar at the bottom. Show one or two alternatives in the
   mockup, e.g. a narrow sidebar with icons.
2. Place the drive chip(s) in the header so that they do not collide with the navigation (with several
   drives and machines wrap or show as a selection).
3. **Settings as a page of their own** instead of `<dialog>`: section list on the left, content on the right (stacked on the phone).
   Sections come via `registerSettingsSection`. PB builds **Allgemein** (today's fields: auto-analysis,
   auto-eject, minimum length, languages) and **MakeMKV-Key**. **Konvertierung & Presets** (PF), **Rechner** (PC) and
   **Medien/Jellyfin** (PE) are placeholders until the packages deliver.
   One save button per section; a notice for unsaved changes.
4. The paths "Nachträglich konvertieren" and "← Laufwerke" become superfluous through the navigation and are dropped.
5. Keyboard and accessibility: tabs with `role="tablist"`, visible focus, views linkable by hash.

---

### PC – Machine management and automatic discovery

**Owns:** `app/nodes.py` (new; gradually replaces the peer parts in `cluster.py`, which PC takes over after P0),
`js/nodes.js`, `css/nodes.css`.

1. **Operating mode** (setting `nodes.mode`): `standalone` (no other machines, no discovery, cluster elements
   in the interface disappear) or `verbund`. Additionally `nodes.discoverable` (this machine answers
   search requests), default **off**. The name of this machine is changeable (default: `INSTANCE_NAME`).
2. **Machine list** in `DATA/nodes.json` instead of the environment variable `PEERS`. On first start existing `PEERS`
   are adopted (migration). `PEERS` afterwards only acts as a preset. Display per machine: name, address, online
   since/last seen, version, drives, cores/RAM, running work. Actions: add (manually by address),
   rename, remove, test the connection.
3. **Find automatically:** button "Rechner im Netz suchen" and optionally a running search in the background.
   - Careful with Docker: in the default bridge network multicast/broadcast (mDNS, UDP) does not reach the container. Decide
     and justify: (a) mDNS `_makemkv-web._tcp` with `network_mode: host` in `docker-compose.yml` (agree the change with PZ,
     because it affects port mapping and firewall) and/or (b) as a fallback an active scan of the own
     /24 network on port 8780 with `GET /api/discovery/hello`. Variant (b) also works in the bridge network. The answer
     contains name, instance ID, version, capabilities and whether pairing is allowed.
   - A machine only answers with details if `discoverable` is on; otherwise `404`.
4. **Pair instead of trusting blindly:** A finds B, click on "Verbinden", B shows a request ("A möchte sich verbinden")
   with confirmation, then both exchange a shared token. All machine-to-machine calls (proxy, hand-over,
   status) carry this token afterwards. As a side effect this solves the problem that peer calls would
   fail when `AUTH_PASS` is set. Manually added machines go through the same pairing. Unpairing deletes the token on both
   sides.
5. **Mixed versions:** during the rollout machines with the old version run. Old machines (without `/api/discovery`)
   stay usable through the existing peer logic and are marked as "ältere Version".
6. Existing functions (shared jobs, hand-over, remote control of drives, converting on another machine)
   must run on the new machine list afterwards. The fields in `/api/state` (`peers`, `reachable`, `has_handover`, …)
   are kept.
7. Test with two local instances (`scripts/dev.sh --port 8781 --name test-b`), including pairing, unpairing,
   machine offline and machine not discoverable.

---

### PD – Internal player

**Owns:** `app/player.py`, `js/player.js`, `css/player.css`. The player gets into the library **only** via
`registerLibraryAction({id:'play', primary:true, …})`. `library.js` belongs to PF. PF rebuilds the library; agree
with PF on where the player sits (overlay or in the detail pane of the new library).

1. A click on a file in the library (and in "Fertige Dateien") opens the player in an overlay or a
   side area: play/pause, seek, volume, fullscreen, audio-track and subtitle choice, chapters (if present),
   shortcuts (space, ←/→, F, Esc).
2. **The core problem is the format, not the interface:** MKV with HEVC 10-bit, VC-1/MPEG-2 (Blu-ray originals),
   AC3/DTS/TrueHD audio and PGS subtitles are not played directly by any browser. Plan:
   - `GET /api/player/probe?path=` returns codecs and tracks and decides: **direct** (HTTP range on the file, if
     the browser can do it), **remux** (copy video, audio to AAC, stream as fragmented MP4) or **transcode**
     (H.264 with lower resolution/bitrate, for VC-1/MPEG-2 or if the browser cannot do HEVC). The browser reports
     what it can do (`MediaSource.isTypeSupported`/`canPlayType`, e.g. HEVC in Safari).
   - Seeking for remux/transcode via a restart of ffmpeg with `-ss`, or generate HLS segments and
     cache them. Weigh up, decide, justify.
   - Text subtitles to WebVTT, picture subtitles (PGS/VobSub) at first only shown as "not supported" (optionally
     burn in).
3. **Consideration for the actual work:** transcoding costs CPU while rips and x265 conversions run.
   ffmpeg with `nice`, at most one simultaneous transcode stream per machine, end the process immediately when the player
   closes or the connection drops. Optional: let playback be streamed from another machine in the cluster
   (use PC's interface).
4. Files with a lock (currently being converted/replaced) are still playable read-only, but with a notice. Allow only paths inside
   the output folder (use the existing `inside_out()`, test path escape).
5. Test with the sample files from `scripts/dev.sh` in Safari-like and Chrome-like behavior.

---

### PE – Jellyfin filing

**Owns:** `app/media/` (new: `detect.py`, `metadata.py`, `naming.py`, `organize.py`), `js/media.js`, `css/media.css`.

1. **Settings** (namespace `media`, section "Medien / Jellyfin" on PB's settings page):
   - Movies folder and series folder (selection with a folder browser inside the mounted target, check for
     write permission).
   - Naming: `jellyfin` (rename by scheme) or `unveraendert` (files and folders stay as they are).
   - Action: `verschieben` (default) or `kopieren`.
   - Metadata source: TMDB API key (field + "Testen"), language for titles (default `de-DE`), ID tags in the name yes/no.
   - Optional: Jellyfin URL and API key to trigger a library scan after filing.
   - Optional: "Automatisch einsortieren, wenn eindeutig erkannt" (default off).
2. **Recognize what it is** (`detect.py`), with a match probability:
   - Sources: disc name and volume label (e.g. `The Walking Dead - Disc 1`, `WALKING_DEAD_S1_D1`), file name and folder,
     number of titles and runtimes. Several titles of similar length of 20–70 min point to a series, a main title over
     70 min to a film.
   - Recognize "Play-All" titles: a title whose runtime roughly equals the sum of the episodes (in the screenshot
     title 3 with 3:21:55 for 44-min episodes) is marked as such and not filed as an episode.
   - So that detection still has material days later: when ripping, store an accompanying file with disc name, label,
     title numbers, runtimes and chapters. After P0 the rip part belongs to `rip.py`: PE registers via a hook
     (e.g. `register_rip_hook`) or asks P0/PZ for the hook. Stored under `DATA/media/` mapped by path,
     **not** as a foreign file in the NAS folder, so that Jellyfin does not stumble.
3. **Metadata** (`metadata.py`): TMDB search for film and series with year, suggestions with poster preview, year and
   short description. Resolve the IMDb ID (`tt1234567`) via TMDB `/find`. Cache results. Without a key:
   no suggestions, then title and year by hand, with a clear notice in the interface. The user supplies the key,
   **do not** obtain one yourself or build one in.
4. **Naming by Jellyfin** (`naming.py`, with tests as pure functions):
   - Film: `<Movies>/Title (Year) [imdbid-tt…]/Title (Year) [imdbid-tt…].mkv`. Several versions as
     `Title (Year) - 1080p.mkv`; extras in subfolders like `extras/`, `behind the scenes/`, `featurettes/`.
   - Series: `<Series>/Series (Year) [tmdbid-…]/Season 01/Series S01E01.mkv`; specials in `Season 00`; double episodes
     `S01E01-E02`. Optionally append episode names (`S01E01 - Episode name`).
   - Replace forbidden characters (`: / \ ? * " < > |`), keep umlauts, remove trailing dots/spaces.
   - Check the rules against the current Jellyfin documentation on naming films and series and note the source in the
     status file.
5. **Assign episodes:** for series discs a proposal from disc number and title order (disc 1 with 4 episodes yields
   E01–E04, disc 2 continues), with a runtime comparison against TMDB. The state per series is remembered. The user
   can correct season and episode per file in a table.
6. **Filing** (`organize.py`): from the library (multi-selection or folder), "In Filme/Serien
   einsortieren …" (registered via `registerLibraryAction`, not written into `library.js`) opens a wizard: recognized → confirm or search (title with suggestions or IMDb ID) → **preview of the
   target tree** (old → new, conflicts red) → execute. Move within the same file system by renaming,
   otherwise copy, check (size) and only then remove the original. Respect existing lock files: whatever is currently being
   converted, transferred or played is not touched (use `busy_reason()`). Target already exists:
   never overwrite, ask. Clean up empty source folders afterwards. Log every action, with an
   undo list for the last action.
7. Test exclusively with sample files and temporary movies/series folders (`scripts/dev.sh`), never on the NAS.
8. Agreement with PF: in the new library, films and series should appear grouped when metadata exists.
   For that PE offers `GET /api/media/info?path=` (title, year, kind, poster URL, season/episode).

---

### PF – Conversion settings and new library

**Owns:** `app/convert.py` (after P0), `app/library.py`, `app/convert_presets.py` (new), `js/library.js`,
`js/convert-editor.js` (new), `css/library.css`, `css/convert.css`, settings section "Konvertierung & Presets".

**Starting point:** today there is one stored preset per disc type (bluray/dvd) with exactly five fields:
`rf`, `preset`, `tune`, `extra` (x265 parameters as text), `audio`. Always x265 10-bit, segment mode for long films,
automatic cropping. The library is a table with a folder tree, codec/audio/size/status and a fixed
conversion block above it.

**Mockup first, with two parts and at least two variants each. Build only after approval.**

#### Part 1 – Setting up conversion: presentation in three levels
1. **Preset cards** as the entry point (a row of selectable cards). Bundled and not deletable, with a short explanation of what
   they are for:
   - *DVD optimal*: deinterlace/IVTC automatic, light denoising, x265 RF ~19–20, copy audio.
   - *Blu-ray optimal*: x265 10-bit, RF ~20–21, `slow`, `aq-mode=3`, copy audio (today's default).
   - *Blu-ray Animation*: `tune=animation`, a higher RF possible.
   - *Film mit starkem Korn*: `tune=grain` or suitable psy-rd/deblock values.
   - *UHD / HDR erhalten*: pass HDR10 metadata through, 10-bit mandatory.
   - *Klein & schnell*: e.g. 1080p→720p, `faster`, audio to AAC/Opus stereo.
   - Plus the user's own presets (from a customization "Als Preset speichern"), rename and delete.
   - Default assignment: which preset is preselected automatically for DVD or Blu-ray.
   Research and justify the exact values (encoder documentation, common recommendations), do not guess.
2. **Customize view** (expandable, starting from the chosen preset; changed values marked, "zurück auf Preset"):
   - **Video:** codec as a segmented choice: *H.265/HEVC (x265)* · *H.264 (x264)* · *AV1 (SVT-AV1)* · *Hardware*
     (only if the target machine reports it, e.g. VAAPI/QSV on `renderD128`) · *nicht konvertieren (nur remuxen)*.
     Bit depth 8/10.
   - **Quality:** slider with an understandable scale ("smaller ← → better", marker "optisch verlustfrei") instead of a bare
     RF number, with the number visible beside it. Alternatively mode *target size* (GB) or *bitrate* with 2-pass. The RF scale depends
     on the codec (CRF x264 ≠ x265 ≠ SVT-AV1 CRF), so map to the same perception scale per codec.
   - **Speed:** preset slider (ultrafast … veryslow or SVT preset 0–13) with a note on duration.
   - **Picture:** resolution (keep/1080p/720p), crop (automatic/off/manual), deinterlace (auto/off/on),
     denoise (off/light/medium), HDR (keep/tone mapping to SDR).
   - **Audio:** per track or as a rule: copy / AAC / Opus / AC3, channels (like source/5.1/stereo downmix), bitrate,
     language filter (refers to the general setting).
   - **Subtitles:** keep all / forced only / only languages X / none.
   - **Experts:** free encoder parameters (today's `extra`) and a display of the generated ffmpeg command (read only).
3. **Forecast, so that decisions are visible:** estimated target size and duration per machine, from the statistics of
   earlier conversions (`size_in/size_out`, fps per codec/preset/resolution/machine, stored in
   `DATA/conv_stats.json`). Optionally a **test encode**: encode 20–30 s at two places, then extrapolate the size and show a
   before/after still image with a slider.
4. **One editor, three places:** `js/convert-editor.js` as a reusable component
   (`mountConvertEditor(el, value, {target, onChange})`) for (a) "Nach dem Rippen konvertieren" in the title list (the
   panel belongs to PA; PA integrates the editor there as soon as PF offers it, until then the old form stays),
   (b) the library, (c) the settings section "Konvertierung & Presets" (preset management, default assignment,
   segments, parallelism).
5. **Backend:** a new, versioned schema for conversion settings (`{"v":2, "codec":…, "quality":{…}, …}`).
   The old five fields are **migrated** on loading; `clean_convert` validates both. `ffmpeg_args`/`x265_args`/
   `audio_args` per codec, the segment mode must work with all software codecs (switch off for hardware if needed).
   Report capabilities per machine via `register_capability('encoders', …)` (from `ffmpeg -encoders` and existing
   devices). Check whether the ffmpeg in the Docker image contains `libx264`, `libsvtav1`, VAAPI; if something is missing, write the wish to
   PZ (`Dockerfile`) into the status file.
6. **Cluster:** a job with v2 settings must **never** go to a machine that does not understand them (old
   version like secondtux) or that lacks the encoder. It would otherwise silently encode with the x265 default. Grey such machines out in the
   "Ausführen auf" selection field and in the hand-over and name the reason. A v1-compatible job (x265 without
   new options) may still go to old machines.

#### Part 2 – Rethinking the library
Proposal as a starting point for the mockup (alternatives welcome):
- **Three areas:** filters/folders on the left (folder tree, quick filters *Original · Konvertiert · In Arbeit · Fehler*,
  *Filme · Serien · Unsortiert* as soon as PE delivers metadata, machine), in the middle the files as **list or grid** (grid
  with posters when PE has metadata), on the right a **detail pane** for the selection: tracks, codec, resolution, HDR, size,
  "Einsparung mit Preset X: ~Y GB", actions (play/PD, convert, file/PE, rename, delete).
- **Badges instead of text columns:** codec (HEVC/H.264/VC-1/MPEG-2), resolution (SD/1080p/UHD), HDR, audio (DTS-HD/TrueHD/AC3),
  status. Series folders summarized with season sub-items.
- **Selection bar at the bottom** as soon as files are selected: "3 Dateien · 62 GB · ~38 GB Ersparnis", preset choice, "Ausführen
  auf …" (with estimated duration per machine), convert. The conversion editor opens as a side panel.
- Running work directly on the file: progress, machine, skip/cancel (existing functions stay).
- Header with the free space of the target and a sum "mögliche Einsparung" across all originals.
- Fast with large libraries (hundreds of files): render in chunks or virtualized, filters without reloading,
  selection is kept on refresh (today every 4 s).
- Existing things stay: renaming files and folders, lock files, converting on another machine,
  replacing the original after a passed check.

---

### PZ – Integration and rollout (phase 3, one agent, after all others)

1. Read the status files of all packages, close open "Needs from others" items (including Dockerfile and
   Compose wishes, e.g. encoders in the image, `network_mode: host` for discovery).
2. Merge the branches onto an integration branch in a sensible order (proposal: PA → PB → PF → PC → PD → PE),
   resolve conflicts, bring `docs/agents/schnittstellen.md` up to the final state.
3. Overall test in the browser: all views, desktop and phone, two local instances in a cluster **plus** one instance on
   the old version ae4603e (simulates secondtux), player, conversion with every codec (short sample file), filing
   (dry run), console free of errors. Extend the README with the new functions.
4. **Rollout is the most important step and happens only after explicit approval by the user:**
   - Merge into `main` and push.
   - **Targets: maintux and vierstein. Do NOT touch secondtux** (stays on the old version, but must be displayed cleanly in the cluster as
     "ältere Version" or "offline").
   - Beforehand check on every machine (`/api/state`) that no rip, backup or conversion is running. Otherwise wait or
     use the hand-over with the user. Back up `data/` (config.json, presets, library cache) and `.env` beforehand
     (`cp -a data data.bak-<date>`).
   - **maintux:** Git clone in `~/makemkv-web` → `git pull` → `docker compose up -d --build`. No passwordless
     `sudo`: if root steps are needed (firewall port for discovery, `network_mode: host`, ffmpeg/driver on the
     host), give the user the finished commands to run themself.
   - **vierstein:** `~/makemkv-web` is **not a Git repo**, the files were copied in. Clarify with the user whether
     a Git clone should be created there now (recommended: clone next to it, take over `.env`/`data`, then switch), or
     update via `rsync` (without `data/`, `.env`). Then `docker compose up -d --build`. `sudo` works without a password.
   - Order: **maintux** first (no drive attached there, lower risk), check, then **vierstein**.
   - After the rollout check on both machines: the interface loads (without browser-cache leftovers), both see each other in the
     cluster (and pair, if PC requires it), old `PEERS` were migrated, secondtux appears offline/older
     instead of an error, the drive on vierstein is detected, a short test conversion runs on maintux, the
     library shows the NAS.
   - Document and keep the way back ready (previous image/commit + `data.bak`).
   - Result in `docs/agents/status-paket-z.md` and as a short message to the user.

---

## 6. File ownership after P0 (short version)

| File / folder | Owner |
|---|---|
| `app/main.py`, `config.py`, `state.py`, `settings.py` (core) | P0, afterwards PZ (one-line registrations allowed) |
| `drives.py`, `rip.py`, `upload.py`, `files.py` | P0, afterwards only via hooks/agreement |
| `convert.py`, `convert_presets.py`, `library.py` | PF |
| `cluster.py`, `nodes.py` | PC |
| `player.py` | PD |
| `app/media/` | PE |
| `static/index.html`, `js/nav.js`, `js/settings.js`, `css/shell.css` | PB |
| `js/jobs.js`, `js/logs.js`, `js/titles.js`, `css/jobs.css` | PA |
| `js/library.js`, `js/convert-editor.js`, `css/library.css`, `css/convert.css` | PF (PD/PE only via `registerLibraryAction`) |
| `js/nodes.js`, `js/handover.js` | PC |
| `js/player.js` | PD |
| `js/media.js` | PE |
| `js/core.js`, `js/app.js`, `css/base.css` | P0, afterwards PZ (registration lines allowed) |
| `docker-compose.yml`, `Dockerfile`, `install.sh` | PZ (change requests via the status file) |
| `docs/agents/status-<package>.md` | the respective package |
