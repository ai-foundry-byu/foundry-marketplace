#!/usr/bin/env python3
"""verify-before-done: PreToolUse + Stop hook. "Done" means "tested".

What counts as a code change (any of these):
  * EFFECTS (git repos, the main signal): at the session's first hook call the
    hook snapshots every dirty or untracked source file with its content hash
    (and HEAD). Later it recomputes. A source file whose content changed since
    the snapshot, or that changed in a commit made since, is a code change, no
    matter which tool made it: Edit, sed -i, a heredoc, tee, cp/mv, a Python
    script, git apply. Source = code extensions (.py, .ts, .go, .html, .css,
    ...) plus Makefile/Dockerfile; docs (*.md, *.txt, *.rst, docs/**), data and
    side-effect files (.json, .db, .log, lockfiles), .claude/ and dependency or
    build dirs (node_modules, .venv, dist, ...) do not count. Files outside the
    project do not count. Files that were dirty before the session and were not
    touched do not count.
  * an Edit/Write/MultiEdit/NotebookEdit to a non-doc file inside the project.
  * outside git only, a command-pattern fallback: write targets of > and >>,
    tee, sed -i, perl -i, cp, mv, and inline python/node code that writes a
    file, git apply and patch.

A Bash test or typecheck command (pytest, npm test, tsc, go test, cargo test,
...) marks the session tested and moves the snapshot to "after this test run".

PreToolUse also guards irreversible commands (git push, vercel --prod, npm
publish, wrangler deploy, terraform apply, ...): DENIED unless the command
carries VERIFY_OK=1, and the token itself is refused while code changed since
the last test run ("run the tests first; VERIFY_OK=1 is for after they pass").
A test in the same command counts only as "<test> && VERIFY_OK=1 <command>":
with ;, ||, & or a pipe in between, the push runs whatever the tests report.
A command this hook denies never runs, so its tests do not count either, and
a command that writes code after its tests ("pytest; sed -i ...") does not
reset the baseline. When destructive-guard will deny the same command, this
hook stays silent, so the more important reason is the one Claude sees.

Stop:
  * If code changed since the last test run, keep Claude working ONCE with a
    reason telling it to run the tests and report the result (non-error Stop
    feedback, see _common.emit_stop_block).
  * Never loops: allows when stop_hook_active is true and this hook made the
    previous block, when background tasks are still in flight, and after
    FOUNDRY_VERIFY_MAX_BLOCKS blocks in a session (default 2). When another
    Stop hook (ship-stop) is what continued the turn, the check still runs, so
    edits made during those continuations are not dropped. An allowed
    unverified stop resets the snapshot so the next turn is not nagged about
    the same change.

Disable (the human override): FOUNDRY_VERIFY=0
Extra test pattern (regex): FOUNDRY_VERIFY_TEST_PATTERN
Extra irreversible pattern (regex): FOUNDRY_VERIFY_IRREVERSIBLE_PATTERN
Extra ignored paths (comma globs): FOUNDRY_VERIFY_IGNORE, e.g. "*.json,config/*"
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "verify-before-done"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_EXT = (".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc")
OVERRIDE = re.compile(r"(?:^|[\s;&|(])VERIFY_OK=1(?=$|[\s;&|)])")

# Both patterns are matched against each normalized command stage (sudo/env
# stripped, bash -c unwrapped), anchored at the start, so text inside a commit
# message or an echo does not count.
_RUNNER = (r"(?:(?:uv|poetry|pipenv|pdm|hatch|rye)\s+run\s+|bunx\s+|pnpm\s+exec\s+|"
           r"npx\s+(?:--yes\s+)?|bundle\s+exec\s+|python\d?(?:\.\d+)?\s+-m\s+)?")
TEST_RE = re.compile(
    r"^" + _RUNNER + r"(?:"
    r"pytest|py\.test|tox|nox|vitest|jest|mocha|ava|rspec|phpunit|ctest|bats|"
    r"tsc|vue-tsc|mypy|pyright|unittest|doctest|playwright\s+test|"
    r"go\s+(?:test|vet)|cargo\s+(?:test|check|nextest)|"
    r"mvn\w*\s+(?:test|verify)|(?:\./)?gradlew?\s+(?:test|check)|"
    r"dotnet\s+test|swift\s+test|deno\s+(?:test|check)|"
    r"(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|typecheck|type-check|check)(?::[\w-]+)?|"
    r"make\s+(?:test|check)|rails\s+test|mix\s+test"
    r")(?=$|\s)"
)

IRREVERSIBLE_RE = re.compile(
    r"^(?:"
    r"git\s+(?:(?:-[Cc]\s+\S+|--git-dir(?:=|\s+)\S+|--work-tree(?:=|\s+)\S+|--no-pager)\s+)*"
    r"push\b(?!.*\s(?:--dry-run|-n)(?:\s|$))|"
    r"vercel\s+(?:.*\s)?--prod\b|vercel\s+(?:promote|remove|rm)\b|"
    r"vercel\s+alias\s+(?:set|rm|remove)\b|vercel\s+domains\s+(?:add|rm|remove|mv|move|transfer|buy)\b|"
    r"netlify\s+deploy\s+.*--prod\b|firebase\s+deploy\b|fly(?:ctl)?\s+deploy\b|"
    r"wrangler\s+(?:[\w-]+\s+)?(?:deploy|publish|delete)\b|railway\s+up\b|"
    r"gh\s+repo\s+delete\b|gh\s+release\s+create\b|gh\s+pr\s+merge\b|"
    r"(?:npm|pnpm|yarn)\s+publish\b|(?:npm|pnpm|yarn)\s+run\s+deploy\b|"
    r"twine\s+upload\b|uv\s+publish\b|poetry\s+publish\b|cargo\s+publish\b|gem\s+push\b|"
    r"docker\s+push\b|terraform\s+(?:apply|destroy)\b|pulumi\s+(?:up|destroy)\b"
    r")"
)


def _stages(cmd: str) -> list[str]:
    return [" ".join(argv) for argv in c.all_argvs(strip_data_heredocs(cmd))]


_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_RUNS_BODY = {"sh", "bash", "zsh", "dash", "ksh", "fish", "python", "python3", "node", "ruby", "perl",
              "php", "deno", "bun", "ssh", "eval", "source", ".", "xargs", "parallel"}


def strip_data_heredocs(cmd: str) -> str:
    """Drop heredoc bodies that are file contents (cat > run_tests.sh <<EOF ... EOF): their lines
    are not commands, so "pytest" in them is not a test run and "git push" in them is not a push.
    A body fed to a shell or interpreter (bash <<EOF, python3 - <<EOF, ssh host <<EOF) runs, and
    stays. The other guards keep reading every line; this is for verify-before-done only."""
    if "<<" not in cmd:
        return cmd
    lines, out, i = cmd.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in _HEREDOC.finditer(line):
            if line[m.start():m.start() + 3] == "<<<" or (m.start() and line[m.start() - 1] == "<"):
                continue  # a here-string, one line
            before = re.split(r"\|\|?|&&|;|&", line[:m.start()])[-1]
            argv = c.strip_prefixes(c.strip_grouping(c.tokenize(before)))
            # the body runs when a shell or interpreter reads it: as the receiving command
            # (bash <<EOF, docker exec -i app sh <<EOF) or down a pipe (cat <<EOF | bash)
            piped = [c.strip_prefixes(c.tokenize(seg)) for seg in line[m.end():].split("|")[1:]]
            runs = any(os.path.basename(t) in _RUNS_BODY for t in argv) or \
                any(a and os.path.basename(a[0]) in _RUNS_BODY for a in piped)
            delim, dash = m.group(3), m.group(1) == "-"
            while i < len(lines):
                body = lines[i]
                i += 1
                if (body.lstrip("\t") if dash else body) == delim:
                    out.append(body)
                    break
                if runs:
                    out.append(body)
    return "\n".join(out)


def _extra(name: str):
    pat = os.environ.get(name, "").strip()
    if not pat:
        return None
    try:
        return re.compile(pat)
    except re.error:
        return None


def is_test_command(cmd: str) -> bool:
    extra = _extra("FOUNDRY_VERIFY_TEST_PATTERN")
    for stage in _stages(cmd):
        if TEST_RE.search(stage) or (extra and extra.search(stage)):
            return True
    return False


def irreversible(cmd: str) -> str | None:
    for stage in _stages(cmd):
        m = IRREVERSIBLE_RE.search(stage)
        if m:
            return m.group(0).strip()
    extra = _extra("FOUNDRY_VERIFY_IRREVERSIBLE_PATTERN")
    if extra:
        m = extra.search(cmd)
        if m:
            return m.group(0)
    return None


def project_dir(event: dict) -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()


def is_code_file(path: str, project: str = "") -> bool:
    if not path:
        return False
    real = c.realpath(path)
    if project:
        proj = c.realpath(project)
        if not c.is_inside(real, proj):
            return False
        rel = os.path.relpath(real, proj)
    else:
        rel = real
    rel = rel.replace(os.sep, "/")
    if rel.lower().endswith(DOC_EXT):
        return False
    parts = rel.split("/")
    if "docs" in parts[:-1] or "doc" in parts[:-1]:
        return False
    if ".claude" in parts[:-1] and not ("worktrees" in parts):
        return False  # plans, memory and settings are not product code
    for glob in os.environ.get("FOUNDRY_VERIFY_IGNORE", "").split(","):
        glob = glob.strip()
        if glob and (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(os.path.basename(rel), glob)):
            return False
    return True


CODE_EXT = {
    ".py", ".pyi", ".pyx", ".ipynb", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".astro", ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".groovy", ".rb", ".php", ".cs", ".fs",
    ".swift", ".m", ".mm", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".sh", ".bash",
    ".zsh", ".fish", ".ps1", ".lua", ".dart", ".ex", ".exs", ".erl", ".hs", ".ml", ".clj",
    ".r", ".jl", ".sql", ".prisma", ".graphql", ".gql", ".proto", ".tf", ".sol", ".zig", ".nim",
}
CODE_NAMES = {"Makefile", "Dockerfile", "Rakefile", "Gemfile", "Justfile", "Procfile"}
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", "site-packages", ".git", ".next",
             ".nuxt", "dist", "build", "target", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", "coverage", ".turbo", ".cache", ".gradle", "vendor",
             # generated output that test/build tools write (coverage HTML, framework builds)
             "htmlcov", ".svelte-kit", ".output", ".vercel", ".parcel-cache", ".angular",
             ".docusaurus", "storybook-static", ".expo", ".ipynb_checkpoints", ".terraform",
             "bower_components", ".serverless"}
UNKNOWN = "(a file written by a shell command)"
MAX_FILES = 5000


def is_source_file(path: str, project: str) -> bool:
    """Stricter than is_code_file: for changes nobody named (shell effects), count real source
    only, so a program writing app.db, out.json or run.log is not "a code edit"."""
    if not is_code_file(path, project):
        return False
    rel = os.path.relpath(c.realpath(path), c.realpath(project)).replace(os.sep, "/")
    if any(part in SKIP_DIRS for part in rel.split("/")[:-1]):
        return False
    base = os.path.basename(rel)
    return base in CODE_NAMES or os.path.splitext(base)[1].lower() in CODE_EXT


# ---- effects: snapshot the dirty source files of the repo, compare later ----------------

def _repo_root(project: str) -> str | None:
    r = c.git(project, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    return c.realpath(r.stdout.strip())


def _head(root: str) -> str:
    r = c.git(root, "rev-parse", "-q", "--verify", "HEAD")
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


def _dirty_sources(root: str, project: str) -> list[str] | None:
    r = c.git(root, "--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=all")
    if r is None or r.returncode != 0:
        return None
    out, toks = [], r.stdout.split("\0")
    i = 0
    while i < len(toks) and len(out) < MAX_FILES:
        entry = toks[i]
        i += 1
        if len(entry) < 4:
            continue
        paths = [entry[3:]]
        if entry[0] in "RC":  # rename/copy: the next token is the old path
            if i < len(toks):
                paths.append(toks[i])
            i += 1
        for rel in paths:
            # cheap string checks first: an un-ignored node_modules can list 100k entries
            parts = rel.rstrip("/").split("/")
            if parts[-1] not in CODE_NAMES and os.path.splitext(parts[-1])[1].lower() not in CODE_EXT:
                continue
            if any(part in SKIP_DIRS for part in parts[:-1]):
                continue
            full = os.path.join(root, rel)
            if is_source_file(full, project):
                out.append(full)
    return out


def take_snapshot(project: str) -> dict:
    root = _repo_root(project)
    if not root:
        return {"git": False}
    dirty = _dirty_sources(root, project)
    if dirty is None:
        return {"git": False}
    return {"git": True, "root": root, "head": _head(root),
            "files": {p: c.blob_hash(p) for p in dirty}}


def _tree_hashes(root: str, head: str, paths: list[str]) -> dict:
    """Blob ids of paths at commit head ("-" when absent)."""
    found = {p: "-" for p in paths}
    if not head:
        return found
    rels = [os.path.relpath(p, root) for p in paths]
    for k in range(0, len(rels), 200):
        r = c.git(root, "ls-tree", "-r", "-z", head, "--", *rels[k:k + 200])
        if r is None or r.returncode != 0:
            continue
        for line in r.stdout.split("\0"):
            if "\t" in line:
                meta, rel = line.split("\t", 1)
                parts = meta.split()
                if len(parts) == 3 and parts[1] == "blob":
                    found[os.path.join(root, rel)] = parts[2]
    return found


def _base(snap: dict) -> dict:
    base = snap.get("files")
    return base if isinstance(base, dict) else {}


def _before(snap: dict, paths) -> dict:
    """Each path's content hash at the snapshot: its snapshot entry, else its blob at the
    snapshot's HEAD, else "-" (absent)."""
    base, root = _base(snap), snap.get("root") or ""
    missing = sorted(p for p in paths if p not in base and root and c.is_inside(p, root))
    before = {p: "-" for p in paths}
    before.update(_tree_hashes(root, snap.get("head") or "", missing) if missing else {})
    before.update({p: base[p] for p in paths if p in base})
    return before


