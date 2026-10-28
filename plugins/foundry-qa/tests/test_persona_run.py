import json
import unittest

import _paths  # noqa: F401
import persona_run as pr
import qa_yaml
from done_gate import ConfigError

PERSONA = """---
name: First-time mobile user
devices: [phone-390x844, tablet-820x1180]
patience_seconds: 8
min_tap_target_px: 44
---
# Body
Never used the app.
"""


class TestPersona(unittest.TestCase):
    def test_parse(self):
        p = pr.parse_persona(PERSONA, "p.md")
        self.assertEqual(p.name, "First-time mobile user")
        self.assertEqual(p.devices, ["phone-390x844", "tablet-820x1180"])
        self.assertEqual((p.patience_seconds, p.min_tap_target_px), (8.0, 44))
        self.assertIn("Never used", p.body)

    def test_rejects(self):
        for text in ("no frontmatter", "---\nfoo: 1\n---\n", "---\nname: x\ndevices: [fridge]\n---\n",
                     "---\nname: x\npatience_seconds: 0\n---\n"):
            with self.subTest(text=text):
                with self.assertRaises(ConfigError):
                    pr.parse_persona(text)

    def test_templates_parse(self):
        for f in sorted((_paths.PERSONA_TEMPLATES / "personas").glob("*.md")):
            with self.subTest(f=f.name):
                p = pr.parse_persona(f.read_text(), str(f))
                self.assertTrue(p.name)

    def test_example_stories_parse(self):
        stories = pr.parse_stories(qa_yaml.load_file(str(_paths.PERSONA_TEMPLATES / "stories.example.json")))
        self.assertGreaterEqual(len(stories), 3)


class TestStories(unittest.TestCase):
    def test_parse_and_plan(self):
        data = {"stories": [
            {"id": "S-1", "title": "see home", "start": "/", "assertions": [{"visible": "h1"}]},
            {"id": "S-2", "title": "desktop only", "start": "/admin", "acceptance": ["looks right"],
             "devices": ["desktop-1440x900", "phone-390x844"]},
        ]}
        stories = pr.parse_stories(data)
        persona = pr.parse_persona(PERSONA)
        matrix = pr.plan(stories, persona, None)
        self.assertEqual([(s.id, d) for s, d in matrix],
                         [("S-1", "phone-390x844"), ("S-1", "tablet-820x1180"), ("S-2", "phone-390x844")])
        self.assertEqual(len(pr.plan(stories, persona, ["desktop-1440x900"])), 2)

    def test_rejects(self):
        bad = [
            {"stories": []},
            {"stories": [{"id": "a", "title": "t"}]},
            {"stories": [{"id": "a", "title": "t", "start": "/"}]},          # nothing to check
            {"stories": [{"id": "a", "title": "t", "start": "/", "acceptance": ["x"]},
                         {"id": "a", "title": "t", "start": "/", "acceptance": ["x"]}]},
            {"stories": [{"id": "a", "title": "t", "start": "/", "steps": [{"hover": "x"}], "acceptance": ["x"]}]},
        ]
        for case in bad:
            with self.subTest(case=json.dumps(case)[:60]):
                with self.assertRaises(ConfigError):
                    pr.parse_stories(case)


