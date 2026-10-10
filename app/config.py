"""Umgebung, Pfade und Vorgaben (alles, was beim Start feststeht)."""
import os
import re
import socket
from pathlib import Path

VERSION = "0.3.0"
# Funktionen dieses Stands, sichtbar für andere Rechner (/api/state -> capabilities.features)
FEATURES = ["handover", "remote-drives", "library-rename", "cancel", "capabilities"]

DATA = Path(os.environ.get("DATA_DIR", "/data"))
OUT_PREFERRED = Path(os.environ.get("OUTPUT_DIR", "/mnt/nas/rips"))
OUT_MOUNT = os.environ.get("OUTPUT_MOUNT", "/mnt/nas")
OUT_FALLBACK = Path(os.environ.get("FALLBACK_DIR", str(DATA / "output")))
INSTANCE = os.environ.get("INSTANCE_NAME") or socket.gethostname()
PEERS_RAW = os.environ.get("PEERS", "")      # „name=http://host:8780,name=…“ – die anderen MakeMKV-Web-Rechner (für die Übergabe)
MKV_DIR = DATA / ".MakeMKV"
CONFIG = DATA / "config.json"
BETAKEY = DATA / "betakey.json"
LIBCACHE = DATA / "library.json"
FORUM_URL = "https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053"
DEV_DRIVE_DIR = os.environ.get("DEV_DRIVE_DIR", "")   # nur Entwicklung (scripts/dev.sh): Attrappen-Laufwerke statt /dev/sr*

AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")    # leer = keine Anmeldung

STAGING = Path(os.environ.get("STAGING_DIR", str(DATA / "staging")))
WORK, READY = STAGING / ".work", STAGING / "ready"     # WORK: läuft gerade, READY: fertig, wartet auf Übertragung
CONVERT, CONV_WORK = STAGING / "convert", STAGING / ".conv"
REPLACE_DIR = STAGING / "replace"        # fertig konvertiert, wartet auf das Zurückspielen (ersetzt das Original)

SEG_MIN_SECONDS = 600       # kürzere Titel werden nicht in Segmente geteilt
LOCK_TTL = 300              # Sekunden ohne Herzschlag, danach gilt eine Sperre als verwaist
LIB_EXT = (".mkv", ".iso", ".m2ts")
LIB_CODECS = ("h264", "vc1", "mpeg2video", "mpeg4", "wmv3")     # diese werden als „Original“ angeboten

X265_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
# Vorgaben für „sieht aus wie das Original, braucht aber nur einen Bruchteil des Platzes“
CONVERT_DEFAULT = {"convert": False, "rf": 21, "preset": "slow", "tune": "none", "extra": "aq-mode=3:no-sao=1", "audio": "copy"}
PRESET_DEFAULTS = {"bluray": dict(CONVERT_DEFAULT), "dvd": dict(CONVERT_DEFAULT)}      # „konvertieren“ ist standardmäßig aus; die Oberfläche startet es bei jeder Disc ebenfalls aus

DEFAULTS = {
    "minlength": 120,      # Sekunden, kürzere Titel werden ignoriert
    "auto_scan": True,     # eingelegte Disc sofort analysieren
    "auto_eject": True,    # nach erfolgreichem Rip auswerfen
    "audio_langs": "",     # z.B. "deu,eng" – leer = alle
    "sub_langs": "",       # z.B. "deu"     – leer = alle
    "key": "",             # eigener MakeMKV-Key; leer = öffentlicher Beta-Key
    "conv_parallel": 1,                    # gleichzeitige Konvertierungen (mehrere Dateien)
    "conv_segments": 0,                    # Segmente je Film: 0 = automatisch nach freien Kernen/RAM, 1 = aus, >1 = fest
    "presets": PRESET_DEFAULTS,  # Konvertierungs-Preset je Disc-Art (in der Oberfläche änderbar)
}

# virtuelle Laufwerke (z. B. CDEmu, VMs) nicht anzeigen; Umgebungsvariable HIDE_DRIVES = Regex, leer = nichts ausblenden
HIDE_RE = re.compile(os.environ.get("HIDE_DRIVES", r"cdemu|virtual|qemu|vbox"), re.I) if os.environ.get("HIDE_DRIVES", "x") else None