def changed_since(snap: dict, project: str) -> list[str]:
    """Source files whose content differs from the snapshot (any tool, committed or not)."""
    if not snap.get("git"):
        return []
    root, base = snap.get("root") or "", _base(snap)
    now = _dirty_sources(root, project)
    if now is None:
        return []
    cands = set(base) | set(now)
    head = _head(root)
    if snap.get("head") and head and head != snap.get("head"):
        r = c.git(root, "diff", "--name-only", "-z", snap["head"], head)
        if r is not None and r.returncode == 0:
            cands |= {os.path.join(root, x) for x in r.stdout.split("\0")
                      if x and is_source_file(os.path.join(root, x), project)}
    before = _before(snap, cands)
    return sorted(p for p in cands if c.blob_hash(p) != before[p])


def _drop_unchanged(snap: dict, files: list[str]) -> list[str]:
    """Edit/Write paths whose content is back to what it was at the snapshot are not a change
    (an edit that was reverted, or an Edit that another hook denied)."""
    if not snap.get("git"):
        return files
    real = {f: c.realpath(f) for f in files if f != UNKNOWN}
    before = _before(snap, set(real.values()))
    return [f for f in files if f == UNKNOWN or c.blob_hash(real[f]) != before[real[f]]]


# ---- fallback outside git: read write targets from the command text -----------------------

