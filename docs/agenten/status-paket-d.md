# Status PD (Interner Player) – Stand 2026-10-10

## Erledigt
- Auftrag, Schnittstellen und Code gelesen; Fähigkeiten geprüft (siehe „Befunde“); Format-Konzept festgelegt (siehe „Entscheidungen“).

- **Mockup fertig: docs/mockups/paket-d.html** (Reiter: Überlagerung · Im Detailbereich (Bibliothek) · Menüs · Hinweise & Zustände · Handy 375 px · Einstellungen). Es nutzt schon die endgültige `app/static/css/player.css` (Klassen `.player…`, Container Queries am Player/Fenster); beim Bauen wird nur das Markup in `js/player.js` erzeugt, 1:1 wie im Mockup. Ansehen: Datei im Browser öffnen (file://) oder `python3 -m http.server` im Repo-Stamm, dann `/docs/mockups/paket-d.html`.

## In Arbeit
- Backend (ohne neue Oberfläche): Probe/Plan, Remux/Transkodierung, Untertitel (WebVTT), Prozess-Aufräumen, Tests. Die Oberfläche (`js/player.js`) folgt erst nach Freigabe des Mockups.

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

## Angebotene Schnittstellen (Entwurf, wird mit dem Backend verbindlich)
- Backend (`/api/player`): `GET|POST /probe`, `POST /session`, `GET /stream/{id}`, `GET /file?path=` (direkt, Range), `GET /subtitle?path=&index=`, `POST /stop`; Einstellungen `player` (`transcode`, `max_height`, `crf`); Fähigkeit `player` (`modes`, `encoders`, `hdr_tonemap`, `max_transcodes`).
- Frontend: `registerLibraryAction({id:'play', primary:true, …})`; `import { openPlayer, mountPlayer } from './player.js'` – `openPlayer(path)` öffnet die Überlagerung, `mountPlayer(el, path, {compact:true})` bettet den Player in den Detailbereich der Bibliothek ein (für PF).

## Brauche von anderen
- **PF** (`js/library.js`): Stelle im Detailbereich der neuen Bibliothek für `mountPlayer(…)` (siehe Mockup, Variante B); Klick auf Dateinamen löst sonst die primäre Aktion (Überlagerung) aus. Status: offen, wartet auf PF-Mockup.
- **P0/PZ** (`js/files.js`): „Fertige Dateien“ hat keine Aktionen; Klick auf den Dateinamen soll `getLibraryActions().find(primary)` ausführen. Status: offen (Koordinator entscheidet).
- **PC** (später): Strom-Adresse eines Rechners (`peers[i].url` ist schon in `/api/state`), `allow_proxy`-Eintrag meldet PD selbst an. Status: offen, niedrige Priorität.
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
