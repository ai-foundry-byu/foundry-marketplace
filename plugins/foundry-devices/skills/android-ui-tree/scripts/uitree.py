#!/usr/bin/env python3
"""Read an Android UI tree (uiautomator dump XML) instead of guessing coordinates.

Get a dump:
    adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml .qa/android/ui.xml

Then:
    uitree.py outline .qa/android/ui.xml            # compact list of meaningful nodes
    uitree.py find .qa/android/ui.xml --text "Sign in"
    uitree.py find .qa/android/ui.xml --id com.example:id/email
    uitree.py find .qa/android/ui.xml --desc "Open menu" --json
    uitree.py tap  .qa/android/ui.xml --text "Sign in" --exact --clickable --serial "$SERIAL"
                                                     # prints: adb -s SERIAL shell input tap X Y

Matching: --text and --desc are case-insensitive substring matches unless
--exact is given. --id matches the full resource-id, or the part after
":id/" (so --id email matches com.example:id/email).

--clickable returns the node that takes the tap. On list screens (Settings,
RecyclerView rows) the text node itself is not clickable; its row is. So a
match whose own node is not clickable resolves to its nearest clickable
ancestor, and tap uses that ancestor's bounds. Matches inside one row count
once. A match with no clickable ancestor is dropped.

`tap` exits 2 if zero or several nodes match, so a script never taps the
wrong thing silently. The printed command carries `-s <serial>` when one is
known: --serial, else $ANDROID_SERIAL, else the only device `adb devices`
lists. With several devices attached and no serial, tap exits 2 and lists
them. Python 3 stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass
class Node:
    index_path: str
    cls: str
    text: str
    resource_id: str
    content_desc: str
    clickable: bool
    enabled: bool
    focused: bool
    checked: bool
    bounds: tuple
    center: tuple

    def label(self) -> str:
        bits = [self.cls.rsplit(".", 1)[-1]]
        if self.resource_id:
            bits.append(f"id={self.resource_id.split(':id/')[-1]}")
        if self.text:
            bits.append(f'text="{self.text}"')
        if self.content_desc:
            bits.append(f'desc="{self.content_desc}"')
        flags = [f for f, on in (("clickable", self.clickable), ("disabled", not self.enabled),
                                 ("focused", self.focused), ("checked", self.checked)) if on]
        if flags:
            bits.append("[" + ",".join(flags) + "]")
        bits.append(f"@{self.center[0]},{self.center[1]}")
        return " ".join(bits)


def parse_bounds(s: str) -> tuple | None:
    m = _BOUNDS.fullmatch((s or "").strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def _truthy(v: str | None) -> bool:
    return (v or "").lower() == "true"


def parse(xml_text: str) -> list[Node]:
    # uiautomator sometimes prints a status line after the XML when dumped to stdout.
    end = xml_text.rfind(">")
    start = xml_text.find("<")
    if start < 0 or end < 0:
        raise ValueError("no XML found in input")
    root = ET.fromstring(xml_text[start:end + 1])
    nodes: list[Node] = []

    def walk(el: ET.Element, path: str) -> None:
        for i, child in enumerate(el.findall("node")):
            p = f"{path}/{i}" if path else str(i)
            b = parse_bounds(child.get("bounds", ""))
            if b:
                x1, y1, x2, y2 = b
                nodes.append(Node(
                    index_path=p,
                    cls=child.get("class", ""),
                    text=child.get("text", ""),
                    resource_id=child.get("resource-id", ""),
                    content_desc=child.get("content-desc", ""),
                    clickable=_truthy(child.get("clickable")),
                    enabled=_truthy(child.get("enabled", "true")),
                    focused=_truthy(child.get("focused")),
                    checked=_truthy(child.get("checked")),
                    bounds=b,
                    center=((x1 + x2) // 2, (y1 + y2) // 2),
                ))
            walk(child, p)

    walk(root, "")
    return nodes


def meaningful(n: Node) -> bool:
    return bool(n.text or n.content_desc or n.resource_id or n.clickable)


def _match(value: str, want: str, exact: bool) -> bool:
    if exact:
        return value == want
    return want.lower() in value.lower()


def find(nodes: list[Node], text: str | None = None, rid: str | None = None,
         desc: str | None = None, exact: bool = False,
         clickable_only: bool = False) -> list[Node]:
    by_path = {n.index_path: n for n in nodes}
    out = []
    seen = set()
    for n in nodes:
        if text is not None and not _match(n.text, text, exact):
            continue
        if desc is not None and not _match(n.content_desc, desc, exact):
            continue
        if rid is not None and not (n.resource_id == rid or n.resource_id.endswith(":id/" + rid)):
            continue
        if clickable_only and not n.clickable:
            n = clickable_ancestor(n, by_path)
            if n is None:
                continue
        if n.bounds[2] <= n.bounds[0] or n.bounds[3] <= n.bounds[1]:
            continue  # zero-size, off-screen
        if n.index_path in seen:
            continue  # title and summary of one row resolve to the same row
        seen.add(n.index_path)
        out.append(n)
    return out


def clickable_ancestor(n: Node, by_path: dict) -> Node | None:
    """Nearest clickable ancestor of n (the row that takes the tap), or None."""
    p = n.index_path
    while "/" in p:
        p = p.rsplit("/", 1)[0]
        a = by_path.get(p)
        if a is not None and a.clickable:
            return a
    return None


def parse_adb_devices(text: str) -> list[str]:
    """Serials in state `device` from `adb devices` output."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and not line.startswith("List of devices"):
            out.append(parts[0])
    return out


