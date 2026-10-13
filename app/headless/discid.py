"""Identifiers of a disc for matching with TheDiscDB (thediscdb.com), calculated the way it does (TheDiscDb.Core/DiscHash):

- Disc ID (per pressing): Blu-ray/UHD = SHA-1 over AACS/Unit_Key_RO.inf; DVD = MD5 over VIDEO_TS.IFO and the VTS_xx_0.IFO (like libdvdread).
- Content hash (MakeMKV method): MD5 over the file sizes (8 bytes each, little endian), sorted by file name –
  Blu-ray: all *.m2ts in BDMV/STREAM, DVD: all files in VIDEO_TS.

Also the total size of the video data (upper limit when ripping "unsure" discs).
"""
import hashlib
import re
import struct

from app.headless.udf import Udf, UdfError

DVD_MAX_IFO = 10            # libdvdread: VIDEO_TS.IFO + at most 9 title sets


def content_hash(files: list[tuple[str, int]]) -> str:
    """files: [(name, size)]. Sorted like .NET OrderBy(Name) for these names (only capital letters, digits, _ and .)."""
    sizes = [size for _name, size in sorted(files)]
    return hashlib.md5(b"".join(struct.pack("<q", s) for s in sizes)).hexdigest().upper()


def aacs_disc_id(unit_key_ro: bytes) -> str:
    return hashlib.sha1(unit_key_ro).hexdigest().upper()


def dvd_disc_id(video_ts_ifo: bytes, vts_ifos: list[bytes | None]) -> str:
    """vts_ifos[0] = VTS_01_0.IFO … (None = missing, skipped)."""
    if len(video_ts_ifo) < 0x40:
        raise ValueError("VIDEO_TS.IFO too small")
    title_sets = min(((video_ts_ifo[0x3E] << 8) | video_ts_ifo[0x3F]) + 1, DVD_MAX_IFO)
    h = hashlib.md5(video_ts_ifo)
    for i in range(title_sets - 1):
        if i < len(vts_ifos) and vts_ifos[i] is not None:
            h.update(vts_ifos[i])
    return h.hexdigest().upper()


def identify(fs: Udf) -> dict:
    """Result: {format: bluray|dvd|None, disc_id, content_hash, content_bytes, files, error}."""
    out = {"format": None, "disc_id": "", "content_hash": "", "content_bytes": 0, "files": 0, "error": ""}
    stream = fs.find("BDMV/STREAM")
    if stream and stream.is_dir:
        files = [(e.name, fs.size(e)) for e in fs.listdir(stream) if not e.is_dir and e.name.lower().endswith(".m2ts")]
        if not files:
            out["error"] = "BDMV/STREAM is empty"
            return out
        out.update(format="bluray", content_hash=content_hash(files), content_bytes=sum(s for _n, s in files), files=len(files))
        uk = fs.find("AACS/Unit_Key_RO.inf") or fs.find("AACS/DUPLICATE/Unit_Key_RO.inf")
        if uk:
            try:
                out["disc_id"] = aacs_disc_id(fs.read(uk))
            except (UdfError, OSError) as e:
                out["error"] = f"Unit_Key_RO.inf not readable: {e}"
        return out
    vts = fs.find("VIDEO_TS")
    if vts and vts.is_dir:
        entries = [e for e in fs.listdir(vts) if not e.is_dir]
        files = [(e.name, fs.size(e)) for e in entries]
        if not files:
            out["error"] = "VIDEO_TS is empty"
            return out
        out.update(format="dvd", content_hash=content_hash(files), files=len(files),
                   content_bytes=sum(s for n, s in files if n.upper().endswith(".VOB")))
        by_name = {e.name.upper(): e for e in entries}
        try:
            main = by_name.get("VIDEO_TS.IFO")
            if main:
                head = fs.read(main)
                count = min((head[0x3E] << 8) | head[0x3F], DVD_MAX_IFO - 1) if len(head) >= 0x40 else 0
                ifos = []
                for n in range(1, count + 1):
                    e = by_name.get(f"VTS_{n:02d}_0.IFO")
                    ifos.append(fs.read(e) if e else None)
                out["disc_id"] = dvd_disc_id(head, ifos)
        except (UdfError, OSError, ValueError) as e:
            out["error"] = f"IFO files not readable: {e}"
        return out
    out["error"] = "neither BDMV nor VIDEO_TS found"
    return out


def valid_hex(s: str, lengths=(32, 40)) -> bool:
    return bool(s) and len(s) in lengths and re.fullmatch(r"[0-9A-F]+", s) is not None