class TestSafety(unittest.TestCase):
    def test_writes_allowed_only_local(self):
        for u in ("http://localhost:3000", "http://127.0.0.1:8000/x", "http://[::1]:3000", "http://app.localhost"):
            self.assertTrue(pr.writes_allowed(u), u)
        for u in ("https://myapp.example.com", "https://staging.example.com", "http://10.0.0.5", "http://localhost.evil.com"):
            self.assertFalse(pr.writes_allowed(u), u)

    def test_cli_refuses_writes_on_remote(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "p.md"
            p.write_text(PERSONA)
            s = Path(td) / "s.json"
            s.write_text(json.dumps({"stories": [{"id": "a", "title": "t", "start": "/", "acceptance": ["x"]}]}))
            code = pr.main(["--persona", str(p), "--stories", str(s), "--base-url", "https://prod.example.com",
                            "--allow-writes", "--plan"])
            self.assertEqual(code, 2)
            code = pr.main(["--persona", str(p), "--stories", str(s), "--base-url", "https://prod.example.com", "--plan"])
            self.assertEqual(code, 0)


class TestVerdictAndTickets(unittest.TestCase):
    def test_classify(self):
        ok = [{"passed": True, "detail": ""}]
        bad = [{"passed": False, "detail": "h1 not visible"}]
        cok = [{"check": "patience", "passed": True, "detail": ""}]
        cbad = [{"check": "tap-targets", "passed": False, "detail": "2 small"}]
        self.assertEqual(pr.classify(ok, cok, True)[0], "passed")
        self.assertEqual(pr.classify(bad, cok, True), ("failed", "h1 not visible"))
        self.assertEqual(pr.classify(ok, cbad, True), ("failed", "tap-targets: 2 small"))
        self.assertEqual(pr.classify([], cok, False)[0], "needs-judgment")
        self.assertEqual(pr.classify([], cbad, False)[0], "failed")  # a failed check is still a failure

    def test_run_verdict(self):
        R = lambda s: pr.StoryResult("a", "t", "d", s)
        self.assertEqual(pr.run_verdict([R("passed"), R("needs-judgment")]), 0)
        self.assertEqual(pr.run_verdict([R("passed"), R("failed"), R("inconclusive")]), 1)
        self.assertEqual(pr.run_verdict([R("passed"), R("inconclusive")]), 6)
        self.assertEqual(pr.run_verdict([]), 6)

    def test_only_reproduced_failures_become_tickets(self):
        prev = [{"story": "A", "device": "p", "status": "failed"}, {"story": "B", "device": "p", "status": "failed"},
                {"story": "C", "device": "p", "status": "passed"}]
        cur = [{"story": "A", "device": "p", "status": "failed"}, {"story": "B", "device": "p", "status": "passed"},
               {"story": "C", "device": "p", "status": "failed"}, {"story": "A", "device": "d", "status": "failed"}]
        self.assertEqual([(r["story"], r["device"]) for r in pr.reproduced_failures(prev, cur)], [("A", "p")])

    def test_ticket_has_repro(self):
        r = {"story": "S-1", "title": "sign up", "device": "phone-390x844", "status": "failed", "reason": "x",
             "steps": [{"goto": "/"}, {"click": "text=Sign up"}],
             "checks": [{"check": "no-overflow", "passed": False, "detail": "page is 600px wide"}],
             "assertions": [], "acceptance": ["user sees the form"], "screenshot": "s.png"}
        t = pr.render_ticket(r, "First-time mobile user", "http://localhost:3000")
        self.assertIn("## Steps to reproduce", t)
        self.assertIn('2. click "text=Sign up"', t)
        self.assertIn("no-overflow: page is 600px wide", t)


# The foundry-sdlc stories.json (contract C1): one file per project, read as is.
SDLC = [
    {"id": "US-01", "title": "see the groups", "acceptance": ["The list shows every group"],
     "surfaces": ["/"], "devices": ["phone-390x844", "desktop-1440x900"], "status": "BUILT",
     "waits_on": [], "covers": ["R-01"], "notes": "", "evidence": [], "owner": "someone"},
    {"id": "US-02", "title": "create a group", "acceptance": ["A new group appears"],
     "surfaces": ["/create"], "devices": ["desktop-1440x900", "ios-sim"], "status": "PARTIAL", "waits_on": [],
     "qa": {"start": "/#/create", "steps": [{"fill": {"selector": "#name", "value": "x"}}],
            "assertions": [{"visible": "#name"}], "wait_for": "form", "retries": 2}},
    {"id": "US-03", "title": "native only", "acceptance": ["works"], "surfaces": ["Home screen"],
     "devices": ["ios-sim"], "status": "BUILT", "waits_on": []},
    {"id": "US-04", "title": "later", "acceptance": ["later"], "surfaces": ["/later"], "devices": [],
     "status": "NOT_BUILT", "waits_on": ["US-01"]},
]


class TestSdlcStories(unittest.TestCase):
    def test_list_and_wrapped_shapes_parse_with_warnings_not_errors(self):
        for data in (SDLC, {"stories": SDLC}):
            warnings = []
            stories = {s.id: s for s in pr.parse_stories(json.loads(json.dumps(data)), "s.json", warnings)}
            self.assertEqual(set(stories), {"US-01", "US-02", "US-03", "US-04"})
            self.assertTrue(any("owner" in w for w in warnings), warnings)
            self.assertTrue(any("retries" in w for w in warnings), warnings)
            self.assertTrue(any("ios-sim" in w for w in warnings), warnings)

    def test_start_scripting_and_devices(self):
        s = {x.id: x for x in pr.parse_stories(SDLC)}
        self.assertEqual((s["US-01"].start, s["US-01"].scripted, s["US-01"].assertions), ("/", False, []))
        self.assertEqual((s["US-02"].start, s["US-02"].scripted, s["US-02"].wait_for), ("/#/create", True, "form"))
        self.assertEqual(s["US-02"].devices, ["desktop-1440x900"])        # ios-sim dropped
        self.assertTrue(s["US-03"].skip_reason)                            # no path, no web device
        self.assertIsNone(s["US-04"].devices)                              # [] = not narrowed

    def test_select_skips_unbuilt_unless_named(self):
        stories = pr.parse_stories(SDLC)
        run, skipped = pr.select_stories(stories, None)
        self.assertEqual([s.id for s in run], ["US-01", "US-02"])
        self.assertEqual({s.id for s, _ in skipped}, {"US-03", "US-04"})
        run, _ = pr.select_stories(stories, ["US-04"])
        self.assertEqual([s.id for s in run], ["US-04"])
        with self.assertRaises(ConfigError):
            pr.select_stories(stories, ["US-99"])

    def test_plan_cli_reads_the_sdlc_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "p.md"
            p.write_text(PERSONA)
            f = Path(td) / "stories.json"
            f.write_text(json.dumps({"stories": SDLC}))
            self.assertEqual(pr.main(["--persona", str(p), "--stories", str(f), "--base-url",
                                      "http://localhost:3000", "--plan"]), 0)


class TestSiteWideChecks(unittest.TestCase):
    def test_site_scope_never_fails_a_story(self):
        site = [{"check": "tap-targets", "scope": "site", "passed": False, "detail": "9 small", "items": ["a"]}]
        ok = [{"check": "patience", "passed": True, "detail": ""}]
        self.assertEqual(pr.classify([{"passed": True, "detail": ""}], ok + site, True)[0], "passed")
        self.assertEqual(pr.classify([], ok + site, False)[0], "needs-judgment")

    def test_reported_once_per_device(self):
        def R(story, device, items):
            r = pr.StoryResult(story, "t", device, "passed")
            r.checks = [{"check": "tap-targets", "scope": "site", "passed": not items, "detail": "", "items": items}]
            return r
        results = [R("A", "phone-390x844", ["a x"]), R("B", "phone-390x844", ["a x", "b y"]), R("A", "tablet-820x1180", [])]
        self.assertEqual(pr.site_findings(results), {"phone-390x844": ["a x", "b y"]})
        report = pr.render_report(pr.parse_persona(PERSONA), results, "http://x", True, [("US-9", "status PARKED")], ["w1"])
        self.assertEqual(report.count("## Site-wide persona checks"), 1)
        self.assertIn("US-9: status PARKED", report)
        self.assertIn("- w1", report)


class TestSurfacesAndRoutePatterns(unittest.TestCase):
    """R3-D4: every surface is opened. R1a-D5/R1b-D5: route patterns are never opened literally."""

    def parse(self, **story):
        base = {"id": "US-1", "title": "t", "acceptance": ["x"], "status": "BUILT"}
        base.update(story)
        return pr.parse_stories([base])[0]

    def test_route_patterns(self):
        for p in ("/groups/:id", "/groups/{id}", "/groups/<id>", "/groups/[id]", "/#/group/:gid/edit"):
            self.assertTrue(pr.is_route_pattern(p), p)
        for p in ("/groups/1", "/", "/#/group/1", "/search?q=a"):
            self.assertFalse(pr.is_route_pattern(p), p)
        self.assertEqual(pr.fill_params("/groups/:id/{tab}", {"id": 1, "tab": "members"}), "/groups/1/members")

    def test_every_path_surface_is_opened(self):
        s = self.parse(surfaces=["/", "Group page", "/#/group/1", "/#/profile"])
        self.assertEqual(s.pages, ["/", "/#/group/1", "/#/profile"])
        self.assertEqual(s.start, "/")
        self.assertFalse(s.inconclusive)

    def test_pattern_only_story_is_inconclusive_not_a_404(self):
        s = self.parse(surfaces=["/groups/:id"])
        self.assertIn("needs a concrete URL (add qa.start)", s.inconclusive)
        self.assertFalse(s.skip_reason)
        run, skipped = pr.select_stories([s], None)
        self.assertEqual(run, [s])                       # reported as an inconclusive row, not hidden as "not run"

    def test_mixed_surfaces_open_the_concrete_ones_and_flag_the_pattern(self):
        s = self.parse(surfaces=["/groups", "/groups/:id"])
        self.assertEqual(s.pages, ["/groups"])
        self.assertEqual(s.unresolved, ["/groups/:id"])

    def test_qa_params_and_qa_start_resolve_patterns(self):
        s = self.parse(surfaces=["/groups", "/groups/:id"], qa={"params": {"id": "7"}})
        self.assertEqual((s.pages, s.unresolved, s.inconclusive), (["/groups", "/groups/7"], [], ""))
        s = self.parse(surfaces=["/groups/:id"], qa={"start": "/groups/1"})
        self.assertEqual((s.start, s.pages, s.inconclusive), ("/groups/1", ["/groups/1"], ""))
        s = self.parse(surfaces=["/groups/:id"], qa={"start": "/groups/:id"})
        self.assertIn("needs a concrete URL", s.inconclusive)

    def test_scripted_story_runs_from_one_start(self):
        s = self.parse(surfaces=["/groups/:id", "/groups"], qa={"assertions": [{"visible": "h1"}]})
        self.assertIn("needs a concrete URL (add qa.start)", s.inconclusive)   # its steps belong to surfaces[0]
        s = self.parse(surfaces=["/groups", "/about"], qa={"assertions": [{"visible": "h1"}]})
        self.assertEqual((s.start, s.pages), ("/groups", ["/groups"]))

    def test_bad_params_rejected(self):
        with self.assertRaises(ConfigError):
            self.parse(surfaces=["/groups/:id"], qa={"params": ["id", 1]})

    def test_plan_lists_the_pattern_story(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "p.md"
            p.write_text(PERSONA)
            f = Path(td) / "stories.json"
            f.write_text(json.dumps([{"id": "US-5", "title": "detail", "acceptance": ["x"], "surfaces": ["/g/:id"]}]))
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = pr.main(["--persona", str(p), "--stories", str(f), "--base-url", "http://localhost:3000", "--plan"])
            self.assertEqual(code, 0)
            self.assertIn("INCONCLUSIVE", buf.getvalue())



class TestEveryFailureAndExpectedConsole(unittest.TestCase):
    def test_classify_names_every_failing_check(self):
        bad = [{"passed": False, "detail": "h1 not visible"}]
        cbad = [{"check": "no-overflow", "passed": False, "detail": "page is 900px wide"},
                {"check": "console", "passed": False, "detail": "1 error(s): boom"},
                {"check": "tap-targets", "scope": "site", "passed": False, "detail": "site-wide, not this story"}]
        status, reason = pr.classify(bad, cbad, True)
        self.assertEqual(status, "failed")
        self.assertIn("h1 not visible", reason)
        self.assertIn("no-overflow: page is 900px wide", reason)
        self.assertIn("console: 1 error(s): boom", reason)
        self.assertNotIn("site-wide", reason)
        self.assertTrue(reason.startswith("3 checks failed: "), reason)

    def test_report_lists_every_failing_check_per_row(self):
        persona = pr.parse_persona("---\nname: P\ndevices: [phone-390x844]\npatience_seconds: 5\n---\nx\n")
        r = pr.StoryResult("S-1", "t", "phone-390x844", "failed", reason="2 checks failed: a; b",
                           checks=[{"check": "no-overflow", "passed": False, "detail": "wide"},
                                   {"check": "console", "passed": False, "detail": "1 error(s): boom"},
                                   {"check": "patience", "passed": True, "detail": "ok"}])
        report = pr.render_report(persona, [r], "http://x", True)
        self.assertIn("## Every failing check", report)
        self.assertIn("- no-overflow: wide", report)
        self.assertIn("- console: 1 error(s): boom", report)
        self.assertNotIn("- patience: ok", report)

    def test_expect_console_parses_and_filters_by_substring(self):
        s, = pr.parse_stories({"stories": [{"id": "S-1", "title": "bad route", "surfaces": ["/nope"],
                                            "acceptance": ["shows a 404 page"],
                                            "qa": {"expect_console": ["404 (Not Found)"]}}]})
        self.assertEqual(s.expect_console, ["404 (Not Found)"])
        errs = ["Failed to load resource: the server responded with a status of 404 (Not Found)", "uncaught: boom"]
        self.assertEqual(pr.unexpected_console(errs, s.expect_console), ["uncaught: boom"])
        self.assertEqual(pr.unexpected_console(errs, []), errs)

    def test_expect_console_rejects_bad_values(self):
        for bad in ("404", [""], [1]):
            with self.assertRaises(ConfigError):
                pr.parse_stories([{"id": "S-1", "title": "t", "surfaces": ["/"], "acceptance": ["a"],
                                   "qa": {"expect_console": bad}}])


if __name__ == "__main__":
    unittest.main()
