#!/usr/bin/env python3
"""sync_vendor.py: copy each canonical file over its vendored copies.

A script or template used by several skills has ONE canonical copy; every other
skill carries a byte-identical vendored copy so it still works when copied on its
own. Each plugin records its copies in plugins/<plugin>/vendor.json:

  {"<copy path relative to the plugin root>": "<canonical path relative to the plugin root>"}

Edit the canonical file, then run this script. CI runs it with --check.

Usage:
  python3 scripts/sync_vendor.py            # write every copy that is missing or stale
  python3 scripts/sync_vendor.py --check    # change nothing; exit 1 if any copy is out of sync
  python3 scripts/sync_vendor.py --root DIR

Standard library only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import List, Optional, Tuple


def read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def vendor_files(root: str) -> List[str]:
    proot = os.path.join(root, "plugins")
    if not os.path.isdir(proot):
        return []
    return [os.path.join(proot, d, "vendor.json") for d in sorted(os.listdir(proot))
            if os.path.isfile(os.path.join(proot, d, "vendor.json"))]


def entries(vendor_json: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """(copy, canonical) pairs relative to the plugin root, or an error message."""
    try:
        with open(vendor_json, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return [], "cannot read: %s" % e
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        return [], 'must be an object {"<copy>": "<canonical>"}'
    return sorted(data.items()), None


def sync(root: str, check: bool = False) -> Tuple[int, List[str]]:
    """Returns (number of copies out of sync or failed, report lines)."""
    root = os.path.abspath(root)
    bad = 0
    report: List[str] = []
    for vj in vendor_files(root):
        pdir = os.path.dirname(vj)
        rel_vj = os.path.relpath(vj, root).replace(os.sep, "/")
        pairs, err = entries(vj)
        if err:
            bad += 1
            report.append("%s: %s" % (rel_vj, err))
            continue
        for copy_rel, canon_rel in pairs:
            copy = os.path.normpath(os.path.join(pdir, copy_rel))
            canon = os.path.normpath(os.path.join(pdir, canon_rel))
            label = "%s <- %s" % (os.path.relpath(copy, root).replace(os.sep, "/"),
                                  os.path.relpath(canon, root).replace(os.sep, "/"))
            if copy == canon:
                bad += 1
                report.append("error: %s: a file cannot be its own canonical source" % label)
                continue
            src = read_bytes(canon)
            if src is None:
                bad += 1
                report.append("error: %s: canonical source is missing" % label)
                continue
            dst = read_bytes(copy)
            if dst == src:
                continue
            state = "missing" if dst is None else "stale"
            if check:
                bad += 1
                report.append("out of sync (%s): %s" % (state, label))
                continue
            os.makedirs(os.path.dirname(copy), exist_ok=True)
            shutil.copyfile(canon, copy)
            shutil.copymode(canon, copy)
            report.append("synced (%s): %s" % (state, label))
    return bad, report


def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(here), help="repo root (default: parent of scripts/)")
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 if any copy is out of sync")
    args = ap.parse_args(argv)
    bad, report = sync(args.root, check=args.check)
    for line in report:
        print(line)
    n = len(vendor_files(os.path.abspath(args.root)))
    if bad:
        hint = " (run python3 scripts/sync_vendor.py)" if args.check else ""
        print("%d problem%s across %d vendor.json file%s%s" % (bad, "" if bad == 1 else "s", n,
                                                             "" if n == 1 else "s", hint), file=sys.stderr)
        return 1
    print("vendored copies are in sync (%d vendor.json file%s)" % (n, "" if n == 1 else "s"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
