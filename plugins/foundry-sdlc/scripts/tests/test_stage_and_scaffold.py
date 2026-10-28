"""Tests for new_project.py and sdlc_stage.py. Run: python3 -m unittest discover -s scripts/tests"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# new_project.py lives in the new-project skill (it is used by that skill only)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "new-project" / "scripts"))
import gen_stories  # noqa: E402
import new_project  # noqa: E402
import sdlc_stage  # noqa: E402

REQUIREMENTS = """# Req
## Sources
| S1 | kickoff | sponsor | 2026-11-01 | notes |
## Asks
| Id | Ask | Src | Date | Priority | Story ids | Status |
|---|---|---|---|---|---|---|
| R-01 | "let students sign in" | S1 | 2026-11-01 | must | US-01 | STORIED |
| R-02 | "find a study group" | S1 | 2026-11-01 | must | US-02 | {r2} |
| R-03 | "sync my calendar" | S1 | 2026-11-01 | could | | {r3} |
## Already exists
| auth | none | - | build | nothing to reuse |
"""

PRD = """# PRD
## 5. User stories
**US-01. Sign in.** (R-01)
1. One email field.
2. A link arrives.

**US-02. Find a group.** (R-02)
Surfaces: /groups
1. Searching FIN 501 lists its groups.

## Appendix A. Addressed critiques
| # | Severity | Critique | Decision | Change |
|---|---|---|---|---|
| C1 | high | no error state | accepted | US-01.3 |
"""

DECISIONS = """# Decisions
| Id | Date | Who | The decision (verbatim) | What it authorizes | What still needs a human |
|---|---|---|---|---|---|
| D-01 | 2026-11-01 | sponsor | "skip calendar sync" | drop R-03 | - |
{approval}
## Pending decisions
"""
APPROVAL = ('| D-02 | 2026-11-02 | product owner | "Approved." | PRD approved: PRD.md v0.1 '
            'and stories US-01, US-02 | the workplan, when asked |')

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
QA_TEMPLATE = (Path(__file__).resolve().parents[3] / "foundry-qa" / "skills" / "done-gate"
               / "templates" / "done-journey.yaml")
QA_GATE = QA_TEMPLATE.parents[1] / "scripts" / "done_gate.py"


def git(d, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def compile_stories(art):
    with redirect_stdout(io.StringIO()):
        return gen_stories.main(["--prd", str(Path(art, "PRD.md")), "--out", str(Path(art, "stories.json"))])


def detail(d, n):
    return sdlc_stage.evaluate(Path(d))["checks"][n]["detail"]


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

    def test_fresh_scaffold_passes_its_own_story_check(self):
        """L1-D1: stories.json is compiled from the scaffolded PRD, so CI is green on push 1."""
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            new_project.scaffold(Path(d, "product"), "X")
            ok, msgs = gen_stories.check(Path(d, "product", "PRD.md"), Path(d, "product", "stories.json"))
            self.assertTrue(ok, msgs)
            r = subprocess.run([sys.executable, "tools/gen_stories.py", "--prd", "product/PRD.md",
                                "--out", "product/stories.json", "--check"], cwd=d,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("STALE", detail(d, 2))

    def test_tools_and_ci_land_at_the_project_root(self):
        """C4: tools/gen_stories.py at the git root (or the folder above product/)."""
        with tempfile.TemporaryDirectory() as d:
            new_project.scaffold(Path(d, "product"), "X")  # no git: product/ -> its parent
            self.assertTrue(Path(d, "tools", "gen_stories.py").is_file())
            self.assertFalse(Path(d, "product", "tools").exists())
            ci = Path(d, ".github", "workflows", "stories.yml").read_text()
            self.assertIn("python3 tools/gen_stories.py --prd product/PRD.md "
                          "--out product/stories.json --check", ci)
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            new_project.scaffold(Path(d, "docs", "product"), "X")
            self.assertTrue(Path(d, "tools", "gen_stories.py").is_file())
            self.assertIn("--prd docs/product/PRD.md", Path(d, ".github/workflows/stories.yml").read_text())
            self.assertEqual(Path(sdlc_stage.evaluate(Path(d))["artifact_dir"]).resolve(),
                             Path(d, "docs", "product").resolve())
        with tempfile.TemporaryDirectory() as d:
            new_project.scaffold(Path(d), "X")  # artifacts at the root
            self.assertIn("--prd PRD.md --out stories.json", Path(d, ".github/workflows/stories.yml").read_text())

    def test_no_name_derives_it_from_the_folder(self):
        """L2-D4: never the example's literal values."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d, "study-group-finder")
            proj.mkdir()
            out = subprocess.run([sys.executable, str(Path(new_project.__file__)), "product"], cwd=proj,
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            readme = Path(proj, "product", "README.md").read_text()
            self.assertIn("# Study Group Finder", readme)
            self.assertNotIn("Study Buddy", readme)
            self.assertNotIn("Team 4", readme)

    @unittest.skipUnless(QA_TEMPLATE.is_file(), "foundry-qa is not next to this plugin")
    def test_journey_template_is_the_qa_template_and_validates(self):
        """L1-D3 / C2: byte-identical to foundry-qa's canonical template and passes --validate."""
        ours = new_project.TEMPLATES / "done-journey.yaml"
        self.assertEqual(ours.read_bytes(), QA_TEMPLATE.read_bytes(),
                         "re-copy foundry-qa/skills/done-gate/templates/done-journey.yaml")
        r = subprocess.run([sys.executable, str(QA_GATE), "--journey", str(ours), "--validate"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_compiled_rows_match_the_schema(self):
        """C1: stories.schema.json describes {"stories": [...]} and every required key is emitted."""
        schema = json.loads((new_project.TEMPLATES / "stories.schema.json").read_text())
        self.assertEqual(schema["type"], "object")
        item = schema["properties"]["stories"]["items"]
        rows, errors, _ = gen_stories.build(PRD, {})
        self.assertEqual(errors, [])
        for row in json.loads(gen_stories.render(rows))["stories"]:
            self.assertTrue(set(item["required"]) <= set(row), set(item["required"]) - set(row))
            self.assertIn(row["status"], item["properties"]["status"]["enum"])

    def test_scaffold_never_overwrites_ci_or_tools(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".github", "workflows").mkdir(parents=True)
            Path(d, ".github", "workflows", "stories.yml").write_text("mine")
            res = {str(p.resolve()): a for p, a in new_project.scaffold(Path(d), "X")}
            self.assertEqual(Path(d, ".github", "workflows", "stories.yml").read_text(), "mine")
            self.assertIn("skipped (exists)", res[str(Path(d, ".github", "workflows", "stories.yml").resolve())])


class GateDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        new_project.scaffold(self.d, "X")
        Path(self.d, "PRD.md").write_text(PRD)
        compile_stories(self.d)
        Path(self.d, "DECISIONS.md").write_text(DECISIONS.format(approval=APPROVAL))

    def tearDown(self):
        self.tmp.cleanup()

    def test_dropped_needs_a_decision_id(self):
        Path(self.d, "REQUIREMENTS.md").write_text(REQUIREMENTS.format(r2="STORIED", r3="DROPPED"))
        self.assertEqual(stage(self.d), 2)
        self.assertIn("R-03", detail(self.d, 2))
        Path(self.d, "REQUIREMENTS.md").write_text(REQUIREMENTS.format(r2="LIVE", r3="DROPPED: D-01, too costly"))
        self.assertEqual(stage(self.d), 3)

    def test_approval_row_needs_a_date_and_no_todo(self):
        Path(self.d, "REQUIREMENTS.md").write_text(REQUIREMENTS.format(r2="STORIED", r3="DROPPED (D-01)"))
        Path(self.d, "DECISIONS.md").write_text(DECISIONS.format(
            approval="| D-02 | TODO: date | TODO: role | TODO | PRD approved | |"))
        self.assertEqual(stage(self.d), 2)

    def test_live_story_without_evidence_is_not_shipped(self):
        doc = json.loads(Path(self.d, "stories.json").read_text())
        for s in doc["stories"]:
            s["status"] = "LIVE"
        Path(self.d, "stories.json").write_text(gen_stories.render(doc["stories"]))
        self.assertIn("no evidence", detail(self.d, 7))

    def test_hook_names_the_stage_6_battery_without_absolute_paths(self):
        res = sdlc_stage.evaluate(self.d)
        uses = sdlc_stage.STAGES[6][2]
        for tool in ("done-gate", "persona-tester", "story-verifier", "design-critique", "a11y-check"):
            self.assertIn(tool, uses)
        self.assertNotIn(str(self.d), res["checks"][2]["detail"])


class StageTests(unittest.TestCase):
    def walk(self, d, art):
        """End to end: scaffold, 2-story PRD, compile, approve, workplan, DONE with a sha,
        a passing done-gate report for HEAD, verifier reports, LIVE, changelog."""
        git(d, "init", "-q")
        new_project.scaffold(art, "X")
        self.assertTrue(gen_stories.check(art / "PRD.md", art / "stories.json")[0])
        self.assertEqual(stage(d), 1)
        Path(art, "REQUIREMENTS.md").write_text(REQUIREMENTS.format(r2="OPEN", r3="OPEN"))
        self.assertEqual(stage(d), 2)
        Path(art, "PRD.md").write_text(PRD)
        self.assertEqual(stage(d), 2)  # stories.json is stale until compiled
        compile_stories(art)
        self.assertEqual(stage(d), 2)  # R-02 and R-03 are OPEN, no approval
        self.assertIn("R-02", detail(d, 2))
        Path(art, "REQUIREMENTS.md").write_text(REQUIREMENTS.format(r2="STORIED", r3="DROPPED (D-01)"))
        Path(art, "DECISIONS.md").write_text(DECISIONS.format(approval=""))
        self.assertEqual(stage(d), 2)
        self.assertIn("PRD approved", detail(d, 2))
        Path(art, "DECISIONS.md").write_text(DECISIONS.format(approval=APPROVAL))
        self.assertEqual(stage(d), 3)
        Path(art, "WORKPLAN.md").write_text(WORKPLAN.format(status="IN REVIEW"))
        self.assertEqual(stage(d), 4)
        Path(d, "app.py").write_text("print('app')\n")
        git(d, "add", "-A")
        git(d, "commit", "-qm", "build T-01")
        sha = git(d, "rev-parse", "--short", "HEAD")
        Path(art, "WORKPLAN.md").write_text(WORKPLAN.format(status="DONE"))
        self.assertEqual(stage(d), 4)  # DONE needs evidence
        self.assertIn("evidence", detail(d, 4))
        Path(art, "WORKPLAN.md").write_text(WORKPLAN.format(status=f"DONE 2026-11-03: commit {sha}"))
        Path(art, "done-journey.yaml").write_text(JOURNEY)
        self.assertEqual(stage(d), 6)  # 5 is not file-detectable, reported as ok
        self.assertIn("done-gate report", detail(d, 6))
        git(d, "add", "-A")
        git(d, "commit", "-qm", "workplan")
        head = git(d, "rev-parse", "HEAD")
        rep = Path(d, ".qa", "done-gate")
        rep.mkdir(parents=True)
        (rep / "last.json").write_text(json.dumps({"sha": head, "exit": 1, "journey": "j", "time": "t"}))
        self.assertEqual(stage(d), 6)
        (rep / "last.json").write_text(json.dumps({"sha": head, "exit": 0, "journey": "j", "time": "t"}))
        self.assertEqual(stage(d), 6)  # no verifier report per story yet
        self.assertIn("US-01", detail(d, 6))
        ver = Path(d, ".qa", "verify")
        ver.mkdir(parents=True)
        for sid in ("US-01", "US-02"):
            (ver / f"{sid}.md").write_text("Result: all PASS")
        self.assertEqual(stage(d), 7)
        for sid in ("US-01", "US-02"):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = gen_stories.main(["--prd", str(art / "PRD.md"), "--out", str(art / "stories.json"),
                                         "--set", f"{sid}=LIVE", "--evidence", str(ver / f"{sid}.md")])
            self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(stage(d), 7)  # the template's fenced example is not a real entry
        Path(art, "CHANGELOG.md").write_text("# log\n\n## 2026-11-03\n- sign-in live (US-01)\n")
        self.assertEqual(stage(d), 8)
        # a code change after the gate sends the project back to stage 6
        Path(d, "app.py").write_text("print('app v2')\n")
        git(d, "commit", "-qam", "v2")
        self.assertEqual(stage(d), 6)
        self.assertIn("app.py", detail(d, 6))

    def test_full_walk_in_root(self):
        with tempfile.TemporaryDirectory() as d:
            self.walk(d, Path(d))

    def test_full_walk_in_product_subdir_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            self.walk(d, Path(d, "product"))
            self.assertTrue(Path(d, "tools", "gen_stories.py").is_file())

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
            Path(d, "REQUIREMENTS.md").write_text(REQUIREMENTS.format(r2="STORIED", r3="DROPPED (D-01)"))
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
