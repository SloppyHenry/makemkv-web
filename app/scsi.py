"""SCSI-Befehle direkt ans Laufwerk (SG_IO), für das, was die cdrom-ioctls nicht schaffen.

Auswerfen wie das Werkzeug `eject` im SCSI-Weg: Entnahme erlauben, Start, Stopp mit Auswerfen. Nötig z. B. beim Panasonic UJ240
im USB-Gehäuse: CDROMEJECT liefert dort SCSI-Status 2 (Check Condition) zurück, die Disc bleibt drin.
START STOP UNIT und PREVENT ALLOW MEDIUM REMOVAL darf jeder mit Schreibrecht aufs Gerät senden (Gruppe cdrom), ohne Root.
"""
import ctypes
import fcntl
import os

SG_IO = 0x2285
SG_DXFER_NONE = -1


class _SgIoHdr(ctypes.Structure):
    _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int), ("cmd_len", ctypes.c_ubyte),
                ("mx_sb_len", ctypes.c_ubyte), ("iovec_count", ctypes.c_ushort), ("dxfer_len", ctypes.c_uint),
                ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p), ("sbp", ctypes.c_void_p), ("timeout", ctypes.c_uint),
                ("flags", ctypes.c_uint), ("pack_id", ctypes.c_int), ("usr_ptr", ctypes.c_void_p), ("status", ctypes.c_ubyte),
                ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte), ("sb_len_wr", ctypes.c_ubyte),
                ("host_status", ctypes.c_ushort), ("driver_status", ctypes.c_ushort), ("resid", ctypes.c_int),
                ("duration", ctypes.c_uint), ("info", ctypes.c_uint)]


def command(fd: int, cdb: list[int], what: str, timeout_ms: int = 20000):
    """Befehl ohne Datenübertragung; OSError, wenn das Laufwerk ablehnt (mit Sense-Daten)."""
    c = (ctypes.c_ubyte * len(cdb))(*cdb)
    sb = (ctypes.c_ubyte * 32)()
    h = _SgIoHdr(interface_id=ord("S"), dxfer_direction=SG_DXFER_NONE, cmd_len=len(cdb), mx_sb_len=len(sb),
                 cmdp=ctypes.addressof(c), sbp=ctypes.addressof(sb), timeout=timeout_ms)
    fcntl.ioctl(fd, SG_IO, h)
    if h.status or h.host_status or h.driver_status:
        s = bytes(sb[:h.sb_len_wr])
        sense = f", Sense {s[2] & 0xF:X}/{s[12]:02X}/{s[13]:02X}" if len(s) > 13 else ""
        raise OSError(f"{what}: Laufwerk lehnt ab (Status {h.status:#x}{sense})")


def eject(dev: str):
    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    try:
        command(fd, [0x1E, 0, 0, 0, 0, 0], "Entnahme erlauben")
        command(fd, [0x1B, 0, 0, 0, 1, 0], "Start")
        command(fd, [0x1B, 0, 0, 0, 2, 0], "Auswerfen")
    finally:
        os.close(fd)
