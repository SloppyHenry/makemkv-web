"""Translate ffmpeg error output into an understandable cause (for the job list).

ffmpeg often writes the actual cause well before the last lines ("CreateInputBuffer failed: out of memory" comes before
"Invalid argument … Conversion failed!"). `message()` searches all collected lines for known patterns and puts the cause
together with the matching ffmpeg line in front; unknown errors stay as before (last lines).
"""
import re
import shutil
import subprocess


def gpu_memory() -> tuple[float, float] | None:
    """(used, total) in GB of the first NVIDIA card, or None. Which programs use it cannot be seen from inside the container."""
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
    return f"{x:.1f}"


def _nvenc_memory(_m) -> str:
    mem = gpu_memory()
    if mem and mem[1] - mem[0] < 1.5:
        return (f"The NVIDIA card's graphics memory is full ({_gb(mem[0])} of {_gb(mem[1])} GB used by other programs) – "
                "NVENC cannot create the encoder. Free graphics memory or choose a preset without NVIDIA.")
    return ("NVENC reports \"out of memory\": graphics memory full or too many simultaneous NVENC sessions"
            + (f" ({_gb(mem[0])} of {_gb(mem[1])} GB used)" if mem else "") + ". Run fewer conversions at the same time or free graphics memory.")


PATTERNS = [
    (re.compile(r"(CreateInputBuffer|CreateBitstreamBuffer|OpenEncodeSessionEx|InitializeEncoder)\w* failed: out of memory|CUDA_ERROR_OUT_OF_MEMORY", re.I),
     _nvenc_memory),
    (re.compile(r"No capable devices found|Cannot load libnvidia-encode|Cannot load libcuda|OpenEncodeSessionEx failed: (unsupported device|no encode device)"
                r"|Driver does not support the required nvenc API version", re.I),
     lambda m: "The NVIDIA card or driver cannot be used for NVENC (card not passed through to the container or driver too old)."),
    (re.compile(r"Failed to initialise VAAPI connection|Failed to create a VAAPI device|No VA display found", re.I),
     lambda m: "The VAAPI device (/dev/dri) cannot be used – graphics device not passed through or the render group is missing."),
    (re.compile(r"No space left on device", re.I),
     lambda m: "No space left in the staging buffer or in the target."),
    (re.compile(r"Unrecognized option '([^']+)'|Option (\S+) not found", re.I),
     lambda m: f"Unknown ffmpeg parameter \"{m.group(1) or m.group(2)}\" – check the free encoder parameters in the preset."),
    (re.compile(r"Invalid data found when processing input|EBML header parsing failed|moov atom not found", re.I),
     lambda m: "The source file is damaged or incomplete."),
    (re.compile(r"Permission denied", re.I),
     lambda m: "No permission to read or write the file."),
]


def explain(lines) -> tuple[str, str]:
    """(cause, ffmpeg line) for the first recognized cause, otherwise ("", "")."""
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
