# Status P0 (Fundament) – Stand 2026-10-10

## Erledigt
- Backend aus `app/main.py` (2117 Zeilen) in Module zerlegt (`config`, `state`, `settings`, `auth`, `ui`, `util`, `files`, `makemkv`, `drives`, `rip`, `upload`, `ffmpeg`, `convert`, `library`, `cluster`, `ext`); Logik unverändert verschoben. Größte Datei: `convert.py` (~300 Zeilen).
- Frontend aus `app/index.html` (893 Zeilen) zerlegt: `app/static/{index.html, css/*.css, js/*.js}`; native ES-Module, kein Build. Statische Dateien mit `no-cache`/ETag; CSS und JS werden vom Server automatisch eingetragen (`app/ui.py`).
- Erweiterungspunkte: Backend `ext.register_router/settings/snapshot/capability/startup/rip_hook/upload_hook`, `ext.allow_proxy`; Frontend `registerView/Panel/SettingsSection/LibraryAction`, `onState`, Ereignisse, Hash-Routing (`#/laufwerke`, `#/bibliothek`). Optionale Module (`app.nodes`, `app.player`, `app.media`, `app.convert_presets`) und alle `static/js/*.js`/`css/*.css` werden automatisch geladen – niemand muss `main.py` oder `app.js` anfassen.
- `/api/state` meldet `capabilities` (Version, Features); `peers[i].capabilities` wird vom Verbund durchgereicht (leer bei alten Rechnern).
- `GET /api/settings` (neu), `POST /api/settings` akzeptiert Namensräume (`general` = die flachen Felder; Geheimnisfelder werden nicht ausgegeben).
- `scripts/dev.sh` (+ `dev-samples.sh`, `dev-bin/makemkvcon`): Instanzen einzeln oder als Paar, Beispieldateien, Attrappen-Laufwerk mit Fake-Rips.
- `Dockerfile`: Paketlayout (`/srv/app`, `uvicorn app.main:app`), neue `.dockerignore`.
- Dokumentation: `docs/agenten/schnittstellen.md`, `AUFTRAG.md` mit committet.

## Geprüft (lokal, `scripts/dev.sh`)
- Alle Routen identisch zum Altstand (OpenAPI-Vergleich), zusätzlich nur `GET /api/settings`. `/api/state`, `/api/library`, `/api/files` gegen die alte Version mit gleichen Daten: gleich (neu nur `capabilities`).
- Browser: Laufwerksansicht und Bibliothek DOM-gleich zum Altstand (Fortschritt, Titelliste, Aktionen, Aufträge, Dateien, Bibliothek), berechnete CSS-Werte gleich bei 375 px; Einstellungsdialog, Speichern, Menü, Zurück/Vor, Direktlink, Verbund mit zwei Instanzen (Fremdlaufwerk, Übergabe-Dialog, Proxy), Konsole ohne Fehler.
- Ablauf: Fake-Rip → Übertragung → Auswerfen; Rip mit Konvertierung; Bibliotheks-Konvertierung (Original ersetzen); Segment-Modus (3 Segmente).
- Erweiterungspunkte mit temporären Testmodulen (Backend und Frontend) ausprobiert und wieder entfernt.

## Nicht geprüft
- `docker build`: auf dem Entwicklungs-Mac ist kein Docker installiert. Layout wurde mit `uvicorn app.main:app` aus einem Ordner nach dem Schema des Images geprüft; das echte Image muss noch gebaut werden (siehe Meldung an den Nutzer).

## Angebotene Schnittstellen
Siehe `docs/agenten/schnittstellen.md`.

## Brauche von anderen
- PF: `convert.ensure_conv_workers()` startet nie weitere Worker (bestehender Fehler, siehe schnittstellen.md §7). Status: offen.

## Fremde Dateien angefasst
Entfällt (P0 besitzt Kern).

## Fragen an den Nutzer
- Docker-Build-Test auf vierstein (Wegwerf-Ordner)? – bereits freigegeben.
