#!/usr/bin/env python3
"""destructive-guard: PreToolUse(Bash) hook that denies catastrophic commands.

Denies: recursive rm of /, ~, $HOME, *, . or a top-level system directory;
force-push to main/master (and plain --force anywhere unless allowed);
git reset --hard / git checkout -- . / git restore . / git clean -f when they
would destroy uncommitted work; DROP / TRUNCATE / DELETE-without-WHERE sent
through a database client; dd to a disk device; mkfs; fork bombs;
chmod/chown -R on / or $HOME; piping a download straight into a shell;
shutdown / reboot / halt. A DELETE whose WHERE is always true (WHERE 1,
1=1, true, 'x'='x', col=col, ... OR 1=1) counts as no WHERE. Also (2026-10-28 review): rm -rf of .git, path
spellings that resolve to /, $HOME or the cwd (//, ~/.., $PWD, ../..), find
<root> -delete with no -name/-path filter, git checkout -f / switch
--discard-changes on a dirty tree, git stash clear, eval/source of a
download, prisma migrate reset, supabase db reset --linked.

Allows (on purpose): rm -rf node_modules, rm -rf ./dist, git status,
git push --force-with-lease to a feature branch, DELETE ... WHERE ...,
git reset --hard on a clean tree.

Disable: FOUNDRY_DESTRUCTIVE_GUARD=0
Allow one rule for your session: FOUNDRY_DESTRUCTIVE_ALLOW=rule1,rule2
  (set in your shell or settings env, not in the command, so the agent
  cannot grant it to itself)
Allow plain force-push to non-protected branches: FOUNDRY_ALLOW_FORCE_PUSH=1
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "destructive-guard"

PROTECTED_BRANCHES = {"main", "master"}
_SYSTEM_DIRS = {"/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64", "/opt",
                "/private", "/proc", "/root", "/sbin", "/srv", "/sys", "/usr", "/var",
                "/System", "/Users", "/Applications", "/Library", "/Volumes"}
_DANGER_LITERALS = {"/", "/*", "~", "~/", "~/*", "$HOME", "${HOME}", "$HOME/", "${HOME}/",
                    "$HOME/*", "${HOME}/*", "*", ".", "./", "./*", "..", "../", "../*", ".*"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_DB_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "duckdb", "sqlcmd", "clickhouse-client",
               "cockroach", "snowsql", "bq", "turso", "pgcli", "mycli", "litecli"}


def _protected_branches() -> set[str]:
    extra = os.environ.get("FOUNDRY_PROTECTED_BRANCHES", "")
    return PROTECTED_BRANCHES | {b.strip() for b in extra.split(",") if b.strip()}


_HOME_VAR = re.compile(r"^(?:\$HOME|\$\{HOME(?::[?\-=+][^}]*)?\})(?=/|$)")
_PWD_VAR = re.compile(r"^(?:\$PWD|\$\{PWD(?::[?\-=+][^}]*)?\}|\$\(\s*pwd\s*\)|`\s*pwd\s*`)(?=/|$)")


def _resolve(tok: str, cwd: str) -> str | None:
    """Best-effort absolute form of an rm target, or None when it is not static."""
    home = os.environ.get("HOME", "")
    t = _HOME_VAR.sub(lambda m: home or m.group(0), tok)
    t = _PWD_VAR.sub(lambda m: cwd or m.group(0), t)
    t = os.path.expanduser(t)
    if "$" in t or "`" in t or any(ch in t for ch in "*?["):
        return None
    if not os.path.isabs(t):
        if not cwd:
            return None
        t = os.path.join(cwd, t)
    return os.path.normpath(t)


def _dangerous_target(tok: str, cwd: str = "") -> bool:
    if tok in _DANGER_LITERALS:
        return True
    t = tok.rstrip("/") or "/"
    if t in _SYSTEM_DIRS:
        return True
    home = os.environ.get("HOME", "")
    if home and c.realpath(t) == c.realpath(home):
        return True
    if t.startswith("/") and t.endswith("/*") and (t[:-2] or "/") in _SYSTEM_DIRS:
        return True
    # Normalized forms: //, /./, /.., ~/.., $HOME/., ${HOME:?}/, $PWD, $(pwd), ../..
    r = _resolve(tok, cwd)
    if r is None:
        return False
    cands = {r, c.realpath(r)}
    sys_real = _SYSTEM_DIRS | {c.realpath(d) for d in _SYSTEM_DIRS}
    if cands & ({"/"} | sys_real):
        return True
    protect = [x for x in (home, cwd) if x]
    for p in protect:
        pr = {os.path.normpath(p), c.realpath(p)}
        for cand in cands:
            # the directory itself, or any ancestor of it
            if any(c.is_inside(q, cand) for q in pr):
                return True
    return False


def _is_git_dir(tok: str, cwd: str) -> bool:
    r = _resolve(tok, cwd) if cwd else None
    base = os.path.basename((r or tok).rstrip("/"))
    return base == ".git"


def _short_flags(argv: list[str]) -> str:
    out = ""
    for tok in argv[1:]:
        if tok == "--":
            break
        if tok.startswith("-") and not tok.startswith("--"):
            out += tok[1:]
    return out


def _long_flags(argv: list[str]) -> set[str]:
    return {t.split("=")[0] for t in argv[1:] if t.startswith("--")}


def _git_sub(argv: list[str]) -> tuple[str, list[str]]:
    """Return (subcommand, rest) skipping git's global options."""
    i = 1
    while i < len(argv):
        t = argv[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(argv):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, argv[i + 1:]
    return "", []


def _dirty(cwd: str, include_untracked: bool = False) -> bool | None:
    args = ["status", "--porcelain"]
    if not include_untracked:
        args.append("--untracked-files=no")
    out = c.git(cwd, *args)
    if out is None or out.returncode != 0:
        return None
    return bool(out.stdout.strip())


def _current_branch(cwd: str) -> str:
    out = c.git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if out is None or out.returncode != 0:
        return ""
    return out.stdout.strip()


def check_rm(argv, cwd=""):
    if os.path.basename(argv[0]) != "rm":
        return None
    shorts = _short_flags(argv)
    longs = _long_flags(argv)
    recursive = "r" in shorts or "R" in shorts or "--recursive" in longs
    if "--no-preserve-root" in longs:
        return ("rm-root", "rm with --no-preserve-root can delete the whole filesystem.")
    if not recursive:
        return None
    targets = [t for t in argv[1:] if not t.startswith("-")]
    bad = [t for t in targets if _dangerous_target(t, cwd)]
    if bad:
        return ("rm-rf-root",
                f"recursive rm of {bad[0]!r} would delete a home, system, or whole working directory. "
                "Name the exact subdirectory to remove (for example rm -rf ./dist or rm -rf node_modules).")
    if any(_is_git_dir(t, cwd) for t in targets):
        return ("rm-rf-git",
                "recursive rm of a .git directory deletes the repository's whole history, including "
                "commits that were never pushed. Fix the repository state with git commands instead.")
    return None


_FIND_NARROW = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex",
                "-iregex", "-newer", "-mtime", "-mmin", "-atime", "-amin", "-ctime", "-cmin",
                "-size", "-empty", "-user", "-group", "-perm", "-links", "-inum", "-samefile",
                "-lname", "-ilname"}


