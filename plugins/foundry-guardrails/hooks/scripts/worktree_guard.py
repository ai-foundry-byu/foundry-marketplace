#!/usr/bin/env python3
"""worktree-guard: PreToolUse(Edit|Write|MultiEdit|NotebookEdit) hook.

When a session runs inside a LINKED git worktree (git worktree add, or Claude
Code's own worktrees), an edit through an absolute path can land in the MAIN
checkout instead of the worktree. That silently changes another session's
working tree. This hook denies exactly that case:

  * cwd is not in a git repo, or is the main checkout: no-op.
  * target is inside the current worktree: allow.
  * target is inside the main checkout and not inside any linked worktree:
    DENY, and name the equivalent path inside the current worktree.
  * anything else (/tmp, another repo, another worktree): allow.

Disable: FOUNDRY_WORKTREE_GUARD=0
Warn instead of deny: FOUNDRY_WORKTREE_GUARD_WARN=1
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "worktree-guard"
TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _abs(cwd: str, p: str) -> str:
    return c.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))


def worktree_layout(cwd: str) -> dict | None:
    """Return {"current": toplevel, "main": main_root, "linked": [paths]} or None.

    None means "not in a linked worktree" (or git is unavailable): the guard
    does nothing.
    """
    out = c.git(cwd, "rev-parse", "--git-dir", "--git-common-dir", "--show-toplevel")
    if out is None or out.returncode != 0:
        return None
    lines = out.stdout.strip().splitlines()
    if len(lines) < 3:
        return None
    git_dir, common_dir, top = (_abs(cwd, x) for x in lines[:3])
    if git_dir == common_dir:
        return None  # main checkout
    wl = c.git(cwd, "worktree", "list", "--porcelain")
    if wl is None or wl.returncode != 0:
        return None
    entries, cur = [], {}
    for line in wl.stdout.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": c.realpath(line[len("worktree "):])}
        elif line.strip() == "bare":
            cur["bare"] = True
    if cur:
        entries.append(cur)
    if not entries or entries[0].get("bare"):
        return None  # bare repo: there is no main working tree to protect
    return {"current": top, "main": entries[0]["path"],
            "linked": [e["path"] for e in entries[1:]]}


def evaluate(cwd: str, target: str) -> str | None:
    """Return a deny reason, or None to allow."""
    layout = worktree_layout(cwd)
    if not layout:
        return None
    t = _abs(cwd, target)
    if c.is_inside(t, layout["current"]):
        return None
    if not c.is_inside(t, layout["main"]):
        return None
    if any(c.is_inside(t, wt) for wt in layout["linked"]):
        return None
    rel = os.path.relpath(t, layout["main"])
    suggestion = os.path.join(layout["current"], rel)
    return (f"{t} is in the main checkout ({layout['main']}), but this session works in the "
            f"worktree {layout['current']}. Editing the main checkout changes files under "
            f"another session's feet. Edit the same file inside your worktree instead: {suggestion}")


def handle(event: dict) -> None:
    if c.disabled("WORKTREE_GUARD"):
        return
    if event.get("tool_name") not in TOOLS:
        return
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    target = tin.get("file_path") or tin.get("notebook_path")
    if not isinstance(target, str) or not target:
        return
    cwd = event.get("cwd") or os.getcwd()
    reason = evaluate(cwd, target)
    if not reason:
        return
    if c.env_flag("FOUNDRY_WORKTREE_GUARD_WARN"):
        c.emit_warn(HOOK, event, reason, target=target)
    else:
        c.emit_deny(HOOK, event, reason, target=target)


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
