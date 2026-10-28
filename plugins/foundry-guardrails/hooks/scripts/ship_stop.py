#!/usr/bin/env python3
"""ship-stop: Stop hook that keeps Claude working until a milestone is checked off.

Armed only when FOUNDRY_SHIP_WORKPLAN points at a markdown workplan. Milestones
are checkbox lines whose first word is an id like M1, M3.2 or M10.1.4:

    - [ ] M3.2 Export endpoint returns CSV
      - acceptance: GET /export?fmt=csv returns 200 and a header row
    - [x] M3.1 Schema migration
    - [!] M3.3 Payment webhook (blocked: needs a sandbox key from a human)

Behavior on Stop:
  * FOUNDRY_SHIP_MILESTONE=M3.2 set: block while that milestone is "[ ]".
  * no milestone named: block while the first "[ ]" milestone is open.
  * "[x]" = done, "[!]" or "[-]" = blocked or deferred by a human or by
    Claude with a written reason: allow the stop.
  * After FOUNDRY_SHIP_MAX_BLOCKS blocks for one (session, milestone)
    (default 8), allow the stop, log it, and tell the human (systemMessage)
    that someone needs to look. The default is 8 because Claude Code ends the
    turn itself once Stop hooks have continued it 8 times in a row with no
    tool call in between (it overrides the 9th block; CLAUDE_CODE_STOP_HOOK_BLOCK_CAP
    raises that). A higher plugin cap would never be reached in that case and
    the "a human needs to look" message would never show.
  * Missing or unreadable workplan, unknown milestone id, background tasks in
    flight: allow.

Disable: FOUNDRY_SHIP_STOP=0, or unset FOUNDRY_SHIP_WORKPLAN.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "ship-stop"
DEFAULT_MAX_BLOCKS = 8
LINE = re.compile(r"^(\s*)[-*+]\s+\[([ xX!\-])\]\s+(M\d+(?:\.\d+)*)\b[:.)]?\s*(.*)$")


def parse_workplan(text: str) -> list[dict]:
    """Parse milestone checkboxes and the indented lines beneath each."""
    items: list[dict] = []
    cur = None
    for raw in text.splitlines():
        m = LINE.match(raw)
        if m:
            state = {" ": "open", "x": "done", "X": "done", "!": "blocked", "-": "blocked"}[m.group(2)]
            cur = {"id": m.group(3), "state": state, "title": m.group(4).strip(),
                   "indent": len(m.group(1)), "details": []}
            items.append(cur)
            continue
        if cur is not None:
            if raw.strip() == "":
                continue
            indent = len(raw) - len(raw.lstrip())
            if indent > cur["indent"] and not raw.lstrip().startswith("#"):
                cur["details"].append(raw.strip())
            else:
                cur = None
    return items


def pick(items: list[dict], wanted: str) -> dict | None:
    if wanted:
        for it in items:
            if it["id"] == wanted:
                return it
        return None
    for it in items:
        if it["state"] == "open":
            return it
    return None


def handle(event: dict) -> None:
    if c.disabled("SHIP_STOP"):
        return
    plan = os.environ.get("FOUNDRY_SHIP_WORKPLAN", "").strip()
    if not plan:
        return
    sid = c.safe_session(event)
    base = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    path = plan if os.path.isabs(plan) else os.path.join(base, plan)
    try:
        with open(path, encoding="utf-8") as fh:
            items = parse_workplan(fh.read())
    except OSError:
        c.log(HOOK, "allow-no-workplan", sid, path=path)
        return
    wanted = os.environ.get("FOUNDRY_SHIP_MILESTONE", "").strip()
    it = pick(items, wanted)
    if it is None:
        if wanted:
            c.log(HOOK, "allow-unknown-milestone", sid, milestone=wanted, path=path)
        return
    if it["state"] != "open":
        return
    if event.get("background_tasks"):
        c.log(HOOK, "allow-background-tasks", sid, milestone=it["id"])
        return
    counter = c.marker(sid, "ship-" + re.sub(r"[^A-Za-z0-9.]", "_", it["id"]))
    max_blocks = c.env_int("FOUNDRY_SHIP_MAX_BLOCKS", DEFAULT_MAX_BLOCKS)
    n = c.read_int(counter)
    if n >= max_blocks:
        c.log(HOOK, "allow-cap-reached", sid, milestone=it["id"], blocks=n)
        c.emit_user_message(HOOK, f"{it['id']} is still open after {n} continuations; "
                                  "a human needs to look at it.")
        return
    c.touch(counter, str(n + 1))
    details = "\n".join(it["details"])[:800]
    criteria = f" Acceptance notes from the workplan:\n{details}\n" if details else " "
    c.emit_stop_block(HOOK, event,
                      f"Milestone {it['id']} '{it['title']}' in {plan} is not checked off yet. "
                      f"Keep working on it.{criteria}Tick it ([x]) only after its acceptance "
                      "criteria are verified with evidence (tests run, output checked). If it is "
                      "truly blocked on something only a human can do, mark it [!] with the reason "
                      f"on the same line. (continuation {n + 1} of at most {max_blocks})",
                      milestone=it["id"])


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
