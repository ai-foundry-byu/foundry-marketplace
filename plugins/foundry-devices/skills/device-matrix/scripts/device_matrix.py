#!/usr/bin/env python3
"""Plan and summarize device QA lanes from user stories.

A story is a JSON object with at least "id" and "devices", for example:
    {"id": "S1", "title": "User signs in", "devices": ["ios", "android:pixel_7", "web-mobile"],
     "steps": ["..."], "expect": ["..."]}

A stories file is a JSON list of stories, or {"stories": [...]}. You may also
pass a directory; every *.json file in it is read.

Commands:
    device_matrix.py plan stories.json [--json]
        Group stories into lanes (one lane per device platform), say which agent
        runs each lane and whether it can run on this host.
    device_matrix.py init stories.json [--qa .qa]
        Write an empty results.json skeleton per lane (status NOT_RUN) so each
        lane agent fills in its own file.
    device_matrix.py report stories.json [--qa .qa] [--json]
        Read <qa>/<lane>/results.json for every lane, build the story-by-lane
        matrix, write <qa>/matrix.md, and print the overall verdict.

Verdict rules: any FAIL -> FAIL. Otherwise any INCONCLUSIVE or NOT_RUN cell
(including a lane that wrote no results) -> INCONCLUSIVE. Otherwise PASS.
Exit code of `report`: 0 PASS, 1 FAIL, 3 INCONCLUSIVE.
Python 3 stdlib only.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# canonical lane -> (agent or plugin that runs it, host OS it needs)
LANES = {
    "ios": ("ios-qa (iOS Simulator)", {"macos"}),
    "iphone": ("foundry-iphone-mirror plugin (real iPhone)", {"macos"}),
    "android": ("android-qa", {"macos", "linux", "windows"}),
    "windows": ("windows-qa", {"windows"}),
    "macos": ("macos-qa", {"macos"}),
    "web": ("foundry-qa plugin (Playwright desktop)", {"macos", "linux", "windows"}),
    "web-mobile": ("foundry-qa plugin (Playwright mobile emulation)", {"macos", "linux", "windows"}),
}

ALIASES = {
    "ios": "ios", "ios-sim": "ios", "ios-simulator": "ios", "iphone-sim": "ios", "ipad-sim": "ios",
    "iphone": "iphone", "iphone-real": "iphone", "ios-device": "iphone", "real-iphone": "iphone",
    "android": "android", "android-emulator": "android", "android-device": "android",
    "windows": "windows", "win": "windows", "windows-desktop": "windows",
    "macos": "macos", "mac": "macos", "macos-desktop": "macos",
    "web": "web", "web-desktop": "web", "desktop-web": "web",
    "web-mobile": "web-mobile", "mobile-web": "web-mobile",
}

STATUSES = ("PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN")


def host_os() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def split_device(raw: str) -> tuple[str | None, str]:
    """'android:pixel_7' -> ('android', 'pixel_7'); unknown -> (None, '')."""
    name, _, profile = str(raw).strip().partition(":")
    return ALIASES.get(name.strip().lower()), profile.strip()


def load_stories(path: str) -> list[dict]:
    files = sorted(glob.glob(os.path.join(path, "*.json"))) if os.path.isdir(path) else [path]
    stories: list[dict] = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "stories" in data:
            data = data["stories"]
        if isinstance(data, dict):
            data = [data]
        for s in data:
            if not isinstance(s, dict) or "id" not in s:
                raise ValueError(f"{f}: every story needs an 'id'")
            stories.append(s)
    ids = [s["id"] for s in stories]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate story ids: {', '.join(map(str, dupes))}")
    return stories


def plan(stories: list[dict], host: str | None = None) -> dict:
    host = host or host_os()
    lanes: dict[str, dict] = {}
    unknown: list[dict] = []
    no_devices: list[str] = []
    for s in stories:
        devs = s.get("devices") or []
        if not devs:
            no_devices.append(s["id"])
            continue
        for raw in devs:
            lane, profile = split_device(raw)
            if lane is None:
                unknown.append({"story": s["id"], "device": raw})
                continue
            agent, hosts = LANES[lane]
            entry = lanes.setdefault(lane, {
                "lane": lane, "agent": agent, "hosts": sorted(hosts),
                "runnable_here": host in hosts, "stories": [], "profiles": [],
            })
            if s["id"] not in entry["stories"]:
                entry["stories"].append(s["id"])
            if profile and profile not in entry["profiles"]:
                entry["profiles"].append(profile)
    return {"host": host, "lanes": [lanes[k] for k in LANES if k in lanes],
            "unknown_devices": unknown, "stories_without_devices": no_devices}


def render_plan(p: dict) -> str:
    out = [f"host: {p['host']}", ""]
    out.append("| lane | agent | runs here | stories | profiles |")
    out.append("|---|---|---|---|---|")
    for l in p["lanes"]:
        here = "yes" if l["runnable_here"] else f"no (needs {'/'.join(l['hosts'])})"
        out.append(f"| {l['lane']} | {l['agent']} | {here} | {', '.join(map(str, l['stories']))} "
                   f"| {', '.join(l['profiles']) or '-'} |")
    if p["unknown_devices"]:
        out.append("")
        out.append("unknown device names (fix the story or add an alias):")
        for u in p["unknown_devices"]:
            out.append(f"  story {u['story']}: {u['device']!r}")
    if p["stories_without_devices"]:
        out.append("")
        out.append("stories with no devices[] (they will not be device-tested): "
                   + ", ".join(map(str, p["stories_without_devices"])))
    return "\n".join(out)


def init(stories: list[dict], qa: str) -> list[str]:
    p = plan(stories)
    written = []
    for l in p["lanes"]:
        d = os.path.join(qa, l["lane"])
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "results.json")
        if os.path.exists(f):
            continue  # never clobber a lane's real results
        skel = {"lane": l["lane"], "agent": l["agent"], "device": "", "build": "",
                "stories": [{"id": sid, "status": "NOT_RUN", "evidence": [], "notes": ""}
                            for sid in l["stories"]]}
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(skel, fh, indent=2)
        written.append(f)
    return written


def read_results(qa: str, lane: str) -> dict | None:
    f = os.path.join(qa, lane, "results.json")
    if not os.path.exists(f):
        return None
    with open(f, encoding="utf-8") as fh:
        return json.load(fh)


def build_matrix(stories: list[dict], qa: str) -> dict:
    p = plan(stories)
    lanes = [l["lane"] for l in p["lanes"]]
    cells: dict[str, dict[str, dict]] = {}
    lane_meta: dict[str, dict] = {}
    for l in p["lanes"]:
        res = read_results(qa, l["lane"]) or {}
        lane_meta[l["lane"]] = {"device": res.get("device", ""), "build": res.get("build", ""),
                                "found": bool(res)}
        by_id = {str(r.get("id")): r for r in res.get("stories", []) if isinstance(r, dict)}
        for sid in l["stories"]:
            r = by_id.get(str(sid), {})
            status = str(r.get("status", "NOT_RUN")).upper()
            if status not in STATUSES:
                status = "INCONCLUSIVE"
            cells.setdefault(str(sid), {})[l["lane"]] = {
                "status": status, "evidence": r.get("evidence", []), "notes": r.get("notes", "")}
    flat = [c["status"] for row in cells.values() for c in row.values()]
    if "FAIL" in flat:
        verdict = "FAIL"
    elif any(s in ("INCONCLUSIVE", "NOT_RUN") for s in flat) or not flat:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "lanes": lanes, "lane_meta": lane_meta, "cells": cells,
            "titles": {str(s["id"]): s.get("title", "") for s in stories},
            "unknown_devices": p["unknown_devices"]}


def render_matrix(m: dict) -> str:
    out = [f"# Device QA matrix: {m['verdict']}", ""]
    out.append("| story | " + " | ".join(m["lanes"]) + " |")
    out.append("|---|" + "---|" * len(m["lanes"]))
    for sid, row in m["cells"].items():
        title = m["titles"].get(sid, "")
        label = f"{sid} {title}".strip()
        out.append(f"| {label} | " + " | ".join(row.get(l, {}).get("status", "-")
                                                  for l in m["lanes"]) + " |")
    out.append("")
    out.append("## Lanes")
    for l in m["lanes"]:
        meta = m["lane_meta"][l]
        if not meta["found"]:
            out.append(f"- {l}: no results.json written (lane did not run)")
        else:
            out.append(f"- {l}: device `{meta['device'] or '?'}`, build `{meta['build'] or '?'}`")
    problems = [(sid, l, c) for sid, row in m["cells"].items() for l, c in row.items()
                if c["status"] != "PASS"]
    if problems:
        out.append("")
        out.append("## Not passing")
        for sid, l, c in problems:
            ev = ", ".join(c["evidence"]) if c["evidence"] else "no evidence"
            note = f" {c['notes']}" if c["notes"] else ""
            out.append(f"- {sid} on {l}: {c['status']}.{note} ({ev})")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plan and summarize device QA lanes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "init", "report"):
        p = sub.add_parser(name)
        p.add_argument("stories")
        p.add_argument("--qa", default=".qa")
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        stories = load_stories(a.stories)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    if a.cmd == "plan":
        p = plan(stories)
        print(json.dumps(p, indent=2) if a.json else render_plan(p))
        return 0
    if a.cmd == "init":
        for f in init(stories, a.qa):
            print(f"wrote {f}")
        return 0
    m = build_matrix(stories, a.qa)
    os.makedirs(a.qa, exist_ok=True)
    md = render_matrix(m)
    with open(os.path.join(a.qa, "matrix.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(json.dumps(m, indent=2) if a.json else md)
    return {"PASS": 0, "FAIL": 1}.get(m["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
