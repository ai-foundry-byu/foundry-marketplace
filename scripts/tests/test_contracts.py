"""Cross-plugin contract tests: the files one plugin writes are the files the next one reads.

Every check drives the scripts exactly as the plugins ship them (as subprocesses,
from a scratch project), so a format change in one plugin that the other does not
follow fails here even when each plugin's own tests stay green.

  foundry-sdlc new-project  -> PRD.md, stories.json, done-journey.yaml, tools/gen_stories.py
  foundry-qa done_gate.py   -> reads done-journey.yaml, writes .qa/done-gate/last.json
  foundry-qa persona_run.py -> reads stories.json
  foundry-sdlc sdlc_stage.py / gen_stories.py --set -> read .qa/done-gate/last.json
  foundry-evals evalkit.py  -> one results root per suite, wherever it is run from

Run: python3 -m unittest discover -s scripts/tests -v
Needs git on PATH. No browser, no network.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGINS = REPO / "plugins"
SDLC = PLUGINS / "foundry-sdlc"
QA = PLUGINS / "foundry-qa"
EVALS = PLUGINS / "foundry-evals"

NEW_PROJECT = SDLC / "skills" / "new-project" / "scripts" / "new_project.py"
SDLC_STAGE = SDLC / "scripts" / "sdlc_stage.py"
SDLC_JOURNEY = SDLC / "skills" / "new-project" / "templates" / "done-journey.yaml"
DONE_GATE = QA / "skills" / "done-gate" / "scripts" / "done_gate.py"
QA_JOURNEY = QA / "skills" / "done-gate" / "templates" / "done-journey.yaml"
PERSONA_RUN = QA / "skills" / "persona-run" / "scripts" / "persona_run.py"
PERSONA = QA / "skills" / "persona-run" / "templates" / "personas" / "first-time-mobile-user.md"
EVALKIT = EVALS / "skills" / "new-eval" / "scripts" / "evalkit.py"

HAVE_GIT = shutil.which("git") is not None


def run(args, cwd, env=None):
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
              "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
              "PYTHONDONTWRITEBYTECODE": "1"})
    e.update(env or {})
    return subprocess.run([str(a) for a in args], cwd=str(cwd), capture_output=True, text=True,
                          timeout=120, env=e)


def py(*args, cwd):
    return run([sys.executable, *args], cwd)


def git(*args, cwd):
    r = run(["git", *args], cwd)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout.strip()


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class ScaffoldContracts(unittest.TestCase):
    """A freshly scaffolded project is valid input for every downstream tool."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="foundry-contract-")).resolve()
        self.proj = self.tmp / "demo-app"
        self.proj.mkdir()
        git("init", "-q", cwd=self.proj)
        r = py(NEW_PROJECT, ".", "--name", "Demo App", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit_all(self, msg="scaffold"):
        git("add", "-A", cwd=self.proj)
        git("commit", "-q", "-m", msg, cwd=self.proj)
        return git("rev-parse", "HEAD", cwd=self.proj)

    def stage_check(self, n):
        r = py(SDLC_STAGE, self.proj, "--json", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        return next(c for c in res["checks"] if c["stage"] == n)

    def gate_record(self, code, sha):
        """A last.json record built by done_gate.py's own last_record(), from the scaffolded journey."""
        script = ("import json,sys; sys.path.insert(0, sys.argv[1]); import done_gate as g; "
                  "j = g.load_journey(sys.argv[2]); "
                  "print(json.dumps(g.last_record(int(sys.argv[3]), [j], sys.argv[4] or None, [])))")
        r = py("-c", script, DONE_GATE.parent, self.proj / "done-journey.yaml", code, sha, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def write_last(self, record):
        d = self.proj / ".qa" / "done-gate"
        d.mkdir(parents=True, exist_ok=True)
        (d / "last.json").write_text(json.dumps(record, indent=2))

    # (a) + (b)
    def test_scaffold_then_gen_stories_check_passes(self):
        for f in ("PRD.md", "stories.json", "done-journey.yaml", "tools/gen_stories.py"):
            self.assertTrue((self.proj / f).is_file(), f)
        r = py("tools/gen_stories.py", "--check", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = py("tools/gen_stories.py", "--prd", "PRD.md", "--out", "stories.json", "--check", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_scaffold_into_product_dir_check_passes_with_printed_command(self):
        repo = self.tmp / "existing-repo"
        repo.mkdir()
        git("init", "-q", cwd=repo)
        r = py(NEW_PROJECT, "product", cwd=repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json", r.stdout)
        r = py("tools/gen_stories.py", "--prd", "product/PRD.md", "--out", "product/stories.json", "--check",
               cwd=repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # (c)
    def test_done_gate_validates_scaffolded_journey(self):
        r = py(DONE_GATE, "--journey", "done-journey.yaml", "--validate", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.proj / ".qa").exists(), "--validate must not write a gate report")

    def test_journey_templates_are_identical(self):
        self.assertEqual(SDLC_JOURNEY.read_text(encoding="utf-8"), QA_JOURNEY.read_text(encoding="utf-8"))

    def test_journey_story_ids_exist_in_stories_json(self):
        rec = self.gate_record(0, "")
        ids = {s["id"] for s in json.loads((self.proj / "stories.json").read_text())["stories"]}
        self.assertTrue(rec["stories"], "the template journey should name the story it proves")
        self.assertLessEqual(set(rec["stories"]), ids)

    # (d)
    def test_persona_run_plan_accepts_scaffolded_stories(self):
        base = [PERSONA_RUN, "--persona", PERSONA, "--stories", "stories.json",
                "--base-url", "http://localhost:3000", "--plan"]
        r = py(*base, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("unknown key", r.stderr)
        self.assertNotIn("CONFIG ERROR", r.stderr)
        # A NOT_BUILT story is skipped by default; naming it puts it in the matrix.
        r = py(*base, "--story", "US-01", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("unknown key", r.stderr)
        self.assertRegex(r.stdout, r"US-01\s+phone-390x844")

    # (e)
    def test_sdlc_stage_reads_done_gate_report(self):
        self.assertIn("no commit yet", self.stage_check(6)["detail"])
        head = self.commit_all()
        self.assertIn("no done-gate report", self.stage_check(6)["detail"])
        self.write_last(self.gate_record(0, head))
        detail = self.stage_check(6)["detail"]
        self.assertNotIn("done-gate", detail)
        self.assertNotIn("done gate", detail)
        verify = self.proj / ".qa" / "verify" / "US-01.md"
        verify.parent.mkdir(parents=True)
        verify.write_text("verified\n")
        check = self.stage_check(6)
        self.assertTrue(check["ok"], check["detail"])
        self.assertIn("done gate exit 0 on HEAD", check["detail"])

    def test_sdlc_stage_refuses_failed_and_stale_reports(self):
        head = self.commit_all()
        self.write_last(self.gate_record(1, head))
        self.assertIn("done gate report says exit 1", self.stage_check(6)["detail"])
        self.write_last(self.gate_record(0, head))
        (self.proj / "app.py").write_text("print('changed')\n")
        new_head = self.commit_all("code change after the gate")
        self.assertNotEqual(new_head, head)
        self.assertIn("code changed since: app.py", self.stage_check(6)["detail"])

    def test_sdlc_stage_reads_report_written_by_done_gate_itself(self):
        """A real done_gate.py run that stops at a config error writes last.json; sdlc reads it."""
        head = self.commit_all()
        r = py(DONE_GATE, "--journey", "done-journey.yaml", "--base-url", "TODO", cwd=self.proj)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        written = json.loads((self.proj / ".qa" / "done-gate" / "last.json").read_text())
        self.assertEqual((written["sha"], written["exit"]), (head, 2))
        self.assertEqual(set(self.gate_record(0, head)), set(written), "fake and real records differ in shape")
        self.assertIn("done gate report says exit 2", self.stage_check(6)["detail"])

    def test_gen_stories_set_live_accepts_passing_report(self):
        head = self.commit_all()
        self.write_last(self.gate_record(0, head))
        ev = self.proj / ".qa" / "verify" / "US-01.md"
        ev.parent.mkdir(parents=True)
        ev.write_text("verified\n")
        r = py("tools/gen_stories.py", "--set", "US-01=LIVE", "--evidence", ".qa/verify/US-01.md", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        story = json.loads((self.proj / "stories.json").read_text())["stories"][0]
        self.assertEqual(story["status"], "LIVE")
        self.assertIn(f"commit:{head}", story["evidence"])


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class EvalkitResultsRoot(unittest.TestCase):
    """(f) One suite has one history, whatever the current directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="foundry-evals-")).resolve()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()
        git("init", "-q", cwd=self.proj)
        self.elsewhere = self.tmp / "elsewhere"
        self.elsewhere.mkdir()
        self.suite = self.proj / "evals" / "refund"
        r = py(EVALKIT, "init", self.suite, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def history_root(self, cwd):
        r = py(EVALKIT, "history", self.suite, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = next(x for x in r.stdout.splitlines() if x.startswith("history: "))
        return Path(line[len("history: "):]).resolve(), r.stdout

    def report_dir(self, out):
        line = next(x for x in out.splitlines() if x.startswith("report: "))
        return Path(line[len("report: "):]).resolve().parent

    def test_check_and_run_from_two_cwds_share_one_root(self):
        cwds = (self.suite.parent, self.elsewhere)
        for cwd in cwds:
            r = py(EVALKIT, "check", self.suite, "--no-judge", cwd=cwd)
            self.assertEqual(r.returncode, 0, f"check from {cwd}: {r.stdout}{r.stderr}")
        dirs = []
        for cwd in cwds:
            r = py(EVALKIT, "run", self.suite, "--no-judge", "--quiet", cwd=cwd)
            self.assertIn(r.returncode, (0, 4), r.stdout + r.stderr)
            dirs.append(self.report_dir(r.stdout))
        expected = self.proj / ".evals" / "refund-triage"
        self.assertEqual(dirs, [expected, expected])
        roots = {self.history_root(cwd)[0] for cwd in (*cwds, self.proj, self.tmp)}
        self.assertEqual(roots, {expected})
        self.assertEqual(len(list(expected.glob("*.json"))), 2)
        for cwd in cwds:
            self.assertFalse((cwd / ".evals").exists(), f"evalkit wrote .evals under the cwd {cwd}")


if __name__ == "__main__":
    unittest.main()
