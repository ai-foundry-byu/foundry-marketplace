"""Tests for scan_secrets.py, probe_key.py and the commit_secret_guard.py hook.

Run from the plugin root:  python3 -m unittest discover -s tests -v
Fake keys below are built by concatenation so this file does not trip scanners itself.
"""
import atexit
import json
import os
import re
import shlex
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


_NO_GITLEAKS_BIN = []


def no_gitleaks_path():
    """A PATH with git but without gitleaks. git's own directory is not enough: Homebrew puts
    gitleaks in the same /opt/homebrew/bin, which made "bundled scanner only" runs use gitleaks."""
    if not _NO_GITLEAKS_BIN:
        d = tempfile.mkdtemp(prefix="fbk-bin-")
        os.symlink(shutil.which("git"), os.path.join(d, "git"))
        atexit.register(shutil.rmtree, d, True)
        _NO_GITLEAKS_BIN.append(d)
    path = f"{_NO_GITLEAKS_BIN[0]}:/usr/bin:/bin"
    if shutil.which("gitleaks", path=path):
        raise unittest.SkipTest("gitleaks is installed in /usr/bin or /bin: cannot test the bundled scanner alone")
    return path


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

    def test_published_examples_and_local_defaults_are_ignored(self):
        text = "\n".join([
            "aws_access_key_id = AKIA" + "IOSFODNN7EXAMPLE",  # AWS's own documentation key
            "DATABASE_URL: postgresql://postgres:postgres@localhost:5432/app",
            "url = postgres://app:Xk9hvL2qPz7R@127.0.0.1/app",
        ])
        self.assertEqual(scan_secrets.scan_text("x", text), [])
        remote = scan_secrets.scan_text("x", "url = postgres://app:Xk9hvL2qPz7R@db.prod.internal/app")
        self.assertEqual([f.rule for f in remote], ["postgres-url-with-password"])

    def test_placeholders_in_provider_key_shapes_are_ignored(self):
        text = "\n".join([
            "ANTHROPIC_API_KEY=sk-ant-" + "your-key-here-0000000000000",
            "GITHUB_TOKEN=ghp_" + "x" * 36,
            "AWS_ACCESS_KEY_ID=AKIA" + "XXXXXXXXXXXXXXXX",
        ])
        self.assertEqual(scan_secrets.scan_text(".env.example", text), [])

    def test_gitleaks_allow_marker_is_honored(self):
        self.assertEqual(scan_secrets.scan_text("t.py", f'X = "{FAKE_GH}"  # gitleaks:allow'), [])

    def test_special_files_are_not_read(self):
        d = tempfile.mkdtemp(prefix="fbk-special-")
        try:
            fifo = os.path.join(d, "pipe")
            os.mkfifo(fifo)
            secret = os.path.join(d, "outside.txt")
            with open(secret, "w") as fh:
                fh.write(f'K = "{FAKE_AWS}"\n')
            link = os.path.join(d, "link.txt")
            os.symlink(secret, link)
            self.assertEqual(scan_secrets.scan_paths([fifo]), [])  # would block forever if opened
            self.assertEqual(scan_secrets.scan_paths([link], follow_symlinks=False), [])
            self.assertEqual(len(scan_secrets.scan_paths([link])), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


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
        self.assertEqual(commit_secret_guard.parse_commit('cd a && git commit -am "x"'), (True, "a", True))  # cd is followed
        self.assertEqual(commit_secret_guard.parse_commit("git -C sub commit --all -m y"), (True, "sub", True))
        self.assertEqual(commit_secret_guard.parse_commit('git commit --amend -m "a"')[2], False)
        self.assertFalse(commit_secret_guard.parse_commit("echo git-commit")[0])

    def stage_secret(self):
        with open(os.path.join(self.repo, "settings.py"), "w") as fh:
            fh.write(f'TOKEN = "{FAKE_GH}"\n')
        git(self.repo, "add", "settings.py")

    def test_blocks_staged_secret_with_stdlib_scanner(self):
        self.stage_secret()
        res = self.run_hook('git commit -m "add settings"', path_env=no_gitleaks_path())
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
                             capture_output=True, text=True, env={**os.environ, "FOUNDRY_COMMIT_SECRET_GUARD": "0"})
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


