import json
import os
import subprocess
import sys
import unittest

from helpers import ROOT, SCRIPTS, HookCase

import _common as c


class Normalize(unittest.TestCase):
    def heads(self, cmd):
        return [argv[0] for argv in c.all_argvs(cmd)]

    def test_split(self):
        self.assertEqual(c.split_top_level("a && b || c; d | e & f"),
                         [["a"], ["b"], ["c"], ["d", "e"], ["f"]])
        self.assertEqual(c.split_top_level("echo 'a && b' | grep x"), [["echo 'a && b'", "grep x"]])
        self.assertEqual(c.split_top_level("make 2>&1 | tee log"), [["make 2>&1", "tee log"]])

    def test_prefix_stripping(self):
        self.assertEqual(self.heads("sudo -u root env A=1 B=2 nohup rm x"), ["rm"])
        self.assertEqual(self.heads("FOO=1 timeout 5 git push"), ["git"])
        self.assertEqual(self.heads("env"), ["env"])
        self.assertEqual(self.heads("command -v git"), ["git"])

    def test_unwrap(self):
        self.assertEqual(self.heads("bash -c 'cd x && rm -rf y'"), ["cd", "rm"])
        self.assertEqual(self.heads("sh -lc \"git push\""), ["git"])
        self.assertIn("cat", self.heads("echo $(cat .env)"))
        self.assertIn("cat", self.heads("echo `cat .env`"))

    def test_bad_input(self):
        self.assertEqual(c.command_stages(""), [])
        self.assertEqual(c.command_stages(None), [])
        c.all_argvs("echo 'unterminated")  # must not raise


class FailOpen(HookCase):
    def test_crashing_handler_exits_zero_silently(self):
        code = ("import sys; sys.path.insert(0, %r); import _common as c\n"
                "def boom(e): raise RuntimeError('kaboom')\n"
                "c.run_hook('t', boom)\n") % SCRIPTS
        proc = subprocess.run([sys.executable, "-c", code], input="{}", capture_output=True,
                              text=True, env=self.env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertTrue(any(x["action"] == "error-fail-open" for x in self.log_lines()))

    def test_unwritable_state_dir_still_guards(self):
        bogus = os.path.join(self.tmp, "a-file")
        open(bogus, "w").close()
        self.env["FOUNDRY_GUARDRAILS_STATE_DIR"] = bogus  # not a directory
        self.assertDenied(self.run_hook("destructive_guard.py", self.bash("rm -rf /")))
        self.assertAllowed(self.run_hook("verify_before_done.py", self.stop()))


class Manifest(unittest.TestCase):
    def test_hooks_json_points_at_real_executables(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as fh:
            data = json.load(fh)
        seen = set()
        for event, groups in data["hooks"].items():
            for g in groups:
                for h in g["hooks"]:
                    self.assertEqual(h["command"], "python3")
                    script = h["args"][0]
                    self.assertTrue(script.startswith("${CLAUDE_PLUGIN_ROOT}/"))
                    path = os.path.join(ROOT, script.replace("${CLAUDE_PLUGIN_ROOT}/", ""))
                    self.assertTrue(os.path.isfile(path), path)
                    self.assertTrue(os.access(path, os.X_OK), path)
                    seen.add(os.path.basename(path))
        self.assertEqual(seen, {"destructive_guard.py", "secret_guard.py", "verify_before_done.py",
                                "worktree_guard.py", "stale_write_guard.py", "ship_stop.py"})


if __name__ == "__main__":
    unittest.main()
