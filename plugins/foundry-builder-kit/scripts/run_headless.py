#!/usr/bin/env python3
"""run_headless.py: run one headless `claude -p` job safely from any scheduler.

Works the same under cron, launchd, systemd, Windows Task Scheduler and GitHub
Actions, because all the safety lives here instead of in the scheduler syntax:

  - a lock, so a slow run and the next scheduled run never overlap
  - a hard timeout, so a stuck run cannot hang forever
  - the transcript saved to a log directory, one JSON file per run
  - a heartbeat written ONLY on real success (exit 0, not an error result, non-empty
    result), for deadman.py to check

Usage:
  run_headless.py --name daily-digest --prompt-file prompts/digest.md \
      --workdir "$HOME/projects/<your-app>" --max-minutes 20 \
      -- --max-turns 30 --allowedTools "Read,Grep,Glob,Bash(git log:*)"

Everything after `--` is passed to claude unchanged.

Auth for unattended runs: set CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`)
or ANTHROPIC_API_KEY in the job's environment. Interactive logins stored in a
desktop keychain are often not reachable from a scheduler.

Exit codes: 0 success, 1 claude failed or returned an error, 4 another run holds
the lock, 5 timeout, 6 claude binary not found.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deadman  # noqa: E402


def acquire_lock(path: str, stale_after_s: float) -> bool:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {time.time():.0f}\n")
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(path)
            except FileNotFoundError:
                continue
            if age > stale_after_s:
                os.remove(path)  # a crashed run left it behind
                continue
            return False
    return False


def judge(returncode: int, stdout: str) -> tuple[bool, str]:
    """Decide success from claude's exit code and its --output-format json result."""
    if returncode != 0:
        return False, f"claude exited {returncode}"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return (bool(stdout.strip()), "non-JSON output" if stdout.strip() else "empty output")
    if isinstance(data, list):  # some versions emit a list of events; the last is the result
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {})
    if data.get("is_error"):
        return False, f"result is_error ({data.get('subtype', 'unknown')})"
    result = str(data.get("result", "")).strip()
    if not result:
        return False, "empty result"
    return True, result[:120].replace("\n", " ")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description="Run a headless claude -p job with lock, timeout, log and heartbeat.")
    ap.add_argument("--name", required=True, help="job name (used for lock, log and heartbeat files)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt", help="prompt text")
    g.add_argument("--prompt-file", help="file holding the prompt")
    ap.add_argument("--workdir", default=os.getcwd(), help="project directory to run in")
    ap.add_argument("--state-dir", default=None, help="where lock, logs and heartbeat go (default: <workdir>/.agent-jobs)")
    ap.add_argument("--max-minutes", type=float, default=20.0)
    ap.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    a = ap.parse_args(argv)

    exe = shutil.which(a.claude_bin) or (a.claude_bin if os.path.isfile(a.claude_bin) else None)
    if not exe:
        print(f"run_headless: {a.claude_bin!r} not found on PATH. Schedulers run with a minimal PATH; "
              "pass --claude-bin with an absolute path.", file=sys.stderr)
        return 6

    prompt = a.prompt if a.prompt is not None else open(a.prompt_file, encoding="utf-8").read()
    state = a.state_dir or os.path.join(a.workdir, ".agent-jobs")
    lock = os.path.join(state, f"{a.name}.lock")
    beat = os.path.join(state, f"{a.name}.heartbeat.json")
    logs = os.path.join(state, "logs")
    os.makedirs(logs, exist_ok=True)

    timeout_s = a.max_minutes * 60
    if not acquire_lock(lock, stale_after_s=timeout_s + 300):
        print(f"run_headless: {a.name} is already running (lock {lock}); skipping this run", file=sys.stderr)
        return 4

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = os.path.join(logs, f"{a.name}-{stamp}-{os.getpid()}.json")
    cmd = [exe, "-p", prompt, "--output-format", "json", *extra]
    try:
        try:
            proc = subprocess.run(cmd, cwd=a.workdir, capture_output=True, text=True,
                                  timeout=timeout_s, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
            print(f"run_headless: {a.name} timed out after {a.max_minutes} min (log {log_path})", file=sys.stderr)
            return 5
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(proc.stdout)
        if proc.stderr:
            with open(log_path + ".stderr", "w", encoding="utf-8") as fh:
                fh.write(proc.stderr)
        ok, detail = judge(proc.returncode, proc.stdout)
        if ok:
            deadman.write_beat(beat, "ok", detail)
            print(f"run_headless: {a.name} ok: {detail}")
            return 0
        print(f"run_headless: {a.name} FAILED: {detail} (log {log_path})", file=sys.stderr)
        return 1
    finally:
        try:
            os.remove(lock)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    sys.exit(main())
