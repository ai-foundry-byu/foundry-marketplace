#!/usr/bin/env python3
"""commit_secret_guard.py: Claude Code PreToolUse hook (matcher: Bash).

When the agent is about to run `git commit`, scan what that commit would contain
and block the command (exit 2) if it holds something that looks like a secret.
Every other Bash command passes through untouched, so the cost is one JSON parse.

It uses gitleaks when it is on PATH (better rules), and the bundled stdlib scanner
otherwise. Output is redacted.

Turn it off for one session:  export FOUNDRY_SECRETS_GUARD=0
Allow a known false positive: add the comment  secrets-hygiene: allow  on that line.

This guards commits the AGENT makes. Commits you type yourself need the git
pre-commit hook from the secrets-hygiene skill as well.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_secrets  # noqa: E402

GIT_COMMIT_RE = re.compile(r"(?:^|[;&|()]|\s)git\s+(?:-C\s+(\S+)\s+)?(?:-c\s+\S+\s+)*commit\b(.*)")


def parse_commit(command: str) -> tuple[bool, str | None, bool]:
    """Return (is_commit, -C dir or None, includes_unstaged_tracked_changes)."""
    m = GIT_COMMIT_RE.search(command)
    if not m:
        return False, None, False
    rest = re.split(r"[;&|]", m.group(2), maxsplit=1)[0]
    try:
        tokens = shlex.split(rest)
    except ValueError:
        tokens = rest.split()
    stage_all = False
    for t in tokens:
        if t == "--all":
            stage_all = True
        elif t.startswith("-") and not t.startswith("--") and "a" in t[1:]:
            # -a, -am, -av; stop at -m's value which shlex keeps as a separate token
            stage_all = True
    dir_ = m.group(1)
    if dir_:
        dir_ = dir_.strip("'\"")
    return True, dir_, stage_all


def run_gitleaks(repo: str) -> list[str] | None:
    """Return redacted finding lines, [] when clean, None if gitleaks failed to run."""
    exe = shutil.which("gitleaks")
    if not exe:
        return None
    try:
        res = subprocess.run(
            [exe, "git", "--pre-commit", "--staged", "--redact", "--no-banner", "--no-color", "-v", repo],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode == 0:
        return []
    if res.returncode == 1:
        lines = [ln for ln in (res.stdout + res.stderr).splitlines()
                 if ln.strip().startswith(("RuleID", "File", "Line", "Secret"))]
        return lines or ["gitleaks reported a leak (run: gitleaks git --pre-commit --staged -v)"]
    return None


def main() -> int:
    if os.environ.get("FOUNDRY_SECRETS_GUARD", "1").strip().lower() in ("0", "false", "off", "no"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    is_commit, dir_, stage_all = parse_commit(command)
    if not is_commit:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    repo = os.path.join(cwd, dir_) if dir_ else cwd
    if not os.path.isdir(repo):
        return 0

    messages: list[str] = []
    try:
        leaks = run_gitleaks(repo)
        if leaks is None:
            messages = [f.render() for f in scan_secrets.scan_diff_mode(True, repo)]
        else:
            messages = leaks
        if stage_all:
            # `git commit -a` stages tracked changes at commit time; gitleaks --staged cannot see them yet.
            messages += [f.render() for f in scan_secrets.scan_diff_mode(False, repo)]
    except (RuntimeError, subprocess.TimeoutExpired, OSError):
        return 0  # not a git repo, or git missing: let git itself report it

    if not messages:
        return 0
    print("Blocked: this commit appears to contain secrets (values redacted):", file=sys.stderr)
    for m in messages[:20]:
        print(f"  {m}", file=sys.stderr)
    print(
        "Unstage the file (git restore --staged <file>), move the value into .env.local "
        "(gitignored), and reference it by name. If a real key was ever committed or pushed, "
        "treat it as leaked: run the secrets-hygiene skill's rotation flow. "
        "False positive: add the comment 'secrets-hygiene: allow' on that line.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
