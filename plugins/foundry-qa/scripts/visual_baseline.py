#!/usr/bin/env python3
"""visual_baseline: screenshot baselines and pixel-diff regression checks.

Commands:
  capture  take screenshots of URLs on device profiles  -> .qa/visual/current/
  compare  diff current screenshots against baselines    -> .qa/visual/diff/
  check    capture, then compare (the everyday command)
  approve  copy current screenshots into the baseline set (a deliberate human step)

Exit codes (compare / check):
  0  every screenshot is within the threshold
  1  at least one screenshot differs beyond the threshold, or changed size
  2  config error (bad arguments, Playwright missing for capture)
  6  inconclusive: a screenshot has no baseline yet, or a page could not load.
     Not a pass. Review the screenshot and run `approve` to create the baseline.

Examples:
  python3 visual_baseline.py capture --url http://localhost:3000/ --name home --devices desktop-1440x900,phone-390x844
  python3 visual_baseline.py approve                    # first run: make the baselines
  python3 visual_baseline.py check --url http://localhost:3000/ --name home --devices desktop-1440x900,phone-390x844
  python3 visual_baseline.py compare --threshold 0.1 --tolerance 8

PNG decoding and diff images use only the standard library (zlib). If Pillow
is installed it is used for decoding, which is faster on large images.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_INCONCLUSIVE = 0, 1, 2, 6
DEFAULT_THRESHOLD = 0.1   # percent of pixels allowed to differ
DEFAULT_TOLERANCE = 8     # per-channel difference (0-255) below which a pixel counts as equal

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


class PngError(ValueError):
    pass


# ── minimal PNG codec ─────────────────────────────────────────────────────────

def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data: bytes) -> tuple[int, int, list[bytes]]:
    """Decode an 8-bit, non-interlaced PNG to (width, height, rows of RGB bytes)."""
    if not data.startswith(_PNG_SIG):
        raise PngError("not a PNG file")
    pos = 8
    width = height = 0
    bit_depth = color_type = interlace = -1
    palette = b""
    idat = []
    while pos < len(data):
        if pos + 8 > len(data):
            raise PngError("truncated chunk header")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"IDAT":
            idat.append(chunk)
        elif ctype == b"IEND":
            break
    if bit_depth != 8:
        raise PngError(f"only 8-bit PNGs are supported (got bit depth {bit_depth})")
    if interlace != 0:
        raise PngError("interlaced PNGs are not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PngError(f"unsupported color type {color_type}")
    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    bpp = channels
    rows: list[bytes] = []
    prev = bytearray(stride)
    p = 0
    for _ in range(height):
        ftype = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        elif ftype != 0:
            raise PngError(f"bad filter type {ftype}")
        rows.append(_to_rgb(bytes(line), color_type, palette))
        prev = line
    return width, height, rows


def _to_rgb(line: bytes, color_type: int, palette: bytes) -> bytes:
    if color_type == 2:
        return line
    if color_type == 6:
        out = bytearray()
        for i in range(0, len(line), 4):
            out += line[i:i + 3]
        return bytes(out)
    if color_type == 0:
        return bytes(b for g in line for b in (g, g, g))
    if color_type == 4:
        return bytes(b for i in range(0, len(line), 2) for b in (line[i],) * 3)
    if color_type == 3:
        return b"".join(palette[i * 3:i * 3 + 3] for i in line)
    raise PngError(f"unsupported color type {color_type}")


def encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    """Encode RGB rows as an 8-bit PNG (filter 0)."""
    def chunk(ctype: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return _PNG_SIG + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def load_rgb(path: Path) -> tuple[int, int, list[bytes]]:
    try:
        from PIL import Image  # optional speed-up
        img = Image.open(path).convert("RGB")
        w, h = img.size
        buf = img.tobytes()
        return w, h, [buf[y * w * 3:(y + 1) * w * 3] for y in range(h)]
    except ImportError:
        return decode_png(path.read_bytes())


# ── diff (pure, unit-tested) ──────────────────────────────────────────────────

@dataclass
class DiffResult:
    name: str
    status: str            # "pass" | "fail" | "no-baseline" | "error"
    diff_percent: float = 0.0
    diff_pixels: int = 0
    total_pixels: int = 0
    threshold: float = DEFAULT_THRESHOLD
    current: str = ""
    baseline: str = ""
    diff_image: str = ""
    message: str = ""


def diff_rows(a: list[bytes], b: list[bytes], width: int, tolerance: int) -> tuple[int, list[bytes]]:
    """Count differing pixels; return (count, diff image rows).

    Diff image: unchanged pixels are the baseline faded to light grey, changed
    pixels are solid red, so a reviewer sees where the change is at a glance.
    """
    count = 0
    out: list[bytes] = []
    for ra, rb in zip(a, b):
        if ra == rb:
            out.append(bytes(200 + (v * 55 // 255) for v in rb))
            continue
        row = bytearray(width * 3)
        for x in range(width):
            i = x * 3
            if (abs(ra[i] - rb[i]) > tolerance or abs(ra[i + 1] - rb[i + 1]) > tolerance
                    or abs(ra[i + 2] - rb[i + 2]) > tolerance):
                count += 1
                row[i:i + 3] = b"\xff\x00\x00"
            else:
                row[i] = 200 + rb[i] * 55 // 255
                row[i + 1] = 200 + rb[i + 1] * 55 // 255
                row[i + 2] = 200 + rb[i + 2] * 55 // 255
        out.append(bytes(row))
    return count, out


def compare_images(name: str, current: Path, baseline: Path, diff_path: Path,
                   threshold: float = DEFAULT_THRESHOLD, tolerance: int = DEFAULT_TOLERANCE) -> DiffResult:
    res = DiffResult(name=name, status="error", threshold=threshold, current=str(current), baseline=str(baseline))
    if not baseline.exists():
        res.status, res.message = "no-baseline", "no baseline yet; review the screenshot, then run approve"
        return res
    try:
        wa, ha, ra = load_rgb(current)
        wb, hb, rb = load_rgb(baseline)
    except (PngError, OSError, zlib.error) as exc:
        res.message = f"could not read image: {exc}"
        return res
    if (wa, ha) != (wb, hb):
        res.status = "fail"
        res.total_pixels = wb * hb
        res.message = f"size changed: baseline {wb}x{hb}, current {wa}x{ha} (layout shift or page length change)"
        return res
    count, rows = diff_rows(ra, rb, wa, tolerance)
    res.total_pixels = wa * ha
    res.diff_pixels = count
    res.diff_percent = round(100.0 * count / res.total_pixels, 4) if res.total_pixels else 0.0
    if count:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_bytes(encode_png(wa, ha, rows))
        res.diff_image = str(diff_path)
    res.status = "pass" if res.diff_percent <= threshold else "fail"
    res.message = f"{res.diff_percent:.4f}% of pixels differ (threshold {threshold}%)"
    return res


def verdict(results: list[DiffResult]) -> int:
    if not results:
        return EXIT_INCONCLUSIVE
    if any(r.status == "fail" for r in results):
        return EXIT_FAIL
    if any(r.status != "pass" for r in results):
        return EXIT_INCONCLUSIVE
    return EXIT_PASS


def compare_dirs(current_dir: Path, baseline_dir: Path, diff_dir: Path, threshold: float,
                 tolerance: int, only: set[str] | None = None) -> list[DiffResult]:
    results = []
    for cur in sorted(current_dir.glob("*.png")):
        if only is not None and cur.name not in only:
            continue
        results.append(compare_images(cur.stem, cur, baseline_dir / cur.name, diff_dir / cur.name,
                                      threshold, tolerance))
    return results


# ── capture (needs Playwright) ────────────────────────────────────────────────

FREEZE_CSS = """
*, *::before, *::after { animation-duration: 0s !important; animation-delay: 0s !important;
  transition-duration: 0s !important; transition-delay: 0s !important; caret-color: transparent !important; }
