# Status PD (built-in player) – as of 2026-10-10 (backend and interface done, mockup approved by the user)

## Done
- Read the order, interfaces and code; checked capabilities (see "Findings"); fixed the format concept (see "Decisions").

- **Mockup done: docs/mockups/paket-d.html** (tabs: overlay · in the detail pane (library) · menus · notes & states · phone 375 px · settings). It already uses the final `app/static/css/player.css` (classes `.player…`, container queries on player/window); when building, only the markup in `js/player.js` is generated, 1:1 as in the mockup. To view: open the file in the browser (file://) or run `python3 -m http.server` in the repo root, then `/docs/mockups/paket-d.html`.

- **Backend done and tested** (`app/player.py` router/settings/capabilities, `app/player_probe.py` path check/probe/decision, `app/player_stream.py` sessions/ffmpeg/subtitles/watchdog; each < 400 lines). Tests: `tests/test_player.py` (see "Tested").

- **Interface built** (mockup approved by the user, implemented 1:1): `js/player.js` (overlay `openPlayer`, embedded `mountPlayer`, controls, shortcuts, fullscreen), `js/player-engine.js` (probe, session, seek restart, resume, subtitles), `js/player-ui.js` (markup/menus), `js/player-settings.js` (section "Player"), `css/player.css`. Primary library action `play`; in "Fertige Dateien" the file name is a button (change in `js/files.js`, see below).

## In progress
- Nothing. Open for PF: embedding in the detail pane (see "Needs from others").

## Tested (locally, scripts/dev.sh, Chromium 152)
- `python3 -m unittest tests.test_player` (Python >= 3.10; with `PLAYER_URL=http://127.0.0.1:8830 PLAYER_OUT=<MKW_DEV_DIR>/output` the HTTP tests against the dev instance run as well): 26 tests green. Decision matrix (Chrome/Safari capabilities, MPEG-2/VC-1/HEVC10, forcing, burn-in, without audio/video), path escape (`../`, absolute, NUL, dot files/lock file, symlink to outside, folder, .iso, non-video -> 400/415/404), range (206), WebVTT subtitles with umlauts, lock file -> `locked.by`, only one transcode stream (409), replacement by the same browser, **ffmpeg ends** on connection loss, on `/stop` and in the watchdog (idle/never fetched).
- In the browser (real `<video>` elements against the dev instance): remux (H.264+AC3 -> AAC) plays, restart with `start=61.5` begins exactly at the keyframe (52.083 s, reported by the server), MPEG-2 is transcoded and plays, HEVC 10-bit is transcoded without HEVC capability, played **directly** with capability + `mkv` (native seeking, range). Second audio track and language setting work (checked: `audio_lang=de` selects the German track), conversion at original size (1920x1080 stays 1920x1080). Burn-in was tested and then removed at the user's request.
- **Not tested:** Safari and Firefox (fMP4 stream without range; fall back to HLS only if needed), HDR tone mapping (local ffmpeg without zscale; filter chain after the ffmpeg wiki, present on the production ffmpeg), VAAPI.

## Interface checked (Chromium 152, desktop 1440 and 375 px)
Overlay and embedded: remux, transcoding (MPEG-2), direct (HEVC 10-bit), errors (.iso, non-video), chapter list and jump, seek bar (native within the buffer, otherwise restart), pause, ±10 s, shortcuts (space, arrows, 0–9, C, ?, Esc), switching audio track (restart at the same position), switching subtitles on/off, speed, menus (desktop: popover, 375 px: sheet), closing ends ffmpeg, hash change closes, click on file names in "Fertige Dateien" and library, section "Player" in the settings dialog (saving, values arrive). Console: no errors except the deliberately provoked 415 responses.
**Not checked** (please have a look yourself): real fullscreen and hiding the bar, double tap on the phone, Safari/Firefox (fMP4 stream without range), iPhone fullscreen, long playback with pause > 5 min (resume), HDR.

## Known limits
- Text subtitles are read from the whole file in one pass (Matroska has no index for that): with large files on the NAS the first request takes a while (cache in `DATA/player-cache`, never two at once, `nice`). The interface then shows "Untertitel werden geladen …".
- Audio is always delivered as AAC stereo when it has to be converted (no surround).
- Direct playback only with the default audio track; another audio track -> remux.

## Findings (locally and read-only on vierstein)
- **Browser (Chromium 152, Mac):** H.264 (incl. High10), HEVC 8/10-bit, AV1, VP9, AAC, Opus, FLAC in MP4 work; **AC3/E-AC3 do not**; Matroska only "maybe" (MediaSource: no). Safari cannot do Matroska, but HEVC. No browser can do VC-1, MPEG-2, DTS, TrueHD. The browser reports its capabilities itself (`canPlayType`/`MediaSource.isTypeSupported`), the server decides accordingly.
- **ffmpeg in the production image (vierstein, Debian ffmpeg 7.1.5):** libx264, libx265, libsvtav1, libopus, aac, libmp3lame, `webvtt`, muxers `mp4`/`hls`/`segment`, decoders for VC-1, MPEG-2, DTS, TrueHD, PGS, DVD subtitles, libzimg (tone mapping), VAAPI/QSV/NVENC encoders (hardware only if the device is present). **Nothing in the Dockerfile is needed for the player.**
- Sample files: sample film H.264 Baseline+AC3(mono)+SRT+3 chapters -> remux (audio to AAC); HEVC Main10+AAC -> direct/remux (depending on browser, Matroska!); MPEG-2 (interlaced)+AC3 -> transcoding.

## Decisions (format concept)
1. **Three paths, the server decides from probe + browser capabilities** (`caps`):
   - *direct*: HTTP range on the original file, only if the container (mp4/webm; mkv only if the browser reports it), the video and the default audio track work in the browser. Native seeking, no CPU.
   - *remux*: copy the video (if the browser can do the codec), audio to AAC, as **fragmented MP4** (`frag_keyframe+empty_moov+default_base_moof`) over an HTTP stream. Almost no CPU.
   - *transcode*: H.264 (libx264, `veryfast`, CRF 24, original resolution, deinterlace for interlaced material, HDR -> SDR by tone mapping), audio AAC. Only if the browser cannot do the video codec (VC-1, MPEG-2, …).
2. **Seeking: ffmpeg restart with `-ss` instead of HLS.** Reasons: HLS would need hls.js (Firefox/Chrome desktop without native HLS; no bundler, no third-party library wanted in the image), a segment buffer (space, cleanup) and runs worse on vierstein (4 cores, rips!) with many short processes. With `-ss` there is exactly **one** process per playback, which ends immediately on closing/connection loss. For video copy the start point is first resolved to the last **keyframe** (ffprobe), so that picture and sound are not shifted against each other; the server reports the real start. The interface draws its own timeline (total duration from the probe); if the target is within the already buffered range it jumps natively, otherwise it restarts (about 0.5–2 s). Fallback to HLS only if Safari does not accept the stream (untested, see "Known problems").
3. **Subtitles:** text tracks (SRT/ASS/mov_text/WebVTT) -> WebVTT via `GET /api/player/subtitle`, the interface displays them itself (own overlay, so the start offset on restart does not matter). Picture tracks (PGS/VobSub): only "not supported" (burn-in was dropped at the user's request).
4. **Consideration:** ffmpeg always with `nice`, small `-threads` while rip/conversion/transfer is running (notice in the interface); at most **one** transcode stream per machine (a second user gets 409 with a reason; the same browser replaces its old stream); the process ends on connection loss, via `POST /api/player/stop` (sendBeacon on closing) and by a watchdog (no progress > 5 min / never fetched > 30 s).
5. **Security:** only `files.inside_out()`, only video extensions, no dot files (lock files), no folders; ffmpeg gets `file:` paths as an argument list (no shell). Locked/converted files stay playable, the probe returns `locked` for the notice.
6. **Cluster:** none (user decision): the player works only with the local machine.

## Interfaces offered
Backend, prefix `/api/player` (all paths relative to the output folder; errors: 400 path, 404, 415 not playable/.iso, 422 unreadable, 409 busy, 504 NAS too slow):
- `GET|POST /probe?path=&caps=&audio=&force=` -> `{path,name,size,duration,container,video{codec,bits,w,h,hdr,interlaced,…},audio[{i,codec,channels,lang,title,default}],subs[{i,codec,lang,kind:'text'|'bitmap',supported,forced}],chapters[{start,end,title}],preferred{audio,sub},plan{mode:'direct'|'remux'|'transcode',video:'copy'|'x264',audio:'copy'|'aac'|'none',reasons[],ok,error},locked:{by,reason}|null,busy{rip,convert,upload,busy,load,cores},transcode_allowed,limits{transcode_busy}}`. `caps` = browser capabilities as a word list: `mkv,h264,h264_10,hevc,hevc10,vp9,av1,opus,flac,ac3,eac3` (aac/mp3 always). `force`: `auto|remux`. Only the preferred audio track can be played directly; other tracks go via remux.
- `POST /session {path,caps,client,start,audio,force}` -> `{mode,plan,duration,locked,busy,id,url,start,native_seek}`: `url` is `/api/player/file?path=…` (direct) or `/api/player/stream/{id}` (fMP4). `start` = actual beginning in s (keyframe for remux); the interface computes `time = start + video.currentTime`. `client` = random ID of the tab; a new stream replaces the old one of the same tab.
- `GET /stream/{id}` (video/mp4, no range, one request = one ffmpeg), `GET /file?path=` (range), `GET /subtitle?path=&index=` (text/vtt; `index` = ordinal of the subtitle track), `POST /stop {client}` (also via `navigator.sendBeacon`), `GET /sessions` (diagnostics).
- Settings (namespace `player`): `transcode` (bool, on), `max_height` (0 = original, otherwise 240–2160; default 0), `crf` (16–35, 24), `preset` (`veryfast`…), `audio_lang` / `sub_lang` (ranked list, e.g. `deu,eng`; 2-letter codes are understood). Empty: audio takes the general `audio_langs`, otherwise the file's default; subtitles only the text track marked default/forced in the file. The probe returns the preselection as `preferred: {audio, sub}` (ordinals). Section "Player" on PB's settings page: `registerSettingsSection({id:'player', …})`, `collect()` -> `{player: {...}}` (comes with the interface).
- Capability `capabilities.player`: `{v:1, modes:['direct','remux','transcode'], encoders:['libx264'], tonemap:bool, max_transcodes:1, subtitles:['text']}`; older machines do not have it -> grey out in the cluster.
- Cluster: **none.** User decision: no streaming from other machines, player calls stay local (no `allow_proxy`).
- Frontend (after approval): `registerLibraryAction({id:'play', primary:true, …})`; `import { openPlayer, mountPlayer } from './player.js'` – `openPlayer(path)` overlay, `mountPlayer(el, path, {compact:true})` embedded (for PF).

## Needs from others
- **PF** (`js/library.js`): a spot in the detail pane of the new library for `mountPlayer(…)` (see mockup, variant B); a click on the file name otherwise triggers the primary action (overlay). Status: open, waiting for PF's mockup.
- **P0/PZ** (`js/files.js`): "Fertige Dateien" has no actions; a click on the file name should run `getLibraryActions().find(primary)`. Status: open (coordinator decides).
- **PC:** nothing any more (no cluster streaming).
- **PZ**: nothing needed in the Dockerfile.

## Foreign files touched
- `app/static/js/files.js` (P0/PZ), with the coordinator's permission: the file name in "Fertige Dateien" becomes a button (`.player-link`, class in `player.css`) that runs the primary library action (`getLibraryActions()`); 6 lines (import, `prim()`, delegation `#filesBody`). If PB/PZ also change `files.js`: take over only these lines.

## Questions for the user
Answered (user's decision, via the coordinator): both (overlay by clicking the file name and a play button in the detail pane); "Ton & Untertitel" one menu; transcoding on vierstein also during a rip (lowest priority, notice); **no** "play on maintux" (player stays local); **no** burn-in (picture subtitles only "not supported"); default: play the original file whenever possible, no downscaling (`max_height` 0 = original), convert only if the browser cannot do the video; preferred language for audio and subtitles in the settings.
Open: none.
