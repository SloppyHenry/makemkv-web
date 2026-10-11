"""Kleiner Leser für das UDF-Dateisystem von DVD und Blu-ray: Verzeichnisse auflisten, Dateigrößen, kleine Dateien lesen.

Liest direkt vom Gerät (ohne Einhängen, der Container darf das nicht) oder aus einer Abbilddatei. Das Dateisystem selbst ist auf
kopiergeschützten Discs nicht verschlüsselt; gelesen werden nur Verwaltungsdaten und kleine Dateien (IFO, Unit_Key_RO.inf).
Unterstützt UDF 1.02–2.60 mit Typ-1-Partition und (Blu-ray, UDF 2.50) Metadaten-Partition. Vorbild ist libudfread (VLC/libbluray):
Verwaltungsdaten (File Entries, Verzeichnisse) liegen in der Partition des Verweises, Dateiinhalte immer in der physischen Partition.
"""
import os
import struct
from dataclasses import dataclass

BLOCK = 2048
TAG_AVDP, TAG_PD, TAG_LVD, TAG_TD, TAG_FSD, TAG_FID, TAG_AED, TAG_FE, TAG_EFE = 2, 5, 6, 8, 256, 257, 258, 261, 266
FT_DIR, FT_FILE, FT_METADATA, FT_METADATA_MIRROR = 4, 5, 250, 251


class UdfError(Exception):
    pass


@dataclass
class Entry:
    name: str
    is_dir: bool
    ref: int        # Partitionsverweis (Index der Partition Map) der ICB
    lba: int        # Block der ICB innerhalb dieser Partition


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _tag(b) -> int:
    if len(b) < 16 or (sum(b[0:4]) + sum(b[5:16])) & 0xFF != b[4]:
        return -1
    return _u16(b, 0)


def _dstring(raw: bytes) -> str:
    """OSTA-CS0: erstes Byte 8 = 8 Bit je Zeichen, 16 = UTF-16BE."""
    if not raw:
        return ""
    if raw[0] == 16:
        return raw[1:].decode("utf-16-be", "replace")
    return raw[1:].decode("latin-1")


