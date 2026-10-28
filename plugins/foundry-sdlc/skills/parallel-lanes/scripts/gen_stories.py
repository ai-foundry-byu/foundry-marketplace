#!/usr/bin/env python3
"""Compile the user stories written inside PRD.md into stories.json.

The PRD is the single source of truth for every story. stories.json is a
build artifact that testers, verifiers and CI read. Never hand-edit a story's
title or acceptance criteria in stories.json: edit the PRD and regenerate.

    python3 gen_stories.py                  # PRD.md -> stories.json (in the current dir)
    python3 gen_stories.py --check          # exit 1 if stories.json is stale or invalid
    python3 gen_stories.py --prd docs/PRD.md --out docs/stories.json

Story format inside PRD.md (everything before the first "## Appendix" heading):

    **US-01. A student signs in with a magic link.** (R-01, R-04)
    Surfaces: /login, /dashboard
    Devices: phone-390x844, desktop-1440x900
    Waits on: R-03
    1. The login page shows one email field and one button.
    2. Submitting a valid email shows "Check your inbox" within 2 s.
       - The button is disabled while the request is in flight.
    3. The link signs the student in and lands on /dashboard.

Rules:
  * A story starts at a bold heading "**<ID>. <Title>.**". IDs look like US-01,
    US-12a or AUTH-3 (letters, a dash, a number, optional letter suffix).
  * An optional "(R-01, R-04)" right after the heading lists the asks the story
    covers; it becomes the "covers" field.
  * Numbered lines are acceptance criteria. Indented "-" or "1." lines continue
    the criterion above them. Top-level "-" bullets also count as criteria.
  * Optional "Surfaces:", "Devices:", "Waits on:" lines (comma separated) set
    those fields. When a line is absent the value already in stories.json is
    kept, else a default is used.
  * A story ends at the next heading, table, horizontal rule or bold line.

What a regenerate preserves from the existing stories.json:
  * status (NOT_BUILT | BUILT | PARTIAL | LIVE | PARKED). New stories start NOT_BUILT.
  * surfaces / devices / waits_on, unless the PRD sets them.
  * any extra keys you added to an entry (for example "notes" or "evidence").

Exit codes: 0 ok, 1 stale or invalid (the reason is printed), 2 usage error.
Python 3.8+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

STATUSES = ("NOT_BUILT", "BUILT", "PARTIAL", "LIVE", "PARKED")
DEFAULT_DEVICES = ["phone-390x844", "desktop-1440x900"]
KEY_ORDER = ("id", "title", "acceptance", "surfaces", "devices", "status", "waits_on", "covers")

HEAD = re.compile(r"^\*\*([A-Z][A-Z0-9]*-\d+[a-z]?)\.\s+(.+?)\*\*\s*(.*)$")
NUM = re.compile(r"^(\d+)[.)]\s+(.*)$")
SUB = re.compile(r"^\s+(?:[-*]|\d+[.)])\s+(.*)$")
TOP_BULLET = re.compile(r"^[-*]\s+(.*)$")
META = re.compile(r"^(Surfaces|Devices|Waits on)\s*:\s*(.*)$", re.IGNORECASE)
META_KEYS = {"surfaces": "surfaces", "devices": "devices", "waits on": "waits_on"}
COVERS = re.compile(r"^\(([^)]*)\)\s*(.*)$")
REQ_ID = re.compile(r"\b[A-Z]{1,4}-\d+[a-z]?\b")


def clean(text: str) -> str:
    """Strip markdown emphasis and code ticks, drop struck-out text, collapse spaces."""
    text = re.sub(r"~~[^~]*~~\s*", "", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def split_list(value: str) -> list:
    value = clean(value)
    if value.lower() in ("", "-", "none", "n/a"):
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_prd(text: str) -> list:
    """Return a list of parsed stories: id, title, acceptance, and any PRD meta."""
    stories, cur = [], None
    for line in text.splitlines():
        if line.startswith("## Appendix"):
            break
        head = HEAD.match(line)
        if head:
            cur = {"id": head.group(1), "title": clean(head.group(2)).rstrip(".:"),
                   "acceptance": [], "meta": {}, "covers": []}
            lead = clean(head.group(3))
            cov = COVERS.match(lead)
            if cov:  # "(R-01, R-02)" right after the heading = the asks this story covers
                cur["covers"] = REQ_ID.findall(cov.group(1))
                lead = cov.group(2).strip()
            if lead:
                cur["acceptance"].append(lead)
            stories.append(cur)
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith(("#", "---", "|", "**")):
            cur = None
            continue
        meta = META.match(stripped)
        if meta and not line.startswith((" ", "\t")):
            cur["meta"][META_KEYS[meta.group(1).lower()]] = split_list(meta.group(2))
            continue
        num = NUM.match(line)
        sub = SUB.match(line)
        top = TOP_BULLET.match(line)
        if num:
            cur["acceptance"].append(clean(num.group(2)))
        elif sub and cur["acceptance"]:
            prev = cur["acceptance"][-1]
            sep = " " if prev.endswith((":", ";", ".")) else "; "
            cur["acceptance"][-1] = prev + sep + clean(sub.group(1))
        elif top:
            cur["acceptance"].append(clean(top.group(1)))
        elif cur["acceptance"] and line.startswith((" ", "\t")):
            # wrapped continuation line of the previous criterion
            cur["acceptance"][-1] += " " + clean(stripped)
    return stories


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}")
    if not isinstance(rows, list):
        raise ValueError(f"{path} must hold a JSON array of stories")
    return {r["id"]: r for r in rows if isinstance(r, dict) and "id" in r}


def build(prd_text: str, existing: dict) -> tuple:
    """Merge parsed PRD stories with existing rows. Returns (rows, errors, notes)."""
    parsed = parse_prd(prd_text)
    errors, notes = [], []
    ids = [s["id"] for s in parsed]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        errors.append(f"duplicate story ids in the PRD: {', '.join(dups)}")
    if not parsed:
        errors.append("no stories found: expected headings like **US-01. Title.**")
    rows = []
    for s in parsed:
        if not s["acceptance"]:
            errors.append(f"{s['id']} has no acceptance criteria")
        old = existing.get(s["id"], {})
        status = old.get("status", "NOT_BUILT")
        if status not in STATUSES:
            errors.append(f"{s['id']} has unknown status {status!r} in stories.json "
                          f"(allowed: {', '.join(STATUSES)})")
        row = {
            "id": s["id"],
            "title": s["title"],
            "acceptance": s["acceptance"],
            "surfaces": s["meta"].get("surfaces", old.get("surfaces", [])),
            "devices": s["meta"].get("devices", old.get("devices", list(DEFAULT_DEVICES))),
            "status": status,
            "waits_on": s["meta"].get("waits_on", old.get("waits_on", [])),
        }
        if s["covers"]:
            row["covers"] = s["covers"]
        for key, value in old.items():  # keep hand-added keys, after the core ones
            if key not in KEY_ORDER:
                row[key] = value
        rows.append(row)
    dropped = sorted(set(existing) - set(ids))
    if dropped:
        notes.append(f"dropped (no longer in the PRD): {', '.join(dropped)}. "
                     "Use status PARKED in stories.json instead of deleting a story you may revive.")
    return rows, errors, notes


def render(rows: list) -> str:
    return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"


def summary(rows: list) -> str:
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    parts = [f"{k} {counts[k]}" for k in STATUSES if k in counts]
    return f"{len(rows)} stories ({', '.join(parts)})"


def check(prd: Path, out: Path) -> tuple:
    """Return (ok, messages) without writing anything."""
    existing = load_existing(out)
    rows, errors, notes = build(prd.read_text(encoding="utf-8"), existing)
    if errors:
        return False, errors
    if not out.exists():
        return False, [f"{out} does not exist: run gen_stories.py"]
    if out.read_text(encoding="utf-8") != render(rows):
        return False, [f"{out} is STALE: regenerate with gen_stories.py"] + notes
    return True, [f"{out} up to date: {summary(rows)}"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compile PRD.md user stories into stories.json")
    ap.add_argument("--prd", default="PRD.md", help="path to the PRD (default PRD.md)")
    ap.add_argument("--out", default="stories.json", help="output path (default stories.json)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if stories.json is stale or a story is invalid; write nothing")
    args = ap.parse_args(argv)
    prd, out = Path(args.prd), Path(args.out)
    if not prd.exists():
        print(f"error: {prd} not found", file=sys.stderr)
        return 2
    try:
        if args.check:
            ok, msgs = check(prd, out)
            for m in msgs:
                print(m if ok else f"error: {m}", file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        rows, errors, notes = build(prd.read_text(encoding="utf-8"), load_existing(out))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print("stories.json NOT written", file=sys.stderr)
        return 1
    out.write_text(render(rows), encoding="utf-8")
    for n in notes:
        print(f"note: {n}")
    print(f"{summary(rows)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
