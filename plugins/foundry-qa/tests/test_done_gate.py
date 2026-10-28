import json
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
import done_gate as dg

GOOD = {"name": "home", "steps": [{"goto": "/"}, {"click": "text=About"}],
        "assertions": [{"visible": "h1"}], "devices": ["phone-390x844"]}


class TestValidation(unittest.TestCase):
    def test_good(self):
        j = dg.validate_journey(GOOD, "x")
        self.assertEqual(j.devices, ["phone-390x844"])
        self.assertEqual(j.screenshot, "home")

    def test_default_device(self):
        d = dict(GOOD)
        d.pop("devices")
        self.assertEqual(dg.validate_journey(d).devices, ["desktop-1440x900"])

    def test_rejects(self):
        bad_cases = [
            {**GOOD, "steps": []},
            {**GOOD, "steps": [{"click": "a"}]},                      # first step not goto
            {**GOOD, "steps": [{"goto": "/"}, {"hover": "a"}]},       # unknown step
            {**GOOD, "steps": [{"goto": "/"}, {"fill": {"selector": "a"}}]},
            {**GOOD, "steps": [{"goto": "/", "click": "a"}]},         # two keys
            {**GOOD, "assertions": []},                                # asserts nothing
            {**GOOD, "assertions": [{"no_console_errors": False}]},
            {**GOOD, "assertions": [{"text": {"selector": "h1"}}]},
            {**GOOD, "devices": ["watch-40x40"]},
            {**GOOD, "unknown_key": 1},
            {**GOOD, "timeout_ms": -1},
            {**GOOD, "ignore_console": ["("]},
            {**GOOD, "sha_check": {"header": "x-sha"}},
            "not a mapping",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(dg.ConfigError):
                    dg.validate_journey(case, "x")

    def test_fill_value_coerced_to_string(self):
        d = {**GOOD, "steps": [{"goto": "/"}, {"fill": {"selector": "#age", "value": 42}}]}
        self.assertEqual(dg.validate_journey(d).steps[1]["fill"]["value"], "42")

    def test_load_journey_yaml_and_json(self):
        with tempfile.TemporaryDirectory() as td:
            y = Path(td) / "j.yaml"
            y.write_text("steps:\n  - goto: /\nassertions:\n  - visible: h1\n")
            self.assertEqual(dg.load_journey(str(y)).name, "j")
            js = Path(td) / "j.json"
            js.write_text(json.dumps(GOOD))
            self.assertEqual(dg.load_journey(str(js)).name, "home")
            bad = Path(td) / "b.yaml"
            bad.write_text("steps: [\n")
            with self.assertRaises(dg.ConfigError):
                dg.load_journey(str(bad))
            with self.assertRaises(dg.ConfigError):
                dg.load_journey(str(Path(td) / "missing.yaml"))

    def test_template_journey_is_valid(self):
        j = dg.load_journey(str(_paths.DONE_GATE_TEMPLATES / "done-journey.yaml"))
        self.assertTrue(j.steps and j.assertions)

    def test_resolve_url(self):
        self.assertEqual(dg.resolve_url("/a", "http://h:3000"), "http://h:3000/a")
        self.assertEqual(dg.resolve_url("a/b", "http://h/app/"), "http://h/app/a/b")
        self.assertEqual(dg.resolve_url("https://x.example/a", ""), "https://x.example/a")
        with self.assertRaises(dg.ConfigError):
            dg.resolve_url("/a", "")


class TestSha(unittest.TestCase):
    SHA = "0123456789abcdef0123456789abcdef01234567"

    def test_extract(self):
        self.assertEqual(dg.extract_sha({"X-Commit-Sha": self.SHA}, "", header="x-commit-sha"), self.SHA)
        self.assertIsNone(dg.extract_sha({"X-Commit-Sha": "not-a-sha"}, "", header="x-commit-sha"))
        self.assertEqual(dg.extract_sha({}, json.dumps({"build": {"commit": self.SHA[:12]}}), json_key="build.commit"),
                         self.SHA[:12])
        self.assertEqual(dg.extract_sha({}, json.dumps({"sha": self.SHA})), self.SHA)
        self.assertEqual(dg.extract_sha({}, f"<meta name=build content={self.SHA}>"), self.SHA)
        self.assertEqual(dg.extract_sha({}, "build: abc1234 ok", regex=r"build: ([0-9a-f]+)"), "abc1234")
        self.assertIsNone(dg.extract_sha({}, "nothing here"))

    def test_match(self):
        self.assertTrue(dg.sha_matches(self.SHA, self.SHA[:7]))
        self.assertTrue(dg.sha_matches(self.SHA[:10], self.SHA.upper()))
        self.assertFalse(dg.sha_matches(self.SHA, "fedcba9"))
        self.assertFalse(dg.sha_matches(self.SHA, self.SHA[:6]))  # too short to trust
        self.assertFalse(dg.sha_matches("", self.SHA))

    def test_check_retries_then_matches(self):
        answers = iter([(None, "unreachable"), ("fedcba9876543", "ok"), (self.SHA, "ok")])
        r = dg.check_sha(self.SHA, "u", fetch=lambda *a: next(answers), sleep=lambda s: None, retries=3)
        self.assertEqual(r.status, "match")

    def test_check_mismatch_after_retries(self):
        r = dg.check_sha(self.SHA, "u", fetch=lambda *a: ("fedcba9876543", "ok"), sleep=lambda s: None, retries=2)
        self.assertEqual(r.status, "mismatch")

    def test_check_unreadable(self):
        r = dg.check_sha(self.SHA, "u", fetch=lambda *a: (None, "unreachable: refused"), sleep=lambda s: None)
        self.assertEqual(r.status, "unreadable")

    def test_expected_sha_validation(self):
        self.assertEqual(dg.resolve_expected_sha("abc1234"), "abc1234")
        with self.assertRaises(dg.ConfigError):
            dg.resolve_expected_sha("main")


def R(status):
    return dg.DeviceResult(journey="j", device="d", status=status)


class TestExitCodes(unittest.TestCase):
    def test_contract(self):
        match = dg.ShaResult("match")
        self.assertEqual(dg.overall_exit(None, [R("pass"), R("pass")]), 0)
        self.assertEqual(dg.overall_exit(match, [R("pass")]), 0)
        self.assertEqual(dg.overall_exit(None, [R("pass"), R("fail")]), 1)
        self.assertEqual(dg.overall_exit(None, [R("fail"), R("inconclusive")]), 1)  # evidence beats no-evidence
        self.assertEqual(dg.overall_exit(None, [R("pass"), R("inconclusive")]), 6)  # never a pass
        self.assertEqual(dg.overall_exit(None, []), 6)
        self.assertEqual(dg.overall_exit(dg.ShaResult("mismatch"), [R("pass")]), 3)
        self.assertEqual(dg.overall_exit(dg.ShaResult("mismatch"), []), 3)
        self.assertEqual(dg.overall_exit(dg.ShaResult("unreadable"), []), 6)

    def test_cli_config_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.yaml"
            bad.write_text("steps:\n  - hover: a\nassertions:\n  - visible: h1\n")
            self.assertEqual(dg.main(["--journey", str(bad), "--validate"]), 2)
            good = Path(td) / "good.yaml"
            good.write_text("steps:\n  - goto: /\nassertions:\n  - visible: h1\n")
            self.assertEqual(dg.main(["--journey", str(good), "--validate"]), 2)  # relative goto, no base url
            self.assertEqual(dg.main(["--journey", str(good), "--validate", "--base-url", "http://localhost:1"]), 0)
            self.assertEqual(dg.main(["--journey", str(good), "--validate", "--base-url", "http://x",
                                      "--devices", "fridge"]), 2)

    def test_cli_sha_mismatch_exits_3_without_browser(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.yaml"
            good.write_text("steps:\n  - goto: http://127.0.0.1:9/\nassertions:\n  - visible: h1\n")
            orig = dg.fetch_sha
            dg.fetch_sha = lambda *a, **k: ("fedcba9876543210", "ok")
            try:
                code = dg.main(["--journey", str(good), "--out", str(Path(td) / "qa"), "--sha-url", "http://x/v",
                                "--expected-sha", "0123456789abcdef", "--sha-retries", "1"])
            finally:
                dg.fetch_sha = orig
            self.assertEqual(code, 3)
            latest = json.loads((Path(td) / "qa" / "latest.json").read_text())
            self.assertEqual(latest["exit_code"], 3)
            self.assertEqual(latest["results"], [])


SDLC_TEMPLATE = _paths.PLUGIN.parent / "foundry-sdlc" / "skills" / "new-project" / "templates" / "done-journey.yaml"


class TestContractC2(unittest.TestCase):
    """done-journey.yaml as foundry-sdlc scaffolds it: stories and auth are documented keys."""

    def test_stories_and_auth_are_accepted(self):
        j = dg.validate_journey({**GOOD, "stories": ["US-01", "US-02"],
                                 "auth": {"storage_state": ".qa/auth.json"}}, "x")
        self.assertEqual(j.stories, ["US-01", "US-02"])
        self.assertEqual(j.auth, {"storage_state": ".qa/auth.json"})
        self.assertEqual(dg.validate_journey({**GOOD, "stories": "US-03"}).stories, ["US-03"])

    def test_unknown_top_level_key_still_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "j.yaml"
            f.write_text("stories: [US-01]\nowner: me\nsteps:\n  - goto: http://x/\nassertions:\n  - visible: h1\n")
            self.assertEqual(dg.main(["--journey", str(f), "--validate"]), 2)

    def test_bad_auth_is_a_config_error(self):
        for auth in ({"token": "x"}, {"login_steps": [{"hover": "a"}]}):
            with self.subTest(auth=auth):
                with self.assertRaises(dg.ConfigError):
                    dg.validate_journey({**GOOD, "auth": auth})

    def test_template_has_exactly_the_contract_keys(self):
        data = dg.qa_yaml.load_file(str(_paths.DONE_GATE_TEMPLATES / "done-journey.yaml"))
        self.assertEqual(set(data), {"name", "base_url", "devices", "stories", "steps", "assertions", "screenshot"})
        self.assertIn("PORT", data["base_url"])
        self.assertEqual(dg.main(["--journey", str(_paths.DONE_GATE_TEMPLATES / "done-journey.yaml"), "--validate"]), 0)

    @unittest.skipUnless(SDLC_TEMPLATE.is_file(), "foundry-sdlc is not next to this plugin")
    def test_foundry_sdlc_template_validates(self):
        self.assertEqual(dg.main(["--journey", str(SDLC_TEMPLATE), "--validate"]), 0)

    def test_port_placeholder(self):
        self.assertEqual(dg.resolve_base("http://localhost:PORT", "5173"), "http://localhost:5173")
        self.assertEqual(dg.resolve_base("http://localhost:3000", None), "http://localhost:3000")
        for port in (None, "abc"):
            with self.assertRaises(dg.ConfigError):
                dg.resolve_base("http://localhost:PORT", port)


class TestLastJson(unittest.TestCase):
    def test_record_shape(self):
        j = dg.validate_journey({**GOOD, "stories": ["US-01"]}, "qa/done-journey.yaml")
        r = dg.DeviceResult("home", "phone-390x844", "fail", reason="h1 not visible")
        rec = dg.last_record(1, [j], "a" * 40, dg.failures_from([r], None))
        for k in ("sha", "exit", "journey", "devices", "time", "failures"):
            self.assertIn(k, rec)
        self.assertEqual((rec["sha"], rec["exit"], rec["journey"]), ("a" * 40, 1, "qa/done-journey.yaml"))
        self.assertEqual(rec["devices"], ["phone-390x844"])
        self.assertEqual(rec["stories"], ["US-01"])
        self.assertEqual(rec["failures"], [{"journey": "home", "device": "phone-390x844", "status": "fail",
                                            "reason": "h1 not visible"}])

    def test_written_after_a_config_error_but_not_after_validate(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "j.yaml"
            f.write_text("base_url: http://localhost:PORT\nsteps:\n  - goto: /\nassertions:\n  - visible: h1\n")
            out = Path(td) / "qa"
            self.assertEqual(dg.main(["--journey", str(f), "--validate", "--out", str(out)]), 0)
            self.assertFalse((out / "last.json").exists())
            self.assertEqual(dg.main(["--journey", str(f), "--out", str(out)]), 2)   # PORT and no --port
            last = json.loads((out / "last.json").read_text())
            self.assertEqual(last["exit"], 2)
            self.assertIn("PORT", last["failures"][0]["reason"])

    def test_written_after_sha_mismatch_with_git_head(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.yaml"
            good.write_text("steps:\n  - goto: http://127.0.0.1:9/\nassertions:\n  - visible: h1\n")
            orig = dg.fetch_sha
            dg.fetch_sha = lambda *a, **k: ("fedcba9876543210", "ok")
            try:
                dg.main(["--journey", str(good), "--out", str(Path(td) / "qa"), "--sha-url", "http://x/v",
                         "--expected-sha", "0123456789abcdef", "--sha-retries", "1"])
            finally:
                dg.fetch_sha = orig
            last = json.loads((Path(td) / "qa" / "last.json").read_text())
            self.assertEqual(last["exit"], 3)
            self.assertEqual(last["sha"], dg.git_head())
            self.assertEqual(last["failures"][0]["status"], "sha-mismatch")


class TestReadOnly(unittest.TestCase):
    def test_decide(self):
        for m in ("GET", "HEAD", "OPTIONS", "get"):
            self.assertEqual(dg.decide_request(m), "allow")
        for m in ("POST", "PUT", "PATCH", "DELETE", "PROPFIND"):
            self.assertEqual(dg.decide_request(m), "block")

    def test_filters(self):
        self.assertEqual(dg.filter_console(["a: favicon 404", "real error"], ["favicon"]), ["real error"])
        self.assertTrue(dg._is_network_error("net::ERR_CONNECTION_REFUSED at http://x"))
        self.assertEqual(dg._hit_auth_wall("https://x/login?next=/", ["/login"]), "/login")
        self.assertIsNone(dg._hit_auth_wall("https://x/home", ["/login"]))


if __name__ == "__main__":
    unittest.main()
