# Status PE (Jellyfin-Ablage) – Stand 2026-10-10

## Erledigt
- Mockup fertig: `docs/mockups/paket-e.html` (Einstellungsabschnitt „Medien / Jellyfin“, Assistent „Einsortieren“ in fünf Schritten, Einstieg aus der Bibliothek; Desktop und 375 px, Umschalter „kein TMDB-Schlüssel“ oben rechts).

## In Arbeit
- Backend: `app/media/` (Einstellungen, Erkennung, Benennung, TMDB-Client, Einsortieren), Tests.

## Angebotene Schnittstellen
(folgt, sobald gebaut: `GET /api/media/info?path=` für PF)

## Abstimmung mit PB (Einstellungsseite)
- Abschnitt wird mit der Kennung `media` angemeldet (`registerSettingsSection({id:'media', label:'Medien / Jellyfin', order:40, icon, description, render, collect})`). Speichern pro Abschnitt macht PB (`POST /api/settings` mit `collect()` = `{media:{…}}`); PE baut keine eigene Speichern-Leiste. Eigene Bedienelemente (Umschalter, Ordnerauswahl) lösen `change` aus. Geheimnisfelder (`tmdb_key`, `jellyfin_key`): `null`/fehlend = unverändert, `""` = löschen; die GET-Antwort liefert nur `tmdb_key_set`/`jellyfin_key_set`.

## Brauche von anderen
- PF: Auswahl-Aktionen (mehrere Dateien) und Ordner-Aktionen in `library.js`: `registerLibraryAction({when(files), run(files)})` bekommt heute nur einzelne Zeilen. Der Assistent „In Filme/Serien einsortieren …“ braucht die Mehrfachauswahl (Dateien) und optional einen Ordner (alle Dateien darin). Status: offen.

## Fremde Dateien angefasst
Keine.

## Fragen an den Nutzer
- TMDB-API-Schlüssel für Live-Tests (kein Schlüssel bis dahin, alles gegen Fixtures/Mock).
