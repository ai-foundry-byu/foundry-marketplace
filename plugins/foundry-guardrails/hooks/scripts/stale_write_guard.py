#!/usr/bin/env python3
"""stale-write-guard: PreToolUse(Write) hook.

The Write tool replaces a whole file with what Claude holds in context. If the
file changed on disk since Claude last read it (another session, a formatter,
the human), those changes are silently lost. This hook flags a Write to a
git-tracked file whose working tree differs from HEAD:

  * new file, untracked file, file outside git, identical content, clean
    tracked file: allow silently.
  * tracked file with uncommitted changes: WARN by default (the call goes
    through, Claude gets a warning in context), DENY when
    FOUNDRY_STALE_WRITE_ENFORCE=1.

Disable: FOUNDRY_STALE_WRITE_GUARD=0
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "stale-write-guard"


def evaluate(cwd: str, target: str, content) -> str | None:
    """Return a reason string when the Write would clobber uncommitted changes."""
    path = c.realpath(target if os.path.isabs(target) else os.path.join(cwd, target))
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
    return (f"{path} has uncommitted changes that are not in HEAD, and Write replaces the whole "
            "file. If those changes are not in what you are writing, they will be lost. Read the "
            "file again now, then use Edit for a targeted change (or commit first).")


def handle(event: dict) -> None:
    if c.disabled("STALE_WRITE_GUARD"):
        return
    if event.get("tool_name") != "Write":
        return
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    target = tin.get("file_path")
    if not isinstance(target, str) or not target:
        return
    reason = evaluate(event.get("cwd") or os.getcwd(), target, tin.get("content"))
    if not reason:
        return
    if c.env_flag("FOUNDRY_STALE_WRITE_ENFORCE"):
        c.emit_deny(HOOK, event, reason, target=target)
    else:
        c.emit_warn(HOOK, event, reason, target=target)


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