class ScanAllIncludesUntrackedTests(unittest.TestCase):
    """L6-D2: --all must scan untracked, not-gitignored files (the ones `git add .` would leak)."""

    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_all_finds_untracked_secret_and_skips_ignored(self):
        with open(os.path.join(self.repo, "settings.py"), "w") as fh:
            fh.write(f'OPENAI = "{FAKE_OPENAI}"\n')
        with open(os.path.join(self.repo, ".gitignore"), "w") as fh:
            fh.write("ignored.py\n")
        with open(os.path.join(self.repo, "ignored.py"), "w") as fh:
            fh.write(f'AWS = "{FAKE_AWS}"\n')
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan_secrets.py"), "--all", "--cwd", self.repo],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("settings.py", res.stdout)
        self.assertNotIn("ignored.py", res.stdout)

    def test_all_clean_output_says_untracked_were_included(self):
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan_secrets.py"), "--all", "--cwd", self.repo],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("untracked", res.stdout)


class RepoHookMixin:
    """A fresh repo per test, plus helpers that pipe a PreToolUse payload into the guard."""

    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def run_hook(self, command, env_extra=None, stdlib_only=False):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.repo})
        env = {**os.environ, **(env_extra or {})}
        if stdlib_only:
            env["PATH"] = no_gitleaks_path()
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "commit_secret_guard.py")],
                              input=payload, capture_output=True, text=True, env=env)

    def assert_blocked(self, command, **kw):
        for stdlib_only in (True, False):
            res = self.run_hook(command, stdlib_only=stdlib_only, **kw)
            self.assertEqual(res.returncode, 2, f"{command!r} stdlib_only={stdlib_only}: {res.stderr}")
            self.assertIn("Blocked", res.stderr)
            self.assertNotIn(FAKE_AWS, res.stderr)
            self.assertNotIn(FAKE_GH, res.stderr)

    def assert_allowed(self, command):
        res = self.run_hook(command, stdlib_only=True)
        self.assertEqual(res.returncode, 0, f"{command!r}: {res.stderr}")