_REDIR = re.compile(r"^(?:\d|&)?>>?\|?(.*)$")
_INLINE_WRITE = re.compile(r"open\([^)]*,\s*(?:mode\s*=\s*)?['\"][^'\"]*[wax]|\.write_(?:text|bytes)\(|"
                           r"writeFile(?:Sync)?\(|File\.write\(|shutil\.(?:copy|move)")
_INTERP = {"python", "python3", "node", "ruby", "perl", "deno", "bun"}


def _positional(args: list[str]) -> list[str]:
    return [a for a in args if a and not a.startswith("-")]


def shell_write_targets(cmd: str, cwd: str) -> list[str]:
    """Files a Bash command writes, as far as its text shows. UNKNOWN for inline code."""
    out: list[str] = []

    def add(p: str) -> None:
        if p and not p.startswith("&"):
            out.append(c.realpath(p if os.path.isabs(os.path.expanduser(p)) else os.path.join(cwd, p)))

    for argv in c.all_argvs(cmd):
        head = os.path.basename(argv[0])
        for k, t in enumerate(argv):
            if t.startswith("<"):
                continue
            m = _REDIR.match(t)
            if m and ">" in t[:3]:
                add(m.group(1) or (argv[k + 1] if k + 1 < len(argv) else ""))
        args = [t for t in argv[1:] if not (_REDIR.match(t) and ">" in t[:3])]
        if head == "tee":
            for t in _positional(args):
                add(t)
        elif head == "sed" and any(t.startswith("-i") or t.startswith("--in-place") or
                                   (re.match(r"^-[a-zA-Z]+$", t) and "i" in t) for t in args):
            pos = _positional(args)
            scripted = any(t in ("-e", "-f") or t.startswith("--expression") for t in args)
            for t in (pos if scripted else pos[1:]):
                add(t)
        elif head == "perl" and any(re.match(r"^-[a-zA-Z]*i", t) for t in args):
            skip = {args[j + 1] for j, t in enumerate(args[:-1]) if re.match(r"^-[a-zA-Z]*e$", t)}
            for t in _positional(args):
                if t not in skip:
                    add(t)
        elif head in ("cp", "mv", "install", "ln"):
            pos = _positional(args)
            if len(pos) >= 2:
                dest = pos[-1]
                full = dest if os.path.isabs(dest) else os.path.join(cwd, dest)
                for src in pos[:-1]:
                    add(os.path.join(dest, os.path.basename(src)) if dest.endswith("/") or
                        os.path.isdir(full) else dest)
                    if head == "mv":
                        add(src)
        elif (head == "git" and argv[1:2] == ["apply"] and "--check" not in args) or \
                (head == "patch" and "--dry-run" not in args):
            out.append(UNKNOWN)
        elif head in _INTERP and _INLINE_WRITE.search(cmd) and (
                "<<" in cmd or any(t in ("-c", "-e", "-") for t in argv[1:])):
            out.append(UNKNOWN)
    return out


