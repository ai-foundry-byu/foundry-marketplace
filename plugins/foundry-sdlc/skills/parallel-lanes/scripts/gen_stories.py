#!/usr/bin/env python3
"""Compile the user stories written inside PRD.md into stories.json.

The PRD is the single source of truth for every story. stories.json is a
build artifact that testers, verifiers and CI read. Never hand-edit a story's
title or acceptance criteria in stories.json: edit the PRD and regenerate.

    python3 gen_stories.py                  # PRD.md -> stories.json (in the current dir)
    python3 gen_stories.py --check          # exit 1 if stories.json is stale or invalid
    python3 gen_stories.py --prd product/PRD.md --out product/stories.json
    python3 gen_stories.py --prd PRD.md --out stories.json --set US-01=LIVE \
        --evidence .qa/verify/US-01.md           # refuses LIVE unless gated (see below)
    python3 gen_stories.py --version        # the version stamp of this copy
    python3 gen_stories.py --refresh-tools .   # bring <root>/tools/gen_stories.py up to this copy

In a scaffolded project this file is tools/gen_stories.py at the project root, and
the call is always: python3 tools/gen_stories.py --prd <PRD.md> --out <stories.json>.

That project copy does not update itself when the skill does. --refresh-tools ROOT,
run from a skill's copy, replaces an older ROOT/tools/gen_stories.py (an unversioned
copy counts as older) with this one, leaves a newer one alone, creates nothing when
there is none, and prints one line: "refreshed tools/gen_stories.py: unversioned ->
0.2.0 (+40 -12 lines)". It also records the new bytes in ROOT/.foundry/generated.json,
the manifest foundry-guardrails reads so an unchanged generated file does not count
as a code edit: {"version": 1, "generator": ..., "files": [{"path", "sha256"}]}.
The scaffold's tool files (tools/gen_stories.py, .foundry/generated.json,
.github/workflows/stories.yml at the git root) are not part of the build under test,
so a refresh after the done gate does not make the gate stale.

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

Output shape (contract C1, read by foundry-qa and the verifier agents):
    {"stories": [{"id", "title", "acceptance", "surfaces", "devices", "status",
                  "waits_on", "covers", "notes", "evidence", optional "qa"}]}
An old file that is a bare JSON array is still read, and --check reports it stale.

What a regenerate preserves from the existing stories.json:
  * status (NOT_BUILT | BUILT | PARTIAL | LIVE | PARKED). New stories start NOT_BUILT.
  * surfaces / devices / waits_on, unless the PRD sets them.
  * notes, evidence, a "qa" block, any extra key on an entry, any extra top-level key.

--set ID=STATUS changes a status (repeatable; --evidence adds paths or URLs). LIVE is
refused unless ALL hold:
  * the whole tree is committed: `git status --porcelain --untracked-files=all` lists
    nothing but artifact files and .qa/ (gitignored files never appear), so neither a
    modified tracked file nor an untracked one (a new app/server.py) can hide; a rename
    counts its source, a changed submodule counts, and a file marked assume-unchanged or
    skip-worktree counts when it differs from the index;
  * the done gate report (.qa/done-gate/last.json) says exit 0 for HEAD;
  * the story has a story-verifier report (an --evidence path named <ID>.md, else
    .qa/verify/<ID>.md) whose "Commit: <sha>" line names HEAD;
  * every evidence path exists.
"HEAD" here also accepts an older commit whose only later changes are artifact files. A
report names its build by commit id (7-64 hex characters; 64 in a SHA-256 repo); "HEAD" or a branch name is refused.
The HEAD sha, the done-gate report and the verifier report are appended to the evidence.

Exit codes: 0 ok, 1 stale, invalid or refused (the reason is printed), 2 usage error.
Python 3.8+ standard library only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

__version__ = "0.2.0"

STATUSES = ("NOT_BUILT", "BUILT", "PARTIAL", "LIVE", "PARKED")
DEFAULT_DEVICES = ["phone-390x844", "desktop-1440x900"]
KEY_ORDER = ("id", "title", "acceptance", "surfaces", "devices", "status", "waits_on", "covers",
             "notes", "evidence")
# Files that may change after the done gate ran without changing the build under test.
ARTIFACT_FILES = {"README.md", "CHANGELOG.md", "REQUIREMENTS.md", "DECISIONS.md", "PRD.md",
                  "WORKPLAN.md", "stories.json", "stories.schema.json", "done-journey.yaml"}
# Scaffold tool files at the git root: generated by foundry-sdlc, not part of the build.
TOOL_FILES = {"tools/gen_stories.py", ".foundry/generated.json", ".github/workflows/stories.yml"}
TOOL_PATH = Path("tools") / "gen_stories.py"
MANIFEST = Path(".foundry") / "generated.json"
VERSION_LINE = re.compile(r'^__version__\s*=\s*["\']([0-9]+(?:\.[0-9]+)*)["\']', re.MULTILINE)
DONE_GATE_REPORTS = (".qa/done-gate/last.json", ".qa/done-gate/latest.json")
# The story-verifier report's first lines name the commit it verified: "Commit: 3f2a9c1".
VERIFIED_AT = re.compile(r"^[*\s]*Commit[*\s]*:[*`\s]*([0-9a-fA-F]{7,40})\b", re.MULTILINE)

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


def read_doc(path: Path) -> tuple:
    """Return (rows, extra top-level keys, legacy) from stories.json. Missing file = empty."""
    if not path.exists():
        return [], {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}")
    if isinstance(data, list):  # the pre-C1 format: a bare array
        return data, {}, True
    if isinstance(data, dict) and isinstance(data.get("stories"), list):
        return data["stories"], {k: v for k, v in data.items() if k != "stories"}, False
    raise ValueError(f'{path} must hold {{"stories": [...]}}')


def load_stories(path: Path) -> list:
    """The story rows of a stories.json (either format). For readers."""
    return [r for r in read_doc(path)[0] if isinstance(r, dict)]


def load_existing(path: Path) -> dict:
    return {r["id"]: r for r in load_stories(path) if "id" in r}


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
            "covers": s["covers"],
            "notes": old.get("notes", ""),
            "evidence": old.get("evidence", []),
        }
        if not isinstance(row["evidence"], list):
            errors.append(f"{s['id']} evidence must be a list of paths or URLs")
        for key, value in old.items():  # keep hand-added keys, after the core ones
            if key not in KEY_ORDER:
                row[key] = value
        rows.append(row)
    dropped = sorted(set(existing) - set(ids))
    if dropped:
        notes.append(f"dropped (no longer in the PRD): {', '.join(dropped)}. "
                     "Use status PARKED in stories.json instead of deleting a story you may revive.")
    return rows, errors, notes


def render(rows: list, extra: dict = None) -> str:
    doc = {"stories": rows}
    doc.update(extra or {})
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def summary(rows: list) -> str:
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    parts = [f"{k} {counts[k]}" for k in STATUSES if k in counts]
    return f"{len(rows)} stories ({', '.join(parts)})"


def check(prd: Path, out: Path) -> tuple:
    """Return (ok, messages) without writing anything."""
    _, extra, legacy = read_doc(out)
    rows, errors, notes = build(prd.read_text(encoding="utf-8"), load_existing(out))
    if errors:
        return False, errors
    if not out.exists():
        return False, [f"{out} does not exist: run gen_stories.py"]
    if legacy:
        return False, [f"{out} is STALE: it is a bare JSON array (old format); "
                       'regenerate with gen_stories.py to get {"stories": [...]}']
    if out.read_text(encoding="utf-8") != render(rows, extra):
        return False, [f"{out} is STALE: regenerate with gen_stories.py"] + notes
    return True, [f"{out} up to date: {summary(rows)}"]


# ---- git and done-gate evidence (shared with sdlc_stage.py) -------------------------

def git(args: list, cwd: Path) -> tuple:
    """Run git; return (exit code, stdout). 127 when git is missing or hangs."""
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return r.returncode, r.stdout.rstrip()


def git_root(path: Path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    code, out = git(["rev-parse", "--show-toplevel"], path if path.is_dir() else path.parent)
    return Path(out).resolve() if code == 0 and out else None


def relpath(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def head_sha(root: Path) -> str:
    code, out = git(["rev-parse", "HEAD"], root)
    return out if code == 0 else ""


def code_files(root: Path, artifact_dir: Path, paths: list) -> list:
    """Paths (relative to root) that are part of the build: not in a .qa/ folder, not an
    artifact file in the artifact dir."""
    art = Path(artifact_dir).resolve()
    return [f for f in paths if f and ".qa" not in Path(f).parts
            and Path(f).as_posix() not in TOOL_FILES
            and not ((root / f).parent.resolve() == art and Path(f).name in ARTIFACT_FILES)]


def dirty_tree(root: Path, artifact_dir: Path) -> list:
    """Files that would change the build but are not in HEAD: modified, staged or deleted
    tracked files, and untracked files that are not gitignored. Artifact edits and .qa/
    do not count. Untracked paths are listed as "<path> (untracked)"."""
    # --ignore-submodules=none: a .gitmodules "ignore = all" must not hide a changed submodule
    code, out = git(["status", "--porcelain", "-z", "--untracked-files=all",
                     "--ignore-submodules=none"], root)
    if code != 0:
        return ["(git status failed)"]
    tracked, untracked, entries = [], [], out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            # -z puts the source in the next field. A rename deletes its source, so it counts:
            # git mv src/app.py .qa/app.py would otherwise drop app.py from the build unseen.
            if "R" in xy and i < len(entries) and entries[i]:
                tracked.append(entries[i])
            i += 1
        (untracked if xy == "??" else tracked).append(path)
    hidden = _flagged_changes(root)
    return (code_files(root, artifact_dir, tracked)
            + [f"{f} (untracked)" for f in code_files(root, artifact_dir, untracked)]
            + [f"{f} (assume-unchanged or skip-worktree: git status hides its edits)"
               for f in code_files(root, artifact_dir, hidden)])


def _flagged_changes(root: Path) -> list:
    """Files marked assume-unchanged or skip-worktree (git status does not report their edits)
    whose working copy differs from the index."""
    code, out = git(["ls-files", "-v", "-z"], root)
    if code != 0:
        return []
    flagged = [e[2:] for e in out.split("\0")
               if len(e) > 2 and (e[0].islower() or e[0] == "S") and (root / e[2:]).is_file()]
    if not flagged:
        return []
    code, staged = git(["ls-files", "-s", "-z", "--", *flagged], root)
    index = {}
    for e in staged.split("\0") if code == 0 else []:
        meta, _, path = e.partition("\t")
        if path and len(meta.split()) >= 2:
            index[path] = meta.split()[1]
    code, hashes = git(["hash-object", "--", *flagged], root)
    if code != 0:
        return flagged  # cannot tell: report them rather than vouch for them
    return [f for f, h in zip(flagged, hashes.splitlines()) if index.get(f) != h.strip()]


dirty_tracked = dirty_tree  # the old name, kept for callers of 0.1.0


def find_report(*dirs):
    """First done-gate report under any of dirs: (path, data) or (None, None)."""
    for d in dirs:
        for rel in DONE_GATE_REPORTS:
            p = Path(d) / rel if d else None
            if p and p.is_file():
                try:
                    return p, json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return p, {}
    return None, None


def report_sha(rep: dict) -> str:
    sha = rep.get("sha") or rep.get("git_sha") or rep.get("head") or ""
    if isinstance(sha, dict):  # older done_gate.py: {"status", "expected", "found"}
        sha = (sha.get("found") or sha.get("expected") or "") if sha.get("status") == "match" else ""
    return str(sha).strip()


def same_build(root: Path, artifact_dir: Path, sha: str, head: str) -> tuple:
    """Is commit sha the build at head (equal, or only artifact files changed since)?
    Returns (ok, why-not)."""
    # Only a commit id names a fixed build. "HEAD" or a branch name matches every future HEAD,
    # a 1-char prefix matches by chance, and "--output=x" is an option git would obey.
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha or ""):
        return False, f"{sha!r} is not a commit id (7-64 hex characters)"
    sha = sha.lower()
    if head.startswith(sha):
        return True, ""
    code, out = git(["diff", "--name-only", sha, head], root)
    if code != 0:
        return False, f"{sha[:7]} is not in this repo's history"
    changed = code_files(root, artifact_dir, out.splitlines())
    if changed:
        return False, f"code changed since {sha[:7]}: {', '.join(changed[:5])}"
    return True, ""


def gate_passed(root: Path, artifact_dir: Path, extra_dirs=()) -> tuple:
    """Did the done gate pass on the build at HEAD? Returns (ok, detail, report path)."""
    head = head_sha(root)
    if not head:
        return False, "no commit yet (git HEAD missing): commit, then run the done gate", None
    path, rep = find_report(root, *extra_dirs)
    if path is None:
        return False, "no done-gate report (.qa/done-gate/last.json): run foundry-qa:done-gate", None
    code = rep.get("exit", rep.get("exit_code"))
    if code != 0:
        return False, f"done gate report says exit {code}, not 0 ({path.name})", path
    sha = report_sha(rep)
    if not sha:
        return False, "done gate report has no sha: rerun foundry-qa:done-gate", path
    ok, why = same_build(root, artifact_dir, sha, head)
    if not ok and "not a commit id" in why:
        return False, f"done gate report sha {why}: rerun foundry-qa:done-gate on HEAD {head[:7]}", path
    if not ok:
        return False, f"done gate ran at {sha[:7]} but {why}; rerun it on HEAD {head[:7]}", path
    if head.startswith(sha.lower()):
        return True, f"done gate exit 0 at HEAD {head[:7]}", path
    return True, f"done gate exit 0 at {sha[:7]} (only artifact files changed since)", path


def verified_sha(path: Path) -> str:
    """The commit a story-verifier report names on its "Commit: <sha>" line, or ""."""
    try:
        m = VERIFIED_AT.search(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    return m.group(1).lower() if m else ""


def verifier_report(sid: str, evidence: list, bases) -> Path:
    """The story-verifier report for sid: an evidence path named <sid>.md, else
    .qa/verify/<sid>.md under one of bases. None when there is none."""
    for e in evidence:
        if re.match(r"^[a-z]+:", e) or Path(e).name != f"{sid}.md":
            continue
        for b in bases:
            if (Path(b) / e).is_file():
                return Path(b) / e
    for b in bases:
        p = Path(b) / ".qa" / "verify" / f"{sid}.md"
        if p.is_file():
            return p
    return None


def verifier_problem(sid: str, report: Path, root: Path, artifact_dir: Path, head: str) -> str:
    """Why this verifier report is not evidence for the build at head ("" when it is)."""
    sha = verified_sha(report)
    rel = relpath(report, root)
    if not sha:
        return (f"{rel} names no commit (no \"Commit: <sha>\" line): rerun the story-verifier "
                f"for {sid} on HEAD {head[:7]}")
    ok, why = same_build(root, artifact_dir, sha, head)
    if not ok:
        return f"{sid} was verified at {sha[:7]} but {why}: rerun its story-verifier on HEAD {head[:7]}"
    return ""


# ---- the project's own copy: version stamp, refresh, guardrails manifest -------------

def version_of(text: str):
    """The __version__ a copy of this file declares, or None (copies before 0.2.0 had none)."""
    m = VERSION_LINE.search(text or "")
    return m.group(1) if m else None


def _vtuple(version: str) -> tuple:
    return tuple(int(p) for p in version.split("."))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_generated(root: Path, paths: list, generator: str) -> bool:
    """Add or update paths (files under root) in root/.foundry/generated.json with their
    SHA-256, keeping every other entry. Returns True when the manifest changed."""
    root = Path(root).resolve()
    man = root / MANIFEST
    try:
        data = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        data = {"version": 1, "generator": generator, "files": []}
    entries = {e["path"]: e for e in data["files"]
               if isinstance(e, dict) and isinstance(e.get("path"), str)}
    before = json.dumps(data, sort_keys=True)
    for p in paths:
        p = Path(p)
        full = (p if p.is_absolute() else root / p).resolve()
        try:
            rel = full.relative_to(root).as_posix()
        except ValueError:
            continue  # outside root: the hook ignores such entries anyway
        if full.is_file():
            entries[rel] = {"path": rel, "sha256": sha256_file(full)}
    data["files"] = sorted(entries.values(), key=lambda e: e["path"])
    data.setdefault("version", 1)
    data.setdefault("generator", generator)
    if json.dumps(data, sort_keys=True) == before and man.exists():
        return False
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def refresh_tools(root: Path, generator: str = "foundry-sdlc/gen_stories") -> tuple:
    """Bring root/tools/gen_stories.py up to this copy. Returns (state, detail, line):
    state is missing, current, newer or refreshed; line is the one-line summary."""
    root = Path(root).resolve()
    target, src = root / TOOL_PATH, Path(__file__).resolve()
    rel = TOOL_PATH.as_posix()
    if not target.is_file():
        return ("missing", "", f"no {rel} under {root}: nothing to refresh "
                "(run this copy directly, or scaffold the project with new-project)")
    old, new = target.read_bytes(), src.read_bytes()
    old_text = old.decode("utf-8", errors="replace")
    old_ver = version_of(old_text)
    if old == new:
        record_generated(root, [target], generator)
        return "current", __version__, f"{rel} is current ({__version__})"
    if old_ver and _vtuple(old_ver) > _vtuple(__version__):
        return ("newer", old_ver, f"{rel} is newer ({old_ver}) than this skill's copy "
                f"({__version__}): left as is; update the foundry-sdlc plugin")
    plus = minus = 0
    for line in difflib.unified_diff(old_text.splitlines(), new.decode("utf-8").splitlines(),
                                     lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            plus += 1
        elif line.startswith("-") and not line.startswith("---"):
            minus += 1
    target.write_bytes(new)
    target.chmod(0o755)
    record_generated(root, [target], generator)
    detail = f"{old_ver or 'unversioned'} -> {__version__}, +{plus} -{minus} lines"
    return ("refreshed", detail, f"refreshed {rel}: {old_ver or 'unversioned'} -> "
            f"{__version__} (+{plus} -{minus} lines)")


def set_status(prd: Path, out: Path, assignments: list, evidence: list) -> tuple:
    """Apply ID=STATUS edits. Returns (exit code, messages). Writes nothing on refusal."""
    ok, msgs = check(prd, out)
    if not ok:
        return 1, msgs + ["regenerate stories.json before changing a status"]
    rows, extra, _ = read_doc(out)
    by_id = {r.get("id"): r for r in rows if isinstance(r, dict)}
    wanted = []
    for a in assignments:
        sid, _, status = a.partition("=")
        status = status.strip().upper()
        if status not in STATUSES:
            return 2, [f"--set {a}: status must be one of {', '.join(STATUSES)}"]
        if sid.strip() not in by_id:
            return 2, [f"--set {a}: no story {sid.strip()} in {out}"]
        wanted.append((sid.strip(), status))
    added, head, report, per_story = [], "", None, {}
    root = git_root(out.parent)
    base = root or Path.cwd()
    evidence = [e if re.match(r"^[a-z]+:", e) or not Path(e).exists() else relpath(Path(e), base)
                for e in evidence]
    if any(s == "LIVE" for _, s in wanted):
        if root is None:
            return 1, ["LIVE refused: not a git repository. A story is LIVE only at a commit."]
        dirty = dirty_tree(root, prd.parent)
        if dirty:
            return 1, [f"LIVE refused: uncommitted changes, not in HEAD ({', '.join(dirty[:5])}). "
                       "git add and commit them (or gitignore them), rerun the gates on that "
                       "commit, then set LIVE."]
        passed, detail, report = gate_passed(root, prd.parent, (Path.cwd(), out.parent))
        if not passed:
            return 1, [f"LIVE refused: {detail}"]
        head = head_sha(root)
        bases = (Path.cwd(), root, out.parent.resolve())
        for e in evidence:
            if not re.match(r"^[a-z]+:", e) and not any((b / e).exists() for b in bases):
                return 1, [f"LIVE refused: evidence {e} does not exist"]
        for sid, status in wanted:
            if status != "LIVE":
                continue
            rep = verifier_report(sid, evidence, bases)
            if rep is None:
                return 1, [f"LIVE refused: no story-verifier report for {sid} "
                           f"(.qa/verify/{sid}.md). Run the story-verifier on HEAD {head[:7]}, "
                           "save its report, and pass it with --evidence."]
            problem = verifier_problem(sid, rep, root, prd.parent, head)
            if problem:
                return 1, [f"LIVE refused: {problem}"]
            per_story[sid] = [relpath(rep, root)]
        added = [f"commit:{head}", f"done-gate:{relpath(report, root)}"]
    for sid, status in wanted:
        row = by_id[sid]
        row["status"] = status
        ev = list(row.get("evidence") or [])
        for e in list(evidence) + per_story.get(sid, []) + (added if status == "LIVE" else []):
            if e not in ev:
                ev.append(e)
        row["evidence"] = ev
    out.write_text(render(rows, extra), encoding="utf-8")
    return 0, [f"{sid} -> {status}" for sid, status in wanted]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compile PRD.md user stories into stories.json")
    ap.add_argument("--prd", default="PRD.md", help="path to the PRD (default PRD.md)")
    ap.add_argument("--out", default="stories.json", help="output path (default stories.json)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if stories.json is stale or a story is invalid; write nothing")
    ap.add_argument("--set", action="append", default=[], metavar="ID=STATUS",
                    help="set a story's status (repeatable); LIVE is refused unless gated")
    ap.add_argument("--evidence", action="append", default=[], metavar="PATH",
                    help="evidence path or URL to record with --set (repeatable)")
    ap.add_argument("--version", action="store_true", help="print this copy's version and exit")
    ap.add_argument("--refresh-tools", metavar="ROOT",
                    help="replace an older ROOT/tools/gen_stories.py with this copy; print one line")
    args = ap.parse_args(argv)
    if args.version:
        print(f"gen_stories.py {__version__}")
        return 0
    if args.refresh_tools:
        if not Path(args.refresh_tools).is_dir():
            print(f"error: {args.refresh_tools} is not a directory", file=sys.stderr)
            return 2
        print(refresh_tools(Path(args.refresh_tools))[2])
        return 0
    prd, out = Path(args.prd), Path(args.out)
    if not prd.exists():
        print(f"error: {prd} not found", file=sys.stderr)
        return 2
    try:
        if args.set:
            code, msgs = set_status(prd, out, args.set, args.evidence)
            for m in msgs:
                print(m if code == 0 else f"error: {m}", file=sys.stdout if code == 0 else sys.stderr)
            return code
        if args.check:
            ok, msgs = check(prd, out)
            for m in msgs:
                print(m if ok else f"error: {m}", file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        extra = read_doc(out)[1]
        rows, errors, notes = build(prd.read_text(encoding="utf-8"), load_existing(out))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print("stories.json NOT written", file=sys.stderr)
        return 1
    out.write_text(render(rows, extra), encoding="utf-8")
    for n in notes:
        print(f"note: {n}")
    print(f"{summary(rows)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
