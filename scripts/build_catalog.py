#!/usr/bin/env python3
"""build_catalog.py: generate site/catalog.json from the files in this repo.

The website never holds its own copy of an item. Everything it shows (names,
descriptions, maturity, SDLC stage, the "how to use" text, install URLs) is read
here from the plugins on disk, so the site cannot drift from the files.

Reads:
  .claude-plugin/marketplace.json            the plugin list
  plugins/<p>/.claude-plugin/plugin.json     version, keywords
  plugins/<p>/README.md                      maturity and stage tables, disable switches
  plugins/<p>/skills/*/SKILL.md              frontmatter name, description; body
  plugins/<p>/agents/*.md                    frontmatter name, description, tools; body
  plugins/<p>/hooks/hooks.json               event, matcher, command (+ script docstring)
  plugins/<p>/templates/*                    one item per top-level entry
  SDLC.md                                    which items each stage names

Usage:
  python3 scripts/build_catalog.py                 # writes site/catalog.json
  python3 scripts/build_catalog.py --root DIR --out FILE --check

Standard library only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

REPO_SLUG = "ai-foundry-byu/foundry-marketplace"
BRANCH = "main"
RAW_BASE = "https://raw.githubusercontent.com/%s/%s/" % (REPO_SLUG, BRANCH)
BLOB_BASE = "https://github.com/%s/blob/%s/" % (REPO_SLUG, BRANCH)
TREE_BASE = "https://github.com/%s/tree/%s/" % (REPO_SLUG, BRANCH)
SITE_URL = "https://ai-foundry-byu.github.io/foundry-marketplace/"

STAGES = [
    (0, "Scaffold"),
    (1, "Requirements"),
    (2, "PRD + stories"),
    (3, "Workplan"),
    (4, "Execute"),
    (5, "Code QA"),
    (6, "Visual QA with example users"),
    (7, "Ship"),
    (8, "Feedback"),
]

# Fallback when neither SDLC.md nor the README says which stage an item serves.
# Keys are words that appear in README "SDLC stage" cells.
STAGE_KEYWORDS = [
    ("scaffold", 0),
    ("requirements", 1),
    ("prd", 2),
    ("pre-build", 2),
    ("design", 2),
    ("story", 2),
    ("workplan", 3),
    ("plan", 3),
    ("execute", 4),
    ("build", 4),
    ("code qa", 5),
    ("test", 5),
    ("ci", 5),
    ("review", 5),
    ("visual qa", 6),
    ("qa", 6),
    ("verify", 6),
    ("user acceptance", 6),
    ("ship", 7),
    ("operate", 7),
    ("feedback", 8),
    ("improve", 8),
    ("optimize", 8),
]

CATEGORY_DEFAULT_STAGE = {
    "guardrails": [4],
    "qa": [6],
    "devices": [6],
    "design": [6],
    "evals": [8],
    "build": [4],
    "sdlc": [0],
}

# Items that serve every stage rather than one (the router, the always-on hooks).
ALL_STAGE_CATEGORIES = {"guardrails"}
ALL_STAGE_NAMES = {"sdlc"}

TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".js", ".ts",
            ".toml", ".plist", ".ps1", ".html", ".css", ".jsonl", ".csv", ".xml"}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def read_json(path: str) -> Any:
    text = read_text(path)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def norm_key(text: str) -> str:
    """Normalize an item name for matching: `scripts/Foo_bar.py` -> foo-bar."""
    t = text.strip().strip("`").strip()
    t = t.split("/")[-1] if "/" in t and "*" not in t else t
    t = re.sub(r"\.(md|py|sh|json|yaml|yml)$", "", t)
    t = re.sub(r"[\s_]+", "-", t.lower())
    return t.strip("-")


def first_sentence(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > 60 else cut.rstrip() + "...")


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------

def _scalar(value: str) -> Any:
    v = value.strip()
    if not v:
        return ""
    if v[0] in "\"'" and v[-1:] == v[0] and len(v) >= 2:
        inner = v[1:-1]
        if v[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in _split_flow(v[1:-1]) if x.strip()]
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    return v


def _split_flow(s: str) -> List[str]:
    out, cur, quote = [], "", ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse a simple YAML frontmatter block. Returns (fields, body).

    Supports `key: value`, quoted values, `key: [a, b]`, block lists (`- a`),
    and block scalars (`key: >` / `key: |`) plus plain continuation lines.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, text
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    data: Dict[str, Any] = {}
    key: Optional[str] = None
    mode = ""  # "", "block>", "block|", "list", "plain"
    buf: List[str] = []

    def flush() -> None:
        nonlocal buf, key, mode
        if key is None:
            return
        if mode == "block|":
            data[key] = "\n".join(buf).rstrip() + ("\n" if buf else "")
            data[key] = data[key].rstrip("\n")
        elif mode in ("block>", "plain"):
            if mode == "plain":
                if buf:
                    data[key] = " ".join([str(data.get(key, ""))] + buf).strip()
            else:
                data[key] = " ".join(x.strip() for x in buf if x.strip())
        buf = []
        mode = ""

    for raw in fm_lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            if mode == "block|":
                buf.append("")
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):(?:\s+(.*)|\s*)$", raw)
        if m and not raw[0].isspace():
            flush()
            key = m.group(1)
            val = (m.group(2) or "").strip()
            if val in (">", ">-", ">+"):
                mode = "block>"
            elif val in ("|", "|-", "|+"):
                mode = "block|"
            elif val == "":
                data[key] = ""
                mode = "list"
            else:
                data[key] = _scalar(val)
                mode = "plain" if not (val[0] in "\"'[") else ""
            continue
        if key is None:
            continue
        stripped = raw.strip()
        if mode == "list" and stripped.startswith("- "):
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(_scalar(stripped[2:]))
        elif mode == "list" and not isinstance(data.get(key), list):
            mode = "plain"
            buf.append(stripped)
        elif mode in ("block>", "block|", "plain"):
            buf.append(stripped if mode != "block|" else raw[2:] if raw.startswith("  ") else stripped)
    flush()
    return data, body


# --------------------------------------------------------------------------
# README tables (maturity, stage, disable switch)
# --------------------------------------------------------------------------

def split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells, cur, i = [], "", 0
    in_code = False
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def parse_tables(md: str) -> List[Dict[str, Any]]:
    """Every pipe table in a markdown file, with the heading it sits under."""
    tables = []
    lines = md.split("\n")
    heading = ""
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("#"):
            heading = line.lstrip("#").strip()
        if (not in_fence and line.strip().startswith("|") and i + 1 < len(lines)
                and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1])):
            header = [h.lower() for h in split_row(line)]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            tables.append({"heading": heading, "header": header, "rows": rows})
            i = j
            continue
        i += 1
    return tables


def classify_maturity(text: str) -> Optional[str]:
    t = text.strip().strip("*").lower()
    if not t or t in ("n/a", "-"):
        return None
    if t.startswith("new"):
        return "new"
    if "proven" in t:
        return "proven"
    if "new" in t:
        return "new"
    return None


def stages_from_text(cell: str) -> List[int]:
    t = " " + re.sub(r"[()/,;+]", " ", cell.lower()) + " "
    found: List[int] = []
    for word, stage in STAGE_KEYWORDS:
        if re.search(r"(?<![a-z-])" + re.escape(word) + r"(?![a-z-])", t):
            if stage not in found:
                found.append(stage)
            t = t.replace(word, " ")
    return sorted(found)


class ReadmeIndex:
    """Maturity / stage / disable info keyed by normalized item name."""

    def __init__(self, md: str):
        self.md = md
        self.rows: List[Dict[str, Any]] = []
        for tbl in parse_tables(md):
            hdr = tbl["header"]
            if not any("maturity" in h for h in hdr):
                continue
            col = {name: next((k for k, h in enumerate(hdr) if name in h), None)
                   for name in ("maturity", "type", "stage", "disable", "event")}
            col["what"] = next((k for k, h in enumerate(hdr) if h.startswith("what") or "purpose" in h), None)
            for cells in tbl["rows"]:
                if not cells:
                    continue
                def cell(name: str) -> str:
                    k = col[name]
                    return cells[k] if k is not None and k < len(cells) else ""
                names = re.findall(r"`([^`]+)`", cells[0]) or [cells[0]]
                self.rows.append({
                    "keys": [norm_key(n) for n in names],
                    "globs": [n.strip() for n in names if "*" in n],
                    "raw_names": [n.strip().lstrip("./") for n in names],
                    "label": cells[0],
                    "type": (cell("type") or "").lower(),
                    "heading": tbl["heading"].lower(),
                    "maturity_raw": cell("maturity").strip(),
                    "maturity": classify_maturity(cell("maturity")),
                    "stage_raw": cell("stage"),
                    "disable": cell("disable"),
                    "what": cell("what"),
                    "what_header": hdr[col["what"]] if col["what"] is not None else "",
                })

    def lookup(self, name: str, item_type: str, relpath: str = "") -> Optional[Dict[str, Any]]:
        key = norm_key(name)
        for row in self.rows:
            if key in row["keys"] and self._type_ok(row, item_type):
                return row
        for row in self.rows:
            if key in row["keys"] and not self._typed(row):
                return row
        for row in self.rows:
            for g in row["globs"]:
                if relpath and fnmatch.fnmatch(relpath, g.lstrip("./")):
                    return row
        return None

    @staticmethod
    def _type_ok(row: Dict[str, Any], item_type: str) -> bool:
        t = row["type"] or row["heading"]
        if not t:
            return True
        return item_type in t or (item_type == "template" and "doc" in t)

    @staticmethod
    def _typed(row: Dict[str, Any]) -> bool:
        t = row["type"] or row["heading"]
        return any(w in t for w in ("skill", "agent", "hook", "template", "script", "doc", "mcp"))

    def rows_under(self, dir_relpath: str, files_rel: List[str]) -> List[Dict[str, Any]]:
        """Rows naming a file inside a template directory (by path or glob)."""
        out = []
        for row in self.rows:
            for n in row["raw_names"]:
                if n.startswith(dir_relpath.rstrip("/") + "/") or any(
                        fnmatch.fnmatch(f, n) for f in files_rel):
                    out.append(row)
                    break
        return out

    def rows_of_type(self, item_type: str) -> List[Dict[str, Any]]:
        return [r for r in self.rows if item_type in (r["type"] or r["heading"])]

    def section(self, name: str) -> str:
        """Text of the README section whose heading mentions `name`."""
        key = norm_key(name)
        parts = re.split(r"\n(?=#{2,4} )", self.md)
        for p in parts:
            head = p.split("\n", 1)[0]
            if key and key in norm_key(re.sub(r"\(.*?\)", "", head.lstrip("#"))):
                return p
        return ""


def maturity_line(body: str) -> Optional[Tuple[str, str]]:
    m = re.search(r"(?im)^\s*\**maturity\**\s*:\s*\**\s*([^\n]+)", body)
    if not m:
        return None
    raw = m.group(1).strip()
    cls = classify_maturity(raw)
    return (cls, raw) if cls else None


def env_switch(text: str) -> Optional[str]:
    m = re.search(r"\b([A-Z][A-Z0-9_]{3,})=0\b", text or "")
    return m.group(1) + "=0" if m else None


# --------------------------------------------------------------------------
# SDLC.md stage mapping
# --------------------------------------------------------------------------

def parse_sdlc(md: str) -> Tuple[Dict[str, List[int]], Dict[int, Dict[str, str]]]:
    """Which backticked names each `### N. Title` section mentions, and its goal/gate."""
    names: Dict[str, List[int]] = {}
    info: Dict[int, Dict[str, str]] = {}
    for m in re.finditer(r"(?m)^###\s+(\d)\.\s+(.+)$", md):
        stage = int(m.group(1))
        start = m.end()
        nxt = re.search(r"(?m)^#{2,3}\s", md[start:])
        section = md[start: start + nxt.start()] if nxt else md[start:]
        meta = {}
        for label in ("Goal", "Gate", "Artifact"):
            g = re.search(r"\*\*%s:\*\*\s*(.+)" % label, section)
            if g:
                meta[label.lower()] = g.group(1).strip()
        info[stage] = meta
        for tok in re.findall(r"`([^`]+)`", section):
            k = norm_key(tok)
            if not k or len(k) < 3:
                continue
            names.setdefault(k, [])
            if stage not in names[k]:
                names[k].append(stage)
    return names, info


# --------------------------------------------------------------------------
# items
# --------------------------------------------------------------------------

def list_files(root: str, directory: str) -> List[str]:
    out = []
    for dp, dns, fns in os.walk(directory):
        dns[:] = sorted(d for d in dns if not d.startswith(".") and d != "__pycache__")
        for fn in sorted(fns):
            if fn.startswith(".") or fn.endswith(".pyc"):
                continue
            out.append(os.path.join(dp, fn))
    return out


def docstring(path: str) -> str:
    text = read_text(path)
    if not text:
        return ""
    m = re.match(r'(?s)\A(?:#![^\n]*\n)?(?:#[^\n]*coding[^\n]*\n)?\s*(?:[rubRUB]{0,2})("""|\'\'\')(.*?)\1', text)
    if m:
        return m.group(2).strip()
    lines = text.split("\n")
    out = []
    for ln in lines[1:] if lines and lines[0].startswith("#!") else lines:
        if ln.startswith("#"):
            out.append(ln.lstrip("#").rstrip()[1:] if ln.startswith("# ") else ln.lstrip("#"))
        elif not ln.strip() and not out:
            continue
        else:
            break
    return "\n".join(out).strip()


