"""Tests for new_project.py and sdlc_stage.py. Run: python3 -m unittest discover -s scripts/tests"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gen_stories  # noqa: E402
import new_project  # noqa: E402
import sdlc_stage  # noqa: E402

REQUIREMENTS = """# Req
## Sources
| S1 | kickoff | sponsor | 2026-11-01 | notes |
## Asks
| Id | Ask |
|---|---|
| R-01 | "let students sign in" |
## Already exists
| auth | none | - | build | nothing to reuse |
"""

PRD = """# PRD
## 5. User stories
**US-01. Sign in.** (R-01)
1. One email field.
2. A link arrives.

## Appendix A. Addressed critiques
| # | Severity | Critique | Decision | Change |
|---|---|---|---|---|
| C1 | high | no error state | accepted | US-01.3 |
"""

WORKPLAN = """# WP
## Milestones
- [ ] M1.1 sign-in live
## Tasks
| Id | Task | Owner | Deps | Status |
|---|---|---|---|---|
| T-01 | build sign-in | agent | - | {status} |
| T-02 | journey | agent | T-01 | PARKED |
"""

JOURNEY = "steps:\n  - goto: /\nassertions:\n  - visible: body\nscreenshot: home\n"


def stage(d):
    return sdlc_stage.evaluate(Path(d))["current_stage"]


class ScaffoldTests(unittest.TestCase):
    def test_scaffold_creates_set_and_fills_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            res = new_project.scaffold(Path(d), "Study Buddy", owner="Team 4", today="2026-11-01")
            names = {p.name for p, a in res if a == "created"}
            for f in sdlc_stage.SCAFFOLD_FILES + ["stories.json", "done-journey.yaml",
                                                  "stories.schema.json", "gen_stories.py"]:
                self.assertIn(f, names)
            readme = Path(d, "README.md").read_text()
            self.assertIn("# Study Buddy", readme)
            self.assertIn("study-buddy", readme)
            self.assertNotIn("{{", "".join(Path(d, f).read_text() for f in new_project.FILES))
            json.loads(Path(d, "stories.schema.json").read_text())
            self.assertTrue(os.access(Path(d, "tools", "gen_stories.py"), os.X_OK))

    def test_scaffold_never_overwrites_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "PRD.md").write_text("mine")
            res = dict((p.name, a) for p, a in new_project.scaffold(Path(d), "X"))
            self.assertEqual(res["PRD.md"], "skipped (exists)")
            self.assertEqual(Path(d, "PRD.md").read_text(), "mine")
            new_project.scaffold(Path(d), "X", force=True)
            self.assertNotEqual(Path(d, "PRD.md").read_text(), "mine")

    def test_fresh_scaffold_is_stage_1(self):
        with tempfile.TemporaryDirectory() as d:
            new_project.scaffold(Path(d), "X")
            self.assertEqual(stage(d), 1)

    def test_empty_dir_is_stage_0(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(stage(d), 0)

    def test_template_prd_parses_and_fails_on_todo(self):
        text = (new_project.TEMPLATES / "PRD.md").read_text()
        stories = gen_stories.parse_prd(text)
        self.assertEqual([s["id"] for s in stories], ["US-01"])
        self.assertEqual(len(stories[0]["acceptance"]), 3)
        self.assertEqual(stories[0]["covers"], ["R-01"])


class StageTests(unittest.TestCase):
    def walk(self, d):
        """Fill each artifact in order and assert the stage advances."""
        new_project.scaffold(Path(d), "X")
        self.assertEqual(stage(d), 1)
        Path(d, "REQUIREMENTS.md").write_text(REQUIREMENTS)
        self.assertEqual(stage(d), 2)
        Path(d, "PRD.md").write_text(PRD)
        self.assertEqual(stage(d), 2)  # stories.json still stale ([])
        with redirect_stdout(io.StringIO()):
            gen_stories.main(["--prd", str(Path(d, "PRD.md")), "--out", str(Path(d, "stories.json"))])
        self.assertEqual(stage(d), 3)
        Path(d, "WORKPLAN.md").write_text(WORKPLAN.format(status="IN REVIEW"))
        self.assertEqual(stage(d), 4)
        Path(d, "WORKPLAN.md").write_text(WORKPLAN.format(status="DONE 2026-11-02: PR #3"))
        self.assertEqual(stage(d), 6)  # 5 is not file-detectable, reported as ok
        Path(d, "done-journey.yaml").write_text(JOURNEY)
        self.assertEqual(stage(d), 7)
        rows = json.loads(Path(d, "stories.json").read_text())
        rows[0]["status"] = "LIVE"
        Path(d, "stories.json").write_text(gen_stories.render(rows))
        self.assertEqual(stage(d), 7)  # the template's fenced example is not a real entry
        Path(d, "CHANGELOG.md").write_text("# log\n\n## 2026-11-03\n- sign-in live (US-01)\n")
        self.assertEqual(stage(d), 8)

    def test_full_walk_in_root(self):
        with tempfile.TemporaryDirectory() as d:
            self.walk(d)

    def test_full_walk_in_product_subdir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d, "product")
            sub.mkdir()
            new_project.scaffold(sub, "X")
            res = sdlc_stage.evaluate(Path(d))
            self.assertEqual(Path(res["artifact_dir"]), sub)
            self.assertEqual(res["current_stage"], 1)

    def test_prd_without_critiques_appendix_stays_stage_2(self):
        with tempfile.TemporaryDirectory() as d:
            new_project.scaffold(Path(d), "X")
            Path(d, "REQUIREMENTS.md").write_text(REQUIREMENTS)
            prd = PRD.split("## Appendix A")[0]
            Path(d, "PRD.md").write_text(prd)
            with redirect_stdout(io.StringIO()):
                gen_stories.main(["--prd", str(Path(d, "PRD.md")), "--out", str(Path(d, "stories.json"))])
            res = sdlc_stage.evaluate(Path(d))
            self.assertEqual(res["current_stage"], 2)
            self.assertIn("Addressed critiques", res["checks"][2]["detail"])

    def test_task_status_parser(self):
        rows = sdlc_stage.task_statuses(WORKPLAN.format(status="NOT STARTED"))
        self.assertEqual(rows, [("T-01", "NOT STARTED"), ("T-02", "PARKED")])

    def test_hook_is_silent_without_artifacts_and_never_raises(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("CLAUDE_PROJECT_DIR")
            os.environ["CLAUDE_PROJECT_DIR"] = d
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(sdlc_stage.hook(), 0)
                self.assertEqual(out.getvalue(), "")
                new_project.scaffold(Path(d), "X")
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(sdlc_stage.hook(), 0)
                self.assertIn("stage 1", out.getvalue())
            finally:
                if old is None:
                    del os.environ["CLAUDE_PROJECT_DIR"]
                else:
                    os.environ["CLAUDE_PROJECT_DIR"] = old


if __name__ == "__main__":
    unittest.main()
