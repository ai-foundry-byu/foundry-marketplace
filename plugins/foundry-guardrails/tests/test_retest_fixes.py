"""Regression tests for the 2026-10-28 retest defects (R1b-D1, R2-D1..D5, R1b-D8, R1a-D7)."""
import hashlib
import json
import os
import subprocess
import unittest

from helpers import HookCase, git, git_repo

import secret_guard as sg

W = "worktree_guard.py"
S = "secret_guard.py"
SW = "stale_write_guard.py"
V = "verify_before_done.py"


# ---------------------------------------------------------------------------
# R1b-D1: worktree-guard protects the main checkout from Agent-tool lane subagents
# ---------------------------------------------------------------------------

class WorktreeGuardSubagentLanes(HookCase):
    def setUp(self):
        super().setUp()
        self.main = git_repo(os.path.join(self.tmp, "app"), {"src/app.py": "x = 1\n"})
        self.lane = os.path.realpath(os.path.join(self.tmp, "app-lanes", "T-03"))
        git(self.main, "worktree", "add", "-q", "-b", "lane/T-03-x", self.lane)
        self.cc_wt = os.path.join(self.main, ".claude", "worktrees", "agent-abc")
        git(self.main, "worktree", "add", "-q", "-b", "worktree-agent-abc", self.cc_wt)
        self.cc_wt = os.path.realpath(self.cc_wt)

    def registry(self, data):
        with open(os.path.join(self.main, ".git", "foundry-lanes.json"), "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def active(self, **extra):
        reg = {"active": True, "lanes": [{"id": "T-03", "tasks": ["T-03"], "branch": "lane/T-03-x",
                                          "worktree": self.lane}]}
        reg.update(extra)
        self.registry(reg)

    def edit(self, target, cwd=None, agent=True, tool="Edit"):
        ev = self.tool(tool, {"file_path": target}, cwd=cwd or self.main)
        if agent:
            ev["agent_id"] = "a1b2"
            ev["agent_type"] = "general-purpose"
        return self.run_hook(W, ev)

    def test_subagent_edit_into_main_denied_while_lanes_active(self):
        self.active()
        res = self.edit(os.path.join(self.main, "src/app.py"))
        self.assertDenied(res, 'isolation: "worktree"')
        self.assertDenied(self.edit("src/app.py"))  # relative path from the main checkout
        self.assertDenied(self.edit(os.path.join(self.main, "new.py"), tool="Write"))

    def test_subagent_edit_inside_lane_or_cc_worktree_allowed(self):
        self.active()
        self.assertAllowed(self.edit(os.path.join(self.lane, "src/app.py")))
        self.assertAllowed(self.edit(os.path.join(self.cc_wt, "src/app.py")))
        self.assertAllowed(self.edit("/tmp/scratch.py"))

    def test_relative_registry_worktree_resolves_from_main(self):
        self.active(lanes=[{"id": "T-03", "worktree": "../app-lanes/T-03"}])
        self.assertAllowed(self.edit(os.path.join(self.lane, "src/app.py")))
        self.assertDenied(self.edit(os.path.join(self.main, "src/app.py")))

    def test_parent_session_unaffected(self):
        self.active()
        self.assertAllowed(self.edit(os.path.join(self.main, "src/app.py"), agent=False))

    def test_no_or_inactive_or_broken_registry_unaffected(self):
        target = os.path.join(self.main, "src/app.py")
        self.assertAllowed(self.edit(target))  # no registry
        self.active(active=False)
        self.assertAllowed(self.edit(target))
        self.registry({"active": True, "lanes": []})
        self.assertAllowed(self.edit(target))
        self.registry("{not json")
        self.assertAllowed(self.edit(target))

    def test_isolated_subagent_keeps_worktree_behavior(self):
        # W1: an isolation:"worktree" subagent runs with cwd = its worktree
        res = self.edit(os.path.join(self.main, "src/app.py"), cwd=self.cc_wt)
        self.assertDenied(res, os.path.join(self.cc_wt, "src", "app.py"))
        self.assertAllowed(self.edit(os.path.join(self.cc_wt, "src/app.py"), cwd=self.cc_wt))

    def test_warn_and_off_switches(self):
        self.active()
        target = os.path.join(self.main, "src/app.py")
        ev = self.tool("Edit", {"file_path": target}, cwd=self.main)
        ev["agent_id"] = "a1"
        self.assertWarned(self.run_hook(W, ev, env={"FOUNDRY_WORKTREE_GUARD_WARN": "1"}))
        self.assertAllowed(self.run_hook(W, ev, env={"FOUNDRY_WORKTREE_GUARD": "0"}))


# ---------------------------------------------------------------------------
# R2-D1: secret-guard follows simple indirection
# ---------------------------------------------------------------------------

class SecretIndirection(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        with open(os.path.join(self.proj, ".env"), "w") as fh:
            fh.write("API_KEY=FAKE-NOT-REAL\n")
        with open(os.path.join(self.proj, "app.py"), "w") as fh:
            fh.write("print(1)\n")

    def deny(self, cmd):
        self.assertIsNotNone(sg.evaluate_bash(cmd, self.proj), f"expected deny: {cmd}")

    def allow(self, cmd):
        self.assertIsNone(sg.evaluate_bash(cmd, self.proj), f"expected allow: {cmd}")

    def test_variable_and_loop_reads_denied(self):
        for cmd in ['f=.env; cat "$f"', "f=.env && cat $f", 'F=".env"; head -3 "${F}"',
                    'for f in .env*; do cat "$f"; done', "for f in .env .env.local; do cat $f; done",
                    'for f in $(ls -a | grep env); do cat "$f"; done',
                    'ls -a | grep env | while read f; do cat "$f"; done',
                    "if true; then cat .env; fi", "cat $(ls -a | grep env)", "cat `ls -a | grep env`"]:
            self.deny(cmd)

    def test_copy_then_read_denied(self):
        for cmd in ["cp .env /tmp/x.txt && cat /tmp/x.txt", "cp .env x; head x",
                    "mv .env backup.txt && cat backup.txt", "cp .env /tmp/ && cat /tmp/.env"]:
            self.deny(cmd)

    def test_find_exec_and_xargs_denied(self):
        for cmd in ["find . -name '.env*' -exec cat {} \\;", "find . -name .env -exec cat {} +",
                    "find . -iname '*.env' -execdir head {} \\;", "find . -type f -exec cat {} \\;",
                    "find . -name .env | xargs cat", "ls -a | grep env | xargs cat",
                    "echo .env | xargs -I{} cat {}"]:
            self.deny(cmd)

    def test_harmless_indirection_allowed(self):
        for cmd in ['f=app.py; cat "$f"', 'for f in *.py; do cat "$f"; done',
                    "find . -name '*.py' -exec cat {} \\;", "find . -name .env",
                    "find . -name '*.py' | xargs cat", "cp .env.example .env && cat .env.example",
                    'cat "$CONFIG_PATH"', "ls -a | grep env", "git ls-files | xargs wc -l",
                    'for f in .env*; do test -f "$f" && echo "$f present"; done',
                    'for f in .env*; do cut -d= -f1 "$f"; done']:
            self.allow(cmd)


# ---------------------------------------------------------------------------
# R2-D2 / R1b-D8: names-only listings filtered with grep, and an accurate env|grep message
# ---------------------------------------------------------------------------

class SecretNamesFilter(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        with open(os.path.join(self.proj, ".env"), "w") as fh:
            fh.write("AWS_KEY=FAKE\nDATABASE_URL=postgres://x\n")

    def test_names_only_then_grep_allowed(self):
        for cmd in ["env | cut -d= -f1 | grep -i '^AWS_'", "cut -d= -f1 .env | grep -i aws",
                    "env | cut -d= -f1 | grep AWS | sort", "printenv | cut -d= -f1 | grep -E 'AWS|GCP'"]:
            self.assertIsNone(sg.evaluate_bash(cmd, self.proj), cmd)

    def test_quiet_env_grep_and_process_substitution_allowed(self):
        for cmd in ["env | grep -q '^AWS_'", "printenv | grep -c TOKEN",
                    "diff <(cut -d= -f1 .env) <(cut -d= -f1 .env.example)"]:
            self.assertIsNone(sg.evaluate_bash(cmd, self.proj), cmd)
        self.assertIsNotNone(sg.evaluate_bash("diff <(cat .env) /dev/null", self.proj))

    def test_grep_that_reads_more_than_stdin_still_denied(self):
        for cmd in ["cut -d= -f1 .env | grep -f patterns .env", "env | cut -d= -f1 | grep AWS .env"]:
            self.assertIsNotNone(sg.evaluate_bash(cmd, self.proj), cmd)

    def test_env_grep_denied_with_accurate_message(self):
        why = sg.evaluate_bash("env | grep -i SCHOOL", self.proj)
        self.assertIsNotNone(why)
        self.assertNotIn("dumps every environment variable", why)
        self.assertIn("NAME=value", why)
        self.assertIn("SCHOOL", why)
        res = self.run_hook(S, self.bash("env | grep -i SCHOOL", cwd=self.proj))
        self.assertDenied(res, "env | cut -d= -f1 | grep -i SCHOOL")


# ---------------------------------------------------------------------------
# R2-D3: safe-forms advice fits the command family; no "! output stays private" text
# ---------------------------------------------------------------------------

class SecretAdvice(HookCase):
    def reason(self, event):
        code, out, _ = self.run_hook(S, event)
        self.assertEqual(code, 0)
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_credential_cli_advice(self):
        for cmd in ["gh auth token", "security find-generic-password -s foo -w", "op read op://a/b/c",
                    "bw get password foo", "gcloud auth print-access-token",
                    "aws configure get aws_secret_access_key"]:
            r = self.reason(self.bash(cmd))
            self.assertNotIn("cut -d= -f1 .env", r, cmd)
            self.assertIn("auth status", r, cmd)
            self.assertIn("! ", r, cmd)
            self.assertIn("into the conversation", r, cmd)

    def test_private_key_advice(self):
        r = self.reason(self.bash("cat keys/id_rsa"))
        self.assertIn("ssh-keygen -l -f", r)
        self.assertNotIn("cut -d= -f1 .env", r)

    def test_env_dump_advice(self):
        r = self.reason(self.bash("env"))
        self.assertIn("env | cut -d= -f1", r)
        self.assertNotIn("cut -d= -f1 .env", r)
        r = self.reason(self.bash("echo $API_KEY"))
        self.assertIn("test -n", r)

    def test_dotenv_advice(self):
        r = self.reason(self.tool("Read", {"file_path": "/p/.env"}))
        self.assertIn("cut -d= -f1 .env", r)
        self.assertIn("source .env", r)

    def test_no_text_says_bang_output_is_private(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("hooks/scripts/secret_guard.py", "skills/guardrails-help/SKILL.md", "README.md"):
            with open(os.path.join(here, rel), encoding="utf-8") as fh:
                text = fh.read().lower()
            for bad in ("stays on your side", "stays private", "not sent to the model", "only you see"):
                self.assertNotIn(bad, text, rel)


# ---------------------------------------------------------------------------
# R2-D4: stale-write warn-only text does not say "blocked"
# ---------------------------------------------------------------------------

class StaleWriteWarnText(HookCase):
    def test_warn_mode_text(self):
        repo = git_repo(os.path.join(self.tmp, "r"), {"README.md": "a\n"})
        with open(os.path.join(repo, "README.md"), "a") as fh:
            fh.write("foreign line\n")
        ev = self.tool("Write", {"file_path": os.path.join(repo, "README.md"), "content": "hello\n"},
                       cwd=repo)
        res = self.run_hook(SW, ev, env={"FOUNDRY_STALE_WRITE_ENFORCE": "0"})
        self.assertWarned(res)
        text = res[1]["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("blocked", text.lower())
        self.assertIn("overwrit", text)
        self.assertDenied(self.run_hook(SW, ev), "stays blocked")


# ---------------------------------------------------------------------------
# R2-D5 and R1a-D7: verify-before-done message and scaffold false positive
# ---------------------------------------------------------------------------

def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class VerifyMessages(HookCase):
    def test_no_doubled_parentheses(self):
        proj = os.path.join(self.tmp, "nogit")
        os.makedirs(proj)
        env = {"CLAUDE_PROJECT_DIR": proj}
        self.run_hook(V, self.bash("python3 -c \"p='calc.py'; open(p,'w').write('x')\"", cwd=proj), env=env)
        code, out, _ = self.run_hook(V, self.stop(cwd=proj), env=env)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("(a file written by a shell command)", text)
        self.assertNotIn("((", text)


class VerifyScaffold(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.realpath(os.path.join(self.tmp, "newapp"))
        os.makedirs(self.proj)
        self.env = dict(self.env, CLAUDE_PROJECT_DIR=self.proj)

    def g(self, *args):
        git(self.proj, *args)

    def scaffold(self, manifest=True):
        os.makedirs(os.path.join(self.proj, "tools"), exist_ok=True)
        gen = os.path.join(self.proj, "tools", "gen_stories.py")
        with open(gen, "w") as fh:
            fh.write("print('gen')\n")
        with open(os.path.join(self.proj, "PRD.md"), "w") as fh:
            fh.write("# PRD\n")
        if manifest:
            os.makedirs(os.path.join(self.proj, ".foundry"), exist_ok=True)
            with open(os.path.join(self.proj, ".foundry", "generated.json"), "w") as fh:
                json.dump({"version": 1, "generator": "foundry-sdlc/new-project",
                           "files": [{"path": "tools/gen_stories.py", "sha256": _sha256(gen)}]}, fh)
        return gen

    def stop_text(self):
        code, out, _ = self.run_hook(V, self.stop(cwd=self.proj))
        self.assertEqual(code, 0)
        return out["hookSpecificOutput"]["additionalContext"] if out else None

    def test_git_init_after_first_hook_then_scaffold_no_block(self):
        # R1a-S0: the first hook call ran before git init, then the scaffolder wrote
        # tools/gen_stories.py and an inline heredoc edited README.md
        self.run_hook(V, self.bash("ls -A && git init", cwd=self.proj))
        self.g("init", "-q", "-b", "main")
        self.run_hook(V, self.bash("python3 /x/new_project.py .", cwd=self.proj))
        self.scaffold()
        self.run_hook(V, self.bash("python3 - <<'EOF'\nopen('README.md','w').write('x')\nEOF",
                                   cwd=self.proj))
        with open(os.path.join(self.proj, "README.md"), "w") as fh:
            fh.write("x\n")
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "scaffold")
        self.assertIsNone(self.stop_text())

    def test_generated_file_edited_after_generation_counts(self):
        self.g("init", "-q", "-b", "main")
        self.run_hook(V, self.bash("ls", cwd=self.proj))
        gen = self.scaffold()
        with open(gen, "a") as fh:
            fh.write("print('changed')\n")
        text = self.stop_text()
        self.assertIsNotNone(text)
        self.assertIn("gen_stories.py", text)

    def test_without_manifest_the_generated_file_counts(self):
        self.g("init", "-q", "-b", "main")
        self.run_hook(V, self.bash("ls", cwd=self.proj))
        self.scaffold(manifest=False)
        self.assertIn("gen_stories.py", self.stop_text() or "")

    def test_other_code_still_counts_with_manifest(self):
        self.g("init", "-q", "-b", "main")
        self.run_hook(V, self.bash("ls", cwd=self.proj))
        self.scaffold()
        with open(os.path.join(self.proj, "app.py"), "w") as fh:
            fh.write("x = 1\n")
        text = self.stop_text() or ""
        self.assertIn("app.py", text)
        self.assertNotIn("gen_stories.py", text)

    def test_malformed_manifest_fails_open_to_counting(self):
        self.g("init", "-q", "-b", "main")
        self.run_hook(V, self.bash("ls", cwd=self.proj))
        self.scaffold(manifest=False)
        os.makedirs(os.path.join(self.proj, ".foundry"))
        with open(os.path.join(self.proj, ".foundry", "generated.json"), "w") as fh:
            fh.write("[1, 2")
        self.assertIn("gen_stories.py", self.stop_text() or "")

    def test_inline_write_of_a_doc_outside_git_is_not_code(self):
        self.run_hook(V, self.bash("python3 - <<'EOF'\ns=open('README.md').read()\n"
                                   "open('README.md','w').write(s)\nEOF", cwd=self.proj))
        self.assertIsNone(self.stop_text())
        self.run_hook(V, self.bash("python3 -c \"open('calc.py','w').write('x')\"", cwd=self.proj))
        self.assertIn("calc.py", self.stop_text() or "")


if __name__ == "__main__":
    unittest.main()
