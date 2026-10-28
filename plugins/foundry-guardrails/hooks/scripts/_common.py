"""Shared helpers for the foundry-guardrails hooks.

Python 3 standard library only. Every hook imports this module, so it must
never raise on ordinary input: each public helper swallows its own errors.

Hook IO contract (Claude Code docs, hooks reference):
  * stdin: one JSON object with session_id, cwd, hook_event_name, and for
    PreToolUse also tool_name / tool_input, for Stop also stop_hook_active.
  * PreToolUse allow: print nothing, exit 0.
  * PreToolUse deny: print {"hookSpecificOutput": {"hookEventName":
    "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
    "..."}} and exit 0.
  * Stop "keep working": print {"hookSpecificOutput": {"hookEventName": "Stop",
    "additionalContext": "..."}} and exit 0. This is the documented non-error
    path: Claude Code labels it "Stop hook feedback" and keeps the same loop
    protections as decision:block (stop_hook_active, the 8-continuation cap),
    while decision:block is labeled "Stop hook error occurred".
  * Message for the human only: {"systemMessage": "..."}. Nothing goes to stderr.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Iterable

PLUGIN = "foundry-guardrails"


# --------------------------------------------------------------------------
# Environment switches
# --------------------------------------------------------------------------

def disabled(name: str) -> bool:
    """True when FOUNDRY_<NAME>=0 or the global FOUNDRY_GUARDRAILS=0 is set."""
    if os.environ.get("FOUNDRY_GUARDRAILS", "").strip() == "0":
        return True
    return os.environ.get(f"FOUNDRY_{name}", "").strip() == "0"


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# --------------------------------------------------------------------------
# State and logging
# --------------------------------------------------------------------------

def state_dir() -> str:
    """Where per-session markers live.

    Order: FOUNDRY_GUARDRAILS_STATE_DIR, then ${CLAUDE_PLUGIN_DATA}/state
    (persists across plugin updates), then ${TMPDIR}/foundry-guardrails.
    """
    override = os.environ.get("FOUNDRY_GUARDRAILS_STATE_DIR")
    if override:
        base = override
    elif os.environ.get("CLAUDE_PLUGIN_DATA"):
        base = os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "state")
    else:
        base = os.path.join(tempfile.gettempdir(), PLUGIN)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return base


def log_path() -> str:
    return os.environ.get("FOUNDRY_GUARDRAILS_LOG") or os.path.join(
        state_dir(), "guardrails.log"
    )


def log(hook: str, action: str, session: str = "", **detail) -> None:
    """Append one JSON line to the guardrails log. Never raises."""
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hook": hook,
            "action": action,
            "session": session,
        }
        rec.update({k: (v[:300] if isinstance(v, str) else v) for k, v in detail.items()})
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def safe_session(event: dict) -> str:
    sid = str(event.get("session_id") or "unknown")
    return re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:64] or "unknown"


def marker(session: str, name: str) -> str:
    return os.path.join(state_dir(), f"{name}-{session}")


def touch(path: str, text: str = "") -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text or str(time.time()))
    except OSError:
        pass


def remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def read_int(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


# --------------------------------------------------------------------------
# Input and output
# --------------------------------------------------------------------------

def read_event() -> dict | None:
    """Parse the hook event from stdin. None on malformed input (fail open)."""
    try:
        # Claude Code writes UTF-8. Decode the bytes ourselves: sys.stdin uses the locale
        # encoding (cp1252 on Windows, ascii under some locales), which raised on non-ASCII
        # text and made every guard fail open on a command such as  rm -rf / # Őrs
        buf = getattr(sys.stdin, "buffer", None)
        raw = buf.read().decode("utf-8", errors="replace") if buf is not None else sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def emit_deny(hook: str, event: dict, reason: str, **detail) -> None:
    msg = f"[{PLUGIN}/{hook}] {reason}"
    log(hook, "deny", safe_session(event), tool=event.get("tool_name", ""), reason=reason, **detail)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        }
    }))


def emit_warn(hook: str, event: dict, text: str, **detail) -> None:
    """Allow the call but put a warning in Claude's context."""
    log(hook, "warn", safe_session(event), tool=event.get("tool_name", ""), reason=text, **detail)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": f"[{PLUGIN}/{hook}] warning: {text}",
        }
    }))