def file_entry(root: str, path: str, base: str) -> Dict[str, str]:
    r = rel(root, path)
    return {"path": os.path.relpath(path, base).replace(os.sep, "/"), "repo_path": r,
            "raw_url": RAW_BASE + r}


def resolve(meta_row: Optional[Dict[str, Any]], body: str) -> Tuple[str, str]:
    line = maturity_line(body)
    if line:
        return line[0], line[1]
    if meta_row and meta_row["maturity"]:
        return meta_row["maturity"], meta_row["maturity_raw"]
    return "unlabeled", ""


def assign_stages(name: str, frontmatter: Dict[str, Any], row: Optional[Dict[str, Any]],
                  sdlc_names: Dict[str, List[int]], category: str,
                  aliases: Tuple[str, ...] = ()) -> List[int]:
    fm = frontmatter.get("stage") or frontmatter.get("sdlc_stage")
    if fm not in (None, ""):
        vals = fm if isinstance(fm, list) else re.findall(r"\d", str(fm))
        got = sorted({int(v) for v in vals if str(v).isdigit() and 0 <= int(v) <= 8})
        if got:
            return got
    for k in (norm_key(name),) + tuple(norm_key(a) for a in aliases):
        if k in sdlc_names:
            return sorted(sdlc_names[k])
    if row and row.get("stage_raw"):
        got = stages_from_text(row["stage_raw"])
        if got:
            return got
    return list(CATEGORY_DEFAULT_STAGE.get(category, []))


