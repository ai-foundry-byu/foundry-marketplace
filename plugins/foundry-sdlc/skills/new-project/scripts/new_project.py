#!/usr/bin/env python3
"""Scaffold the foundry-sdlc artifact set into a project directory.

    python3 new_project.py <dir> [--name "<Project Name>"] [--owner "<Owner>"]
                           [--root <project root>] [--force] [--no-tools] [--no-ci]

<dir> is where the artifacts go: "." for a new idea, "product" inside an existing repo.
Without --name the name comes from the project folder ("study-buddy" -> "Study Buddy").

Creates (never overwrites an existing file unless --force):
    <dir>/  README.md  REQUIREMENTS.md  DECISIONS.md  PRD.md  WORKPLAN.md  CHANGELOG.md
            stories.json (compiled from the new PRD.md, so --check passes at once)
            stories.schema.json  done-journey.yaml
    <project root>/tools/gen_stories.py            (--no-tools skips it)
    <project root>/.github/workflows/stories.yml   (CI runs --check; --no-ci skips it)

The project root is --root, else the git root of <dir>, else the folder above
product/ (or docs/product/), else the current directory when <dir> is inside it,
else <dir>. Every skill then runs, from the project root:
    python3 tools/gen_stories.py --prd <dir>/PRD.md --out <dir>/stories.json

Placeholders in the templates: {{PROJECT_NAME}}, {{SLUG}}, {{DATE}}, {{OWNER}}.
Unfilled text is marked "TODO:" so sdlc_stage.py can tell a stage is unfinished.
Python 3.8+ standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
FILES = ["README.md", "REQUIREMENTS.md", "DECISIONS.md", "PRD.md", "WORKPLAN.md",
         "CHANGELOG.md", "stories.schema.json", "done-journey.yaml"]
CI_PATH = Path(".github") / "workflows" / "stories.yml"

sys.path.insert(0, str(HERE))
import gen_stories  # noqa: E402


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def fill(text: str, values: dict) -> str:
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def project_root(dest: Path) -> Path:
    """Where tools/ and .github/ go (contract C4)."""
    dest = dest.resolve()
    probe = dest
    while not probe.exists():
        probe = probe.parent
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(probe),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    if dest.name == "product":
        return dest.parent.parent if dest.parent.name == "docs" else dest.parent
    cwd = Path.cwd().resolve()
    if cwd in dest.parents:
        return cwd
    return dest


def derive_name(dest: Path) -> str:
    """A project name from the folder: study-buddy -> Study Buddy."""
    root = project_root(dest)
    words = re.split(r"[-_\s]+", root.name.strip())
    return " ".join(w[:1].upper() + w[1:] for w in words if w) or "New Project"


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def write_new(target: Path, text: str, force: bool, results: list) -> None:
    if target.exists() and not force:
        results.append((target, "skipped (exists)"))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    results.append((target, "created"))


def scaffold(dest: Path, name: str = "", owner: str = "TODO: team or owner",
             force: bool = False, tools: bool = True, today: str = "",
             root: Path = None, ci: bool = True) -> list:
    """Write the artifact set. Returns a list of (path, action) tuples."""
    dest = Path(dest)
    root = Path(root).resolve() if root else project_root(dest)
    name = name or derive_name(dest)
    values = {"PROJECT_NAME": name, "SLUG": slugify(name),
              "DATE": today or _dt.date.today().isoformat(), "OWNER": owner}
    dest.mkdir(parents=True, exist_ok=True)
    results = []
    for fname in FILES:
        write_new(dest / fname, fill((TEMPLATES / fname).read_text(encoding="utf-8"), values),
                  force, results)
    # Compile stories.json from the PRD on disk, so gen_stories.py --check passes at once.
    rows, errors, _ = gen_stories.build((dest / "PRD.md").read_text(encoding="utf-8"), {})
    write_new(dest / "stories.json", gen_stories.render([] if errors else rows), force, results)
    if tools:
        target = root / "tools" / "gen_stories.py"
        if target.exists() and not force:
            results.append((target, "skipped (exists)"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(HERE / "gen_stories.py", target)
            target.chmod(0o755)
            results.append((target, "created"))
    if ci:
        ci_values = {"PRD_PATH": rel(dest / "PRD.md", root),
                     "STORIES_PATH": rel(dest / "stories.json", root)}
        write_new(root / CI_PATH, fill((TEMPLATES / "stories-ci.yml").read_text(encoding="utf-8"),
                                       ci_values), force, results)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold the foundry-sdlc artifact set")
    ap.add_argument("dir", help='artifact directory: "." or "product" (created if missing)')
    ap.add_argument("--name", default="", help="project name; default: from the project folder")
    ap.add_argument("--owner", default="TODO: team or owner")
    ap.add_argument("--root", default="", help="project root for tools/ and .github/ (default: git root)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    ap.add_argument("--no-tools", action="store_true", help="do not copy tools/gen_stories.py")
    ap.add_argument("--no-ci", action="store_true", help="do not write .github/workflows/stories.yml")
    args = ap.parse_args(argv)
    if not TEMPLATES.is_dir():
        print(f"error: templates not found at {TEMPLATES}", file=sys.stderr)
        return 2
    dest = Path(args.dir)
    root = Path(args.root).resolve() if args.root else project_root(dest)
    name = args.name or derive_name(dest)
    if not args.name:
        print(f'name: "{name}" (from the folder name; pass --name to change it)')
    for path, action in scaffold(dest, name, args.owner, args.force, not args.no_tools,
                                 root=root, ci=not args.no_ci):
        print(f"{action:18} {path}")
    print(f"\nProject root: {root}")
    print(f"Stories, from the project root: python3 tools/gen_stories.py "
          f"--prd {rel(dest / 'PRD.md', root)} --out {rel(dest / 'stories.json', root)}")
    print("Next: fill REQUIREMENTS.md (stage 1, gather-requirements skill). "
          "Check progress any time with sdlc_stage.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
