#!/usr/bin/env python3
"""stale-write-guard: PreToolUse(Write) + PostToolUse(Edit|Write|MultiEdit) hook.

The Write tool replaces a whole file with what Claude holds in context. If the
file has uncommitted changes that Claude did not make (the human, a formatter,
another session), a whole-file Write silently loses them. This hook protects
exactly those changes:

  * PostToolUse after each Edit/Write/MultiEdit the session makes: record the
    file's content hash as "this session's own last write".
  * PreToolUse(Write) is allowed when the target is new, untracked, outside
    git, clean vs HEAD, identical to the new content, or still byte-identical
    to this session's own last write (the uncommitted changes are Claude's).
  * Otherwise the tracked file holds uncommitted changes this session did not
    make: DENY by default (a warning after the fact protects nothing, because
    the write has already happened). FOUNDRY_STALE_WRITE_ENFORCE=0 switches to
    warn-only. A Read does not lift the deny: use Edit, or commit/stash first.

Disable: FOUNDRY_STALE_WRITE_GUARD=0
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "stale-write-guard"
RECORD_TOOLS = {"Edit", "Write", "MultiEdit"}


def _abs(cwd: str, target: str) -> str:
    return c.realpath(target if os.path.isabs(target) else os.path.join(cwd, target))


def _record_path(sid: str) -> str:
    return c.marker(sid, "stale-own-writes") + ".json"


def record_own_write(sid: str, path: str) -> None:
    rec = c.read_json(_record_path(sid), {})
    if not isinstance(rec, dict):
        rec = {}
    rec[path] = c.blob_hash(path)
    if len(rec) > 2000:  # bound the file; oldest entries go first
        rec = dict(list(rec.items())[-2000:])
    c.write_json(_record_path(sid), rec)


def evaluate(cwd: str, target: str, content, sid: str = "") -> str | None:
    """Return a reason string when the Write would clobber uncommitted changes."""
    path = _abs(cwd, target)
    if not os.path.isfile(path):
        return None
    if isinstance(content, str):
        try:
            with open(path, encoding="utf-8") as fh:
                if fh.read() == content:
                    return None
        except (OSError, UnicodeDecodeError):
            pass
    repo_cwd = os.path.dirname(path)
    tracked = c.git(repo_cwd, "ls-files", "--error-unmatch", "--", path)
    if tracked is None or tracked.returncode != 0:
        return None
    diff = c.git(repo_cwd, "diff", "--quiet", "HEAD", "--", path)
    if diff is None or diff.returncode != 1:
        return None  # 0 = clean, anything else = cannot tell, fail open
    own = c.read_json(_record_path(sid), {}) if sid else {}
    if isinstance(own, dict) and own.get(path) and own[path] == c.blob_hash(path):
        return None  # the uncommitted changes are this session's own last write
    return (f"{path} has uncommitted changes that are not in HEAD and were not made by this "
            "session, and Write replaces the whole file, so those changes would be lost. A "
            "whole-file Write stays blocked while the file is dirty, even after a Read. Instead: "
            "Read the file and use Edit for a targeted change that keeps the uncommitted lines, "
            "or ask the user to commit or stash first. If the user explicitly wants the "
            "uncommitted changes discarded, say so in your reply and let them do it.")


def handle(event: dict) -> None:
    if c.disabled("STALE_WRITE_GUARD"):
        return
    tool = event.get("tool_name")
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    target = tin.get("file_path")
    if not isinstance(target, str) or not target:
        return
    cwd = event.get("cwd") or os.getcwd()
    sid = c.safe_session(event)
    if event.get("hook_event_name") == "PostToolUse":
        if tool in RECORD_TOOLS:
            record_own_write(sid, _abs(cwd, target))
        return
    if tool != "Write":
        return
    reason = evaluate(cwd, target, tin.get("content"), sid)
    if not reason:
        return
    if os.environ.get("FOUNDRY_STALE_WRITE_ENFORCE", "").strip() == "0":
        c.emit_warn(HOOK, event, reason, target=target)
    else:
        c.emit_deny(HOOK, event, reason, target=target)


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
