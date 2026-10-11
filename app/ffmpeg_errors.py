"""ffmpeg-Fehlerausgabe in eine verständliche Ursache übersetzen (für die Auftragsliste).

ffmpeg schreibt die eigentliche Ursache oft weit vor die letzten Zeilen („CreateInputBuffer failed: out of memory“ steht vor
„Invalid argument … Conversion failed!“). `message()` sucht in allen gesammelten Zeilen nach bekannten Mustern und stellt die Ursache
samt der passenden ffmpeg-Zeile voran; unbekannte Fehler bleiben wie bisher (letzte Zeilen).
"""
import re
import shutil
import subprocess


def gpu_memory() -> tuple[float, float] | None:
    """(belegt, gesamt) in GB der ersten NVIDIA-Karte, oder None. Welche Programme belegen, sieht man im Container nicht."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        used, total = (float(x) / 1024 for x in out.splitlines()[0].split(","))
        return used, total
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def _gb(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _nvenc_memory(_m) -> str:
    mem = gpu_memory()
    if mem and mem[1] - mem[0] < 1.5:
        return (f"Grafikspeicher der NVIDIA-Karte ist voll ({_gb(mem[0])} von {_gb(mem[1])} GB belegt, durch andere Programme) – "
                "NVENC kann den Encoder nicht anlegen. Grafikspeicher freigeben oder ein Preset ohne NVIDIA wählen.")
    return ("NVENC meldet „zu wenig Speicher“: Grafikspeicher voll oder zu viele gleichzeitige NVENC-Sitzungen"
            + (f" ({_gb(mem[0])} von {_gb(mem[1])} GB belegt)" if mem else "") + ". Weniger Konvertierungen gleichzeitig oder Grafikspeicher freigeben.")


PATTERNS = [
    (re.compile(r"(CreateInputBuffer|CreateBitstreamBuffer|OpenEncodeSessionEx|InitializeEncoder)\w* failed: out of memory|CUDA_ERROR_OUT_OF_MEMORY", re.I),
     _nvenc_memory),
    (re.compile(r"No capable devices found|Cannot load libnvidia-encode|Cannot load libcuda|OpenEncodeSessionEx failed: (unsupported device|no encode device)"
                r"|Driver does not support the required nvenc API version", re.I),
     lambda m: "NVIDIA-Karte bzw. Treiber ist für NVENC nicht nutzbar (Karte nicht in den Container durchgereicht oder Treiber zu alt)."),
    (re.compile(r"Failed to initialise VAAPI connection|Failed to create a VAAPI device|No VA display found", re.I),
     lambda m: "VAAPI-Gerät (/dev/dri) ist nicht nutzbar – Grafikgerät nicht durchgereicht oder Gruppe render fehlt."),
    (re.compile(r"No space left on device", re.I),
     lambda m: "Kein Platz mehr im Zwischenspeicher bzw. im Ziel."),
    (re.compile(r"Unrecognized option '([^']+)'|Option (\S+) not found", re.I),
     lambda m: f"Unbekannter ffmpeg-Parameter „{m.group(1) or m.group(2)}“ – freie Encoder-Parameter im Preset prüfen."),
    (re.compile(r"Invalid data found when processing input|EBML header parsing failed|moov atom not found", re.I),
     lambda m: "Quelldatei ist beschädigt oder unvollständig."),
    (re.compile(r"Permission denied", re.I),
     lambda m: "Keine Berechtigung zum Lesen oder Schreiben der Datei."),
]


def explain(lines) -> tuple[str, str]:
    """(Ursache, ffmpeg-Zeile) für die erste erkannte Ursache, sonst ("", "")."""
    lines = [x for x in lines if x]
    for rx, text in PATTERNS:
        for line in lines:
            m = rx.search(line)
            if m:
                return text(m), re.sub(r"^\[[^\]]*@ 0x[0-9a-f]+\]\s*", "", line)[:200]
    return "", ""


def message(prefix: str, lines, tail: int = 4) -> str:
    lines = list(lines)
    why, line = explain(lines)
    if why:
        return f"{prefix}: {why} (ffmpeg: {line})"
    return f"{prefix}: " + " | ".join(lines[-tail:])
