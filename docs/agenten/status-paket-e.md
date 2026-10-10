# Status PE (Jellyfin-Ablage) – Stand 2026-10-10

Mockup fertig: docs/mockups/paket-e.html (Umschalter „kein TMDB-Schlüssel“ oben rechts; Desktop und 375 px je Ansicht)

## Erledigt (Backend komplett, Oberfläche wartet auf Freigabe des Mockups)
- `app/media/` (Paket, lädt sich automatisch): `conf.py` (Einstellungen `media`, Ordnerprüfung), `naming.py` (Jellyfin-Benennung, reine Funktionen), `detect.py` (Erkennen, Play-All, Episodenvorschlag), `metadata.py` (TMDB-Client mit Zwischenspeicher), `scan.py`/`analyze.py` (Auswahl → Erkennung + TMDB), `plan.py` (Vorschau), `organize.py`+`moves.py` (Ausführen, nie überschreiben, Kopieren mit Größenprüfung, Rückgängig), `series.py` (Folgenstand je Serie), `store.py` (Begleitdaten unter `DATA/media/`), `auto.py` (Automatik, Standard aus), `jellyfin.py` (Scan anstoßen), `info.py`, `api.py`.
- Tests (`python -m unittest discover -s tests -t .`, 65 Tests, kein Zusatzpaket): Benennung, Erkennung, TMDB-Client gegen lokale Attrappe `scripts/tmdb_mock.py`, Plan/Ausführen/Rückgängig in Temp-Ordnern, Automatik-Entscheidung.
- Live gegen die Dev-Instanz (Port 8840, TMDB-Attrappe 8841) geprüft: Rip-Hook schreibt Begleitdaten, Erkennen (inkl. Play-All, auch bei Teilauswahl), Suche/IMDb-Auflösung, Plan, Ausführen, Rückgängig, Automatik nach Rip (5 Folgen einsortiert, Play-All bleibt), Ordnerauswahl/Prüfung.
- Quellen der Benennungsregeln: https://jellyfin.org/docs/general/server/media/movies/ und .../shows/ (abgerufen 2026-10-10): `Titel (Jahr) [imdbid-tt…]`, Versionen ` - 1080p`, Extras-Ordner (extras, behind the scenes, deleted scenes, featurettes, interviews, scenes, shorts, trailers, samples, clips, other), `Season 01`, `S01E01-E02`, Specials `Season 00`, unzulässige Zeichen `< > : " / \ | ? *`.

## In Arbeit / offen
- Oberfläche (`js/media.js`, `css/media.css`): erst nach Freigabe des Mockups, dann 1:1.
- Abschnitt wird als `media` angemeldet (`registerSettingsSection`, order 40, icon, description); Speichern pro Abschnitt über PB (`collect()` = `{media:{…}}`, Geheimnisfelder `null` = unverändert; eigene Bedienelemente lösen `change` aus).

## Angebotene Schnittstellen
Alles unter `/api/media` (Dev-Beispiele). Einstellungen: Namensraum `media` {movies_dir, series_dir, naming: jellyfin|unveraendert, action: verschieben|kopieren, tmdb_key*, language, id_tags, episode_names, jellyfin_url, jellyfin_key*, jellyfin_scan, auto} (*Geheimnis, GET liefert `tmdb_key_set`).
- **Für PF (Gruppierung):** `GET /api/media/info?path=<rel>` und `POST /api/media/info {"paths":[…]}` → `{"items":[…]}`:
  `{"path":"Serien/…/Season 01/The Walking Dead S01E01.mkv","known":true,"source":"tool|name","kind":"series|movie","title":"The Walking Dead","year":2010,"tmdb":1402,"imdb":"tt1520211","poster":"https://image.tmdb.org/t/p/w342/twd.jpg","season":1,"episode":1,"episode_end":1,"episode_name":"…","role":"episode"}`; unbekannt: `{"path":…,"known":false}`. `source:"name"` = aus einem Pfad im Jellyfin-Aufbau gelesen (ohne Poster, auch für Dateien, die nicht über das Tool einsortiert wurden). Pfade: relativ zum Ausgabeordner oder absolut. Nur dieser Rechner kennt `poster`/Begleitdaten (nicht im Verbund geteilt).
- **Sammelabfrage für PF (fertig, getestet):** `POST /api/media/infos` mit `{"paths":["Serien/…/S01E01.mkv","x/y.mkv"]}` (bis 2000 Pfade) → Antwort ist ein Objekt **je Pfad**, Unbekanntes fehlt (wie in PFs Status gewünscht):
  `{"Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E01.mkv": {"known":true,"source":"tool","kind":"series","title":"The Walking Dead","year":2010,"tmdb":1402,"imdb":"tt1520211","poster":"https://image.tmdb.org/t/p/w342/twd.jpg","season":1,"episode":1,"episode_end":1,"episode_name":"Days Gone Bye","role":"episode"}}`. Die Liste mit allen Pfaden (auch Unbekannte, Feld `known:false`) liefert weiter `POST /api/media/info` → `{"items":[…]}`.
