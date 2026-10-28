#!/usr/bin/env python3
"""Read and act on a macOS app's accessibility tree through System Events.

Needs: macOS, and Accessibility permission for the app that runs this script
(System Settings > Privacy & Security > Accessibility).

    ax_tree.py dump "Calculator" [--depth 8] [--out .qa/macos/ax.json]
    ax_tree.py outline .qa/macos/ax.json
    ax_tree.py find .qa/macos/ax.json --role AXButton --id Seven
    ax_tree.py press "Calculator" 1/1/1/1/1/6       # AXPress the path that find printed
    ax_tree.py bounds "Calculator"                  # x,y,w,h of window 1 for screencapture -R

On current macOS (checked on 26.6), Calculator's keys have no name, the
description "button", and an AXIdentifier such as "Seven", "Eight", "Equals"
or "AllClear". Many modern apps (SwiftUI especially) look like this: when
--name finds nothing, try --id. Use the path `find` prints, never a path from
an example: it differs between macOS versions.

A path is the window number followed by 1-based child indexes, exactly as
`dump` prints it. Paths are only valid until the UI changes, so dump again
after every action that changes the screen.

`find` matches --name/--desc/--value/--id as case-insensitive substrings and
--role exactly. Python 3 stdlib only (it shells out to osascript).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

TIMEOUT_S = 60

_DUMP_JXA = r"""
function run(argv) {
  var appName = argv[0], maxDepth = parseInt(argv[1], 10);
  var se = Application('System Events');
  var proc = se.processes.byName(appName);
  var out = [];
  function a(e, f) { try { var v = e[f](); return v === undefined ? null : v; } catch (x) { return null; } }
  function walk(e, depth, path) {
    var ident = null;
    try { ident = e.attributes.byName('AXIdentifier').value(); } catch (x) {}
    var val = a(e, 'value');
    out.push({path: path, depth: depth, role: a(e, 'role'), subrole: a(e, 'subrole'),
              name: a(e, 'name'), description: a(e, 'description'),
              value: val === null ? null : String(val), identifier: ident,
              enabled: a(e, 'enabled'), position: a(e, 'position'), size: a(e, 'size')});
    if (depth >= maxDepth) return;
    var kids = [];
    try { kids = e.uiElements(); } catch (x) {}
    for (var i = 0; i < kids.length; i++) walk(kids[i], depth + 1, path + '/' + (i + 1));
  }
  var wins = proc.windows();
  for (var w = 0; w < wins.length; w++) walk(wins[w], 0, String(w + 1));
  return JSON.stringify(out);
}
"""

_PRESS_JXA = r"""
function run(argv) {
  var appName = argv[0], parts = argv[1].split('/');
  var proc = Application('System Events').processes.byName(appName);
  proc.frontmost = true;
  var e = proc.windows[parseInt(parts[0], 10) - 1];
  for (var i = 1; i < parts.length; i++) e = e.uiElements[parseInt(parts[i], 10) - 1];
  var label = e.role() + ' ' + (e.name() || e.description() || '');
  e.actions.byName('AXPress').perform();
  return 'pressed ' + label;
}
"""

_BOUNDS_JXA = r"""
function run(argv) {
  var w = Application('System Events').processes.byName(argv[0]).windows[0];
  var p = w.position(), s = w.size();
  return [p[0], p[1], s[0], s[1]].join(',');
}
"""


def osascript_js(script: str, *args: str) -> str:
    p = subprocess.run(["osascript", "-l", "JavaScript", "-e", script, *args],
                       capture_output=True, text=True, timeout=TIMEOUT_S)
    if p.returncode != 0:
        msg = p.stderr.strip()
        if "assistive access" in msg.lower() or "-1719" in msg or "-25211" in msg:
            msg += ("\nhint: grant Accessibility to the app running this script "
                    "(System Settings > Privacy & Security > Accessibility), then restart it.")
        raise RuntimeError(msg or f"osascript exited {p.returncode}")
    return p.stdout.strip()


def center(el: dict) -> tuple[int, int] | None:
    pos, size = el.get("position"), el.get("size")
    if not pos or not size:
        return None
    return int(pos[0] + size[0] / 2), int(pos[1] + size[1] / 2)


def label(el: dict) -> str:
    bits = [el.get("role") or "?"]
    for key, tag in (("identifier", "id"), ("name", "name"), ("description", "desc"), ("value", "value")):
        v = el.get(key)
        if v not in (None, "", "missing value"):
            s = str(v)
            bits.append(f'{tag}="{s[:60]}"')
    if el.get("enabled") is False:
        bits.append("[disabled]")
    c = center(el)
    if c:
        bits.append(f"@{c[0]},{c[1]}")
    bits.append(f"path={el.get('path')}")
    return " ".join(bits)


def meaningful(el: dict) -> bool:
    return any(el.get(k) not in (None, "", "missing value")
               for k in ("name", "description", "value", "identifier"))


def find(tree: list[dict], role: str | None = None, name: str | None = None,
         desc: str | None = None, value: str | None = None, ident: str | None = None) -> list[dict]:
    def sub(have, want):
        return want is None or (have is not None and want.lower() in str(have).lower())
    return [el for el in tree
            if (role is None or el.get("role") == role)
            and sub(el.get("name"), name) and sub(el.get("description"), desc)
            and sub(el.get("value"), value) and sub(el.get("identifier"), ident)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="macOS accessibility tree helper.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("dump"); d.add_argument("app"); d.add_argument("--depth", type=int, default=8)
    d.add_argument("--out")
    o = sp.add_parser("outline"); o.add_argument("json_file"); o.add_argument("--all", action="store_true")
    f = sp.add_parser("find"); f.add_argument("json_file")
    for flag in ("--role", "--name", "--desc", "--value", "--id"):
        f.add_argument(flag)
    pr = sp.add_parser("press"); pr.add_argument("app"); pr.add_argument("path")
    b = sp.add_parser("bounds"); b.add_argument("app")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "dump":
            raw = osascript_js(_DUMP_JXA, a.app, str(a.depth))
            tree = json.loads(raw or "[]")
            text = json.dumps(tree, indent=1)
            if a.out:
                with open(a.out, "w", encoding="utf-8") as fh:
                    fh.write(text)
                print(f"wrote {len(tree)} elements to {a.out}")
            else:
                print(text)
            return 0 if tree else 1
        if a.cmd == "press":
            print(osascript_js(_PRESS_JXA, a.app, a.path))
            return 0
        if a.cmd == "bounds":
            print(osascript_js(_BOUNDS_JXA, a.app))
            return 0
    except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    try:
        with open(a.json_file, encoding="utf-8") as fh:
            tree = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"error: cannot read {a.json_file}: {e}\n")
        return 2
    if a.cmd == "outline":
        for el in tree:
            if a.all or meaningful(el):
                print("  " * int(el.get("depth", 0)) + label(el))
        return 0
    hits = find(tree, a.role, a.name, a.desc, a.value, a.id)
    for h in hits:
        print(label(h))
    if not hits and a.name is not None and a.id is None:
        sys.stderr.write("no match. Many apps expose an AXIdentifier but no name: "
                         "run `outline` and try --id (for example --id Seven in Calculator).\n")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
