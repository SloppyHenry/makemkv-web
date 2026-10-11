"""Winzige UDF-Abbilder für Tests: UDF 1.02 (nur physische Partition, File Entries) oder 2.50 (Metadaten-Partition, Extended File Entries).

files: {"BDMV/STREAM/00000.m2ts": 123456 (nur Größe, kein Inhalt) | b"…" (Inhalt)}. Verzeichnisse entstehen aus den Pfaden.
"""
import struct

B = 2048
PART_START, META_LBN, DATA_LBN = 300, 10, 200      # Partition ab Block 300; Metadaten ab Partitionsblock 10; Dateiinhalte ab 200


def _tag(buf: bytearray, tag_id: int, loc: int):
    struct.pack_into("<HHBBHHHI", buf, 0, tag_id, 3, 0, 0, 0, 0, 0, loc)
    buf[4] = (sum(buf[0:4]) + sum(buf[5:16])) & 0xFF


def _fe(ext: bool, ftype: int, size: int, ads: bytes, ad_type: int, loc: int) -> bytearray:
    b = bytearray(B)
    struct.pack_into("<HH", b, 20, 4, 0)
    struct.pack_into("<H", b, 24, 1)
    b[27] = ftype
    struct.pack_into("<H", b, 34, ad_type)
    struct.pack_into("<Q", b, 56, size)
    base, la = (216, 208) if ext else (176, 168)
    struct.pack_into("<II", b, la, 0, len(ads))
    b[base:base + len(ads)] = ads
    _tag(b, 266 if ext else 261, loc)
    return b


def _fid(name: str, is_dir: bool, parent: bool, lbn: int, ref: int) -> bytes:
    raw = b"" if parent else b"\x08" + name.encode("latin-1")
    ln = (38 + len(raw) + 3) & ~3
    b = bytearray(ln)
    struct.pack_into("<HBB", b, 16, 1, (0x02 if is_dir else 0) | (0x08 if parent else 0), len(raw))
    struct.pack_into("<IIH", b, 20, B, lbn, ref)
    b[38:38 + len(raw)] = raw
    _tag(b, 257, 0)
    return bytes(b)


def build(files: dict, version: str = "2.50") -> bytes:
    meta = version >= "2.50"
    tree: dict = {}
    for path, content in files.items():
        node = tree
        parts = path.split("/")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = content
    mref = 1 if meta else 0                        # Partitionsverweis für Verwaltungsdaten
    mbase = 0 if meta else META_LBN                # erster Block der Verwaltungsdaten in dieser Partition
    blocks: dict[int, bytes] = {}                  # absoluter Block -> Inhalt
    nxt = {"meta": mbase + 2, "data": DATA_LBN}    # mbase: FSD, mbase+1: Wurzel-FE

    def mabs(lbn):
        return PART_START + (META_LBN + lbn if meta else lbn)

    def put_dir(node: dict, fe_lbn: int, parent_lbn: int):
        fids, children = [_fid("", True, True, parent_lbn, mref)], []
        for name, sub in sorted(node.items()):
            lbn = nxt["meta"]
            nxt["meta"] += 1
            fids.append(_fid(name, isinstance(sub, dict), False, lbn, mref))
            children.append((name, sub, lbn))
        data = b"".join(fids)
        dlbn = nxt["meta"]
        nxt["meta"] += (len(data) + B - 1) // B
        for k in range(0, len(data), B):
            blocks[mabs(dlbn + k // B)] = data[k:k + B]
        blocks[mabs(fe_lbn)] = bytes(_fe(meta, 4, len(data), struct.pack("<II", len(data), dlbn), 0, fe_lbn))
        for _name, sub, lbn in children:
            if isinstance(sub, dict):
                put_dir(sub, lbn, fe_lbn)
                continue
            size = sub if isinstance(sub, int) else len(sub)
            dl = nxt["data"]
            if isinstance(sub, bytes):
                for k in range(0, len(sub), B):
                    blocks[PART_START + dl + k // B] = sub[k:k + B]
                nxt["data"] += (len(sub) + B - 1) // B or 1
            else:
                nxt["data"] += 1
            ad = struct.pack("<IIH6x", min(size, 0x3FFFFFFF), dl, 0)          # long_ad in die physische Partition
            blocks[mabs(lbn)] = bytes(_fe(meta, 5, size, ad, 1, lbn))

    put_dir(tree, mbase + 1, mbase + 1)
    fsd = bytearray(B)
    struct.pack_into("<IIH", fsd, 400, B, mbase + 1, mref)
    _tag(fsd, 256, mbase)
    blocks[mabs(mbase)] = bytes(fsd)
    if meta:                                        # Metadaten-Datei (und Spiegel) in der physischen Partition: ein Extent ab META_LBN
        ln = (nxt["meta"] + 1) * B
        for lbn, ft in ((0, 250), (1, 251)):
            blocks[PART_START + lbn] = bytes(_fe(True, ft, ln, struct.pack("<II", ln, META_LBN), 0, lbn))
    avdp = bytearray(B)
    struct.pack_into("<II", avdp, 16, 16 * B, 32)
    _tag(avdp, 2, 256)
    pd = bytearray(B)
    struct.pack_into("<H", pd, 22, 0)
    struct.pack_into("<II", pd, 188, PART_START, 100000)
    _tag(pd, 5, 32)
    lvd = bytearray(B)
    struct.pack_into("<I", lvd, 212, B)
    struct.pack_into("<IIH", lvd, 248, B, mbase, mref)
    maps = struct.pack("<BBHH", 1, 6, 1, 0)
    if meta:
        m = bytearray(64)
        m[0], m[1] = 2, 64
        m[5:5 + 23] = b"*UDF Metadata Partition"
        struct.pack_into("<HHIII", m, 36, 1, 0, 0, 1, 0xFFFFFFFF)
        maps += bytes(m)
    struct.pack_into("<II", lvd, 264, len(maps), 2 if meta else 1)
    lvd[440:440 + len(maps)] = maps
    _tag(lvd, 6, 33)
    td = bytearray(B)
    _tag(td, 8, 34)
    blocks.update({256: bytes(avdp), 32: bytes(pd), 33: bytes(lvd), 34: bytes(td)})
    img = bytearray((max(blocks) + 1) * B)
    for lba, data in blocks.items():
        img[lba * B:lba * B + len(data)] = data
    return bytes(img)
