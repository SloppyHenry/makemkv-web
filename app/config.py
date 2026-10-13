"""Environment, paths and defaults (everything that is fixed at startup)."""
import os
import re
import socket
from pathlib import Path

VERSION = "0.3.0"
# Features of this version, visible to other machines (/api/state -> capabilities.features)
FEATURES = ["handover", "remote-drives", "library-rename", "cancel", "capabilities"]

DATA = Path(os.environ.get("DATA_DIR", "/data"))
OUT_PREFERRED = Path(os.environ.get("OUTPUT_DIR", "/mnt/nas/rips"))
OUT_MOUNT = os.environ.get("OUTPUT_MOUNT", "/mnt/nas")
OUT_FALLBACK = Path(os.environ.get("FALLBACK_DIR", str(DATA / "output")))
INSTANCE = os.environ.get("INSTANCE_NAME") or socket.gethostname()
PEERS_RAW = os.environ.get("PEERS", "")      # "name=http://host:8780,name=…" – the other Spindle machines (for hand-over)
MKV_DIR = DATA / ".MakeMKV"
CONFIG = DATA / "config.json"
BETAKEY = DATA / "betakey.json"
LIBCACHE = DATA / "library.json"
FORUM_URL = "https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053"
DEV_DRIVE_DIR = os.environ.get("DEV_DRIVE_DIR", "")   # development only (scripts/dev.sh): fake drives instead of /dev/sr*

AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")    # empty = no login

STAGING = Path(os.environ.get("STAGING_DIR", str(DATA / "staging")))
WORK, READY = STAGING / ".work", STAGING / "ready"     # WORK: in progress, READY: finished, waiting for transfer
CONVERT, CONV_WORK = STAGING / "convert", STAGING / ".conv"
REPLACE_DIR = STAGING / "replace"        # finished converting, waiting to be written back (replaces the original)

SEG_MIN_SECONDS = 600       # shorter titles are not split into segments
LOCK_TTL = 300              # seconds without a heartbeat, after that a lock counts as orphaned
LIB_EXT = (".mkv", ".iso", ".m2ts")
LIB_CODECS = ("h264", "vc1", "mpeg2video", "mpeg4", "wmv3")     # these are offered as "original"

X265_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
# Defaults for "looks like the original, but needs only a fraction of the space"
CONVERT_DEFAULT = {"convert": False, "rf": 21, "preset": "slow", "tune": "none", "extra": "aq-mode=3:no-sao=1", "audio": "copy"}
PRESET_DEFAULTS = {"bluray": dict(CONVERT_DEFAULT), "dvd": dict(CONVERT_DEFAULT)}      # "convert" is off by default; the interface also starts it off for every disc

DEFAULTS = {
    "minlength": 120,      # seconds, shorter titles are ignored
    "auto_scan": True,     # analyze an inserted disc right away
    "auto_eject": True,    # eject after a successful rip
    "audio_langs": "",     # e.g. "eng,deu" – empty = all
    "sub_langs": "",       # e.g. "eng"     – empty = all
    "key": "",             # own MakeMKV key; empty = public beta key
    "conv_parallel": 1,                    # simultaneous conversions (several files)
    "conv_segments": 0,                    # segments per movie: 0 = automatic by free cores/RAM, 1 = off, >1 = fixed
    "presets": PRESET_DEFAULTS,  # conversion preset per disc type (changeable in the interface)
}

# do not show virtual drives (e.g. CDEmu, VMs); environment variable HIDE_DRIVES = regex, empty = hide nothing
HIDE_RE = re.compile(os.environ.get("HIDE_DRIVES", r"cdemu|virtual|qemu|vbox"), re.I) if os.environ.get("HIDE_DRIVES", "x") else None
