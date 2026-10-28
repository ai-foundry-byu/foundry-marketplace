#!/usr/bin/env python3
"""evalkit: a small, standard-library-only eval runner for agents and prompts.

A suite is a directory with a suite.json and a cases.jsonl. For every case (and
every rep) evalkit runs YOUR target command, sends the case on stdin as JSON,
reads one JSON object back from stdout, and grades it. Code graders first
(exact, contains, regex, json_field); an optional judge command for the few
criteria code cannot check. Each run is written to
.evals/<suite>/<timestamp>.json plus a markdown summary, and compared with the
previous comparable run.

Commands:
  evalkit.py init <dir>                  copy the example suite to <dir>
  evalkit.py run <suite> [options]       run, grade, write report, compare
  evalkit.py check <suite> [--no-judge]  oracle + empty-output self-test, controls
  evalkit.py compare <suite>|<a.json> [<b.json>]
  evalkit.py history <suite>             one line per stored run

Exit codes: 0 ok, 2 config error, 3 run incomplete (no scorable trial),
4 below the gate threshold (--gate / --fail-under), 5 check failed.

The method behind this file runs in production in the AI Foundry team's own
harness; this standalone port is new (see the plugin README for maturity).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
EXIT_OK, EXIT_CONFIG, EXIT_INCOMPLETE, EXIT_BELOW, EXIT_CHECK = 0, 2, 3, 4, 5
GRADER_TYPES = {"exact", "contains", "regex", "json_field", "judge"}
DEFAULT_SPLITS = {"train": 0.4, "val": 0.2, "test": 0.4}
OUTPUT_EXCERPT = 600


class ConfigError(Exception):
    """A suite, case or grader that cannot be run as written."""


# ---------------------------------------------------------------- loading

def _parse_command(cmd, where: str) -> list[str]:
    if isinstance(cmd, str):
        parts = shlex.split(cmd)
    elif isinstance(cmd, list) and all(isinstance(x, str) for x in cmd):
        parts = list(cmd)
    else:
        raise ConfigError(f"{where}: command must be a string or a list of strings")
    if not parts:
        raise ConfigError(f"{where}: command is empty")
    return parts


def validate_grader(g: dict, where: str) -> None:
    if not isinstance(g, dict):
        raise ConfigError(f"{where}: grader must be an object")
    t = g.get("type")
    if t not in GRADER_TYPES:
        raise ConfigError(f"{where}: unknown grader type {t!r} (use one of {sorted(GRADER_TYPES)})")
    if t == "exact" and "value" not in g:
        raise ConfigError(f"{where}: exact grader needs 'value'")
    if t == "contains" and "value" not in g and "any" not in g:
        raise ConfigError(f"{where}: contains grader needs 'value' (str or list) or 'any' (list)")
    if t == "regex":
        if "pattern" not in g:
            raise ConfigError(f"{where}: regex grader needs 'pattern'")
        try:
            re.compile(g["pattern"])
        except re.error as e:
            raise ConfigError(f"{where}: bad regex {g['pattern']!r}: {e}") from e
    if t == "json_field":
        if "path" not in g and "field" not in g:
            raise ConfigError(f"{where}: json_field grader needs 'path'")
        if not any(k in g for k in ("equals", "one_of", "exists", "is")):
            raise ConfigError(f"{where}: json_field grader needs equals, one_of, exists or is")
        if "is" in g and g["is"] not in _JSON_TYPES:
            raise ConfigError(f"{where}: json_field 'is' must be one of {sorted(_JSON_TYPES)}")
    if t == "judge" and not g.get("criterion"):
        raise ConfigError(f"{where}: judge grader needs 'criterion' (and should have 'rubric')")


def load_suite(path) -> dict:
    p = Path(path)
    f = p / "suite.json" if p.is_dir() else p
    if not f.is_file():
        raise ConfigError(f"no suite.json at {f}")
    try:
        suite = json.loads(f.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"{f}: invalid JSON: {e}") from e
    if not isinstance(suite, dict) or not suite.get("name"):
        raise ConfigError(f"{f}: needs a 'name'")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", suite["name"]):
        raise ConfigError(f"{f}: name must be letters, digits, '.', '_' or '-'")
    target = suite.get("target") or {}
    target["command"] = _parse_command(target.get("command"), f"{f} target")
    target.setdefault("timeout_s", 120)
    suite["target"] = target
    suite.setdefault("cases", "cases.jsonl")
    suite.setdefault("reps", 1)
    suite.setdefault("threshold", None)
    suite.setdefault("graders", [])
    suite.setdefault("controls", [])
    suite.setdefault("surfaces", [])
    suite.setdefault("splits", DEFAULT_SPLITS)
    for i, g in enumerate(suite["graders"]):
        validate_grader(g, f"{f} graders[{i}]")
    if suite.get("judge"):
        suite["judge"]["command"] = _parse_command(suite["judge"].get("command"), f"{f} judge")
        suite["judge"].setdefault("timeout_s", 180)
    for i, c in enumerate(suite["controls"]):
        if not c.get("name"):
            raise ConfigError(f"{f} controls[{i}]: needs a name")
        c["command"] = _parse_command(c.get("command"), f"{f} controls[{i}]")
        c.setdefault("max_score", 0.3)
    suite["_dir"] = f.parent.resolve()
    suite["_file"] = f.resolve()
    return suite


def load_cases(suite: dict) -> list[dict]:
    f = suite["_dir"] / suite["cases"]
    if not f.is_file():
        raise ConfigError(f"no cases file at {f}")
    cases, seen = [], set()
    for n, line in enumerate(f.read_text().splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            c = json.loads(s)
        except json.JSONDecodeError as e:
            raise ConfigError(f"{f}:{n}: invalid JSON: {e}") from e
        if not isinstance(c, dict) or "id" not in c or "input" not in c:
            raise ConfigError(f"{f}:{n}: a case needs 'id' and 'input'")
        if c["id"] in seen:
            raise ConfigError(f"{f}:{n}: duplicate case id {c['id']!r}")
        seen.add(c["id"])
        c.setdefault("graders", [])
        c.setdefault("tags", [])
        for i, g in enumerate(c["graders"]):
            validate_grader(g, f"{f}:{n} graders[{i}]")
        if not c["graders"] and not suite["graders"]:
            raise ConfigError(f"{f}:{n}: case {c['id']!r} has no graders and the suite has none")
        c["split"] = c.get("split") or assign_split(suite["name"], c["id"], suite["splits"])
        cases.append(c)
    if not cases:
        raise ConfigError(f"{f}: no cases")
    return cases


def assign_split(suite_name: str, case_id: str, splits: dict) -> str:
    """Deterministic: a case keeps its split when other cases are added."""
    h = int(hashlib.sha256(f"{suite_name}:{case_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    acc = 0.0
    items = list(splits.items())
    for name, frac in items:
        acc += float(frac)
        if h < acc:
            return name
    return items[-1][0]


# ---------------------------------------------------------------- grading

def get_path(obj, path: str):
    """Dotted path into dicts and lists. Returns (found, value)."""
    if path in ("", ".", None):
        return True, obj
    cur = obj
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and re.fullmatch(r"-?\d+", part) and -len(cur) <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _as_text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True)


_JSON_TYPES = {"string": str, "number": (int, float), "boolean": bool, "array": list,
               "object": dict, "null": type(None)}


def grade_one(g: dict, output: dict, case: dict, judge=None):
    """Returns (passed: True|False|None, reason). None = could not grade."""
    t = g["type"]
    field = g.get("path", g.get("field", "output"))
    found, val = get_path(output, field)
    ic = bool(g.get("ignore_case"))

    if t == "judge":
        if judge is None:
            return None, "judge skipped (--no-judge or no judge configured)"
        ok, reason = judge(case, output, g)
    elif t == "json_field" and "exists" in g:
        ok = found == bool(g["exists"])
        reason = f"{field} {'exists' if found else 'missing'}"
        if ok and found and ("equals" in g or "one_of" in g or "is" in g):
            ok, reason = _json_field_checks(g, field, val)
    elif not found:
        ok, reason = False, f"field {field!r} missing from output"
    elif t == "exact":
        want = g["value"]
        if isinstance(want, str) and isinstance(val, str):
            a, b = (val.strip(), want.strip()) if g.get("strip", True) else (val, want)
            ok = a.casefold() == b.casefold() if ic else a == b
        else:
            ok = val == want
        reason = f"{field} == {want!r}" if ok else f"{field} is {_short(val)!r}, wanted {want!r}"
    elif t == "contains":
        text = _as_text(val)
        hay = text.casefold() if ic else text
        if "any" in g:
            needles = list(g["any"])
            hits = [n for n in needles if (n.casefold() if ic else n) in hay]
            ok = bool(hits)
            reason = f"found {hits[0]!r}" if ok else f"none of {needles!r} in {field}"
        else:
            needles = g["value"] if isinstance(g["value"], list) else [g["value"]]
            missing = [n for n in needles if (n.casefold() if ic else n) not in hay]
            ok = not missing
            reason = f"{field} contains {needles!r}" if ok else f"{field} lacks {missing!r}"
    elif t == "regex":
        flags = 0
        for ch in str(g.get("flags", "")) + ("i" if ic else ""):
            flags |= {"i": re.I, "m": re.M, "s": re.S}.get(ch, 0)
        m = re.search(g["pattern"], _as_text(val), flags)
        ok = m is not None
        reason = f"matched {m.group(0)[:60]!r}" if ok else f"/{g['pattern']}/ not found in {field}"
    elif t == "json_field":
        ok, reason = _json_field_checks(g, field, val)
    else:  # unreachable after validation
        raise ConfigError(f"unknown grader type {t}")

    if ok is None:
        return None, reason
    if g.get("negate"):
        return (not ok), ("NOT: " + reason)
    return bool(ok), reason


def _json_field_checks(g, field, val):
    if "is" in g:
        py = _JSON_TYPES[g["is"]]
        is_type = isinstance(val, py) and not (g["is"] == "number" and isinstance(val, bool))
        if not is_type:
            return False, f"{field} is {type(val).__name__}, wanted {g['is']}"
    if "equals" in g and val != g["equals"]:
        return False, f"{field} is {_short(val)!r}, wanted {g['equals']!r}"
    if "one_of" in g and val not in g["one_of"]:
        return False, f"{field} is {_short(val)!r}, not one of {g['one_of']!r}"
    return True, f"{field} ok ({_short(val)!r})"


def _short(v, n=80):
    s = _as_text(v)
    return s if len(s) <= n else s[: n - 3] + "..."


def grader_name(g: dict, i: int) -> str:
    return g.get("name") or f"{g['type']}#{i}"


# ---------------------------------------------------------------- running

def run_command(cmd: list[str], payload: dict, cwd: Path, timeout: float):
    """Run one subprocess with JSON on stdin. Returns (obj|None, error|None, seconds)."""
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True,
                           timeout=timeout, cwd=str(cwd))
    except FileNotFoundError as e:
        return None, f"command not found: {e.filename or cmd[0]}", time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s", time.monotonic() - t0
    dt = time.monotonic() - t0
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip()[-400:]
        return None, f"exit {p.returncode}: {tail}", dt
    obj = _parse_json_object(p.stdout)
    if obj is None:
        return None, f"stdout is not a JSON object: {p.stdout.strip()[:200]!r}", dt
    return obj, None, dt


def _parse_json_object(text: str):
    text = (text or "").strip()
    candidates = [text] + [ln for ln in reversed(text.splitlines()) if ln.strip()]
    for c in candidates:
        try:
            v = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(v, dict):
            return v
    return None


def make_judge(suite: dict, costs: list):
    cfg = suite.get("judge")
    if not cfg:
        return None

    def judge(case, output, g):
        payload = {"case_id": case["id"], "input": case["input"], "expected": case.get("expected"),
                   "output": output, "criterion": g["criterion"], "rubric": g.get("rubric", "")}
        obj, err, _ = run_command(cfg["command"], payload, suite["_dir"], cfg["timeout_s"])
        if err:
            return None, f"judge error: {err}"
        meta = obj.get("_meta") or {}
        if isinstance(meta.get("cost_usd"), (int, float)):
            costs.append(float(meta["cost_usd"]))
        v = obj.get("pass")
        if v is None:
            return None, f"judge said unknown: {obj.get('reason', '')}"[:300]
        return bool(v), str(obj.get("reason", ""))[:300]

    return judge


def select_cases(cases, *, case_ids=None, split="all", tags=None):
    out = cases
    if case_ids:
        known = {c["id"] for c in cases}
        missing = [x for x in case_ids if x not in known]
        if missing:
            raise ConfigError(f"unknown case id(s): {missing}")
        out = [c for c in out if c["id"] in case_ids]
    if split and split != "all":
        out = [c for c in out if c["split"] == split]
    if tags:
        out = [c for c in out if set(tags) & set(c.get("tags") or [])]
    if not out:
        raise ConfigError("no cases selected")
    return out


def run_trials(suite, cases, *, reps, command=None, use_judge=True, progress=None):
    command = command or suite["target"]["command"]
    judge_costs: list[float] = []
    judge = make_judge(suite, judge_costs) if use_judge else None
    rows = []
    total = len(cases) * reps
    for case in cases:
        graders = list(suite["graders"]) + list(case["graders"])
        for rep in range(reps):
            payload = {"case_id": case["id"], "rep": rep, "input": case["input"]}
            out, err, dt = run_command(command, payload, suite["_dir"], suite["target"]["timeout_s"])
            row = {"case_id": case["id"], "rep": rep, "split": case["split"],
                   "tags": case.get("tags", []), "duration_s": round(dt, 3)}
            if err:
                row.update(status="error", error=err, pass_=None)
            else:
                meta = out.get("_meta") or {}
                row["cost_usd"] = float(meta["cost_usd"]) if isinstance(meta.get("cost_usd"), (int, float)) else None
                row["output"] = out
                grades, unknown, skipped = [], [], 0
                for i, g in enumerate(graders):
                    ok, reason = grade_one(g, out, case, judge)
                    if ok is None and g["type"] == "judge" and judge is None:
                        skipped += 1
                        grades.append({"name": grader_name(g, i), "type": g["type"], "pass": None,
                                       "reason": reason, "skipped": True})
                        continue
                    if ok is None:
                        unknown.append(reason)
                    grades.append({"name": grader_name(g, i), "type": g["type"], "pass": ok, "reason": reason})
                row["grades"] = grades
                row["judge_skipped"] = skipped
                scored = [x for x in grades if not x.get("skipped")]
                if unknown:
                    row.update(status="error", error="; ".join(unknown), pass_=None)
                elif not scored:
                    row.update(status="error", error="every grader was skipped", pass_=None)
                else:
                    row.update(status="ok", pass_=all(x["pass"] for x in scored))
            row["pass"] = row.pop("pass_")
            rows.append(row)
            if progress:
                progress(len(rows), total, row)
    return rows, judge_costs


# ---------------------------------------------------------------- stats

def case_means(rows) -> dict:
    by: dict[str, list[float]] = {}
    for r in rows:
        if r["status"] == "ok":
            by.setdefault(r["case_id"], []).append(1.0 if r["pass"] else 0.0)
    return {cid: sum(v) / len(v) for cid, v in by.items()}


def pass_at_k(n: int, c: int, k: int) -> float:
    """Chance at least one of k tries passes (unbiased, from n tries with c passes)."""
    if n < k:
        raise ValueError("n < k")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Chance all k tries pass. The bar for an agent that runs unattended."""
    if n < k:
        raise ValueError("n < k")
    return math.comb(c, k) / math.comb(n, k)


