# Schnittstellen und Aufbau (Stand nach Phase 2, alle Pakete zusammengeführt)

Gilt für alle Pakete. Ergänzt `AUFTRAG.md`; bei Widerspruch gilt `AUFTRAG.md` Abschnitt 4 (Spielregeln).

## 0. Konventionen
- **Keine Datei mit mehr als 400 Zeilen Code** (Python, JS, CSS, Shell). Wird ein Modul zu groß, in sinnvolle Teile aufteilen (Beispiel: `convert.py` und `ffmpeg.py`). Vor jedem Commit `wc -l` auf die geänderten Dateien.
- Deutsch in Oberfläche, Kommentaren und Commit-Nachrichten. Kein npm, kein Bundler, kein Framework: native ES-Module, FastAPI.
- Ein Modul, eine Aufgabe. Neue Funktionen in neue Dateien des eigenen Pakets; fremde Module nur über die Erweiterungspunkte unten ansprechen.
- Backend: `python -m py_compile` bzw. `pyflakes` sauber. Frontend: keine Fehler in der Browser-Konsole.

## 1. Aufbau

### Backend (`app/`, Python-Paket, Start: `uvicorn app.main:app`)
| Modul | Inhalt | Besitzer |
|---|---|---|
| `main.py` | erzeugt die App, bindet Router ein, lädt optionale Module, startet Hintergrundaufgaben | P0/PZ |
| `ext.py` | **alle Erweiterungspunkte** (Registrierungsfunktionen), importiert nichts aus `app` | P0/PZ |
| `config.py` | Umgebungsvariablen, Pfade, Konstanten, `DEFAULTS`, `VERSION`/`FEATURES` | P0/PZ |
| `state.py` | Laufzeitstatus (`settings`, `drives`, `uploads`, `conversions`, `peers_state` …), `broadcast()`, `snapshot()`, `/api/state`, `/api/events` | P0/PZ |
| `settings.py` | Laden/Speichern, `GET/POST /api/settings` mit Namensräumen | P0/PZ |
| `auth.py` | Passwortschutz (HTTP Basic) als Middleware | P0 (PC ergänzt Token-Prüfung) |
| `ui.py` | liefert `index.html` und `/static`; trägt CSS/JS-Dateien automatisch ein | P0/PZ |
| `util.py` | reine Hilfsfunktionen (`safe_name`, `fmt_bytes`, `unique_path`, `valid_name` …) | P0 |
| `files.py` | Ausgabeziel (`out_dir`), Pfadprüfung `inside_out`, Sperrdateien, `busy_reason`, Datei-API (`/api/files`, `/api/download`) | P0 |
| `makemkv.py` | `makemkvcon`-Aufruf und Robot-Parser, Beta-Key | P0 |
| `drives.py` | Laufwerke (ioctl), Analyse, Auswerfen, Poller | P0 |
| `rip.py` | Rippen/Backup in den Zwischenspeicher, Rip-Hooks | P0 |
| `upload.py` | Zwischenspeicher und Übertragung ins Ziel, Upload-Hooks | P0 |
| `ffmpeg.py` | ffmpeg/ffprobe: Argumente, Fortschritt, Segmente, Pause | PF |
| `convert.py` | Konvertierung: Warteschlange, Worker, Abbrechen/Überspringen, `clean_convert` | PF |
| `library.py` | Bibliothek: Scan, Cache, nachträglich konvertieren, Umbenennen | PF |
| `cluster.py` | andere Rechner abfragen, Proxy `/api/peer/…`, Übergabe | PC |

Abhängigkeiten laufen von unten nach oben (`ext`/`config`/`util` → `state` → `files`/`makemkv` → `drives`/`upload`/`ffmpeg` → `convert` → `rip`/`library`/`cluster`). Wo zwei Module sich gegenseitig brauchen (`upload` ↔ `convert` ↔ `cluster`), importiert das jüngere das andere als Modul (`from app import convert`) und ruft zur Laufzeit `convert.x()` auf, nie `from app.convert import x` im Kreis.

