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
            rows = json.loads(out.read_text())
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
            self.assertEqual(json.loads(out.read_text())[0]["status"], "LIVE")

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


if __name__ == "__main__":
    unittest.main()
