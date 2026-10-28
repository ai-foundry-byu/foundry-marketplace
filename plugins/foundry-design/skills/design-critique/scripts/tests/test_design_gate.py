"""Tests for design_gate.py. Run from the plugin root:

    python3 -m unittest discover -s skills/design-critique/scripts/tests -v

The pure logic (color math, page evaluation, limits, baseline comparison, CLI check/bless)
is tested with the stdlib only. One end-to-end test drives a local fixture page with
Playwright and is skipped when Playwright or its browser is not installed.
"""
import contextlib
import functools
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import design_gate as g  # noqa: E402


class ColorTests(unittest.TestCase):
    def test_parse_formats(self):
        self.assertEqual(g.parse_color("rgb(1, 2, 3)"), (1.0, 2.0, 3.0, 1.0))
        self.assertEqual(g.parse_color("rgba(10,20,30,0.5)"), (10.0, 20.0, 30.0, 0.5))
        self.assertEqual(g.parse_color("rgb(10 20 30 / 50%)"), (10.0, 20.0, 30.0, 0.5))
        self.assertEqual(g.parse_color("#fff"), (255.0, 255.0, 255.0, 1.0))
        self.assertEqual(g.parse_color("#00000080")[3], 128 / 255)
        self.assertEqual(g.parse_color("transparent")[3], 0.0)

    def test_parse_rejects_garbage(self):
        for bad in ("blue", "#12", "hsl(0, 0%, 0%)", "rgb(1,2)"):
            with self.assertRaises(g.ColorError):
                g.parse_color(bad)

    def test_known_contrast_ratios(self):
        black, white = g.parse_color("#000"), g.parse_color("#fff")
        self.assertAlmostEqual(g.contrast_ratio(black, white), 21.0, places=2)
        self.assertAlmostEqual(g.contrast_ratio(white, white), 1.0, places=2)
        # #767676 on white is the classic just-passing gray, about 4.54:1
        self.assertAlmostEqual(g.contrast_ratio(g.parse_color("#767676"), white), 4.54, places=2)
        # #777777 just fails, about 4.48:1
        self.assertLess(g.contrast_ratio(g.parse_color("#777777"), white), 4.5)

    def test_translucent_text_is_composited(self):
        white = g.parse_color("#fff")
        half_black = g.parse_color("rgba(0,0,0,0.5)")
        ratio = g.contrast_ratio(half_black, white)
        self.assertAlmostEqual(ratio, g.contrast_ratio(g.parse_color("rgb(127.5,127.5,127.5)"), white), places=3)

    def test_background_layers_composite_over_page(self):
        # a 50% black overlay on a white page resolves to mid gray
        bg = g.resolve_background(["rgba(0, 0, 0, 0.5)"], "rgb(255, 255, 255)")
        self.assertAlmostEqual(bg[0], 127.5, places=1)
        self.assertEqual(bg[3], 1.0)
        # an opaque inner layer wins over outer ones
        bg = g.resolve_background(["rgb(10, 10, 10)", "rgb(200, 0, 0)"])
        self.assertEqual(bg[:3], (10.0, 10.0, 10.0))

    def test_large_text(self):
        self.assertTrue(g.is_large_text(24, 400))
        self.assertTrue(g.is_large_text(19, 700))
        self.assertFalse(g.is_large_text(19, 400))
        self.assertFalse(g.is_large_text(16, 700))


def raw_page(**over):
    base = {
        "touch": True, "inner_width": 390, "scroll_width": 390,
        "dead_controls": 0, "entry_points": 4, "primary_buttons": 1, "unlabeled_buttons": 0,
        "inputs_font_px": [16], "targets": [{"w": 48, "h": 48, "label": "Save"}],
        "text_samples": [{"fg": "rgb(17, 17, 17)", "bg_layers": [], "size": 16, "weight": 400, "text": "Hi"}],
    }
    base.update(over)
    return base


