#!/usr/bin/env python3
"""check_items.py: enforce the item rules (R1-R3 in CONTRIBUTING.md) over every plugin.

Every skill must work installed through its plugin AND copied on its own, and
every agent must say which skill it needs when it is copied on its own.

Checks, per plugin under plugins/:
  R1a  a SKILL.md contains ${CLAUDE_PLUGIN_ROOT} but has no
       "Install: plugin only. <reason>." line right under its H1 title
  R1b  a ${CLAUDE_SKILL_DIR}/<path> in a SKILL.md does not exist inside that skill folder
  R1m  an "Install: plugin only." or "Requires skill:" line that is not right under the H1
  R2c  a vendor.json entry whose canonical source is missing, whose copy is missing,
       or whose copy is not byte-identical to the source
  R2f  a vendored .py imports a sibling module of its canonical source that is not
       next to the copy (or is there but differs and is not vendored)
  R2g  a script inside a skill folder reads ${CLAUDE_PLUGIN_ROOT} (find siblings via __file__)
  R3d  an agent with a locate snippet has no "Requires skill:" line, names a skill that is
       not in the same plugin, or uses a skill in a snippet that it does not list;
       or a snippet does not have the exact shape
  R3e  an agent references ${CLAUDE_PLUGIN_ROOT} outside a locate snippet and is not
       marked "Install: plugin only."
  R5a  a SKILL.md "Uses agent:" line names an agent that is not in this plugin's agents/
  R5b  a skill that installs on its own names a plugin-only agent in "Uses agent:"

Checks over the whole catalog (only when .claude-plugin/marketplace.json exists):
  E1   evidence/evidence.json is missing or is not a JSON object
  E2   a catalog item has no evidence entry ("<plugin>/<type>/<name>")
  E3   an evidence entry has a label other than verified, beta or new, or no note or date
  E4   an evidence entry names no catalog item

Output: one line per violation, "path:line: rule: message", paths relative to the
repo root. Exit 1 on any violation, 0 when clean.

Usage:
  python3 scripts/check_items.py                 # every plugin under plugins/
  python3 scripts/check_items.py --json
  python3 scripts/check_items.py --root DIR [--plugin NAME ...]

Standard library only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

PLUGIN_ONLY_PREFIX = "Install: plugin only."
REQUIRES_PREFIX = "Requires skill:"
USES_AGENT_PREFIX = "Uses agent:"  # "Uses agents:" is accepted too
MARKERS = (PLUGIN_ONLY_PREFIX, REQUIRES_PREFIX, USES_AGENT_PREFIX)

EVIDENCE_REL = "evidence/evidence.json"
EVIDENCE_LABELS = ("verified", "beta", "new")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PLUGIN_ROOT_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}|\$CLAUDE_PLUGIN_ROOT\b")
SKILL_DIR_REF_RE = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/([^\s\"'`)\]>;,|]*)")
# The locate snippet from R3, with any NAME_DIR variable and any skill name. The user-level
# fallback honors CLAUDE_CONFIG_DIR, where Claude Code reads user skills when it is set.
SNIPPET_RE = re.compile(
    r'(?P<var>[A-Z][A-Z0-9_]*)="\$\{CLAUDE_PLUGIN_ROOT\}/skills/(?P<a>[A-Za-z0-9._-]+)"; '
    r'\[ -d "\$(?P=var)" \] \|\| (?P=var)="\$\(ls -d \.claude/skills/(?P<b>[A-Za-z0-9._-]+) '
    r'"\$\{CLAUDE_CONFIG_DIR:-\$HOME/\.claude\}/skills/(?P<c>[A-Za-z0-9._-]+)" 2>/dev/null \| head -1\)"')
# The PowerShell form for Windows agents: the assignment line, then a fallback line that
# checks .claude/skills/<name> and $HOME/.claude/skills/<name>.
PS_SNIPPET_RE = re.compile(r'^\s*\$(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"\$\{CLAUDE_PLUGIN_ROOT\}/skills/(?P<a>[A-Za-z0-9._-]+)"\s*$')
SNIPPET_HINT_RE = re.compile(r'[A-Z][A-Z0-9_]*="\$\{CLAUDE_PLUGIN_ROOT\}/skills/')
SCRIPT_EXT = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl"}
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}


class Violation:
    __slots__ = ("path", "line", "rule", "message")

    def __init__(self, path: str, line: int, rule: str, message: str):
        self.path, self.line, self.rule, self.message = path, line, rule, message

    def text(self) -> str:
        return "%s:%d: %s: %s" % (self.path, self.line, self.rule, self.message)

    def as_dict(self) -> Dict[str, object]:
        return {"path": self.path, "line": self.line, "rule": self.rule, "message": self.message}


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def body_start(lines: List[str]) -> int:
    """Index of the first line after a leading --- frontmatter block (0 if none)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                return i + 1
    return 0