def emit_stop_block(hook: str, event: dict, reason: str, **detail) -> None:
    """Keep Claude working, through the non-error Stop feedback path."""
    log(hook, "block-stop", safe_session(event), reason=reason, **detail)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": f"[{PLUGIN}/{hook}] {reason}",
    }}))


def emit_user_message(hook: str, text: str) -> None:
    """Show a line to the human (not an error, not a block)."""
    print(json.dumps({"systemMessage": f"[{PLUGIN}/{hook}] {text}"}))


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: str, data) -> None:
    """Atomic write; never raises."""
    try:
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def blob_hash(path: str) -> str:
    """git's blob id for a file's bytes (so it compares with ls-tree output), "-" if absent."""
    import hashlib
    try:
        if not os.path.isfile(path):
            return "-"  # a FIFO or device named like source would block the read
        h = hashlib.sha1(b"blob %d\0" % os.path.getsize(path))
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):  # a big dump.sql stays out of memory
                h.update(chunk)
    except OSError:
        return "-"
    return h.hexdigest()


def run_hook(hook: str, fn) -> None:
    """Run fn(event) and exit 0 no matter what. A crashing guard fails open."""
    try:
        event = read_event()
        if event is not None:
            fn(event)
    except Exception as exc:  # noqa: BLE001 - fail open by design
        log(hook, "error-fail-open", error=repr(exc))
    sys.exit(0)


# --------------------------------------------------------------------------
# Shell command normalization
# --------------------------------------------------------------------------

