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

    def verify(self, d, sid="US-01", sha=None):
        """A story-verifier report. sha=None writes no "Commit:" line (an old-format report)."""
        v = Path(d, ".qa", "verify")
        v.mkdir(parents=True, exist_ok=True)
        head = f"Commit: {sha}\n" if sha else ""
        (v / f"{sid}.md").write_text(f"{head}Story {sid}: demo\n\nResult: 3 PASS. LIVE-eligible.\n")
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
            report = self.verify(d, sha=head[:7])
            # an artifact-only commit after the gate and the verifier still counts as the same build
            Path(d, "CHANGELOG.md").write_text("# log\n")
            git(d, "add", "-A")
            git(d, "commit", "-qm", "docs")
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", report)
            self.assertEqual(code, 0, msg)
            row = g.load_stories(out)[0]
            self.assertEqual(row["status"], "LIVE")
            self.assertIn(f"commit:{git(d, 'rev-parse', 'HEAD')}", row["evidence"])
            self.assertTrue(any(e.endswith("US-01.md") for e in row["evidence"]))
            self.assertTrue(g.check(prd, out)[0])

    def test_live_refused_with_untracked_code(self):
        """R1a-D3 / B2: an untracked app file is not in the commit, so the story is not LIVE."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            Path(d, "app").mkdir()
            Path(d, "app", "server.py").write_text("print('new')\n")
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d, sha=head))
            self.assertEqual(code, 1)
            self.assertIn("app/server.py", msg)
            self.assertIn("untracked", msg)
            self.assertEqual(g.load_stories(out)[0]["status"], "NOT_BUILT")

    def test_untracked_qa_files_and_artifacts_do_not_block_live(self):
        """.qa/ anywhere (product/.qa/run/server.pid) and artifact files are not the build."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            Path(d, "product", ".qa", "run").mkdir(parents=True)
            Path(d, "product", ".qa", "run", "server.pid").write_text("123\n")
            Path(d, "DECISIONS.md").write_text("# new, not yet committed\n")
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d, sha=head))
            self.assertEqual(code, 0, msg)

    def test_dirty_tree_lists_tracked_and_untracked_code(self):
        with tempfile.TemporaryDirectory() as d:
            self.project(d)
            Path(d, "app.py").write_text("print('changed')\n")
            Path(d, "new file.py").write_text("x = 1\n")
            dirty = g.dirty_tree(Path(d).resolve(), Path(d).resolve())
            self.assertIn("app.py", dirty)
            self.assertIn("new file.py (untracked)", dirty)

    def test_live_refused_when_verifier_report_names_no_commit(self):
        """B2 / R1a-D4: the verifier report must say which commit it verified."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            self.gate(d, git(d, "rev-parse", "HEAD"))
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", self.verify(d))
            self.assertEqual(code, 1)
            self.assertIn("Commit:", msg)

    def test_live_refused_when_verified_on_older_code(self):
        """R1a-D4: verified at commit A, code changed in B, gate rerun on B: still refused."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            old = git(d, "rev-parse", "HEAD")
            report = self.verify(d, sha=old)
            Path(d, "app.py").write_text("print('v2')\n")
            git(d, "commit", "-qam", "v2")
            self.gate(d, git(d, "rev-parse", "HEAD"))
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                                      "--evidence", report)
            self.assertEqual(code, 1)
            self.assertIn(old[:7], msg)
            self.assertIn("app.py", msg)

    def test_live_refused_without_a_verifier_report_for_that_story(self):
        """Evidence for another story is not evidence for this one."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-02=LIVE",
                                      "--evidence", self.verify(d, "US-01", sha=head))
            self.assertEqual(code, 1)
            self.assertIn("US-02", msg)

    def test_live_finds_the_default_verifier_report(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            self.verify(d, "US-02", sha=head)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-02=LIVE",
                                      "--evidence", "https://example.com/build/42")
            self.assertEqual(code, 0, msg)
            self.assertIn(".qa/verify/US-02.md", g.load_stories(out)[1]["evidence"])

    def test_partial_needs_no_gate(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            code, msg = self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-02=PARTIAL")
            self.assertEqual(code, 0, msg)
            self.assertEqual(g.load_stories(out)[1]["status"], "PARTIAL")
            self.assertEqual(self.run_main("--prd", str(prd), "--out", str(out),
                                           "--set", "US-02=DONE")[0], 2)

    # -- review D (2026-10-28): ways a change or a stale report slipped past --set LIVE --------

    def live(self, d, prd, out):
        return self.run_main("--prd", str(prd), "--out", str(out), "--set", "US-01=LIVE",
                             "--evidence", str(Path(d, ".qa", "verify", "US-01.md")))

    def test_live_refused_when_gate_report_sha_is_not_a_commit_id(self):
        """"HEAD" or "main" matched every future HEAD, "a" matched 1 in 16, and "--output=x"
        was an option git diff obeyed (it wrote x and printed nothing, so the gate passed)."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.verify(d, sha=head)
            for bad in ("HEAD", "master", head[:1], "--output=" + str(Path(d, "pwned")), head + "zz"):
                self.gate(d, bad)
                code, msg = self.live(d, prd, out)
                self.assertEqual(code, 1, bad)
                self.assertIn("not a commit id", msg, bad)
            self.assertFalse(Path(d, "pwned").exists())
            self.gate(d, head.upper()[:12])  # a valid id in capitals is still that commit
            self.assertEqual(self.live(d, prd, out)[0], 0)

    def test_live_refused_when_code_is_renamed_away(self):
        """A staged rename lists only its destination; its source left the build unseen."""
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            self.verify(d, sha=head)
            git(d, "mv", "app.py", "README.md")
            code, msg = self.live(d, prd, out)
            self.assertEqual(code, 1)
            self.assertIn("app.py", msg)

    def test_live_refused_when_assume_unchanged_hides_an_edit(self):
        with tempfile.TemporaryDirectory() as d:
            prd, out = self.project(d)
            head = git(d, "rev-parse", "HEAD")
            self.gate(d, head)
            self.verify(d, sha=head)
            git(d, "update-index", "--assume-unchanged", "app.py")
            self.assertEqual(self.live(d, prd, out)[0], 0)  # flagged but unchanged: fine
            git(d, "checkout", "--", "stories.json")  # back to NOT_BUILT
            Path(d, "app.py").write_text("print('changed after the gate')\n")
            code, msg = self.live(d, prd, out)
            self.assertEqual(code, 1)
            self.assertIn("app.py (assume-unchanged", msg)