def build_plugin(root: str, entry: Dict[str, Any], sdlc_names: Dict[str, List[int]],
                 marketplace: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    name = entry.get("name", "")
    src = entry.get("source")
    category = entry.get("category", "")
    plugin: Dict[str, Any] = {
        "name": name,
        "description": entry.get("description", ""),
        "category": category,
        "tags": entry.get("tags", []) or [],
        "starter": "starter" in (entry.get("tags") or []),
        "install": ["/plugin marketplace add %s" % REPO_SLUG,
                    "/plugin install %s@%s" % (name, marketplace)],
    }
    if not isinstance(src, str):
        repo = ""
        if isinstance(src, dict):
            repo = src.get("repo") or src.get("url") or ""
            if src.get("path"):
                repo = repo + " (" + src["path"] + ")"
        url = entry.get("homepage") or (
            "https://github.com/" + src["repo"] if isinstance(src, dict) and src.get("repo") else "")
        plugin.update({"external": True, "source_repo": repo, "url": url,
                       "maturity": "external", "readme": "", "counts": {}})
        item = {
            "id": "%s/%s" % (name, name), "plugin": name, "type": "plugin", "name": name,
            "slug": name, "description": entry.get("description", ""), "stages": [],
            "maturity": "external", "maturity_note": "Maintained in its own repository.",
            "body": "", "source_url": url, "raw_url": "", "files": [], "external": True,
            "external_repo": repo, "needs_plugin": True, "tags": plugin["tags"],
        }
        return plugin, [item]

    pdir = os.path.normpath(os.path.join(root, src))
    manifest = read_json(os.path.join(pdir, ".claude-plugin", "plugin.json")) or {}
    readme = read_text(os.path.join(pdir, "README.md"))
    idx = ReadmeIndex(readme)
    plugin.update({
        "external": False,
        "path": rel(root, pdir),
        "version": manifest.get("version", ""),
        "keywords": manifest.get("keywords", []) or [],
        "license": manifest.get("license", ""),
        "url": TREE_BASE + rel(root, pdir),
        "readme": readme,
        "readme_url": BLOB_BASE + rel(root, os.path.join(pdir, "README.md")),
    })
    items: List[Dict[str, Any]] = []

    def add(item_type: str, iname: str, desc: str, body: str, path: str, files: List[Dict[str, str]],
            fm: Dict[str, Any], extra: Optional[Dict[str, Any]] = None, aliases: Tuple[str, ...] = ()) -> None:
        r = rel(root, path)
        row = idx.lookup(iname, item_type, rel(pdir, path))
        for a in aliases:
            row = row or idx.lookup(a, item_type, rel(pdir, path))
        mat, note = resolve(row, body)
        if mat == "unlabeled" and fm.get("maturity"):
            c = classify_maturity(str(fm["maturity"]))
            if c:
                mat, note = c, str(fm["maturity"])
        it = {
            "id": "%s/%s" % (name, iname), "plugin": name, "type": item_type, "name": iname,
            "slug": iname, "description": desc or (row["what"] if row else ""),
            "stages": assign_stages(iname, fm, row, sdlc_names, category, aliases),
            "maturity": mat, "maturity_note": note, "body": body,
            "path": r, "source_url": BLOB_BASE + r, "raw_url": RAW_BASE + r if os.path.isfile(path) else "",
            "files": files, "external": False,
            "needs_plugin": "CLAUDE_PLUGIN_ROOT" in body, "tags": plugin["tags"],
        }
        if extra:
            it.update(extra)
        items.append(it)

    # skills
    sroot = os.path.join(pdir, "skills")
    for d in sorted(os.listdir(sroot)) if os.path.isdir(sroot) else []:
        sk = os.path.join(sroot, d, "SKILL.md")
        if not os.path.isfile(sk):
            continue
        fm, body = parse_frontmatter(read_text(sk))
        sdir = os.path.dirname(sk)
        files = [file_entry(root, f, sdir) for f in list_files(root, sdir)]
        files.sort(key=lambda f: (f["path"] != "SKILL.md", f["path"]))
        add("skill", str(fm.get("name") or d), str(fm.get("description", "")), body, sk, files, fm,
            aliases=(d,))

    # agents
    aroot = os.path.join(pdir, "agents")
    for fn in sorted(os.listdir(aroot)) if os.path.isdir(aroot) else []:
        if not fn.endswith(".md"):
            continue
        ap = os.path.join(aroot, fn)
        fm, body = parse_frontmatter(read_text(ap))
        tools = fm.get("tools", "")
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        add("agent", str(fm.get("name") or fn[:-3]), str(fm.get("description", "")), body, ap,
            [file_entry(root, ap, aroot)], fm,
            extra={"tools": tools, "model": fm.get("model", "")}, aliases=(fn[:-3],))

    # hooks
    hooks_path = os.path.join(pdir, "hooks", "hooks.json")
    hooks_doc = read_json(hooks_path)
    if hooks_doc is None and isinstance(manifest.get("hooks"), dict):
        hooks_doc, hooks_path = {"hooks": manifest["hooks"]}, os.path.join(pdir, ".claude-plugin", "plugin.json")
    hooks_map = (hooks_doc or {}).get("hooks", {}) if isinstance(hooks_doc, dict) else {}
    hook_items: Dict[str, Dict[str, Any]] = {}
    for event, groups in hooks_map.items() if isinstance(hooks_map, dict) else []:
        for grp in groups or []:
            matcher = grp.get("matcher", "") if isinstance(grp, dict) else ""
            for h in (grp.get("hooks", []) if isinstance(grp, dict) else []):
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                args_ = h.get("args") if isinstance(h, dict) else None
                if isinstance(args_, list) and args_:
                    cmd = " ".join([cmd] + ['"%s"' % a if " " in a or "$" in a else a for a in map(str, args_)])
                m = re.search(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/([^\"'\s]+)", cmd)
                script_rel = m.group(1) if m else ""
                script = os.path.join(pdir, script_rel) if script_rel else ""
                base = os.path.basename(script_rel) if script_rel else event
                hname = norm_key(re.sub(r"\.[a-z]+$", "", base))
                rec = hook_items.setdefault(hname, {"triggers": [], "script": script, "script_rel": script_rel})
                rec["triggers"].append({"event": event, "matcher": matcher, "command": cmd,
                                        "timeout": h.get("timeout") if isinstance(h, dict) else None})
    unmatched_rows = [r for r in idx.rows_of_type("hook")]
    for hname, rec in hook_items.items():
        script = rec["script"]
        doc = docstring(script) if script and os.path.isfile(script) else ""
        row = idx.lookup(hname, "hook")
        if row is None:
            # A README may label the hook in words ("SessionStart stage hint").
            free = [r for r in unmatched_rows if not any(k in hook_items for k in r["keys"])]
            if len(free) == 1 and len(hook_items) == 1:
                row = free[0]
        section = idx.section(hname) or (idx.section(row["label"]) if row else "")
        disable = env_switch(row["disable"]) if row and row.get("disable") else None
        disable = disable or env_switch(section) or env_switch(doc)
        what = row["what"] if row and row["what"] else ""
        if what and "block" in row.get("what_header", "") and not what.lower().startswith("block"):
            what = "Blocks " + (what[0].lower() + what[1:] if what[:1].isupper() and (what[1:2].islower() or what[1:2] == " ") else what)
        desc = what or first_sentence(
            re.sub(r"^[\w.-]+:\s*", "", doc.split("\n\n")[0]) if doc else "") or (hooks_doc or {}).get("description", "")
        body_parts = []
        if section:
            body_parts.append(section.strip())
        if doc:
            body_parts.append("### From the script header\n\n```text\n" + doc + "\n```")
        files = [file_entry(root, hooks_path, pdir)]
        if script and os.path.isfile(script):
            files.append(file_entry(root, script, pdir))
        add("hook", hname, desc, "\n\n".join(body_parts), script if script and os.path.isfile(script) else hooks_path,
            files, {}, extra={"triggers": rec["triggers"], "disable": disable or "",
                              "script_doc": doc},
            aliases=((row["label"],) if row else ()))
        # hooks always need the plugin; the README's text may not mention CLAUDE_PLUGIN_ROOT
        items[-1]["needs_plugin"] = True

    # templates
    troot = os.path.join(pdir, "templates")
    tmpl_rows = idx.rows_of_type("template")
    tmpl_classes = {r["maturity"] for r in tmpl_rows if r["maturity"]}
    for entry_name in sorted(os.listdir(troot)) if os.path.isdir(troot) else []:
        if entry_name.startswith("."):
            continue
        tp = os.path.join(troot, entry_name)
        if os.path.isdir(tp):
            files = [file_entry(root, f, troot) for f in list_files(root, tp)]
            readme_t = os.path.join(tp, "README.md")
            body = read_text(readme_t) if os.path.isfile(readme_t) else ""
            if not body:
                body = "Files:\n\n" + "\n".join("- `%s`" % f["path"] for f in files)
        else:
            files = [file_entry(root, tp, troot)]
            raw = read_text(tp)
            ext = os.path.splitext(entry_name)[1].lower()
            if ext == ".md":
                body = raw
            elif ext in TEXT_EXT and raw:
                lang = {".yml": "yaml", ".jsonl": "json"}.get(ext, ext.lstrip("."))
                body = "```%s\n%s\n```" % (lang, raw.rstrip())
            else:
                body = ""
        tname = entry_name
        row = idx.lookup(tname, "template", rel(pdir, tp)) or idx.lookup("templates/" + tname, "template", rel(pdir, tp))
        if row is None and os.path.isdir(tp):
            sub = idx.rows_under(rel(pdir, tp), [rel(pdir, os.path.join(root, f["repo_path"])) for f in files])
            if sub:
                mats_ = {r["maturity"] for r in sub if r["maturity"]}
                row = dict(sub[0])
                row["what"] = " ".join(dict.fromkeys(
                    r["what"].rstrip(".") + "." for r in sub if r["what"]))
                row["maturity"] = mats_.pop() if len(mats_) == 1 else (sub[0]["maturity"])
        if row is None and len(tmpl_classes) == 1:
            row = {"maturity": tmpl_classes.pop(), "maturity_raw": "", "stage_raw": tmpl_rows[0]["stage_raw"],
                   "what": "", "label": ""}
            tmpl_classes = {row["maturity"]}
        desc = (row["what"] if row and row.get("what") else "")
        if not desc:
            fm_t, b_t = parse_frontmatter(body) if body.startswith("---") else ({}, body)
            desc = str(fm_t.get("description", "")) or ""
            if not desc:
                for ln in b_t.split("\n"):
                    s = ln.strip()
                    if (s and not s.startswith(("#", "```", "|", "-", "<!--", "{", "[", "*", ">"))
                            and "{{" not in s and not re.match(r"^[\w$\"-]+\s*:", s)):
                        desc = first_sentence(s, 200)
                        break
        mat, note = (row["maturity"], row.get("maturity_raw", "")) if row and row.get("maturity") else ("unlabeled", "")
        r = rel(root, tp)
        items.append({
            "id": "%s/%s" % (name, tname), "plugin": name, "type": "template", "name": tname,
            "slug": tname, "description": desc,
            "stages": assign_stages(tname, {}, row, sdlc_names, category),
            "maturity": mat, "maturity_note": note, "body": body, "path": r,
            "source_url": (TREE_BASE if os.path.isdir(tp) else BLOB_BASE) + r,
            "raw_url": RAW_BASE + r if os.path.isfile(tp) else "",
            "files": files, "external": False, "needs_plugin": False, "tags": plugin["tags"],
        })

    for it in items:
        it["all_stages"] = bool(it["name"] in ALL_STAGE_NAMES or category in ALL_STAGE_CATEGORIES)
        if it["name"] in ALL_STAGE_NAMES:
            it["stages"] = []

    # unique slugs inside a plugin
    seen: Dict[str, int] = {}
    for it in items:
        seen[it["slug"]] = seen.get(it["slug"], 0) + 1
    for it in items:
        if seen[it["slug"]] > 1:
            it["slug"] = "%s-%s" % (it["slug"], it["type"])
        it["id"] = "%s/%s" % (name, it["slug"])
    counts: Dict[str, int] = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    plugin["counts"] = counts
    mats = {it["maturity"] for it in items}
    plugin["maturity"] = "proven" if mats == {"proven"} else ("new" if mats == {"new"} else "mixed")
    return plugin, items


def build(root: str) -> Dict[str, Any]:
    mp = read_json(os.path.join(root, ".claude-plugin", "marketplace.json"))
    if not isinstance(mp, dict):
        raise SystemExit("error: .claude-plugin/marketplace.json is missing or not valid JSON")
    marketplace = mp.get("name", "")
    sdlc_md = read_text(os.path.join(root, "SDLC.md"))
    sdlc_names, sdlc_info = parse_sdlc(sdlc_md)
    plugins, items = [], []
    for entry in mp.get("plugins", []) or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        p, its = build_plugin(root, entry, sdlc_names, marketplace)
        plugins.append(p)
        items.extend(its)
    stages = []
    for sid, sname in STAGES:
        meta = sdlc_info.get(sid, {})
        stages.append({"id": sid, "name": sname, "goal": meta.get("goal", ""),
                       "gate": meta.get("gate", ""), "artifact": meta.get("artifact", "")})
    return {
        "schema": 1,
        "marketplace": {
            "name": marketplace,
            "description": mp.get("description", ""),
            "owner": mp.get("owner", {}),
            "version": (mp.get("metadata") or {}).get("version", ""),
            "repo": REPO_SLUG,
            "repo_url": "https://github.com/" + REPO_SLUG,
            "site_url": SITE_URL,
            "raw_base": RAW_BASE,
            "blob_base": BLOB_BASE,
            "contributing_url": BLOB_BASE + "CONTRIBUTING.md",
            "sdlc_url": BLOB_BASE + "SDLC.md",
        },
        "stages": stages,
        "plugins": plugins,
        "items": items,
    }


def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(here), help="repo root (default: parent of scripts/)")
    ap.add_argument("--out", default=None, help="output path (default: <root>/site/catalog.json)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the output file is stale")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    out = args.out or os.path.join(root, "site", "catalog.json")
    data = build(root)
    text = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    if args.check:
        if read_text(out) != text:
            print("catalog is stale: run python3 scripts/build_catalog.py", file=sys.stderr)
            return 1
        print("catalog is current")
        return 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    by_type: Dict[str, int] = {}
    for it in data["items"]:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    unl = [it["id"] for it in data["items"] if it["maturity"] == "unlabeled"]
    nostage = [it["id"] for it in data["items"]
               if not it["stages"] and not it["external"] and not it.get("all_stages")]
    print("wrote %s: %d plugins, %d items %s" % (rel(root, out), len(data["plugins"]), len(data["items"]),
                                                json.dumps(by_type, sort_keys=True)))
    if unl:
        print("unlabeled maturity: " + ", ".join(unl))
    if nostage:
        print("no SDLC stage: " + ", ".join(nostage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