def fence_mask(lines: List[str]) -> List[bool]:
    """True for each line inside (or opening/closing) a ``` or ~~~ fence."""
    out, fence = [], ""
    for ln in lines:
        s = ln.strip()
        if fence:
            out.append(True)
            if s.startswith(fence):
                fence = ""
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]
            out.append(True)
            continue
        out.append(False)
    return out


def marker_of(line: str) -> Optional[str]:
    """The marker prefix a stripped line starts with, or None."""
    if line.startswith("Uses agents:"):
        return USES_AGENT_PREFIX
    return next((p for p in MARKERS if line.startswith(p)), None)


def header_markers(lines: List[str]) -> Tuple[Dict[str, Tuple[int, str]], Dict[str, int]]:
    """Find the marker lines that sit right under the H1 title.

    Returns (under_title, elsewhere): each maps a prefix to (line number, text) for the
    markers in the header block, and to the line number for markers found anywhere else.
    The header block is the run of blank lines and marker lines straight after the
    first H1 (or after the frontmatter when the file has no H1).
    """
    start = body_start(lines)
    mask = fence_mask(lines)
    h1 = None
    for i in range(start, len(lines)):
        if not mask[i] and re.match(r"^#\s+\S", lines[i]):
            h1 = i
            break
    i = (h1 + 1) if h1 is not None else start
    under: Dict[str, Tuple[int, str]] = {}
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        hit = marker_of(s)
        if hit is None or hit in under:
            break
        under[hit] = (i + 1, s)
        i += 1
    elsewhere: Dict[str, int] = {}
    for j in range(start, len(lines)):
        if mask[j]:
            continue
        p = marker_of(lines[j].strip())
        if p and not (p in under and under[p][0] == j + 1):
            elsewhere.setdefault(p, j + 1)
    return under, elsewhere


def plugin_only_reason(text: str) -> str:
    """The reason after "Install: plugin only." under the H1, or "" when not marked."""
    under, _ = header_markers(text.split("\n"))
    if PLUGIN_ONLY_PREFIX not in under:
        return ""
    return under[PLUGIN_ONLY_PREFIX][1][len(PLUGIN_ONLY_PREFIX):].strip()


def is_plugin_only(text: str) -> bool:
    under, _ = header_markers(text.split("\n"))
    return PLUGIN_ONLY_PREFIX in under


def marker_names(text: str, prefix: str) -> List[str]:
    """Comma-separated names from a marker line under the H1 (anywhere as a fallback)."""
    lines = text.split("\n")
    under, elsewhere = header_markers(lines)
    if prefix in under:
        raw = under[prefix][1]
    elif prefix in elsewhere:
        raw = lines[elsewhere[prefix] - 1].strip()
    else:
        return []
    names = raw.split(":", 1)[1].strip().rstrip(".")
    return [n.strip().strip("`") for n in names.split(",") if n.strip().strip("`")]


def requires_skills(text: str) -> List[str]:
    """Skill names from the "Requires skill:" line under the H1 (anywhere as a fallback)."""
    return marker_names(text, REQUIRES_PREFIX)


def uses_agents(text: str) -> List[str]:
    """Agent names from a skill's "Uses agent:" line under the H1 (anywhere as a fallback)."""
    return marker_names(text, USES_AGENT_PREFIX)


def marker_line(text: str, prefix: str) -> int:
    """1-based line of a marker (under the H1 first), or 1 when it is absent."""
    under, elsewhere = header_markers(text.split("\n"))
    return under[prefix][0] if prefix in under else elsewhere.get(prefix, 1)


def snippet_skills(text: str) -> List[str]:
    """Skill folder names used by well-formed locate snippets, in order."""
    out: List[str] = []
    for m in SNIPPET_RE.finditer(text):
        if m.group("a") == m.group("b") == m.group("c") and m.group("a") not in out:
            out.append(m.group("a"))
    return out


