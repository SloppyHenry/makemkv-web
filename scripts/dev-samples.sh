#!/usr/bin/env bash
# Erzeugt Beispieldateien (per ffmpeg) in dem angegebenen Ordner. Vorhandenes wird nicht neu erzeugt.
# Aufruf: scripts/dev-samples.sh <Zielordner>
set -euo pipefail
OUT="${1:?Zielordner fehlt}"
mkdir -p "$OUT"
ff() { ffmpeg -hide_banner -loglevel error -y "$@"; }
video() { echo "testsrc2=size=$1:rate=$2"; }
tone() { echo "sine=frequency=${1:-440}:sample_rate=48000"; }
make() {   # make <Datei> <Befehl …>: nur wenn die Datei fehlt
  local f="$1"; shift
  [ -s "$f" ] && return 0
  mkdir -p "$(dirname "$f")"
  echo "  erzeuge ${f#$OUT/}"
  "$@" "$f.part.mkv" && mv "$f.part.mkv" "$f"
}

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
printf '1\n00:00:01,000 --> 00:00:05,000\nHallo, das ist ein Untertitel.\n\n2\n00:00:10,000 --> 00:00:14,000\nZweite Zeile mit Umlauten: äöü ß\n' > "$TMP/sub.srt"
printf ';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=40000\ntitle=Anfang\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=40000\nEND=80000\ntitle=Mitte\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=80000\nEND=120000\ntitle=Ende\n' > "$TMP/chap.txt"

# 1. Spielfilm, 2 min, H.264 + AC3 (Stereo), Untertitel und Kapitel
make "$OUT/Beispielfilm (2019)/Beispielfilm (2019).mkv" ff \
  -f lavfi -i "$(video 854x480 24)" -f lavfi -i "$(tone)" -i "$TMP/sub.srt" -i "$TMP/chap.txt" -t 120 \
  -map 0:v -map 1:a -map 2:s -map_metadata 3 -c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p -c:a ac3 -b:a 192k -c:s srt \
  -metadata:s:a:0 language=deu -metadata:s:s:0 language=deu

# 2. Serien-Disc „The Walking Dead – Disc 1“: fünf Episoden à ca. 44 min und ein „Play All“-Titel (Summe der ersten vier)
i=0
for secs in 2652 2620 2695 2601 2648; do
  i=$((i + 1)); n=$(printf '%02d' $i)
  make "$OUT/The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel $n.mkv" ff \
    -f lavfi -i "$(video 320x180 2)" -f lavfi -i "$(tone $((300 + i * 40)))" -t "$secs" \
    -c:v libx264 -preset ultrafast -crf 35 -pix_fmt yuv420p -c:a aac -b:a 24k -ac 1 -metadata:s:a:0 language=eng
done
PA="$OUT/The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel 06.mkv"
if [ ! -s "$PA" ]; then
  echo "  erzeuge ${PA#$OUT/} (Play All)"
  for k in 01 02 03 04; do echo "file '$OUT/The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel $k.mkv'"; done > "$TMP/list.txt"
  ff -f concat -safe 0 -i "$TMP/list.txt" -c copy "$PA.part.mkv" && mv "$PA.part.mkv" "$PA"
fi

# 3. HEVC 10-bit
make "$OUT/Beispiel HEVC 10-bit (2021)/Beispiel HEVC 10-bit (2021).mkv" ff \
  -f lavfi -i "$(video 640x360 24)" -f lavfi -i "$(tone 523)" -t 120 \
  -c:v libx265 -preset ultrafast -crf 30 -pix_fmt yuv420p10le -x265-params log-level=error -c:a aac -b:a 96k -ac 2

# 4. Ordner und Datei mit Umlauten und Sonderzeichen
make "$OUT/Ärger & Übung – Größe/Tschüß Fußball (2020).mkv" ff \
  -f lavfi -i "$(video 640x360 25)" -f lavfi -i "$(tone 660)" -t 20 \
  -c:v libx264 -preset ultrafast -crf 32 -pix_fmt yuv420p -c:a aac -b:a 96k

# 5. DVD-artig: MPEG-2, 720x576, AC3
make "$OUT/Beispiel DVD (2005)/Beispiel DVD (2005).mkv" ff \
  -f lavfi -i "$(video 720x576 25)" -f lavfi -i "$(tone 392)" -t 30 \
  -c:v mpeg2video -b:v 3M -pix_fmt yuv420p -flags +ildct+ilme -c:a ac3 -b:a 192k -metadata:s:a:0 language=deu
echo "Beispieldateien in $OUT"
