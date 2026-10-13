"""SCSI commands sent directly to the drive (SG_IO), for what the cdrom ioctls cannot do.

Ejecting like the `eject` tool on its SCSI path: allow removal, start, stop with eject. Needed e.g. for the Panasonic UJ240
in a USB enclosure: there CDROMEJECT returns SCSI status 2 (check condition) and the disc stays in.
START STOP UNIT and PREVENT ALLOW MEDIUM REMOVAL may be sent by anyone with write access to the device (group cdrom), without root.
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
    """Command without data transfer; OSError if the drive refuses (with sense data)."""
    c = (ctypes.c_ubyte * len(cdb))(*cdb)
    sb = (ctypes.c_ubyte * 32)()
    h = _SgIoHdr(interface_id=ord("S"), dxfer_direction=SG_DXFER_NONE, cmd_len=len(cdb), mx_sb_len=len(sb),
                 cmdp=ctypes.addressof(c), sbp=ctypes.addressof(sb), timeout=timeout_ms)
    fcntl.ioctl(fd, SG_IO, h)
    if h.status or h.host_status or h.driver_status:
        s = bytes(sb[:h.sb_len_wr])
        sense = f", sense {s[2] & 0xF:X}/{s[12]:02X}/{s[13]:02X}" if len(s) > 13 else ""
        raise OSError(f"{what}: drive refuses (status {h.status:#x}{sense})")


def eject(dev: str):
    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    try:
        command(fd, [0x1E, 0, 0, 0, 0, 0], "Allow removal")
        command(fd, [0x1B, 0, 0, 0, 1, 0], "Start")
        command(fd, [0x1B, 0, 0, 0, 2, 0], "Eject")
    finally:
        os.close(fd)