def agent_files(pdir: str) -> Dict[str, str]:
    """Map every name an agent answers to (file stem and frontmatter name) -> its .md path."""
    out: Dict[str, str] = {}
    aroot = os.path.join(pdir, "agents")
    if not os.path.isdir(aroot):
        return out
    for fn in sorted(os.listdir(aroot)):
        if not fn.endswith(".md"):
            continue
        ap = os.path.join(aroot, fn)
        out[fn[:-3]] = ap
        m = re.search(r"(?m)^name:\s*['\"]?([A-Za-z0-9._-]+)", read_text(ap).split("\n---", 1)[0])
        if m:
            out.setdefault(m.group(1), ap)
    return out


def walk_files(directory: str) -> List[str]:
    out = []
    for dp, dns, fns in os.walk(directory):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            if not fn.endswith(".pyc"):
                out.append(os.path.join(dp, fn))
    return out


def skill_names(pdir: str) -> Dict[str, str]:
    """Map every name a skill answers to (folder name and frontmatter name) -> folder."""
    out: Dict[str, str] = {}
    sroot = os.path.join(pdir, "skills")
    if not os.path.isdir(sroot):
        return out
    for d in sorted(os.listdir(sroot)):
        sk = os.path.join(sroot, d, "SKILL.md")
        if not os.path.isfile(sk):
            continue
        out[d] = d
        m = re.search(r"(?m)^name:\s*['\"]?([A-Za-z0-9._-]+)", read_text(sk).split("\n---", 1)[0])
        if m:
            out.setdefault(m.group(1), d)
    return out