class ChainedStageCommitTests(RepoHookMixin, unittest.TestCase):
    """D1 / L6-D3: a single command that stages and commits must be scanned for what it WILL commit."""

    def test_add_all_and_commit(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_blocked("git add -A && git commit -m wip")
        self.assert_blocked("git add --all && git commit -m wip")

    def test_add_dot_semicolon_commit(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_blocked("git add . ; git commit -m x")
        self.assert_blocked("git add .\ngit commit -m x")

    def test_add_named_file_and_commit(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_blocked("git add settings.py && git commit -m x")
        self.assert_blocked('git add "settings.py" && git commit -m "add settings"')

    def test_quoted_path_with_space_and_subdir(self):
        self.write("my app/config.py", f'TOKEN = "{FAKE_GH}"\n')
        self.assert_blocked('git add "my app/config.py" && git commit -m x')
        self.assert_blocked("git add 'my app' && git commit -m x")

    def test_git_dash_C_and_cd(self):
        self.write("sub/cfg.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_blocked("git -C sub add cfg.py && git -C sub commit -m x")
        self.assert_blocked("cd sub && git add . && git commit -m x")

    def test_commit_am_on_modified_tracked_file(self):
        with open(os.path.join(self.repo, "README.md"), "a") as fh:
            fh.write(f"key: {FAKE_AWS}\n")
        self.assert_blocked('git commit -am "docs"')
        self.assert_blocked("git commit -a -m docs")
        self.assert_blocked("git commit -m docs README.md")

    def test_or_chain_and_bash_c(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_blocked("git add -A || true; git commit -m x")
        self.assert_blocked("bash -c 'git add -A && git commit -m x'")

    def test_add_force_of_ignored_env_file(self):
        self.write(".gitignore", ".env\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore")
        self.write(".env", "X=1\n")
        self.assert_blocked("git add -f .env && git commit -m x")

    def test_untracked_secret_not_staged_by_this_command_is_allowed(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.write("ok.py", "x = 1\n")
        self.assert_allowed("git add ok.py && git commit -m ok")
        self.assert_allowed('git commit --allow-empty -m "msg mentions -a and settings.py"')

    def test_gitignored_secret_is_not_staged_by_add_all(self):
        self.write(".gitignore", "local_settings.py\n")
        self.write("local_settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_allowed("git add -A && git commit -m ignore")

    def test_clean_chain_passes(self):
        self.write("app.py", "print('hi')\n")
        self.assert_allowed("git add -A && git commit -m app")

    def test_new_and_deprecated_off_switch(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        for name in ("FOUNDRY_COMMIT_SECRET_GUARD", "FOUNDRY_SECRETS_GUARD"):
            res = self.run_hook("git add -A && git commit -m x", env_extra={name: "0"})
            self.assertEqual(res.returncode, 0, name)

    def test_first_commit_of_new_repo(self):
        d = tempfile.mkdtemp(prefix="fbk-new-")
        try:
            with open(os.path.join(d, "settings.py"), "w") as fh:
                fh.write(f'AWS_KEY = "{FAKE_AWS}"\n')
            payload = json.dumps({"tool_name": "Bash", "cwd": d, "tool_input": {
                "command": "git init && git add . && git commit -m init"}})
            res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "commit_secret_guard.py")],
                                 input=payload, capture_output=True, text=True)
            self.assertEqual(res.returncode, 2, res.stderr)
            self.assertFalse(os.path.exists(os.path.join(d, ".git")), "the guard must not create the repo")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_heredoc_commit_message(self):
        self.write("settings.py", f'AWS_KEY = "{FAKE_AWS}"\n')
        self.assert_blocked("git add -A && git commit -F - <<'EOF'\nit's a message\nEOF")

    def test_plan_parser(self):
        plan = commit_secret_guard.plan_command
        p = plan("git add -A && git commit -m wip", "/r")
        self.assertTrue(p.commits)
        self.assertEqual([(s.kind, s.pathspecs) for s in p.stages], [("all", [])])
        p = plan('git -C "my dir" add a.py \'b c.py\'; git -C "my dir" commit -m x', "/r")
        self.assertEqual(p.stages[0].cwd, os.path.join("/r", "my dir"))
        self.assertEqual(p.stages[0].pathspecs, ["a.py", "b c.py"])
        p = plan("git commit -am x", "/r")
        self.assertEqual([s.kind for s in p.stages], ["tracked"])
        p = plan("git commit -ma", "/r")  # -m with message "a", not -a
        self.assertEqual(p.stages, [])
        self.assertFalse(plan("echo 'git add -A && git commit -m x'", "/r").commits)
        self.assertFalse(plan("git add -A", "/r").commits)
        self.assertEqual(plan("git add -n .", "/r").stages, [])


class ShellFormsTests(RepoHookMixin, unittest.TestCase):
    """Adversarial review 2026-10-28: shell forms that used to slip past the guard, and its false blocks."""

    def secret(self, rel="cfg.py"):
        self.write(rel, f'AWS_KEY = "{FAKE_AWS}"\n')

    def tracked_secret(self):
        with open(os.path.join(self.repo, "README.md"), "a") as fh:
            fh.write(f"key: {FAKE_AWS}\n")

    def run_hook_in(self, command, cwd, stdlib_only=True, timeout=None):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
        env = {**os.environ}
        if stdlib_only:
            env["PATH"] = no_gitleaks_path()
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "commit_secret_guard.py")],
                              input=payload, capture_output=True, text=True, env=env, timeout=timeout)

    def test_redirections_do_not_become_pathspecs(self):
        self.secret()
        self.assert_blocked("git add -A 2>/dev/null && git commit -m x")
        self.assert_blocked("git add -A >/dev/null 2>&1; git commit -m x")

    def test_redirections_on_commit_all(self):
        self.tracked_secret()
        self.assert_blocked("git commit -am x 2>&1 | tail -3")
        self.assert_blocked("git commit -am x > /dev/null")

    def test_trailing_comment(self):
        self.secret()
        self.assert_blocked("git add -A  # stage everything\ngit commit -m x")

    def test_computed_cd_and_dash_C_stay_in_the_repo(self):
        self.secret()
        os.makedirs(os.path.join(self.repo, "src"))
        sub = os.path.join(self.repo, "src")
        for cmd in ('cd "$(git rev-parse --show-toplevel)" && git add -A && git commit -m x',
                    'git -C "$(pwd)" add -A && git commit -m x', 'cd "$PWD" && git add -A && git commit -m x'):
            res = self.run_hook_in(cmd, sub)
            self.assertEqual(res.returncode, 2, f"{cmd!r}: {res.stderr}")

    def test_cd_inside_subshell_does_not_leak(self):
        self.secret()
        other = make_repo()
        try:
            self.assert_blocked(f"(cd {shlex.quote(other)} && git status) && git add -A && git commit -m x")
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_cd_dash_returns(self):
        self.secret()
        self.assert_blocked("cd / && cd - && git add -A && git commit -m x")

    def test_git_aliases(self):
        self.secret()
        self.assert_blocked("git add -A && git -c alias.ci=commit ci -m x")
        git(self.repo, "config", "alias.ci", "commit")
        self.assert_blocked("git add -A && git ci -m x")
        git(self.repo, "config", "alias.save", "!git add -A && git commit -m save")
        self.assert_blocked("git save")

    def test_runner_programs(self):
        self.tracked_secret()
        self.assert_blocked("timeout 60 git commit -am x")
        self.assert_blocked("git ls-files -m | xargs git add && git commit -m x")
        self.assert_blocked("find . -name README.md -exec git add {} + && git commit -m x")

    def test_paths_known_only_at_run_time(self):
        self.secret()
        self.assert_blocked('F=cfg.py; git add "$F" && git commit -m x')
        self.assert_blocked('for f in cfg.py; do git add "$f"; done && git commit -m x')

    def test_shell_forms_that_run_git(self):
        self.secret()
        self.assert_blocked("bash -lc 'git add -A && git commit -m x'")
        self.assert_blocked("bash <<'EOF'\ngit add -A\ngit commit -m x\nEOF")

    def test_key_in_the_command_text(self):
        self.assert_blocked(f"cat > cfg.py <<'EOF'\nAWS_KEY = \"{FAKE_AWS}\"\nEOF\ngit add cfg.py && git commit -m x")
        self.assert_blocked(f"echo 'AWS_KEY = \"{FAKE_AWS}\"' > cfg.py && git add -A && git commit -m x")
        self.assert_blocked(f'git commit --allow-empty -m "rotate {FAKE_AWS}"')

    def test_prestaged_secret_is_scanned_by_both_scanners(self):
        # gitleaks skips both of these (a non-base32 AWS-style id, a secret by file name only);
        # the bundled scanner must still run on the index when gitleaks is installed.
        self.write("cfg.py", 'AWS_ACCESS_KEY_ID = "AKIA' + 'Q7ZZRT5YU8IOPAM1"\n')
        git(self.repo, "add", "cfg.py")
        self.assert_blocked("git commit -m x")
        git(self.repo, "rm", "-q", "--cached", "cfg.py")
        self.write(".env", "DEBUG=1\n")
        git(self.repo, "add", ".env")
        self.assert_blocked("git commit -m x")

    def test_allow_comment_works_for_prestaged_lines_with_gitleaks(self):
        self.write("fixture.py", f'TOKEN = "{FAKE_GH}"  # secrets-hygiene: allow\n')
        git(self.repo, "add", "fixture.py")
        for stdlib_only in (True, False):
            res = self.run_hook_in("git commit -m fixture", self.repo, stdlib_only=stdlib_only)
            self.assertEqual(res.returncode, 0, f"stdlib_only={stdlib_only}: {res.stderr}")

    @unittest.skipUnless(shutil.which("gitleaks"), "gitleaks not installed")
    def test_gitleaks_error_is_not_a_leak(self):
        self.write(".gitleaks.toml", "title = [broken\n")
        self.write("app.py", "x = 1\n")
        res = self.run_hook_in("git add -A && git commit -m ok", self.repo, stdlib_only=False)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_one_failing_stage_keeps_the_other_findings(self):
        self.secret()
        res = self.run_hook("git add -A; git add ../outside.txt; git commit -m x", stdlib_only=True)
        self.assertEqual(res.returncode, 2, res.stderr)

    def test_staging_after_the_commit_does_not_count(self):
        self.secret()
        self.assert_allowed("git commit -m x; git add -A")

    def test_symlinks_and_fifos(self):
        outside = tempfile.mkdtemp(prefix="fbk-outside-")
        try:
            with open(os.path.join(outside, "secret.txt"), "w") as fh:
                fh.write(f'K = "{FAKE_AWS}"\n')
            os.mkfifo(os.path.join(outside, "pipe"))
            os.symlink(os.path.join(outside, "secret.txt"), os.path.join(self.repo, "creds.txt"))
            os.symlink(os.path.join(outside, "pipe"), os.path.join(self.repo, "p"))
            res = self.run_hook_in("git add -A && git commit -m links", self.repo, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)  # git commits the links, not their targets
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_docs_examples_and_local_db_urls_pass(self):
        self.write("README.md", "aws_access_key_id = AKIA" + "IOSFODNN7EXAMPLE\n")
        self.write("docker-compose.yml", "DATABASE_URL: postgresql://postgres:postgres@localhost:5432/app\n")
        self.assert_allowed("git add -A && git commit -m docs")

    def test_secret_file_names_past_the_content_cap(self):
        self.write("a.py", "x = 1\n")
        self.write("z/.env", "X=1\n")
        old = commit_secret_guard.MAX_FILES
        commit_secret_guard.MAX_FILES = 1
        try:
            plan = commit_secret_guard.plan_command("git add -A && git commit -m x", self.repo)
            found = commit_secret_guard.collect_findings(plan, self.repo)
        finally:
            commit_secret_guard.MAX_FILES = old
        self.assertTrue(any("z/.env" in m and "secret-file" in m for m in found), found)


class PlainHookInstallTests(unittest.TestCase):
    """L6-D4: the documented plain-hook install must work on a machine without gitleaks."""

    def test_documented_install_without_gitleaks(self):
        skill_dir = os.path.dirname(SCRIPTS)
        with open(os.path.join(skill_dir, "SKILL.md")) as fh:
            text = fh.read()
        m = re.search(r"\*\*plain git hook\*\*.*?```bash\n(.*?)```", text, re.S)
        self.assertIsNotNone(m, "plain git hook block not found")
        install = m.group(1).replace("${CLAUDE_SKILL_DIR}", skill_dir)
        repo = make_repo()
        try:
            env = {**os.environ, "PATH": no_gitleaks_path()}
            res = subprocess.run(["sh", "-c", install], cwd=repo, env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(os.path.join(repo, "app.py"), "w") as fh:
                fh.write("x = 1\n")
            git(repo, "add", "app.py")
            ok = subprocess.run(["git", "commit", "-q", "-m", "clean"], cwd=repo, env=env, capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            with open(os.path.join(repo, "cfg.py"), "w") as fh:
                fh.write(f'KEY = "{FAKE_AWS}"\n')
            git(repo, "add", "cfg.py")
            bad = subprocess.run(["git", "commit", "-q", "-m", "leak"], cwd=repo, env=env, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
        finally:
            shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