class ToolVersionTests(unittest.TestCase):
    """Wave D (b): a project keeps its own copy at tools/gen_stories.py, so fixes reach it only
    through a version stamp and --refresh-tools."""

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = g.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def test_version_is_stamped_and_printed(self):
        self.assertRegex(g.__version__, r"^\d+\.\d+\.\d+$")
        code, out = self.run_main("--version")  # works without a PRD.md
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), f"gen_stories.py {g.__version__}")
        self.assertEqual(g.version_of(Path(g.__file__).read_text()), g.__version__)
        self.assertIsNone(g.version_of("print('an old copy')\n"))

    def test_refresh_replaces_an_old_copy_and_summarizes_the_diff(self):
        with tempfile.TemporaryDirectory() as d:
            tool = Path(d, "tools", "gen_stories.py")
            tool.parent.mkdir()
            tool.write_text("#!/usr/bin/env python3\nprint('old')\n")
            code, out = self.run_main("--refresh-tools", d)
            self.assertEqual(code, 0, out)
            self.assertEqual(tool.read_bytes(), Path(g.__file__).read_bytes())
            line = out.strip()
            self.assertEqual(len(line.splitlines()), 1, line)
            self.assertIn("refreshed tools/gen_stories.py", line)
            self.assertIn(f"unversioned -> {g.__version__}", line)
            self.assertRegex(line, r"\+\d+ -1 lines")
            # the guardrails manifest now vouches for the refreshed bytes
            man = json.loads(Path(d, ".foundry", "generated.json").read_text())
            entry = [f for f in man["files"] if f["path"] == "tools/gen_stories.py"]
            self.assertEqual(entry[0]["sha256"], g.sha256_file(tool))
            # a second run has nothing to do
            code, out = self.run_main("--refresh-tools", d)
            self.assertEqual(code, 0)
            self.assertIn(f"tools/gen_stories.py is current ({g.__version__})", out)

    def test_refresh_keeps_a_newer_copy_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_main("--refresh-tools", d)
            self.assertEqual(code, 0)
            self.assertIn("no tools/gen_stories.py", out)
            self.assertFalse(Path(d, "tools").exists())
            tool = Path(d, "tools", "gen_stories.py")
            tool.parent.mkdir()
            tool.write_text('__version__ = "999.0.0"\n')
            code, out = self.run_main("--refresh-tools", d)
            self.assertEqual(code, 0)
            self.assertIn("newer", out)
            self.assertEqual(tool.read_text(), '__version__ = "999.0.0"\n')

    def test_manifest_merge_keeps_other_entries(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".foundry").mkdir()
            Path(d, ".foundry", "generated.json").write_text(json.dumps(
                {"version": 1, "generator": "other", "files": [{"path": "x.py", "sha256": "0" * 64}]}))
            Path(d, "a.py").write_text("a = 1\n")
            g.record_generated(Path(d), [Path(d, "a.py"), Path("/elsewhere/b.py")], "foundry-sdlc/test")
            man = json.loads(Path(d, ".foundry", "generated.json").read_text())
            self.assertEqual(man["version"], 1)
            self.assertEqual(sorted(f["path"] for f in man["files"]), ["a.py", "x.py"])

    def test_scaffold_tool_files_are_not_the_build(self):
        """Refreshing tools/gen_stories.py after the done gate must not make the build stale."""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(g.code_files(Path(d), Path(d), ["tools/gen_stories.py",
                                                             ".foundry/generated.json",
                                                             ".github/workflows/stories.yml",
                                                             "tools/other.py"]),
                             ["tools/other.py"])


if __name__ == "__main__":
    unittest.main()