def _paths(sid: str) -> dict:
    return {k: c.marker(sid, f"verify-{k}") for k in ("dirty", "tested", "ok", "blocks", "rebase", "last")}


def _snap_path(sid: str) -> str:
    return c.marker(sid, "verify-snap") + ".json"


def snapshot(event: dict, sid: str, fresh: bool = False) -> dict:
    """The session's baseline. Taken at the first hook call, and again at the first hook call
    after a test command (so it reflects the code the tests saw)."""
    m = _paths(sid)
    snap = None if fresh or os.path.exists(m["rebase"]) else c.read_json(_snap_path(sid))
    if not isinstance(snap, dict):
        snap = take_snapshot(project_dir(event))
        c.write_json(_snap_path(sid), snap)
        c.remove(m["rebase"])
    return snap


def untested_changes(event: dict, sid: str) -> list[str]:
    """Code changed since the last test run: tool edits plus measured effects."""
    m = _paths(sid)
    snap = snapshot(event, sid)
    files = [] if os.path.exists(m["tested"]) else _drop_unchanged(snap, _dirty_files(m["dirty"]))
    # one set, built once: a membership test per file (this was quadratic, and 3,000
    # changed files took minutes, past the hook timeout, so the guard failed open)
    seen = set(files) | {c.realpath(f) for f in files if f != UNKNOWN}
    for p in changed_since(snap, project_dir(event)):
        rp = c.realpath(p)
        if p not in seen and rp not in seen:
            files.append(p)
            seen.update((p, rp))
    return files


