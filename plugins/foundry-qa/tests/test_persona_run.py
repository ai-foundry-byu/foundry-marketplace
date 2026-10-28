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
            {"stories": [{"id": "a", "title": "t", "start": "/", "acceptance": ["x"], "bogus": 1}]},
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


if __name__ == "__main__":
    unittest.main()
