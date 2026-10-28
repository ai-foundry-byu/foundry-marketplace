#!/usr/bin/env python3
"""Tell an agent which SDLC stage a project is in, from the artifacts on disk.

    python3 sdlc_stage.py [PROJECT_DIR]          # human-readable report
    python3 sdlc_stage.py [PROJECT_DIR] --json   # machine-readable
    python3 sdlc_stage.py --hook                 # SessionStart hook mode (quiet, never fails)

The artifact set lives in PROJECT_DIR, or in PROJECT_DIR/product, or in
PROJECT_DIR/docs/product (searched in that order). The current stage is the
FIRST stage whose exit check fails. Unfilled template text is marked "TODO:";
a file that still contains "TODO:" does not count as done.

Stage exit checks (deterministic, file-based):
  0 Scaffold      README.md, CHANGELOG.md, REQUIREMENTS.md, DECISIONS.md, PRD.md, WORKPLAN.md exist
  1 Requirements  REQUIREMENTS.md has an R-01 style row, an "Already exists" section, no TODO:
  2 PRD           PRD.md has stories with criteria, no TODO:, an "Addressed critiques"
                  appendix with content, stories.json is fresh (gen_stories --check), every
                  R-id's Status is STORIED, LIVE or DROPPED citing a D-id, and DECISIONS.md
                  has the human's approval row:
                  | D-07 | 2026-11-02 | <who> | "<their words>" | PRD approved: ... | ... |
  3 Workplan      WORKPLAN.md has a task table and at least one "- [ ] M" milestone, no TODO:
  4 Execute       every task row's Status is PARKED, or DONE with evidence (a commit sha,
                  a PR "#12" or a URL): "DONE 2026-11-03: commit 3f2a9c1"
  5 Code QA       not detectable from files: CI is the evidence. Reported as a reminder.
  6 Visual QA     done-journey.yaml has steps and no TODO:; the done-gate report
                  (.qa/done-gate/last.json: sha, exit, journey, time) says exit 0 for git
                  HEAD (or for a commit whose only later changes are artifact files); and
                  every story that is not PARKED has a story-verifier report
                  (.qa/verify/<id>.md) or evidence in stories.json
  7 Ship          every story that is not PARKED is LIVE with evidence that names its
                  commit ("commit:<sha>", added by gen_stories.py --set), and CHANGELOG.md
                  has a dated entry
  8 Feedback      steady state: bugs become stories (see the bug-to-story skill)

Exit code is always 0 in report modes; this tool reports, it does not gate.
Python 3.8+ standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_stories  # noqa: E402

STAGES = [
    (0, "Scaffold", "new-project"),
    (1, "Gather requirements", "gather-requirements"),
    (2, "PRD + user stories", "write-prd (then the prd-critic agent)"),
    (3, "Workplan", "write-workplan"),
    (4, "Execute", "parallel-lanes"),
    (5, "Code QA", "foundry-qa:regression-check + your CI"),
    (6, "Visual QA with example users",
     "the stage-6 battery on the committed HEAD (local or hosted): foundry-qa:done-gate, "
     "foundry-qa persona-tester per device, story-verifier agent per story, "
     "foundry-design:design-critique, foundry-qa:a11y-check (the ship skill runs them in order)"),
    (7, "Ship", "ship"),
    (8, "Feedback", "bug-to-story"),
]
SCAFFOLD_FILES = ["README.md", "CHANGELOG.md", "REQUIREMENTS.md", "DECISIONS.md",
                  "PRD.md", "WORKPLAN.md"]
TODO = "TODO:"
REQ_ROW = re.compile(r"^\|\s*R-\d+\s*\|", re.MULTILINE)
TASK_HEADER = re.compile(r"^\|\s*Id\s*\|\s*Task\s*\|.*\|\s*Status\s*\|\s*$",
                         re.MULTILINE | re.IGNORECASE)
MILESTONE = re.compile(r"^- \[[ xX]\] M\d", re.MULTILINE)
DATED = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)
REQ_ID = re.compile(r"^\|\s*(R-\d+)\s*\|")
APPROVAL = re.compile(r"^\|\s*D-\d+\s*\|\s*\d{4}-\d{2}-\d{2}\s*\|.*\bPRD approved\b",
                      re.MULTILINE | re.IGNORECASE)
EVIDENCE = re.compile(r"\b[0-9a-f]{7,40}\b|#\d+|https?://")


def find_root(project: Path) -> Path:
    for cand in (project, project / "product", project / "docs" / "product"):
        if (cand / "PRD.md").exists() or (cand / "REQUIREMENTS.md").exists():
            return cand
    return project


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def task_statuses(workplan: str) -> list:
    """Return (id, status) for every row of every table whose header is Id | Task | ... | Status."""
    out, lines = [], workplan.splitlines()
    i = 0
    while i < len(lines):
        if TASK_HEADER.match(lines[i]):
            header = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
            col = header.index("status")
            i += 2  # skip the |---| row
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) > col and cells[0]:
                    out.append((cells[0], cells[col]))
                i += 1
            continue
        i += 1
    return out


def cells(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def requirement_statuses(req: str) -> list:
    """Return (R-id, status) per ask row. Status = the "Status" column, else the last cell."""
    out, col = [], None
    for line in req.splitlines():
        if not line.lstrip().startswith("|"):
            col = None
            continue
        row = cells(line)
        low = [c.lower() for c in row]
        if low and low[0] == "id" and "status" in low:
            col = low.index("status")
            continue
        m = REQ_ID.match(line.strip())
        if m:
            out.append((m.group(1), row[col] if col is not None and len(row) > col else row[-1]))
    return out


def covered(status: str) -> bool:
    s = status.strip().upper()
    return s.startswith(("STORIED", "LIVE")) or (s.startswith("DROPPED") and bool(re.search(r"\bD-\d+", s)))


def approved(decisions: str) -> bool:
    return any(TODO not in m.group(0) for m in
               re.finditer(APPROVAL.pattern + r".*$", decisions, re.MULTILINE | re.IGNORECASE))


def evaluate(project: Path) -> dict:
    root = find_root(project)
    checks = []  # (stage, ok, detail)

    missing = [f for f in SCAFFOLD_FILES if not (root / f).exists()]
    checks.append((0, not missing, "missing: " + ", ".join(missing) if missing else "artifact set present"))

    req = read(root / "REQUIREMENTS.md")
    problems = []
    if not REQ_ROW.search(req):
        problems.append("no R-01 style ask rows")
    if "## Already exists" not in req:
        problems.append('no "## Already exists" audit section')
    if TODO in req:
        problems.append("still has TODO: placeholders")
    checks.append((1, not problems, "; ".join(problems) or "asks, sources and audit recorded"))

    prd_path = root / "PRD.md"
    prd = read(prd_path)
    problems = []
    if TODO in prd:
        problems.append("still has TODO: placeholders")
    stories = gen_stories.parse_prd(prd)
    if not stories:
        problems.append("no **US-01. Title.** stories")
    elif any(not s["acceptance"] for s in stories):
        problems.append("a story has no acceptance criteria")
    m = re.search(r"^## Appendix A\. Addressed critiques\s*$(.*?)(?=^## |\Z)", prd,
                  re.MULTILINE | re.DOTALL)
    if not m or not re.search(r"^\s*[-|\d]", m.group(1), re.MULTILINE):
        problems.append("no filled \"## Appendix A. Addressed critiques\" (run the prd-critic agent)")
    if prd_path.exists() and stories:
        try:
            ok, msgs = gen_stories.check(prd_path, root / "stories.json")
        except ValueError as exc:
            ok, msgs = False, [str(exc)]
        if not ok:
            problems.append(msgs[0].replace(str(root) + os.sep, ""))
    uncovered = [rid for rid, status in requirement_statuses(req) if not covered(status)]
    if uncovered:
        problems.append(f"{', '.join(uncovered[:10])} not STORIED or DROPPED (D-id): "
                        "story it, or record a decision that drops it")
    if not approved(read(root / "DECISIONS.md")):
        problems.append('no human approval in DECISIONS.md (a dated D-row saying "PRD approved")')
    checks.append((2, not problems, "; ".join(problems) or
                   f"{len(stories)} stories, critiqued, stories.json fresh, every ask covered, approved"))

    wp = read(root / "WORKPLAN.md")
    tasks = task_statuses(wp)
    problems = []
    if not tasks:
        problems.append("no task table (| Id | Task | Owner | Deps | Status |)")
    if not MILESTONE.search(wp):
        problems.append("no \"- [ ] M1.1\" milestones")
    if TODO in wp:
        problems.append("still has TODO: placeholders")
    checks.append((3, not problems, "; ".join(problems) or f"{len(tasks)} tasks planned"))

    open_tasks = [t for t, s in tasks if not s.upper().startswith(("DONE", "PARKED"))]
    no_proof = [t for t, s in tasks if s.upper().startswith("DONE") and not EVIDENCE.search(s[4:])]
    problems = []
    if open_tasks:
        problems.append(f"open tasks: {', '.join(open_tasks[:12])}" + (" ..." if len(open_tasks) > 12 else ""))
    if no_proof:
        problems.append(f"DONE without evidence (add the commit sha): {', '.join(no_proof[:12])}")
    if not tasks:
        problems.append("no tasks yet")
    checks.append((4, not problems, "; ".join(problems) or "all tasks DONE (with evidence) or PARKED"))

    checks.append((5, True, "not file-detectable: a green CI run and per-change tests are the evidence"))

    journey = read(root / "done-journey.yaml")
    rows = []
    try:
        rows = gen_stories.load_stories(root / "stories.json")
    except ValueError:
        pass
    groot = gen_stories.git_root(root)
    problems = []
    if not journey:
        problems.append("no done-journey.yaml")
    else:
        if not re.search(r"^steps:", journey, re.MULTILINE):
            problems.append("done-journey.yaml has no steps:")
        if TODO in journey:
            problems.append("done-journey.yaml still has TODO: placeholders")
    if groot is None:
        problems.append("not a git repository: the build under test is a commit (git init, commit)")
    else:
        ok, gate_detail, _ = gen_stories.gate_passed(groot, root, (project, root))
        if not ok:
            problems.append(gate_detail)
        bases = {groot, Path(project).resolve(), root.resolve()}
        unverified = [r.get("id") for r in rows if r.get("status") != "PARKED" and not r.get("evidence")
                      and not any((b / ".qa" / "verify" / f"{r.get('id')}.md").is_file() for b in bases)]
        if unverified:
            problems.append(f"no story-verifier report (.qa/verify/<id>.md) for "
                            f"{', '.join(map(str, unverified[:10]))}")
    checks.append((6, not problems, "; ".join(problems) or
                   "done gate exit 0 on HEAD and every story verified (now mark LIVE or PARTIAL)"))

    not_live = [r.get("id") for r in rows if r.get("status") not in ("LIVE", "PARKED")]
    unproven = [r.get("id") for r in rows if r.get("status") == "LIVE"
                and not any(str(e).startswith("commit:") for e in (r.get("evidence") or []))]
    problems = []
    if not rows:
        problems.append("no stories in stories.json")
    if not_live:
        problems.append(f"{len(not_live)} stories not LIVE: {', '.join(map(str, not_live[:10]))}")
    if unproven:
        problems.append(f"LIVE with no evidence of its commit (set LIVE with gen_stories.py --set): "
                        f"{', '.join(map(str, unproven[:10]))}")
    changelog = re.sub(r"^```.*?^```", "", read(root / "CHANGELOG.md"), flags=re.MULTILINE | re.DOTALL)
    if not DATED.search(changelog):
        problems.append("CHANGELOG.md has no dated \"## YYYY-MM-DD\" entry")
    checks.append((7, not problems, "; ".join(problems) or "every in-scope story LIVE and logged"))

    checks.append((8, False, "steady state: each bug becomes a story plus a failing regression test"))

    current = next(stage for stage, ok, _ in checks if not ok)
    name, uses = STAGES[current][1], STAGES[current][2]
    return {
        "artifact_dir": str(root),
        "current_stage": current,
        "stage_name": name,
        "use": uses,
        "checks": [{"stage": s, "name": STAGES[s][1], "ok": ok, "detail": d} for s, ok, d in checks],
    }


def report(res: dict) -> str:
    lines = [f"Artifacts: {res['artifact_dir']}"]
    for c in res["checks"]:
        mark = "ok  " if c["ok"] else "TODO"
        lines.append(f"  [{mark}] {c['stage']} {c['name']}: {c['detail']}")
    lines.append(f"Current stage: {res['current_stage']} {res['stage_name']}. Use: {res['use']}.")
    lines.append("Never skip a gate: finish this stage's exit check before starting the next.")
    return "\n".join(lines)


def hook() -> int:
    """SessionStart: print a two-line context note when the project uses the artifact set."""
    try:
        project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        root = find_root(project)
        if not ((root / "PRD.md").exists() or (root / "REQUIREMENTS.md").exists()):
            return 0
        res = evaluate(project)
        failing = next(c for c in res["checks"] if c["stage"] == res["current_stage"])
        print(f"[foundry-sdlc] This project is in stage {res['current_stage']} "
              f"({res['stage_name']}). Exit check still failing: {failing['detail']}.")
        print(f"[foundry-sdlc] Use: {res['use']}. Never skip a gate. "
              "Run the foundry-sdlc:sdlc skill for the full map.")
    except Exception:  # a status hint must never break a session
        return 0
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--hook" in argv:
        return hook()
    as_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    project = Path(args[0]) if args else Path.cwd()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    res = evaluate(project)
    print(json.dumps(res, indent=2) if as_json else report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
