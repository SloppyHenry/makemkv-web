"""Ejecting: if the drive refuses CDROMEJECT (positive SCSI status), the SCSI path is used like `eject`."""
import unittest
from unittest import mock

from tests import env  # noqa: F401

from app import drives


class TrayTest(unittest.TestCase):
    def _tray(self, req, ioctl_result):
        with mock.patch.object(drives, "DEV_DRIVE_DIR", ""), mock.patch.object(drives.os, "open", return_value=99), \
                mock.patch.object(drives.os, "close"), mock.patch.object(drives.fcntl, "ioctl", return_value=ioctl_result), \
                mock.patch.object(drives.scsi, "eject") as ej:
            drives.tray("/dev/sr0", req)
        return ej

    def test_eject_ok_without_scsi(self):
        self.assertFalse(self._tray(drives.CDROM_EJECT, 0).called)

    def test_eject_check_condition_uses_scsi(self):
        """Panasonic UJ240 in a USB enclosure (vierstein): CDROMEJECT -> 2, the disc stays in."""
        self.assertEqual(self._tray(drives.CDROM_EJECT, 2).call_args.args, ("/dev/sr0",))

    def test_close_refused_raises(self):
        with self.assertRaises(OSError):
            self._tray(drives.CDROM_CLOSE_TRAY, 2)


if __name__ == "__main__":
    unittest.main()
