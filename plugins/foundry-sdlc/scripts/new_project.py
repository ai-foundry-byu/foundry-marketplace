#!/usr/bin/env python3
"""Scaffold the foundry-sdlc artifact set into a project directory.

    python3 new_project.py <dir> --name "Study Buddy" [--owner "Team 4"] [--force] [--no-tools]

Creates (never overwrites an existing file unless --force):
    README.md  REQUIREMENTS.md  DECISIONS.md  PRD.md  WORKPLAN.md  CHANGELOG.md
    stories.json ([])  stories.schema.json  done-journey.yaml
    tools/gen_stories.py   (copied so CI can run --check without the plugin; --no-tools skips it)

Placeholders in the templates: {{PROJECT_NAME}}, {{SLUG}}, {{DATE}}, {{OWNER}}.
Unfilled text is marked "TODO:" so sdlc_stage.py can tell a stage is unfinished.
Python 3.8+ standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
FILES = ["README.md", "REQUIREMENTS.md", "DECISIONS.md", "PRD.md", "WORKPLAN.md",
         "CHANGELOG.md", "stories.schema.json", "done-journey.yaml"]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def fill(text: str, values: dict) -> str:
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def scaffold(dest: Path, name: str, owner: str = "TODO: team or owner",
             force: bool = False, tools: bool = True, today: str = "") -> list:
    """Write the artifact set. Returns a list of (path, action) tuples."""
    values = {"PROJECT_NAME": name, "SLUG": slugify(name),
              "DATE": today or _dt.date.today().isoformat(), "OWNER": owner}
    dest.mkdir(parents=True, exist_ok=True)
    results = []
    for fname in FILES:
        target = dest / fname
        if target.exists() and not force:
            results.append((target, "skipped (exists)"))
            continue
        target.write_text(fill((TEMPLATES / fname).read_text(encoding="utf-8"), values),
                          encoding="utf-8")
        results.append((target, "created"))
    stories = dest / "stories.json"
    if not stories.exists() or force:
        stories.write_text("[]\n", encoding="utf-8")
        results.append((stories, "created"))
    else:
        results.append((stories, "skipped (exists)"))
    if tools:
        tdir = dest / "tools"
        tdir.mkdir(exist_ok=True)
        target = tdir / "gen_stories.py"
        if target.exists() and not force:
            results.append((target, "skipped (exists)"))
        else:
            shutil.copyfile(HERE / "gen_stories.py", target)
            target.chmod(0o755)
            results.append((target, "created"))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold the foundry-sdlc artifact set")
    ap.add_argument("dir", help="project directory (created if missing)")
    ap.add_argument("--name", required=True, help='human name, e.g. "Study Buddy"')
    ap.add_argument("--owner", default="TODO: team or owner")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    ap.add_argument("--no-tools", action="store_true", help="do not copy tools/gen_stories.py")
    args = ap.parse_args(argv)
    if not TEMPLATES.is_dir():
        print(f"error: templates not found at {TEMPLATES}", file=sys.stderr)
        return 2
    for path, action in scaffold(Path(args.dir), args.name, args.owner, args.force,
                                 not args.no_tools):
        print(f"{action:18} {path}")
    print("\nNext: fill REQUIREMENTS.md (stage 1, gather-requirements skill). "
          "Check progress any time with sdlc_stage.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
