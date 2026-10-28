#!/usr/bin/env python3
"""commit_secret_guard.py: Claude Code PreToolUse hook (matcher: Bash).

When the agent is about to run `git commit`, scan what that commit WILL contain and
block the command (exit 2) if it holds something that looks like a secret.

"What it will contain" is the current index PLUS everything the same Bash command
stages first, because agents usually stage and commit in one call:

  git add -A && git commit -m wip       tracked changes + untracked, not-ignored files
  git add . ; git commit -m x           the same, under the current directory
  git add settings.py && git commit     the named paths (quoted paths and globs work)
  git add -f .env && git commit         named paths, gitignored ones included
  git commit -a / -am / <paths>         tracked changes (whole tree, or the given paths)
  git init && git add . && git commit   the first commit of a new repo

The command is read the way the shell reads it: chains (&&, ||, ;, |, &, newlines),
subshells `( ... )`, redirections (`2>/dev/null`, `2>&1 | tail`), `# comments` and
heredoc bodies are handled; `cd`, `pushd`/`popd`, `git -C DIR`, `bash -c '...'`, `eval`,
runners such as `timeout`, `sudo`, `env`, `xargs` and `find -exec`, and git aliases
(`git ci`, `-c alias.x=...`, `!shell` aliases) are followed. A path the hook cannot know
in advance (`"$FILE"`, `$(...)`) is treated as the whole tree. The command text itself is
scanned too, so a key in a commit message or in a file the command writes is caught.

The index is always scanned with the bundled stdlib scanner, and also with gitleaks when
it is on PATH (more rules), so the verdict does not depend on whether a file was staged
earlier or by this command. Files the command is about to stage go through the bundled
scanner. Output is redacted. Any internal error lets the command run (fail open), so a
broken guard never blocks your work.

Turn it off: start Claude Code with FOUNDRY_COMMIT_SECRET_GUARD=0 in its environment
  (export it in your terminal before you run `claude`; an `export` inside the agent's
  Bash tool does not reach the hook). FOUNDRY_SECRETS_GUARD=0 still works; it is the
  old, deprecated name. The foundry-guardrails plugin has its own, different switch:
  FOUNDRY_SECRET_GUARD.
Allow a known false positive: add the comment  secrets-hygiene: allow  on that line
  (gitleaks:allow works too).

This guards commits the AGENT makes. Commits you type yourself need the git
pre-commit hook from the secrets-hygiene skill as well. A command that copies a secret
in from elsewhere and commits it in the same call (cp ~/key.pem . && git add . && git
commit) is not visible before it runs; the pre-commit hook catches that one.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_secrets  # noqa: E402

SWITCHES = ("FOUNDRY_COMMIT_SECRET_GUARD", "FOUNDRY_SECRETS_GUARD")  # new name first, deprecated alias second
OFF_VALUES = ("0", "false", "off", "no")
GIT_COMMIT_RE = re.compile(r"(?:^|[;&|()]|\s)git\s+(?:-C\s+(\S+)\s+)?(?:-c\s+\S+\s+)*commit\b(.*)")
GIT_ADD_RE = re.compile(r"(?:^|[;&|()\s])git\s+(?:-\S+\s+(?:\S+\s+)?)*(?:add|stage)\b")
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DYNAMIC_RE = re.compile(r"[$`]")          # a word the shell expands at run time
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "time", "command",
            "builtin", "exec", "noglob"}
# Programs that run another command given later on their own command line.
RUNNERS = {"sudo", "doas", "env", "nice", "ionice", "nohup", "timeout", "gtimeout", "stdbuf", "caffeinate",
           "chronic", "unbuffer", "xargs", "find", "watch", "flock"}
PATH_FROM_INPUT = {"xargs", "find"}       # the paths they pass to git come from stdin or a search
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_BUILTINS = {
    "add", "am", "annotate", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file", "check-ignore",
    "checkout", "cherry", "cherry-pick", "clean", "clone", "commit", "commit-tree", "config", "count-objects",
    "describe", "diff", "diff-files", "diff-index", "diff-tree", "difftool", "fetch", "for-each-ref",
    "format-patch", "fsck", "gc", "grep", "hash-object", "help", "init", "log", "ls-files", "ls-remote",
    "ls-tree", "merge", "merge-base", "mergetool", "mv", "notes", "prune", "pull", "push", "range-diff",
    "read-tree", "rebase", "reflog", "remote", "repack", "replace", "reset", "restore", "rev-list", "rev-parse",
    "revert", "rm", "shortlog", "show", "show-branch", "show-ref", "sparse-checkout", "stage", "stash", "status",
    "submodule", "switch", "symbolic-ref", "tag", "update-index", "update-ref", "var", "verify-commit",
    "version", "whatchanged", "worktree", "write-tree", "lfs", "maintenance", "credential",
}
ALIAS_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
REDIR_OPS = ("&>>", "&>", ">>", ">&", ">|", "<<<", "<<-", "<<", "<&", "<>", ">", "<")
COMMAND_TEXT = "(the command itself)"
MAX_FILES = 5000          # untracked files content-scanned per staging command (names are always checked)
MAX_BYTES = 2_000_000     # untracked files larger than this are skipped


@dataclass
class Stage:
    """Files a `git add` (or `git commit -a/<paths>`) in the command will put in the commit."""
    kind: str                 # "all": tracked changes + untracked files; "tracked": tracked changes only
    cwd: str                  # directory git runs in (after cd / -C)
    pathspecs: list = field(default_factory=list)  # empty = the whole work tree
    force: bool = False       # git add -f: gitignored files too
    seq: int = 0              # position in the command; staging after the last commit does not count


@dataclass
class Plan:
    commits: list = field(default_factory=list)   # directories `git commit` runs in
    stages: list = field(default_factory=list)
    inits: list = field(default_factory=list)     # directories a `git init` in the command creates
    unparsed: bool = False                        # some segment could not be tokenized
    commit_seqs: list = field(default_factory=list)  # position of each commit, parallel to `commits`
    seq: int = 0


# ---------------------------------------------------------------- shell reading

def _skip_substitution(s: str, i: int) -> int:
    """`s[i]` starts `$(`, `<(`, `>(` or a backquote. Return the index just past its end."""
    n = len(s)
    if s[i] == "`":
        j = i + 1
        while j < n and s[j] != "`":
            j += 2 if s[j] == "\\" else 1
        return min(j + 1, n)
    depth, j, quote = 0, i + 1, None
    while j < n:
        ch = s[j]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                j += 1
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            j += 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _read_word(s: str, i: int) -> tuple:
    """Skip blanks, then read one shell word (quotes respected). Returns (raw word, end index)."""
    n = len(s)
    while i < n and s[i] in " \t":
        i += 1
    start, quote = i, None
    while i < n:
        ch = s[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            i += 1
        elif ch in " \t\n;&|()<>":
            break
        i += 1
    return s[start:i], i


def _split(command: str) -> list:
    """Read a command into items: ("cmd", text), ("(", ""), (")", "") and ("body", heredoc text, owner).

    Redirections (`>f`, `2>&1`, `&>/dev/null`, `<<EOF`) and `# comments` are dropped, heredoc
    bodies are taken out of the command stream, and `$(...)` / backquotes stay inside their word.
    """
    items, buf, heredocs, quote, i = [], [], [], None, 0
    command = command.replace("\\\n", " ")
    n = len(command)

    def flush():
        text = "".join(buf).strip()
        if text:
            items.append(("cmd", text))
        buf.clear()

    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 1
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            i += 1
        elif ch == "\\" and i + 1 < n:
            buf.append(command[i:i + 2])
            i += 2
        elif ch == "#" and (not buf or buf[-1][-1:] in (" ", "\t")):
            j = command.find("\n", i)       # a comment runs to the end of the line
            i = n if j < 0 else j
        elif (ch == "$" and command.startswith("$(", i)) or ch == "`":
            j = _skip_substitution(command, i)
            buf.append(command[i:j])
            i = j
        elif ch in "<>" or command.startswith("&>", i):
            if ch in "<>" and command.startswith("(", i + 1):  # process substitution <(cmd): a word
                j = _skip_substitution(command, i)
                buf.append(command[i:j])
                i = j
                continue
            k = len(buf)                     # a file-descriptor number right before: 2>/dev/null
            while k > 0 and buf[k - 1].isdigit():
                k -= 1
            if k < len(buf) and (k == 0 or buf[k - 1][-1:] in (" ", "\t")):
                del buf[k:]
            op = next(o for o in REDIR_OPS if command.startswith(o, i))
            word, i = _read_word(command, i + len(op))
            if op in ("<<", "<<-"):
                delim = word.replace("'", "").replace('"', "").replace("\\", "")
                if delim:
                    heredocs.append((delim, op == "<<-", len(items)))
        elif ch == "\n":
            flush()
            i += 1
            while heredocs:                  # heredoc bodies start on the next line
                delim, tabs, owner = heredocs.pop(0)
                body = []
                while i < n:
                    j = command.find("\n", i)
                    line = command[i:] if j < 0 else command[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
                    body.append(line)
                items.append(("body", "\n".join(body), owner))
        elif ch in ";&|":
            flush()
            i += 1
        elif ch in "()":
            flush()
            items.append((ch, ""))
            i += 1
        else:
            buf.append(ch)
            i += 1
    flush()
    return items


def split_segments(command: str) -> list:
    """The simple commands in a shell command line, in order (see `_split`)."""
    return [it[1] for it in _split(command) if it[0] == "cmd"]


def _join(base: str, path: str) -> str:
    return os.path.normpath(os.path.join(base, os.path.expanduser(path)))


def _resolve_dir(base: str, path: str) -> str | None:
    """`path` relative to `base`, or None when the shell computes it at run time ($VAR, $(...))."""
    if DYNAMIC_RE.search(path):
        path = path.replace("${PWD}", base).replace("$PWD", base)
        path = os.path.expandvars(path)
        if DYNAMIC_RE.search(path):
            return None
    return _join(base, path)


def _strip_prefix(tokens: list) -> tuple:
    """Drop `VAR=x`, keywords and runner programs in front of the real command.

    Returns (tokens, paths_from_input): the second is True after xargs / find -exec, whose
    file arguments the hook cannot see.
    """
    from_input = False
    while tokens:
        head = tokens[0]
        base = os.path.basename(head)
        if ENV_ASSIGN_RE.match(head) or head in KEYWORDS:
            tokens = tokens[1:]
        elif base in RUNNERS:
            from_input = from_input or base in PATH_FROM_INPUT
            nxt = [j for j in range(1, len(tokens))
                   if os.path.basename(tokens[j]) in ({"git", "eval"} | SHELLS)]
            tokens = tokens[nxt[0]:] if nxt else []
        else:
            break
    return tokens, from_input


def _parse_add(args: list, cwd: str, from_input: bool = False):
    kind, force, specs, rest = None, False, [], False
    i = 0
    while i < len(args):
        t = args[i]
        if rest or not t.startswith("-") or t == "-":
            specs.append(t)
        elif t == "--":
            rest = True
        elif t in ("-A", "--all", "--no-ignore-removal"):
            kind = "all"
        elif t in ("-u", "--update", "-p", "--patch", "-i", "--interactive", "-e", "--edit"):
            kind = kind or "tracked"
        elif t in ("-f", "--force"):
            force = True
        elif t in ("-n", "--dry-run"):
            return None
        elif t.startswith("--pathspec-from-file"):
            if t == "--pathspec-from-file":
                i += 1
            kind = "all"  # cannot read the list reliably: assume the whole tree
        elif t.startswith("--"):
            pass  # --verbose, --chmod=+x, --intent-to-add, ...
        else:  # combined short flags such as -Av, -fA
            letters = t[1:]
            if "n" in letters:
                return None
            if "A" in letters:
                kind = "all"
            elif any(c in letters for c in "upie"):
                kind = kind or "tracked"
            if "f" in letters:
                force = True
        i += 1
    if from_input or any(DYNAMIC_RE.search(s) for s in specs):
        return Stage(kind or "all", cwd, [], force)  # paths known only at run time: the whole tree
    if kind is None:
        if not specs:
            return None  # `git add` with no paths stages nothing
        kind = "all"     # `git add <path>` stages tracked changes and untracked files under it
    return Stage(kind, cwd, specs, force)


COMMIT_VALUE_SHORT = set("mFCct")
COMMIT_VALUE_LONG = {"--message", "--file", "--reuse-message", "--reedit-message", "--fixup", "--squash",
                     "--author", "--date", "--template", "--cleanup", "--trailer", "--pathspec-from-file"}


def _parse_commit(args: list, cwd: str, plan: Plan) -> None:
    plan.commits.append(cwd)
    plan.commit_seqs.append(plan.seq)
    stage_all, specs, rest, i = False, [], False, 0
    while i < len(args):
        t = args[i]
        if rest or not t.startswith("-") or t == "-":
            specs.append(t)
        elif t == "--":
            rest = True
        elif t in ("--all", "--interactive", "--patch"):
            stage_all = True
        elif t in COMMIT_VALUE_LONG:
            i += 1
            if t == "--pathspec-from-file":
                stage_all = True
        elif t.startswith("--"):
            pass  # --amend, --no-verify, --message=..., ...
        else:
            for j, c in enumerate(t[1:]):
                if c in ("a", "p"):
                    stage_all = True
                if c in COMMIT_VALUE_SHORT:
                    if j == len(t) - 2:
                        i += 1  # the value is the next token: -m "msg", -am "msg"
                    break       # otherwise the value is attached: -mfix
        i += 1
    if any(DYNAMIC_RE.search(s) for s in specs):
        specs, stage_all = [], True
    if specs:
        plan.stages.append(Stage("tracked", cwd, specs, seq=plan.seq))
    elif stage_all:
        plan.stages.append(Stage("tracked", cwd, [], seq=plan.seq))


def _parse_init(args: list, cwd: str, plan: Plan) -> None:
    target, i = None, 0
    while i < len(args):
        t = args[i]
        if t in ("-b", "--initial-branch", "--template", "--separate-git-dir", "--object-format"):
            i += 1
        elif not t.startswith("-") and target is None:
            target = t
        i += 1
    plan.inits.append((_resolve_dir(cwd, target) or cwd) if target else cwd)


def _git_alias(name: str, gdir: str) -> str | None:
    if not os.path.isdir(gdir):
        return None
    try:
        res = subprocess.run(["git", "config", "--get", f"alias.{name}"], cwd=gdir, capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = res.stdout.strip()
    return value if res.returncode == 0 and value else None


def _plan_git(tokens: list, cur: str, plan: Plan, depth: int, from_input: bool) -> None:
    gdir, i, aliases = cur, 1, {}
    while i < len(tokens) and tokens[i].startswith("-"):
        t = tokens[i]
        if t == "-C" and i + 1 < len(tokens):
            gdir = _resolve_dir(gdir, tokens[i + 1]) or gdir
            i += 2
        elif t in ("-c", "--git-dir", "--work-tree", "--namespace", "--config-env"):
            if i + 1 < len(tokens):
                value = tokens[i + 1]
                if t == "--work-tree":
                    gdir = _resolve_dir(gdir, value) or gdir
                elif t == "-c" and value.lower().startswith("alias.") and "=" in value:
                    name, alias = value[6:].split("=", 1)
                    aliases[name.lower()] = alias
            i += 2
        else:
            if t.startswith("--work-tree="):
                gdir = _resolve_dir(gdir, t.split("=", 1)[1]) or gdir
            i += 1
    if i >= len(tokens):
        return
    sub, args = tokens[i], tokens[i + 1:]
    plan.seq += 1
    if sub in ("add", "stage"):
        st = _parse_add(args, gdir, from_input)
        if st:
            st.seq = plan.seq
            plan.stages.append(st)
    elif sub == "commit":
        _parse_commit(args, gdir, plan)
    elif sub == "init":
        _parse_init(args, gdir, plan)
    elif sub not in GIT_BUILTINS and depth < 3 and ALIAS_NAME_RE.match(sub):
        alias = aliases.get(sub.lower()) or _git_alias(sub, gdir)
        if alias:
            rest = " ".join(shlex.quote(a) for a in args)
            if alias.startswith("!"):     # a shell alias runs from the top of the work tree
                plan_command(f"{alias[1:]} {rest}", toplevel(gdir) or gdir, plan, depth + 1)
            else:
                plan_command(f"git {alias} {rest}", gdir, plan, depth + 1)


def plan_command(command: str, cwd: str, plan: Plan | None = None, depth: int = 0) -> Plan:
    """Work out which commits a Bash command makes and which files it stages on the way."""
    plan = plan or Plan()
    cur, prev, subshells, pushed = cwd, cwd, [], []
    feeds_shell: dict = {}   # item index -> True when a heredoc body there is a script run by a shell
    for idx, item in enumerate(_split(command)):
        kind, text = item[0], item[1]
        if kind == "(":
            subshells.append(cur)
            continue
        if kind == ")":
            if subshells:
                cur = subshells.pop()   # a cd inside ( ... ) does not leak out
            continue
        if kind == "body":
            if feeds_shell.get(item[2]) and depth < 3:
                plan_command(text, cur, plan, depth + 1)
            continue
        try:
            tokens = shlex.split(text)
        except ValueError:
            plan.unparsed = True
            tokens = text.split()
        tokens, from_input = _strip_prefix(tokens)
        if not tokens:
            continue
        prog = os.path.basename(tokens[0])
        if prog in ("cd", "pushd", "popd"):
            targets = [t for t in tokens[1:] if not t.startswith("-") or t == "-"]
            if prog == "popd":
                new = pushed.pop() if pushed else None
            elif not targets:
                new = None if prog == "pushd" else os.path.expanduser("~")
            elif targets[0] == "-":
                new = prev                   # cd -: back to the previous directory
            else:
                new = _resolve_dir(cur, targets[0])  # None for $VAR / $(...): stay where we are
                if new and prog == "pushd":
                    pushed.append(cur)
            if new:
                prev, cur = cur, new
            continue
        if prog in SHELLS:
            flags = [t for t in tokens[1:] if t.startswith("-") and not t.startswith("--")]
            if any("c" in t[1:] for t in flags):       # bash -c '...', bash -lc '...'
                pos = next(j for j, t in enumerate(tokens) if t in flags and "c" in t[1:])
                if pos + 1 < len(tokens) and depth < 3:
                    plan_command(tokens[pos + 1], cur, plan, depth + 1)
            else:
                feeds_shell[idx] = True                  # bash <<'EOF' ... EOF
            continue
        if prog == "eval" and depth < 3:
            plan_command(" ".join(tokens[1:]), cur, plan, depth + 1)
            continue
        if prog == "git":
            _plan_git(tokens, cur, plan, depth, from_input)
    return plan


def parse_commit(command: str) -> tuple:
    """Compatibility helper: (is_commit, -C dir or None, stages tracked changes at commit time)."""
    p = plan_command(command, ".")
    if not p.commits:
        return False, None, False
    d = p.commits[0]
    tracked = any(s.kind == "tracked" and s.cwd == d and not s.pathspecs for s in p.stages)
    return True, (None if d == "." else d), tracked


# ---------------------------------------------------------------- scanning

def _git(args: list, cwd: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "git failed")
    return res.stdout


def toplevel(path: str) -> str | None:
    if not os.path.isdir(path):
        return None
    try:
        return os.path.realpath(_git(["rev-parse", "--show-toplevel"], path).strip())
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None


def run_gitleaks(repo: str) -> list | None:
    """(file, line, rule) for each staged finding, [] when clean, None if gitleaks is missing or failed."""
    exe = shutil.which("gitleaks")
    if not exe:
        return None
    try:
        # --exit-code 3 tells "found leaks" apart from gitleaks' own errors (exit 1), such as a
        # broken .gitleaks.toml, which must not read as a leak.
        res = subprocess.run(
            [exe, "git", "--pre-commit", "--staged", "--redact", "--no-banner", "--no-color",
             "--exit-code", "3", "--report-format", "json", "--report-path", "-", repo],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode == 0:
        return []
    if res.returncode != 3:
        return None
    try:
        found = json.loads(res.stdout or "[]")
        return [(str(f.get("File", "?")), int(f.get("StartLine", 0)), str(f.get("RuleID", "gitleaks")))
                for f in found]
    except (ValueError, TypeError, AttributeError):
        return [("?", 0, "gitleaks reported a leak (run: gitleaks git --pre-commit --staged -v)")]


def scan_index(top: str) -> list:
    """Findings in what is staged now: the bundled scanner, plus gitleaks when it is installed."""
    found = scan_secrets.scan_diff_mode(True, top)
    out = [f.render() for f in found]
    seen = {(f.path, f.line) for f in found}
    staged: dict = {}
    for path, line, rule in run_gitleaks(top) or []:
        if (path, line) in seen:
            continue
        if path not in staged:
            try:
                staged[path] = _git(["show", f":{path}"], top).splitlines()
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                staged[path] = []
        text = staged[path][line - 1] if 0 < line <= len(staged[path]) else ""
        if any(p in text for p in scan_secrets.ALLOW_PRAGMAS):
            continue  # the same allow comment works for both scanners
        out.append(f"{path}:{line}: {rule} (gitleaks): REDACTED")
    return out


def scan_stage(st: Stage, top: str, git_prefix: list) -> list:
    """Findings for the files one staging command will add. `git_prefix` targets a not-yet-created repo."""
    run_dir = os.path.realpath(st.cwd) if st.pathspecs else top
    tail = ["--", *st.pathspecs] if st.pathspecs else []
    out: list = []
    if not git_prefix:  # a brand-new repo has no tracked files yet
        out += [f.render() for f in scan_secrets.scan_diff_mode(False, run_dir, st.pathspecs or None)]
    if st.kind == "all":
        ls = [*git_prefix, "ls-files", "-z", "--others"] + ([] if st.force else ["--exclude-standard"]) + tail
        names = [n for n in _git(ls, run_dir).split("\0") if n]
        for n in names[MAX_FILES:]:  # past the content cap, still refuse secret file names
            if scan_secrets.is_secret_filename(n):
                out.append(scan_secrets.Finding(os.path.relpath(os.path.join(run_dir, n), top), 0,
                                                "secret-file", "(file name)").render())
        paths = [os.path.join(run_dir, n) for n in names[:MAX_FILES]]
        for f in scan_secrets.scan_paths(paths, max_bytes=MAX_BYTES, follow_symlinks=False):
            f.path = os.path.relpath(f.path, top)
            out.append(f.render())
    return out


def collect_findings(plan: Plan, cwd: str) -> list:
    tops: dict = {}  # toplevel -> git prefix ([] for an existing repo, a temp git dir for `git init`)
    last_commit: dict = {}  # toplevel -> position of the last commit in the command
    tmpdirs: list = []
    inits = [os.path.realpath(d) for d in plan.inits]
    seqs = plan.commit_seqs + [10 ** 9] * (len(plan.commits) - len(plan.commit_seqs))

    def resolve(path: str):
        real = os.path.realpath(path)
        top = toplevel(real)
        if top:
            return top
        for d in inits:  # the command runs `git init` first: the repo does not exist yet
            if real == d or real.startswith(d + os.sep):
                return d
        return None

    def note(what: str, exc: Exception) -> None:
        print(f"commit_secret_guard: skipped {what} ({type(exc).__name__}: {exc})", file=sys.stderr)

    try:
        for d, seq in zip(plan.commits, seqs):
            top = resolve(d)
            if not top:
                continue
            last_commit[top] = max(seq, last_commit.get(top, seq))
            if top in tops:
                continue
            if toplevel(top):
                tops[top] = []
            elif os.path.isdir(top):
                tmp = tempfile.mkdtemp(prefix="fbk-guard-")
                tmpdirs.append(tmp)
                prefix = ["--git-dir", tmp, "--work-tree", top]
                _git([*prefix, "init", "-q"], top)
                tops[top] = prefix
        messages: list = []
        for top, prefix in tops.items():
            if prefix:
                continue  # a new repo: the index is empty until the command runs
            try:
                messages += scan_index(top)
            except Exception as exc:  # noqa: BLE001 - one failed scan must not discard the others
                note("the index scan", exc)
        for st in plan.stages:
            top = resolve(st.cwd)
            if top in tops and st.seq <= last_commit[top]:
                try:
                    messages += scan_stage(st, top, tops[top])
                except Exception as exc:  # noqa: BLE001 - e.g. a path outside the repo: git add fails too
                    note(f"git add {' '.join(st.pathspecs) or '(whole tree)'}", exc)
        return list(dict.fromkeys(messages))
    finally:
        for tmp in tmpdirs:
            shutil.rmtree(tmp, ignore_errors=True)


def scan_command_text(command: str) -> list:
    """A key typed into the command: a commit message, or a file the command writes then commits.

    Provider-shaped keys only; the generic `name = value` rule is skipped on prose."""
    return [f.render() for f in scan_secrets.scan_text(COMMAND_TEXT, command, skip_rules=("generic-assignment",))]


def switched_off() -> bool:
    for name in SWITCHES:
        if os.environ.get(name, "1").strip().lower() in OFF_VALUES:
            return True
    return False


def main() -> int:
    if switched_off():
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            return 0
        command = (payload.get("tool_input") or {}).get("command") or ""
        if not isinstance(command, str) or "git" not in command:
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        plan = plan_command(command, cwd)
        if not plan.commits and plan.unparsed and GIT_COMMIT_RE.search(command):
            # Could not tokenize the command but it looks like a commit: scan conservatively.
            plan.commits.append(cwd)
            if GIT_ADD_RE.search(command):
                plan.stages.append(Stage("all", cwd, []))
        if not plan.commits:
            return 0
        messages = scan_command_text(command) + collect_findings(plan, cwd)
    except Exception as exc:  # fail open: a guard bug must never block the user's work
        print(f"commit_secret_guard: internal error, not blocking ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0

    if not messages:
        return 0
    print("Blocked: this commit, including files the same command stages with git add, "
          "appears to contain secrets (values redacted):", file=sys.stderr)
    for m in messages[:20]:
        print(f"  {m}", file=sys.stderr)
    print(
        "Do not stage that file (or unstage it: git restore --staged <file>), move the value into "
        ".env.local (gitignored), and reference it by name. A key in the command itself (a commit "
        "message, or a file the command writes) must come out of the command. If a real key was ever "
        "committed or pushed, treat it as leaked: run the secrets-hygiene skill's rotation flow. "
        "False positive: add the comment 'secrets-hygiene: allow' on that line.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