- `/api/state` → `media`: `{running, undo (Id der rückgängig-fähigen letzten Aktion|null), configured, tmdb}`; `capabilities.media` = `{v:1, naming:[…]}`.
- Assistent: `POST /detect {paths}` (Dateien oder Ordner) → `{detect:{kind,title,year,season,disc,confidence,reasons,items:[{path,dur,role: episode|playall|movie|extra,…}]}, tmdb:{available,error,candidates,chosen,similarity}, start:{episode,known,estimated}, episodes:{assigned,episode_list,error}, files}`; `GET /search?q=&type=movie|tv&year=` (ohne Schlüssel `{available:false}`); `GET /find?imdb=tt…`; `GET /title?type=&id=`; `POST /episodes {items,season,start,tmdb}`; `POST /plan` und `POST /run` (gleiche Anfrage: kind,title,year,tmdb,imdb,poster,season,disc,items[{path,role,season,episodes,name,version,extra_kind}],decisions{pfad:skip|rename}); `GET /run/{id}` (Fortschritt); `GET /history`; `POST /undo/{id}` (nur die letzte); `GET /auto` (Protokoll der Automatik).
- Einstellungen prüfen: `GET /check-dir?path=`, `GET /browse?path=`, `POST /mkdir`, `POST /tmdb/test {key?}`, `POST /jellyfin/test {url?,key?}`, `GET /cache`, `POST /cache/clear`.
- Entwicklung: `MEDIA_ROOT` (Wurzel der Ordnerauswahl, sonst `OUTPUT_MOUNT`/Ausgabeordner), `MEDIA_TMDB_BASE` (Adresse der TMDB-Attrappe, `python3 scripts/tmdb_mock.py 8841`, Schlüssel `testkey`).

## Entscheidungen
- Filme: ID-Tag bevorzugt `imdbid`, Serien `tmdbid` (wie Auftrag), jeweils das andere als Rückfall. `:` wird zu ` - `, `? * < >` entfallen, `"` wird `'`, `/ \ |` werden ` - `.
- Poster werden vom Browser direkt von image.tmdb.org geladen (nur Bild-URL, kein Schlüssel).
- Verschieben im selben Dateisystem = Umbenennen; sonst Kopie über Teildatei, Größenprüfung, dann Original entfernen. Konflikt = nie überschreiben (Überspringen oder ` - 2`).
- Automatik braucht TMDB-Schlüssel, Treffer ≥ 95 %, Folgenlaufzeiten ±6 min, Startfolge bekannt, keinen Konflikt/Sperre.

## Brauche von anderen
- PF: Auswahl-Aktionen (mehrere Dateien) und Ordner-Aktionen in `library.js`: `registerLibraryAction({when(files), run(files)})` bekommt heute nur Zeilen. Der Assistent braucht Mehrfachauswahl (Dateien) bzw. Ordner (der Server löst Ordner selbst auf: `paths` darf Ordner enthalten). Außerdem: `GET/POST /api/media/info` für die Gruppierung nutzen. Status: offen.
- PF/Library-Cache: Nach dem Einsortieren verschwinden Dateien aus dem Ausgabeordner; falls der Filme-/Serien-Ordner im Ausgabeordner liegt, tauchen sie dort unter neuem Pfad auf (Cache-Einträge alter Pfade verfallen beim nächsten Scan). Nach `POST /run` feuert die Oberfläche `emit('files-changed')`.
- PZ: keine Änderungen an Dockerfile/Compose nötig (nur Standardbibliothek + vorhandenes fastapi/pydantic).

## Fremde Dateien angefasst
Keine.

## Fragen an den Nutzer
1. TMDB-API-Schlüssel (kostenlos bei themoviedb.org) für Live-Tests? Bisher nur gegen Attrappe getestet.
2. Wo liegen Filme- und Serien-Ordner auf dem NAS (Vorschlag: neben `dump`, z. B. `/mnt/datenstein/Filme` und `/mnt/datenstein/Serien`)?
3. Soll die Automatik (nach dem Rippen ohne Rückfrage einsortieren) überhaupt angeboten werden, und mit welcher Schwelle (jetzt 95 %)?

## Nachtrag (Antwort des Nutzers)
- Vorbelegung `movies_dir=/mnt/datenstein/Filme`, `series_dir=/mnt/datenstein/Serien` (nur Standardwert; das Backend legt nichts an). Achtung: Im Container heißt das NAS ggf. `/mnt/nas` (OUTPUT_MOUNT); liegt die Vorbelegung außerhalb des eingehängten Ziels, meldet der Plan „Der Ordner muss innerhalb des eingehängten Ziels liegen“ (statt Absturz), und der Nutzer wählt den Ordner in den Einstellungen neu. PZ/Nutzer: tatsächlichen Mount-Pfad im Container prüfen.
- TMDB-Schlüssel trägt der Nutzer später selbst ein; bis dahin nur Attrappe. Automatik bleibt wie gebaut (Standard aus).
