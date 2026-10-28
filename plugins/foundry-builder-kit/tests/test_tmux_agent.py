"""Integration tests for tmux_agent.py. Skipped when tmux is not installed."""
import os
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


if __name__ == "__main__":
    unittest.main()
