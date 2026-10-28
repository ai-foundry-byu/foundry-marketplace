import os
import unittest

from helpers import HookCase

import verify_before_done as v

S = "verify_before_done.py"


class Classification(unittest.TestCase):
    def test_code_vs_docs(self):
        proj = "/proj"
        self.assertTrue(v.is_code_file("/proj/src/app.py", proj))
        self.assertTrue(v.is_code_file("/proj/web/index.ts", proj))
        for p in ["/proj/README.md", "/proj/notes.txt", "/proj/docs/api.py", "/proj/guide.rst",
                  "/proj/.claude/plans/x.py", "/elsewhere/app.py"]:
            self.assertFalse(v.is_code_file(p, proj), p)

    def test_ignore_env(self):
        os.environ["FOUNDRY_VERIFY_IGNORE"] = "*.json, config/*"
        try:
            self.assertFalse(v.is_code_file("/proj/package.json", "/proj"))
            self.assertFalse(v.is_code_file("/proj/config/app.py", "/proj"))
            self.assertTrue(v.is_code_file("/proj/src/app.py", "/proj"))
        finally:
            del os.environ["FOUNDRY_VERIFY_IGNORE"]

    def test_test_commands(self):
        for cmd in ["pytest", "python -m pytest -q", "python3 -m unittest discover -s tests",
                    "uv run pytest", "npm test", "npm run test:unit", "pnpm typecheck",
                    "npx tsc --noEmit", "go test ./...", "cargo test", "cd web && npm run typecheck",
                    "bun test", "make test"]:
            self.assertTrue(v.is_test_command(cmd), cmd)
        for cmd in ["echo pytest", "git commit -m 'run pytest later'", "npm install", "ls tests"]:
            self.assertFalse(v.is_test_command(cmd), cmd)

    def test_irreversible(self):
        for cmd in ["git push", "git push origin main", "vercel --prod", "vercel deploy --prod",
                    "npm publish", "wrangler deploy", "wrangler pages deploy dist",
                    "gh pr merge 12 --squash", "terraform apply", "docker push me/app",
                    "sudo firebase deploy", "bash -c 'twine upload dist/*'"]:
            self.assertIsNotNone(v.irreversible(cmd), cmd)
        for cmd in ["git push --dry-run", "git status", "vercel ls", "npm run build",
                    "git commit -m 'git push later'", "wrangler dev", "terraform plan"]:
            self.assertIsNone(v.irreversible(cmd), cmd)


class Flow(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        self.env["CLAUDE_PROJECT_DIR"] = self.proj

    def edit(self, rel, session="s1"):
        return self.run_hook(S, self.tool("Edit", {"file_path": os.path.join(self.proj, rel),
                                                   "old_string": "a", "new_string": "b"},
                                          cwd=self.proj, session=session))

    def stop(self, session="s1", **kw):
        return self.run_hook(S, HookCase.stop(session=session, cwd=self.proj, **kw))

    def assertStopBlocked(self, result):
        code, out, _ = result
        self.assertEqual(code, 0)
        self.assertIsNotNone(out)
        # non-error Stop feedback (2026-10-28): decision:block is shown as "Stop hook error"
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertIn("test", out["hookSpecificOutput"]["additionalContext"])

    def test_no_edits_no_block(self):
        self.assertAllowed(self.stop())

    def test_doc_edit_no_block(self):
        self.assertAllowed(self.edit("README.md"))
        self.assertAllowed(self.edit("docs/setup.py"))
        self.assertAllowed(self.stop())

    def test_code_edit_then_stop_blocks_once(self):
        self.assertAllowed(self.edit("app.py"))
        self.assertStopBlocked(self.stop())
        # Claude continues because of our block: stop_hook_active is true, so allow
        self.assertAllowed(self.stop(active=True))
        self.assertTrue(any(x["action"] == "allow-unverified-stop" for x in self.log_lines()))

    def test_code_edit_then_tests_then_stop_allows(self):
        self.edit("app.py")
        self.assertAllowed(self.run_hook(S, self.bash("python -m pytest -q", cwd=self.proj)))
        self.assertAllowed(self.stop())

    def test_edit_after_test_needs_new_test(self):
        self.run_hook(S, self.bash("pytest", cwd=self.proj))
        self.edit("app.py")
        self.assertStopBlocked(self.stop())

    def test_block_cap_per_session(self):
        for _ in range(2):
            self.edit("app.py")
            self.assertStopBlocked(self.stop())
            self.assertAllowed(self.stop(active=True))
        self.edit("app.py")
        self.assertAllowed(self.stop())  # cap of 2 reached
        self.assertTrue(any("cap" in str(x.get("why", "")) for x in self.log_lines()))

    def test_cap_configurable(self):
        self.env["FOUNDRY_VERIFY_MAX_BLOCKS"] = "0"
        self.edit("app.py")
        self.assertAllowed(self.stop())

    def test_background_tasks_allow(self):
        self.edit("app.py")
        self.assertAllowed(self.stop(background_tasks=[{"id": "t1", "type": "shell"}]))
        self.assertStopBlocked(self.stop())  # still dirty afterwards

    def test_sessions_are_isolated(self):
        self.edit("app.py", session="a")
        self.assertAllowed(self.stop(session="b"))
        self.assertStopBlocked(self.stop(session="a"))

    def test_push_denied_without_token(self):
        self.assertDenied(self.run_hook(S, self.bash("git push origin feature", cwd=self.proj)),
                          "VERIFY_OK=1")
        self.assertEqual(self.log_lines()[-1]["action"], "deny")

    def test_push_token_only_after_tests(self):
        # 2026-10-28 live campaign (D5): the token was typed with no tests run
        self.edit("app.py")
        self.assertDenied(self.run_hook(S, self.bash("VERIFY_OK=1 git push", cwd=self.proj)),
                          "run the tests first")
        self.run_hook(S, self.bash("pytest", cwd=self.proj))
        self.assertAllowed(self.run_hook(S, self.bash("VERIFY_OK=1 git push", cwd=self.proj)))
        self.assertAllowed(self.stop())

    def test_disabled(self):
        self.env["FOUNDRY_VERIFY"] = "0"
        self.assertAllowed(self.run_hook(S, self.bash("git push", cwd=self.proj)))
        self.edit("app.py")
        self.assertAllowed(self.stop())

    def test_malformed(self):
        for raw in ["", "garbage", "[]", '{"hook_event_name":"Stop","session_id":{"x":1}}',
                    '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":5}']:
            self.assertAllowed(self.run_hook(S, None, raw=raw))


if __name__ == "__main__":
    unittest.main()