def _chain(cmd: str) -> list[tuple[list[str], str]]:
    """Top-level pipelines of cmd with the operator after each: [(stages, "&&"|"||"|";"|"&"|"")].

    Quote aware, like _common.split_top_level, but it keeps the operators, which say whether
    a later command runs only when an earlier one passed."""
    out: list[tuple[list[str], str]] = []
    stages: list[str] = []
    buf: list[str] = []
    quote, i, n = "", 0, len(cmd)

    def cut(op: str | None) -> None:
        s = "".join(buf).strip()
        buf.clear()
        if s:
            stages.append(s)
        if op is not None:
            if stages:
                out.append((stages.copy(), op))
            stages.clear()

    while i < n:
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.extend((ch, cmd[i + 1]))
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif cmd[i:i + 2] in ("&&", "||"):
            cut(cmd[i:i + 2])
            i += 2
            continue
        elif ch in (";", "\n"):
            cut(";")
        elif ch == "&" and not ((i and cmd[i - 1] in "<>") or cmd[i + 1:i + 2] == ">"):
            cut("&")
        elif ch == "|":
            if cmd[i + 1:i + 2] == "&":
                i += 1
            cut(None)
        else:
            buf.append(ch)
        i += 1
    cut("")
    return out


def _tests_gate_push(cmd: str) -> bool:
    """True when every irreversible step in cmd runs only after a test passed in the same
    command: "<test> && ... && VERIFY_OK=1 git push", the test last in its pipeline (a pipe
    hands the exit status to the next stage), and only && between them. With ;, ||, & or
    | the push runs whatever the tests say, so they do not count."""
    chain = _chain(strip_data_heredocs(cmd))
    pushes = [k for k, (stages, _) in enumerate(chain) if any(irreversible(s) for s in stages)]
    if not pushes:
        return False
    for k in pushes:
        gated = False
        for j in range(k - 1, -1, -1):
            if chain[j][1] != "&&":
                break
            if is_test_command(chain[j][0][-1]):
                gated = True
                break
        if not gated:
            return False
    return True


