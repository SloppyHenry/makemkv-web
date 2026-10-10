"""Gemeinsame Testumgebung: eigene Ordner, bevor `app` importiert wird. Aufruf: python3 -m unittest discover -s tests -t . -v"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="mkw-test-f-"))
os.environ.update(DATA_DIR=str(TMP / "data"), STAGING_DIR=str(TMP / "staging"), OUTPUT_DIR=str(TMP / "out"), FALLBACK_DIR=str(TMP / "out"),
                  OUTPUT_MOUNT=str(TMP / "nomount"), INSTANCE_NAME="test-f")
sys.path.insert(0, str(ROOT))
SAMPLES = Path(os.environ.get("MKW_SAMPLES", os.path.join(os.environ.get("MKW_DEV_DIR", os.path.join(os.environ.get("TMPDIR", "/tmp"), "mkw-dev-f")), "samples-cache")))
