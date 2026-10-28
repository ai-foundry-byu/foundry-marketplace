"""Regression tests for the 2026-10-28 independent review (review D) of the retest fixes."""
import json
import os
import unittest

from helpers import HookCase, git, git_repo

import secret_guard as sg

W = "worktree_guard.py"


# ---------------------------------------------------------------------------
# worktree-guard: the subagent-lane protection must hold for the registry the skill writes
# ---------------------------------------------------------------------------

class WorktreeGuardLaneRegistryHoles(HookCase):
    def setUp(self):
        super().setUp()
        self.parent = os.path.realpath(os.path.join(self.tmp, "work"))
        self.main = git_repo(os.path.join(self.parent, "app"), {"src/app.py": "x = 1\n"})
        self.lane = os.path.realpath(os.path.join(self.parent, "app-lanes", "L1"))
        git(self.main, "worktree", "add", "-q", "-b", "lane/L1", self.lane)
        self.target = os.path.join(self.main, "src", "app.py")

    def registry(self, lanes):
        with open(os.path.join(self.main, ".git", "foundry-lanes.json"), "w") as fh:
            json.dump({"active": True, "lanes": lanes}, fh)

    def edit(self, target, cwd):
        ev = self.tool("Edit", {"file_path": target}, cwd=cwd)
        ev["agent_id"] = "a1b2"
        ev["agent_type"] = "general-purpose"
        return self.run_hook(W, ev)

    def test_null_worktrees_from_the_skill_template_still_protect_main(self):
        # parallel-lanes writes the registry before launch with "worktree": null per lane
        self.registry([{"id": "L1", "tasks": ["T-02"], "branch": None, "worktree": None},
                       {"id": "L2", "tasks": ["T-03"], "branch": None, "worktree": None}])
        self.assertDenied(self.edit(self.target, self.main), "no lane has registered")
        self.assertAllowed(self.edit(os.path.join(self.lane, "src", "app.py"), self.main))

    def test_lane_path_at_or_above_main_does_not_switch_the_guard_off(self):
        for wt in (".", self.main, self.parent):
            self.registry([{"id": "L1", "worktree": wt}])
            self.assertDenied(self.edit(self.target, self.main))

    def test_session_started_above_the_repo_is_covered(self):
        self.registry([{"id": "L1", "worktree": self.lane}])
        self.assertDenied(self.edit(self.target, self.parent))
        self.assertDenied(self.edit(os.path.join(self.main, "src", "new_dir", "n.py"), self.parent))
        self.assertDenied(self.edit(os.path.join(self.main, ".git", "foundry-lanes.json"), self.parent))
        self.assertAllowed(self.edit(os.path.join(self.lane, "src", "app.py"), self.parent))

    def test_case_variant_path_on_a_case_insensitive_volume_denied(self):
        upper = os.path.join(self.parent, "APP", "src", "app.py")
        if not os.path.exists(upper):
            self.skipTest("case-sensitive volume")
        self.registry([{"id": "L1", "worktree": None}])
        self.assertDenied(self.edit(upper, self.main))
        self.assertDenied(self.edit(upper, self.lane))  # the linked-worktree rule too
        self.assertAllowed(self.edit(os.path.join(self.parent, "APP-LANES", "L1", "a.py"), self.lane))

    def test_deny_tells_the_subagent_not_to_edit_the_registry(self):
        self.registry([{"id": "L1", "worktree": None}])
        res = self.edit(self.target, self.main)
        self.assertDenied(res, "a subagent never edits that file")


# ---------------------------------------------------------------------------
# secret-guard: values smuggled past the names-only allowance, and stdin-fed code
# ---------------------------------------------------------------------------

class SecretReviewD(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        with open(os.path.join(self.proj, ".env"), "w") as fh:
            fh.write("API_KEY=FAKE-NOT-REAL\nAWS_SECRET_ACCESS_KEY=FAKE\n")
        with open(os.path.join(self.proj, "app.py"), "w") as fh:
            fh.write("print(1)\n")

    def deny(self, cmd):
        self.assertIsNotNone(sg.evaluate_bash(cmd, self.proj), f"expected deny: {cmd!r}")

    def allow(self, cmd):
        self.assertIsNone(sg.evaluate_bash(cmd, self.proj), f"expected allow: {cmd!r}")

    def test_printenv_of_names_from_a_names_only_listing_denied(self):
        for cmd in ["printenv $(env | cut -d= -f1)", "printenv $(env | cut -d= -f1 | grep -i aws)",
                    "printenv `env | cut -d= -f1 | grep -i key`",
                    "for k in $(env | cut -d= -f1 | grep -i aws); do printenv $k; done",
                    'for k in $(cut -d= -f1 .env); do printenv "$k"; done',
                    'source .env; for k in $(cut -d= -f1 .env); do echo "$k=${!k}"; done',
                    "for k in API_KEY DB_PASSWORD; do printenv $k; done", "k=API_KEY; printenv $k"]:
            self.deny(cmd)
        for cmd in ["printenv HOME", "printenv PATH HOME", "env | cut -d= -f1 | grep -i aws",
                    'for k in $(env | cut -d= -f1 | grep -i aws); do echo "$k"; done']:
            self.allow(cmd)

    def test_code_fed_to_an_interpreter_on_stdin_denied(self):
        for cmd in ["python3 - <<'PY'\nprint(open('.env').read())\nPY",
                    "python3 - <<'PY'\nfrom dotenv import dotenv_values\nprint(dotenv_values('.env'))\nPY",
                    "python3 - <<EOF\nimport os\nprint(os.environ)\nEOF",
                    "node <<'JS'\nconsole.log(require('fs').readFileSync('.env', 'utf8'))\nJS",
                    "python3 <<< 'print(open(\".env\").read())'"]:
            self.deny(cmd)
        for cmd in ["python3 - <<'PY'\nprint(1 + 1)\nPY", "python3 - <<'PY'\nprint(1)\nPY\nls -la .env",
                    "python3 <<< 'print(2)'"]:
            self.allow(cmd)

    def test_versioned_interpreter_names_checked(self):
        for cmd in ["python3.12 -c \"print(open('.env').read())\"",
                    "python3.11 -c 'import os; print(os.environ)'"]:
            self.deny(cmd)
        self.allow("python3.12 -c 'print(1)'")

    def test_binding_inside_a_shell_wrapper_followed(self):
        self.deny("bash -c 'f=.env; cat \"$f\"'")
        self.deny('sh -c "f=.env; cat \\$f"')
        self.allow("bash -c 'f=app.py; cat \"$f\"'")

    def test_listing_dotfiles_of_a_folder_with_env_into_a_reader_denied(self):
        for cmd in ["ls -A | xargs cat", "ls -a | xargs -n1 head", 'ls -A | while read f; do cat "$f"; done',
                    "for f in $(ls -A); do cat $f; done", "cat $(ls -A)"]:
            self.deny(cmd)
        for cmd in ["ls -A", "ls -la", "ls | xargs cat", "for f in $(ls *.py); do cat $f; done",
                    "ls -a | grep -c env"]:
            self.allow(cmd)


if __name__ == "__main__":
    unittest.main()
