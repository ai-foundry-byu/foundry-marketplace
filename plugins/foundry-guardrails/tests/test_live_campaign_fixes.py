"""Regression tests for the defects found by the 2026-10-28 live hook campaign (lane L5).

Each class names the defect id it pins down (D2..D9 in the campaign's defect list).
"""
import os
import subprocess
import unittest

from helpers import HookCase, git, git_repo

import destructive_guard as dg

V = "verify_before_done.py"
SW = "stale_write_guard.py"
SS = "ship_stop.py"
SG = "secret_guard.py"


def write(path, text, mode="w"):
    with open(path, mode, encoding="utf-8") as fh:
        fh.write(text)


class StopShape(HookCase):
    """D9 / (7): a Stop guard must use the documented non-error path."""

    def assertStopFeedback(self, result, contains=""):
        code, out, err = result
        self.assertEqual(code, 0)
        self.assertEqual(err, "", "a Stop guard must print nothing on stderr")
        self.assertIsNotNone(out, "expected Stop feedback, got nothing")
        self.assertNotIn("decision", out, "decision:block is shown as a hook error")
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "Stop")
        if contains:
            self.assertIn(contains, hso["additionalContext"])
        return hso["additionalContext"]


class VerifyShellEdits(StopShape):
    """D2: code edits made through Bash must arm the Stop check."""

    def setUp(self):
        super().setUp()
        self.proj = git_repo(os.path.join(self.tmp, "proj"), {
            "calc.py": "def add(a, b):\n    return a - b\n",
            "README.md": "# calc\n",
            "pre_dirty.py": "x = 1\n",
        })
        self.env["CLAUDE_PROJECT_DIR"] = self.proj
        # a file that was already dirty before the session started
        write(os.path.join(self.proj, "pre_dirty.py"), "x = 2\n")

    def pre(self, cmd, session="s1"):
        return self.run_hook(V, self.bash(cmd, cwd=self.proj, session=session))

    def sh(self, cmd):
        subprocess.run(cmd, shell=True, cwd=self.proj, check=True, capture_output=True)

    def stop(self, session="s1", **kw):
        return self.run_hook(V, HookCase.stop(session=session, cwd=self.proj, **kw))

    def bash_edit(self, cmd):
        """PreToolUse for cmd, then run it for real, the way Claude Code does."""
        self.assertAllowed(self.pre(cmd))
        self.sh(cmd)

    def start(self):
        self.assertAllowed(self.pre("ls"))  # the session's first hook call takes the snapshot

    def test_sed_in_place(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertStopFeedback(self.stop(), "calc.py")

    def test_heredoc_redirect(self):
        self.start()
        self.bash_edit("cat > calc.py <<'EOF'\ndef add(a, b):\n    return a + b\nEOF")
        self.assertStopFeedback(self.stop(), "calc.py")

    def test_tee(self):
        self.start()
        self.bash_edit("printf 'def sub(a, b):\\n    return a - b\\n' | tee sub.py >/dev/null")
        self.assertStopFeedback(self.stop(), "sub.py")

    def test_python_writes_file(self):
        self.start()
        self.bash_edit("python3 - <<'EOF'\nopen('calc.py', 'w').write('def add(a, b):\\n    return a + b\\n')\nEOF")
        self.assertStopFeedback(self.stop(), "calc.py")

    def test_cp(self):
        self.start()
        self.bash_edit("cp calc.py calc2.py")
        self.assertStopFeedback(self.stop(), "calc2.py")

    def test_docs_only_bash_edit_does_not_block(self):
        self.start()
        self.bash_edit("echo 'more words' >> README.md && mkdir -p docs && echo x > docs/api.py")
        self.assertAllowed(self.stop())

    def test_side_effect_files_do_not_block(self):
        self.start()
        self.bash_edit("echo data > app.db && echo '{}' > out.json && echo log > run.log")
        self.assertAllowed(self.stop())

    def test_pre_existing_dirty_file_does_not_block(self):
        self.start()
        self.assertAllowed(self.stop())

    def test_edit_then_tests_allows(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertAllowed(self.pre("python3 -m pytest -q"))
        self.assertAllowed(self.stop())

    def test_edit_and_test_in_one_command_allows(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak && python3 -m unittest -q 2>/dev/null; true")
        self.assertAllowed(self.stop())

    def test_tests_then_edit_blocks(self):
        self.start()
        self.assertAllowed(self.pre("python3 -m pytest -q"))
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertStopFeedback(self.stop(), "calc.py")

    def test_edit_commit_without_tests_blocks(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        git(self.proj, "commit", "-qam", "fix")
        self.assertStopFeedback(self.stop(), "calc.py")

    def test_edit_test_commit_then_push_with_token(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertAllowed(self.pre("python3 -m pytest -q"))
        self.assertAllowed(self.pre("git commit -qam fix"))
        git(self.proj, "commit", "-qam", "fix")
        self.assertAllowed(self.pre("VERIFY_OK=1 git push origin feature"))
        self.assertAllowed(self.stop())

    def test_one_block_then_no_nag_next_turn(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertStopFeedback(self.stop())
        self.assertAllowed(self.stop(active=True))
        self.assertAllowed(self.stop())  # same change, next turn: not nagged again

    def test_sessions_have_their_own_snapshot(self):
        self.start()
        self.bash_edit("sed -i.bak 's/a - b/a + b/' calc.py && rm calc.py.bak")
        self.assertAllowed(self.stop(session="other"))  # its first call: snapshot only
        self.assertStopFeedback(self.stop())


class VerifyShellEditsNoGit(StopShape):
    """D2 fallback: outside git, shell write targets are read from the command."""

    def setUp(self):
        super().setUp()
        self.proj = os.path.realpath(os.path.join(self.tmp, "plain"))
        os.makedirs(self.proj)
        write(os.path.join(self.proj, "calc.py"), "x = 1\n")
        self.env["CLAUDE_PROJECT_DIR"] = self.proj

    def pre(self, cmd, session="s1"):
        return self.run_hook(V, self.bash(cmd, cwd=self.proj, session=session))

    def stop(self, session="s1", **kw):
        return self.run_hook(V, HookCase.stop(cwd=self.proj, session=session, **kw))

    def test_patterns_mark_dirty(self):
        for cmd, name in [("sed -i '' 's/1/2/' calc.py", "calc.py"),
                          ("cat > app.py <<'EOF'\nprint(1)\nEOF", "app.py"),
                          ("echo 'x = 2' | tee -a lib.py", "lib.py"),
                          ("cp calc.py calc2.py", "calc2.py"),
                          ("perl -pi -e 's/1/2/' calc.py", "calc.py"),
                          ("python3 - <<'EOF'\nopen('gen.py','w').write('x')\nEOF", "shell")]:
            with self.subTest(cmd=cmd):
                sid = "s-" + str(abs(hash(cmd)))  # the block cap is per session
                self.assertAllowed(self.pre(cmd, session=sid))
                self.assertStopFeedback(self.stop(session=sid), name)
                self.assertAllowed(self.stop(session=sid, active=True))

    def test_docs_and_data_targets_do_not_count(self):
        for cmd in ["cat > NOTES.md <<'EOF'\nhi\nEOF", "echo hi >> notes.txt", "python3 app.py > out.json",
                    "echo x > /tmp/elsewhere.py", "ls 2>&1 >/dev/null"]:
            self.assertAllowed(self.pre(cmd))
        self.assertAllowed(self.stop())

    def test_pattern_then_test_allows(self):
        self.assertAllowed(self.pre("sed -i '' 's/1/2/' calc.py"))
        self.assertAllowed(self.pre("python3 -m pytest"))
        self.assertAllowed(self.stop())


class VerifyOkToken(HookCase):
    """D5 / (4): VERIFY_OK=1 is for after the tests pass, not instead of them."""

    def setUp(self):
        super().setUp()
        self.proj = git_repo(os.path.join(self.tmp, "proj"), {"app.py": "x = 1\n"})
        self.env["CLAUDE_PROJECT_DIR"] = self.proj

    def pre(self, cmd):
        return self.run_hook(V, self.bash(cmd, cwd=self.proj))

    def edit(self):
        r = self.run_hook(V, self.tool("Edit", {"file_path": os.path.join(self.proj, "app.py")},
                                       cwd=self.proj))
        # then the Edit happens, as in Claude Code (an Edit that leaves the file as it was is
        # not a change: see test_adversarial_review.RevertedToolEdits)
        write(os.path.join(self.proj, "app.py"), "x = 2\n")
        return r

    def test_token_refused_after_untested_edit(self):
        self.edit()
        self.assertDenied(self.pre("VERIFY_OK=1 git push origin feature"), "run the tests first")
        self.assertAllowed(self.pre("python3 -m pytest"))
        self.assertAllowed(self.pre("VERIFY_OK=1 git push origin feature"))

    def test_token_allowed_when_no_code_changed(self):
        self.assertAllowed(self.pre("VERIFY_OK=1 git push origin feature"))

    def test_tests_in_the_same_command_count(self):
        self.edit()
        self.assertAllowed(self.pre("python3 -m pytest && VERIFY_OK=1 git push origin feature"))

    def test_token_on_harmless_command_is_not_a_verification(self):
        self.edit()
        self.assertAllowed(self.pre("VERIFY_OK=1 true"))
        _, out, _ = self.run_hook(V, HookCase.stop(cwd=self.proj))
        self.assertIsNotNone(out)

    def test_deny_text_tells_agent_not_to_self_certify(self):
        code, out, _ = self.pre("git push origin feature")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("Only after a passing run", reason)
        self.assertIn("do not add VERIFY_OK=1", reason)

    def test_destructive_command_gets_one_reason(self):
        # destructive-guard denies this one; verify stays silent so its reason is the one shown
        self.assertAllowed(self.pre("git push --force origin main"))
        self.assertDenied(self.run_hook("destructive_guard.py",
                                        self.bash("git push --force origin main", cwd=self.proj)))
        self.env["FOUNDRY_DESTRUCTIVE_GUARD"] = "0"
        self.assertDenied(self.pre("git push --force origin main"), "irreversible")


class ShipStopCap(StopShape):
    """D3: the default cap must fire before Claude Code's own backstop."""

    PLAN = "- [ ] M1 Search is case-insensitive\n"

    def setUp(self):
        super().setUp()
        self.plan = os.path.join(self.tmp, "WORKPLAN.md")
        write(self.plan, self.PLAN)
        self.env["FOUNDRY_SHIP_WORKPLAN"] = self.plan

    def stop(self, **kw):
        return self.run_hook(SS, HookCase.stop(cwd=self.tmp, **kw))

    def test_default_cap_is_8_and_the_human_message_shows(self):
        for i in range(8):
            self.assertStopFeedback(self.stop(active=True), f"continuation {i + 1} of at most 8")
        code, out, err = self.stop(active=True)
        self.assertEqual(err, "")
        self.assertIn("a human needs to look", out["systemMessage"])
        self.assertNotIn("hookSpecificOutput", out)
        self.assertEqual(self.log_lines()[-1]["action"], "allow-cap-reached")


class StaleWrite(HookCase):
    """D4 / (2): deny by default, but never for the session's own uncommitted work."""

    def setUp(self):
        super().setUp()
        self.repo = git_repo(os.path.join(self.tmp, "repo"), {"README.md": "hello\n"})
        self.f = os.path.join(self.repo, "README.md")

    def pre_write(self, content="new\n", session="s1"):
        return self.run_hook(SW, self.tool("Write", {"file_path": self.f, "content": content},
                                           cwd=self.repo, session=session))

    def post(self, tool, session="s1"):
        ev = self.tool(tool, {"file_path": self.f}, cwd=self.repo, session=session)
        ev["hook_event_name"] = "PostToolUse"
        return self.run_hook(SW, ev)

    def test_dirty_file_denied_by_default_with_a_correct_message(self):
        write(self.f, "canary-uncommitted\n", "a")
        code, out, _ = self.pre_write()
        self.assertDenied((code, out, ""), "Edit")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertNotIn("Read the file again now", reason)
        self.assertIn("even after a Read", reason)
        self.assertIn("commit or stash", reason)

    def test_enforce_0_is_warn_only(self):
        write(self.f, "canary-uncommitted\n", "a")
        self.env["FOUNDRY_STALE_WRITE_ENFORCE"] = "0"
        self.assertWarned(self.pre_write(), "uncommitted")

    def test_session_own_write_can_be_rewritten(self):
        self.assertAllowed(self.pre_write("v1\n"))  # clean vs HEAD
        write(self.f, "v1\n")                       # the Write happens
        self.assertAllowed(self.post("Write"))
        self.assertAllowed(self.pre_write("v2\n"))  # dirty, but only with our own write

    def test_session_own_edit_can_be_rewritten(self):
        write(self.f, "hello\nedited by Edit\n")
        self.assertAllowed(self.post("Edit"))
        self.assertAllowed(self.pre_write("v2\n"))

    def test_someone_else_changes_after_our_write_are_protected(self):
        write(self.f, "v1\n")
        self.post("Write")
        write(self.f, "v1\nhuman line\n", )
        self.assertDenied(self.pre_write("v2\n"))

    def test_other_session_write_does_not_count(self):
        write(self.f, "v1\n")
        self.post("Write", session="other")
        self.assertDenied(self.pre_write("v2\n"))


class SqlTautology(unittest.TestCase):
    """D6 / (5): an always-true WHERE is no WHERE."""

    def deny(self, sql):
        hit = dg.evaluate(f'sqlite3 app.db "{sql}"', "/")
        self.assertIsNotNone(hit, sql)
        self.assertEqual(hit[0], "sql-delete-no-where", sql)

    def allow(self, sql):
        self.assertIsNone(dg.evaluate(f'sqlite3 app.db "{sql}"', "/"), sql)

    def test_tautologies_denied(self):
        for sql in ["DELETE FROM t WHERE 1", "delete from t where 1=1", "DELETE FROM t WHERE true",
                    "DELETE FROM t WHERE 'x'='x'", "DELETE FROM t WHERE id=id", "DELETE FROM t WHERE 1 OR id=2",
                    "DELETE FROM t WHERE id = 2 or 1 = 1", "DELETE FROM t WHERE (1=1)", "DELETE FROM t WHERE 2>1",
                    "DELETE FROM t WHERE 1 <> 0", "DELETE FROM t WHERE NOT 0", "DELETE FROM t WHERE 1=1;",
                    "DELETE FROM t WHERE 1 = 1 AND 2 = 2"]:
            self.deny(sql)
        self.assertEqual(dg.evaluate("psql -c 'DELETE FROM t WHERE 1=1' db", "/")[0], "sql-delete-no-where")
        self.assertEqual(dg.evaluate("echo 'delete from t where 1' | sqlite3 app.db", "/")[0],
                         "sql-delete-no-where")

    def test_real_filters_allowed(self):
        for sql in ["DELETE FROM t WHERE id=2", "delete from t where name='bob'", "DELETE FROM t WHERE id = 1 AND 1=1",
                    "DELETE FROM t WHERE a=1 AND (b=2 OR 1=1)", "DELETE FROM t WHERE name = 'tom or 1=1'",
                    "DELETE FROM t WHERE 1=0", "DELETE FROM t WHERE created_at < date('now', '-7 days')",
                    "DELETE FROM t WHERE id IN (1, 2)"]:
            self.allow(sql)


class SecretNames(HookCase):
    """D8 / (6): listing the NAMES in a .env is allowed; printing values is not."""

    def setUp(self):
        super().setUp()
        self.proj = os.path.realpath(os.path.join(self.tmp, "proj"))
        os.makedirs(self.proj)
        write(os.path.join(self.proj, ".env"),
              "# app settings\nOPENAI_API_KEY=sk-test-123\nexport DATABASE_URL='postgres://u:p@h/db'\n\nDEBUG=1\n")
        # the hook's own environment must not hold multi-line values for the env | cut case
        self.env = {k: v for k, v in self.env.items() if "\n" not in v}

    def sg(self, cmd):
        return self.run_hook(SG, self.bash(cmd, cwd=self.proj))

    def test_names_only_forms_allowed(self):
        for cmd in ["cut -d= -f1 .env", "cut -d '=' -f 1 .env", "cut -f1 -d= .env | sort",
                    "sed 's/=.*//' .env", "sed -E 's/=.*$//' .env", "sed -n 's/=.*//p' .env",
                    "awk -F= '{print $1}' .env", "awk -F '=' '{ print $1 }' .env | sort | uniq",
                    "grep -o '^[A-Za-z_][A-Za-z0-9_]*' .env", "grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env",
                    "env | cut -d= -f1", "printenv | cut -d= -f1 | sort"]:
            self.assertAllowed(self.sg(cmd))

    def test_value_printing_forms_still_denied(self):
        for cmd in ["cut -d= -f2 .env", "cut -d= -f1,2 .env", "cut -d= -f1- .env", "awk -F= '{print $2}' .env",
                    "awk -F= '{print $1, $2}' .env", "sed 's/=/ /' .env", "grep -o '^[A-Z_]*=.*' .env",
                    "cut -d= -f1 .env | xargs -I{} grep {} .env", "cut -d= -f1 .env; cat .env",
                    "cut -d= -f1 .env | tee names.txt", "env", "env | cut -d= -f2"]:
            self.assertDenied(self.sg(cmd))

    def test_multiline_value_is_not_names_only(self):
        write(os.path.join(self.proj, ".env"), 'KEY="-----BEGIN KEY-----\nMIIEabcdefghijklmnop\n-----END KEY-----"\n')
        self.assertDenied(self.sg("cut -d= -f1 .env"), "not NAME=value")

    def test_deny_reasons_point_at_the_names_form(self):
        self.assertDenied(self.sg("cat .env"), "cut -d= -f1 .env")
        self.assertDenied(self.sg("env"), "cut -d= -f1")


if __name__ == "__main__":
    unittest.main()
