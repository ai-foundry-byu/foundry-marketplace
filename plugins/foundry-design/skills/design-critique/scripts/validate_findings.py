#!/usr/bin/env python3
"""validate_findings.py - validate a design-critique findings file (stdlib only).

A findings file is a JSON array of finding objects (or {"findings": [...]}) that must
match findings.schema.json (in the design-critique skill folder), plus the run rules the schema alone
cannot express:

  - the proposal verb is one of remove | merge | relabel | inline | escalate (never add)
  - questions 1, 5, 6, 8 (flow shape) carry a delta with before/after counts
  - a delta must not make things worse (after > before)
  - at most 2 findings with severity "nit" per run
  - ids are unique
  - a finding with no grounding (no constitution_refs, log_refs or heuristic) must escalate

Usage:
  python3 validate_findings.py design/findings/2026-01-15-settings.json [--schema PATH]
      [--verdicts design/findings/2026-01-15-settings.verdicts.md]

--verdicts also fails unless every surface (each one in the verdicts file and each one a
finding names) has a verdict line for all 8 questions: `C3 route:/settings - clean`.
Exit 0 = valid, 1 = violations printed, 2 = unreadable input.
Warnings (exit unaffected) flag addition language hidden in a diff_hint of a non-escalate
finding. Quote UI labels you name ('Add member') so they are not read as proposals.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMA = os.path.join(HERE, "..", "findings.schema.json")
FLOW_SHAPE_QUESTIONS = {1, 5, 6, 8}
MAX_NITS = 2
# Language that PROPOSES a new element. Bare "create" or "new" is not enough: hints often name
# the product's own controls ("Delete the 'Create a group' FAB").
ADDITION_RE = re.compile(
    r"\b(add|adding|introduce|introducing)\b"
    r"|\b(create|build|make) (a |an )?new\b"
    r"|\bnew (button|screen|page|modal|step|panel|tab|setting)s?\b", re.I)
# Quoted spans are UI labels being named, not proposals: 'Add member', "New group", `Create`.
QUOTED_RE = re.compile(r"(?<!\w)'[^']*'(?!\w)|\"[^\"]*\"|`[^`]*`|\u2018[^\u2019]*\u2019|\u201c[^\u201d]*\u201d")

_TYPES = {
    "object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
}


def check_schema(value, schema: dict, path: str) -> list[str]:
    """Validate the JSON Schema subset this project uses: type, required, enum,
    additionalProperties false, properties, items, minimum, maximum."""
    errs: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not one of {schema['enum']}")
        return errs
    t = schema.get("type")
    if t:
        py = _TYPES[t]
        ok = isinstance(value, py) and not (t in ("integer", "number") and isinstance(value, bool))
        if not ok:
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing required field '{req}'")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{path}: unknown field '{k}'")
        for k, sub in props.items():
            if k in value:
                errs += check_schema(value[k], sub, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs += check_schema(item, schema["items"], f"{path}[{i}]")
    return errs


def check_rules(findings: list[dict]) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []
    seen: set[str] = set()
    nits = 0
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            continue
        where = f"[{i}] {f.get('id', '?')}"
        fid = f.get("id")
        if fid in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(fid)
        q = f.get("question")
        delta = f.get("delta") or {}
        verb = (f.get("proposal") or {}).get("type")
        if q in FLOW_SHAPE_QUESTIONS and verb != "escalate":
            has_clicks = "clicks_before" in delta and "clicks_after" in delta
            has_surfaces = "surfaces_before" in delta and "surfaces_after" in delta
            if not (has_clicks or has_surfaces):
                errs.append(f"{where}: question C{q} is flow-shape; delta needs clicks_before/after or surfaces_before/after")
        for a, b in (("clicks_before", "clicks_after"), ("surfaces_before", "surfaces_after")):
            if a in delta and b in delta and isinstance(delta[a], int) and isinstance(delta[b], int) and delta[b] > delta[a]:
                errs.append(f"{where}: delta {b} ({delta[b]}) > {a} ({delta[a]}); a subtraction cannot add")
        if f.get("severity") == "nit":
            nits += 1
        grounded = bool(f.get("constitution_refs") or f.get("log_refs") or f.get("heuristic"))
        if not grounded and verb != "escalate":
            errs.append(f"{where}: no grounding (constitution_refs, log_refs or heuristic); ungrounded taste must escalate")
        hint = (f.get("proposal") or {}).get("diff_hint", "")
        # escalate is how additions reach the builder, so it never warns
        if hint and verb != "escalate" and ADDITION_RE.search(QUOTED_RE.sub(" ", hint)):
            warns.append(f"{where}: diff_hint reads like an addition ({hint[:60]!r}); the critic may only subtract")
    if nits > MAX_NITS:
        errs.append(f"run has {nits} nits; at most {MAX_NITS} allowed")
    return errs, warns


VERDICT_RE = re.compile(r"^\s*[-*]?\s*C([1-8])\s+(\S+)\s+-\s+(clean|finding)\b", re.I | re.M)


def check_verdicts(findings: list, text: str) -> list[str]:
    """Every surface named in the findings, and every surface in the verdicts file, needs one
    verdict line per question: `C3 route:/settings - clean` or `C3 route:/settings - finding df-7`."""
    seen: dict[str, set[int]] = {}
    for m in VERDICT_RE.finditer(text or ""):
        seen.setdefault(m.group(2), set()).add(int(m.group(1)))
    if not seen:
        return ["verdicts file has no 'Cn <surface> - clean|finding' lines; a run with no verdicts is not a pass"]
    surfaces = set(seen) | {f.get("surface") for f in findings if isinstance(f, dict) and f.get("surface")}
    errs = []
    for surface in sorted(surfaces):
        missing = [f"C{q}" for q in range(1, 9) if q not in seen.get(surface, set())]
        if missing:
            errs.append(f"verdicts: {surface} has no verdict line for {', '.join(missing)}")
    return errs


def validate(data, schema: dict) -> tuple[list[str], list[str]]:
    if isinstance(data, dict) and "findings" in data:
        data = data["findings"]
    if not isinstance(data, list):
        return ["top level must be a JSON array of findings (or {\"findings\": [...]})"], []
    errs: list[str] = []
    for i, f in enumerate(data):
        errs += check_schema(f, schema, f"[{i}]")
    rule_errs, warns = check_rules(data)
    return errs + rule_errs, warns


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("findings")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    ap.add_argument("--verdicts", help="the run's verdict lines file; fail unless every surface has C1-C8")
    a = ap.parse_args(argv)
    try:
        with open(a.schema, encoding="utf-8") as fh:
            schema = json.load(fh)
        with open(a.findings, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    errs, warns = validate(data, schema)
    if a.verdicts:
        try:
            with open(a.verdicts, encoding="utf-8") as fh:
                vtext = fh.read()
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        items = data.get("findings", []) if isinstance(data, dict) else data
        errs += check_verdicts(items if isinstance(items, list) else [], vtext)
    for w in warns:
        print("warning:", w)
    if errs:
        print("INVALID findings file:")
        for e in errs:
            print("  x", e)
        return 1
    n = len(data["findings"] if isinstance(data, dict) else data)
    print(f"valid: {n} finding(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
