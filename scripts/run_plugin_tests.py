#!/usr/bin/env python3
"""run_plugin_tests.py: run every plugin's unit tests, wherever each plugin keeps them.

A plugin may keep tests in tests/, scripts/tests/, or inside a skill
(skills/<name>/scripts/tests/). This finds every directory named tests/ under
plugins/<p>/ that holds test*.py files (not one nested inside another tests/),
and runs, from the plugin root:

  python3 -m unittest discover -s <tests dir> -t <tests dir>

which is the same as the "python3 -m unittest discover -s tests" line in the
plugin READMEs. Tests that need Playwright and Chromium skip themselves when
those are missing.

Usage:
  python3 scripts/run_plugin_tests.py                  # every plugin
  python3 scripts/run_plugin_tests.py --plugin foundry-qa --list

Standard library only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import List, Optional, Tuple

SKIP = {"node_modules", "__pycache__", ".git", "fixtures", ".venv", "venv"}


def test_dirs(pdir: str) -> List[str]:
    out: List[str] = []
    for dp, dns, fns in os.walk(pdir):
        dns[:] = sorted(d for d in dns if d not in SKIP and not d.startswith("."))
        if os.path.basename(dp) == "tests" and any(f.startswith("test") and f.endswith(".py") for f in fns):
            out.append(dp)
            dns[:] = []  # a tests/ inside tests/ is fixtures, not a second suite
    return out


def plugins(root: str, only: Optional[List[str]]) -> List[str]:
    proot = os.path.join(root, "plugins")
    if not os.path.isdir(proot):
        return []
    return [os.path.join(proot, d) for d in sorted(os.listdir(proot))
            if os.path.isdir(os.path.join(proot, d)) and not d.startswith(".") and (not only or d in only)]


def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(here))
    ap.add_argument("--plugin", action="append", help="only this plugin folder (repeatable)")
    ap.add_argument("--list", action="store_true", help="print the suites, run nothing")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per suite")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    results: List[Tuple[str, str, float]] = []
    for pdir in plugins(root, args.plugin):
        for td in test_dirs(pdir):
            rel_td = os.path.relpath(td, pdir).replace(os.sep, "/")
            label = "%s: %s" % (os.path.basename(pdir), rel_td)
            if args.list:
                print(label)
                continue
            print("::group::%s" % label if os.environ.get("GITHUB_ACTIONS") else "== %s" % label, flush=True)
            t0 = time.time()
            try:
                rc = subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", rel_td, "-t", rel_td, "-v"],
                                     cwd=pdir, timeout=args.timeout)
                status = "ok" if rc == 0 else "FAILED (exit %d)" % rc
            except subprocess.TimeoutExpired:
                status = "FAILED (timed out after %ds)" % args.timeout
            if os.environ.get("GITHUB_ACTIONS"):
                print("::endgroup::", flush=True)
            results.append((label, status, time.time() - t0))
    if args.list:
        return 0
    print("\nplugin test suites:")
    for label, status, secs in results:
        print("  %-60s %s (%.1fs)" % (label, status, secs))
    failed = [r for r in results if r[1] != "ok"]
    print("%d suite%s, %d failed" % (len(results), "" if len(results) == 1 else "s", len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