def _writes_after_tests(cmd: str, cwd: str, project: str) -> bool:
    """"pytest; sed -i ... app.py": code written after the tests in the same command, so the
    tests did not see it and the command must not reset the baseline."""
    chain = _chain(strip_data_heredocs(cmd))
    tests = [j for j, (stages, _) in enumerate(chain) if any(is_test_command(s) for s in stages)]
    if not tests:
        return False
    later = " ; ".join(" | ".join(stages) for stages, _ in chain[tests[-1] + 1:])
    return bool(later) and any(p == UNKNOWN or is_source_file(p, project)
                               for p in shell_write_targets(later, cwd))


def _destructive_would_deny(cmd: str, cwd: str) -> bool:
    """destructive-guard denies this command too: let its reason be the one Claude sees."""
    if c.disabled("DESTRUCTIVE_GUARD"):
        return False
    try:
        import destructive_guard as dg
        hit = dg.evaluate(cmd, cwd)
    except Exception:  # noqa: BLE001 - never let the sibling break this hook
        return False
    allowed = {r.strip() for r in os.environ.get("FOUNDRY_DESTRUCTIVE_ALLOW", "").split(",") if r.strip()}
    return bool(hit) and hit[0] not in allowed


def _mark_dirty(m: dict, paths: list[str]) -> None:
    try:
        with open(m["dirty"], "a", encoding="utf-8") as fh:
            for p in paths:
                fh.write(p + "\n")
    except OSError:
        pass
    c.remove(m["tested"])


def _short(files: list[str]) -> str:
    return ", ".join(os.path.basename(f) for f in files[:6]) + (" ..." if len(files) > 6 else "")


def handle_pre(event: dict) -> None:
    sid = c.safe_session(event)
    m = _paths(sid)
    tool = event.get("tool_name", "")
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    snap = snapshot(event, sid)  # first call: baseline; after a test run: re-baseline
    project = project_dir(event)
    if tool in EDIT_TOOLS:
        path = str(tin.get("file_path") or tin.get("notebook_path") or "")
        if is_code_file(path, project):
            _mark_dirty(m, [path])
        return
    if tool != "Bash":
        return
    cmd = str(tin.get("command") or "")
    cwd = str(event.get("cwd") or project)
    token = OVERRIDE.search(strip_data_heredocs(cmd))  # not a VERIFY_OK=1 inside a file being written
    # Decide first, record after: a command this hook denies never runs, so its tests must not
    # mark the session tested ("pytest && git push" denied, then "VERIFY_OK=1 git push" alone
    # was accepted with no test ever run).
    hit = irreversible(cmd)
    if hit:
        if _destructive_would_deny(cmd, cwd):
            return  # destructive-guard denies it; nothing in it runs
        if not token:
            _deny_irreversible(event, hit, cmd)
            return
        pending = untested_changes(event, sid)  # before this command's own tests count
        if pending and not _tests_gate_push(cmd):
            same = " The tests in this command do not count: the push would run whatever they " \
                   "report. In one command only '<test> && VERIFY_OK=1 <command>' counts (no |, ;, " \
                   "|| or & between them)." if is_test_command(cmd) else ""
            c.emit_deny(HOOK, event,
                        f"VERIFY_OK=1 was refused: code changed in this session ({_short(pending)}) "
                        "and no test or typecheck command has run since, so run the tests first; "
                        f"VERIFY_OK=1 is for after they pass.{same} If the project has no tests or you "
                        "cannot verify, do not retry: tell the user what is unverified and let them "
                        "run the command.",
                        command=cmd, files=", ".join(pending[:10]))
            return
        c.log(HOOK, "verify-ok-token", sid, command=cmd)
    elif token:
        c.log(HOOK, "verify-ok-token-ignored", sid, command=cmd)  # only means something on a push/deploy
    if not snap.get("git"):
        hits = [p for p in shell_write_targets(cmd, cwd) if p == UNKNOWN or is_source_file(p, project)]
        if hits:
            _mark_dirty(m, hits)
    if is_test_command(cmd) and not _writes_after_tests(cmd, cwd, project):
        c.touch(m["tested"])
        c.touch(m["rebase"])


