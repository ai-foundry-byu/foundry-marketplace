"""Tests for scan_secrets.py, probe_key.py and the commit_secret_guard.py hook.

Run from the plugin root:  python3 -m unittest discover -s tests -v
Fake keys below are built by concatenation so this file does not trip scanners itself.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "secrets-hygiene", "scripts")
sys.path.insert(0, SCRIPTS)

import commit_secret_guard  # noqa: E402
import probe_key  # noqa: E402
import scan_secrets  # noqa: E402

FAKE_OPENAI = "sk-" + "proj-" + "Q7x9Lm2Pv8Rt4Wz6Yb1Nc3Kd5Hf0Js" + "Ga7Ue2"
FAKE_GH = "ghp" + "_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
FAKE_AWS = "AKIA" + "Z7QW3RT5YU8IO2PA"


def git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env)


def make_repo():
    d = tempfile.mkdtemp(prefix="fbk-repo-")
    git(d, "init", "-q")
    git(d, "config", "user.email", "test@example.com")
    git(d, "config", "user.name", "Test")
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("hello\n")
    git(d, "add", "README.md")
    git(d, "commit", "-q", "-m", "init")
    return d


class ScanLineTests(unittest.TestCase):
    def test_detects_provider_keys(self):
        rules = {f.rule for f in scan_secrets.scan_text("x.py", f'a = "{FAKE_OPENAI}"\nb = "{FAKE_GH}"\nc="{FAKE_AWS}"')}
        self.assertIn("openai-key", rules)
        self.assertIn("github-token", rules)
        self.assertIn("aws-access-key-id", rules)

    def test_output_is_redacted(self):
        f = scan_secrets.scan_text("x.py", f'KEY = "{FAKE_OPENAI}"')[0]
        self.assertNotIn(FAKE_OPENAI, f.render())
        self.assertTrue(f.preview.endswith("***"))

    def test_placeholders_and_env_reads_are_ignored(self):
        text = "\n".join([
            "OPENAI_API_KEY=REPLACE_ME",
            "api_key = os.environ['OPENAI_API_KEY']",
            "const token = process.env.GITHUB_TOKEN",
            "password = 'aaaaaaaaaaaaaaaaaaaa'",
            "SECRET=your_secret_here_please",
        ])
        self.assertEqual(scan_secrets.scan_text("x", text), [])

    def test_generic_high_entropy_assignment(self):
        f = scan_secrets.scan_text("cfg.py", 'db_password = "Xk9#vL2qPz7Rw4Tn8Ys1"'.replace("#", "h"))
        self.assertEqual([x.rule for x in f], ["generic-assignment"])

    def test_allow_pragma(self):
        line = f'FIXTURE = "{FAKE_OPENAI}"  # secrets-hygiene: allow'
        self.assertEqual(scan_secrets.scan_text("t.py", line), [])

    def test_one_finding_per_value(self):
        line = f'OPENAI_API_KEY="{FAKE_OPENAI}"'
        self.assertEqual(len(scan_secrets.scan_text("x", line)), 1)

    def test_private_key_block(self):
        f = scan_secrets.scan_text("k", "-----BEGIN OPENSSH " + "PRIVATE KEY-----")
        self.assertEqual(f[0].rule, "private-key-block")

    def test_secret_filenames(self):
        self.assertTrue(scan_secrets.is_secret_filename(".env"))
        self.assertTrue(scan_secrets.is_secret_filename("app/.env.local"))
        self.assertTrue(scan_secrets.is_secret_filename("certs/server.pem"))
        self.assertFalse(scan_secrets.is_secret_filename(".env.example"))
        self.assertFalse(scan_secrets.is_secret_filename("src/env.ts"))

    def test_parse_unified_diff_line_numbers(self):
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +3,2 @@\n+one\n+two\n"
                "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")
        self.assertEqual(scan_secrets.parse_unified_diff(diff), [("a.py", 3, "one"), ("a.py", 4, "two")])


class ScanGitTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_staged_scan_finds_secret_and_env_file(self):
        with open(os.path.join(self.repo, "config.py"), "w") as fh:
            fh.write(f'KEY = "{FAKE_GH}"\n')
        with open(os.path.join(self.repo, ".env"), "w") as fh:
            fh.write("X=1\n")
        git(self.repo, "add", "-f", "config.py", ".env")
        rules = {f.rule for f in scan_secrets.scan_diff_mode(True, self.repo)}
        self.assertEqual(rules, {"github-token", "secret-file-staged"})
        self.assertEqual(scan_secrets.main(["--staged", "--cwd", self.repo, "--quiet"]), 1)

    def test_clean_staged_scan(self):
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("print('hi')\n")
        git(self.repo, "add", "app.py")
        self.assertEqual(scan_secrets.main(["--staged", "--cwd", self.repo, "--quiet"]), 0)


class ProbeTests(unittest.TestCase):
    def fetch_with(self, status):
        return lambda url, headers: (status, "" if status else "URLError")

    def test_classify(self):
        self.assertEqual(probe_key.classify(200), "LIVE")
        self.assertEqual(probe_key.classify(401), "DEAD")
        for s in (403, 429, 500, None):
            self.assertEqual(probe_key.classify(s), "ERR")

    def test_unset_env_is_err_not_clear(self):
        v, _ = probe_key.probe("openai", "NOPE", fetch=self.fetch_with(401), environ={})
        self.assertEqual(v, "ERR")

    def test_exit_codes(self):
        env = {"K": "sk-test-value-1234"}
        self.assertEqual(probe_key.main(["openai:K"], fetch=self.fetch_with(401), environ=env), 0)
        self.assertEqual(probe_key.main(["openai:K"], fetch=self.fetch_with(200), environ=env), 1)
        self.assertEqual(probe_key.main(["openai:K"], fetch=self.fetch_with(None), environ=env), 2)
        self.assertEqual(probe_key.main(["badformat"], fetch=self.fetch_with(401), environ=env), 3)

    def test_key_never_printed_in_full(self):
        seen = {}

        def fetch(url, headers):
            seen.update(headers)
            return 200, ""
        v, detail = probe_key.probe("anthropic", "K", fetch=fetch, environ={"K": "sk-ant-api03-secretsecret"})
        self.assertEqual(seen["x-api-key"], "sk-ant-api03-secretsecret")
        self.assertNotIn("secretsecret", detail)


class GuardHookTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def run_hook(self, command, path_env=None):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.repo})
        env = {**os.environ}
        if path_env is not None:
            env["PATH"] = path_env
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "commit_secret_guard.py")],
                              input=payload, capture_output=True, text=True, env=env)

    def test_parse_commit(self):
        self.assertEqual(commit_secret_guard.parse_commit("git status"), (False, None, False))
        self.assertEqual(commit_secret_guard.parse_commit('git commit -m "x"'), (True, None, False))
        self.assertEqual(commit_secret_guard.parse_commit('cd a && git commit -am "x"'), (True, None, True))
        self.assertEqual(commit_secret_guard.parse_commit("git -C sub commit --all -m y"), (True, "sub", True))
        self.assertEqual(commit_secret_guard.parse_commit('git commit --amend -m "a"')[2], False)
        self.assertFalse(commit_secret_guard.parse_commit("echo git-commit")[0])

    def stage_secret(self):
        with open(os.path.join(self.repo, "settings.py"), "w") as fh:
            fh.write(f'TOKEN = "{FAKE_GH}"\n')
        git(self.repo, "add", "settings.py")

    def test_blocks_staged_secret_with_stdlib_scanner(self):
        self.stage_secret()
        git_dir = os.path.dirname(shutil.which("git"))
        res = self.run_hook('git commit -m "add settings"', path_env=f"{git_dir}:/usr/bin:/bin")
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("Blocked", res.stderr)
        self.assertNotIn(FAKE_GH, res.stderr)

    @unittest.skipUnless(shutil.which("gitleaks"), "gitleaks not installed")
    def test_blocks_staged_secret_with_gitleaks(self):
        self.stage_secret()
        res = self.run_hook('git commit -m "add settings"')
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertNotIn(FAKE_GH, res.stderr)

    def test_blocks_commit_all_on_unstaged_tracked_change(self):
        with open(os.path.join(self.repo, "README.md"), "a") as fh:
            fh.write(f"key: {FAKE_AWS}\n")
        res = self.run_hook('git commit -a -m "docs"')
        self.assertEqual(res.returncode, 2, res.stderr)

    def test_passes_clean_commit_and_other_commands(self):
        with open(os.path.join(self.repo, "ok.py"), "w") as fh:
            fh.write("x = 1\n")
        git(self.repo, "add", "ok.py")
        self.assertEqual(self.run_hook('git commit -m "ok"').returncode, 0)
        self.assertEqual(self.run_hook("ls -la").returncode, 0)

    def test_disable_switch(self):
        self.stage_secret()
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": self.repo})
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "commit_secret_guard.py")], input=payload,
                             capture_output=True, text=True, env={**os.environ, "FOUNDRY_SECRETS_GUARD": "0"})
        self.assertEqual(res.returncode, 0)

    def test_non_git_dir_passes(self):
        d = tempfile.mkdtemp()
        try:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": d})
            res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "commit_secret_guard.py")], input=payload,
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