def bootstrap_ci(values, n=2000, seed=0, alpha=0.05):
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    k = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(k)) / k for _ in range(n))
    return round(means[int(alpha / 2 * n)], 4), round(means[min(n - 1, int((1 - alpha / 2) * n))], 4)


def summarize(rows, reps: int, threshold=None, judge_costs=()) -> dict:
    cm = case_means(rows)
    vals = list(cm.values())
    score = round(sum(vals) / len(vals), 4) if vals else None
    lo, hi = bootstrap_ci(vals)
    counts: dict[str, list[int]] = {}
    for r in rows:
        if r["status"] == "ok":
            n_c = counts.setdefault(r["case_id"], [0, 0])
            n_c[0] += 1
            n_c[1] += 1 if r["pass"] else 0
    k = reps
    full = {cid: nc for cid, nc in counts.items() if nc[0] >= k}
    pak = round(sum(pass_at_k(n, c, k) for n, c in full.values()) / len(full), 4) if full else None
    phk = round(sum(pass_hat_k(n, c, k) for n, c in full.values()) / len(full), 4) if full else None
    by_rep: dict[int, list[float]] = {}
    for r in rows:
        if r["status"] == "ok":
            by_rep.setdefault(r["rep"], []).append(1.0 if r["pass"] else 0.0)
    rep_scores = [round(sum(v) / len(v), 4) for _, v in sorted(by_rep.items())]
    tags: dict[str, list[float]] = {}
    tag_of = {r["case_id"]: r.get("tags") or [] for r in rows}
    for cid, m in cm.items():
        for t in tag_of.get(cid, []):
            tags.setdefault(t, []).append(m)
    target_costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    n_ok = sum(1 for r in rows if r["status"] == "ok")
    s = {
        "score": score, "ci_low": lo, "ci_high": hi,
        "k": k, "pass_at_k": pak, "pass_hat_k": phk, "pass_k_short": sorted(set(counts) - set(full)),
        "rep_scores": rep_scores,
        "stdev_across_reps": round(statistics.pstdev(rep_scores), 4) if len(rep_scores) > 1 else 0.0,
        "n_cases": len(vals), "n_trials": len(rows), "n_ok": n_ok,
        "n_errors": len(rows) - n_ok,
        "flipping_cases": sorted(cid for cid, m in cm.items() if 0 < m < 1),
        "always_failing_cases": sorted(cid for cid, m in cm.items() if m == 0),
        "unscored_cases": sorted({r["case_id"] for r in rows} - set(cm)),
        "by_tag": {t: round(sum(v) / len(v), 4) for t, v in sorted(tags.items())},
        "judge_skipped": sum(r.get("judge_skipped", 0) for r in rows),
        "target_cost_usd": round(sum(target_costs), 6) if target_costs else None,
        "judge_cost_usd": round(sum(judge_costs), 6) if judge_costs else None,
        "cost_reported_trials": len(target_costs),
        "duration_s": round(sum(r["duration_s"] for r in rows), 2),
        "threshold": threshold,
    }
    costs = [c for c in (s["target_cost_usd"], s["judge_cost_usd"]) if c is not None]
    s["total_cost_usd"] = round(sum(costs), 6) if costs else None
    s["verdict"] = None if threshold is None or score is None else ("PASS" if score >= threshold else "FAIL")
    return s


