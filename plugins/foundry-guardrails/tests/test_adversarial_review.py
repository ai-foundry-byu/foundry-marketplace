"""Regression tests for the holes found by the 2026-10-28 adversarial review of the D2-D9 fixes.

Each test names the attack it pins down. They drive the hooks the way Claude Code does
(JSON on stdin), in throwaway git repos.
"""
import os
import subprocess
import time
import unittest

from helpers import HookCase, git, git_repo

import _common as c
import destructive_guard as dg

V = "verify_before_done.py"
SG = "secret_guard.py"


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8") as fh:
        fh.write(text)


class VerifyCase(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = git_repo(os.path.join(self.tmp, "proj"),
                             {"calc.py": "def add(a, b):\n    return a - b\n", "README.md": "# r\n"})
        self.env["CLAUDE_PROJECT_DIR"] = self.proj
        self.assertAllowed(self.pre("ls"))  # first hook call: the snapshot

    def pre(self, cmd, session="s1"):
        return self.run_hook(V, self.bash(cmd, cwd=self.proj, session=session))

    def stop(self, session="s1", **kw):
        return self.run_hook(V, HookCase.stop(session=session, cwd=self.proj, **kw))

    def sh(self, cmd):
        subprocess.run(cmd, shell=True, cwd=self.proj, check=True, capture_output=True)

    def bash_edit(self, cmd="sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak"):
        self.assertAllowed(self.pre(cmd))
        self.sh(cmd)

    def assertBlocked(self, result, contains=""):
        _, out, err = result
        self.assertEqual(err, "")
        self.assertIsNotNone(out, "expected Stop feedback")
        self.assertIn(contains, out["hookSpecificOutput"]["additionalContext"])


class DeniedCommandDoesNotCountAsTested(VerifyCase):
    """'pytest && git push' is denied, so nothing in it runs: its pytest must not count."""

    def test_denied_test_and_push_then_token_alone_is_refused(self):
        self.bash_edit()
        self.assertDenied(self.pre("python3 -m pytest -q && git push origin feat"), "irreversible")
        self.assertDenied(self.pre("VERIFY_OK=1 git push origin feat"), "run the tests first")
        self.assertBlocked(self.stop(), "calc.py")


class SameCommandTestsMustGateThePush(VerifyCase):
    """A same-command test counts only as '<test> && VERIFY_OK=1 <push>'."""

    def test_ungated_forms_refused(self):
        for cmd in ["python3 -m pytest -q; VERIFY_OK=1 git push origin feat",
                    "python3 -m pytest -q || VERIFY_OK=1 git push origin feat",
                    "python3 -m pytest -q || true; VERIFY_OK=1 git push origin feat",
                    "python3 -m pytest -q | tail -3 && VERIFY_OK=1 git push origin feat",
                    "npm test & VERIFY_OK=1 git push origin feat",
                    "true || python3 -m pytest; VERIFY_OK=1 git push origin feat",
                    "python3 -m pytest && VERIFY_OK=1 git push origin feat; VERIFY_OK=1 npm publish"]:
            with self.subTest(cmd=cmd):
                self.bash_edit("echo '# x' >> calc.py")
                self.assertDenied(self.pre(cmd), "do not count")

    def test_gated_forms_allowed(self):
        for cmd in ["python3 -m pytest -q && VERIFY_OK=1 git push origin feat",
                    "cd . && npm test && VERIFY_OK=1 git push origin feat",
                    "pytest -q 2>&1 && VERIFY_OK=1 git push && VERIFY_OK=1 npm publish"]:
            with self.subTest(cmd=cmd):
                self.bash_edit("echo '# x' >> calc.py")
                self.assertAllowed(self.pre(cmd))


class WritesAfterTestsInOneCommand(VerifyCase):
    def test_test_then_sed_in_one_command_still_blocks(self):
        self.bash_edit("python3 -m pytest -q 2>/dev/null; sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertBlocked(self.stop(), "calc.py")

    def test_test_then_commit_still_counts_as_tested(self):
        self.bash_edit()
        self.assertAllowed(self.pre("python3 -m pytest -q && git commit -qam fix"))
        git(self.proj, "commit", "-qam", "fix")
        self.assertAllowed(self.stop())


class OtherStopHookContinuations(VerifyCase):
    """ship-stop's continuations make every later Stop 'active'; that is not verify's own block."""

    def test_edit_during_another_hooks_continuation_is_checked(self):
        self.assertAllowed(self.stop())             # nothing changed; ship-stop continued the turn
        self.bash_edit()                            # Claude edits during that continuation
        self.assertBlocked(self.stop(active=True), "calc.py")
        self.assertAllowed(self.stop(active=True))  # this time it was our block: let it through

    def test_cap_still_bounds_it(self):
        blocks = 0
        for _ in range(8):
            self.bash_edit("echo '# x' >> calc.py")
            _, out, _ = self.stop(active=True)
            blocks += out is not None
        self.assertLessEqual(blocks, 2)


class RevertedToolEdits(VerifyCase):
    def test_edit_then_revert_does_not_block(self):
        p = os.path.join(self.proj, "calc.py")
        self.assertAllowed(self.run_hook(V, self.tool("Edit", {"file_path": p}, cwd=self.proj)))
        write(p, "def add(a, b):\n    return a + b\n")
        self.assertAllowed(self.run_hook(V, self.tool("Edit", {"file_path": p}, cwd=self.proj)))
        write(p, "def add(a, b):\n    return a - b\n")
        self.assertAllowed(self.stop())

    def test_edit_that_never_happened_does_not_block(self):
        # PreToolUse fired, then another hook denied the Edit: the file is unchanged
        p = os.path.join(self.proj, "calc.py")
        self.assertAllowed(self.run_hook(V, self.tool("Edit", {"file_path": p}, cwd=self.proj)))
        self.assertAllowed(self.stop())

    def test_edit_that_stays_still_blocks(self):
        p = os.path.join(self.proj, "calc.py")
        self.run_hook(V, self.tool("Edit", {"file_path": p}, cwd=self.proj))
        write(p, "def add(a, b):\n    return a + b\n")
        self.assertBlocked(self.stop(), "calc.py")


class GeneratedOutputDirs(VerifyCase):
    def test_coverage_html_and_framework_output_do_not_count(self):
        self.bash_edit("mkdir -p htmlcov .svelte-kit .output && echo '<p>' > htmlcov/index.html && "
                       "echo x > htmlcov/a.js && echo x > .svelte-kit/b.js && echo x > .output/c.js")
        self.assertAllowed(self.stop())


class StopStaysFastOnBigChanges(VerifyCase):
    """The Stop check was quadratic in the number of changed files: 3,000 new files took
    minutes, past the 10 s hook timeout, so the guard failed open on the biggest changes."""

    def test_3000_new_committed_files(self):
        for i in range(3000):
            write(os.path.join(self.proj, "gen", f"m{i % 30}", f"f{i}.py"), f"x = {i}\n")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "scaffold")
        t = time.time()
        result = self.stop()
        self.assertLess(time.time() - t, 10, "Stop must finish inside the 10 s hook timeout")
        self.assertBlocked(result, "3000 file(s)")


class BlobHash(HookCase):
    def test_matches_git_hash_object(self):
        p = os.path.join(self.tmp, "f.py")
        write(p, "x = 1\n" * 1000)
        want = subprocess.run(["git", "hash-object", p], capture_output=True, text=True).stdout.strip()
        self.assertEqual(c.blob_hash(p), want)
        self.assertEqual(c.blob_hash(os.path.join(self.tmp, "missing.py")), "-")

    def test_fifo_does_not_block(self):
        p = os.path.join(self.tmp, "pipe.py")
        os.mkfifo(p)
        self.assertEqual(c.blob_hash(p), "-")


class SecretNamesSmuggling(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.realpath(os.path.join(self.tmp, "proj"))
        write(os.path.join(self.proj, ".env"), "OPENAI_API_KEY=sk-test-123\nDEBUG=1\n")
        write(os.path.join(self.proj, "sub", ".env"),
              'PEM="-----BEGIN KEY-----\nMIIEabcdefghijklmnop\n-----END KEY-----"\n')
        self.env = {k: v for k, v in self.env.items() if "\n" not in v}

    def sg(self, cmd):
        return self.run_hook(SG, self.bash(cmd, cwd=self.proj))

    def test_awk_operand_assignment_denied(self):
        # FS=Q makes $1 the whole line, so the "names-only" awk printed every value
        for cmd in ["awk -F= '{print $1}' FS=Q .env", "awk -F= '{print $1}' FS='#' .env"]:
            self.assertDenied(self.sg(cmd))

    def test_grep_ranges_that_span_values_denied(self):
        for cmd in ["grep -o '^[0-z]*' .env", "grep -o '^[--z]*' .env", "grep -oE '^[0-z]+' .env",
                    "grep -o '^[A-z]*' .env"]:
            self.assertDenied(self.sg(cmd))
        for cmd in ["grep -o '^[A-Za-z_][A-Za-z0-9_]*' .env", "grep -o '^[A-Z_-]*' .env"]:
            self.assertAllowed(self.sg(cmd))

    def test_process_substitution_is_parsed(self):
        for cmd in ["diff <(cat .env) /dev/null", "paste <(cat .env)", "cat <(cut -d= -f2 .env)"]:
            self.assertDenied(self.sg(cmd))

    def test_cd_in_the_same_command_is_not_vouched_for(self):
        for cmd in ["cd sub && cut -d= -f1 .env", "cd sub; sed 's/=.*//' .env",
                    "(cd sub && awk -F= '{print $1}' .env)", "env -C sub cut -d= -f1 .env"]:
            self.assertDenied(self.sg(cmd))
        self.assertAllowed(self.sg("cut -d= -f1 .env"))

    def test_sourced_multiline_values_block_env_names(self):
        for cmd in ["source sub/.env && env | cut -d= -f1", "set -a; . ./sub/.env; set +a; printenv | cut -d= -f1"]:
            self.assertDenied(self.sg(cmd))
        self.assertAllowed(self.sg("source .env && env | cut -d= -f1"))


class SqlTautologyEvasions(unittest.TestCase):
    def test_comments_parens_and_heredoc_lines(self):
        for cmd in ['psql -c "DELETE FROM users WHERE 1=1 -- cleanup" db',
                    "sqlite3 app.db 'DELETE FROM users WHERE true /* all */'",
                    'psql -c "DELETE FROM users WHERE (1)=(1)" db',
                    "psql mydb <<'SQL'\nDELETE FROM users\nWHERE 1=1;\nSQL"]:
            with self.subTest(cmd=cmd):
                hit = dg.evaluate(cmd, "/")
                self.assertIsNotNone(hit)
                self.assertEqual(hit[0], "sql-delete-no-where")

    def test_real_filters_with_comments_allowed(self):
        for cmd in ['psql -c "DELETE FROM users WHERE email = \'x\' -- by email" db',
                    "psql mydb <<'SQL'\nDELETE FROM users\nWHERE id = 5;\nSQL",
                    'psql -c "DELETE FROM users WHERE lower(a) = lower(a) AND id = 3" db']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(dg.evaluate(cmd, "/"))


class SubshellAndBraceGrouping(HookCase):
    """(cmd) and { cmd; } hid the command head from every guard."""

    def test_destructive(self):
        for cmd in ["(cd /tmp && rm -rf ~)", "{ rm -rf ~; }", "( rm -rf / )", "! rm -rf ~"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(dg.evaluate(cmd, "/tmp"))
        for cmd in ["(cd build && rm -rf dist)", "((i++))", "echo $(date)"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(dg.evaluate(cmd, "/tmp"))

    def test_secret(self):
        import secret_guard as sg
        for cmd in ["(cat .env)", "{ cat .env; }", "(cd sub && cat .env)"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(sg.evaluate_bash(cmd, self.tmp))

    def test_verify(self):
        proj = git_repo(os.path.join(self.tmp, "proj"), {"app.py": "x = 1\n"})
        self.env["CLAUDE_PROJECT_DIR"] = proj
        ev = lambda cmd: self.bash(cmd, cwd=proj)
        self.assertDenied(self.run_hook(V, ev("(git push origin feat)")), "irreversible")
        write(os.path.join(proj, "app.py"), "x = 2\n")
        self.assertDenied(self.run_hook(V, ev("(npm test || true) && VERIFY_OK=1 git push origin feat")),
                          "do not count")
        self.assertAllowed(self.run_hook(V, ev("(cd . && npm test) && VERIFY_OK=1 git push origin feat")))


class HeredocBodiesAreData(VerifyCase):
    """cat > run_tests.sh <<EOF ... pytest ... EOF writes a file; nothing in it ran."""

    def test_written_script_mentioning_tests_is_not_a_test_run(self):
        self.bash_edit()
        for cmd in ["cat > run_tests.sh <<'EOF'\n#!/bin/sh\npytest -q\nEOF",
                    "cat > Makefile <<'EOF'\ntest:\n\tpytest -q\nEOF"]:
            self.bash_edit(cmd)
        self.assertBlocked(self.stop(), "calc.py")

    def test_written_deploy_script_is_not_a_push(self):
        self.assertAllowed(self.pre("cat > deploy.sh <<'EOF'\ngit push origin main\nEOF"))
        self.assertAllowed(self.pre("cat > notes.txt <<'EOF'\nVERIFY_OK=1\nEOF"))
        self.assertDenied(self.pre("cat > x.sh <<'EOF'\nVERIFY_OK=1\nEOF\ngit push origin feat"), "irreversible")

    def test_bodies_that_run_still_count(self):
        for cmd in ["bash <<'EOF'\ngit push origin feat\nEOF", "cat <<'EOF' | sh\ngit push origin feat\nEOF",
                    "docker exec -i app sh <<EOF\ngit push origin feat\nEOF"]:
            with self.subTest(cmd=cmd):
                self.assertDenied(self.pre(cmd), "irreversible")
        self.bash_edit()
        self.bash_edit("bash <<'EOF'\npython3 -m pytest -q 2>/dev/null || true\nEOF")
        self.assertAllowed(self.stop())


if __name__ == "__main__":
    unittest.main()
