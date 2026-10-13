"""Tests for app/ffmpeg_errors.py (making ffmpeg errors understandable)."""
import unittest
from unittest import mock

from tests import env  # noqa: F401

from app import ffmpeg_errors as fe

# real output from maintux (RTX 3080, graphics memory taken by other programs)
NVENC_OOM = ["[hevc_nvenc @ 0x63f960d5b900] CreateInputBuffer failed: out of memory (10): ",
             "[vost#0:0/hevc_nvenc @ 0x63f960dc41c0] Error while opening encoder - maybe incorrect parameters such as bit_rate, rate, width or height.",
             "[vf#0:0 @ 0x63f960df2600] Error sending frames to consumers: Cannot allocate memory",
             "[vost#0:0/hevc_nvenc @ 0x627dbb6c6600] Terminating thread with return code -22 (Invalid argument)",
             "[out#0/matroska @ 0x627dbb69cbc0] Nothing was written into output file, because at least one of its streams received no packets.",
             "frame=    0 fps=0.0 q=0.0 Lsize=       0KiB time=N/A bitrate=N/A speed=N/A", "Conversion failed!"]


class ExplainTest(unittest.TestCase):
    def test_nvenc_memory_full(self):
        with mock.patch.object(fe, "gpu_memory", return_value=(9.3, 10.0)):
            m = fe.message("ffmpeg failed", NVENC_OOM)
        self.assertTrue(m.startswith("ffmpeg failed: The NVIDIA card's graphics memory is full (9.3 of 10.0 GB used"), m)
        self.assertIn("(ffmpeg: CreateInputBuffer failed: out of memory (10):", m)

    def test_nvenc_sessions_when_memory_free(self):
        with mock.patch.object(fe, "gpu_memory", return_value=(2.0, 10.0)):
            self.assertIn("too many simultaneous NVENC sessions", fe.message("x", NVENC_OOM))

    def test_unknown_keeps_tail(self):
        self.assertEqual(fe.message("ffmpeg failed", ["a", "b", "c", "d", "e"]), "ffmpeg failed: b | c | d | e")

    def test_other_patterns(self):
        self.assertIn("\"-foo\"", fe.message("x", ["Unrecognized option '-foo'."]))
        self.assertIn("No space left", fe.message("x", ["av_interleaved_write_frame(): No space left on device"]))
        self.assertIn("VAAPI", fe.message("x", ["[AVHWDeviceContext @ 0x1] Failed to initialise VAAPI connection: -1 (unknown libva error)."]))


if __name__ == "__main__":
    unittest.main()
