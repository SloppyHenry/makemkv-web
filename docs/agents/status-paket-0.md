# Status P0 (foundation) – as of 2026-10-10

## Done
- Backend split out of `app/main.py` (2117 lines) into modules (`config`, `state`, `settings`, `auth`, `ui`, `util`, `files`, `makemkv`, `drives`, `rip`, `upload`, `ffmpeg`, `convert`, `library`, `cluster`, `ext`); logic moved unchanged. Largest file: `convert.py` (~300 lines).
- Frontend split out of `app/index.html` (893 lines): `app/static/{index.html, css/*.css, js/*.js}`; native ES modules, no build. Static files with `no-cache`/ETag; CSS and JS are registered automatically by the server (`app/ui.py`).
- Extension points: backend `ext.register_router/settings/snapshot/capability/startup/rip_hook/upload_hook`, `ext.allow_proxy`; frontend `registerView/Panel/SettingsSection/LibraryAction`, `onState`, events, hash routing (`#/laufwerke`, `#/bibliothek`). Optional modules (`app.nodes`, `app.player`, `app.media`, `app.convert_presets`) and all `static/js/*.js`/`css/*.css` are loaded automatically – nobody has to touch `main.py` or `app.js`.
- `/api/state` reports `capabilities` (version, features); `peers[i].capabilities` is passed through by the cluster (empty on old machines).
- `GET /api/settings` (new), `POST /api/settings` accepts namespaces (`general` = the flat fields; secret fields are not returned).
- `scripts/dev.sh` (+ `dev-samples.sh`, `dev-bin/makemkvcon`): instances singly or as a pair, sample files, fake drive with fake rips.
- `Dockerfile`: package layout (`/srv/app`, `uvicorn app.main:app`), new `.dockerignore`.
- Documentation: `docs/agents/schnittstellen.md`, `AUFTRAG.md` committed as well.

## Verified (locally, `scripts/dev.sh`)
- All routes identical to the old state (OpenAPI comparison), only `GET /api/settings` added. `/api/state`, `/api/library`, `/api/files` compared against the old version with the same data: identical (only `capabilities` is new).
- Browser: drive view and library DOM-identical to the old state (progress, title list, actions, jobs, files, library), computed CSS values identical at 375 px; settings dialog, saving, menu, back/forward, deep link, cluster with two instances (foreign drive, hand-over dialog, proxy), console free of errors.
- Flow: fake rip → transfer → eject; rip with conversion; library conversion (replace original); segment mode (3 segments).
- Extension points tried with temporary test modules (backend and frontend) and removed again.

## Docker
- There is no Docker on the development Mac. With the user's approval, the changed Python stage of the image was built on vierstein in a throwaway folder (`~/mkw-build-test-p0`, deleted afterwards together with the image; running container and `~/makemkv-web` untouched) (same `COPY app /srv/app`, `WORKDIR /srv`, `CMD uvicorn app.main:app`) and started briefly: `/api/state`, `/`, `/static/...` respond, modules are registered.
- **Not built:** the MakeMKV stage of the real Dockerfile (it downloads MakeMKV and requires `ACCEPT_EULA=yes`; unchanged). The full build happens in PZ during rollout.

## Interfaces offered
See `docs/agents/schnittstellen.md`.

## Needs from others
- PF: `convert.ensure_conv_workers()` never starts further workers (existing bug, see schnittstellen.md §7). Status: open.

## Foreign files touched
Not applicable (P0 owns the core).

## Questions for the user
- Docker build test on vierstein (throwaway folder)? – already approved.
