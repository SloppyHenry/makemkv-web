# Status PD (Interner Player) – Stand 2026-10-10 (Backend fertig, Oberfläche wartet auf Freigabe des Mockups)

## Erledigt
- Auftrag, Schnittstellen und Code gelesen; Fähigkeiten geprüft (siehe „Befunde“); Format-Konzept festgelegt (siehe „Entscheidungen“).

- **Mockup fertig: docs/mockups/paket-d.html** (Reiter: Überlagerung · Im Detailbereich (Bibliothek) · Menüs · Hinweise & Zustände · Handy 375 px · Einstellungen). Es nutzt schon die endgültige `app/static/css/player.css` (Klassen `.player…`, Container Queries am Player/Fenster); beim Bauen wird nur das Markup in `js/player.js` erzeugt, 1:1 wie im Mockup. Ansehen: Datei im Browser öffnen (file://) oder `python3 -m http.server` im Repo-Stamm, dann `/docs/mockups/paket-d.html`.

- **Backend fertig und getestet** (`app/player.py` Router/Einstellungen/Fähigkeiten, `app/player_probe.py` Pfadprüfung/Probe/Entscheidung, `app/player_stream.py` Sitzungen/ffmpeg/Untertitel/Wächter; je < 400 Zeilen). Tests: `tests/test_player.py` (siehe „Getestet“).

## In Arbeit
- Nichts, bis das Mockup freigegeben ist. Danach: `js/player.js` (Überlagerung, eingebettet, Menüs, Tastenkürzel, Untertitel-Anzeige, Seek-Neustart) 1:1 nach dem Mockup, `registerLibraryAction({id:'play', primary:true})`, `registerSettingsSection` „Player“.

## Getestet (lokal, scripts/dev.sh, Chromium 152)
- `python3 -m unittest tests.test_player` (Python >= 3.10; mit `PLAYER_URL=http://127.0.0.1:8830 PLAYER_OUT=<MKW_DEV_DIR>/output` laufen zusätzlich die HTTP-Tests gegen die Dev-Instanz): 23 Tests grün. Entscheidungsmatrix (Chrome-/Safari-Fähigkeiten, MPEG-2/VC-1/HEVC10, Erzwingen, Einbrennen, ohne Ton/Video), Pfadausbruch (`../`, absolut, NUL, Punktdateien/Sperrdatei, Symlink nach außen, Ordner, .iso, Nicht-Video -> 400/415/404), Range (206), Untertitel-WebVTT mit Umlauten, Sperrdatei -> `locked.by`, nur ein Transkodier-Strom (409), Ersetzen durch denselben Browser, **ffmpeg endet** bei Verbindungsabriss, bei `/stop` und im Wächter (Leerlauf/nie abgeholt).
- Im Browser (echte `<video>`-Elemente gegen die Dev-Instanz): Remux (H.264+AC3 -> AAC) spielt, Neustart mit `start=61.5` beginnt exakt am Keyframe (52,083 s, vom Server gemeldet), MPEG-2 wird transkodiert und spielt, HEVC 10-bit wird ohne HEVC-Fähigkeit transkodiert, mit Fähigkeit + `mkv` **direkt** abgespielt (natives Suchen, Range). Bilduntertitel einbrennen (selbst gebaute PGS-Spur) funktioniert, zweite Tonspur wählbar.
- **Nicht getestet:** Safari und Firefox (fMP4-Strom ohne Range; Rückfall HLS nur falls nötig), HDR-Tonemapping (lokales ffmpeg ohne zscale; Filterkette nach ffmpeg-Wiki, auf dem Produktions-ffmpeg vorhanden), VAAPI, Wiedergabe von einem anderen Rechner.

## Bekannte Grenzen
- Bilduntertitel (PGS) nach einem Sprung: ein gerade laufender Untertitel erscheint erst beim nächsten (ffmpeg verliert den Zustand beim `-ss`).
- Textuntertitel werden in einem Durchgang aus der ganzen Datei gelesen (Matroska hat dafür keinen Index): bei großen Dateien am NAS dauert der erste Abruf (Zwischenspeicher in `DATA/player-cache`, nie zwei gleichzeitig, `nice`). Die Oberfläche zeigt dann „Untertitel werden geladen …“.
- Ton wird immer als AAC-Stereo geliefert, wenn er umgewandelt werden muss (kein Surround).
- Direkt-Wiedergabe nur mit Standardtonspur; andere Tonspur -> Remux.

## Befunde (lokal und lesend auf vierstein)
- **Browser (Chromium 152, Mac):** H.264 (inkl. High10), HEVC 8/10-bit, AV1, VP9, AAC, Opus, FLAC im MP4 gehen; **AC3/E-AC3 gehen nicht**; Matroska nur „maybe“ (MediaSource: nein). Safari kann kein Matroska, dafür HEVC. VC-1, MPEG-2, DTS, TrueHD kann kein Browser. Der Browser meldet seine Fähigkeiten selbst (`canPlayType`/`MediaSource.isTypeSupported`), der Server entscheidet danach.
- **ffmpeg im Produktions-Image (vierstein, Debian-ffmpeg 7.1.5):** libx264, libx265, libsvtav1, libopus, aac, libmp3lame, `webvtt`, Muxer `mp4`/`hls`/`segment`, Decoder für VC-1, MPEG-2, DTS, TrueHD, PGS, DVD-Untertitel, libzimg (Tonemapping), VAAPI/QSV/NVENC-Encoder (Hardware nur falls Gerät da). **Für den Player ist nichts am Dockerfile nötig.**
- Beispieldateien: Beispielfilm H.264 Baseline+AC3(mono)+SRT+3 Kapitel -> Remux (Ton nach AAC); HEVC Main10+AAC -> direkt/Remux (je nach Browser, Matroska!); MPEG-2 (interlaced)+AC3 -> Transkodierung.

## Entscheidungen (Format-Konzept)
1. **Drei Wege, der Server entscheidet anhand von Probe + Browser-Fähigkeiten** (`caps`):
   - *direkt*: HTTP-Range auf die Originaldatei, nur wenn Container (mp4/webm; mkv nur wenn der Browser es meldet), Video- und die Standard-Tonspur im Browser gehen. Natives Suchen, keine CPU.
   - *Remux*: Video kopieren (wenn der Browser den Codec kann), Ton nach AAC, als **fragmentiertes MP4** (`frag_keyframe+empty_moov+default_base_moof`) per HTTP-Strom. Fast keine CPU.
   - *Transkodieren*: H.264 (libx264, `veryfast`, CRF 24, höchstens 720p, Deinterlace bei Zeilensprung, HDR -> SDR per Tonemapping), Ton AAC. Nur wenn der Browser den Videocodec nicht kann (VC-1, MPEG-2, …) oder der Nutzer „kleiner/ruckelfrei“ wählt.
2. **Suchen: ffmpeg-Neustart mit `-ss` statt HLS.** Gründe: HLS bräuchte hls.js (Firefox/Chrome-Desktop ohne Native-HLS; kein Bundler, keine Fremdbibliothek im Image gewünscht), einen Segment-Zwischenspeicher (Platz, Aufräumen) und läuft auf vierstein (4 Kerne, Rips!) mit vielen kurzen Prozessen schlechter. Mit `-ss` gibt es genau **einen** Prozess pro Wiedergabe, der beim Schließen/Abriss sofort endet. Bei Video-Kopie wird der Startpunkt vorher auf den letzten **Keyframe** aufgelöst (ffprobe), damit Bild und Ton nicht gegeneinander verschoben sind; der Server meldet den echten Start. Die Oberfläche zeichnet ihre eigene Zeitleiste (Gesamtdauer aus der Probe), liegt das Ziel im bereits gepufferten Bereich, wird nativ gesprungen, sonst neu gestartet (ca. 0,5–2 s). Rückfall HLS nur, falls Safari den Strom nicht annimmt (ungeprüft, siehe „Bekannte Probleme“).
3. **Untertitel:** Textspuren (SRT/ASS/mov_text/WebVTT) -> WebVTT über `GET /api/player/subtitle`, die Oberfläche zeigt sie selbst an (eigene Überlagerung, damit der Startversatz bei Neustart nicht stört). Bildspuren (PGS/VobSub): „nicht unterstützt“, optional **einbrennen** (erzwingt Transkodierung).
4. **Rücksicht:** ffmpeg immer mit `nice`, `-threads` klein, solange Rip/Konvertierung/Übertragung läuft (Hinweis in der Oberfläche); höchstens **ein** Transkodier-Strom je Rechner (ein zweiter Nutzer bekommt 409 mit Begründung; derselbe Browser ersetzt seinen alten Strom); Prozess endet bei Verbindungsabriss, per `POST /api/player/stop` (sendBeacon beim Schließen) und durch einen Wächter (kein Fortschritt > 5 min / nie abgeholt > 30 s).
5. **Sicherheit:** nur `files.inside_out()`, nur Videoendungen, keine Punktdateien (Sperrdateien), keine Ordner; ffmpeg bekommt `file:`-Pfade als Argumentliste (keine Shell). Gesperrte/konvertierte Dateien bleiben abspielbar, die Probe liefert `locked` für den Hinweis.
6. **Verbund (optional, später):** Alle Rechner sehen dasselbe NAS, d. h. derselbe relative Pfad gilt überall. Sinnvoll ist „Transkodieren auf maintux“: `POST /api/peer/{name}/player/session` (per `ext.allow_proxy`) liefert eine Strom-Adresse, der Browser holt den Strom direkt vom Rechner (`peers[i].url`, Browser muss ihn erreichen). Kein Range-Proxy über `cluster.py` nötig. Mit PC abzustimmen, sobald dessen Rechnerliste steht.

## Angebotene Schnittstellen
Backend, Präfix `/api/player` (alle Pfade relativ zum Ausgabeordner; Fehler: 400 Pfad, 404, 415 nicht abspielbar/.iso, 422 nicht lesbar, 409 belegt, 504 NAS zu langsam):
- `GET|POST /probe?path=&caps=&audio=&burn=&force=` -> `{path,name,size,duration,container,video{codec,bits,w,h,hdr,interlaced,…},audio[{i,codec,channels,lang,title,default}],subs[{i,codec,lang,kind:'text'|'bitmap',forced}],chapters[{start,end,title}],plan{mode:'direct'|'remux'|'transcode',video:'copy'|'x264',audio:'copy'|'aac'|'none',burn,reasons[],ok,error},locked:{by,reason}|null,busy{rip,convert,upload,busy,load,cores},transcode_allowed,limits{transcode_busy}}`. `caps` = Browser-Fähigkeiten als Wortliste: `mkv,h264,h264_10,hevc,hevc10,vp9,av1,opus,flac,ac3,eac3` (aac/mp3 immer). `force`: `auto|remux|transcode`.
- `POST /session {path,caps,client,start,audio,burn,force,quality}` -> `{mode,plan,duration,locked,busy,id,url,start,native_seek}`: `url` ist `/api/player/file?path=…` (direkt) oder `/api/player/stream/{id}` (fMP4). `start` = tatsächlicher Beginn in s (Keyframe bei Remux); die Oberfläche rechnet `Zeit = start + video.currentTime`. `client` = zufällige Kennung des Tabs; ein neuer Strom ersetzt den alten desselben Tabs.
- `GET /stream/{id}` (video/mp4, kein Range, ein Abruf = ein ffmpeg), `GET /file?path=` (Range), `GET /subtitle?path=&index=` (text/vtt; `index` = Ordnungszahl der Untertitelspur), `POST /stop {client}` (auch per `navigator.sendBeacon`), `GET /sessions` (Diagnose).
- Einstellungen (Namensraum `player`): `transcode` (bool, 1), `max_height` (240–2160, 720), `crf` (16–35, 24), `preset` (`veryfast`…).
- Fähigkeit `capabilities.player`: `{v:1, modes:['direct','remux','transcode'], encoders:['libx264'], tonemap:bool, max_transcodes:1, subtitles:['text']}`; ältere Rechner haben sie nicht -> im Verbund ausgrauen.
- Verbund: `ext.allow_proxy('player/(probe|session|stop)')`. Für „Abspielen auf maintux“ ruft die Oberfläche `POST /api/peer/{name}/player/session` und öffnet `peers[i].url + url` direkt im `<video>` (Strom und Datei laufen ohne Proxy; der Browser muss den Rechner erreichen, bei gesetztem `AUTH_PASS` fragt der Browser einmal nach dem Passwort). `subtitle` (GET) ebenfalls direkt am Rechner.
- Frontend (nach Freigabe): `registerLibraryAction({id:'play', primary:true, …})`; `import { openPlayer, mountPlayer } from './player.js'` – `openPlayer(path)` Überlagerung, `mountPlayer(el, path, {compact:true})` eingebettet (für PF).

## Brauche von anderen
- **PF** (`js/library.js`): Stelle im Detailbereich der neuen Bibliothek für `mountPlayer(…)` (siehe Mockup, Variante B); Klick auf Dateinamen löst sonst die primäre Aktion (Überlagerung) aus. Status: offen, wartet auf PF-Mockup.
- **P0/PZ** (`js/files.js`): „Fertige Dateien“ hat keine Aktionen; Klick auf den Dateinamen soll `getLibraryActions().find(primary)` ausführen. Status: offen (Koordinator entscheidet).
- **PC** (später, optional): Für „Abspielen auf maintux“ holt der Browser Strom und Datei direkt unter `peers[i].url` (steht in `/api/state`). PCs Rechner-Token gilt dort nicht; bei gesetztem `AUTH_PASS` auf dem Zielrechner fragt der Browser per Basic-Anmeldung. Bitte PC prüfen, ob `/api/player/stream|file|subtitle` unter der Token-Prüfung für Browser-Direktaufrufe erreichbar bleiben (`auth.py` Pfadliste), sonst reicht der Verbund nur für `probe/session/stop` per Proxy. Status: offen, niedrige Priorität.
- **PZ**: nichts am Dockerfile nötig.

## Fremde Dateien angefasst
Keine.

## Fragen an den Nutzer
1. Soll es **beides** geben: Klick auf den Dateinamen öffnet die Überlagerung, ein Abspielen-Knopf im Detailbereich der Bibliothek bettet den Player ein (Empfehlung), oder nur eines von beiden?
2. Ton und Untertitel liegen in **einem** Menü („Ton & Untertitel“), damit auf dem Handy alles in eine Zeile passt. Recht so?
3. Darf auf dem Rechner mit dem Laufwerk (vierstein, 4 Kerne) **transkodiert werden, während ein Rip läuft** (mit niedrigster Priorität, Hinweis im Player)? Oder lieber sperren und nur „Auf maintux abspielen“ anbieten?
4. Soll es „Abspielen auf maintux“ (Umwandeln auf dem stärkeren Rechner, Browser holt den Strom direkt dort ab) geben? Setzt voraus, dass der Browser maintux:8780 erreicht.
5. Bilduntertitel (PGS/VobSub) **einbrennen** anbieten (kostet Transkodierung) oder nur „nicht unterstützt“ anzeigen?
6. Standard-Qualität beim Umwandeln: 720p, CRF 24 (Mockup-Annahme). Passt das?