def _deny_irreversible(event: dict, hit: str, cmd: str) -> None:
    c.emit_deny(HOOK, event,
                f"'{hit}' is irreversible (it publishes, deploys, pushes or deletes something "
                "other people see). Run the project's tests or typecheck first and report the "
                "command and result to the user. Only after a passing run, re-run the command "
                "prefixed with VERIFY_OK=1 (for example: VERIFY_OK=1 git push). If the project has "
                "no tests or you could not verify, do not add VERIFY_OK=1: tell the user what is "
                "unverified and let them run the command.",
                command=cmd)


def _dirty_files(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            seen = []
            for line in fh:
                line = line.strip()
                if line and line not in seen:
                    seen.append(line)
            return seen
    except OSError:
        return []


def handle_stop(event: dict) -> None:
    sid = c.safe_session(event)
    m = _paths(sid)
    files = untested_changes(event, sid)
    if not files:
        for k in ("dirty", "tested", "ok", "last"):
            c.remove(m[k])
        return
    max_blocks = c.env_int("FOUNDRY_VERIFY_MAX_BLOCKS", 2)
    blocks = c.read_int(m["blocks"])
    reason_skip = None
    # stop_hook_active only means "a Stop hook continued this turn". When that hook was THIS one,
    # we asked already: let the stop through. When it was another one (ship-stop keeps Claude
    # working, and every later stop is active), the edits made since still need a check;
    # skipping and resetting here erased them unseen. The session cap still bounds us.
    if event.get("stop_hook_active") and os.path.exists(m["last"]):
        reason_skip = "stop_hook_active"
    elif event.get("background_tasks"):
        reason_skip = "background tasks in flight"
    elif blocks >= max_blocks:
        reason_skip = f"block cap {max_blocks} reached"
    if reason_skip:
        c.log(HOOK, "allow-unverified-stop", sid, why=reason_skip, files=", ".join(files[:10]))
        if reason_skip != "background tasks in flight":
            c.remove(m["dirty"])  # do not nag on the next, unrelated turn
            c.remove(m["last"])
            snapshot(event, sid, fresh=True)
        return
    c.touch(m["blocks"], str(blocks + 1))
    c.touch(m["last"])
    c.emit_stop_block(HOOK, event,
                      f"Code changed in {len(files)} file(s) ({_short(files)}) and no test or "
                      "typecheck command has run since. Before finishing: run the "
                      "project's tests or typecheck (for example pytest, npm test, npx tsc --noEmit, "
                      "go test ./...), and report the command and its result. If this change cannot "
                      "be tested, say so plainly and explain why. "
                      f"(block {blocks + 1} of at most {max_blocks} this session; FOUNDRY_VERIFY=0 disables)",
                      files=", ".join(files[:10]))


def handle(event: dict) -> None:
    if c.disabled("VERIFY"):
        return
    name = event.get("hook_event_name") or ("PreToolUse" if "tool_name" in event else "Stop")
    if name == "PreToolUse":
        handle_pre(event)
    elif name == "Stop":
        handle_stop(event)


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
