#!/usr/bin/env python3
"""scan_secrets.py: a small, dependency-free secret scanner.

It is a fallback and a teaching tool, not a replacement for gitleaks. Use gitleaks
when you can install it; use this when you cannot (a locked-down lab machine, a
fresh clone with no tooling) or inside a Claude Code hook where startup time matters.

Modes:
  scan_secrets.py --staged            scan lines being added in the git index
  scan_secrets.py --worktree          scan unstaged changes to tracked files (git commit -a)
  scan_secrets.py --all               scan every file git would let you commit: tracked files plus
                                      untracked files that are not gitignored (what `git add .` stages)
  scan_secrets.py PATH [PATH ...]     scan the given files

Exit codes: 0 clean, 1 findings, 2 usage or git error.
Findings print redacted (first 6 characters only), never the full value.

Allow a line on purpose by adding the comment:  secrets-hygiene: allow
(gitleaks' own inline marker, gitleaks:allow, is honored too, so one comment satisfies both.)
Only values that are wholly a placeholder are skipped (your-key-here, <token>, xxxxxxxx,
REPLACE_ME, changeme). A key-shaped value that merely contains "fake" or "test" is reported,
so mark a deliberate test key with the allow comment.
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
ALLOW_PRAGMAS = (ALLOW_PRAGMA, "gitleaks:allow")
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "host.docker.internal")
DEFAULT_DB_PASSWORDS = ("postgres", "password")

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

# Code that reads a value instead of holding one (token = process.env.GITHUB_TOKEN).
ENV_READ_HINTS = ("process.env", "os.environ", "${", "getenv", "env(")
# A provider prefix is stripped before the placeholder test, so sk-ant-your-key-here is judged
# on "your-key-here".
PROVIDER_PREFIX_RE = re.compile(
    r"^(?:sk-ant-(?:api\d\d-)?|sk-or-v1-|sk-(?:proj-|svcacct-|admin-)?|(?:sk|pk|rk)_(?:live|test)_|"
    r"gh[pousr]_|github_pat_|AKIA|ASIA|AIza|gsk_|xox[abprs]-)"
)
# Pieces a placeholder is made of. A value is a placeholder only when these pieces make up ALL
# of it: AKIA + "Q7FAKEFAKEFAKE12" still has "Q712" left over, so it is reported like any other key.
PLACEHOLDER_PIECE_RE = re.compile(
    r"(?i)<[^>]*>|(.)\1{3,}|x{3,}|replace|changeme|change|placeholder|example|sample|dummy|fake|"
    r"your|my|api|keys?|here|goes|me|test|secret|token|password|value|[\W_]"
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


def looks_like_placeholder(value: str) -> bool:
    """True only when the WHOLE value is a placeholder (your-key-here, <token>, xxxxxxxx,
    REPLACE_ME, changeme, sk-ant-your-key-here-000) or an env read. A key-shaped value that merely
    contains fake/dummy/example is reported: mark a deliberate test key with the allow pragma."""
    low = value.lower()
    if any(h in low for h in ENV_READ_HINTS):
        return True
    if len(set(value)) <= 3:  # aaaaaaaa, 00000000
        return True
    body = PROVIDER_PREFIX_RE.sub("", value, count=1)
    if re.match(r"(?i)your[_-]", body):  # your_secret_here_please
        return True
    return PLACEHOLDER_PIECE_RE.sub("", body) == ""


def is_known_non_secret(rule: str, value: str, line: str) -> bool:
    """Values that match a rule but are published examples or local-only defaults."""
    if rule == "aws-access-key-id":
        return value.endswith("EXAMPLE")  # AWS's documentation key, AKIAIOSFODNN7EXAMPLE
    if rule == "postgres-url-with-password":
        creds, _, rest = value.split("://", 1)[1].partition("@")
        password = creds.split(":", 1)[1]
        host = re.split(r"[:/?]", rest, 1)[0].lower() if not rest.startswith("[") else rest.split("]")[0] + "]"
        return (host in LOOPBACK_HOSTS or password.lower() in DEFAULT_DB_PASSWORDS
                or looks_like_placeholder(password))
    return False


def scan_line(path: str, lineno: int, line: str, skip_rules: tuple = ()) -> list[Finding]:
    if any(p in line for p in ALLOW_PRAGMAS):
        return []
    out: list[Finding] = []
    seen_spans: list[tuple[int, int]] = []
    for rule, rx, grp in RULES:
        if rule in skip_rules:
            continue
        for m in rx.finditer(line):
            value = m.group(grp)
            span = m.span(grp)
            if any(s <= span[0] < e for s, e in seen_spans):
                continue  # a more specific rule already reported this value
            # Every key-shaped rule skips values that are wholly a placeholder (sk-ant-your-key-here,
            # ghp_xxxx..., <token>), what a .env.example is meant to hold.
            if rule not in ("private-key-block", "postgres-url-with-password"):
                if looks_like_placeholder(value):
                    continue
            if rule == "generic-assignment" and shannon_entropy(value) < 3.0:
                continue
            if is_known_non_secret(rule, value, line):
                continue
            seen_spans.append(span)
            out.append(Finding(path, lineno, rule, redact(value)))
    return out


def scan_text(path: str, text: str, start_line: int = 1, skip_rules: tuple = ()) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), start=start_line):
        findings.extend(scan_line(path, i, line, skip_rules))
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


def scan_diff_mode(cached: bool, cwd: str | None, pathspecs: list[str] | None = None) -> list[Finding]:
    """Scan added lines in the index (cached=True) or in unstaged tracked changes (cached=False).

    `pathspecs` limits the diff to those paths, relative to `cwd`, exactly as git reads them.
    """
    base = ["diff", "--cached"] if cached else ["diff"]
    tail = ["--", *pathspecs] if pathspecs else []
    names = git([*base, "--name-only", "--diff-filter=ACMR", *tail], cwd).splitlines()
    findings = [Finding(n, 0, "secret-file-staged", "(file name)") for n in names if is_secret_filename(n)]
    diff = git([*base, "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR", *tail], cwd)
    for path, lineno, text in parse_unified_diff(diff):
        findings.extend(scan_line(path, lineno, text))
    return findings


def scan_paths(paths: list[str], max_bytes: int | None = None, follow_symlinks: bool = True) -> list[Finding]:
    """Scan files by content and name. Only regular files are read: a FIFO, a device, or a
    symlink to one (/dev/zero) would block or never end. With follow_symlinks=False a symlink
    is skipped, because git commits the link itself, not the file it points to."""
    findings: list[Finding] = []
    for p in paths:
        if is_secret_filename(p):
            findings.append(Finding(p, 0, "secret-file", "(file name)"))
        try:
            if (not follow_symlinks and os.path.islink(p)) or not os.path.isfile(p):
                continue
            if max_bytes is not None and os.path.getsize(p) > max_bytes:
                continue
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except (IsADirectoryError, FileNotFoundError, NotADirectoryError, PermissionError):
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
    g.add_argument("--all", action="store_true",
                   help="scan tracked files plus untracked files that are not gitignored")
    ap.add_argument("--cwd", default=None, help="repository directory (default: current)")
    ap.add_argument("--quiet", action="store_true", help="print only the count")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args(argv)

    note = ""
    try:
        if a.staged:
            findings = scan_diff_mode(True, a.cwd)
        elif a.worktree:
            findings = scan_diff_mode(False, a.cwd)
        elif a.all:
            root = a.cwd or "."
            # --cached --others --exclude-standard: tracked files AND untracked files git would
            # stage with `git add .`. Untracked files are the ones a careless add leaks.
            out = git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], a.cwd)
            files = sorted({f for f in out.split("\0") if f})
            findings = scan_paths([os.path.join(root, f) for f in files], follow_symlinks=False)
            note = f" ({len(files)} files: tracked and untracked; gitignored files skipped)"
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
            print(f"scan_secrets: clean{note}")
        return 0
    if not a.quiet:
        for f in findings:
            print(f.render())
    print(f"scan_secrets: {len(findings)} possible secret(s). Remove them, or mark a false positive "
          f"with the comment '{ALLOW_PRAGMA}'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