# ---------------------------------------------------------------- fingerprints

def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fingerprint(suite, cases) -> dict:
    case_view = sorted(([c["id"], c["input"], c.get("expected"), c["graders"]] for c in cases),
                       key=lambda x: str(x[0]))
    surfaces = {}
    for rel in suite.get("surfaces") or []:
        f = suite["_dir"] / rel
        surfaces[rel] = hashlib.sha256(f.read_bytes()).hexdigest()[:16] if f.is_file() else "missing"
    return {"case_set_sha": _sha(case_view), "grader_sha": _sha(suite["graders"]),
            "target_sha": _sha(suite["target"]["command"]), "surfaces": surfaces}


# ---------------------------------------------------------------- storage

def out_dir_for(suite, out_root) -> Path:
    return Path(out_root) / suite["name"]


def write_run(record: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    base = record["run_id"]
    f = out / f"{base}.json"
    i = 2
    while f.exists():
        record["run_id"] = f"{base}-{i}"
        f = out / f"{record['run_id']}.json"
        i += 1
    f.write_text(json.dumps(record, indent=2, sort_keys=False, default=str))
    (out / f"{record['run_id']}.md").write_text(render_markdown(record))
    return f


def list_runs(out: Path) -> list[dict]:
    if not out.is_dir():
        return []
    runs = []
    for f in sorted(out.glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(r, dict) and r.get("evalkit") and "summary" in r:
            r["_path"] = str(f)
            runs.append(r)
    runs.sort(key=lambda r: (r.get("started_at", ""), r.get("run_id", "")))
    return runs


def previous_comparable(runs, current) -> dict | None:
    """Latest earlier full run on the same split. Case-set mismatch is reported by compare()."""
    for r in reversed(runs):
        if r["run_id"] == current["run_id"] or r.get("subset"):
            continue
        if r.get("split") != current.get("split"):
            continue
        if r.get("started_at", "") > current.get("started_at", ""):
            continue
        return r
    return None


def compare(prev: dict, cur: dict) -> dict:
    a, b = prev["summary"], cur["summary"]
    same_cases = prev["fingerprint"]["case_set_sha"] == cur["fingerprint"]["case_set_sha"]
    same_graders = prev["fingerprint"]["grader_sha"] == cur["fingerprint"]["grader_sha"]
    pm = {k: v for k, v in prev.get("case_means", {}).items()}
    cm = {k: v for k, v in cur.get("case_means", {}).items()}
    regressed = sorted(c for c in cm if c in pm and pm[c] == 1.0 and cm[c] < 1.0)
    fixed = sorted(c for c in cm if c in pm and pm[c] < 1.0 and cm[c] == 1.0)
    moved = sorted(c for c in cm if c in pm and c not in regressed and c not in fixed and pm[c] != cm[c])
    delta = None if a["score"] is None or b["score"] is None else round(b["score"] - a["score"], 4)
    half = max((a["ci_high"] - a["ci_low"]) / 2, (b["ci_high"] - b["ci_low"]) / 2)
    noise = max(half, a.get("stdev_across_reps", 0), b.get("stdev_across_reps", 0))
    changed_surfaces = sorted(k for k, v in cur["fingerprint"].get("surfaces", {}).items()
                              if prev["fingerprint"].get("surfaces", {}).get(k) != v)
    cost_delta = None
    if a.get("total_cost_usd") is not None and b.get("total_cost_usd") is not None:
        cost_delta = round(b["total_cost_usd"] - a["total_cost_usd"], 6)
    if not same_cases:
        reading = "NOT COMPARABLE: the case set changed. Re-run a new baseline before reading a delta."
    elif not same_graders:
        reading = "NOT COMPARABLE: the suite-level graders changed."
    elif delta is None:
        reading = "no score on one side"
    elif abs(delta) <= noise:
        reading = f"within noise (|delta| {abs(delta):.3f} <= noise band {noise:.3f})"
    else:
        reading = "improved" if delta > 0 else "regressed"
    return {"previous_run": prev["run_id"], "comparable": same_cases and same_graders,
            "score_delta": delta, "noise_band": round(noise, 4), "reading": reading,
            "newly_failing": regressed, "newly_passing": fixed, "moved": moved,
            "cost_delta_usd": cost_delta, "changed_surfaces": changed_surfaces,
            "target_changed": prev["fingerprint"].get("target_sha") != cur["fingerprint"].get("target_sha")}


# ---------------------------------------------------------------- report

def _fmt(x, pct=True):
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%" if pct else f"{x}"


def render_markdown(rec: dict) -> str:
    s = rec["summary"]
    L = [f"# Eval run: {rec['suite']} / {rec['run_id']}", ""]
    if rec.get("label"):
        L.append(f"Label: **{rec['label']}**")
    L += [f"Started {rec['started_at']}, split `{rec['split']}`, {s['n_cases']} cases x {s['k']} reps"
          f"{' (SUBSET: not a baseline)' if rec.get('subset') else ''}.", ""]
    if rec.get("control"):
        L += [f"CONTROL RUN `{rec['control']}`: this score must stay LOW.", ""]
    L += ["| metric | value |", "|---|---|",
          f"| score (mean case pass rate) | {_fmt(s['score'])} (95% CI {_fmt(s['ci_low'])} to {_fmt(s['ci_high'])}) |",
          f"| pass@{s['k']} (any try passes) | {_fmt(s['pass_at_k'])} |",
          f"| pass^{s['k']} (every try passes) | {_fmt(s['pass_hat_k'])} |",
          f"| threshold | {_fmt(s['threshold']) if s['threshold'] is not None else 'none set'} |",
          f"| verdict | {s['verdict'] or 'n/a'} |",
          f"| trials ok / errors | {s['n_ok']} / {s['n_errors']} |",
          f"| cost (target + judge, as reported) | {('$%.4f' % s['total_cost_usd']) if s['total_cost_usd'] is not None else 'not reported'} |",
          f"| wall time | {s['duration_s']}s |", ""]
    if s["judge_skipped"]:
        L += [f"WARNING: {s['judge_skipped']} judge check(s) were skipped. Cases were graded on code checks only, "
              "so this score is an upper bound. Do not quote it as the suite score.", ""]
    if s["n_errors"]:
        L += [f"WARNING: {s['n_errors']} trial(s) had no scorable output and are NOT counted as zeros. "
              "Fix them before trusting the score.", ""]
    if s["pass_k_short"]:
        L += [f"Cases with fewer than k scorable reps (left out of pass@k / pass^k): {', '.join(s['pass_k_short'])}", ""]
    cmp_ = rec.get("comparison")
    L.append("## Compared with the previous run")
    if not cmp_:
        L += ["", "No earlier comparable run. This run is the baseline.", ""]
    else:
        L += ["", f"Previous: `{cmp_['previous_run']}`. Reading: **{cmp_['reading']}**.",
              f"Score delta: {cmp_['score_delta']:+.3f}" if cmp_["score_delta"] is not None else "Score delta: n/a"]
        if cmp_["cost_delta_usd"] is not None:
            L.append(f"Cost delta: ${cmp_['cost_delta_usd']:+.4f}")
        if cmp_["changed_surfaces"]:
            L.append(f"Changed surfaces: {', '.join(cmp_['changed_surfaces'])}")
        if cmp_["target_changed"]:
            L.append("The target command changed.")
        for key, title in (("newly_failing", "Newly failing"), ("newly_passing", "Newly passing"), ("moved", "Moved (partial)")):
            if cmp_[key]:
                L.append(f"{title}: {', '.join(cmp_[key])}")
        L.append("")
    if s["by_tag"]:
        L += ["## By tag", "", "| tag | score |", "|---|---|"]
        L += [f"| {t} | {_fmt(v)} |" for t, v in s["by_tag"].items()] + [""]
    if s["always_failing_cases"]:
        L += ["## Cases at 0% on every rep", "",
              "Read these first. A case that fails on every try is often a broken case (an unstated "
              "expectation or a wrong grader), not a weak agent.", "",
              ", ".join(s["always_failing_cases"]), ""]
    if s["flipping_cases"]:
        L += ["## Flipping cases (pass on some reps, fail on others)", "", ", ".join(s["flipping_cases"]), ""]
    fails = [r for r in rec["rows"] if r["status"] == "ok" and not r["pass"]]
    L += ["## Failures", ""]
    if not fails:
        L += ["None.", ""]
    for r in fails:
        L.append(f"### {r['case_id']} (rep {r['rep']})")
        for g in r["grades"]:
            if g["pass"] is False:
                L.append(f"- FAIL `{g['name']}`: {g['reason']}")
        L += ["", "```json", _short(r.get("output"), OUTPUT_EXCERPT), "```", ""]
    errs = [r for r in rec["rows"] if r["status"] == "error"]
    if errs:
        L += ["## Errors (not scored)", ""]
        L += [f"- {r['case_id']} rep {r['rep']}: {r['error']}" for r in errs] + [""]
    return "\n".join(L)


# ---------------------------------------------------------------- commands

def _now():
    return datetime.now(timezone.utc)


def execute_run(suite, cases, *, reps, split, subset, label=None, use_judge=True,
                command=None, control=None, progress=None, threshold="suite"):
    started = _now()
    rows, judge_costs = run_trials(suite, cases, reps=reps, command=command, use_judge=use_judge,
                                   progress=progress)
    thr = suite["threshold"] if threshold == "suite" else threshold
    rec = {
        "evalkit": VERSION, "suite": suite["name"],
        "run_id": started.strftime("%Y%m%dT%H%M%S") + f"-{started.microsecond // 1000:03d}Z",
        "started_at": started.isoformat(timespec="microseconds"),
        "label": label, "split": split, "subset": subset, "control": control,
        "reps": reps, "use_judge": use_judge and bool(suite.get("judge")),
        "command": command or suite["target"]["command"],
        "fingerprint": fingerprint(suite, cases),
        "summary": summarize(rows, reps, thr, judge_costs),
        "case_means": {k: round(v, 4) for k, v in case_means(rows).items()},
        "rows": rows,
    }
    return rec


def cmd_run(args) -> int:
    suite = load_suite(args.suite)
    cases = load_cases(suite)
    ids = [x.strip() for x in args.cases.split(",")] if args.cases else None
    tags = [x.strip() for x in args.tag.split(",")] if args.tag else None
    sel = select_cases(cases, case_ids=ids, split=args.split, tags=tags)
    reps = args.reps or int(suite["reps"])
    command = _parse_command(args.target, "--target") if args.target else None
    subset = bool(ids or tags or command)

    def progress(i, n, row):
        if not args.quiet:
            mark = "ERR " if row["status"] == "error" else ("pass" if row["pass"] else "FAIL")
            print(f"[{i}/{n}] {mark} {row['case_id']} rep {row['rep']}", file=sys.stderr)

    rec = execute_run(suite, sel, reps=reps, split=args.split, subset=subset, label=args.label,
                      use_judge=not args.no_judge, command=command, progress=progress)
    out = out_dir_for(suite, args.out)
    prev = previous_comparable(list_runs(out), rec)
    if prev and not subset:
        rec["comparison"] = compare(prev, rec)
    path = write_run(rec, out)
    s = rec["summary"]
    print(f"suite {suite['name']}: score {_fmt(s['score'])} (CI {_fmt(s['ci_low'])}-{_fmt(s['ci_high'])}), "
          f"pass^{s['k']} {_fmt(s['pass_hat_k'])}, errors {s['n_errors']}, verdict {s['verdict'] or 'n/a'}")
    if rec.get("comparison"):
        print(f"vs {rec['comparison']['previous_run']}: {rec['comparison']['reading']}")
    if s["judge_skipped"]:
        print(f"WARNING: {s['judge_skipped']} judge checks skipped; score is an upper bound")
    print(f"report: {path.with_suffix('.md')}")
    if s["n_ok"] == 0:
        return EXIT_INCOMPLETE
    gate = args.fail_under if args.fail_under is not None else (suite["threshold"] if args.gate else None)
    if gate is not None:
        metric = s["pass_hat_k"] if args.fail_metric == "pass_hat_k" else s["score"]
        if metric is None or metric < gate:
            print(f"GATE: {args.fail_metric} {_fmt(metric)} is below {_fmt(gate)}")
            return EXIT_BELOW
    return EXIT_OK


def self_test(suite, cases, use_judge=True) -> list[str]:
    """Free checks: every oracle passes, an empty output fails every case."""
    problems = []
    judge_costs: list[float] = []
    judge = make_judge(suite, judge_costs) if use_judge else None
    for c in cases:
        graders = list(suite["graders"]) + list(c["graders"])
        code_graders = [g for g in graders if g["type"] != "judge" or judge is not None]
        if "oracle" in c:
            for i, g in enumerate(code_graders):
                ok, reason = grade_one(g, c["oracle"], c, judge)
                if ok is not True:
                    problems.append(f"{c['id']}: oracle fails {grader_name(g, i)} ({reason})")
        else:
            problems.append(f"{c['id']}: no oracle (a known-good output); add one so the grader can be tested")
        empty_results = [grade_one(g, {}, c, None) for g in graders if g["type"] != "judge"]
        if empty_results and all(ok is True for ok, _ in empty_results):
            problems.append(f"{c['id']}: an EMPTY output passes every code grader; the case cannot fail")
    return problems


def cmd_check(args) -> int:
    suite = load_suite(args.suite)
    cases = load_cases(suite)
    print(f"suite {suite['name']}: {len(cases)} cases, splits "
          + ", ".join(f"{k}={sum(1 for c in cases if c['split'] == k)}" for k in suite["splits"]))
    problems = self_test(suite, cases, use_judge=not args.no_judge)
    for p in problems:
        print(f"  PROBLEM {p}")
    failed = bool([p for p in problems if "no oracle" not in p])
    if not suite["controls"]:
        print("  WARNING no controls defined. Add a do-nothing and a pushover control to suite.json.")
    for ctl in suite["controls"]:
        rec = execute_run(suite, cases, reps=1, split="all", subset=True, use_judge=not args.no_judge,
                          command=ctl["command"], control=ctl["name"], threshold=None)
        s = rec["summary"]
        ok = s["score"] is not None and s["score"] <= ctl["max_score"]
        print(f"  control {ctl['name']}: score {_fmt(s['score'])} (must be <= {_fmt(ctl['max_score'])}) "
              f"{'ok' if ok else 'TOO HIGH: your graders reward a broken agent'}")
        if s["n_errors"]:
            print(f"    {s['n_errors']} control trials errored: {rec['rows'][0].get('error', '')[:120]}")
        if not ok:
            passed = sorted(c for c, m in rec["case_means"].items() if m > 0)
            print(f"    cases the control passed: {', '.join(passed)}")
            failed = True
    print("check: FAILED" if failed else "check: ok")
    return EXIT_CHECK if failed else EXIT_OK


def cmd_compare(args) -> int:
    p = Path(args.a)
    if p.suffix == ".json" and p.is_file():
        a = json.loads(p.read_text())
        if not args.b:
            raise ConfigError("give two run files, or a suite")
        b = json.loads(Path(args.b).read_text())
    else:
        suite = load_suite(p)
        runs = [r for r in list_runs(out_dir_for(suite, args.out)) if not r.get("subset")]
        if len(runs) < 2:
            print("fewer than two full runs stored; nothing to compare")
            return EXIT_OK
        a, b = runs[-2], runs[-1]
    c = compare(a, b)
    print(json.dumps(c, indent=2))
    return EXIT_OK


def cmd_history(args) -> int:
    suite = load_suite(args.suite)
    runs = list_runs(out_dir_for(suite, args.out))
    if not runs:
        print("no runs stored")
        return EXIT_OK
    print(f"{'run_id':<24} {'split':<6} {'score':>7} {'pass^k':>7} {'err':>4} {'cost':>9}  case_set          label")
    for r in runs:
        s = r["summary"]
        cost = f"${s['total_cost_usd']:.4f}" if s.get("total_cost_usd") is not None else "n/a"
        tag = " (subset)" if r.get("subset") else ""
        print(f"{r['run_id']:<24} {r['split']:<6} {_fmt(s['score']):>7} {_fmt(s['pass_hat_k']):>7} "
              f"{s['n_errors']:>4} {cost:>9}  {r['fingerprint']['case_set_sha']}  {r.get('label') or ''}{tag}")
    return EXIT_OK


def cmd_init(args) -> int:
    src = Path(__file__).resolve().parent.parent / "templates" / "example-suite"
    judge_src = Path(__file__).resolve().parent / "judge_claude.py"
    if not src.is_dir() or not judge_src.is_file():
        raise ConfigError("init needs the example suite and judge_claude.py, which ship with the "
                          "new-eval skill; run init from that skill's copy of evalkit.py")
    dst = Path(args.dir)
    if dst.exists() and any(dst.iterdir()):
        raise ConfigError(f"{dst} exists and is not empty")
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(judge_src, dst / "judge.py")
    print(f"copied example suite to {dst}. Next: python3 {Path(__file__).name} check {dst}")
    return EXIT_OK


def build_parser():
    ap = argparse.ArgumentParser(prog="evalkit", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a suite and write a report")
    r.add_argument("suite")
    r.add_argument("--reps", type=int, help="tries per case (default: suite reps)")
    r.add_argument("--cases", help="comma-separated case ids (a pilot; never a baseline)")
    r.add_argument("--tag", help="only cases with one of these tags (comma-separated)")
    r.add_argument("--split", default="all", choices=["all", "train", "val", "test"])
    r.add_argument("--label", help="a name for this run, e.g. baseline or v2-shorter-prompt")
    r.add_argument("--no-judge", action="store_true", help="skip judge graders (score becomes an upper bound)")
    r.add_argument("--target", help="override the target command for this run (recorded as a subset)")
    r.add_argument("--out", default=".evals", help="results root (default .evals)")
    r.add_argument("--gate", action="store_true", help="exit 4 if score is below the suite threshold")
    r.add_argument("--fail-under", type=float, help="exit 4 if the metric is below this value")
    r.add_argument("--fail-metric", default="score", choices=["score", "pass_hat_k"])
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("check", help="self-test graders with oracles and empty output, run controls")
    c.add_argument("suite")
    c.add_argument("--no-judge", action="store_true")
    c.set_defaults(fn=cmd_check)
    m = sub.add_parser("compare", help="compare the last two runs of a suite, or two run files")
    m.add_argument("a")
    m.add_argument("b", nargs="?")
    m.add_argument("--out", default=".evals")
    m.set_defaults(fn=cmd_compare)
    h = sub.add_parser("history", help="list stored runs")
    h.add_argument("suite")
    h.add_argument("--out", default=".evals")
    h.set_defaults(fn=cmd_history)
    i = sub.add_parser("init", help="copy the example suite to a directory")
    i.add_argument("dir")
    i.set_defaults(fn=cmd_init)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
