# Status PB (Navigation + Einstellungsseite) – Stand 2026-10-10

Mockup fertig: docs/mockups/paket-b.html (vom Nutzer freigegeben: Variante A, Chips in eigener Leiste ohne Auswahlmenü, Plakette am Reiter Laufwerke, ein Abschnitt pro Ansicht)

## Erledigt
- Mockup (Übersicht mit Reitern; jede Szene auch einzeln per `?s=<szene>` in voller Fenstergröße). Varianten: A Reiter oben (Empfehlung), B Seitenleiste, Laufwerks-Chips (umbrechend / optional Auswahlmenü), Einstellungsseite (Desktop + Handy), Handy mit Tab-Leiste und „Mehr“, Verhalten/Tastatur.

## Umgesetzt (1:1 nach Mockup A, im Browser geprüft bei 1440 und 375 px)
- `index.html`, `js/nav.js`, `js/settings.js`, `js/settings-general.js` (neu: Abschnitte Allgemein, MakeMKV-Key, Übergangsabschnitt Konvertierung), `css/shell.css`. Burger-Menü und Zahnrad-Dialog entfallen.
- Reiter aus `getViews()` (auch später angemeldete), Plakette = laufende Aufträge (eigener Rechner + erreichbare Peers), „Mehr“-Blatt auf dem Handy ab 6 Ansichten, `role=tablist/tab/tabpanel`, ←/→/Pos1/Ende/Leertaste, „Zum Inhalt springen“, Laufwerksleiste `#drivebar` nur in „Laufwerke“.
- Einstellungen: `#/einstellungen/<abschnitt>`, Speichern/Verwerfen je Abschnitt (POST nur mit `collect()` des Abschnitts, danach Neu-Rendern mit der Antwort), gelber Punkt in der Liste und am Reiter „Einstellungen“ bei Ungespeichertem, `beforeunload`-Warnung.
- Ereignisse: `route` (jede Hash-Änderung, Argument = Rest nach der Ansicht), `settings:dirty` (bool). `settings:open` navigiert weiter zur Seite.
- Entwicklungshinweis: `scripts/dev.sh` braucht mit dem System-Python 3.9 ein neueres Python (`PYTHON=/opt/homebrew/bin/python3.14`), sonst scheitert `ext.py` an `Callable | None`.

## Angebotene Schnittstellen
- Erwartete Abschnittskennungen für `registerSettingsSection`: `general`, `key` (PB), `nodes` (PC), `media` (PE), `convert` (PF). Reihenfolge über `order` (PB: 10 und 20).
- Optionale Felder an Abschnitten: `icon`, `description`. Änderungen erkennt PB aus `input`/`change`-Ereignissen im Abschnitt und dem Vergleich von `collect()`. Wer andere Wege hat, löst `el.dispatchEvent(new Event('change', {bubbles: true}))` aus.
- Optional an `registerView`: `badge(S)` (Zahl oder 0) für eine Plakette am Reiter.
- Bis PF den Abschnitt `convert` anmeldet, zeigt PB „Gleichzeitige Dateien“ und „Segmente pro Film“ als Abschnitt `convert-basic` („Konvertierung“); er verschwindet, sobald es `convert` gibt (PF übernimmt die Felder).

## Brauche von anderen
- PA (`drives.js`): nichts Zwingendes. `#drivechips` und die Chip-Darstellung bleiben; das Element zieht nur in `#drivebar`. Optional (nur falls der Nutzer das Auswahlmenü bei vielen Laufwerken will): Funktion, die Chips in einen Container rendert, mit kompakter Darstellung. Status: offen/optional.
- PA: Die Protokoll-Karte entscheidet PA; PB braucht dafür keine eigene Ansicht. Status: Hinweis.
- P0/PZ (`registry.js`): Unterabschnitte im Hash (`#/einstellungen/medien`): `fromHash` soll nur das erste Segment (`split(/[/?]/)[0]`) für die Ansicht nehmen und den Rest über eine Funktion (z. B. `routeRest()`) liefern. Ohne das funktioniert nur `#/einstellungen`. Status: erledigt (siehe unten).
- PF: `library.js` „← Laufwerke“ (`#lib-back`) entfernen (PB entfernt nur den Aufruf in `files.js`). Abschnitt als `convert` anmelden und `conv_parallel`/`conv_segments` übernehmen. Status: offen.
- PC/PE: Abschnittskennungen `nodes` bzw. `media` verwenden. Status: offen.

## Fremde Dateien angefasst
- `app/static/js/files.js`: Knopf `#to-lib` und Handler entfernt (abgesprochen).
- `app/static/js/registry.js`: `routeRest()` neu, `fromHash` nimmt nur das erste Hash-Segment, Ereignis `route` bei `hashchange` (vom Koordinator erlaubt; PZ übernimmt beim Zusammenführen).

## Fragen an den Nutzer
1. Welche Navigation: A (Reiter oben) oder B (Seitenleiste)?
2. Chips unter den Reitern in eigener Leiste (nur in „Laufwerke“): so recht? Auswahlmenü bei sehr vielen Laufwerken gewünscht?
3. Plakette der laufenden Aufträge am Reiter „Laufwerke“: so recht, oder lieber getrennt (z. B. Konvertierungen am Reiter „Bibliothek“)?
4. Einstellungen: ein Abschnitt zur Zeit mit Speichern je Abschnitt (wie im Mockup) oder alles auf einer langen Seite?

## Entscheidung des Koordinators (2026-10-10)
- `registry.js` (`fromHash`/Unterrouten `#/einstellungen/<abschnitt>`): PB darf diese **eine** Änderung selbst in `app/static/js/registry.js` machen (erstes Hash-Segment = Ansicht, Rest über eine kleine exportierte Funktion, z. B. `routeRest()`), klein halten und in diesem Dokument unter „Fremde Dateien angefasst“ vermerken. PZ übernimmt sie beim Zusammenführen.
- PF/PC/PE sind informiert: Abschnittskennungen `convert`, `nodes`, `media`; Speichern pro Abschnitt über `collect()`; PF entfernt `#lib-back`.
- `files.js` (Knopf `#to-lib`) darfst du bei der Umsetzung wie vorher abgesprochen entfernen.