def check_find(argv, cwd=""):
    """find <home|/|cwd> -delete (or -exec rm) with no name/age/size filter."""
    if os.path.basename(argv[0]) != "find":
        return None
    rest = argv[1:]
    starts = []
    for t in rest:
        if t.startswith("-") or t in ("(", "!", ")"):
            break
        starts.append(t)
    preds = set(rest[len(starts):])
    deletes = "-delete" in preds
    for i, t in enumerate(rest):
        if t in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(rest) \
                and os.path.basename(rest[i + 1]) in ("rm", "shred", "unlink"):
            deletes = True
    if not deletes or preds & _FIND_NARROW:
        return None
    bad = [t for t in (starts or ["."]) if _dangerous_target(t, cwd)]
    if bad:
        return ("find-delete-root",
                f"find {bad[0]} with -delete and no -name/-path filter deletes everything under a "
                "home, system, or whole working directory. Add a filter such as -name '*.pyc'.")
    return None


def check_git(argv, cwd):
    if os.path.basename(argv[0]) != "git":
        return None
    sub, rest = _git_sub(argv)
    protected = _protected_branches()
    if sub == "push":
        if "--dry-run" in rest or "-n" in rest:
            return None
        flags = [t for t in rest if t.startswith("-")]
        refs = [t for t in rest if not t.startswith("-")]
        hard_force = any(f in ("--force", "-f") or re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", f) for f in flags) \
            or any(r.startswith("+") for r in refs)
        lease = any(f.startswith("--force-with-lease") or f.startswith("--force-if-includes") for f in flags)
        deleting = "--delete" in flags or "-d" in flags or any(r.startswith(":") for r in refs)
        mirror = "--mirror" in flags
        # refs[0] is usually the remote; branch names come after it
        branch_refs = refs[1:] if len(refs) > 1 else []
        targets = set()
        for r in branch_refs:
            r = r.lstrip("+")
            dst = r.split(":")[-1] if ":" in r else r
            targets.add(dst.replace("refs/heads/", ""))
        if not branch_refs and (hard_force or lease):
            cur = _current_branch(cwd)
            if cur:
                targets.add(cur)
        hits = targets & protected
        if mirror:
            return ("git-push-mirror", "git push --mirror overwrites and deletes every ref on the remote.")
        if deleting and hits:
            return ("git-delete-protected",
                    f"this deletes the protected branch {sorted(hits)[0]!r} on the remote.")
        if (hard_force or lease) and hits:
            return ("git-force-push-protected",
                    f"force-pushing to {sorted(hits)[0]!r} rewrites shared history. Push a new branch "
                    "and open a pull request instead.")
        if hard_force and not c.env_flag("FOUNDRY_ALLOW_FORCE_PUSH"):
            return ("git-force-push",
                    "plain --force can overwrite commits someone else pushed. Use "
                    "git push --force-with-lease, which refuses if the remote moved.")
        return None
    if sub == "reset" and "--hard" in rest:
        if _dirty(cwd):
            return ("git-reset-hard",
                    "git reset --hard would throw away uncommitted changes. Run git stash "
                    "(recoverable) or commit first.")
        return None
    if sub == "clean":
        shorts = "".join(t[1:] for t in rest if t.startswith("-") and not t.startswith("--"))
        if "f" not in shorts and "--force" not in rest:
            return None
        if "n" in shorts or "--dry-run" in rest:
            return None
        if "x" in shorts or "X" in shorts or _dirty(cwd, include_untracked=True):
            return ("git-clean",
                    "git clean -f permanently deletes untracked files (with -x also ignored files such "
                    "as .env). Run git clean -n first to list what would go, then delete paths by name.")
        return None
    if sub == "stash" and rest[:1] == ["clear"]:
        return ("git-stash-clear",
                "git stash clear deletes every stash entry, and stashes are uncommitted work. "
                "Drop a specific entry with git stash drop stash@{N} after checking it.")
    if (sub == "checkout" and ("-f" in rest or "--force" in rest)) or \
            (sub == "switch" and ("--discard-changes" in rest or "-f" in rest or "--force" in rest)):
        if _dirty(cwd):
            return ("git-discard-all",
                    f"git {sub} with --force/--discard-changes throws away every uncommitted change. "
                    "Run git stash first.")
        return None
    if sub in ("checkout", "restore"):
        pathspec_all = any(t in (".", ":/", "*") for t in rest)
        if not pathspec_all:
            return None
        if sub == "restore" and "--staged" in rest and "--worktree" not in rest and "-W" not in rest:
            return None
        if _dirty(cwd):
            return ("git-discard-all",
                    f"git {sub} . discards every uncommitted change in the tree. Run git stash "
                    "instead, or restore specific files by name.")
        return None
    return None


_DROP = re.compile(r"(?i)\bdrop\s+(table|database|schema)\b")
_TRUNC = re.compile(r"(?i)\btruncate\s+(table\s+)?[A-Za-z_\"`\[]")
_DELETE = re.compile(r"(?is)\bdelete\s+from\s+[\w.\"`\[\]]+(.*?)(?:;|\"|'|$)")


def _db_client_present(argvs) -> bool:
    for argv in argvs:
        head = os.path.basename(argv[0])
        if head in _DB_CLIENTS:
            return True
        joined = " ".join(argv[:4])
        if re.search(r"\b(supabase\s+db|prisma\s+db\s+execute|wrangler\s+d1\s+execute|"
                     r"rails\s+(db|dbconsole)|psql|mysql)\b", joined):
            return True
    return False


def check_db_reset(argv):
    j = " ".join(os.path.basename(argv[0]) if k == 0 else t for k, t in enumerate(argv))
    j = re.sub(r"^(?:npx|pnpm\s+(?:exec|dlx)|bunx|yarn)\s+", "", j)
    if re.match(r"^prisma\s+(?:migrate\s+reset|db\s+push\s+.*--force-reset)\b", j):
        return ("db-reset", "this drops and recreates the database DATABASE_URL points at, which "
                            "may be a shared or hosted one. A human should run it after checking the URL.")
    if re.match(r"^supabase\s+db\s+reset\b", j) and re.search(r"\s--(linked|db-url)\b", j):
        return ("db-reset", "supabase db reset against a linked/remote project wipes its data.")
    return None


def check_sql(cmd: str, argvs):
    if not _db_client_present(argvs):
        return None
    if _DROP.search(cmd):
        return ("sql-drop", "DROP TABLE/DATABASE/SCHEMA destroys data. Write a reviewed migration "
                            "and run it through your migration tool after a backup.")
    if _TRUNC.search(cmd):
        return ("sql-truncate", "TRUNCATE deletes every row. Use DELETE ... WHERE ... on the rows you mean.")
    for m in _DELETE.finditer(cmd):
        if not re.search(r"(?i)\bwhere\b", m.group(1) or ""):
            return ("sql-delete-no-where",
                    "DELETE FROM without a WHERE clause deletes every row. Add a WHERE clause "
                    "(run the matching SELECT first to check the count).")
    # the SQL text as the client receives it: shell quotes removed by the tokenizer; plus the raw
    # text when a heredoc carries the SQL, since its lines are split into separate "commands"
    texts = [" ".join(a) for a in argvs] + [t for a in argvs for t in a[1:]] + (["\n".join(
        cmd.splitlines()[1:])] if "<<" in cmd else [])
    for text in texts:
        text = _SQL_COMMENT.sub(" ", text)  # WHERE 1=1 -- cleanup  is still WHERE 1=1
        for m in _DELETE_WHERE.finditer(text):
            if _always_true(m.group(1)):
                return ("sql-delete-no-where",
                        "DELETE with an always-true WHERE (WHERE 1, WHERE 1=1, WHERE true, "
                        "WHERE col=col, WHERE ... OR 1=1) deletes every row, the same as no WHERE. "
                        "Name the rows you mean (run the matching SELECT first to check the count).")
    return None


_DELETE_WHERE = re.compile(r"(?is)\bdelete\s+from\s+[\w.\"`\[\]]+\s+where\s+(.*?)\s*"
                           r"(?=;|$|\b(?:returning|order\s+by|limit)\b)")
_NUM = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def _split_top(expr: str, word: str) -> list[str]:
    """Split expr on a keyword (OR / AND) outside quotes and parentheses."""
    parts, buf, depth, quote, i = [], [], 0, "", 0
    pat = re.compile(rf"(?i)\b{word}\b")
    while i < len(expr):
        ch = expr[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif depth == 0 and pat.match(expr, i) and (i == 0 or not expr[i - 1].isalnum()):
            parts.append("".join(buf))
            buf = []
            i += len(word)
            continue
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def _unwrap(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        inner = expr[1:-1]
        depth = 0
        for ch in inner:  # only strip when the outer parens enclose the whole expression
            depth += (ch == "(") - (ch == ")")
            if depth < 0:
                return expr
        expr = inner.strip()
    return expr


def _literal(tok: str):
    tok = tok.strip()
    if _NUM.match(tok):
        return float(tok)
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"" and tok[0] not in tok[1:-1]:
        return tok[1:-1]
    if tok.lower() in ("true", "false"):
        return tok.lower() == "true"
    return None


_CMP = re.compile(r"^(.+?)\s*(==|=|<>|!=|>=|<=|>|<|\bis\b)\s*(.+)$", re.I)


def _atom_true(atom: str) -> bool:
    atom = _unwrap(atom)
    low = atom.lower()
    if low == "true" or (_NUM.match(atom) and float(atom) != 0):
        return True
    if re.match(r"(?i)^not\s+(0|false)$", atom):
        return True
    if len(atom) >= 3 and atom[0] in "'\"" and _NUM.match(atom[1:-1] or "x") and float(atom[1:-1]) != 0:
        return True  # WHERE '1'
    m = _CMP.match(atom)
    if not m:
        return False
    left, op, right = _unwrap(m.group(1)), m.group(2).lower(), _unwrap(m.group(3))  # (1)=(1)
    if op in ("=", "==", ">=", "<=", "is") and left.lower() == right.lower() and not re.search(r"[()]", left):
        return True  # col = col, 'x' = 'x', 1 = 1
    a, b = _literal(left), _literal(right)
    if a is None or b is None or type(a) is not type(b):
        return False
    try:
        return {"=": a == b, "==": a == b, "is": a == b, "<>": a != b, "!=": a != b,
                ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
    except TypeError:
        return False


def _always_true(clause: str) -> bool:
    """True when a WHERE clause matches every row (WHERE 1, 1=1, x=x, ... OR true)."""
    clause = (clause or "").strip()
    if not clause:
        return False
    for disjunct in _split_top(_unwrap(clause), "or"):
        conjuncts = _split_top(_unwrap(disjunct), "and")
        def true(part: str) -> bool:
            inner = _unwrap(part)
            return _always_true(inner) if inner != part else _atom_true(part)
        if conjuncts and all(part and true(part) for part in conjuncts):
            return True
    return False


def check_misc(argv):
    head = os.path.basename(argv[0])
    if head == "dd":
        for t in argv[1:]:
            if t.startswith("of=/dev/") and t not in ("of=/dev/null", "of=/dev/stdout", "of=/dev/stderr"):
                return ("dd-disk", "dd to a device file overwrites a disk.")
    if re.match(r"^mkfs(\.\w+)?$", head) or head in ("mke2fs", "newfs", "wipefs"):
        return ("mkfs", f"{head} formats a filesystem.")
    if head == "diskutil" and len(argv) > 1 and re.match(r"(?i)^(erase\w*|partitionDisk|zeroDisk|secureErase)$", argv[1]):
        return ("mkfs", "diskutil erase/partition wipes a disk.")
    if head in ("chmod", "chown", "chgrp"):
        shorts = _short_flags(argv)
        if "R" in shorts or "--recursive" in _long_flags(argv):
            targets = [t for t in argv[2:] if not t.startswith("-")]
            if any(_dangerous_target(t) and t not in (".", "./", "*", "./*") for t in targets):
                return ("chmod-recursive-root",
                        f"recursive {head} on a system or home directory can make the machine unusable.")
    if head in ("shutdown", "reboot", "halt", "poweroff"):
        return ("shutdown", f"{head} stops the machine and every running session.")
    if head == "systemctl" and len(argv) > 1 and argv[1] in ("reboot", "poweroff", "halt", "kexec"):
        return ("shutdown", "systemctl reboot/poweroff stops the machine.")
    if head == "init" and len(argv) > 1 and argv[1] in ("0", "6"):
        return ("shutdown", "init 0/6 stops the machine.")
    return None


_FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:")
_PIPE_SUBST = re.compile(
    r"(?:^|[\s;&|(/])(?:(?:ba|z|da|k)?sh|source|eval|\.)\s+(?:-[a-zA-Z]+\s+)*"
    r"(?:<\s*\(|[\"']?\$\()\s*(?:curl|wget)\b")
_STDIN_INTERP = {"python", "python3", "node", "perl", "ruby", "php"}


def check_pipe_to_shell(cmd: str, pipelines):
    if _PIPE_SUBST.search(cmd):
        return ("curl-pipe-sh", "running a downloaded script without reading it first.")
    for stages in pipelines:
        heads = [os.path.basename(a[0]) for a in stages]
        for i, h in enumerate(heads):
            later = stages[i + 1:]
            interp_stdin = any(os.path.basename(a[0]) in _STDIN_INTERP and (len(a) == 1 or a[1] == "-")
                               for a in later)
            if h in ("curl", "wget") and (any(x in _SHELLS for x in heads[i + 1:]) or interp_stdin):
                return ("curl-pipe-sh",
                        "piping a download straight into a shell runs code nobody has read. "
                        "Download it to a file, read it, then run it.")
    return None


def evaluate(cmd: str, cwd: str = "") -> tuple[str, str] | None:
    """Return (rule, reason) for a denied command, or None to allow."""
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    if _FORK_BOMB.search(cmd):
        return ("fork-bomb", "this is a fork bomb; it exhausts the process table.")
    pipelines = c.command_stages(cmd)
    argvs = [a for p in pipelines for a in p]
    hit = check_pipe_to_shell(cmd, pipelines) or check_sql(cmd, argvs)
    if hit:
        return hit
    for argv in argvs:
        hit = (check_rm(argv, cwd) or check_find(argv, cwd) or check_git(argv, cwd)
               or check_misc(argv) or check_db_reset(argv))
        if hit:
            return hit
    return None


def handle(event: dict) -> None:
    if c.disabled("DESTRUCTIVE_GUARD"):
        return
    if event.get("tool_name") != "Bash":
        return
    tin = event.get("tool_input") or {}
    cmd = tin.get("command") if isinstance(tin, dict) else None
    hit = evaluate(cmd or "", event.get("cwd") or os.getcwd())
    if not hit:
        return
    rule, why = hit
    allowed = {r.strip() for r in os.environ.get("FOUNDRY_DESTRUCTIVE_ALLOW", "").split(",") if r.strip()}
    if rule in allowed:
        c.log(HOOK, "allow-override", c.safe_session(event), rule=rule, command=cmd)
        return
    c.emit_deny(HOOK, event,
                f"Blocked destructive command (rule {rule}): {why} If a human really wants this, "
                f"they can run it themselves, or allow the rule for the session with "
                f"FOUNDRY_DESTRUCTIVE_ALLOW={rule} in their shell or settings env.",
                rule=rule, command=cmd)


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