_PREFIX_CMDS = {"sudo", "doas", "command", "builtin", "exec", "nohup", "time",
                "nice", "ionice", "timeout", "stdbuf", "caffeinate", "xargs"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_top_level(cmd: str) -> list[list[str]]:
    """Split a command string into pipelines, each a list of stage strings.

    Quote and backslash aware. Pipelines are separated by ; && || & and
    newlines; stages within a pipeline by a single |.
    """
    pipelines: list[list[str]] = []
    stages: list[str] = []
    buf: list[str] = []
    quote = ""
    i, n = 0, len(cmd)

    def flush_stage():
        s = "".join(buf).strip()
        buf.clear()
        if s:
            stages.append(s)

    def flush_pipeline():
        flush_stage()
        if stages:
            pipelines.append(stages.copy())
        stages.clear()

    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(cmd[i + 1])
            i += 2
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        two = cmd[i:i + 2]
        if two in ("&&", "||"):
            flush_pipeline()
            i += 2
            continue
        if c in (";", "\n"):
            flush_pipeline()
            i += 1
            continue
        if c == "&":
            # "2>&1" and "&>" are redirections, not separators
            prev = cmd[i - 1] if i else ""
            nxt = cmd[i + 1] if i + 1 < n else ""
            if prev in (">", "<") or nxt == ">":
                buf.append(c)
                i += 1
                continue
            flush_pipeline()
            i += 1
            continue
        if c == "|":
            if cmd[i + 1:i + 2] == "&":
                i += 1
            flush_stage()
            i += 1
            continue
        buf.append(c)
        i += 1
    flush_pipeline()
    return pipelines


def tokenize(stage: str) -> list[str]:
    try:
        return shlex.split(stage, comments=False, posix=True)
    except ValueError:
        return stage.split()


def strip_prefixes(argv: list[str]) -> list[str]:
    """Drop VAR=val assignments and wrappers like sudo, env, nohup, timeout."""
    out = list(argv)
    for _ in range(12):
        if not out:
            return out
        head = os.path.basename(out[0])
        if _ASSIGN.match(out[0]):
            out = out[1:]
            continue
        if head == "env":
            rest = out[1:]
            while rest and (rest[0].startswith("-") or _ASSIGN.match(rest[0])):
                if rest[0] in ("-u", "--unset", "-C", "--chdir", "-S") and len(rest) > 1:
                    rest = rest[2:]
                else:
                    rest = rest[1:]
            if not rest:
                return ["env"]  # bare env dumps the environment; keep it visible
            out = rest
            continue
        if head in _PREFIX_CMDS:
            rest = out[1:]
            while rest and rest[0].startswith("-"):
                flag = rest[0]
                takes_value = head in ("sudo", "doas") and flag in ("-u", "-g", "-C", "-h", "-p", "-U")
                takes_value = takes_value or (head == "nice" and flag == "-n")
                takes_value = takes_value or (head == "xargs" and flag in ("-I", "-n", "-P", "-L", "-d", "-E"))
                rest = rest[2:] if takes_value and len(rest) > 1 else rest[1:]
            if head == "timeout" and rest and re.match(r"^\d+[smhd]?$", rest[0]):
                rest = rest[1:]
            if head == "nice" and rest and re.match(r"^-?\d+$", rest[0]):
                rest = rest[1:]
            if not rest:
                return [head]
            out = rest
            continue
        break
    return out


# $(...), `...` and process substitution <(...) / >(...): each runs a command whose output
# lands in the transcript (diff <(cat .env) /dev/null printed the file).
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`|[<>]\(([^()]*)\)")


def strip_grouping(argv: list[str]) -> list[str]:
    """Drop subshell and group syntax around a command: "(rm" -> "rm", ".env)" -> ".env",
    "{" / "}" / "!" tokens. Without this, (cd /tmp && rm -rf ~), { cat .env; } and
    (git push) had heads "(cd", "{" and "(git", and every guard let them through."""
    out = list(argv)
    while out and out[0] in ("(", "{", "!"):
        out = out[1:]
    if out and out[0].startswith("(") and not out[0].startswith("(("):  # (( )) is arithmetic
        out[0] = out[0].lstrip("(")
    while out and out[-1] in (")", "}", ";"):
        out = out[:-1]
    if out:
        last = out[-1]
        extra = last.count(")") - last.count("(")
        while extra > 0 and last.endswith(")"):
            last, extra = last[:-1], extra - 1
        out[-1] = last
    return [t for t in out if t]


def command_stages(cmd: str, _depth: int = 0) -> list[list[list[str]]]:
    """Normalize a Bash command into pipelines of argv lists.

    Unwraps `bash -c '...'`, `sh -c`, `eval '...'`, $(...) / backticks and <(...) so
    a wrapper cannot hide the real command. Depth limited.
    """
    if not isinstance(cmd, str) or not cmd.strip():
        return []
    result: list[list[list[str]]] = []
    for pipeline in split_top_level(cmd):
        argvs: list[list[str]] = []
        for stage in pipeline:
            argv = strip_prefixes(strip_grouping(tokenize(stage)))
            if not argv:
                continue
            head = os.path.basename(argv[0])
            inner = None
            if head in _SHELLS and _depth < 4:
                for j, tok in enumerate(argv[1:], start=1):
                    if re.match(r"^-[a-zA-Z]*c[a-zA-Z]*$", tok) and j + 1 < len(argv):
                        inner = argv[j + 1]
                        break
            elif head == "eval" and _depth < 4 and len(argv) > 1:
                inner = " ".join(argv[1:])
            if inner is not None:
                result.extend(command_stages(inner, _depth + 1))
                continue
            argvs.append(argv)
        if argvs:
            result.append(argvs)
    if _depth < 4:
        for m in _SUBST.finditer(cmd):
            inner = next((g for g in m.groups() if g is not None), "")
            if inner and inner.strip():
                result.extend(command_stages(inner, _depth + 1))
    return result


def all_argvs(cmd: str) -> list[list[str]]:
    return [argv for pipeline in command_stages(cmd) for argv in pipeline]


def git(cwd: str, *args: str, timeout: float = 5.0) -> subprocess.CompletedProcess | None:
    """Run a read-only git command. None when git is missing or errors out."""
    try:
        return subprocess.run(["git", *args], cwd=cwd or None, capture_output=True,
                              text=True, timeout=timeout)
    except Exception:
        return None


def realpath(p: str) -> str:
    try:
        return os.path.realpath(os.path.abspath(os.path.expanduser(p)))
    except Exception:
        return os.path.abspath(p)


def is_inside(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def first(items: Iterable, default=None):
    for x in items:
        return x
    return default