def attached_serials() -> list[str] | None:
    """Serials adb sees right now, or None when adb is missing or does not answer."""
    adb = shutil.which("adb")
    if not adb:
        return None
    try:
        p = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_adb_devices(p.stdout or "") if p.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read an Android uiautomator dump.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("outline", help="list meaningful nodes")
    o.add_argument("xml")
    o.add_argument("--all", action="store_true", help="include layout-only nodes")
    for name in ("find", "tap"):
        p = sub.add_parser(name)
        p.add_argument("xml")
        p.add_argument("--text")
        p.add_argument("--id", dest="rid")
        p.add_argument("--desc")
        p.add_argument("--exact", action="store_true")
        p.add_argument("--clickable", action="store_true")
        p.add_argument("--json", action="store_true")
        if name == "tap":
            p.add_argument("--serial", help="device serial for the printed command "
                                            "(default: $ANDROID_SERIAL, else the only attached device)")
    a = ap.parse_args(argv)

    with open(a.xml, encoding="utf-8", errors="replace") as fh:
        nodes = parse(fh.read())

    if a.cmd == "outline":
        for n in nodes:
            if a.all or meaningful(n):
                depth = n.index_path.count("/")
                print("  " * depth + n.label())
        return 0

    if a.text is None and a.rid is None and a.desc is None:
        ap.error("give at least one of --text, --id, --desc")
    hits = find(nodes, a.text, a.rid, a.desc, a.exact, a.clickable)
    if a.cmd == "find":
        if a.json:
            print(json.dumps([asdict(h) for h in hits], indent=2))
        else:
            for h in hits:
                print(h.label())
        return 0 if hits else 1
    # tap
    if len(hits) != 1:
        sys.stderr.write(f"tap needs exactly one match, found {len(hits)}:\n")
        for h in hits:
            sys.stderr.write("  " + h.label() + "\n")
        return 2
    serial = a.serial or os.environ.get("ANDROID_SERIAL")
    if not serial:
        attached = attached_serials()
        if attached and len(attached) > 1:
            sys.stderr.write(f"{len(attached)} devices attached ({', '.join(attached)}): "
                             "pass --serial <serial> so the tap hits the right one\n")
            return 2
        if attached:
            serial = attached[0]
    x, y = hits[0].center
    target = f"-s {serial} " if serial else ""
    print(f"adb {target}shell input tap {x} {y}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