class Udf:
    def __init__(self, read_blocks):
        """read_blocks(lba, n) -> bytes (n * 2048)."""
        self._read = read_blocks
        self.phys_start = None
        self.part_base: dict[int, int] = {}       # Partitionsverweis -> absoluter Startblock (Metadaten: Start der Metadaten-Datei)
        self.mirror_base: dict[int, int] = {}
        self.phys_refs: set[int] = set()
        self._mount()

    # ------------------------------------------------------------ Datenträger
    def _block(self, lba: int, n: int = 1) -> bytes:
        b = self._read(lba, n)
        if len(b) < n * BLOCK:
            raise UdfError(f"Block {lba} nicht lesbar")
        return b

    def _mount(self):
        avdp = self._block(256)
        if _tag(avdp) != TAG_AVDP:
            raise UdfError("kein UDF-Dateisystem (Anker an Block 256 fehlt)")
        length, loc = _u32(avdp, 16), _u32(avdp, 20)
        pd, lvd = None, None
        for i in range(max(1, min(length // BLOCK, 64))):
            b = self._block(loc + i)
            t = _tag(b)
            if t == TAG_PD and pd is None:
                pd = b
            elif t == TAG_LVD and lvd is None:
                lvd = b
            elif t == TAG_TD:
                break
        if pd is None or lvd is None:
            raise UdfError("Partitions- oder Volume-Beschreibung fehlt")
        if _u32(lvd, 212) != BLOCK:
            raise UdfError("unerwartete Blockgröße")
        pd_number, self.phys_start = _u16(pd, 22), _u32(pd, 188)
        self._maps(lvd, pd_number)
        self.fsd_ref, self.fsd_lba = _u16(lvd, 256), _u32(lvd, 252)

    def _maps(self, lvd: bytes, pd_number: int):
        table_len, count = _u32(lvd, 264), _u32(lvd, 268)
        m, end = 440, 440 + min(table_len, BLOCK - 440)
        meta = []
        for i in range(count):
            if m + 2 > end:
                break
            typ, ln = lvd[m], lvd[m + 1]
            if ln < 2:
                break
            if typ == 1 and ln == 6:
                self.part_base[i] = self.phys_start
                self.phys_refs.add(i)
            elif typ == 2 and ln == 64:
                ident = lvd[m + 5:m + 28].rstrip(b"\0 ")
                if ident.startswith(b"*UDF Metadata Partition"):
                    meta.append((i, _u32(lvd, m + 40), _u32(lvd, m + 44)))
                elif ident.startswith(b"*UDF Sparable Partition"):      # Datenträger mit Ersatzbereichen: wie physisch behandeln
                    self.part_base[i] = self.phys_start
                    self.phys_refs.add(i)
            m += ln
        if not self.phys_refs:
            raise UdfError("keine physische Partition")
        for ref, loc, mirror in meta:
            self._map_metadata(ref, loc, mirror)

    def _map_metadata(self, ref: int, loc: int, mirror: int):
        for which, lba in (("main", loc), ("mirror", mirror)):
            try:
                b = self._block(self.phys_start + lba)
            except UdfError:
                continue
            if _tag(b) not in (TAG_FE, TAG_EFE):
                continue
            fe = self._parse_fe(b, ref)
            if fe["ads"] and fe["type"] in (FT_METADATA, FT_METADATA_MIRROR):
                start = self.phys_start + fe["ads"][0][1]
                if fe["type"] == FT_METADATA:
                    self.part_base[ref] = start
                else:
                    self.mirror_base[ref] = start
        if ref not in self.part_base and ref in self.mirror_base:
            self.part_base[ref] = self.mirror_base.pop(ref)
        if ref not in self.part_base:
            raise UdfError("Metadaten-Partition nicht lesbar")

    def _meta_blocks(self, ref: int, lba: int, n: int = 1) -> bytes:
        """Verwaltungsdaten lesen (bei Lesefehler aus der Spiegelkopie)."""
        if ref not in self.part_base:
            raise UdfError(f"unbekannte Partition {ref}")
        try:
            return self._block(self.part_base[ref] + lba, n)
        except (UdfError, OSError):
            if ref in self.mirror_base:
                return self._block(self.mirror_base[ref] + lba, n)
            raise

    # ------------------------------------------------------------ File Entries
    def _parse_fe(self, b: bytes, ref: int) -> dict:
        tag = _tag(b)
        if tag == TAG_FE:
            l_ea, l_ad, base = _u32(b, 168), _u32(b, 172), 176
        elif tag == TAG_EFE:
            l_ea, l_ad, base = _u32(b, 208), _u32(b, 212), 216
        else:
            raise UdfError(f"kein File Entry (Tag {tag})")
        ftype, ad_type = b[27], _u16(b, 34) & 7
        size = struct.unpack_from("<Q", b, 56)[0]
        start = base + l_ea
        if start + l_ad > len(b):
            raise UdfError("File Entry beschädigt")
        if ad_type == 3:
            return {"type": ftype, "size": size, "inline": bytes(b[start:start + l_ad]), "ads": []}
        return {"type": ftype, "size": size, "inline": None, "ads": self._ads(b[start:start + l_ad], ad_type, ref)}

    def _ads(self, raw: bytes, ad_type: int, ref: int, depth: int = 0) -> list[tuple[int, int, int]]:
        """Allocation Descriptors -> [(Partitionsverweis, Block, Länge in Bytes)]; Fortsetzungen werden nachgelesen."""
        out, step = [], {0: 8, 1: 16, 2: 20}.get(ad_type)
        if step is None:
            raise UdfError(f"unbekannte Belegungsart {ad_type}")
        for o in range(0, len(raw) - step + 1, step):
            v = _u32(raw, o)
            length, kind = v & 0x3FFFFFFF, v >> 30
            if length == 0:
                break
            if ad_type == 0:
                lba, pref = _u32(raw, o + 4), ref
            elif ad_type == 1:
                lba, pref = _u32(raw, o + 4), _u16(raw, o + 8)
            else:
                lba, pref = _u32(raw, o + 12), _u16(raw, o + 16)
            if kind == 3:                                   # weitere Descriptoren in einem eigenen Block
                if depth > 8:
                    raise UdfError("zu viele Fortsetzungen")
                b = self._meta_blocks(pref, lba)
                if _tag(b) != TAG_AED:
                    raise UdfError("Fortsetzung der Belegung beschädigt")
                out += self._ads(b[24:24 + _u32(b, 20)], ad_type, ref, depth + 1)
                break
            if kind == 0:
                out.append((pref, lba, length))
        return out

    def _fe(self, e: Entry) -> dict:
        return self._parse_fe(self._meta_blocks(e.ref, e.lba), e.ref)

    # ------------------------------------------------------------ Verzeichnisse
    def root(self) -> Entry:
        fsd = self._meta_blocks(self.fsd_ref, self.fsd_lba)
        if _tag(fsd) != TAG_FSD:
            raise UdfError("File Set Descriptor fehlt")
        return Entry("", True, _u16(fsd, 400 + 8), _u32(fsd, 400 + 4))

    def _dir_bytes(self, fe: dict) -> bytes:
        if fe["inline"] is not None:
            return fe["inline"][:fe["size"]]
        out = bytearray()
        for ref, lba, length in fe["ads"]:
            out += self._meta_blocks(ref, lba, (length + BLOCK - 1) // BLOCK)[:length]
        return bytes(out[:fe["size"]])

    def listdir(self, d: Entry) -> list[Entry]:
        fe = self._fe(d)
        if fe["type"] != FT_DIR:
            raise UdfError(f"{d.name or '/'} ist kein Verzeichnis")
        raw, o, out = self._dir_bytes(fe), 0, []
        while o + 38 <= len(raw):
            if _u16(raw, o) != TAG_FID:
                break
            chars, l_fi, l_iu = raw[o + 18], raw[o + 19], _u16(raw, o + 36)
            icb_lba, icb_ref = _u32(raw, o + 24), _u16(raw, o + 28)
            name = _dstring(raw[o + 38 + l_iu:o + 38 + l_iu + l_fi])
            if not chars & 0x0C and name:                   # nicht gelöscht, kein Elternverweis
                out.append(Entry(name, bool(chars & 0x02), icb_ref, icb_lba))
            o += (38 + l_iu + l_fi + 3) & ~3
        return out

    def find(self, path: str) -> Entry | None:
        """Pfad wie „BDMV/STREAM“ ohne Rücksicht auf Groß-/Kleinschreibung."""
        e = self.root()
        for part in [p for p in path.split("/") if p]:
            if not e.is_dir:
                return None
            e = next((x for x in self.listdir(e) if x.name.upper() == part.upper()), None)
            if e is None:
                return None
        return e

    def size(self, e: Entry) -> int:
        return self._fe(e)["size"]

    def read(self, e: Entry, limit: int = 16 * 2**20) -> bytes:
        """Kleine Datei lesen. Dateiinhalte liegen immer in der physischen Partition."""
        fe = self._fe(e)
        if fe["size"] > limit:
            raise UdfError(f"{e.name} ist zu groß ({fe['size']} Bytes)")
        if fe["inline"] is not None:
            return fe["inline"][:fe["size"]]
        out = bytearray()
        for _ref, lba, length in fe["ads"]:
            out += self._block(self.phys_start + lba, (length + BLOCK - 1) // BLOCK)[:length]
        return bytes(out[:fe["size"]])


def open_device(path: str):
    """Gerät oder Abbild öffnen. Rückgabe (Udf, close)."""
    fd = os.open(path, os.O_RDONLY)

    def read_blocks(lba: int, n: int) -> bytes:
        return os.pread(fd, n * BLOCK, lba * BLOCK)

    try:
        return Udf(read_blocks), lambda: os.close(fd)
    except BaseException:
        os.close(fd)
        raise
