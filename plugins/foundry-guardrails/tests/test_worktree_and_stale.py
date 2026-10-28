import os
import unittest

from helpers import HookCase, git, git_repo

W = "worktree_guard.py"
SW = "stale_write_guard.py"


class WorktreeGuard(HookCase):
    def setUp(self):
        super().setUp()
        self.main = git_repo(os.path.join(self.tmp, "main"), {"src/app.py": "x = 1\n"})
        self.wt = os.path.join(self.main, ".claude", "worktrees", "feature")
        git(self.main, "worktree", "add", "-q", "-b", "feature", self.wt)
        self.wt = os.path.realpath(self.wt)
        self.other = os.path.realpath(os.path.join(self.tmp, "other-wt"))
        git(self.main, "worktree", "add", "-q", "-b", "other", self.other)

    def edit(self, target, cwd, tool="Edit"):
        return self.run_hook(W, self.tool(tool, {"file_path": target}, cwd=cwd))

    def test_edit_inside_own_worktree_allowed(self):
        self.assertAllowed(self.edit(os.path.join(self.wt, "src/app.py"), self.wt))
        self.assertAllowed(self.edit("src/app.py", self.wt))  # relative path

    def test_edit_main_checkout_from_worktree_denied(self):
        res = self.edit(os.path.join(self.main, "src/app.py"), self.wt)
        self.assertDenied(res, os.path.join(self.wt, "src", "app.py"))
        self.assertEqual(self.log_lines()[-1]["action"], "deny")

    def test_write_and_notebook_tools_covered(self):
        self.assertDenied(self.edit(os.path.join(self.main, "new.py"), self.wt, tool="Write"))
        res = self.run_hook(W, self.tool("NotebookEdit", {"notebook_path": os.path.join(self.main, "n.ipynb")},
                                         cwd=self.wt))
        self.assertDenied(res)

    def test_from_subdirectory_of_worktree(self):
        sub = os.path.join(self.wt, "src")
        self.assertDenied(self.edit(os.path.join(self.main, "src/app.py"), sub))

    def test_main_checkout_session_is_noop(self):
        self.assertAllowed(self.edit(os.path.join(self.main, "src/app.py"), self.main))

    def test_outside_paths_allowed(self):
        self.assertAllowed(self.edit(os.path.join(self.tmp, "scratch.py"), self.wt))
        self.assertAllowed(self.edit(os.path.join(self.other, "src/app.py"), self.wt))

    def test_not_a_repo(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertAllowed(self.edit(os.path.join(plain, "a.py"), plain))

    def test_warn_mode_and_disable(self):
        target = os.path.join(self.main, "src/app.py")
        self.env["FOUNDRY_WORKTREE_GUARD_WARN"] = "1"
        self.assertWarned(self.edit(target, self.wt))
        self.env["FOUNDRY_WORKTREE_GUARD"] = "0"
        self.assertAllowed(self.edit(target, self.wt))

    def test_malformed(self):
        for raw in ["", "nope", '{"tool_name":"Edit"}', '{"tool_name":"Edit","tool_input":{"file_path":7}}']:
            self.assertAllowed(self.run_hook(W, None, raw=raw))


class StaleWriteGuard(HookCase):
    def setUp(self):
        super().setUp()
        self.repo = git_repo(os.path.join(self.tmp, "repo"), {"app.py": "a = 1\n"})
        self.f = os.path.join(self.repo, "app.py")

    def write(self, path, content="b = 2\n"):
        return self.run_hook(SW, self.tool("Write", {"file_path": path, "content": content}, cwd=self.repo))

    def make_dirty(self):
        with open(self.f, "a") as fh:
            fh.write("# local change\n")

    def test_clean_tracked_file_allowed(self):
        self.assertAllowed(self.write(self.f))

    def test_new_and_untracked_files_allowed(self):
        self.assertAllowed(self.write(os.path.join(self.repo, "new.py")))
        untracked = os.path.join(self.repo, "scratch.py")
        with open(untracked, "w") as fh:
            fh.write("x\n")
        self.assertAllowed(self.write(untracked))

    def test_dirty_file_warns_by_default(self):
        self.make_dirty()
        self.assertWarned(self.write(self.f), "uncommitted")
        self.assertEqual(self.log_lines()[-1]["action"], "warn")

    def test_dirty_file_denied_when_enforced(self):
        self.make_dirty()
        self.env["FOUNDRY_STALE_WRITE_ENFORCE"] = "1"
        self.assertDenied(self.write(self.f), "Edit")
        self.assertEqual(self.log_lines()[-1]["action"], "deny")

    def test_identical_content_allowed(self):
        self.make_dirty()
        with open(self.f) as fh:
            same = fh.read()
        self.env["FOUNDRY_STALE_WRITE_ENFORCE"] = "1"
        self.assertAllowed(self.write(self.f, same))

    def test_outside_git_allowed(self):
        plain = os.path.join(self.tmp, "plain.py")
        with open(plain, "w") as fh:
            fh.write("x\n")
        self.env["FOUNDRY_STALE_WRITE_ENFORCE"] = "1"
        self.assertAllowed(self.write(plain))

    def test_disable_and_other_tools(self):
        self.make_dirty()
        self.env["FOUNDRY_STALE_WRITE_GUARD"] = "0"
        self.assertAllowed(self.write(self.f))
        self.env.pop("FOUNDRY_STALE_WRITE_GUARD")
        self.assertAllowed(self.run_hook(SW, self.tool("Edit", {"file_path": self.f}, cwd=self.repo)))

    def test_malformed(self):
        for raw in ["", "{]", '{"tool_name":"Write","tool_input":{"file_path":""}}']:
            self.assertAllowed(self.run_hook(SW, None, raw=raw))


if __name__ == "__main__":
    unittest.main()