### Frontend (`app/static/`, kein Build)
- `index.html` Gerüst (Kopfzeile, `#banners`, `#views`, Platzhalter `<!--ASSETS-->`; PB).
- `css/*.css`: `base` (Grundlagen) · `layout` · `components` · `shell` (PB) · `jobs` (PA) · `library` (PF); **jede weitere `*.css` wird vom Server automatisch eingebunden** (alphabetisch nach den genannten).
- `js/*.js`: native ES-Module. **Jede `js/<name>.js` wird automatisch geladen** (Reihenfolge der Kernmodule siehe `JS_ORDER` in `ui.py`, weitere alphabetisch). Ein Modul meldet sich beim Import selbst an; `main.py`/`app.js` müssen dafür nicht angefasst werden.
- Gemeinsames: `core.js` (`$`, `esc`, `api`, `toast`, `setHtml`, `S`, `ui`, `delegate`, Verbindung) und `registry.js` (alle Erweiterungspunkte).
- Besitz: `drives.js`/`titles.js`/`jobs.js`/`logs.js` PA · `nav.js`/`settings.js` PB · `handover.js` PC · `files.js`/`core.js`/`registry.js`/`app.js` P0/PZ · `library.js`/`cvform.js` PF (`cvform.js` wird durch `convert-editor.js` ersetzt).
- Ausgeliefert wird mit `Cache-Control: no-cache` (ETag): Browser holen nach einem Update neu, nichts wird gemischt.

## 2. Backend-Erweiterungspunkte (`from app import ext`)
Dein Modul wird **automatisch geladen**, wenn es einen der Namen in `OPTIONAL_MODULES` (`main.py`) trägt: `app.nodes`, `app.player`, `app.media` (Paket mit `__init__.py`), `app.convert_presets`. Beim Import registrierst du alles. Fehlt das Modul, wird es übersprungen; ein Fehler darin bricht den Start ab.

| Aufruf | Zweck |
|---|---|
| `ext.register_router(router)` | eigener `APIRouter` (Präfix laut AUFTRAG 4.3, z. B. `/api/player`) |
| `ext.register_settings(ns, Model, defaults, secret=(), on_change=None)` | Einstellungs-Namensraum (s. 4) |
| `ext.register_snapshot(key, fn)` | `fn()` landet in jeder Statusmeldung unter `key` (schnell, JSON-fähig, kein Netzwerk) |
| `ext.register_capability(name, value)` | Fähigkeit dieses Rechners, sichtbar im Verbund (`/api/state` → `capabilities`) |
| `ext.register_startup(async_fn)` | Hintergrundaufgabe, startet nach dem Laden der Einstellungen |
| `ext.register_rip_hook(fn)` | nach jedem fertig gerippten Titel (sync oder async) |
| `ext.register_upload_hook(fn)` | nach jeder ins Ziel übertragenen Datei (sync oder async) |
| `ext.allow_proxy(regex)` | erlaubt `POST /api/peer/{name}/<pfad>` für Pfade (ohne `/api/`), die vollständig passen |

Fehler in Hooks und Snapshot-Funktionen werden protokolliert und stören nichts anderes.

Rip-Hook: `info = {dev, disc, title, rel, folder, file, mode, converting}` (`disc` = Name/Typ/Volume/alle Titel wie in `/api/state`; `title` = der gerippte Titel mit `id`, `name`, `duration`, `bytes`, `chapters`, `tracks`; `rel` = Zielpfad im Ausgabeordner, wie ihn die Übertragung anfragt; `file` = Datei im Zwischenspeicher; `converting` = geht erst noch durch die Konvertierung). Upload-Hook: `item["name"]` ist der angefragte Pfad (= `rel`), `item["dest"]` der echte (kann wegen `unique_path` abweichen).

Beispiel (`app/player.py`):
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

Nützliche vorhandene Hilfen: `files.out_dir()`, `files.inside_out(rel)` (Pfadausbruch → 400), `files.busy_reason(rel, is_dir, abs)`, `files.acquire_lock/release_lock`, `state.broadcast()`, `state.settings`.

