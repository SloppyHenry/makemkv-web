# Status PB (Navigation + Einstellungsseite) – Stand 2026-10-10

Mockup fertig: docs/mockups/paket-b.html

## Erledigt
- Mockup (Übersicht mit Reitern; jede Szene auch einzeln per `?s=<szene>` in voller Fenstergröße). Varianten: A Reiter oben (Empfehlung), B Seitenleiste, Laufwerks-Chips (umbrechend / optional Auswahlmenü), Einstellungsseite (Desktop + Handy), Handy mit Tab-Leiste und „Mehr“, Verhalten/Tastatur.

## In Arbeit
- Backend gibt es für PB nicht. Die Oberfläche wird erst nach Freigabe des Mockups durch den Nutzer gebaut (1:1).

## Geplanter Umbau (nach Freigabe)
- `index.html`: Kopfzeile mit Logo und `<nav>` (Reiter, `role="tablist"`), Leiste `#drivebar` mit dem umgezogenen `#drivechips`, „Zum Inhalt springen“, `viewport-fit=cover`; Burger-Menü und Zahnrad entfallen.
- `js/nav.js`: Reiter aus `getViews()` (automatisch auch spätere Ansichten), Plakette für laufende Aufträge (Rips/Analyse/Konvertierungen/Übertragungen, eigener Rechner und erreichbare Peers; eine Ansicht kann `badge(S)` liefern), Tastatur (←/→, Pos1/Ende), Hinweisleisten, Seitentitel.
- `js/settings.js`: Ansicht `einstellungen` (Abschnittsliste links, Inhalt rechts); Abschnitte `general` (Auto-Analyse, Auto-Auswerfen, Mindestlänge, Sprachen) und `key` (MakeMKV-Key); Speichern je Abschnitt (`POST /api/settings` nur mit `collect()` dieses Abschnitts), Änderungsanzeige per Vergleich von `collect()` mit dem Stand beim Rendern, Warnung beim Verlassen.
- `css/shell.css`: Entwurf steht im Mockup (`.nav…`, `.drivebar`, `.page…`, `.set…`).

## Angebotene Schnittstellen
- Erwartete Abschnittskennungen für `registerSettingsSection`: `general`, `key` (PB), `nodes` (PC), `media` (PE), `convert` (PF). Reihenfolge über `order` (PB: 10 und 20).
- Optionale Felder an Abschnitten: `icon`, `description`. Änderungen erkennt PB aus `input`/`change`-Ereignissen im Abschnitt und dem Vergleich von `collect()`. Wer andere Wege hat, löst `el.dispatchEvent(new Event('change', {bubbles: true}))` aus.
- Optional an `registerView`: `badge(S)` (Zahl oder 0) für eine Plakette am Reiter.
- Bis PF den Abschnitt `convert` anmeldet, zeigt PB „Gleichzeitige Dateien“ und „Segmente pro Film“ als Abschnitt `convert-basic` („Konvertierung“); er verschwindet, sobald es `convert` gibt (PF übernimmt die Felder).

## Brauche von anderen
- PA (`drives.js`): nichts Zwingendes. `#drivechips` und die Chip-Darstellung bleiben; das Element zieht nur in `#drivebar`. Optional (nur falls der Nutzer das Auswahlmenü bei vielen Laufwerken will): Funktion, die Chips in einen Container rendert, mit kompakter Darstellung. Status: offen/optional.
- PA: Die Protokoll-Karte entscheidet PA; PB braucht dafür keine eigene Ansicht. Status: Hinweis.
- P0/PZ (`registry.js`): Unterabschnitte im Hash (`#/einstellungen/medien`): `fromHash` soll nur das erste Segment (`split(/[/?]/)[0]`) für die Ansicht nehmen und den Rest über eine Funktion (z. B. `routeRest()`) liefern. Ohne das funktioniert nur `#/einstellungen`. Status: offen.
- PF: `library.js` „← Laufwerke“ (`#lib-back`) entfernen (PB entfernt nur den Aufruf in `files.js`). Abschnitt als `convert` anmelden und `conv_parallel`/`conv_segments` übernehmen. Status: offen.
- PC/PE: Abschnittskennungen `nodes` bzw. `media` verwenden. Status: offen.

## Fremde Dateien angefasst
- Geplant (mit dem Koordinator abgesprochen): `app/static/js/files.js` – Knopf `#to-lib` („Nachträglich konvertieren“) und dessen Handler entfernen. Noch nicht geschehen.

## Fragen an den Nutzer
1. Welche Navigation: A (Reiter oben) oder B (Seitenleiste)?
2. Chips unter den Reitern in eigener Leiste (nur in „Laufwerke“): so recht? Auswahlmenü bei sehr vielen Laufwerken gewünscht?
3. Plakette der laufenden Aufträge am Reiter „Laufwerke“: so recht, oder lieber getrennt (z. B. Konvertierungen am Reiter „Bibliothek“)?
4. Einstellungen: ein Abschnitt zur Zeit mit Speichern je Abschnitt (wie im Mockup) oder alles auf einer langen Seite?

## Entscheidung des Koordinators (2026-10-10)
- `registry.js` (`fromHash`/Unterrouten `#/einstellungen/<abschnitt>`): PB darf diese **eine** Änderung selbst in `app/static/js/registry.js` machen (erstes Hash-Segment = Ansicht, Rest über eine kleine exportierte Funktion, z. B. `routeRest()`), klein halten und in diesem Dokument unter „Fremde Dateien angefasst“ vermerken. PZ übernimmt sie beim Zusammenführen.
- PF/PC/PE sind informiert: Abschnittskennungen `convert`, `nodes`, `media`; Speichern pro Abschnitt über `collect()`; PF entfernt `#lib-back`.
- `files.js` (Knopf `#to-lib`) darfst du bei der Umsetzung wie vorher abgesprochen entfernen.
