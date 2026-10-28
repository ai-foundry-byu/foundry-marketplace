"""Tests for gen_stories.py. Run: python3 -m unittest discover -s scripts/tests"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gen_stories as g  # noqa: E402

PRD = """# Demo PRD

Intro prose that is not a story.

## 5. User stories

**US-01. A student signs in with a magic link.** (R-01, R-04)
Surfaces: /login, /dashboard
Devices: phone-390x844
1. The login page shows one email field and one `Send link` button.
2. Submitting a valid email shows "Check your inbox":
   - within 2 s
3. The link lands on /dashboard.
   - The old session is replaced; no second tab opens.

**US-02. Empty state is honest.** The dashboard says "No courses yet" when there are none.

**US-03. Struck criteria are dropped.**
1. ~~Old wording~~ New wording stays.
- A top-level bullet is a criterion too.

| table | ends a story |
|---|---|

## Appendix A. Addressed critiques

**US-99. Not a story, it is after the appendix.**
1. ignored
"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.stories = {s["id"]: s for s in g.parse_prd(PRD)}

    def test_finds_stories_and_stops_at_appendix(self):
        self.assertEqual(list(self.stories), ["US-01", "US-02", "US-03"])

    def test_title_strips_trailing_period(self):
        self.assertEqual(self.stories["US-01"]["title"], "A student signs in with a magic link")

    def test_numbered_criteria_and_sub_bullets(self):
        ac = self.stories["US-01"]["acceptance"]
        self.assertEqual(len(ac), 3)
        self.assertEqual(ac[0], "The login page shows one email field and one Send link button.")
        self.assertEqual(ac[1], 'Submitting a valid email shows "Check your inbox": within 2 s')
        self.assertEqual(ac[2], "The link lands on /dashboard. The old session is replaced; no second tab opens.")

    def test_meta_and_covers(self):
        s = self.stories["US-01"]
        self.assertEqual(s["meta"]["surfaces"], ["/login", "/dashboard"])
        self.assertEqual(s["meta"]["devices"], ["phone-390x844"])
        self.assertEqual(s["covers"], ["R-01", "R-04"])

    def test_lead_sentence_becomes_criterion(self):
        self.assertEqual(self.stories["US-02"]["acceptance"],
                         ['The dashboard says "No courses yet" when there are none.'])

    def test_strikethrough_and_top_bullets(self):
        self.assertEqual(self.stories["US-03"]["acceptance"],
                         ["New wording stays.", "A top-level bullet is a criterion too."])


class BuildTests(unittest.TestCase):
    def test_new_story_defaults(self):
        rows, errors, _ = g.build(PRD, {})
        self.assertEqual(errors, [])
        us2 = rows[1]
        self.assertEqual(us2["status"], "NOT_BUILT")
        self.assertEqual(us2["devices"], g.DEFAULT_DEVICES)
        self.assertEqual(us2["surfaces"], [])
        self.assertEqual(list(rows[0])[:7], list(g.KEY_ORDER[:7]))

    def test_preserves_status_and_extra_keys_and_unset_meta(self):
        existing = {"US-02": {"id": "US-02", "title": "old title", "acceptance": ["old"],
                              "surfaces": ["/home"], "devices": ["tablet-820x1180"],
                              "status": "LIVE", "waits_on": ["US-01"], "notes": "verified 11-02"}}
        rows, errors, _ = g.build(PRD, existing)
        self.assertEqual(errors, [])
        us2 = rows[1]
        self.assertEqual(us2["title"], "Empty state is honest")  # PRD wins for text
        self.assertEqual(us2["status"], "LIVE")
        self.assertEqual(us2["surfaces"], ["/home"])
        self.assertEqual(us2["devices"], ["tablet-820x1180"])
        self.assertEqual(us2["waits_on"], ["US-01"])
        self.assertEqual(us2["notes"], "verified 11-02")

    def test_prd_meta_overrides_existing(self):
        existing = {"US-01": {"id": "US-01", "surfaces": ["/old"], "status": "BUILT"}}
        rows, _, _ = g.build(PRD, existing)
        self.assertEqual(rows[0]["surfaces"], ["/login", "/dashboard"])
        self.assertEqual(rows[0]["status"], "BUILT")

    def test_story_without_criteria_is_an_error(self):
        prd = "**US-01. Has criteria.**\n1. yes\n\n**US-02. Bare.**\n\n## Next\n"
        # A bare heading with no lead and no criteria
        _, errors, _ = g.build(prd, {})
        self.assertTrue(any("US-02 has no acceptance criteria" in e for e in errors))

    def test_duplicate_ids_are_an_error(self):
        prd = "**US-01. A.**\n1. a\n\n**US-01. B.**\n1. b\n"
        _, errors, _ = g.build(prd, {})
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_unknown_status_is_an_error(self):
        _, errors, _ = g.build(PRD, {"US-01": {"id": "US-01", "status": "DONE"}})
        self.assertTrue(any("unknown status" in e for e in errors))

    def test_dropped_story_is_reported(self):
        _, _, notes = g.build(PRD, {"US-50": {"id": "US-50", "status": "BUILT"}})
        self.assertTrue(any("US-50" in n for n in notes))

    def test_no_stories_is_an_error(self):
        _, errors, _ = g.build("# nothing here\n", {})
        self.assertTrue(errors)


