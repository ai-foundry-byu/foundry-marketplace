import tempfile
import unittest
import zlib
import struct
from pathlib import Path

import _paths  # noqa: F401
import visual_baseline as vb


def solid(w, h, rgb):
    return [bytes(rgb) * w for _ in range(h)]


def write_png(path, w, h, rows):
    path.write_bytes(vb.encode_png(w, h, rows))


def png_with_filter(w, h, rows_rgba, ftype):
    """Hand-build an RGBA PNG using one filter type, to exercise the decoder."""
    bpp = 4
    raw = b""
    prev = bytes(w * bpp)
    for row in rows_rgba:
        out = bytearray()
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = {0: 0, 1: a, 2: b, 3: (a + b) >> 1, 4: vb._paeth(a, b, c)}[ftype]
            out.append((x - pred) & 0xFF)
        raw += bytes([ftype]) + bytes(out)
        prev = row
    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return vb._PNG_SIG + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class TestPng(unittest.TestCase):
    def test_roundtrip(self):
        rows = [bytes(b for x in range(5) for b in (x * 7 % 256, y * 13 % 256, (x + y) % 256)) for y in range(4)]
        w, h, back = vb.decode_png(vb.encode_png(5, 4, rows))
        self.assertEqual((w, h), (5, 4))
        self.assertEqual(back, rows)

    def test_all_filters_rgba(self):
        w, h = 6, 5
        rgba = [bytes(b for x in range(w) for b in ((x * 40 + y) % 256, (y * 50) % 256, (x * y * 9) % 256, 255))
                for y in range(h)]
        expected = [bytes(b for i in range(0, len(r), 4) for b in r[i:i + 3]) for r in rgba]
        for f in range(5):
            with self.subTest(filter=f):
                _, _, rows = vb.decode_png(png_with_filter(w, h, rgba, f))
                self.assertEqual(rows, expected)

    def test_rejects_non_png(self):
        with self.assertRaises(vb.PngError):
            vb.decode_png(b"GIF89a....")


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_identical_passes(self):
        write_png(self.d / "a.png", 10, 10, solid(10, 10, (10, 20, 30)))
        write_png(self.d / "b.png", 10, 10, solid(10, 10, (10, 20, 30)))
        r = vb.compare_images("x", self.d / "a.png", self.d / "b.png", self.d / "diff.png")
        self.assertEqual((r.status, r.diff_pixels), ("pass", 0))
        self.assertFalse((self.d / "diff.png").exists())

    def test_noise_under_tolerance_passes(self):
        write_png(self.d / "a.png", 10, 10, solid(10, 10, (100, 100, 100)))
        write_png(self.d / "b.png", 10, 10, solid(10, 10, (104, 100, 97)))
        r = vb.compare_images("x", self.d / "a.png", self.d / "b.png", self.d / "diff.png", tolerance=8)
        self.assertEqual(r.status, "pass")

    def test_change_over_threshold_fails_and_writes_diff(self):
        base = solid(10, 10, (255, 255, 255))
        cur = [bytearray(r) for r in base]
        for y in range(2):
            for x in range(10):
                cur[y][x * 3:x * 3 + 3] = b"\x00\x00\x00"
        write_png(self.d / "cur.png", 10, 10, [bytes(r) for r in cur])
        write_png(self.d / "base.png", 10, 10, base)
        r = vb.compare_images("x", self.d / "cur.png", self.d / "base.png", self.d / "diff.png", threshold=5.0)
        self.assertEqual(r.diff_pixels, 20)
        self.assertEqual(r.diff_percent, 20.0)
        self.assertEqual(r.status, "fail")
        _, _, drows = vb.decode_png((self.d / "diff.png").read_bytes())
        self.assertEqual(drows[0][:3], b"\xff\x00\x00")
        self.assertNotEqual(drows[5][:3], b"\xff\x00\x00")
        r2 = vb.compare_images("x", self.d / "cur.png", self.d / "base.png", self.d / "diff.png", threshold=25.0)
        self.assertEqual(r2.status, "pass")

    def test_size_change_fails(self):
        write_png(self.d / "a.png", 10, 12, solid(10, 12, (0, 0, 0)))
        write_png(self.d / "b.png", 10, 10, solid(10, 10, (0, 0, 0)))
        r = vb.compare_images("x", self.d / "a.png", self.d / "b.png", self.d / "diff.png")
        self.assertEqual(r.status, "fail")
        self.assertIn("size changed", r.message)

    def test_missing_baseline_is_inconclusive(self):
        write_png(self.d / "a.png", 4, 4, solid(4, 4, (0, 0, 0)))
        r = vb.compare_images("x", self.d / "a.png", self.d / "nope.png", self.d / "diff.png")
        self.assertEqual(r.status, "no-baseline")
        self.assertEqual(vb.verdict([r]), 6)

    def test_verdict(self):
        P, F, N = (vb.DiffResult("p", "pass"), vb.DiffResult("f", "fail"), vb.DiffResult("n", "no-baseline"))
        self.assertEqual(vb.verdict([P, P]), 0)
        self.assertEqual(vb.verdict([P, F, N]), 1)
        self.assertEqual(vb.verdict([P, N]), 6)
        self.assertEqual(vb.verdict([]), 6)

    def test_cli_compare_and_approve(self):
        root = self.d / "visual"
        (root / "current").mkdir(parents=True)
        write_png(root / "current" / "home-desktop-1440x900.png", 4, 4, solid(4, 4, (1, 2, 3)))
        self.assertEqual(vb.main(["compare", "--root", str(root)]), 6)   # no baseline yet
        self.assertEqual(vb.main(["approve", "--root", str(root)]), 0)
        self.assertEqual(vb.main(["compare", "--root", str(root)]), 0)
        write_png(root / "current" / "home-desktop-1440x900.png", 4, 4, solid(4, 4, (200, 2, 3)))
        self.assertEqual(vb.main(["compare", "--root", str(root)]), 1)
        self.assertEqual(vb.main(["compare", "--root", str(root), "--devices", "toaster"]), 2)


if __name__ == "__main__":
    unittest.main()
