#!/usr/bin/env python3
"""scan_secrets.py: a small, dependency-free secret scanner.

It is a fallback and a teaching tool, not a replacement for gitleaks. Use gitleaks
when you can install it; use this when you cannot (a locked-down lab machine, a
fresh clone with no tooling) or inside a Claude Code hook where startup time matters.

Modes:
  scan_secrets.py --staged            scan lines being added in the git index
  scan_secrets.py --worktree          scan unstaged changes to tracked files (git commit -a)
  scan_secrets.py --all               scan every tracked file at HEAD of the work tree
  scan_secrets.py PATH [PATH ...]     scan the given files

Exit codes: 0 clean, 1 findings, 2 usage or git error.
Findings print redacted (first 6 characters only), never the full value.

Allow a line on purpose by adding the comment:  secrets-hygiene: allow
"""
from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass

ALLOW_PRAGMA = "secrets-hygiene: allow"

# (rule id, compiled regex, group index holding the secret)
RULES: list[tuple[str, re.Pattern[str], int]] = [
    ("aws-access-key-id", re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"), 1),
    ("github-token", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,})\b"), 1),
    ("github-fine-grained-pat", re.compile(r"\b(github_pat_[A-Za-z0-9_]{60,})\b"), 1),
    ("anthropic-key", re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{20,})"), 1),
    ("openrouter-key", re.compile(r"\b(sk-or-v1-[a-f0-9]{48,})\b"), 1),
    ("openai-key", re.compile(r"\b(sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,})"), 1),
    ("groq-key", re.compile(r"\b(gsk_[A-Za-z0-9]{40,})\b"), 1),
    ("stripe-live-key", re.compile(r"\b((?:sk|rk)_live_[A-Za-z0-9]{20,})\b"), 1),
    ("slack-token", re.compile(r"\b(xox[abprs]-[A-Za-z0-9\-]{10,})\b"), 1),
    ("google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"), 1),
    ("private-key-block", re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----)"), 1),
    ("postgres-url-with-password", re.compile(r"\b(postgres(?:ql)?://[^:\s/]+:[^@\s]{6,}@[^\s'\"]+)"), 1),
    (
        "generic-assignment",
        re.compile(
            r"""(?i)\b[A-Z0-9_]*(?:api[_-]?key|secret|token|passwd|password|private[_-]?key)[A-Z0-9_]*\b"""
            r"""\s*[:=]\s*['"]?([A-Za-z0-9_\-+/=.]{16,})['"]?"""
        ),
        1,
    ),
]

PLACEHOLDER_HINTS = (
    "replace_me", "replaceme", "your_", "your-", "<", "example", "placeholder",
    "changeme", "xxxx", "dummy", "fake", "test_key", "process.env", "os.environ",
    "${", "getenv", "env(",
)

# Files that are secrets by name, whatever they contain.
SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env(\.[A-Za-z0-9_-]+)?|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.pfx|credentials\.json|service-account.*\.json)$"
)
SAFE_FILE_RE = re.compile(r"(^|/)\.env\.(example|sample|template|dist)$")


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    preview: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.preview}"


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def redact(value: str) -> str:
    return value[:6] + "***" if len(value) > 6 else "***"


def looks_like_placeholder(value: str, line: str) -> bool:
    low = value.lower()
    if any(h in low for h in PLACEHOLDER_HINTS):
        return True
    if len(set(value)) <= 3:  # aaaaaaaa, 00000000
        return True
    line_low = line.lower()
    return "replace_me" in line_low or "placeholder" in line_low


def scan_line(path: str, lineno: int, line: str) -> list[Finding]:
    if ALLOW_PRAGMA in line:
        return []
    out: list[Finding] = []
    seen_spans: list[tuple[int, int]] = []
    for rule, rx, grp in RULES:
        for m in rx.finditer(line):
            value = m.group(grp)
            span = m.span(grp)
            if any(s <= span[0] < e for s, e in seen_spans):
                continue  # a more specific rule already reported this value
            if rule in ("generic-assignment", "openai-key"):
                if looks_like_placeholder(value, line):
                    continue
            if rule == "generic-assignment" and shannon_entropy(value) < 3.0:
                continue
            seen_spans.append(span)
            out.append(Finding(path, lineno, rule, redact(value)))
    return out


def scan_text(path: str, text: str, start_line: int = 1) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), start=start_line):
        findings.extend(scan_line(path, i, line))
    return findings


def is_secret_filename(path: str) -> bool:
    return bool(SECRET_FILE_RE.search(path)) and not SAFE_FILE_RE.search(path)


def parse_unified_diff(diff: str) -> list[tuple[str, int, str]]:
    """Return (path, new_line_number, text) for every added line in a -U0 diff."""
    added: list[tuple[str, int, str]] = []
    path = None
    new_line = 0
    hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else (target[2:] if target.startswith("b/") else target)
            continue
        if raw.startswith("--- "):
            continue
        m = hunk.match(raw)
        if m:
            new_line = int(m.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            added.append((path, new_line, raw[1:]))
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1
    return added


def git(args: list[str], cwd: str | None) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"git {' '.join(args)} failed")
    return res.stdout


def scan_diff_mode(cached: bool, cwd: str | None) -> list[Finding]:
    base = ["diff", "--cached"] if cached else ["diff"]
    names = git([*base, "--name-only", "--diff-filter=ACMR"], cwd).splitlines()
    findings = [Finding(n, 0, "secret-file-staged", "(file name)") for n in names if is_secret_filename(n)]
    diff = git([*base, "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR"], cwd)
    for path, lineno, text in parse_unified_diff(diff):
        findings.extend(scan_line(path, lineno, text))
    return findings


def scan_paths(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for p in paths:
        if is_secret_filename(p):
            findings.append(Finding(p, 0, "secret-file", "(file name)"))
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except (IsADirectoryError, FileNotFoundError, PermissionError):
            continue
        if "\x00" in text[:4096]:
            continue  # binary
        findings.extend(scan_text(p, text))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan for committed secrets (redacted output).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="scan lines added in the git index")
    g.add_argument("--worktree", action="store_true", help="scan unstaged changes to tracked files")
    g.add_argument("--all", action="store_true", help="scan all tracked files")
    ap.add_argument("--cwd", default=None, help="repository directory (default: current)")
    ap.add_argument("--quiet", action="store_true", help="print only the count")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args(argv)

    try:
        if a.staged:
            findings = scan_diff_mode(True, a.cwd)
        elif a.worktree:
            findings = scan_diff_mode(False, a.cwd)
        elif a.all:
            root = a.cwd or "."
            files = git(["ls-files"], a.cwd).splitlines()
            findings = scan_paths([os.path.join(root, f) for f in files])
        elif a.paths:
            findings = scan_paths(a.paths)
        else:
            ap.print_usage(sys.stderr)
            return 2
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"scan_secrets: {exc}", file=sys.stderr)
        return 2

    if not findings:
        if not a.quiet:
            print("scan_secrets: clean")
        return 0
    if not a.quiet:
        for f in findings:
            print(f.render())
    print(f"scan_secrets: {len(findings)} possible secret(s). Remove them, or mark a false positive "
          f"with the comment '{ALLOW_PRAGMA}'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
