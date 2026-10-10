# Status PA (UI-Feinschliff) – Stand 2026-10-10

## Erledigt
- **Drehender Kreis (Punkt 1):** `jobs.js` baut die Liste nicht mehr per `setHtml()` neu. Neues Modul `js/jobs-list.js` (`reconcileJobs`): ein stabiles DOM-Element pro Auftrag (Schlüssel `c|Rechner|id`, `u|Rechner|id`, `d|Rechner|Laufwerk`), geändert werden nur Text, Balkenbreite, Klassen und (nur bei Änderung) die Knöpfe. Zusätzlich ist die Drehphase an die Uhr gekoppelt (`syncSpin`, `animation-delay: -(Date.now() % 1000)ms`), falls ein Element eingefügt oder verschoben wird. Das Fortschrittsfeld (`#prog` in `drives.js`) wird ebenfalls nur einmal aufgebaut; der unbestimmte Balken (`@keyframes ind`) läuft jetzt über `transform` statt `margin-left` und startet bei neuen Meldungen nicht neu. Weitere Spinner gibt es nicht (Bibliothek und Laufwerks-Chips haben keine Animation; im Fortschrittsfeld gibt es keinen Kreis).
- **Statussymbol** immer kreisrund: 24 px (gerade), `aspect-ratio:1/1`, `flex:none`, `box-sizing:border-box`; `prefers-reduced-motion` verlangsamt die Drehung.
- **Auftragszeile responsiv (Punkt 2):** Container Query auf die Liste (`.joblist`, `container: jobs/inline-size`), nicht aufs Fenster. Breit (ab 520 px Listenbreite): eine Zeile mit Textknöpfen rechts; mittel (360–519 px): Knöpfe unter dem Text; schmal (bis 359 px): Symbolknöpfe (⏭ ✕) rechts neben dem Text. Statuspille und Rechnername stehen direkt neben dem Titel (umbrechen darunter, wenn der Platz fehlt); der Text hat nie weniger als ca. 190 px, lange Namen werden gekürzt (schmal: bis zu zwei Zeilen). Geprüft bei 1440, 1280, 1050, 900, 700, 375 px, mit Rechnername und langen Dateinamen.
- **Protokoll nur einmal (Punkt 3):** `#compactLog` ist entfernt. Es bleibt die untere Karte `#fullLog` (Slot `bottom`), einklappbar; der Zustand wird in `localStorage` (`logOpen`, mit try/catch) gemerkt. Ein **neuer** Fehler klappt sie auf (ohne die gemerkte Wahl zu überschreiben); ist sie beim Laden zu und enthält Fehler, zeigt eine rote Plakette „N Fehler“ im Kopf. Tastaturbedienbar (`summary`), Fokus sichtbar.
- **Titelliste (Punkt 4):** Plakette „Längster“/„Kurz“ steht jetzt unter dem Dateinamen (`css/titles.css`), der Name wird nicht mehr abgeschnitten. Dazu: auf dem Handy (bis 700 px) wird jede Titelzeile zur Karte (Name oben, Dauer · Größe · Spuren darunter), kein waagerechtes Scrollen mehr.
- `hidden` wirkt jetzt auch bei Knöpfen/Flex-Elementen in Liste, Werkzeugleiste und Fortschrittsfeld (`.secondary{display:inline-block}` überschrieb es vorher).

## In Arbeit
- Einbau von PFs `mountConvertEditor` in die Titelliste („Nach dem Rippen konvertieren“): warte auf das Angebot in PFs Status-Datei (`status-paket-f.md` existiert noch nicht). Bis dahin bleibt das alte Formular (`cvform.js`).

## Angebotene Schnittstellen
- `jobsPanelHtml(id, withDest)` und `data-joblist` in `js/jobs.js` bleiben **unverändert** (PF kann die Bibliothek umbauen und die Auftragsliste wie bisher einbinden). Neu: das Listenelement trägt die Klasse `joblist` (bitte beibehalten, sie enthält die Container Query); Zeilen sind `<div class="job" data-key="…">` (bitte nicht von außen verändern).
- `js/jobs-list.js`: `reconcileJobs(listEl, [{key, model}], leerText)`, `syncSpin(el, ms)`, `jobBtn(...)` (für eigene stabile Listen mit drehendem Kreis: `syncSpin` nach Einfügen aufrufen).
- Protokoll: Karte `#fullLog` (Details-Element), Rumpf `#logFull`; `registerPanel({view:'laufwerke', slot:'bottom', id:'fullLog'})`. Wer das Protokoll in eine andere Ansicht verschieben will (PB hat dafür keinen Bedarf gemeldet): in `logs.js` den Slot ändern.
- CSS-Dateien von PA: `css/jobs.css`, `css/titles.css` (werden automatisch eingebunden). Neue JS-Datei: `js/jobs-list.js` (wird automatisch geladen; hat keine Nebenwirkungen).

## Brauche von anderen
- PF: `mountConvertEditor(el, value, {target, onChange})` für die Titelliste (siehe AUFTRAG PF Teil 1, Punkt 4). Status: offen. Wunsch: Wert im Format von `convOf(d)`/`cv` (heutiges `cvform.js`-Objekt `{convert, rf, preset, tune, extra, audio}` bzw. v2-Schema), damit `startRip()` in `titles.js` ihn unverändert an `POST /api/drives/{id}/rip` (`convert`) schicken kann.
- PB: nichts. `#drivechips` und seine Darstellung bleiben (`drives.js`), das Element darf in `#drivebar` ziehen.

## Fremde Dateien angefasst
Keine.

## Fragen an den Nutzer
- Protokoll standardmäßig aufgeklappt (wie bisher) oder zugeklappt? Derzeit: aufgeklappt, bis der Nutzer es einklappt (wird gemerkt).
