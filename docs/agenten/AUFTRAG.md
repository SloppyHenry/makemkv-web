# MakeMKV-Web – Ausbau mit mehreren parallelen Agenten

> **Lies dieses Dokument vollständig, bevor du irgendetwas änderst.**
> Du bist **nicht allein**: Mehrere Claude-Agenten arbeiten **gleichzeitig** an diesem Tool, jeder an einem
> eigenen Arbeitspaket, jeder in einem eigenen Git-Worktree. Alles, was du tust, muss so gebaut sein, dass die
> anderen Pakete ungestört daneben entstehen und sich am Ende sauber zusammenführen lassen.

---

## 1. Das Projekt in Kürze

- Repo: `~/Projekte/makemkv-web` (GitHub `SloppyHenry/makemkv-web`, Branch `main`)
- Headless MakeMKV mit Browser-Oberfläche. Läuft per Docker Compose auf **vierstein** (`ssh vierstein`, User `henry`,
  `~/makemkv-web`, Port 8780, http://192.168.178.7:8780). Ausgabe auf das NFS von datenstein: `/mnt/datenstein/dump`.
- Mehrere Rechner bilden einen Verbund („Cluster“): Aufträge aller Rechner werden gemeinsam angezeigt, Konvertierungen
  können übergeben werden, fremde Laufwerke sind fernsteuerbar. Die Rechner kennen sich heute nur über die Umgebungsvariable
  `PEERS` (`name=http://host:8780,…`), Aufrufe laufen über `/api/peer/{name}/…` (Positivliste `PROXY_ERLAUBT`).
- Backend: `app/main.py` (FastAPI, `makemkvcon -r`, ffmpeg/x265, Server-Sent-Events, Sperrdateien gegen Doppelbearbeitung).
- Frontend: `app/index.html` – Single-Page-UI **ohne Build-Schritt** (das bleibt so: kein npm, kein Bundler).
- Sprache der Oberfläche, Kommentare und Commit-Nachrichten: **Deutsch**, Stil wie im bestehenden Code.
- Lies vor dem Start: `README.md`, `git log --oneline | head -30`, und die Status-Dateien der anderen Pakete (Abschnitt 4).

### 1.1 Rechner, auf denen das Tool läuft (Stand 2026-10-10)

| Rechner | Adresse | Installation | Hardware | Hinweise |
|---|---|---|---|---|
| **vierstein** | 192.168.178.7 (`ssh vierstein`) | `~/makemkv-web`, **kein Git**: Dateien wurden hineinkopiert, Stand = `main` ae4603e | 4 Kerne, 7 GB RAM, `/dev/dri/renderD128` | Hier hängt das BD-Laufwerk (MATSHITA BD-MLT UJ240AS, USB, trennt sich manchmal). `sudo` ohne Passwort. |
| **maintux** | 192.168.178.189, nur WLAN (`ssh maintux`) | `~/makemkv-web`, Git-Clone von GitHub, Stand ae4603e | Ryzen 5950X (32 Threads), 31 GB RAM, RTX 3080 | Starker Konvertier-Rechner. `sudo` **nur mit Passwort**: Befehle dafür gibt der Nutzer selbst ein. Docker hat **keine** NVIDIA-Runtime. Auf der GPU läuft außerdem ein llama.cpp-Server (Port 8080), daher NVENC nur nach Rücksprache. Staging auf `/mnt/SSD/makemkv-staging`. |
| **secondtux** | 192.168.178.160 | – | – | **Bleibt vorerst außen vor**: kein Ausrollen, kein Zugriff. Er steht aber in `PEERS` beider Rechner und kann jederzeit mit dem **alten Stand** wieder auftauchen. Alles muss mit einem alten Rechner im Verbund klarkommen. |

Alle Rechner schreiben in dasselbe NFS-Ziel `/mnt/datenstein/dump` (datenstein 192.168.178.4).

## 2. Was der Nutzer will (Gesamtbild)

1. Der Lade-/Arbeitskreis dreht sich nicht sauber.
2. Die Knöpfe rechts in der Auftragsliste passen sich nicht an, wenn das Fenster schmaler wird (der Text wird zu einer
   Wortspalte zerquetscht, siehe Screenshot: „Konverti / erung / 56 % · …“).
3. Kein Burger-Menü mehr, stattdessen eine saubere, sichtbare Navigation.
4. Die Protokoll-Karte gibt es auf der Hauptseite doppelt.
5. Rechnerverwaltung in den Einstellungen: Rechner manuell hinzufügen und Rechner automatisch finden. Ein Rechner ist
   nur auffindbar, wenn das dort in den Einstellungen eingeschaltet ist. Er kann auch eigenständig („standalone“) arbeiten.
6. In der Bibliothek auf Dateien klicken, dann spielt ein interner Player sie ab.
7. Fertige Dateien in einen Filme- oder Serien-Ordner verschieben. Ordner, Unterordner und Dateien werden dabei
   automatisch nach dem Jellyfin-Schema benannt. Das Tool versucht zuerst selbst zu erkennen, um welches Medium es sich
   handelt; sonst fragt es nach Titel oder IMDb-ID und zeigt beim Titel Vorschläge an. In den Einstellungen lässt sich
   festlegen: Filme-Ordner, Serien-Ordner, und ob nach Jellyfin umbenannt oder nur unverändert kopiert/verschoben wird.
8. Mehr Möglichkeiten für die MKV-Konvertierung: fertige, optimale Presets für DVD und Blu-ray, und darüber hinaus Codec,
   Qualität usw. selbst wählen. Dafür eine gute Darstellung finden. Die Bibliotheksübersicht darf dafür komplett
   umgebaut werden. Zuerst ein Mockup.
9. **Am wichtigsten:** Am Ende läuft alles auf den Rechnern im Verbund. Jetzt sind das **maintux und vierstein**;
   secondtux bleibt vorerst außen vor (siehe 1.1).

## 3. Phasen und Pakete

```
Phase 1 (allein, zuerst):  P0  Fundament – Aufteilen in Module, Erweiterungspunkte, Dev-Umgebung
Phase 2 (parallel):        PA  UI-Feinschliff (Kreis, responsive Aufträge, ein Protokoll)
                           PB  Navigation + Einstellungsseite (Rahmen)
                           PC  Rechnerverwaltung + automatische Erkennung
                           PD  Interner Player
                           PE  Jellyfin-Ablage (Erkennen, Metadaten, Benennen, Verschieben)
                           PF  Konvertierungs-Einstellungen + neue Bibliothek
Phase 3 (allein, zuletzt): PZ  Integration, Gesamttest, Ausrollen auf maintux + vierstein
```

Phase 2 startet erst, wenn P0 auf `main` gemergt ist. Bis dahin arbeitet kein anderer Agent am Code.

---

## 4. Spielregeln für alle Agenten (verbindlich)

### 4.1 Git und Worktrees
- Jeder Agent arbeitet in **seinem eigenen Worktree** auf **seinem eigenen Branch**, nie direkt im Hauptordner:
  ```bash
  git -C ~/Projekte/makemkv-web worktree add ~/Projekte/makemkv-web-wt/<paket> -b <paket> main
  ```
  `<paket>` ist `paket-a`, `paket-b`, … Gibt es den Worktree schon, arbeite dort weiter.
- Kleine, in sich fertige Commits mit deutscher Nachricht im Stil des bestehenden `git log`.
- **Nicht pushen, nicht auf `main` mergen.** Die Zusammenführung macht PZ oder der Nutzer. Ausnahme: P0 wird vom
  Nutzer freigegeben und dann auf `main` gemergt.
- Hole regelmäßig den Stand von `main` (`git rebase main`), vor allem bevor du dein Paket als fertig meldest.

### 4.2 Dateien und Zuständigkeiten
- Jedes Paket **besitzt** bestimmte Dateien (Tabelle in Abschnitt 6). Nur der Besitzer ändert sie.
- Brauchst du eine Änderung in einer fremden Datei, mach sie **nicht selbst**. Trag sie in deine Status-Datei unter
  „Brauche von anderen“ ein und benachrichtige den Besitzer (4.4). Ausnahme: eine einzelne Zeile, mit der du dein Modul
  an einem Erweiterungspunkt von P0 anmeldest (Import und Registrierung in `app/main.py` bzw. `app/static/js/app.js`).
  Solche Ein-Zeilen-Änderungen sind erlaubt und konfliktarm.
- Neue Funktionen kommen in **neue Dateien** des eigenen Pakets, nicht in bestehende fremde Module.

### 4.3 Namensräume (damit nichts kollidiert)
| Paket | API-Präfix | Einstellungs-Namensraum | CSS-Präfix | Frontend-Modul |
|---|---|---|---|---|
| PA | – (bestehende) | – | `.job…`, `.log…` | `js/jobs.js`, `js/logs.js` |
| PB | – | `general` (übernimmt die heutigen Felder) | `.nav…`, `.page…`, `.set…` | `js/nav.js`, `js/settings.js` |
| PC | `/api/nodes/…`, `/api/discovery/…` | `nodes` | `.node…` | `js/nodes.js` |
| PD | `/api/player/…` | `player` | `.player…` | `js/player.js` |
| PE | `/api/media/…` | `media` | `.media…` | `js/media.js` |
| PF | `/api/convert/…`, `/api/library/…` (bestehende bleiben) | `convert` (übernimmt `presets`, `conv_*`) | `.cv…`, `.lib…` | `js/convert-editor.js`, `js/library.js` |

- Bestehende Endpunkte behalten ihre Pfade und Antwortformen, weil ältere Instanzen im Verbund sie während des Ausrollens
  weiter aufrufen. Felder kommen nur **dazu**, umbenannt oder entfernt wird nichts.
- Was im Verbund erreichbar sein soll, meldest du über den Proxy-Erweiterungspunkt von P0 an. Das alte `PROXY_ERLAUBT`
  wird nicht direkt bearbeitet.

### 4.4 Voneinander wissen
- Jedes Paket führt **`docs/agenten/status-<paket>.md`** in seinem Worktree, nur das eigene Paket schreibt diese Datei.
  Halte sie nach jedem Meilenstein aktuell:
  ```markdown
  # Status <Paket> – Stand <Datum Uhrzeit>
  ## Erledigt
  ## In Arbeit
  ## Angebotene Schnittstellen   (Endpunkte mit Beispiel-JSON, JS-Funktionen, Events, Einstellungsschlüssel)
  ## Brauche von anderen         (wer, was, warum – mit Status: offen/erledigt)
  ## Fremde Dateien angefasst    (sollte leer sein, sonst begründen)
  ## Fragen an den Nutzer
  ```
- **Lies vor jedem größeren Schritt die Status-Dateien der anderen** unter
  `~/Projekte/makemkv-web-wt/paket-*/docs/agenten/status-*.md`. So erfährst du, was es schon gibt und was geplant ist.
  Baue nichts doppelt, was ein anderes Paket anbietet. Nutze dessen Schnittstelle (vorerst gegen eine Attrappe, falls es
  sie noch nicht gibt).
- Hast du die Werkzeuge `ListAgents`/`SendMessage`, schreib den betroffenen Agenten bei Schnittstellenfragen direkt an,
  knapp und mit Verweis auf die Status-Datei. Sonst: Eintrag unter „Brauche von anderen“ und den Nutzer darauf hinweisen.
- Ändert sich eine Schnittstelle, die ein anderes Paket nutzt: zuerst in der Status-Datei ankündigen, dann ändern.

### 4.5 Arbeitsweise
- **Erst Mockup, dann bauen** (ausdrückliche Vorgabe des Nutzers): Jedes Paket mit sichtbarer neuer Oberfläche
  (PB, PC, PD, PE, PF) legt zuerst ein statisches Mockup als `docs/mockups/<paket>.html` an. Es nutzt dieselben Farben und
  Komponenten wie die App. Zeig es dem Nutzer und **warte auf Freigabe**. Backend-Arbeit darf in der Zeit weiterlaufen.
  Freigegebene Mockups werden **1:1** umgesetzt. Was nicht geht, wird vorher genannt und nicht stillschweigend weggelassen.
- **Im Browser prüfen**, nicht nur per `curl`: lokal mit `scripts/dev.sh` (von P0) starten, im eingebauten Browser
  öffnen und Desktop- sowie Handybreite (375 px) ansehen. Eine Konsole ohne Fehler ist Pflicht.
- Auf vierstein, maintux oder secondtux **nichts ausrollen** und dort keine Container neu starten. Dort laufen echte
  Rips und Konvertierungen. Das macht nur PZ, nach Rückfrage. Nur lesende Abfragen (z. B. `ffmpeg -encoders`,
  `/api/state`) sind erlaubt, wenn du Hardware-Fähigkeiten oder echte Daten kennen musst.
- **Abwärtskompatibilität im Verbund ist Pflicht:** Neue Rechner müssen mit Rechnern auf dem alten Stand (secondtux!)
  zusammenarbeiten. Fehlt einem Rechner eine Fähigkeit, wird er in der Oberfläche dafür ausgegraut, nicht mit falschen
  Daten bedient. Jeder Rechner meldet seine Fähigkeiten (Version, Codecs, Features) in `/api/state`.
- Am NAS (`/mnt/datenstein/…`) **nichts löschen, verschieben oder umbenennen**, solange du entwickelst. Getestet wird mit
  den Beispieldateien aus `scripts/dev.sh` in einem temporären Ordner.
- Echte Fragen an den Nutzer (Geschmack, Datenschutz, API-Schlüssel) stellen statt raten. Alles andere selbst
  entscheiden und die Entscheidung in der Status-Datei begründen.
- Fertig heißt: Funktion im Browser geprüft, `python -m py_compile` sauber, Status-Datei aktuell, Branch auf `main`
  rebased, kurze Zusammenfassung an den Nutzer mit dem, was er selbst testen sollte.

---

## 5. Die Arbeitspakete

### P0 – Fundament (Phase 1, ein Agent, vor allen anderen)

**Ziel:** Den Code so aufteilen, dass fünf Agenten parallel arbeiten können, ohne sich ständig dieselben zwei Dateien zu
zerschießen. **Keine sichtbare Verhaltensänderung.** Nach P0 muss die App exakt so funktionieren wie vorher.

1. **Backend aufteilen** in ein Paket `app/` mit Modulen, z. B. `config.py` (Umgebung, Pfade, `DEFAULTS`),
   `state.py` (Laufzeitstatus, `broadcast`, `snapshot`), `drives.py`, `rip.py`, `convert.py`, `upload.py`, `library.py`,
   `cluster.py` (heutige Peers, Proxy, Übergabe), `settings.py`, `files.py`. `main.py` erzeugt nur noch die App, bindet die
   Router ein und startet die Hintergrundaufgaben. Reines Verschieben, keine Logik umschreiben.
2. **Erweiterungspunkte** schaffen und dokumentieren:
   - `register_router(router)`: neue Module bringen einen eigenen `APIRouter` mit.
   - `register_settings(namespace, PydanticModel, defaults)`: `GET/POST /api/settings` akzeptiert verschachtelte
     Namensräume (`{"media": {...}}`). Die heutigen flachen Felder bleiben weiter gültig, sie gehören zu `general`.
   - `register_snapshot(key, fn)`: Module hängen eigene Daten an `/api/state` bzw. die SSE-Nachricht an, ohne
     `snapshot()` anzufassen.
   - `allow_proxy(regex)`: ersetzt das direkte Bearbeiten von `PROXY_ERLAUBT`.
   - `register_startup(coro)`: Hintergrundaufgaben eines Moduls.
3. **Frontend aufteilen:** `app/static/index.html` (Gerüst), `app/static/css/{base,layout,components}.css`,
   `app/static/js/` als native ES-Module (`<script type="module">`, kein Build): `core.js` (`$`, `api`, `esc`, `toast`,
   `setHtml`, SSE-Verbindung, globaler Status `S`), `drives.js`, `titles.js`, `jobs.js`, `logs.js`, `library.js`,
   `handover.js`, `settings.js`, `app.js` (lädt und registriert die Module). Statische Dateien über FastAPI ausliefern.
   Auf No-Cache bzw. Versionsparameter achten, damit Browser nach dem Ausrollen keine alten Module mischen.
4. **Frontend-Erweiterungspunkte:**
   - `registerView({id, label, icon, order, mount(el), unmount()})` mit Hash-Routing (`#/laufwerke`, `#/bibliothek`,
     `#/einstellungen`, …). Zurück-Taste und Neuladen behalten die Ansicht. Das heutige Burger-Menü bleibt **vorerst**
     als Darstellung bestehen, PB ersetzt es.
   - `registerSettingsSection({id, label, order, render(el, settings), collect() -> {namespace: {...}}})`.
   - `onState(fn)`: Abonnement auf Statusänderungen statt direkter Aufrufe aus `render()`.
   - `registerLibraryAction({id, label, icon, primary?, when(files), run(files)})`: Aktionen für Dateien in der
     Bibliothek (Abspielen von PD, Einsortieren von PE, Konvertieren von PF). So muss niemand außer PF `library.js`
     anfassen. `primary: true` heißt: Klick auf den Dateinamen löst diese Aktion aus (PD: Abspielen).
   - Backend: `register_rip_hook(fn)` (wird nach jedem fertigen Titel mit Disc-Infos aufgerufen, für PE) und
     `register_capability(name, value)` (landet in `/api/state` unter `capabilities`, für Verbund-Prüfungen).
5. **Dev-Umgebung** `scripts/dev.sh`: startet die App lokal auf dem Mac (uvicorn) mit `DATA_DIR`/`OUTPUT_DIR` in einem
   temporären Ordner und erzeugt per ffmpeg Beispieldateien, z. B. einen 2-min-Film H.264+AC3,
   `The Walking Dead - Disc 1 - Titel 01…05` mit Episodenlänge, eine HEVC-10-bit-Datei und einen Ordner mit Umlauten.
   Optional `--port`/`--name`, damit sich zwei Instanzen nebeneinander starten lassen (braucht PC zum Testen des Verbunds).
6. `docs/agenten/AUFTRAG.md` (diese Datei) mit committen, `docs/agenten/schnittstellen.md` mit der Beschreibung aller
   Erweiterungspunkte samt Beispiel anlegen.
7. Prüfen: Alle bestehenden Endpunkte antworten gleich (vorher/nachher-Vergleich von `/api/state` und `/api/library`
   gegen die Dev-Instanz), Oberfläche im Browser durchklicken, Docker-Image baut (`docker build .`).

**Übergabe:** Status-Datei und eine Nachricht an den Nutzer, dass P0 auf `main` gemergt werden kann und Phase 2 startet.

---

### PA – UI-Feinschliff

**Besitzt:** `js/jobs.js`, `js/logs.js`, `css/` Teile für Aufträge/Protokoll (eigene Datei `css/jobs.css` anlegen).

1. **Drehender Kreis (`.status-check.run`) ruckelt.** Ursache ist schon gefunden: `renderJob()` baut die ganze Liste per
   `setHtml()` neu, sobald sich Prozent, fps oder Restzeit ändern, also mehrmals pro Sekunde. Dabei wird das
   Kreis-Element neu erzeugt und die CSS-Animation beginnt jedes Mal wieder bei 0°. Lösung: Aufträge **schlüsselweise**
   aktualisieren (ein stabiles DOM-Element pro Auftrag, nur Text, Balkenbreite und Knöpfe ändern). Als zusätzliche
   Absicherung die Phase an die Uhr koppeln (`animation-delay: -(Date.now() % 1000)ms`). Alle anderen drehenden oder
   laufenden Elemente gleich prüfen: unbestimmter Fortschrittsbalken (`@keyframes ind`), Kreis im Fortschrittspanel,
   Spinner in der Bibliothek. Der Kreis muss kreisrund bleiben (`aspect-ratio`, `flex:none`) und darf bei Teilpixeln
   nicht eiern (gerade Größen, `box-sizing`).
2. **Auftragszeile responsiv.** Heute stehen Statuspille, „Überspringen“ und „Abbrechen“ starr rechts und quetschen den
   Text auf Wortbreite. Lösung mit **Container Queries** auf das Aufträge-Panel (die Breite hängt am Layout, nicht am
   Fenster): breit, dann alles in einer Zeile; mittel, dann Knöpfe unter den Text; schmal, dann Knöpfe als
   Symbol-Knöpfe oder in einem „⋯“-Menü. Statuspille an den Titel heften. Der Text darf nie unter ca. 180 px fallen.
   Prüfen bei 1440, 1280, 1050, 900, 700 und 375 px, auch mit Rechnernamen-Plakette und langen Dateinamen.
3. **Protokoll nur einmal.** Heute gibt es `#compactLog` („Protokoll anzeigen“, rechts) **und** `#fullLog` (unten).
   Nur eine Karte bleibt. Empfehlung: die untere, einklappbar; der Zustand wird gemerkt (localStorage mit try/catch). Ein
   neuer Fehler klappt sie auf bzw. zeigt eine Plakette. Stimm das kurz mit PB ab, falls PB das Protokoll als eigene
   Ansicht in der Navigation haben will.
4. Gefunden, kleiner: In der Titelliste schneidet die Plakette „Längster“ den Dateinamen ab („…Disc 1 – Tit“). Plakette
   neben die Nummer oder unter den Namen setzen. Die Titelliste gehört eigentlich zu P0/`titles.js`; nach P0 hat sie keinen
   Besitzer mehr, PA übernimmt sie.

---

### PB – Navigation und Einstellungsseite

**Besitzt:** `static/index.html` (Gerüst/Kopfzeile), `js/nav.js`, `js/settings.js`, `css/shell.css`.

1. **Burger-Menü (☰) und Zahnrad-Dialog ersetzen** durch eine sichtbare Navigation mit den Ansichten
   *Laufwerke · Bibliothek · Einstellungen* (weitere Ansichten melden sich über `registerView` an und erscheinen
   automatisch). Vorschlag zur Abstimmung im Mockup: Desktop mit Reitern in der Kopfzeile neben dem Logo (aktive Ansicht
   rot unterstrichen, Zahl laufender Aufträge als Plakette), Handy mit Tab-Leiste unten. Ein bis zwei Alternativen im
   Mockup zeigen, z. B. eine schmale Seitenleiste mit Symbolen.
2. Laufwerks-Chip(s) in der Kopfzeile so unterbringen, dass sie mit der Navigation nicht kollidieren (bei mehreren
   Laufwerken und Rechnern umbrechen bzw. als Auswahl zeigen).
3. **Einstellungen als eigene Seite** statt `<dialog>`: links Abschnittsliste, rechts Inhalt (auf dem Handy untereinander).
   Abschnitte kommen über `registerSettingsSection`. PB baut **Allgemein** (die heutigen Felder: Auto-Analyse,
   Auto-Auswerfen, Mindestlänge, Sprachen) und **MakeMKV-Key**. **Konvertierung & Presets** (PF), **Rechner** (PC) und
   **Medien/Jellyfin** (PE) sind Platzhalter, bis die Pakete liefern.
   Pro Abschnitt ein Speichern-Knopf; Hinweis bei ungespeicherten Änderungen.
4. Die Wege „Nachträglich konvertieren“ und „← Laufwerke“ werden durch die Navigation überflüssig und entfallen.
5. Tastatur und Barrierefreiheit: Reiter mit `role="tablist"`, Fokus sichtbar, Ansichten per Hash verlinkbar.

---

### PC – Rechnerverwaltung und automatische Erkennung

**Besitzt:** `app/nodes.py` (neu; ersetzt nach und nach die Peer-Teile in `cluster.py`, das PC nach P0 übernimmt),
`js/nodes.js`, `css/nodes.css`.

1. **Betriebsart** (Einstellung `nodes.mode`): `standalone` (keine anderen Rechner, keine Erkennung, Verbund-Elemente
   in der Oberfläche verschwinden) oder `verbund`. Zusätzlich `nodes.discoverable` (dieser Rechner antwortet auf
   Suchanfragen), Standard **aus**. Name dieses Rechners änderbar (Standard: `INSTANCE_NAME`).
2. **Rechnerliste** in `DATA/nodes.json` statt der Umgebungsvariable `PEERS`. Beim ersten Start werden vorhandene `PEERS`
   übernommen (Migration). `PEERS` wirkt danach nur noch als Vorbelegung. Anzeige je Rechner: Name, Adresse, online
   seit/zuletzt gesehen, Version, Laufwerke, Kerne/RAM, laufende Arbeit. Aktionen: hinzufügen (manuell per Adresse),
   umbenennen, entfernen, Verbindung testen.
3. **Automatisch finden:** Knopf „Rechner im Netz suchen“ und optional laufende Suche im Hintergrund.
   - Achtung Docker: Im Standard-Bridge-Netz kommen Multicast/Broadcast (mDNS, UDP) nicht in den Container. Entscheide
     und begründe: (a) mDNS `_makemkv-web._tcp` mit `network_mode: host` in `docker-compose.yml` (Änderung mit PZ
     abstimmen, weil sie Port-Mapping und Firewall betrifft) und/oder (b) als Rückfallebene ein aktiver Scan des eigenen
     /24-Netzes auf Port 8780 mit `GET /api/discovery/hello`. Variante (b) funktioniert auch im Bridge-Netz. Die Antwort
     enthält Name, Instanz-ID, Version, Fähigkeiten und ob gekoppelt werden darf.
   - Ein Rechner antwortet nur mit Details, wenn `discoverable` an ist; sonst `404`.
4. **Koppeln statt blind vertrauen:** A findet B, Klick auf „Verbinden“, B zeigt eine Anfrage („A möchte sich verbinden“)
   mit Bestätigung, dann tauschen beide ein gemeinsames Token aus. Alle Rechner-zu-Rechner-Aufrufe (Proxy, Übergabe,
   Status) tragen danach dieses Token. Das löst nebenbei das Problem, dass Peer-Aufrufe bei gesetztem `AUTH_PASS`
   scheitern würden. Manuell hinzugefügte Rechner durchlaufen dieselbe Kopplung. Entkoppeln löscht das Token auf beiden
   Seiten.
5. **Gemischte Versionen:** Während des Ausrollens laufen Rechner mit altem Stand. Alte Rechner (ohne `/api/discovery`)
   bleiben über die bisherige Peer-Logik nutzbar und werden als „ältere Version“ markiert.
6. Bestehende Funktionen (gemeinsame Aufträge, Übergabe, Fernsteuerung der Laufwerke, Konvertieren auf anderem Rechner)
   müssen danach auf der neuen Rechnerliste laufen. Die Felder in `/api/state` (`peers`, `reachable`, `has_handover`, …)
   bleiben erhalten.
7. Testen mit zwei lokalen Instanzen (`scripts/dev.sh --port 8781 --name test-b`), inklusive Kopplung, Entkopplung,
   Rechner offline und Rechner nicht auffindbar.

---

### PD – Interner Player

**Besitzt:** `app/player.py`, `js/player.js`, `css/player.css`. In die Bibliothek kommt der Player **nur** über
`registerLibraryAction({id:'play', primary:true, …})`. `library.js` gehört PF. PF baut die Bibliothek neu; stimmt
mit PF ab, wo der Player sitzt (Überlagerung oder im Detailbereich der neuen Bibliothek).

1. Klick auf eine Datei in der Bibliothek (und in „Fertige Dateien“) öffnet den Player in einer Überlagerung bzw. einem
   Seitenbereich: Wiedergabe/Pause, Suchen, Lautstärke, Vollbild, Tonspur- und Untertitelwahl, Kapitel (falls vorhanden),
   Tastenkürzel (Leertaste, ←/→, F, Esc).
2. **Das Kernproblem ist das Format, nicht die Oberfläche:** MKV mit HEVC 10-bit, VC-1/MPEG-2 (Blu-ray-Originale),
   AC3/DTS/TrueHD-Ton und PGS-Untertitel spielt kein Browser direkt ab. Plan:
   - `GET /api/player/probe?path=` liefert Codecs und Spuren und entscheidet: **direkt** (HTTP-Range auf die Datei, wenn
     der Browser es kann), **Remux** (Video kopieren, Ton nach AAC, als fragmentiertes MP4 streamen) oder **Transkodieren**
     (H.264 mit niedriger Auflösung/Bitrate, für VC-1/MPEG-2 oder wenn der Browser HEVC nicht kann). Der Browser meldet,
     was er kann (`MediaSource.isTypeSupported`/`canPlayType`, z. B. HEVC in Safari).
   - Suchen bei Remux/Transkodierung über einen Neustart von ffmpeg mit `-ss`, oder HLS-Segmente erzeugen und
     zwischenspeichern. Abwägen, entscheiden, begründen.
   - Textuntertitel nach WebVTT, Bilduntertitel (PGS/VobSub) zunächst nur als „nicht unterstützt“ anzeigen (optional
     einbrennen).
3. **Rücksicht auf die eigentliche Arbeit:** Transkodieren kostet CPU, während Rips und x265-Konvertierungen laufen.
   ffmpeg mit `nice`, höchstens ein gleichzeitiger Transkodier-Strom pro Rechner, Prozess sofort beenden, wenn der Player
   schließt oder die Verbindung abreißt. Optional: Wiedergabe von einem anderen Rechner im Verbund streamen lassen
   (Schnittstelle von PC verwenden).
4. Dateien mit Sperre (wird gerade konvertiert/ersetzt) trotzdem lesend abspielbar, aber mit Hinweis. Nur Pfade innerhalb
   des Ausgabeordners zulassen (vorhandenes `inside_out()` verwenden, Pfadausbruch testen).
5. Testen mit den Beispieldateien aus `scripts/dev.sh` in Safari-ähnlichem und Chrome-ähnlichem Verhalten.

---

### PE – Jellyfin-Ablage

**Besitzt:** `app/media/` (neu: `detect.py`, `metadata.py`, `naming.py`, `organize.py`), `js/media.js`, `css/media.css`.

1. **Einstellungen** (Namensraum `media`, Abschnitt „Medien / Jellyfin“ auf der Einstellungsseite von PB):
   - Filme-Ordner und Serien-Ordner (Auswahl mit Ordnerbrowser innerhalb des eingehängten Ziels, Prüfung auf
     Schreibrechte).
   - Benennung: `jellyfin` (umbenennen nach Schema) oder `unveraendert` (Dateien und Ordner bleiben, wie sie sind).
   - Aktion: `verschieben` (Standard) oder `kopieren`.
   - Metadatenquelle: TMDB-API-Schlüssel (Feld + „Testen“), Sprache für Titel (Standard `de-DE`), ID-Tags im Namen ja/nein.
   - Optional: Jellyfin-URL und API-Schlüssel, um nach dem Einsortieren einen Bibliotheks-Scan anzustoßen.
   - Optional: „Automatisch einsortieren, wenn eindeutig erkannt“ (Standard aus).
2. **Erkennen, was es ist** (`detect.py`), mit Trefferwahrscheinlichkeit:
   - Quellen: Disc-Name und Volume-Label (z. B. `The Walking Dead - Disc 1`, `WALKING_DEAD_S1_D1`), Dateiname und Ordner,
     Titelanzahl und Laufzeiten. Mehrere ähnlich lange Titel von 20–70 min deuten auf eine Serie, ein Haupttitel über
     70 min auf einen Film.
   - „Play-All“-Titel erkennen: Ein Titel, dessen Laufzeit etwa der Summe der Episoden entspricht (im Screenshot
     Titel 3 mit 3:21:55 bei 44-min-Episoden), wird als solcher markiert und nicht als Episode einsortiert.
   - Damit die Erkennung auch Tage später noch Material hat: Beim Rippen eine Begleitdatei mit Disc-Name, Label,
     Titelnummern, Laufzeiten und Kapiteln ablegen. Der Rip-Teil gehört nach P0 zu `rip.py`: PE meldet sich per Hook an
     (z. B. `register_rip_hook`) oder fragt P0/PZ nach dem Hook. Ablage unter `DATA/media/` mit Zuordnung über den Pfad,
     **nicht** als Fremddatei im NAS-Ordner, damit Jellyfin nicht stolpert.
3. **Metadaten** (`metadata.py`): TMDB-Suche nach Film und Serie mit Jahr, Vorschläge mit Poster-Vorschau, Jahr und
   Kurzbeschreibung. IMDb-ID (`tt1234567`) über TMDB `/find` auflösen. Ergebnisse zwischenspeichern. Ohne Schlüssel:
   keine Vorschläge, dann Titel und Jahr manuell, mit klarem Hinweis in der Oberfläche. Den Schlüssel liefert der Nutzer,
   **nicht** selbst einen besorgen oder fest einbauen.
4. **Benennen nach Jellyfin** (`naming.py`, mit Tests als reine Funktionen):
   - Film: `<Filme>/Titel (Jahr) [imdbid-tt…]/Titel (Jahr) [imdbid-tt…].mkv`. Mehrere Fassungen als
     `Titel (Jahr) - 1080p.mkv`; Extras in Unterordner wie `extras/`, `behind the scenes/`, `featurettes/`.
   - Serie: `<Serien>/Serie (Jahr) [tmdbid-…]/Season 01/Serie S01E01.mkv`; Specials in `Season 00`; Doppelfolgen
     `S01E01-E02`. Episodennamen optional anhängen (`S01E01 - Episodenname`).
   - Unzulässige Zeichen ersetzen (`: / \ ? * " < > |`), Umlaute behalten, Punkt/Leerzeichen am Ende entfernen.
   - Regeln gegen die aktuelle Jellyfin-Dokumentation zu Benennung von Filmen und Serien prüfen und Quelle in der
     Status-Datei vermerken.
5. **Episoden zuordnen:** Bei Serien-Discs Vorschlag aus Disc-Nummer und Titelreihenfolge (Disc 1 mit 4 Episoden ergibt
   E01–E04, Disc 2 macht weiter), mit Abgleich der Laufzeiten gegen TMDB. Der Stand pro Serie wird gemerkt. Der Nutzer
   kann in einer Tabelle Staffel und Episode je Datei korrigieren.
6. **Einsortieren** (`organize.py`): Aus der Bibliothek (Mehrfachauswahl oder Ordner) öffnet „In Filme/Serien
   einsortieren …“ (angemeldet über `registerLibraryAction`, nicht in `library.js` hineingeschrieben) einen Assistenten: erkannt → bestätigen oder suchen (Titel mit Vorschlägen bzw. IMDb-ID) → **Vorschau des
   Zielbaums** (alt → neu, Konflikte rot) → ausführen. Verschieben innerhalb desselben Dateisystems per Umbenennen,
   sonst kopieren, prüfen (Größe) und erst dann das Original entfernen. Vorhandene Sperrdateien beachten: Was gerade
   konvertiert, übertragen oder abgespielt wird, wird nicht angefasst (`busy_reason()` nutzen). Ziel existiert schon:
   nie überschreiben, nachfragen. Leere Quellordner danach aufräumen. Jede Aktion protokollieren, mit einer
   Rückgängig-Liste für die letzte Aktion.
7. Testen ausschließlich mit Beispieldateien und temporären Filme-/Serien-Ordnern (`scripts/dev.sh`), nie am NAS.
8. Abstimmung mit PF: In der neuen Bibliothek sollen Filme und Serien gruppiert erscheinen, wenn Metadaten vorliegen.
   PE bietet dafür `GET /api/media/info?path=` (Titel, Jahr, Art, Poster-URL, Staffel/Episode) an.

---

### PF – Konvertierungs-Einstellungen und neue Bibliothek

**Besitzt:** `app/convert.py` (nach P0), `app/library.py`, `app/convert_presets.py` (neu), `js/library.js`,
`js/convert-editor.js` (neu), `css/library.css`, `css/convert.css`, Einstellungsabschnitt „Konvertierung & Presets“.

**Ausgangslage:** Heute gibt es pro Disc-Art (bluray/dvd) ein gespeichertes Preset mit genau fünf Feldern:
`rf`, `preset`, `tune`, `extra` (x265-Parameter als Text), `audio`. Immer x265 10-bit, Segment-Modus für lange Filme,
automatisches Zuschneiden. Die Bibliothek ist eine Tabelle mit Ordnerbaum, Codec/Audio/Größe/Status und darüber einem
festen Konvertierungs-Block.

**Mockup zuerst, mit zwei Teilen und je mindestens zwei Varianten. Erst nach Freigabe bauen.**

#### Teil 1 – Konvertierung einstellen: Darstellung in drei Ebenen
1. **Preset-Karten** als Einstieg (eine Zeile wählbarer Karten). Mitgeliefert und nicht löschbar, mit kurzer Erklärung,
   wofür sie gedacht sind:
   - *DVD optimal*: Deinterlace/IVTC automatisch, leichtes Entrauschen, x265 RF ~19–20, Ton kopieren.
   - *Blu-ray optimal*: x265 10-bit, RF ~20–21, `slow`, `aq-mode=3`, Ton kopieren (heutiger Standard).
   - *Blu-ray Animation*: `tune=animation`, höheres RF möglich.
   - *Film mit starkem Korn*: `tune=grain` bzw. passende psy-rd/Deblock-Werte.
   - *UHD / HDR erhalten*: HDR10-Metadaten durchreichen, 10-bit Pflicht.
   - *Klein & schnell*: z. B. 1080p→720p, `faster`, Ton nach AAC/Opus Stereo.
   - Dazu eigene Presets des Nutzers (aus einer Anpassung „Als Preset speichern“), umbenennen und löschen.
   - Standard-Zuordnung: welches Preset automatisch für DVD bzw. Blu-ray vorgewählt wird.
   Die genauen Werte recherchieren und begründen (Encoder-Dokumentation, gängige Empfehlungen), nicht raten.
2. **Anpassen-Ansicht** (aufklappbar, ausgehend vom gewählten Preset; geänderte Werte markiert, „zurück auf Preset“):
   - **Video:** Codec als Segmentauswahl: *H.265/HEVC (x265)* · *H.264 (x264)* · *AV1 (SVT-AV1)* · *Hardware*
     (nur, wenn der Ziel-Rechner sie meldet, z. B. VAAPI/QSV auf `renderD128`) · *nicht konvertieren (nur remuxen)*.
     Bit-Tiefe 8/10.
   - **Qualität:** Regler mit verständlicher Skala („kleiner ← → besser“, Markierung „optisch verlustfrei“) statt nackter
     RF-Zahl, die Zahl daneben sichtbar. Alternativ Modus *Zielgröße* (GB) bzw. *Bitrate* mit 2-Pass. Die RF-Skala hängt
     vom Codec ab (CRF x264 ≠ x265 ≠ SVT-AV1 CRF), deshalb pro Codec auf die gleiche Wahrnehmungsskala abbilden.
   - **Geschwindigkeit:** Preset-Regler (ultrafast … veryslow bzw. SVT-Preset 0–13) mit Hinweis auf die Dauer.
   - **Bild:** Auflösung (beibehalten/1080p/720p), Zuschneiden (automatisch/aus/manuell), Deinterlace (auto/aus/an),
     Entrauschen (aus/leicht/mittel), HDR (erhalten/Tonemapping nach SDR).
   - **Ton:** pro Spur bzw. als Regel: kopieren / AAC / Opus / AC3, Kanäle (wie Quelle/5.1/Stereo-Downmix), Bitrate,
     Sprachfilter (verweist auf Allgemein-Einstellung).
   - **Untertitel:** alle behalten / nur erzwungene / nur Sprachen X / keine.
   - **Experten:** freie Encoder-Parameter (heutiges `extra`) und eine Anzeige des erzeugten ffmpeg-Befehls (nur lesen).
3. **Vorhersage, damit man Entscheidungen sieht:** geschätzte Zielgröße und Dauer pro Rechner, aus der Statistik
   bisheriger Konvertierungen (`size_in/size_out`, fps je Codec/Preset/Auflösung/Rechner, gespeichert in
   `DATA/conv_stats.json`). Optional eine **Probe**: 20–30 s an zwei Stellen kodieren, dann Größe hochrechnen und ein
   Vorher/Nachher-Standbild mit Schieberegler zeigen.
4. **Ein Editor, drei Orte:** `js/convert-editor.js` als wiederverwendbare Komponente
   (`mountConvertEditor(el, value, {target, onChange})`) für (a) „Nach dem Rippen konvertieren“ in der Titelliste (das
   Panel gehört PA; PA baut den Editor dort ein, sobald PF ihn anbietet, bis dahin bleibt das alte Formular),
   (b) die Bibliothek, (c) den Einstellungsabschnitt „Konvertierung & Presets“ (Preset-Verwaltung, Standard-Zuordnung,
   Segmente, Parallelität).
5. **Backend:** Neues, versioniertes Schema für Konvertierungs-Einstellungen (`{"v":2, "codec":…, "quality":{…}, …}`).
   Die alten fünf Felder werden beim Laden **migriert**; `clean_convert` validiert beides. `ffmpeg_args`/`x265_args`/
   `audio_args` pro Codec, der Segment-Modus muss mit allen Software-Codecs funktionieren (für Hardware ggf. abschalten).
   Fähigkeiten pro Rechner über `register_capability('encoders', …)` melden (aus `ffmpeg -encoders` und vorhandenen
   Geräten). Prüfen, ob das ffmpeg im Docker-Image `libx264`, `libsvtav1`, VAAPI enthält; fehlt etwas, den Wunsch an
   PZ (`Dockerfile`) in die Status-Datei schreiben.
6. **Verbund:** Ein Auftrag mit v2-Einstellungen darf **nie** an einen Rechner gehen, der sie nicht versteht (alter
   Stand wie secondtux) oder dem der Encoder fehlt. Der würde sonst still mit x265-Standard kodieren. Solche Rechner im
   „Ausführen auf“-Auswahlfeld und bei der Übergabe ausgrauen und den Grund nennen. Ein v1-kompatibler Auftrag (x265 ohne
   neue Optionen) darf weiter an alte Rechner gehen.

#### Teil 2 – Bibliothek neu denken
Vorschlag als Ausgangspunkt fürs Mockup (Alternativen erwünscht):
- **Drei Bereiche:** links Filter/Ordner (Ordnerbaum, Schnellfilter *Original · Konvertiert · In Arbeit · Fehler*,
  *Filme · Serien · Unsortiert* sobald PE Metadaten liefert, Rechner), Mitte die Dateien als **Liste oder Raster** (Raster
  mit Postern, wenn PE Metadaten hat), rechts ein **Detailbereich** zur Auswahl: Spuren, Codec, Auflösung, HDR, Größe,
  „Einsparung mit Preset X: ~Y GB“, Aktionen (Abspielen/PD, Konvertieren, Einsortieren/PE, Umbenennen, Löschen).
- **Plaketten statt Textspalten:** Codec (HEVC/H.264/VC-1/MPEG-2), Auflösung (SD/1080p/UHD), HDR, Audio (DTS-HD/TrueHD/AC3),
  Status. Serien-Ordner zusammengefasst mit Staffel-Unterpunkten.
- **Auswahlleiste unten**, sobald Dateien gewählt sind: „3 Dateien · 62 GB · ~38 GB Ersparnis“, Preset-Wahl, „Ausführen
  auf …“ (mit geschätzter Dauer je Rechner), Konvertieren. Der Konvertierungs-Editor öffnet sich als Seitenleiste.
- Laufende Arbeit direkt an der Datei: Fortschritt, Rechner, Überspringen/Abbrechen (bisherige Funktionen bleiben).
- Kopfzeile mit Speicherplatz des Ziels und einer Summe „mögliche Einsparung“ über alle Originale.
- Schnell bei großen Bibliotheken (Hunderte Dateien): Rendern in Stücken bzw. virtualisiert, Filter ohne Neuladen,
  Auswahl bleibt beim Aktualisieren erhalten (heute alle 4 s).
- Bestehendes bleibt erhalten: Umbenennen von Dateien und Ordnern, Sperrdateien, Konvertieren auf anderem Rechner,
  Original ersetzen nach bestandener Prüfung.

---

### PZ – Integration und Ausrollen (Phase 3, ein Agent, nach allen anderen)

1. Status-Dateien aller Pakete lesen, offene „Brauche von anderen“-Punkte schließen (inkl. Dockerfile- und
   Compose-Wünsche, z. B. Encoder im Image, `network_mode: host` für die Erkennung).
2. Branches in sinnvoller Reihenfolge auf einen Integrationsbranch mergen (Vorschlag: PA → PB → PF → PC → PD → PE),
   Konflikte lösen, `docs/agenten/schnittstellen.md` auf den Endstand bringen.
3. Gesamttest im Browser: alle Ansichten, Desktop und Handy, zwei lokale Instanzen im Verbund **plus** eine Instanz auf
   dem alten Stand ae4603e (simuliert secondtux), Player, Konvertierung mit jedem Codec (kurze Beispieldatei), Einsortieren
   (Trockenlauf), Konsole fehlerfrei. README um die neuen Funktionen ergänzen.
4. **Ausrollen ist der wichtigste Schritt und passiert erst nach ausdrücklicher Freigabe durch den Nutzer:**
   - Auf `main` mergen und pushen.
   - **Ziele: maintux und vierstein. secondtux NICHT anfassen** (bleibt auf altem Stand, muss im Verbund aber als
     „ältere Version“ bzw. „offline“ sauber angezeigt werden).
   - Vorher auf jedem Rechner prüfen (`/api/state`), dass kein Rip, Backup oder Konvertierung läuft. Sonst warten oder
     mit dem Nutzer die Übergabe nutzen. `data/` (config.json, Presets, Bibliotheks-Cache) und `.env` vorher sichern
     (`cp -a data data.bak-<datum>`).
   - **maintux:** Git-Clone in `~/makemkv-web` → `git pull` → `docker compose up -d --build`. Kein passwortloses
     `sudo`: Werden Root-Schritte gebraucht (Firewall-Port für Erkennung, `network_mode: host`, ffmpeg/Treiber auf dem
     Host), gib dem Nutzer die fertigen Befehle zum Selbst-Ausführen.
   - **vierstein:** `~/makemkv-web` ist **kein Git-Repo**, die Dateien wurden hineinkopiert. Mit dem Nutzer klären, ob
     dort jetzt ein Git-Clone entstehen soll (empfohlen: daneben klonen, `.env`/`data` übernehmen, dann umschalten), oder
     per `rsync` (ohne `data/`, `.env`) aktualisieren. Danach `docker compose up -d --build`. `sudo` geht ohne Passwort.
   - Reihenfolge: erst **maintux** (dort hängt kein Laufwerk, geringeres Risiko), prüfen, dann **vierstein**.
   - Nach dem Ausrollen auf beiden Rechnern prüfen: Oberfläche lädt (ohne Browser-Cache-Reste), beide sehen sich im
     Verbund (und koppeln, falls PC das verlangt), alte `PEERS` wurden migriert, secondtux erscheint offline/älter
     statt eines Fehlers, Laufwerk auf vierstein wird erkannt, eine kurze Testkonvertierung läuft auf maintux, die
     Bibliothek zeigt das NAS.
   - Rückweg dokumentieren und bereithalten (vorheriges Image/Commit + `data.bak`).
   - Ergebnis in `docs/agenten/status-paket-z.md` und als kurze Meldung an den Nutzer.

---

## 6. Dateibesitz nach P0 (Kurzfassung)

| Datei / Ordner | Besitzer |
|---|---|
| `app/main.py`, `config.py`, `state.py`, `settings.py` (Kern) | P0, danach PZ (Ein-Zeilen-Registrierungen erlaubt) |
| `drives.py`, `rip.py`, `upload.py`, `files.py` | P0, danach nur über Hooks/Absprache |
| `convert.py`, `convert_presets.py`, `library.py` | PF |
| `cluster.py`, `nodes.py` | PC |
| `player.py` | PD |
| `app/media/` | PE |
| `static/index.html`, `js/nav.js`, `js/settings.js`, `css/shell.css` | PB |
| `js/jobs.js`, `js/logs.js`, `js/titles.js`, `css/jobs.css` | PA |
| `js/library.js`, `js/convert-editor.js`, `css/library.css`, `css/convert.css` | PF (PD/PE nur über `registerLibraryAction`) |
| `js/nodes.js`, `js/handover.js` | PC |
| `js/player.js` | PD |
| `js/media.js` | PE |
| `js/core.js`, `js/app.js`, `css/base.css` | P0, danach PZ (Registrierungs-Zeilen erlaubt) |
| `docker-compose.yml`, `Dockerfile`, `install.sh` | PZ (Änderungswünsche über Status-Datei) |
| `docs/agenten/status-<paket>.md` | jeweiliges Paket |
