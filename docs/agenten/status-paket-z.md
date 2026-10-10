# Status PZ (Zusammenführung, Gesamttest, Ausrollen) – Stand 2026-10-10

Nichts ist gepusht, nichts ist auf maintux, vierstein oder secondtux ausgerollt. Ausrollen erst nach ausdrücklicher Freigabe.

## Zusammengeführt
Branch `paket-z` = `main` + `paket-a` … `paket-f` (PF zuletzt, Stand `2e3fe50`). Einziger Konflikt: `files.js` (PB gegen PD), aufgelöst: Abspielen am Dateinamen, kein Knopf „Nachträglich konvertieren“ mehr (die Bibliothek ersetzt ihn).

## Eigene Änderungen in PZ
- Titelliste (`titles.js`) bettet `mountConvertEditor(…, {mode:'compact'})` ein (PA hätte es tun sollen), `cvform.js` entfernt. Der Rip bekommt die v2-Einstellung.
- Übergabe an andere Rechner (`cluster.cfg_for_peer`): prüft `convert_caps.peer_ok`; alte Rechner bekommen nur die fünf alten Felder (`to_v1`), und nur wenn sich der Auftrag so ausdrücken lässt, sonst Grund in der Fehlerliste. Gilt für `/api/handover`, die Übergabe nach dem Hochladen und `/api/convert/start`.
- **Fehler behoben:** `/api/convert/start` auf einen anderen Rechner lieferte 500 (async `peer_call` über `asyncio.to_thread` aufgerufen, Coroutine kam zurück). Regressionstest in `tests/test_handover_caps.py`.
- `core.js`: 422-Antworten (Liste von Fehlerobjekten) werden lesbar angezeigt statt „[object Object]“.
- `main.py`: `peer_prober` startet immer (auch ohne `PEERS`, denn die Rechnerliste kann später gefüllt werden).
- `scripts/dev.sh`: sucht ein Python ab 3.10.
- Medien-Ordner (PE): Vorbelegung `OUTPUT_MOUNT/Filme` und `/Serien` statt festem `/mnt/datenstein/…` (im Container heißt das NAS wie `NAS_MOUNT` in der `.env`).
- Dockerfile: `intel-media-va-driver` und `vainfo` (Hardware-Encoding, i5-7300U nur 8-Bit-HEVC). Compose: `group_add` um `RENDER_GID`, Gerätregel `c 226:*` (`/dev/dri`); `.env.example` und `install.sh` kennen `RENDER_GID`. Bestehende `.env`-Dateien ohne `RENDER_GID` laufen weiter (Standard 105).
- Handy (375 px): Einstellungen liefen bei „Konvertierung & Presets“ über (Grid-Spalten `1fr` → `minmax(0,1fr)`, `shell.css`); Auswahlleiste der Bibliothek war zu breit und verdeckte die Reiterleiste (`library.css`); der Editor scrollt beim Öffnen ins Bild (`library.js`).
- Tests: `tests/__init__.py` setzt die gemeinsame Umgebung (vorher scheiterten 15 Tests nur im gemeinsamen Lauf).
- Doku: `schnittstellen.md` (§7 Module der Pakete, §8 Einschränkungen), README.

## Geprüft (lokal, `scripts/dev.sh`, Browser)
- Drei Instanzen: zwei neue im Verbund (8900/8901) und eine auf dem alten Stand `ae4603e` (8902, als „secondtux“). Die alte erscheint als erreichbar/`legacy`; in der Bibliothek ist sie für angepasste Aufträge ausgegraut mit Grund und mit „Blu-ray optimal“ wählbar.
- Konvertierung von 8900 auf die alte Instanz (fünf Felder, fertig, HEVC 10-bit) und auf die neue (x264, fertig, H.264); x264 an die alte wird mit 409 und Begründung abgelehnt.
- Alle Ansichten und alle Einstellungsabschnitte bei Desktop und 375 px ohne waagerechten Überlauf; Player (Remux, spielt); Einsortieren bis zum Plan (nicht ausgeführt); Titelliste mit Editor auf dem Handy.
- `python3 -m unittest discover -s tests -t .`: grün (9 übersprungen, ohne echte Medienquelle). `pyflakes` sauber (bis auf eine alte ungenutzte Variable in `upload.py`). Keine Datei über 400 Zeilen.

## Nicht geprüft / offen
- Voller Docker-Build mit MakeMKV-Stufe (verlangt `ACCEPT_EULA=yes`, nur mit Freigabe).
- Hardware-Encoding (VAAPI), HDR→SDR, echte Dolby-Vision-Datei, Probe-Kodierung mit einer echten Blu-ray-Datei, Safari/Firefox.
- Probe-Kodierung im Browser nur auf Backend-Ebene.

## Ausrollen (nach Freigabe)
1. `paket-z` nach `main` mergen (lokal), danach auf Wunsch pushen.
2. **maintux** (Git-Clone, kein sudo ohne Passwort): Zustand prüfen (`/api/state` ohne laufende Aufträge), `data/` und `.env` sichern, `git pull`, `docker compose up -d --build` (EULA über `.env`/`install.sh` wie bisher).
3. **vierstein** (kein Git-Repo, sudo ohne Passwort): Vorgehen klären (Klon neben `~/makemkv-web` oder rsync), gleiche Sicherung, Build und Neustart.
4. **secondtux** bleibt unberührt und erscheint im Verbund als alter Stand.
5. Rückweg: vorheriges Image/Commit zurück (`git checkout <alter Commit>`, `docker compose up -d --build`), `data/` und `.env` aus der Sicherung.