class EvaluatePageTests(unittest.TestCase):
    def test_clean_page(self):
        m, d = g.evaluate_page(raw_page(), {})
        self.assertEqual(m["small_target_count"], 0)
        self.assertEqual(m["contrast_failure_count"], 0)
        self.assertFalse(m["h_scroll"])
        self.assertEqual(m["inputs_under_16px"], 0)

    def test_touch_vs_pointer_minimum(self):
        raw = raw_page(targets=[{"w": 32, "h": 32, "label": "x"}])
        self.assertEqual(g.evaluate_page(raw, {})[0]["small_target_count"], 1)   # touch: 44
        raw["touch"] = False
        self.assertEqual(g.evaluate_page(raw, {})[0]["small_target_count"], 0)   # pointer: 24

    def test_inline_links_and_hidden_targets_exempt(self):
        raw = raw_page(targets=[{"w": 30, "h": 18, "inline": True}, {"w": 1, "h": 1}])
        self.assertEqual(g.evaluate_page(raw, {})[0]["small_target_count"], 0)

    def test_low_contrast_counted_large_text_relaxed(self):
        gray = "rgb(150, 150, 150)"  # about 2.96:1 on white
        mid = "rgb(130, 130, 130)"   # about 3.84:1 on white: fails normal, passes large
        raw = raw_page(text_samples=[
            {"fg": gray, "bg_layers": [], "size": 16, "weight": 400, "text": "a"},
            {"fg": mid, "bg_layers": [], "size": 16, "weight": 400, "text": "b"},
            {"fg": mid, "bg_layers": [], "size": 28, "weight": 400, "text": "c"},
            {"fg": gray, "bg_image": True, "size": 16, "weight": 400, "text": "d"},
        ])
        m, d = g.evaluate_page(raw, {})
        self.assertEqual(m["contrast_failure_count"], 2)
        self.assertEqual(d["contrast_unknown"], 1)
        self.assertEqual({f["text"] for f in d["contrast_failures"]}, {"a", "b"})

    def test_dark_theme_contrast(self):
        raw = raw_page(text_samples=[{"fg": "rgba(255,255,255,0.5)", "bg_layers": ["rgb(20, 20, 20)"],
                                      "size": 14, "weight": 400, "text": "meta"}])
        self.assertEqual(g.evaluate_page(raw, {})[0]["contrast_failure_count"], 0)
        raw["text_samples"][0]["fg"] = "rgba(255,255,255,0.3)"
        self.assertEqual(g.evaluate_page(raw, {})[0]["contrast_failure_count"], 1)

    def test_horizontal_scroll_and_small_inputs(self):
        m, _ = g.evaluate_page(raw_page(scroll_width=420, inputs_font_px=[14, 16]), {})
        self.assertTrue(m["h_scroll"])
        self.assertEqual(m["inputs_under_16px"], 1)
        m, _ = g.evaluate_page(raw_page(touch=False, inputs_font_px=[14]), {})
        self.assertEqual(m["inputs_under_16px"], 0)  # only enforced on touch


BASELINE = {
    "page.home@phone.dead_controls": 0,
    "page.home@phone.entry_points": 5,
    "page.home@phone.primary_buttons": 1,
    "page.home@phone.h_scroll": False,
    "flow.add-task@phone.clicks": 2,
    "flow.add-task@phone.reached": True,
    "context.cart-total@phone.present": True,
}


class GateTests(unittest.TestCase):
    def test_identical_passes(self):
        fails, notes = g.gate(dict(BASELINE), BASELINE, {})
        self.assertEqual(fails, [])

    # The "plant a known-bad" discipline: each planted regression must fail the gate.
    def test_planted_extra_click_fails(self):
        cur = {**BASELINE, "flow.add-task@phone.clicks": 3}
        fails, _ = g.gate(cur, BASELINE, {})
        self.assertTrue(any("flow.add-task@phone.clicks: 2 -> 3" in f for f in fails), fails)

    def test_planted_dead_control_fails(self):
        cur = {**BASELINE, "page.home@phone.dead_controls": 1}
        self.assertTrue(g.gate(cur, BASELINE, {})[0])

    def test_planted_duplicate_entry_point_fails(self):
        cur = {**BASELINE, "page.home@phone.entry_points": 6}
        self.assertTrue(g.gate(cur, BASELINE, {})[0])

    def test_lost_context_fails(self):
        cur = {**BASELINE, "context.cart-total@phone.present": False}
        self.assertTrue(any("must hold" in f for f in g.gate(cur, BASELINE, {})[0]))

    def test_broken_flow_fails_even_without_baseline(self):
        cur = {**BASELINE, "flow.add-task@phone.reached": False}
        fails, _ = g.gate(cur, None, {})
        self.assertTrue(any("no longer reaches" in f for f in fails))

    def test_second_primary_button_is_absolute_violation(self):
        cur = {**BASELINE, "page.home@phone.primary_buttons": 2}
        fails, _ = g.gate(cur, None, {})
        self.assertTrue(any("exceeds limit 1" in f for f in fails))
        # a null limit disables the absolute check; the baseline still catches it
        fails, _ = g.gate(cur, None, {"max_primary_buttons": None})
        self.assertEqual(fails, [])
        self.assertTrue(g.gate(cur, BASELINE, {"max_primary_buttons": None})[0])

    def test_horizontal_scroll(self):
        cur = {**BASELINE, "page.home@phone.h_scroll": True}
        fails, _ = g.gate(cur, BASELINE, {})
        self.assertEqual(len(fails), 2)  # absolute + regression
        fails, _ = g.gate(cur, None, {"allow_horizontal_scroll": True})
        self.assertEqual(fails, [])

    def test_missing_metric_fails_new_metric_notes(self):
        cur = dict(BASELINE)
        del cur["context.cart-total@phone.present"]
        cur["page.about@phone.dead_controls"] = 0
        fails, notes = g.gate(cur, BASELINE, {})
        self.assertTrue(any("missing" in f for f in fails))
        self.assertTrue(any("page.about@phone.dead_controls" in n for n in notes))

    def test_improvement_is_noted_not_failed(self):
        cur = {**BASELINE, "flow.add-task@phone.clicks": 1}
        fails, notes = g.gate(cur, BASELINE, {})
        self.assertEqual(fails, [])
        self.assertTrue(any("improved" in n for n in notes))