## 3. Frontend-Erweiterungspunkte (`import … from './registry.js'`)
```js
registerView({id, label, icon, order, hash?, mount(el), unmount()})   // Ansicht; Route #/<hash|id>; erscheint automatisch im Menü
registerPanel({view, slot, order, id, html})                           // Feld in einer Zwei-Spalten-Ansicht ('laufwerke'): slot 'left' | 'right' | 'bottom'
registerSettingsSection({id, label, order, render(el, settings), collect()})   // collect() liefert {namespace: {...}}
registerLibraryAction({id, label, icon, primary?, when(files), run(files)})    // Datei-Aktion in der Bibliothek; primary = Klick auf den Dateinamen
onState(fn)                                                            // fn(S) bei jeder Statusmeldung
on(evt, fn) / emit(evt, data)                                          // Ereignisse: 'view' (neue Ansicht), 'files-changed', 'conn' (Verbindung), 'settings:open'
navigate(id)                                                           // zu einer Ansicht wechseln (setzt den Hash)
```
- `mount(el)` läuft bei **jedem** Aktivieren; der Container bleibt bestehen (Inhalt nur beim ersten Mal aufbauen, z. B. `if(el.dataset.built) return`). `unmount()` beim Verlassen. Nach `mount` werden alle `onState`-Funktionen mit dem letzten Status erneut aufgerufen.
- `registerPanel`: `html` ist ein komplettes `<section class="panel" id="…">`. Das Feld existiert erst, wenn die Ansicht zum ersten Mal angezeigt wird: Renderfunktionen müssen `if(!$('#meinfeld')) return;` prüfen. Ereignisse an solche Elemente mit `delegate('#meinfeld', 'click', (e, root) => …)` (aus `core.js`) hängen.
- Zugriff auf den Status: `import { S } from './core.js'` (live gebunden). Zustand der Oberfläche: `ui` (`core.js`). Drittmodule sollten `drives.js`-Funktionen (`curDrive`, `allDrives`, `driveUrl`) wiederverwenden, statt Laufwerke selbst zu suchen.
- Bibliothek: `when(files)` bekommt die betroffenen Dateien (`{path, size, mtime, state, info, job, locked}`), `run(files)` führt aus. Heute rendert `library.js` Zeilen-Knöpfe und die primäre Aktion am Dateinamen; Auswahl-Aktionen (mehrere Dateien) ergänzt PF in `library.js`.
- Einstellungen: bis PB die Seite baut, rendert `settings.js` alle Abschnitte untereinander im Dialog; `collect()` wird beim Speichern aufgerufen.

Beispiel (`js/player.js`):
```js
import { registerLibraryAction } from './registry.js';
registerLibraryAction({id:'play', label:'Abspielen', icon:'▶', primary:true,
  when: fs => fs.length === 1 && /\.(mkv|mp4)$/i.test(fs[0].path), run: fs => openPlayer(fs[0].path)});
```

## 4. Einstellungen mit Namensräumen
- `GET /api/settings` und `POST /api/settings`. Flache Felder (`minlength`, `auto_eject`, …) gehören zum Namensraum `general` und gelten weiter; zusätzlich geht `{"general": {...}}`. Erweiterungen: `{"media": {"movies_dir": "…"}}`. In `config.json` liegen sie verschachtelt.
- `ext.register_settings("media", MediaSettings, {"movies_dir": ""}, secret=("tmdb_key",))`. Der Wert steht danach in `state.settings["media"]` (validiert, mit Vorgaben aufgefüllt). Beim POST wird mit dem vorhandenen Wert **zusammengeführt** und mit dem Modell geprüft (Fehler → 422).
- `secret`: Diese Felder erscheinen **nicht** in `/api/state` (geht auch an andere Rechner!) und `GET /api/settings`, nur `<feld>_set: true`. Beim POST heißt `null`/fehlend „unverändert“, `""` „löschen“.
- `on_change(alt, neu)` (sync oder async) läuft nach dem Ändern.
- Unbekannte Namensräume in `config.json` (Modul fehlt gerade) bleiben beim Speichern erhalten.

## 5. Verbund und Abwärtskompatibilität
- `/api/state` meldet `capabilities` (`version`, `features`, plus alles, was Module registrieren). Ältere Rechner (z. B. secondtux) haben das Feld nicht: `peers[i].capabilities` ist dann `{}`; auf Fähigkeiten nur mit Vorbehalt vertrauen und im Zweifel ausgrauen.
- Bestehende Endpunkte, Pfade und Antwortformen bleiben (AUFTRAG 4.3). Felder nur hinzufügen.
- Neue Endpunkte, die im Verbund erreichbar sein sollen: `ext.allow_proxy(...)` im eigenen Modul.

