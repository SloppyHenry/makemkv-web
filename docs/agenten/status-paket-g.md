# Status PG (Headless-Modus) – Stand 2026-10-11

Branch `paket-g` (von `main` 63738f7). Nichts ist gepusht, nichts ist in `main` zusammengeführt, nichts ist ausgerollt.

## Verhalten
Eingeschaltet (Einstellungen → Headless-Modus) läuft nach dem Einlegen einer Disc ohne Bedienung:
1. Analyse (auch wenn „automatisch analysieren“ aus ist).
2. Gedächtnis: Wurde dieselbe Disc schon einmal von Hand gerippt (hier oder an einem anderen Rechner im Verbund), dieselben Titel, Namen und Ordner.
3. Disc-Kennungen direkt vom Gerät lesen und in TheDiscDB nachschlagen (erst Disc-ID, dann Inhalts-Hash). Treffer: nur der Hauptfilm bzw. nur die Folgen; Ordner „Titel (Jahr)“, Folgen „Serie S01E02 - Folgentitel“.
3a. Kein Treffer, aber TMDB kennt den Namen eindeutig (nur als Film oder nur als Serie): der Titel mit der Filmlaufzeit (± 4 %, mind. 3 min) bzw. die Titel mit Folgenlänge der Staffel (± 12 %, mindestens zwei). Hilft vor allem bei deutschen Ausgaben, die TheDiscDB selten kennt.
3b. Sonst Struktur der Disc. Film = genau ein Titel ab 70 min und keine Reihe gleich langer Titel; Serie = mindestens zwei Folgen (15–80 min) ohne Titel ab 70 min, Play-All und Extras fallen weg. TMDB (falls Schlüssel da) dient nur als Gegenprobe des Namens.
4. Unsicher: alle Titel ohne Duplikate (gleiche Laufzeit, Größe, Segmente) und ohne Play-All. Wären das mehr als doppelt so viele Daten wie Videodaten auf der Disc: nichts rippen, „bitte von Hand“.
5. Danach wird die Disc immer ausgeworfen (fertig, Fehler, „von Hand“). Nur ein Abbruch durch den Nutzer lässt sie drin.
Wird eine „von Hand“-Disc wieder eingelegt, bleibt sie im Laufwerk („wartet auf Auswahl“); die dann von Hand gerippte Auswahl merkt sich das Gedächtnis. Unbekannte Discs lassen sich mit „An TheDiscDB melden“ einreichen (Vorschlag aus Gedächtnis/Erkennung, Zuordnung je Titel, Vorschau; gesendet wird nur auf Knopfdruck, TheDiscDB prüft vor dem Veröffentlichen).
Optional: nach dem Rippen mit dem Standard-Preset der Disc-Art konvertieren. Protokoll mit Begründung im Feld „Headless-Modus“ (Laufwerke); „Erkennung testen“ zeigt die Wahl, ohne zu rippen.

## Dateien
- Neu: `app/headless/` (`__init__`, `udf`, `discid`, `discdb`, `choose`, `run`), `js/headless.js`, `css/headless.css`, `tests/test_headless.py`, `tests/udf_build.py`.
- Dazu: `plan.py`, `memory.py`, `tmdbmatch.py`, `contribute.py`, `js/headless-contribute.js`, `tests/test_headless_more.py`.
- Kern: `ext.register_scan_hook` (+ `auto_scan_forced`), `drives.do_scan(auto=…)` ruft die Hooks, `rip.prepare_rip()` aus `api_rip` herausgelöst, `makemkv` liefert `segments` (Attribut 26), `main.OPTIONAL_MODULES` + `app.headless`.
- Attrappe `makemkvcon`: `source`, `segments`, `fail` je Titel.

## Geprüft
- Inhalts-Hash an zwei echten TheDiscDB-Einträgen nachgerechnet (Blu-ray „10 Cloverfield Lane“, DVD „Bakugan Vol. 1“): identisch.
- UDF-Leser: hdiutil-Abbilder (UDF 1.02/1.50, Blu-ray- und DVD-Struktur) und eigenes UDF-2.50-Abbild mit Metadaten-Partition; Disc-ID und Hash wie erwartet.
- Live gegen thediscdb.com (`scripts/dev.sh`, Attrappe mit Cloverfield-Abbild und einer gleich langen Schein-Playlist): Treffer über den Inhalts-Hash, nur `00800.mpls` gerippt, als „10 Cloverfield Lane (2016)“.
- Ablauf in der Attrappe: Serien-Disc (5 Folgen, Play-All und Extra ausgelassen), Lesefehler (ausgeworfen, „Fehler“), 30 Schein-Playlists („von Hand“, nichts gerippt, ausgeworfen), Kinderserie mit 11-min-Folgen (unsicher, alle Titel).
- Oberfläche bei 1440 und 375 px ohne Konsolenfehler und ohne waagerechten Überlauf.
- Gedächtnis in der Attrappe: unbekannte Disc → „von Hand“; wieder eingelegt → bleibt drin; von Hand Titel 8 als „Mein Film (2020)“ gerippt; wieder eingelegt → genau dieser Titel mit Namen und Ordner. Abfrage bei anderen Rechnern per Unit-Test.
- TMDB (Attrappe `scripts/tmdb_mock.py`): Disc „MATRIX“ mit zwei langen Titeln → der Titel mit 136 min als „Matrix (1999)“.
- Meldung an TheDiscDB: Vorschlag und Vorschau gegen die Attrappe, Absenden nur per Unit-Test (keine Testdaten an TheDiscDB geschickt).
- `python3 -m unittest discover -s tests -t .`: 182 Tests grün (9 übersprungen). Keine Datei über 400 Zeilen.

## Offen
- Test mit echter Disc im Laufwerk (DVD, Blu-ray, UHD): Lesen von `/dev/sr0` im Container, Disc-ID und Treffer in TheDiscDB.
- Schwellen der Strukturerkennung und des TMDB-Abgleichs an eigenen Discs prüfen (Film, Serien-DVD, Serien-Blu-ray).
- Gedächtnis über zwei echte, gekoppelte Rechner (bisher nur Unit-Test).
- Die Einreichung nutzt TheDiscDBs offene „Engram“-Schnittstelle (dort noch ohne Schlüssel, „TODO: API key“); bekommt sie einen Schlüssel, muss die Meldung angepasst werden. Erste echte Meldung bitte gemeinsam prüfen.