class CliTests(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = g.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_write_then_check_then_stale(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = Path(d, "PRD.md"), Path(d, "stories.json")
            prd.write_text(PRD)
            code, _, _ = self.run_main("--prd", str(prd), "--out", str(out), "--check")
            self.assertEqual(code, 1)  # missing file
            code, stdout, _ = self.run_main("--prd", str(prd), "--out", str(out))
            self.assertEqual(code, 0)
            self.assertIn("3 stories", stdout)
            self.assertEqual(self.run_main("--prd", str(prd), "--out", str(out), "--check")[0], 0)
            # a human verifies a story: status edit only, still fresh
            rows = json.loads(out.read_text())["stories"]
            rows[0]["status"] = "LIVE"
            out.write_text(g.render(rows))
            self.assertEqual(self.run_main("--prd", str(prd), "--out", str(out), "--check")[0], 0)
            # the PRD changes: now stale
            prd.write_text(PRD.replace("Old wording~~ New wording", "Old wording~~ Newer wording"))
            code, _, err = self.run_main("--prd", str(prd), "--out", str(out), "--check")
            self.assertEqual(code, 1)
            self.assertIn("STALE", err)
            # regenerate keeps the LIVE status
            self.assertEqual(self.run_main("--prd", str(prd), "--out", str(out))[0], 0)
            self.assertEqual(json.loads(out.read_text())["stories"][0]["status"], "LIVE")

    def test_invalid_prd_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = Path(d, "PRD.md"), Path(d, "stories.json")
            prd.write_text("**US-01. Bare.**\n\n## End\n")
            code, _, err = self.run_main("--prd", str(prd), "--out", str(out))
            self.assertEqual(code, 1)
            self.assertIn("no acceptance criteria", err)
            self.assertFalse(out.exists())

    def test_missing_prd_is_usage_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main("--prd", str(Path(d, "nope.md")))[0], 2)

    def test_corrupt_stories_json(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = Path(d, "PRD.md"), Path(d, "stories.json")
            prd.write_text(PRD)
            out.write_text("{not json")
            self.assertEqual(self.run_main("--prd", str(prd), "--out", str(out))[0], 1)



def git(d, *args):
    import subprocess
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com", "PATH": __import__("os").environ["PATH"],
           "HOME": str(d)}
    r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class ContractTests(unittest.TestCase):
    """C1: stories.json is {"stories": [...]} with every documented key."""

    def test_render_is_the_c1_object_shape(self):
        rows, errors, _ = g.build(PRD, {})
        self.assertEqual(errors, [])
        doc = json.loads(g.render(rows))
        self.assertEqual(list(doc), ["stories"])
        row = doc["stories"][0]
        self.assertEqual(list(row), list(g.KEY_ORDER))
        self.assertEqual(row["covers"], ["R-01", "R-04"])
        self.assertEqual(row["notes"], "")
        self.assertEqual(row["evidence"], [])
        self.assertEqual(doc["stories"][1]["covers"], [])

    def test_qa_block_and_unknown_keys_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = Path(d, "PRD.md"), Path(d, "stories.json")
            prd.write_text(PRD)
            with redirect_stdout(io.StringIO()):
                g.main(["--prd", str(prd), "--out", str(out)])
            doc = json.loads(out.read_text())
            doc["stories"][0]["qa"] = {"start": "/login", "steps": [{"goto": "/login"}]}
            doc["generated_by"] = "a human"
            out.write_text(json.dumps(doc))
            with redirect_stdout(io.StringIO()):
                g.main(["--prd", str(prd), "--out", str(out)])
            again = json.loads(out.read_text())
            self.assertEqual(again["stories"][0]["qa"]["start"], "/login")
            self.assertEqual(again["generated_by"], "a human")

    def test_legacy_array_is_read_then_stale_then_migrated(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = Path(d, "PRD.md"), Path(d, "stories.json")
            prd.write_text(PRD)
            out.write_text(json.dumps([{"id": "US-01", "status": "BUILT"}]))
            self.assertEqual(g.load_stories(out)[0]["status"], "BUILT")
            ok, msgs = g.check(prd, out)
            self.assertFalse(ok)
            self.assertIn("array", msgs[0])
            with redirect_stdout(io.StringIO()):
                g.main(["--prd", str(prd), "--out", str(out)])
            self.assertEqual(json.loads(out.read_text())["stories"][0]["status"], "BUILT")
            self.assertTrue(g.check(prd, out)[0])


class SetStatusTests(unittest.TestCase):
    """--set US-01=LIVE refuses unless committed, gated on that SHA, and evidenced."""

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = g.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def project(self, d):
        git(d, "init", "-q")
        Path(d, "app.py").write_text("print('hi')\n")
        prd, out = Path(d, "PRD.md"), Path(d, "stories.json")
        prd.write_text(PRD)
        with redirect_stdout(io.StringIO()):
            g.main(["--prd", str(prd), "--out", str(out)])
        git(d, "add", "-A")
        git(d, "commit", "-qm", "build")
        return prd, out

    def gate(self, d, sha, code=0):
        rep = Path(d, ".qa", "done-gate")
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "last.json").write_text(json.dumps({"sha": sha, "exit": code,
                                                   "journey": "done-journey.yaml",
                                                   "time": "2026-11-03T10:00:00Z"}))

    def verify(self, d, sid="US-01"):
        v = Path(d, ".qa", "verify")
        v.mkdir(parents=True, exist_ok=True)
        (v / f"{sid}.md").write_text("Result: 3 PASS")
        return str(v / f"{sid}.md")

    def test_live_refused_without_gate_report(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d))
            self.assertEqual(code, 1)
            self.assertIn("done-gate", msg)
            self.assertEqual(g.load_stories(out)[0]["status"], "NOT_BUILT")

    def test_live_refused_on_dirty_tree(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            self.gate(d, git(d, "rev-parse", "HEAD"))
            Path(d, "app.py").write_text("print('changed')\n")
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d))
            self.assertEqual(code, 1)
            self.assertIn("uncommitted", msg)

    def test_live_refused_when_gate_failed_or_ran_on_other_code(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            old = git(d, "rev-parse", "HEAD")
            self.gate(d, old, code=1)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d))
            self.assertEqual(code, 1)
            self.assertIn("exit 1", msg)
            self.gate(d, old)
            Path(d, "app.py").write_text("print('v2')\n")
            git(d, "commit", "-qam", "v2")
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d))
            self.assertEqual(code, 1)
            self.assertIn("app.py", msg)

    def test_live_refused_without_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            self.gate(d, git(d, "rev-parse", "HEAD"))
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE")
            self.assertEqual(code, 1)
            self.assertIn("evidence", msg)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", ".qa/verify/missing.md")
            self.assertEqual(code, 1)

    def test_live_accepted_records_sha_and_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            # an artifact-only commit after the gate still counts as the same build
            Path(d, "CHANGELOG.md").write_text("# log\n")
            git(d, "add", "-A")
            git(d, "commit", "-qm", "docs")
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d))
            self.assertEqual(code, 0, msg)
            row = g.load_stories(out)[0]
            self.assertEqual(row["status"], "LIVE")
            self.assertIn(f"commit:{git(d, 'rev-parse', 'HEAD')}", row["evidence"])
            self.assertTrue(any(e.endswith("US-01.md") for e in row["evidence"]))
            self.assertTrue(g.check(prd, out)[0])

    def test_partial_needs_no_gate(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-02=PARTIAL")
            self.assertEqual(code, 0, msg)
            self.assertEqual(g.load_stories(out)[1]["status"], "PARTIAL")
            self.assertEqual(self.run_main("--prd", str(prd), "--out", str(out),
                                           "--set", "US-02=DONE")[0], 2)


if __name__ == "__main__":
    unittest.main()