## 6. Entwicklung und Test (`scripts/dev.sh`)
- `scripts/dev.sh` startet eine Instanz auf http://127.0.0.1:8790 (Name `dev-a`), `scripts/dev.sh pair` zwei (8790/8791) im Verbund, `stop`/`status`, `--port`, `--name`, `--peers`, `--bg`, `--reset`. Daten in `$TMPDIR/makemkv-web-dev/` (`MKW_DEV_DIR` ändert das); **nie das echte NAS**.
- Das „NAS“ (`output/`) wird mit Beispieldateien gefüllt (Film H.264+AC3 mit Untertitel und Kapiteln, Serien-Disc „The Walking Dead – Disc 1“ mit fünf Episoden und Play-All-Titel, HEVC 10-bit, MPEG-2-DVD, Ordner mit Umlauten).
- Attrappen-Laufwerk `sr0` (Datei in `<name>/drives/`) mit Attrappe `makemkvcon` (`scripts/dev-bin`): Disc wird „analysiert“, Rippen/Backup laufen in Sekunden und erzeugen winzige Dateien. `scripts/dev.sh disc --name dev-a ready|empty|open` legt Disc ein/entfernt sie/öffnet die Schublade. Eigene Disc: `<name>/drives/sr0.json` (`type`, `name`, `volume`, `titles[{name,secs,bytes,chapters}]`).
- Im Browser prüfen: Desktop (1440) und Handy (375), Konsole ohne Fehler.

## 7. Module der Pakete (Phase 2)
| Paket | Backend | Oberfläche | Schnittstelle nach außen |
|---|---|---|---|
| PA UI-Feinschliff | – | `jobs.js`, `jobs-list.js` (stabile Zeilen), `logs.js`, `drives.js`, `titles.js`, `css/jobs.css`, `css/titles.css` | Titelliste bettet `mountConvertEditor(…, {mode:'compact'})` ein |
| PB Navigation, Einstellungen | – | `nav.js`, `settings.js`, `settings-general.js`, `css/shell.css` | Reiter aus `getViews()`; Einstellungen `#/einstellungen/<abschnitt>` mit Speichern je Abschnitt; Ereignisse `route`, `settings:dirty` |
| PC Rechner | `nodes*.py`, `cluster.py` | `nodes*.js`, `css/nodes.css` | `DATA/nodes.json`, Token-Kopplung, Suche im /24, `peers[i].legacy/trust/version`; `cluster.cfg_for_peer(cfg, peer)` für Übergaben |
| PD Player | `player.py`, `player_probe.py`, `player_stream.py` | `player*.js`, `css/player.css` | `/api/player/*`; `openPlayer(path)` (Überlagerung), `mountPlayer(el, path, {compact})` (eingebettet); Entscheidung direkt/Remux/Transcode, ffmpeg-Neustart beim Springen (kein HLS) |
| PE Jellyfin-Ablage | `app/media/*` | `media*.js`, `css/media.css` | `/api/media/*` (u. a. `POST /api/media/infos`); Bibliotheksaktion „Einsortieren“; Ordner-Vorbelegung aus `OUTPUT_MOUNT` |
| PF Konvertierung, Bibliothek | `convert_schema.py` (Schema v2, v1 bleibt gültig), `ffmpeg_args.py`, `convert_caps.py`, `convert_stats.py`, `convert_builtin.py`, `convert_presets.py`, `convert_probe.py`, `library_info.py` | `convert-*.js`, `library*.js`, `css/convert.css`, `css/library.css` | `/api/convert/*` (meta, estimate, start, Presets, Probe); `capabilities.convert`; `mountConvertEditor(el, value, {target, onChange, mode:'full'\|'compact'\|'side', discKind, files, readonly})` → `{get, set, setFiles, refresh, destroy}`; Bibliotheksaktionen mit `ctx.where` = `row`/`detail`/`bar`/`folder` |

Verbund und Konvertierung: Eine Übergabe prüft vorher `convert_caps.peer_ok`. Rechner mit altem Stand bekommen nur die fünf alten Felder (`convert_schema.to_v1`), und das nur, wenn sich der Auftrag so ausdrücken lässt; sonst bleibt der Auftrag hier und der Grund wird gemeldet. Konvertierte Dateien tragen im Container `MKW_CONVERTED`; „konvertiert“ in der Bibliothek heißt dieses Kennzeichen oder HEVC/AV1.

Tests: `python3 -m unittest discover -s tests -t .` (die gemeinsame Umgebung setzt `tests/__init__.py`).

## 8. Bekannte Einschränkungen
- Dauer-Vorhersagen sind ohne Statistik Schätzungen und werden mit jeder fertigen Konvertierung genauer.
- Hardware-Encoding (VAAPI), HDR→SDR (`zscale`) und echte Dolby-Vision-Dateien sind nur auf Backend-Ebene getestet, nicht mit echter Hardware/Quelle.
- Container Queries brauchen Safari 16+ bzw. Firefox 110+.
- (behoben durch PF: `convert.ensure_conv_workers()` startete nie weitere Worker.)