"""


def capture(urls: list[str], names: list[str], devices: list[str], out_dir: Path, browser: str,
            masks: list[str], wait_for: str | None, full_page: bool, settle_ms: int) -> tuple[list[str], list[str]]:
    from playwright.sync_api import sync_playwright
    from done_gate import context_kwargs
    shots, errors = [], []
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = getattr(pw, browser).launch()
        try:
            for url, name in zip(urls, names):
                for device in devices:
                    ctx = b.new_context(**context_kwargs(device, browser), reduced_motion="reduce")
                    page = ctx.new_page()
                    target = out_dir / f"{name}-{device}.png"
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30000)
                        page.add_style_tag(content=FREEZE_CSS)
                        if wait_for:
                            page.locator(wait_for).first.wait_for(state="visible", timeout=15000)
                        page.evaluate("document.fonts ? document.fonts.ready.then(() => true) : true")
                        page.wait_for_timeout(settle_ms)
                        page.screenshot(path=str(target), full_page=full_page, scale="css",
                                        animations="disabled", caret="hide",
                                        mask=[page.locator(m) for m in masks] or None)
                        shots.append(str(target))
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{name}@{device}: {str(exc).splitlines()[0]}")
                    finally:
                        ctx.close()
        finally:
            b.close()
    return shots, errors


def _names_for(urls: list[str], names: list[str]) -> list[str]:
    if names and len(names) != len(urls):
        raise ValueError("give one --name per --url (or none)")
    if names:
        return names
    from urllib.parse import urlsplit
    out = []
    for u in urls:
        path = urlsplit(u).path.strip("/").replace("/", "-") or "home"
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    from done_gate import DEVICE_PROFILES
    ap = argparse.ArgumentParser(prog="visual_baseline.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["capture", "compare", "check", "approve"])
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--name", action="append", default=[], help="screenshot name per --url")
    ap.add_argument("--devices", default="desktop-1440x900")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    ap.add_argument("--root", default=".qa/visual", help="holds current/, baselines/, diff/")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="max percent of pixels that may differ")
    ap.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE, help="per-channel noise tolerance 0-255")
    ap.add_argument("--mask", action="append", default=[], help="selector to paint over (clocks, avatars, ads)")
    ap.add_argument("--wait-for", default=None, help="selector that must be visible before the shot")
    ap.add_argument("--viewport-only", action="store_true", help="screenshot the viewport, not the full page")
    ap.add_argument("--settle-ms", type=int, default=300)
    ap.add_argument("--only", action="append", default=None, help="approve/compare only this file name")
    args = ap.parse_args(argv)

    root = Path(args.root)
    cur, base, diff = root / "current", root / "baselines", root / "diff"
    devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    bad = [d for d in devices if d not in DEVICE_PROFILES]
    if bad:
        print(f"CONFIG ERROR: unknown device(s) {bad}; known: {sorted(DEVICE_PROFILES)}", file=sys.stderr)
        return EXIT_CONFIG
    if not (0 <= args.tolerance <= 255) or args.threshold < 0:
        print("CONFIG ERROR: tolerance must be 0-255 and threshold >= 0", file=sys.stderr)
        return EXIT_CONFIG

    if args.command == "approve":
        if not cur.exists():
            print(f"CONFIG ERROR: nothing to approve, {cur} does not exist", file=sys.stderr)
            return EXIT_CONFIG
        base.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in sorted(cur.glob("*.png")):
            if args.only and f.name not in args.only:
                continue
            shutil.copy2(f, base / f.name)
            print(f"approved {f.name}")
            n += 1
        print(f"{n} baseline(s) written to {base}. Commit them with the change they describe.")
        return EXIT_PASS

    capture_errors: list[str] = []
    captured: set[str] | None = None
    if args.command in ("capture", "check"):
        if not args.url:
            print("CONFIG ERROR: capture/check need at least one --url", file=sys.stderr)
            return EXIT_CONFIG
        try:
            names = _names_for(args.url, args.name)
        except ValueError as exc:
            print(f"CONFIG ERROR: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        try:
            import playwright  # noqa: F401
        except ImportError:
            print("CONFIG ERROR: Playwright is not installed. Run:\n"
                  "  pip install playwright && python3 -m playwright install chromium", file=sys.stderr)
            return EXIT_CONFIG
        if cur.exists() and args.command == "check":
            shutil.rmtree(cur)
        shots, capture_errors = capture(args.url, names, devices, cur, args.browser, args.mask,
                                        args.wait_for, not args.viewport_only, args.settle_ms)
        captured = {Path(s).name for s in shots}
        for s in shots:
            print(f"captured {s}")
        for e in capture_errors:
            print(f"CAPTURE FAILED {e}")
        if args.command == "capture":
            return EXIT_INCONCLUSIVE if capture_errors else EXIT_PASS

    if not cur.exists():
        print(f"CONFIG ERROR: {cur} does not exist; run capture first", file=sys.stderr)
        return EXIT_CONFIG
    only = set(args.only) if args.only else captured
    results = compare_dirs(cur, base, diff, args.threshold, args.tolerance, only)
    for r in results:
        print(f"{r.status.upper():12} {r.name}: {r.message}" + (f"  diff: {r.diff_image}" if r.diff_image else ""))
    code = verdict(results)
    if capture_errors and code == EXIT_PASS:
        code = EXIT_INCONCLUSIVE
    root.mkdir(parents=True, exist_ok=True)
    (root / "report.json").write_text(json.dumps({"exit_code": code, "capture_errors": capture_errors,
                                                  "results": [asdict(r) for r in results]}, indent=2))
    label = {0: "PASS", 1: "VISUAL REGRESSION", 6: "INCONCLUSIVE (not a pass)"}[code]
    print(f"VISUAL: {label} (exit {code})  report: {root / 'report.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
