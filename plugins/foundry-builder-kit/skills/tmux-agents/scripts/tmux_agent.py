#!/usr/bin/env python3
"""tmux_agent.py: let an agent drive interactive programs through tmux.

Every command uses a PRIVATE tmux socket, one per project, so an agent never types
into the user's own tmux sessions, and agents working in different projects never
see (or kill) each other's sessions.

  tmux_agent.py start  NAME [--cwd DIR] [--cmd "python3 -q"]
  tmux_agent.py send   NAME "text to type"          (types it, then presses Enter separately)
  tmux_agent.py send   NAME "text" --no-enter
  tmux_agent.py keys   NAME C-c                     (control keys: C-c, C-d, Escape, Up, Tab, ...)
  tmux_agent.py read   NAME [--lines 200]
  tmux_agent.py wait   NAME "regex" [--timeout 30] [--fixed]   exit 0 on match, 1 on timeout
  tmux_agent.py run    NAME "command" [--timeout 600]          run a shell command, wait, print output and exit code
  tmux_agent.py ls
  tmux_agent.py kill   NAME | --all                  (--all: every session on THIS project's socket)
  tmux_agent.py socket                              print the socket path

Socket: $TMUX_AGENT_SOCKET if set (set it to share one socket on purpose), else
<tmp dir>/tmux-agent-<uid>/<project>-<hash>.sock, where the project is the git
top-level of the current directory (or the directory itself outside a repo).
Watch along as a human:  tmux -S <socket> attach -t NAME   (detach: Ctrl-b d)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def project_root() -> str:
    """The git top-level of the current directory, or the directory itself outside a repo."""
    cwd = os.getcwd()
    try:
        res = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return os.path.realpath(res.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return os.path.realpath(cwd)


def socket_path() -> str:
    env = os.environ.get("TMUX_AGENT_SOCKET")
    if env:
        return env
    uid = os.getuid() if hasattr(os, "getuid") else "user"
    d = os.path.join(tempfile.gettempdir(), f"tmux-agent-{uid}")
    os.makedirs(d, mode=0o700, exist_ok=True)
    root = project_root()
    slug = re.sub(r"[^A-Za-z0-9_-]", "", os.path.basename(root))[:12] or "root"
    # Keep the name short: a Unix socket path is limited to about 104 bytes on macOS.
    return os.path.join(d, f"{slug}-{hashlib.sha1(root.encode()).hexdigest()[:10]}.sock")


def tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    exe = shutil.which("tmux")
    if not exe:
        sys.exit("tmux_agent: tmux is not installed (macOS: brew install tmux; Ubuntu: sudo apt install tmux; Windows: use WSL)")
    return subprocess.run([exe, "-S", socket_path(), *args], capture_output=True, text=True, check=check)


def target(name: str) -> str:
    return f"{name}:0.0"


def capture(name: str, lines: int = 200) -> str:
    res = tmux("capture-pane", "-p", "-J", "-t", target(name), "-S", f"-{lines}")
    return res.stdout


def wait_for(name: str, pattern: str, timeout: float = 30.0, fixed: bool = False,
             interval: float = 0.5, lines: int = 1000, reader=capture) -> bool:
    rx = re.compile(re.escape(pattern) if fixed else pattern, re.MULTILINE)
    deadline = time.monotonic() + timeout
    while True:
        if rx.search(reader(name, lines)):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def send_text(name: str, text: str, enter: bool = True, delay: float = 0.3) -> None:
    # -l sends the text literally (no key-name parsing). Enter goes in a SEPARATE call after a
    # short pause: full-screen apps (Claude Code, Codex, other TUIs) may treat text+Enter that
    # arrive together as a paste and not submit it.
    tmux("send-keys", "-t", target(name), "-l", "--", text)
    if enter:
        time.sleep(delay)
        tmux("send-keys", "-t", target(name), "Enter")


def run_command(name: str, command: str, timeout: float) -> tuple[int | None, str]:
    """Run a shell command in the pane and return (exit_code or None on timeout, output)."""
    tag = uuid.uuid4().hex[:8]
    begin, end = f"__BEGIN_{tag}__", f"__END_{tag}__"
    send_text(name, f"echo {begin}; {command}; echo {end}=$?")
    if not wait_for(name, rf"^{end}=\d+", timeout=timeout, lines=5000):
        return None, capture(name, 5000)
    text = capture(name, 5000)
    start = text.rfind(begin + "\n")
    out = text[start + len(begin) + 1:] if start >= 0 else text
    m = re.search(rf"^{end}=(\d+)", out, re.MULTILINE)
    code = int(m.group(1)) if m else None
    body = out[: m.start()] if m else out
    return code, body.rstrip("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Drive interactive CLIs through tmux on a private socket.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("name"); s.add_argument("--cwd", default=None)
    s.add_argument("--cmd", dest="launch", default=None, help="program to launch in the pane")
    s.add_argument("--width", type=int, default=200); s.add_argument("--height", type=int, default=50)
    se = sub.add_parser("send"); se.add_argument("name"); se.add_argument("text")
    se.add_argument("--no-enter", action="store_true"); se.add_argument("--delay", type=float, default=0.3)
    k = sub.add_parser("keys"); k.add_argument("name"); k.add_argument("keys", nargs="+")
    r = sub.add_parser("read"); r.add_argument("name"); r.add_argument("--lines", type=int, default=200)
    w = sub.add_parser("wait"); w.add_argument("name"); w.add_argument("pattern")
    w.add_argument("--timeout", type=float, default=30.0); w.add_argument("--fixed", action="store_true")
    ru = sub.add_parser("run"); ru.add_argument("name"); ru.add_argument("command")
    ru.add_argument("--timeout", type=float, default=600.0)
    sub.add_parser("ls")
    sub.add_parser("socket")
    kl = sub.add_parser("kill"); kl.add_argument("name", nargs="?"); kl.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    sock = socket_path()

    if a.cmd == "start":
        args = ["new-session", "-d", "-s", a.name, "-x", str(a.width), "-y", str(a.height)]
        if a.cwd:
            args += ["-c", a.cwd]
        res = tmux(*args, check=False)
        if res.returncode != 0:
            print(res.stderr.strip(), file=sys.stderr)
            return 1
        if a.launch:
            send_text(a.name, a.launch)
        print(f"started {a.name}\n  socket: {sock}\n  watch: tmux -S {sock} attach -t {a.name}\n"
              f"  read:  tmux -S {sock} capture-pane -p -J -t {a.name}:0.0 -S -200")
        return 0
    if a.cmd == "send":
        send_text(a.name, a.text, enter=not a.no_enter, delay=a.delay)
        return 0
    if a.cmd == "keys":
        tmux("send-keys", "-t", target(a.name), *a.keys)
        return 0
    if a.cmd == "read":
        sys.stdout.write(capture(a.name, a.lines))
        return 0
    if a.cmd == "wait":
        ok = wait_for(a.name, a.pattern, timeout=a.timeout, fixed=a.fixed)
        if not ok:
            print(f"timeout after {a.timeout}s waiting for {a.pattern!r}; last output:", file=sys.stderr)
            sys.stderr.write(capture(a.name, 30))
        return 0 if ok else 1
    if a.cmd == "run":
        code, out = run_command(a.name, a.command, a.timeout)
        print(out)
        if code is None:
            print(f"timeout after {a.timeout}s (the command may still be running; send C-c with `keys`)", file=sys.stderr)
            return 124
        return code
    if a.cmd == "ls":
        res = tmux("list-sessions", "-F", "#{session_name}\t#{session_windows} windows\tcreated #{t:session_created}", check=False)
        print(res.stdout.strip() or "(no sessions)")
        print(f"socket: {sock}", file=sys.stderr)
        return 0
    if a.cmd == "socket":
        print(sock)
        return 0
    if a.cmd == "kill":
        if a.all:
            tmux("kill-server", check=False)  # only this socket's server: this project's sessions
            return 0
        if not a.name:
            print("kill needs a NAME or --all", file=sys.stderr)
            return 2
        res = tmux("kill-session", "-t", a.name, check=False)
        return 0 if res.returncode == 0 else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
