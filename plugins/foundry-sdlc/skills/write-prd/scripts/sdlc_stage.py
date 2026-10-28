#!/usr/bin/env python3
"""Tell an agent which SDLC stage a project is in, from the artifacts on disk.

    python3 sdlc_stage.py [PROJECT_DIR]          # human-readable report
    python3 sdlc_stage.py [PROJECT_DIR] --json   # machine-readable
    python3 sdlc_stage.py --hook                 # SessionStart hook mode (quiet, never fails)
    python3 sdlc_stage.py [PROJECT_DIR] --mark-follow-ups   # after a partial ship (see below)

The artifact set lives in PROJECT_DIR, or in PROJECT_DIR/product, or in
PROJECT_DIR/docs/product (searched in that order). The current stage is the
FIRST stage whose exit check fails, with one exception: once a story is LIVE and
stages 0 to 6 pass (the gates are current on HEAD), the project is in stage 8 even
when some stories are not LIVE yet; those stories, the FOLLOW-UP tasks and the
OPEN-FEEDBACK asks are listed as stage 8 open work. A code change after the gate
fails stage 6 again. Unfilled template text is marked "TODO:"; a file that still
contains "TODO:" does not count as done.

Status words shared with the ship and bug-to-story skills:
  REQUIREMENTS.md  STORIED, LIVE, DROPPED (D-xx), PARTIAL (D-xx): <what survives>,
                   OPEN (no story yet: fails stage 2),
                   OPEN-FEEDBACK: <why> (a bug report not yet storied, for example
                   "OPEN-FEEDBACK: not reproduced"; stage 8 open work, not a stage 2 failure)
  WORKPLAN.md      DONE <date>: commit <sha>, PARKED, FOLLOW-UP (blocks US-xx) (a ticket
                   written by ship or bug-to-story; stage 8 open work, not a stage 4 failure),
                   any other word (NOT STARTED, IN REVIEW ...) holds stage 4 open

Stage exit checks (deterministic, file-based):
  0 Scaffold      README.md, CHANGELOG.md, REQUIREMENTS.md, DECISIONS.md, PRD.md, WORKPLAN.md exist
  1 Requirements  REQUIREMENTS.md has an R-01 style row, an "Already exists" section, no TODO:
  2 PRD           PRD.md has stories with criteria, no TODO:, an "Addressed critiques"
                  appendix with content, stories.json is fresh (gen_stories --check), every
                  R-id's Status is STORIED, LIVE, OPEN-FEEDBACK, or DROPPED / PARTIAL citing
                  a D-id, and DECISIONS.md has the human's approval row:
                  | D-07 | 2026-11-02 | <who> | "<their words>" | PRD approved: ... | ... |
  3 Workplan      WORKPLAN.md has a task table and at least one "- [ ] M" milestone, no TODO:
  4 Execute       every task row's Status is PARKED, FOLLOW-UP, or DONE with evidence (a
                  commit sha, a PR "#12" or a URL): "DONE 2026-11-03: commit 3f2a9c1"
  5 Code QA       not detectable from files: CI is the evidence. Reported as a reminder.
  6 Visual QA     done-journey.yaml has steps and no TODO:; the tree is committed (no
                  modified or untracked file outside the artifact files and .qa/); the
                  done-gate report (.qa/done-gate/last.json: sha, exit, journey, time) says
                  exit 0 for git HEAD (or for a commit whose only later changes are artifact
                  files); and every story that is not PARKED or LIVE has a story-verifier
                  report (.qa/verify/<id>.md, whose "Commit: <sha>" line names that same
                  build) or evidence in stories.json. After a ship, NOT_BUILT stories are
                  open work instead.
  7 Ship          every story that is not PARKED is LIVE with evidence that names its
                  commit ("commit:<sha>", added by gen_stories.py --set), and CHANGELOG.md
                  has a dated entry
  8 Feedback      steady state: bugs become stories (see the bug-to-story skill); lists the
                  open work: stories not LIVE, FOLLOW-UP tasks, OPEN-FEEDBACK asks

Notes (not a stage check): "project tools out of date" when <root>/tools/gen_stories.py
(the project's own copy, at the git root or PROJECT_DIR) differs from the gen_stories.py
next to this file and is not newer. The note names the refresh command.

--mark-follow-ups (the ship skill runs it after a partial ship, once at least one story is
LIVE): every WORKPLAN task that is not DONE, PARKED or FOLLOW-UP and names a story that is
not LIVE or PARKED becomes "FOLLOW-UP (blocks US-02)", so the detector leaves stage 4. A
task that names no such story is left alone and listed, for a human call. Refused (and
nothing written) while no story is LIVE. Exit 1 when it refused or left a task open.

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
STORY_REF = re.compile(r"\b[A-Z][A-Z0-9]*-\d+[a-z]?\b")


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


def task_rows(lines: list):
    """Yield (line index, cells, status column) for every row of every table whose header
    is Id | Task | ... | Status."""
    i = 0
    while i < len(lines):
        if TASK_HEADER.match(lines[i]):
            header = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
            col = header.index("status")
            i += 2  # skip the |---| row
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) > col and cells[0]:
                    yield i, cells, col
                i += 1
            continue
        i += 1


def task_statuses(workplan: str) -> list:
    """Return (id, status) for every row of every table whose header is Id | Task | ... | Status."""
    return [(cells[0], cells[col]) for _, cells, col in task_rows(workplan.splitlines())]


def closed_task(status: str) -> bool:
    return status.upper().startswith(("DONE", "PARKED")) or follow_up(status)


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
    """STORIED, LIVE, or DROPPED / PARTIAL citing the decision: "PARTIAL (D-01): ..."."""
    s = status.strip().upper()
    return s.startswith(("STORIED", "LIVE")) or (
        s.startswith(("DROPPED", "PARTIAL")) and bool(re.search(r"\bD-\d+", s)))


def feedback(status: str) -> bool:
    """An ask from a bug report that has no story yet: "OPEN-FEEDBACK: not reproduced"."""
    return status.strip().upper().startswith("OPEN-FEEDBACK")


def follow_up(status: str) -> bool:
    """A ticket written by ship or bug-to-story: "FOLLOW-UP (blocks US-05)"."""
    return status.strip().upper().startswith("FOLLOW-UP")


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
    asks = requirement_statuses(req)
    open_feedback = [(rid, st) for rid, st in asks if feedback(st)]
    uncovered = [rid for rid, st in asks if not covered(st) and not feedback(st)]
    if uncovered:
        problems.append(f"{', '.join(uncovered[:10])} not STORIED or DROPPED (D-id): "
                        "story it, or record a decision that drops it (a bug report not "
                        "storied yet is OPEN-FEEDBACK)")
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

    follow_ups = [(t, s) for t, s in tasks if follow_up(s)]
    open_tasks = [t for t, s in tasks if not closed_task(s)]
    no_proof = [t for t, s in tasks if s.upper().startswith("DONE") and not EVIDENCE.search(s[4:])]
    problems = []
    if open_tasks:
        problems.append(f"open tasks: {', '.join(open_tasks[:12])}" + (" ..." if len(open_tasks) > 12 else ""))
    if no_proof:
        problems.append(f"DONE without evidence (add the commit sha): {', '.join(no_proof[:12])}")
    if not tasks:
        problems.append("no tasks yet")
    checks.append((4, not problems, "; ".join(problems) or
                   "all tasks DONE (with evidence), PARKED or FOLLOW-UP"))

    checks.append((5, True, "not file-detectable: a green CI run and per-change tests are the evidence"))

    journey = read(root / "done-journey.yaml")
    rows = []
    try:
        rows = gen_stories.load_stories(root / "stories.json")
    except ValueError:
        pass
    groot = gen_stories.git_root(root)
    shipped = [r.get("id") for r in rows if r.get("status") == "LIVE"]
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
        dirty = gen_stories.dirty_tree(groot, root)
        if dirty:
            problems.append(f"uncommitted changes, not in HEAD ({', '.join(dirty[:5])}): "
                            "commit them, then rerun the done gate on that commit")
        ok, gate_detail, _ = gen_stories.gate_passed(groot, root, (project, root))
        if not ok:
            problems.append(gate_detail)
        bases = [groot, Path(project).resolve(), root.resolve()]
        head = gen_stories.head_sha(groot)
        skip = {"PARKED", "LIVE"} | ({"NOT_BUILT"} if shipped else set())
        unverified, stale = [], []
        for r in rows:
            sid = str(r.get("id"))
            if r.get("status") in skip:
                continue
            rep = gen_stories.verifier_report(sid, [], bases)
            if rep is None:
                if not r.get("evidence"):
                    unverified.append(sid)
            elif head:
                why = gen_stories.verifier_problem(sid, rep, groot, root, head)
                if why:
                    stale.append(why)
        if unverified:
            problems.append(f"no story-verifier report (.qa/verify/<id>.md) for "
                            f"{', '.join(unverified[:10])}")
        problems.extend(stale[:5])
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

    work = []
    if shipped:
        work.append(f"{len(shipped)} of {len(rows)} stories LIVE")
    if not_live and shipped:
        work.append("not LIVE: " + ", ".join(f"{r.get('id')} {r.get('status')}" for r in rows
                                              if r.get("id") in not_live[:10]))
    if follow_ups:
        work.append("follow-ups: " + ", ".join(f"{t} {st}" for t, st in follow_ups[:10]))
    if open_feedback:
        work.append("open feedback: " + ", ".join(f"{rid} {st}" for rid, st in open_feedback[:10]))
    lead = "; ".join(work) + "; " if work else ""
    checks.append((8, False, lead + "steady state: each bug becomes a story plus a failing regression test"))

    current = next(stage for stage, ok, _ in checks if not ok)
    # A partial ship is stage 8: one story is LIVE, the gates are current on HEAD, and the
    # only stage 7 gap is stories that are not LIVE yet (they are open work, listed above).
    if current == 7 and shipped and not unproven and DATED.search(changelog):
        current = 8
    name, uses = STAGES[current][1], STAGES[current][2]
    if current == 8 and (follow_ups or (not_live and shipped)):
        uses = ("parallel-lanes for the FOLLOW-UP tasks, then ship (the stage-6 battery on the "
                "new commit); bug-to-story for each new report")
    return {
        "artifact_dir": str(root),
        "current_stage": current,
        "stage_name": name,
        "use": uses,
        "checks": [{"stage": s, "name": STAGES[s][1], "ok": ok, "detail": d} for s, ok, d in checks],
        "notes": tool_notes(project, groot),
    }


def tool_notes(project: Path, groot) -> list:
    """A note per project copy of tools/gen_stories.py that differs from the copy next to
    this file. A project scaffolded earlier runs its own copy, so later fixes skip it."""
    ours = Path(__file__).resolve().parent / "gen_stories.py"
    try:
        mine = ours.read_bytes()
    except OSError:
        return []
    notes, seen = [], set()
    for base in (groot, Path(project).resolve()):
        if base is None or base in seen:
            continue
        seen.add(base)
        tool = base / gen_stories.TOOL_PATH
        try:
            theirs = tool.read_bytes()
        except OSError:
            continue
        if theirs == mine:
            continue
        ver = gen_stories.version_of(theirs.decode("utf-8", errors="replace"))
        rel = gen_stories.relpath(tool, Path(project).resolve())
        if ver and gen_stories._vtuple(ver) > gen_stories._vtuple(gen_stories.__version__):
            notes.append(f"project tools newer than this plugin: {rel} is {ver}, this copy is "
                         f"{gen_stories.__version__}; update the foundry-sdlc plugin")
            continue
        notes.append(f"project tools out of date: {rel} is {ver or 'unversioned'}, the skill copy "
                     f"is {gen_stories.__version__}, so later fixes do not reach this project. "
                     f"Refresh it: python3 \"{ours}\" --refresh-tools {base}")
    return notes


def mark_follow_ups(project: Path) -> tuple:
    """After a partial ship: open WORKPLAN tasks that name a story not yet LIVE become
    FOLLOW-UP (blocks <ids>). Returns (exit code, messages)."""
    root = find_root(project)
    try:
        rows = gen_stories.load_stories(root / "stories.json")
    except ValueError as exc:
        return 1, [f"refused: {exc}"]
    if not any(r.get("status") == "LIVE" for r in rows):
        return 1, ["refused: no story is LIVE yet. FOLLOW-UP is for the work left after a "
                   "partial ship: finish the open tasks, or ship a story first. Nothing written."]
    open_ids = {str(r.get("id")) for r in rows if r.get("status") not in ("LIVE", "PARKED")}
    wp_path = root / "WORKPLAN.md"
    text = read(wp_path)
    lines = text.splitlines(keepends=True)
    changed, left = [], []
    for i, cells, col in list(task_rows([ln.rstrip("\r\n") for ln in lines])):
        tid, status = cells[0], cells[col]
        if closed_task(status):
            continue
        refs = []
        for j, cell in enumerate(cells):
            if j in (0, col):
                continue
            refs += [r for r in STORY_REF.findall(cell) if r in open_ids and r not in refs]
        if not refs:
            left.append(f"{tid} ({status or 'no status'}) names no story that is still open: set it "
                        "DONE with its commit, PARKED with a D-id, or FOLLOW-UP (blocks US-xx) by hand")
            continue
        new = f"FOLLOW-UP (blocks {', '.join(refs)})"
        line = lines[i]
        end = line[len(line.rstrip("\r\n")):]
        body = line.rstrip("\r\n")
        lead = body[:len(body) - len(body.lstrip())]
        parts = body.strip().strip("|").split("|")
        parts[col] = f" {new} "
        lines[i] = lead + "|" + "|".join(parts) + "|" + end
        changed.append(f"{tid}: {status} -> {new}")
    if changed:
        wp_path.write_text("".join(lines), encoding="utf-8")
    if not changed and not left:
        return 0, ["nothing to mark: every task is DONE, PARKED or FOLLOW-UP"]
    return (1 if left else 0), changed + left


def report(res: dict) -> str:
    lines = [f"Artifacts: {res['artifact_dir']}"]
    for c in res["checks"]:
        mark = "ok  " if c["ok"] else "TODO"
        lines.append(f"  [{mark}] {c['stage']} {c['name']}: {c['detail']}")
    for n in res.get("notes", []):
        lines.append(f"Note: {n}.")
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
        label = "Open work" if res["current_stage"] == 8 else "Exit check still failing"
        print(f"[foundry-sdlc] This project is in stage {res['current_stage']} "
              f"({res['stage_name']}). {label}: {failing['detail']}.")
        print(f"[foundry-sdlc] Use: {res['use']}. Never skip a gate. "
              "Run the foundry-sdlc:sdlc skill for the full map.")
        for n in res.get("notes", []):
            print(f"[foundry-sdlc] Note: {n}.")
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
    if "--mark-follow-ups" in argv:
        code, msgs = mark_follow_ups(project)
        for m in msgs:
            print(m)
        return code
    res = evaluate(project)
    print(json.dumps(res, indent=2) if as_json else report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
