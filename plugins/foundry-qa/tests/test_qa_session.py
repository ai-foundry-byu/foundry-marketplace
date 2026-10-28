"""Signed-in sessions (contract C3), the Playwright-missing fix, and settle()."""
import argparse
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import _paths  # noqa: F401
import done_gate as dg
import qa_session as qs


def args_for(argv):
    ap = argparse.ArgumentParser()
    qs.add_auth_args(ap)
    return ap.parse_args(argv)


class TestAuthBlock(unittest.TestCase):
    def test_each_form_parses(self):
        self.assertEqual(qs.parse_auth({"storage_state": ".qa/auth.json"}), {"storage_state": ".qa/auth.json"})
        self.assertEqual(qs.parse_auth({"headers": {"X-QA": 1}}), {"headers": {"X-QA": "1"}})
        c = qs.parse_auth({"cookies": [{"name": "s", "value": "ok", "domain": "localhost", "path": "/"}]})
        self.assertEqual(c["cookies"][0]["name"], "s")
        steps = qs.parse_auth({"login_steps": [{"goto": "/login"}, {"click": "#go"}]}, validate_step=dg.validate_step)
        self.assertEqual(steps["login_steps"][1], {"click": "#go"})
        self.assertIsNone(qs.parse_auth(None))

    def test_rejects(self):
        bad = [{}, {"token": "x"}, {"storage_state": ""}, {"headers": {}}, {"cookies": [{"name": "s"}]},
               {"cookies": [{"name": "s", "value": "v", "bogus": 1}]},
               {"login_steps": [{"click": "#go"}]},              # first step must be a goto
               {"login_steps": [{"goto": "/"}, {"hover": "x"}]}]   # unknown step
        for case in bad:
            with self.subTest(case=case):
                with self.assertRaises((qs.SessionError, dg.ConfigError)):
                    qs.parse_auth(case, validate_step=dg.validate_step)

    def test_env_expansion(self):
        self.assertEqual(qs.expand_env("Bearer ${QA_T}", {"QA_T": "abc"}), "Bearer abc")
        with self.assertRaises(qs.SessionError):
            qs.expand_env("${NOPE_NOT_SET_X}", {})

    def test_cookie_defaults_to_base_url(self):
        auth = {"cookies": [{"name": "s", "value": "v"}, {"name": "t", "value": "w", "domain": "example.com"}]}
        out = qs.cookies_for(auth, "http://127.0.0.1:4173/app")
        self.assertEqual(out[0]["url"], "http://127.0.0.1:4173")
        self.assertEqual(out[1]["path"], "/")

    def test_cli_and_file(self):
        with tempfile.TemporaryDirectory() as td:
            j = Path(td) / "journey.yaml"
            j.write_text("auth:\n  headers: {X-A: one}\nsteps:\n  - goto: /\nassertions:\n  - visible: h1\n")
            auth = qs.auth_from_args(args_for(["--auth", str(j), "--header", "X-B: two",
                                               "--storage-state", "s.json"]), dg.validate_step)
            self.assertEqual(auth, {"headers": {"X-A": "one", "X-B": "two"}, "storage_state": "s.json"})
            with self.assertRaises(qs.SessionError):
                qs.auth_from_args(args_for(["--header", "no-colon"]))
            self.assertIsNone(qs.auth_from_args(args_for([])))

    def test_missing_storage_state_is_a_config_error_with_the_fix(self):
        with self.assertRaises(qs.SessionError) as cm:
            qs.check_ready({"storage_state": "/no/such/auth.json"})
        self.assertIn("login --url", str(cm.exception))


class FakeLauncher:
    def __init__(self, exc):
        self.exc = exc

    def launch(self, headless=True):
        raise self.exc


class FakePw:
    def __init__(self, exc):
        self.chromium = FakeLauncher(exc)


class TestBrowserMissing(unittest.TestCase):
    def test_missing_executable_becomes_the_fix(self):
        exc = Exception("BrowserType.launch: Executable doesn't exist at /x/chrome-headless-shell\n"
                        "Looks like Playwright was just installed or updated. Please run: playwright install")
        with self.assertRaises(qs.BrowserMissing) as cm:
            qs.launch(FakePw(exc), "chromium")
        msg = str(cm.exception)
        self.assertIn("python3 -m playwright install chromium", msg)
        self.assertIn("venv", msg)

    def test_other_launch_errors_pass_through(self):
        with self.assertRaises(RuntimeError):
            qs.launch(FakePw(RuntimeError("sandbox crashed")), "chromium")

    def test_done_gate_prints_fix_and_exits_2(self):
        orig = qs.import_sync_playwright

        def boom(browser="chromium"):
            raise qs.BrowserMissing(qs.playwright_fix(browser))
        qs.import_sync_playwright = boom
        try:
            with tempfile.TemporaryDirectory() as td:
                j = Path(td) / "j.yaml"
                j.write_text("steps:\n  - goto: http://127.0.0.1:9/\nassertions:\n  - visible: h1\n")
                err = io.StringIO()
                with redirect_stderr(err):
                    code = dg.main(["--journey", str(j), "--out", str(Path(td) / "qa")])
                self.assertEqual(code, 2)
                self.assertIn("python3 -m playwright install chromium", err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())
                last = json.loads((Path(td) / "qa" / "last.json").read_text())
                self.assertEqual(last["exit"], 2)
        finally:
            qs.import_sync_playwright = orig


class FakePage:
    def __init__(self):
        self.waited = 0

    def on(self, *_a):
        pass

    def wait_for_timeout(self, ms):
        self.waited += ms
        time.sleep(ms / 1000.0)


class TestSettle(unittest.TestCase):
    def test_ready_is_when_the_last_request_ended_not_after_the_settle(self):
        page = FakePage()
        tracker = qs.NetTracker(page)
        tracker.inflight, tracker.last = 0, time.monotonic() - 2
        t = time.monotonic()
        ready, note = qs.settle(page, tracker, 2000, None, settle_ms=50)
        self.assertLess(ready - t, 0.05)        # quiet already: content was ready on entry
        self.assertEqual(note, "")
        self.assertGreaterEqual(page.waited, 50)

    def test_never_quiet_is_noted(self):
        page = FakePage()
        tracker = qs.NetTracker(page)
        tracker.inflight = 1
        _, note = qs.settle(page, tracker, 300, None, settle_ms=0)
        self.assertIn("never went quiet", note)


if __name__ == "__main__":
    unittest.main()
