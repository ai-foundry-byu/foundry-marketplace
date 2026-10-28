"""Test helpers: run a hook script the way Claude Code does (JSON on stdin)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "hooks", "scripts")
sys.path.insert(0, SCRIPTS)

_SCRUB = [k for k in os.environ if k.startswith("FOUNDRY_") or k in (
    "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR")]


class HookCase(unittest.TestCase):
    """Base class: isolated state dir and a clean FOUNDRY_* environment."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fg-test-")
        self.state = os.path.join(self.tmp, "state")
        self.env = {k: v for k, v in os.environ.items() if k not in _SCRUB}
        self.env["FOUNDRY_GUARDRAILS_STATE_DIR"] = self.state
        self.env["HOME"] = os.environ.get("HOME", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, script: str, event, env: dict | None = None, raw: str | None = None):
        e = dict(self.env)
        e.update(env or {})
        stdin = raw if raw is not None else json.dumps(event)
        proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)], input=stdin,
                              capture_output=True, text=True, env=e, timeout=30)
        out = proc.stdout.strip()
        parsed = json.loads(out) if out else None
        return proc.returncode, parsed, proc.stderr

    @staticmethod
    def bash(cmd: str, cwd: str = "/", session: str = "s1") -> dict:
        return {"session_id": session, "hook_event_name": "PreToolUse", "cwd": cwd,
                "tool_name": "Bash", "tool_input": {"command": cmd}}

    @staticmethod
    def tool(name: str, tool_input: dict, cwd: str = "/", session: str = "s1") -> dict:
        return {"session_id": session, "hook_event_name": "PreToolUse", "cwd": cwd,
                "tool_name": name, "tool_input": tool_input}

    @staticmethod
    def stop(session: str = "s1", cwd: str = "/", active: bool = False, **extra) -> dict:
        ev = {"session_id": session, "hook_event_name": "Stop", "cwd": cwd,
              "stop_hook_active": active}
        ev.update(extra)
        return ev

    def assertDenied(self, result, contains: str = ""):
        code, out, _ = result
        self.assertEqual(code, 0)
        self.assertIsNotNone(out, "expected a deny decision, got no output")
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        if contains:
            self.assertIn(contains, hso["permissionDecisionReason"])

    def assertAllowed(self, result):
        code, out, err = result
        self.assertEqual(code, 0, err)
        self.assertIsNone(out, f"expected silent allow, got {out}")

    def assertWarned(self, result, contains: str = ""):
        code, out, _ = result
        self.assertEqual(code, 0)
        self.assertIsNotNone(out)
        hso = out["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hso)
        self.assertIn("warning", hso["additionalContext"])
        if contains:
            self.assertIn(contains, hso["additionalContext"])

    def log_lines(self) -> list[dict]:
        path = os.path.join(self.state, "guardrails.log")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]


def git_repo(path: str, files: dict | None = None) -> str:
    """Create a git repo with one commit. Returns its realpath."""
    os.makedirs(path, exist_ok=True)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

    def g(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, env=env)

    g("init", "-q", "-b", "main")
    for name, text in (files or {"app.py": "print('hi')\n"}).items():
        full = os.path.join(path, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    return os.path.realpath(path)


def git(path: str, *args: str) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, env=env)
