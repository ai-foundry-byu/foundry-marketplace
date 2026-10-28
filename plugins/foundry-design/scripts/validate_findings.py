#!/usr/bin/env python3
"""validate_findings.py - validate a design-critique findings file (stdlib only).

A findings file is a JSON array of finding objects (or {"findings": [...]}) that must
match skills/design-critique/findings.schema.json, plus the run rules the schema alone
cannot express:

  - the proposal verb is one of remove | merge | relabel | inline | escalate (never add)
  - questions 1, 5, 6, 8 (flow shape) carry a delta with before/after counts
  - a delta must not make things worse (after > before)
  - at most 2 findings with severity "nit" per run
  - ids are unique
  - a finding with no grounding (no constitution_refs, log_refs or heuristic) must escalate

Usage:
  python3 validate_findings.py design/findings/2026-01-15-settings.json [--schema PATH]
Exit 0 = valid, 1 = violations printed, 2 = unreadable input.
Warnings (exit unaffected) flag addition language hidden in a diff_hint.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMA = os.path.join(HERE, "..", "skills", "design-critique", "findings.schema.json")
FLOW_SHAPE_QUESTIONS = {1, 5, 6, 8}
MAX_NITS = 2
ADDITION_RE = re.compile(r"\b(add|adding|introduce|create|new (button|screen|page|modal|step|panel|tab|setting))\b", re.I)

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
        if hint and ADDITION_RE.search(hint):
            warns.append(f"{where}: diff_hint reads like an addition ({hint[:60]!r}); the critic may only subtract")
    if nits > MAX_NITS:
        errs.append(f"run has {nits} nits; at most {MAX_NITS} allowed")
    return errs, warns


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