class ConfigTests(unittest.TestCase):
    def test_local_target_detection(self):
        for ok in ("http://localhost:3000", "http://127.0.0.1:8080/x", "http://app.localhost", "http://box.local"):
            self.assertTrue(g.is_local_target(ok), ok)
        for bad in ("https://example.com", "https://myapp.vercel.app", "http://10.0.0.5"):
            self.assertFalse(g.is_local_target(bad), bad)

    def test_validate_config(self):
        with self.assertRaises(g.ConfigError):
            g.validate_config({"pages": [{"name": "x", "path": "/"}]})
        with self.assertRaises(g.ConfigError):
            g.validate_config({"base_url": "http://localhost", "flows": [{"name": "f", "steps": [{"jump": 1}], "goal": "x"}]})
        cfg = g.validate_config({"base_url": "http://localhost", "pages": [{"name": "home", "path": "/"}]})
        self.assertEqual(cfg["base_url"], "http://localhost")

    def test_count_clicks(self):
        self.assertEqual(g.count_clicks([{"click": "a"}, {"fill": "b", "value": "c"}, {"click": "d"}]), 2)

    def test_example_config_is_valid(self):
        path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "templates", "design-gate.config.json")
        g.validate_config(g.load_json(path))

    def test_run_refuses_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "c.json")
            with open(cfg, "w") as fh:
                json.dump({"base_url": "https://example.com", "pages": [{"name": "h", "path": "/"}]}, fh)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(g.main(["run", "--config", cfg]), 3)


class CliTests(unittest.TestCase):
    def test_check_and_bless_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cur = os.path.join(tmp, "cur.json")
            base = os.path.join(tmp, "design", "base.json")
            with open(cur, "w") as fh:
                json.dump({"metrics": BASELINE, "details": {}}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(g.main(["bless", "--current", cur, "--baseline", base]), 0)
                self.assertEqual(g.main(["check", "--current", cur, "--baseline", base]), 0)
            worse = {**BASELINE, "flow.add-task@phone.clicks": 4}
            with open(cur, "w") as fh:
                json.dump({"metrics": worse}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(g.main(["check", "--current", cur, "--baseline", base]), 1)
            self.assertIn("DESIGN GATE: FAIL", out.getvalue())

    def test_bad_json_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cur = os.path.join(tmp, "cur.json")
            with open(cur, "w") as fh:
                fh.write("{nope")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(g.main(["check", "--current", cur]), 2)


def _playwright_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


FIXTURE = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{margin:0;font:16px sans-serif;background:#fff;color:#111}
button{min-width:48px;min-height:48px;font-size:16px} .faint{color:#bbb}</style></head>
<body><nav><a href="/" style="display:inline-block;padding:14px">Home</a>
<a href="/b" style="display:inline-block;padding:14px">Tasks</a></nav>
<main><input id=title style="font-size:16px;height:48px">
<button class="btn-primary" id=save onclick="document.getElementById('out').textContent=document.getElementById('title').value">Save</button>
<button disabled>Archive</button><p class=faint>low contrast note</p><p id=out></p></main></body></html>"""


@unittest.skipUnless(_playwright_ready(), "Playwright + chromium not installed")
class EndToEndTests(unittest.TestCase):
    def test_measure_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "index.html"), "w") as fh:
                fh.write(FIXTURE)
            class Quiet(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *a):
                    pass
            handler = functools.partial(Quiet, directory=tmp)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                cfg = g.validate_config({
                    "base_url": f"http://127.0.0.1:{srv.server_address[1]}",
                    "viewports": {"phone": {"width": 390, "height": 844, "touch": True}},
                    "pages": [{"name": "home", "path": "/"}],
                    "flows": [{"name": "save", "start": "/", "steps": [
                        {"fill": "#title", "value": "Buy milk"}, {"click": "#save"}], "goal": "text=Buy milk"}],
                    "context_checks": [{"name": "nav", "path": "/", "selector": "nav"}],
                })
                m, d = g.measure(cfg)
            finally:
                srv.shutdown()
        self.assertEqual(m["page.home@phone.dead_controls"], 1)
        self.assertEqual(m["page.home@phone.primary_buttons"], 1)
        self.assertEqual(m["page.home@phone.entry_points"], 2)
        self.assertGreaterEqual(m["page.home@phone.contrast_failure_count"], 1)
        self.assertFalse(m["page.home@phone.h_scroll"])
        self.assertEqual(m["flow.save@phone.clicks"], 1)
        self.assertTrue(m["flow.save@phone.reached"])
        self.assertTrue(m["context.nav@phone.present"])


if __name__ == "__main__":
    unittest.main()
