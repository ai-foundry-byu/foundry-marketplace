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

Subagent lanes. A subagent started with the Agent tool and no isolation runs with the
parent's cwd, the main checkout, so the rule above never fires for it. Its tool calls carry
agent_id in the hook input (the parent's own calls do not). When such a call edits the main
checkout and the lane registry <git common dir>/foundry-lanes.json says lanes are active
({"active": true, "lanes": [{"id", "tasks", "branch", "worktree"}]}, written by the
foundry-sdlc parallel-lanes skill), the edit is denied unless the target is inside a
registered lane worktree, a linked worktree, or .claude/worktrees/. Lanes whose "worktree"
is still null (the skill writes the registry before launch) count as active. The repo is
found from cwd, else from the target (a session started in the folder above the repo). A
"worktree" at or above the main checkout ("." or "~") is ignored. No registry, an inactive
or unreadable one, or no lanes: nothing changes, so ordinary subagents are not affected.

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


def _case_insensitive(path: str) -> bool:
    """True when the volume holding path ignores case (macOS and Windows defaults)."""
    alt = path.swapcase()
    try:
        return alt != path and os.path.exists(alt) and os.path.samefile(path, alt)
    except OSError:
        return False


def _inside(child: str, parent: str) -> bool:
    """c.is_inside, and on a case-insensitive volume also when only the case differs:
    realpath keeps the case as typed, so /Users/me/APP/src/a.py missed /Users/me/app."""
    if c.is_inside(child, parent):
        return True
    if not c.is_inside(child.casefold(), parent.casefold()):
        return False
    return _case_insensitive(parent)


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


REGISTRY = "foundry-lanes.json"


def _git_dirs(cwd: str) -> tuple[str, str, str] | None:
    out = c.git(cwd, "rev-parse", "--git-dir", "--git-common-dir", "--show-toplevel")
    if out is None or out.returncode != 0:
        return None
    lines = out.stdout.strip().splitlines()
    if len(lines) < 3:
        return None
    git_dir, common_dir, top = (_abs(cwd, x) for x in lines[:3])
    return git_dir, common_dir, top


def active_lanes(common_dir: str, main: str) -> list[str] | None:
    """Worktree paths of the active lane registry, or None when no lanes are active.

    An active registry whose lanes have not reported a worktree yet (the parallel-lanes skill
    writes "worktree": null before launch) is still active: the list is then empty. A path at
    or above the main checkout ("." or "~") is not a lane worktree and is ignored, so it
    cannot switch the guard off for the whole checkout."""
    reg = c.read_json(os.path.join(common_dir, REGISTRY))
    if not isinstance(reg, dict) or reg.get("active") is not True:
        return None
    lanes = reg.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        return None
    paths = []
    for lane in lanes:
        wt = lane.get("worktree") if isinstance(lane, dict) else None
        if isinstance(wt, str) and wt.strip():
            wt = os.path.expanduser(wt.strip())
            p = c.realpath(wt if os.path.isabs(wt) else os.path.join(main, wt))
            if not _inside(main, p):
                paths.append(p)
    return paths


def _probe_dir(path: str) -> str:
    """The nearest existing directory at or above path, outside any .git directory."""
    parts = path.split(os.sep)
    if ".git" in parts:
        path = os.sep.join(parts[:parts.index(".git")]) or os.sep
    d = path
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return d


def evaluate_subagent(cwd: str, target: str) -> str | None:
    """A subagent call (hook input has agent_id) that edits a main checkout with active lanes.

    The repo is found from cwd and, failing that, from the target itself: a session started in
    the folder above the repo has a cwd that is not in git at all, and its subagents edit the
    main checkout by absolute path."""
    t = _abs(cwd, target)
    seen = set()
    for probe in (cwd, _probe_dir(t)):
        dirs = _git_dirs(probe)
        if not dirs or dirs in seen:
            continue
        seen.add(dirs)
        git_dir, common_dir, main = dirs
        if git_dir != common_dir:
            continue  # a linked worktree: evaluate() covers a cwd there, and a target there is a lane
        if not _inside(t, main):
            continue
        lanes = active_lanes(common_dir, main)
        if lanes is None:
            continue
        if _inside(t, os.path.join(main, ".claude", "worktrees")):
            return None
        if any(_inside(t, wt) for wt in lanes):
            return None
        wl = c.git(main, "worktree", "list", "--porcelain")
        if wl is not None and wl.returncode == 0:
            linked = [c.realpath(x[len("worktree "):]) for x in wl.stdout.splitlines()
                      if x.startswith("worktree ")][1:]
            if any(_inside(t, wt) for wt in linked):
                return None
        registry = os.path.join(common_dir, REGISTRY)
        where = (f"registered lanes: {', '.join(lanes)}" if lanes else
                 "no lane has registered its worktree yet")
        return (f"{t} is in the main checkout ({main}), and this edit comes from a subagent while "
                f"parallel lanes are active ({registry}). A lane subagent started without isolation "
                "runs in the main checkout, so its edits land under the integrator and the other "
                f"lanes. Edit only inside your lane worktree, by absolute path ({where}). If you are "
                'the integrator: launch each lane with the Agent tool option isolation: "worktree" '
                "(or as its own claude session started inside the lane worktree), and do "
                "main-checkout work yourself, not in a subagent. If every lane has been merged, the "
                f'integrator sets "active": false in {registry}; a subagent never edits that file.')
    return None


def evaluate(cwd: str, target: str) -> str | None:
    """Return a deny reason, or None to allow."""
    layout = worktree_layout(cwd)
    if not layout:
        return None
    t = _abs(cwd, target)
    if _inside(t, layout["current"]):
        return None
    if not _inside(t, layout["main"]):
        return None
    if any(_inside(t, wt) for wt in layout["linked"]):
        return None
    rel = os.path.relpath(t, layout["main"]) if c.is_inside(t, layout["main"]) else \
        os.path.relpath(t.casefold(), layout["main"].casefold())  # only the case differed
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
    if not reason and event.get("agent_id"):
        reason = evaluate_subagent(cwd, target)
    if not reason:
        return
    if c.env_flag("FOUNDRY_WORKTREE_GUARD_WARN"):
        c.emit_warn(HOOK, event, reason, target=target)
    else:
        c.emit_deny(HOOK, event, reason, target=target)


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
