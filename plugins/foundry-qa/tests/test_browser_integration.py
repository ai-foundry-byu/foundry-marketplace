"""End-to-end tests against a local fixture site in a real headless browser.

Skipped automatically when Playwright or its Chromium build is not installed.
The a11y test also needs one download of axe-core (skipped if offline).
Run:  python3 -m unittest tests.test_browser_integration -v   (from the plugin root)
"""
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import _paths

SHA = "0123456789abcdef0123456789abcdef01234567"


def _browser_ok():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


class Handler(SimpleHTTPRequestHandler):
    writes = 0

    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/slow"):
            time.sleep(1.2)                       # data that lands well after the load event
            self._json([{"name": "Stats 121"}, {"name": "Finance 201"}, {"name": "Strategy 401"}])
            return
        if self.path.startswith("/private.html"):
            signed_in = ("qa_session=ok" in (self.headers.get("Cookie") or "")
                         or self.headers.get("X-QA-Token") == "letmein")
            if not signed_in:
                self.send_response(302)
                self.send_header("Location", "/login.html")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        if self.path.startswith("/api/version"):
            body = json.dumps({"commit": SHA}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        Handler.writes += 1
        body = b'{"saved": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(_browser_ok(), "Playwright + Chromium not installed")
class TestBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(Handler, directory=str(_paths.FIXTURES / "site"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        Handler.writes = 0

    def tearDown(self):
        self.td.cleanup()

    def run_script(self, name, *args):
        p = subprocess.run([sys.executable, str(_paths.script(name)), *args], cwd=self.d,
                           capture_output=True, text=True, timeout=240)
        return p.returncode, p.stdout + p.stderr

    def journey(self, text):
        f = self.d / "j.yaml"
        f.write_text(text)
        return str(f)

    SAVE = """
name: save email
devices: [desktop-1440x900, phone-390x844]
steps:
  - goto: /index.html
  - fill: {selector: "#email", value: "student@example.com"}
  - click: "#save"
assertions:
  - visible: h1
  - text: {selector: "#status", contains: "Saved (simulated)"}
  - url_contains: index
  - no_console_errors: true
screenshot: save
"""

    def test_done_gate_pass_read_only_and_sha(self):
        code, out = self.run_script("done_gate.py", "--journey", self.journey(self.SAVE), "--base-url", self.base,
                                    "--read-only", "--sha-url", f"{self.base}/api/version",
                                    "--sha-json-key", "commit", "--expected-sha", SHA[:10])
        self.assertEqual(code, 0, out)
        self.assertEqual(Handler.writes, 0, "the read-only guard let a write reach the server")
        latest = json.loads((self.d / ".qa/done-gate/latest.json").read_text())
        self.assertTrue(all(Path(r["screenshot"]).exists() for r in latest["results"]))
        self.assertEqual(len(latest["results"][0]["blocked_writes"]), 1)

    def test_done_gate_sha_mismatch(self):
        code, out = self.run_script("done_gate.py", "--journey", self.journey(self.SAVE), "--base-url", self.base,
                                    "--sha-url", f"{self.base}/api/version", "--expected-sha", "fedcba9876",
                                    "--sha-retries", "1")
        self.assertEqual(code, 3, out)

    def test_done_gate_without_read_only_writes_for_real(self):
        j = self.journey(self.SAVE.replace("Saved (simulated)", "Saved"))
        code, out = self.run_script("done_gate.py", "--journey", j, "--base-url", self.base, "--devices", "desktop-1440x900")
        self.assertEqual(code, 0, out)
        self.assertEqual(Handler.writes, 1)

    def test_done_gate_fail(self):
        j = self.journey("timeout_ms: 1500\nsteps:\n  - goto: /index.html\nassertions:\n  - visible: \"#does-not-exist\"\n")
        code, out = self.run_script("done_gate.py", "--journey", j, "--base-url", self.base)
        self.assertEqual(code, 1, out)

    def test_done_gate_console_error_fails(self):
        j = self.journey("steps:\n  - goto: /broken.html\nassertions:\n  - no_console_errors: true\n")
        code, out = self.run_script("done_gate.py", "--journey", j, "--base-url", self.base)
        self.assertEqual(code, 1, out)

    def test_done_gate_unreachable_is_inconclusive(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        j = self.journey("steps:\n  - goto: /\nassertions:\n  - visible: h1\n")
        code, out = self.run_script("done_gate.py", "--journey", j, "--base-url", f"http://127.0.0.1:{port}")
        self.assertEqual(code, 6, out)
        self.assertIn("not a pass", out.lower())

    def test_done_gate_auth_wall_is_inconclusive(self):
        j = self.journey("auth_wall: [about.html]\nsteps:\n  - goto: /about.html\nassertions:\n  - visible: h1\n")
        code, out = self.run_script("done_gate.py", "--journey", j, "--base-url", self.base)
        self.assertEqual(code, 6, out)

    def test_persona_run(self):
        persona = self.d / "p.md"
        persona.write_text("---\nname: Mobile newcomer\ndevices: [phone-390x844]\npatience_seconds: 20\n"
                           "min_tap_target_px: 24\n---\nNew here.\n")
        stories = self.d / "s.json"
        stories.write_text(json.dumps({"stories": [
            {"id": "S-1", "title": "save email", "start": "/index.html", "writes": True,
             "steps": [{"fill": {"selector": "#email", "value": "a@example.com"}}, {"click": "#save"}],
             "assertions": [{"text": {"selector": "#status", "contains": "Saved"}}]},
            {"id": "S-2", "title": "broken page", "start": "/broken.html", "assertions": [{"visible": "h1"}]},
            {"id": "S-3", "title": "about reads well", "start": "/about.html", "acceptance": ["the copy is clear"]},
        ]}))
        args = ["--persona", str(persona), "--stories", str(stories), "--base-url", self.base, "--out", "out"]
        code, out = self.run_script("persona_run.py", *args)
        self.assertEqual(code, 1, out)
        self.assertEqual(Handler.writes, 0)
        res = {r["story"]: r for r in json.loads((self.d / "out/results.json").read_text())["results"]}
        self.assertEqual(res["S-1"]["status"], "passed", res["S-1"])
        self.assertEqual(res["S-2"]["status"], "failed")
        failed_checks = {c["check"] for c in res["S-2"]["checks"] if not c["passed"]}
        self.assertTrue({"no-overflow", "tap-targets", "console"} <= failed_checks, failed_checks)
        self.assertEqual(res["S-3"]["status"], "needs-judgment")
        self.assertIn("Needs judgment", (self.d / "out/REPORT.md").read_text())
        code, out = self.run_script("persona_run.py", *args, "--file-tickets")
        self.assertTrue((self.d / "out/tickets/S-2-phone-390x844.md").exists(), out)
        self.assertFalse((self.d / "out/tickets/S-1-phone-390x844.md").exists())

    def test_visual_baseline(self):
        args = ["--url", f"{self.base}/about.html", "--name", "about", "--devices", "desktop-1440x900,phone-390x844"]
        code, out = self.run_script("visual_baseline.py", "check", *args)
        self.assertEqual(code, 6, out)                       # no baselines yet
        self.assertEqual(self.run_script("visual_baseline.py", "approve")[0], 0)
        code, out = self.run_script("visual_baseline.py", "check", *args)
        self.assertEqual(code, 0, out)

    def test_explore(self):
        code, out = self.run_script("explore.py", "--url", f"{self.base}/index.html", "--max-pages", "5")
        self.assertEqual(code, 0, out)
        data = json.loads((self.d / ".qa/explore/findings.json").read_text())
        self.assertGreaterEqual(len([p for p in data["pages"] if p["status"] == 200]), 2)
        code, out = self.run_script("explore.py", "--url", f"{self.base}/broken.html", "--max-pages", "2",
                                    "--devices", "phone-390x844")
        self.assertEqual(code, 1, out)
        self.assertIn("overflow", out)

    def test_a11y(self):
        code, out = self.run_script("a11y_check.py", "--url", f"{self.base}/broken.html")
        if code == 6 and "could not load axe-core" in out:
            self.skipTest("axe-core download unavailable (offline)")
        self.assertEqual(code, 1, out)
        self.assertIn("button-name", out)
        code, out = self.run_script("a11y_check.py", "--url", f"{self.base}/index.html",
                                    "--devices", "desktop-1440x900,phone-390x844")
        self.assertEqual(code, 0, out)

    # ── regressions from the 2026-10 live test campaign ──────────────────────

    def test_persona_run_reads_sdlc_stories_and_waits_for_async_data(self):
        """L3-D1/L1-D13: the product stories.json is read as is. L3-D2: checks see data that loads late."""
        persona = self.d / "p.md"
        persona.write_text("---\nname: Mobile newcomer\ndevices: [phone-390x844]\npatience_seconds: 20\n"
                           "min_tap_target_px: 44\n---\nNew here.\n")
        stories = self.d / "stories.json"
        stories.write_text(json.dumps({"stories": [
            {"id": "US-01", "title": "see the groups", "acceptance": ["Every group is listed"],
             "surfaces": ["/slow.html"], "devices": ["phone-390x844", "ios-sim"], "status": "BUILT",
             "waits_on": [], "covers": ["R-01"], "notes": "", "evidence": [], "owner": "unknown-key"},
            {"id": "US-02", "title": "save email", "acceptance": ["It saves"], "surfaces": ["/index.html"],
             "devices": ["phone-390x844"], "status": "BUILT", "waits_on": [],
             "qa": {"steps": [{"fill": {"selector": "#email", "value": "a@example.com"}}, {"click": "#save"}],
                    "assertions": [{"text": {"selector": "#status", "contains": "Saved"}}]}},
        ]}))
        code, out = self.run_script("persona_run.py", "--persona", str(persona), "--stories", str(stories),
                                    "--base-url", self.base, "--out", "out")
        self.assertNotIn("CONFIG ERROR", out)
        self.assertIn("WARNING", out)                         # unknown key and ios-sim: warned, not rejected
        data = json.loads((self.d / "out/results.json").read_text())
        res = {r["story"]: r for r in data["results"]}
        us1 = res["US-01"]
        self.assertGreaterEqual(us1["elapsed_s"], 1.2, "patience must be measured to content, not the load event")
        self.assertEqual(us1["status"], "failed", us1)        # the TypeError fires only after the fetch
        self.assertTrue(any("null" in e or "members" in e for e in us1["console_errors"]), us1["console_errors"])
        self.assertEqual(res["US-02"]["status"], "passed", res["US-02"])   # qa block steps ran
        self.assertIn("phone-390x844", data["site_findings"])  # 20x20 icon buttons, only present after load
        self.assertTrue(any("Join" in x for x in data["site_findings"]["phone-390x844"]))
        tap = [c for c in us1["checks"] if c["check"] == "tap-targets"][0]
        self.assertEqual(tap["scope"], "site")
        report = (self.d / "out/REPORT.md").read_text()
        self.assertEqual(report.count("## Site-wide persona checks"), 1)

    def test_explore_crawls_hash_routes_and_attributes_events(self):
        """L3-D3: #/routes are pages. L3-D11: the back-check target's errors stay off the parent page."""
        code, out = self.run_script("explore.py", "--url", f"{self.base}/spa.html", "--max-pages", "6")
        data = json.loads((self.d / ".qa/explore/findings.json").read_text())
        urls = [p["url"] for p in data["pages"]]
        self.assertIn(f"{self.base}/spa.html#/a", urls, out)
        self.assertIn(f"{self.base}/spa.html#/b", urls, out)
        self.assertFalse(any("logout" in u for u in urls), urls)
        self.assertFalse(any(u.endswith("#top") for u in urls), urls)
        by_url = {p["url"]: p for p in data["pages"]}
        kinds_b = {f["kind"] for f in by_url[f"{self.base}/spa.html#/b"]["findings"]}
        self.assertIn("uncaught", kinds_b)
        kinds_a = {f["kind"] for f in by_url[f"{self.base}/spa.html#/a"]["findings"]}
        self.assertIn("img-no-alt", kinds_a)
        start = by_url[f"{self.base}/spa.html"]
        self.assertFalse([f for f in start["findings"] if "boom from fixture" in f["detail"]], start["findings"])
        self.assertTrue(any("boom from fixture" in f["detail"] for f in by_url[f"{self.base}/broken.html"]["findings"]))
        self.assertEqual(code, 1, out)

    def test_signed_in_session_in_every_script(self):
        """L1-D8: storage state, cookies, headers and login_steps reach every script."""
        private = f"{self.base}/private.html"
        journey = self.journey("name: account\nauth_wall: [login.html]\nsteps:\n  - goto: /private.html\n"
                               "assertions:\n  - visible: \"#secret\"\n")
        code, out = self.run_script("done_gate.py", "--journey", journey, "--base-url", self.base)
        self.assertEqual(code, 6, out)                       # signed out: bounced to sign-in, not a pass
        code, out = self.run_script("done_gate.py", "--journey", journey, "--base-url", self.base,
                                    "--header", "X-QA-Token: letmein")
        self.assertEqual(code, 0, out)
        crumb = self.d / "crumb.yaml"
        crumb.write_text("name: account\nauth_wall: [login.html]\nauth:\n  cookies:\n    - {name: qa_session, value: ok}\n"
                         "steps:\n  - goto: /private.html\nassertions:\n  - visible: \"#secret\"\n")
        code, out = self.run_script("done_gate.py", "--journey", str(crumb), "--base-url", self.base)
        self.assertEqual(code, 0, out)
        steps = self.d / "login.yaml"
        steps.write_text("login_steps:\n  - goto: /login.html\n  - click: \"#signin\"\n")
        code, out = self.run_script("qa_session.py", "login", "--url", self.base, "--steps", str(steps),
                                    "--wait-for", "#secret", "--out", ".qa/auth.json")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.d / ".qa/auth.json").exists())
        code, out = self.run_script("done_gate.py", "--journey", journey, "--base-url", self.base,
                                    "--storage-state", ".qa/auth.json")
        self.assertEqual(code, 0, out)
        last = json.loads((self.d / ".qa/done-gate/last.json").read_text())
        self.assertEqual(last["exit"], 0)
        login_j = self.d / "loginsteps.yaml"
        login_j.write_text("auth:\n  login_steps:\n    - goto: /login.html\n    - click: \"#signin\"\n"
                           "    - wait_for: \"#secret\"\nsteps:\n  - goto: /private.html\nassertions:\n"
                           "  - visible: \"#secret\"\n")
        code, out = self.run_script("done_gate.py", "--journey", str(login_j), "--base-url", self.base, "--read-only")
        self.assertEqual(code, 0, out)
        persona = self.d / "p.md"
        persona.write_text("---\nname: Member\ndevices: [desktop-1440x900]\npatience_seconds: 20\n---\nSigned in.\n")
        stories = self.d / "s.json"
        stories.write_text(json.dumps([{"id": "US-01", "title": "account", "acceptance": ["shows the account"],
                                        "surfaces": ["/private.html"], "devices": [], "status": "BUILT", "waits_on": [],
                                        "qa": {"assertions": [{"url_contains": "private"}]}}]))
        code, out = self.run_script("persona_run.py", "--persona", str(persona), "--stories", str(stories),
                                    "--base-url", self.base, "--storage-state", ".qa/auth.json", "--out", "pout")
        self.assertEqual(code, 0, out)
        code, out = self.run_script("explore.py", "--url", private, "--max-pages", "1", "--back-checks", "0",
                                    "--header", "X-QA-Token: letmein")
        pages = json.loads((self.d / ".qa/explore/findings.json").read_text())["pages"]
        self.assertEqual(pages[0]["title"], "Your account", out)
        code, out = self.run_script("visual_baseline.py", "capture", "--url", private, "--name", "account",
                                    "--auth", str(crumb))
        self.assertEqual(code, 0, out)
        code, out = self.run_script("a11y_check.py", "--journey", str(crumb), "--base-url", self.base)
        if not (code == 6 and "could not load axe-core" in out):
            self.assertIn("journey:account", out)
            self.assertNotIn("INCONCLUSIVE journey", out)

    def test_a11y_target_size(self):
        """L3-D10: 20x20 icon buttons side by side fail WCAG 2.5.8 even when axe passes them."""
        code, out = self.run_script("a11y_check.py", "--url", f"{self.base}/slow.html", "--devices", "phone-390x844")
        if code == 6 and "could not load axe-core" in out:
            self.skipTest("axe-core download unavailable (offline)")
        self.assertIn("target-size-2.5.8", out)
        self.assertEqual(code, 1, out)
        report = json.loads((self.d / ".qa/a11y/report.json").read_text())
        ts = report["pages"][0]["target_size"]
        self.assertTrue(any("Join" in x["target"] for x in ts["failing"]), ts)
        code, out = self.run_script("a11y_check.py", "--url", f"{self.base}/broken.html")
        self.assertIn("small-targets", out)          # a lone 10x10 button: spaced, so manual review


if __name__ == "__main__":
    unittest.main()
