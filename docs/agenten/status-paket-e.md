# Status PE (Jellyfin-Ablage) – Stand 2026-10-10

## Erledigt
- Mockup fertig: `docs/mockups/paket-e.html` (Einstellungsabschnitt „Medien / Jellyfin“, Assistent „Einsortieren“ in fünf Schritten, Einstieg aus der Bibliothek; Desktop und 375 px, Umschalter „kein TMDB-Schlüssel“ oben rechts).

## In Arbeit
- Backend: `app/media/` (Einstellungen, Erkennung, Benennung, TMDB-Client, Einsortieren), Tests.

## Angebotene Schnittstellen
(folgt, sobald gebaut: `GET /api/media/info?path=` für PF)

## Brauche von anderen
- PF: Auswahl-Aktionen (mehrere Dateien) und Ordner-Aktionen in `library.js`: `registerLibraryAction({when(files), run(files)})` bekommt heute nur einzelne Zeilen. Der Assistent „In Filme/Serien einsortieren …“ braucht die Mehrfachauswahl (Dateien) und optional einen Ordner (alle Dateien darin). Status: offen.

## Fremde Dateien angefasst
Keine.

## Fragen an den Nutzer
- TMDB-API-Schlüssel für Live-Tests (kein Schlüssel bis dahin, alles gegen Fixtures/Mock).
