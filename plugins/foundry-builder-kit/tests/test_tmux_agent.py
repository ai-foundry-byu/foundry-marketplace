"""Integration tests for tmux_agent.py. Skipped when tmux is not installed."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "tmux-agents", "scripts", "tmux_agent.py")
sys.path.insert(0, os.path.dirname(SCRIPT))

import tmux_agent  # noqa: E402


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class TmuxAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sockdir = tempfile.mkdtemp(prefix="tma-")
        cls.env = {**os.environ, "TMUX_AGENT_SOCKET": os.path.join(cls.sockdir, "t.sock")}
        os.environ["TMUX_AGENT_SOCKET"] = cls.env["TMUX_AGENT_SOCKET"]

    @classmethod
    def tearDownClass(cls):
        subprocess.run([sys.executable, SCRIPT, "kill", "--all"], env=cls.env, capture_output=True)
        shutil.rmtree(cls.sockdir, ignore_errors=True)

    def cli(self, *args, timeout=60):
        return subprocess.run([sys.executable, SCRIPT, *args], env=self.env, capture_output=True,
                              text=True, timeout=timeout)

    def test_repl_round_trip(self):
        self.assertEqual(self.cli("start", "repl", "--cmd", "PYTHON_BASIC_REPL=1 python3 -q").returncode, 0)
        self.assertEqual(self.cli("wait", "repl", ">>> ", "--fixed", "--timeout", "15").returncode, 0)
        self.cli("send", "repl", "print(6*7)")
        self.assertEqual(self.cli("wait", "repl", "^42$", "--timeout", "10").returncode, 0)
        self.assertEqual(self.cli("kill", "repl").returncode, 0)

    def test_run_returns_output_and_exit_code(self):
        self.cli("start", "sh", "--cmd", "exec /bin/sh")
        ok = self.cli("run", "sh", "echo hello-from-pane", "--timeout", "15")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("hello-from-pane", ok.stdout)
        bad = self.cli("run", "sh", "sh -c 'exit 3'", "--timeout", "15")
        self.assertEqual(bad.returncode, 3)
        self.cli("kill", "sh")

    def test_wait_timeout_and_literal_send(self):
        self.cli("start", "lit", "--cmd", "exec /bin/sh")
        self.assertEqual(self.cli("wait", "lit", "never-appears-zzz", "--timeout", "1").returncode, 1)
        self.cli("send", "lit", "echo C-c Enter literal")
        self.assertEqual(self.cli("wait", "lit", "^C-c Enter literal$", "--timeout", "10").returncode, 0)
        self.cli("kill", "lit")

    def test_ls_and_private_socket(self):
        self.cli("start", "listed")
        out = self.cli("ls").stdout
        self.assertIn("listed", out)
        self.assertEqual(tmux_agent.socket_path(), self.env["TMUX_AGENT_SOCKET"])
        self.cli("kill", "listed")


class SocketPathTests(unittest.TestCase):
    """L6-D7: the default socket is per project, so agents in different projects never share sessions."""

    def setUp(self):
        self.saved = os.environ.pop("TMUX_AGENT_SOCKET", None)
        self.cwd = os.getcwd()
        self.a = tempfile.mkdtemp(prefix="tma-a-")
        self.b = tempfile.mkdtemp(prefix="tma-b-")

    def tearDown(self):
        os.chdir(self.cwd)
        if self.saved is not None:
            os.environ["TMUX_AGENT_SOCKET"] = self.saved
        shutil.rmtree(self.a, ignore_errors=True)
        shutil.rmtree(self.b, ignore_errors=True)

    def sock_in(self, d):
        os.chdir(d)
        return tmux_agent.socket_path()

    def test_different_projects_get_different_sockets(self):
        sa, sb = self.sock_in(self.a), self.sock_in(self.b)
        self.assertNotEqual(sa, sb)
        self.assertEqual(sa, self.sock_in(self.a))
        self.assertEqual(oct(os.stat(os.path.dirname(sa)).st_mode & 0o777), "0o700")

    def test_subdirectory_of_a_git_repo_shares_the_repo_socket(self):
        subprocess.run(["git", "init", "-q", self.a], check=True)
        sub = os.path.join(self.a, "src", "deep")
        os.makedirs(sub)
        self.assertEqual(self.sock_in(sub), self.sock_in(self.a))

    def test_env_override_still_wins(self):
        os.environ["TMUX_AGENT_SOCKET"] = os.path.join(self.b, "shared.sock")
        try:
            self.assertEqual(self.sock_in(self.a), os.path.join(self.b, "shared.sock"))
        finally:
            os.environ.pop("TMUX_AGENT_SOCKET", None)


class SkillHelperShellTests(unittest.TestCase):
    """L6-D6: the documented helper must work in zsh (macOS default) and bash, where `$T start` did not."""
    SKILL = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "SKILL.md")

    def blocks(self):
        with open(self.SKILL) as fh:
            text = fh.read()
        return text, re.findall(r"```bash\n(.*?)```", text, re.S)

    def test_no_word_split_helper_left(self):
        text, blocks = self.blocks()
        self.assertNotIn('T="python3', text)
        self.assertIsNone(re.search(r"\$T\b", text))
        for b in blocks:
            if re.search(r"^T [a-z]", b, re.M):
                self.assertIn("T() {", b, "every block that calls T must define it (functions do not "
                                          "survive between Bash tool calls)")

    def test_helper_runs_in_zsh_and_bash(self):
        _, blocks = self.blocks()
        define = next(ln for b in blocks for ln in b.splitlines() if ln.startswith("T() {"))
        define = define.replace("${CLAUDE_SKILL_DIR}", os.path.dirname(os.path.dirname(SCRIPT)))
        for sh in ("zsh", "bash"):
            exe = shutil.which(sh)
            if not exe:
                continue
            res = subprocess.run([exe, "-c", define + "\nT --help"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"{sh}: {res.stderr}")
            self.assertIn("private socket", res.stdout)


if __name__ == "__main__":
    unittest.main()