class Checker:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.violations: List[Violation] = []

    def rel(self, path: str) -> str:
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def add(self, path: str, line: int, rule: str, message: str) -> None:
        self.violations.append(Violation(self.rel(path), line, rule, message))

    # ---------------------------------------------------------------- plugins
    def plugins(self, only: Optional[List[str]] = None) -> List[str]:
        proot = os.path.join(self.root, "plugins")
        if not os.path.isdir(proot):
            return []
        out = []
        for d in sorted(os.listdir(proot)):
            p = os.path.join(proot, d)
            if os.path.isdir(p) and not d.startswith(".") and (not only or d in only):
                out.append(p)
        return out

    def run(self, only: Optional[List[str]] = None) -> List[Violation]:
        for pdir in self.plugins(only):
            self.check_plugin(pdir)
        if os.path.isfile(os.path.join(self.root, ".claude-plugin", "marketplace.json")):
            self.check_evidence(only)
        self.violations.sort(key=lambda v: (v.path, v.line, v.rule))
        return self.violations

    def check_plugin(self, pdir: str) -> None:
        agents = agent_files(pdir)
        sroot = os.path.join(pdir, "skills")
        if os.path.isdir(sroot):
            for d in sorted(os.listdir(sroot)):
                sdir = os.path.join(sroot, d)
                if os.path.isfile(os.path.join(sdir, "SKILL.md")):
                    self.check_skill(sdir, agents)
        names = skill_names(pdir)
        aroot = os.path.join(pdir, "agents")
        if os.path.isdir(aroot):
            for fn in sorted(os.listdir(aroot)):
                if fn.endswith(".md"):
                    self.check_agent(os.path.join(aroot, fn), names)
        self.check_vendor(pdir)

    # ---------------------------------------------------------------- skills
    def check_skill(self, sdir: str, agents: Optional[Dict[str, str]] = None) -> None:
        sk = os.path.join(sdir, "SKILL.md")
        text = read_text(sk)
        lines = text.split("\n")
        under, elsewhere = header_markers(lines)
        plugin_only = PLUGIN_ONLY_PREFIX in under
        self._misplaced(sk, under, elsewhere)
        if plugin_only and not under[PLUGIN_ONLY_PREFIX][1][len(PLUGIN_ONLY_PREFIX):].strip():
            self.add(sk, under[PLUGIN_ONLY_PREFIX][0], "R1a",
                     'the "Install: plugin only." line needs a one-sentence reason after it')
        real_sdir = os.path.realpath(sdir)
        for n, ln in enumerate(lines, 1):
            if not plugin_only and PLUGIN_ROOT_RE.search(ln):
                self.add(sk, n, "R1a", "SKILL.md uses ${CLAUDE_PLUGIN_ROOT}, which stays literal when the "
                         "skill is copied on its own; move the file into this skill folder and use "
                         '${CLAUDE_SKILL_DIR}, or add "Install: plugin only. <reason>." under the title')
            for m in SKILL_DIR_REF_RE.finditer(ln):
                ref = m.group(1).rstrip(".:,")
                if not ref or any(c in ref for c in "<>*{}$?[") or ref.startswith("..."):
                    continue
                target = os.path.realpath(os.path.join(sdir, ref))
                if not (target == real_sdir or target.startswith(real_sdir + os.sep)):
                    self.add(sk, n, "R1b", "${CLAUDE_SKILL_DIR}/%s points outside the skill folder" % ref)
                elif not os.path.exists(target):
                    self.add(sk, n, "R1b", "${CLAUDE_SKILL_DIR}/%s does not exist in %s" % (ref, self.rel(sdir)))
        self.check_uses_agents(sk, text, plugin_only, agents or {})
        if plugin_only:
            return
        for f in walk_files(sdir):
            if os.path.splitext(f)[1].lower() not in SCRIPT_EXT:
                continue
            if "/tests/" in f.replace(os.sep, "/")[len(sdir):]:
                continue
            for n, ln in enumerate(read_text(f).split("\n"), 1):
                if "CLAUDE_PLUGIN_ROOT" in ln:
                    self.add(f, n, "R2g", "script reads CLAUDE_PLUGIN_ROOT, which is unset when the skill is "
                             "copied on its own; find sibling files via __file__")
                    break

    def check_uses_agents(self, sk: str, text: str, plugin_only: bool, agents: Dict[str, str]) -> None:
        """R5: the agents a skill hands work to are in this plugin, so a single-skill install can bring them."""
        n = marker_line(text, USES_AGENT_PREFIX)
        for name in uses_agents(text):
            ap = agents.get(name)
            if ap is None:
                self.add(sk, n, "R5a", 'uses agent "%s", which is not in this plugin\'s agents/; name an agent '
                         "of this plugin here, and mention agents from other plugins in the text instead (a single-skill "
                         "install cannot bring them along)" % name)
            elif not plugin_only and is_plugin_only(read_text(ap)):
                self.add(sk, n, "R5b", 'uses agent "%s", which is plugin only, so a copy of this skill cannot bring '
                         'it along; mark the skill "Install: plugin only. <reason>." or drop the agent' % name)

    # ---------------------------------------------------------------- evidence
    def check_evidence(self, only: Optional[List[str]] = None) -> None:
        """E1-E4: every catalog item has an entry in evidence/evidence.json, and every entry is well formed."""
        import build_catalog  # late import: build_catalog imports this module

        path = os.path.join(self.root, EVIDENCE_REL)
        raw = read_text(path)
        if not raw.strip():
            self.add(path, 1, "E1", "%s is missing; it holds the tested label for every catalog item" % EVIDENCE_REL)
            return
        try:
            data = json.loads(raw)
        except ValueError as e:
            self.add(path, 1, "E1", "%s is not valid JSON: %s" % (EVIDENCE_REL, e))
            return
        if not isinstance(data, dict):
            self.add(path, 1, "E1", '%s must be an object {"<plugin>/<type>/<name>": {...}}' % EVIDENCE_REL)
            return
        try:
            catalog = build_catalog.build(self.root)
        except SystemExit:
            return  # an unreadable marketplace.json is reported by claude plugin validate
        elines = raw.split("\n")

        def line_of(key: str) -> int:
            needle = json.dumps(key)
            return next((i for i, ln in enumerate(elines, 1) if needle in ln), 1)

        def wanted(plugin: str) -> bool:
            return not only or plugin in only

        keys = set()
        for it in catalog["items"]:
            key = build_catalog.evidence_key(it)
            keys.add(key)
            if wanted(it["plugin"]) and build_catalog.find_evidence(data, it) is None:
                self.add(path, 1, "E2", 'no entry for catalog item "%s"; add {"label": "new", "note": "<what was '
                         'tested>", "date": "YYYY-MM-DD"} under that key' % key)
            keys.add("%s/%s/%s" % (it["plugin"], it["type"], it.get("slug", it["name"])))
        for key, ev in data.items():
            if not wanted(key.split("/", 1)[0]):
                continue
            n = line_of(key)
            if key not in keys:
                self.add(path, n, "E4", '"%s" names no catalog item (keys are <plugin>/<type>/<name>)' % key)
            if not isinstance(ev, dict):
                self.add(path, n, "E3", '"%s" must be an object with label, note and date' % key)
                continue
            if ev.get("label") not in EVIDENCE_LABELS:
                self.add(path, n, "E3", '"%s" has label %s; use one of %s' % (key, json.dumps(ev.get("label")),
                                                                             ", ".join(EVIDENCE_LABELS)))
            if not isinstance(ev.get("note"), str) or not ev["note"].strip():
                self.add(path, n, "E3", '"%s" needs a note saying what was tested and what was not' % key)
            if not isinstance(ev.get("date"), str) or not DATE_RE.match(ev["date"]):
                self.add(path, n, "E3", '"%s" needs a date as YYYY-MM-DD' % key)

    def _misplaced(self, path: str, under: Dict[str, Tuple[int, str]], elsewhere: Dict[str, int]) -> None:
        for p, n in sorted(elsewhere.items()):
            self.add(path, n, "R1m", '"%s" must sit right under the H1 title, before any other text' % p)

    # ---------------------------------------------------------------- agents
    def check_agent(self, ap: str, names: Dict[str, str]) -> None:
        text = read_text(ap)
        lines = text.split("\n")
        under, elsewhere = header_markers(lines)
        self._misplaced(ap, under, elsewhere)
        plugin_only = PLUGIN_ONLY_PREFIX in under
        req = requires_skills(text)
        req_line = under.get(REQUIRES_PREFIX, (elsewhere.get(REQUIRES_PREFIX, 1), ""))[0]
        used: List[Tuple[int, str]] = []
        for n, ln in enumerate(lines, 1):
            snippets = list(SNIPPET_RE.finditer(ln))
            for m in snippets:
                if not (m.group("a") == m.group("b") == m.group("c")):
                    self.add(ap, n, "R3d", "locate snippet names different skills (%s, %s, %s); use one name"
                             % (m.group("a"), m.group("b"), m.group("c")))
                else:
                    used.append((n, m.group("a")))
            ps = PS_SNIPPET_RE.match(ln)
            if ps:
                name = ps.group("a")
                nxt = next((x for x in lines[n:] if x.strip()), "")
                if ("Test-Path" in nxt and re.search(r"[\"']\.claude/skills/%s[\"']" % re.escape(name), nxt)
                        and re.search(r"[\"']\$HOME/\.claude/skills/%s[\"']" % re.escape(name), nxt)):
                    used.append((n, name))
                else:
                    self.add(ap, n, "R3d", "PowerShell locate snippet needs a fallback line that tests "
                             ".claude/skills/%s and $HOME/.claude/skills/%s" % (name, name))
                continue
            if not snippets and SNIPPET_HINT_RE.search(ln):
                self.add(ap, n, "R3d", "locate snippet does not have the exact shape from CONTRIBUTING.md R3")
                continue
            stripped = SNIPPET_RE.sub("", ln)
            if not plugin_only and PLUGIN_ROOT_RE.search(stripped):
                m2 = re.search(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/([^\s\"'`)]*)", stripped)
                sub = m2.group(1) if m2 else ""
                if sub.startswith("skills/"):
                    msg = ("agent points into a skill through ${CLAUDE_PLUGIN_ROOT}, which is empty when the "
                           "agent is copied on its own; use the locate snippet and $SKILL_DIR")
                    self.add(ap, n, "R3d", msg)
                else:
                    self.add(ap, n, "R3e", "agent references ${CLAUDE_PLUGIN_ROOT}/%s, a plugin file outside any "
                             'skill; move it into a skill, or add "Install: plugin only. <reason>." under the title'
                             % sub)
        if used and not req:
            self.add(ap, used[0][0], "R3d", 'agent has a locate snippet but no "Requires skill: <name>" line '
                     "under its title")
        for name in req:
            if name not in names:
                self.add(ap, req_line, "R3d", 'requires skill "%s", which is not in this plugin' % name)
        req_dirs = {names.get(r, r) for r in req}
        for n, name in used:
            if req and name not in req_dirs and name not in req:
                self.add(ap, n, "R3d", 'locate snippet uses skill "%s", which the "Requires skill:" line does '
                         "not list" % name)
            if name not in names.values():
                self.add(ap, n, "R3d", 'locate snippet points at skills/%s, which does not exist' % name)

    # ---------------------------------------------------------------- vendor.json
    def check_vendor(self, pdir: str) -> None:
        vp = os.path.join(pdir, "vendor.json")
        if not os.path.isfile(vp):
            return
        raw = read_text(vp)
        try:
            data = json.loads(raw)
        except ValueError as e:
            self.add(vp, 1, "R2c", "vendor.json is not valid JSON: %s" % e)
            return
        if not isinstance(data, dict):
            self.add(vp, 1, "R2c", 'vendor.json must be an object {"<copy>": "<canonical>"}')
            return
        vlines = raw.split("\n")

        def line_of(key: str) -> int:
            needle = json.dumps(key)
            for i, ln in enumerate(vlines, 1):
                if needle in ln:
                    return i
            return 1

        copies = {os.path.normpath(k): os.path.normpath(v) for k, v in data.items() if isinstance(v, str)}
        for copy_rel, canon_rel in data.items():
            n = line_of(copy_rel)
            if not isinstance(canon_rel, str):
                self.add(vp, n, "R2c", "%s: the canonical path must be a string" % copy_rel)
                continue
            copy = os.path.join(pdir, copy_rel)
            canon = os.path.join(pdir, canon_rel)
            if os.path.normpath(copy_rel) == os.path.normpath(canon_rel):
                self.add(vp, n, "R2c", "%s is listed as its own canonical source" % copy_rel)
                continue
            src = read_bytes(canon)
            dst = read_bytes(copy)
            if src is None:
                self.add(vp, n, "R2c", "canonical source %s does not exist" % canon_rel)
                continue
            if dst is None:
                self.add(vp, n, "R2c", "vendored copy %s does not exist (run python3 scripts/sync_vendor.py)" % copy_rel)
                continue
            if src != dst:
                self.add(vp, n, "R2c", "%s differs from its canonical %s (run python3 scripts/sync_vendor.py)"
                         % (copy_rel, canon_rel))
            if copy_rel.endswith(".py"):
                self.check_vendored_imports(vp, n, pdir, copy_rel, canon_rel, copies)

    def check_vendored_imports(self, vp: str, n: int, pdir: str, copy_rel: str, canon_rel: str,
                               copies: Dict[str, str]) -> None:
        canon_dir = os.path.dirname(os.path.join(pdir, canon_rel))
        copy_dir = os.path.dirname(os.path.join(pdir, copy_rel))
        for mod in sorted(imported_modules(read_text(os.path.join(pdir, canon_rel)))):
            for cand in (mod + ".py", mod):
                src = os.path.join(canon_dir, cand)
                if not os.path.exists(src) or (cand == mod and not os.path.isfile(os.path.join(src, "__init__.py"))):
                    continue
                dst = os.path.join(copy_dir, cand)
                dst_rel = os.path.normpath(os.path.relpath(dst, pdir))
                if not os.path.exists(dst):
                    self.add(vp, n, "R2f", "%s imports %s, which is next to the canonical but missing next to the "
                             "copy; vendor %s too" % (copy_rel, mod, self.rel(src)))
                elif os.path.isfile(src) and read_bytes(src) != read_bytes(dst) and dst_rel not in copies:
                    self.add(vp, n, "R2f", "%s imports %s; the copy next to it differs from %s and is not in "
                             "vendor.json" % (copy_rel, mod, self.rel(src)))
                break


def imported_modules(source: str) -> List[str]:
    """Top-level module names a Python file imports (absolute and relative)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                out.extend(a.name for a in node.names)
            elif node.module:
                out.append(node.module.split(".")[0])
    return sorted(set(out))


def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(here), help="repo root (default: parent of scripts/)")
    ap.add_argument("--plugin", action="append", help="check only this plugin folder name (repeatable)")
    ap.add_argument("--json", action="store_true", help="print violations as JSON")
    args = ap.parse_args(argv)
    checker = Checker(args.root)
    found = checker.run(args.plugin)
    if args.json:
        print(json.dumps({"ok": not found, "count": len(found),
                          "violations": [v.as_dict() for v in found]}, indent=1))
    else:
        for v in found:
            print(v.text())
        n = len(checker.plugins(args.plugin))
        print("%d violation%s in %d plugin%s" % (len(found), "" if len(found) == 1 else "s",
                                                 n, "" if n == 1 else "s"), file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
