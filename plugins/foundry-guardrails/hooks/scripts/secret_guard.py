#!/usr/bin/env python3
"""secret-guard: PreToolUse(Bash|Read) hook that keeps secrets out of the transcript.

Anything a command prints, or a file Claude reads, goes into the conversation
and to the model provider. This hook denies the common, well-meaning ways an
agent leaks a secret:

  * Reading a secret file: Read(.env), cat/grep/head/sed/awk on .env, *.pem,
    *.key, SSH private keys, ~/.aws/credentials, .netrc, .npmrc, .pypirc,
    .git-credentials, docker/kube/gh config, service-account JSON.
  * Browser credential stores (Login Data, Cookies, key4.db, logins.json)
    and keychain database files, by any command.
  * Password-manager CLIs: bw, op, lpass, secret-tool, pass/gopass show,
    keepassxc-cli, security dump-keychain / find-*-password -w.
  * Token printers: gh auth token, gcloud auth print-access-token,
    aws configure get, az account get-access-token, kubectl config view --raw.
  * Whole-environment dumps: env, printenv, set, export -p, declare -p.
  * Echoing a variable named like a secret ($API_KEY, $GITHUB_TOKEN), or any
    variable in a command that just sourced an env file.
  * Also: globs that expand to .env (cat .env*), grep -r for a secret name in a
    directory holding .env, git diff/show/blame/log -p of a secret file,
    console.log(process.env) / print(os.environ) in inline code, heroku config,
    docker compose config, and the Grep tool in content mode on a secret file.
  * Simple indirection: a variable bound in the same command (f=.env; cat "$f",
    for f in .env*; do cat "$f"; done, ... | while read f), a reader of $(...) whose
    command names a secret file, find -exec <reader> on secret names (or on a folder
    holding .env with no name filter), ... | xargs <reader> fed by a command naming a
    secret file, and a copy (cp/mv .env x) read later in the same command. Also ls -a/-A of
    a folder holding .env feeding a reader, printenv/echo ${!k} of names picked at run time
    (printenv $(env | cut -d= -f1 | grep AWS)), and code an interpreter reads from a heredoc
    or here-string (python3 - <<'PY' ... open('.env') ... PY), versioned names included.

Allowed on purpose: source .env / . .env (loads without printing),
test -f .env, ls .env, cp .env.example .env, docker --env-file .env,
echo ".env" >> .gitignore, cat .env.example, cat id_ed25519.pub.
Names only (key names, never values), optionally piped into sort/uniq/wc/head/tail:
cut -d= -f1 .env, sed 's/=.*//' .env (also -E, -n ...p), awk -F= '{print $1}' .env,
grep -o '^[A-Za-z_][A-Za-z0-9_]*' .env, env | cut -d= -f1, and either one filtered by a
stdin-only grep (env | cut -d= -f1 | grep -i AWS). env | grep NAME prints whole NAME=value
lines, so it stays denied. A dotenv file with a
multi-line value or a long token in a comment is still denied, since those forms
would print part of it; so is env | cut when an environment value holds a newline, or
when the command sources a file whose values are not one line each. Not vouched for
(so denied as plain reads): awk with an FS=/RS= operand, grep classes with ranges such
as [0-z] that span '=', and relative paths after a cd in the same command.

Disable: FOUNDRY_SECRET_GUARD=0
This is an accident-catcher, not a sandbox. See the plugin README.
"""
from __future__ import annotations

import fnmatch
import glob
import itertools
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "secret-guard"

_TEMPLATE_SUFFIX = re.compile(r"(?i)\.(example|sample|template|dist|defaults|schema|tmpl)$")

_SECRET_PATH = [
    (re.compile(r"(?i)(^|/)\.env(\.[\w-]+)*$"), "dotenv file"),
    (re.compile(r"(?i)(^|/)\.envrc$"), "direnv file"),
    (re.compile(r"(?i)\.(pem|key|p12|pfx|jks|keystore|ppk)$"), "private key or keystore"),
    (re.compile(r"(?i)(^|/)id_(rsa|dsa|ecdsa|ed25519)(_sk)?$"), "SSH private key"),
    (re.compile(r"(?i)(^|/)\.aws/(credentials|config)$"), "AWS credentials"),
    (re.compile(r"(?i)(^|/)\.(netrc|pgpass|npmrc|pypirc|git-credentials)$"), "stored credentials file"),
    (re.compile(r"(?i)(^|/)\.docker/config\.json$"), "docker registry credentials"),
    (re.compile(r"(?i)(^|/)\.kube/config$"), "kubernetes credentials"),
    (re.compile(r"(?i)(^|/)\.config/gh/hosts\.ya?ml$"), "GitHub CLI token file"),
    (re.compile(r"(?i)(^|/)\.config/gcloud/.*(credential|token|\.db$)"), "gcloud credential store"),
    (re.compile(r"(?i)(^|/)application_default_credentials\.json$"), "gcloud credentials"),
    (re.compile(r"(?i)(^|/)(credentials|client_secrets?|service[-_]?account[\w-]*)\.json$"), "credentials JSON"),
    (re.compile(r"(?i)(^|/)secrets?\.(json|ya?ml|toml|ini)$"), "secrets file"),
    (re.compile(r"(?i)(^|/)\.claude/\.credentials\.json$"), "Claude CLI credentials"),
]

_BROWSER_NAMES = re.compile(r"(?i)(^|/)(Login Data|Web Data|Cookies|key4\.db|logins\.json|"
                            r"cookies\.sqlite|signons\.sqlite|Local State)$")
_BROWSER_CTX = re.compile(r"(?i)(chrome|chromium|brave|edge|firefox|mozilla|arc|vivaldi|opera|"
                          r"safari|application support|\.config/)")
_KEYCHAIN = re.compile(r"(?i)(^|/)[\w.-]+\.keychain(-db)?$")

_READERS = {"cat", "less", "more", "head", "tail", "bat", "batcat", "nl", "tac", "strings",
            "xxd", "hexdump", "od", "base64", "grep", "egrep", "fgrep", "rg", "ag", "ack",
            "awk", "gawk", "sed", "cut", "sort", "uniq", "diff", "cmp", "comm", "paste",
            "column", "jq", "yq", "openssl", "pbcopy", "xclip", "dd", "sqlite3",
            "zcat", "gzcat", "bzcat", "xzcat", "zstdcat", "lzcat", "lz4cat",
            "view", "fold", "rev", "pr", "expand"}
_INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "deno", "bun", "Rscript"}
# versioned names: python3.12 -c "print(open('.env').read())" ran unchecked
_INTERP_NAME = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|node|nodejs|ruby[\d.]*|perl[\d.]*|php[\d.]*|"
                          r"deno|bun|Rscript)$")
# an interpreter fed by a heredoc or here-string: python3 - <<'PY' ... open('.env') ... PY
_HEREDOC_INTERP = re.compile(r"(?:^|[\s;&|(/])(?:python[\d.]*|pypy[\d.]*|node|nodejs|ruby[\d.]*|"
                             r"perl[\d.]*|php[\d.]*|deno|bun|Rscript)\b[^\n]*?(<<<?)-?\s*"
                             r"(?:(['\"]?)([A-Za-z_][\w-]*)\2)?")
_SECRET_VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
_INDIRECT_VAR = re.compile(r"\$\{!([A-Za-z_][A-Za-z0-9_]*)\}")  # ${!k}: the value of the var k names
# Long markers match anywhere in a name; short ones (KEY, PASS, PWD, AUTH) only as a whole
# _-separated word, so $GIT_AUTHOR_NAME, $MONKEY or $SESSION_COUNT stay readable while
# $OPENAI_API_KEY, $AUTH_HEADER and $SESSION_SECRET do not.
_SECRET_NAME = re.compile(r"(?i)(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|APIKEY|COOKIE|DSN|"
                          r"DATABASE_URL|CONNECTION_STRING|(?:MONGO\w*|REDIS|POSTGRES\w*|DB)_UR[LI]|"
                          r"(?:^|_)(?:KEY|KEYS|PASS|PWD|AUTH)(?:_|$))")
_BENIGN_VARS = {"PATH", "HOME", "PWD", "OLDPWD", "USER", "SHELL", "LANG", "TERM", "TMPDIR",
                "EDITOR", "HOSTNAME", "VIRTUAL_ENV", "NODE_ENV", "CI", "PYTHONPATH"}


_GREPS = {"grep", "egrep", "fgrep", "rg", "ag", "ack"}


def _quiet_grep(argv: list[str]) -> bool:
    # ripgrep's -L means --follow (it still prints matches); only grep's -L is quiet
    quiet = "qcl" if os.path.basename(argv[0]) in ("rg", "ag", "ack") else "qclL"
    for tok in argv[1:]:
        if tok in ("--quiet", "--silent", "--count", "--files-with-matches", "--files-without-match"):
            return True
        if tok.startswith("-") and not tok.startswith("--") and re.search(f"[{quiet}]", tok[1:]) \
                and not re.search(r"[A-BCe]", tok[1:]):
            return True
    return False


def secret_path(p: str) -> str | None:
    """Return a label if the path names a secret file, else None."""
    if not isinstance(p, str) or not p:
        return None
    p = p.strip().strip("'\"")
    if p.startswith("@"):
        p = p[1:]
    if ":" in p and not p.startswith("/"):
        p = p.split(":", 1)[1]  # git show HEAD:.env
    if "=" in p and not p.startswith(("/", ".", "~")):
        p = p.split("=", 1)[1]  # dd if=.env, --file=.env
    if p.endswith(".pub"):
        return None
    if _TEMPLATE_SUFFIX.search(p):
        return None
    if _BROWSER_NAMES.search(p) and _BROWSER_CTX.search(p):
        return "browser credential store"
    if _KEYCHAIN.search(p):
        return "keychain database"
    for pat, label in _SECRET_PATH:
        if pat.search(p):
            return label
    return None


_GLOB_CHARS = re.compile(r"[*?\[]")
_COMMON_SECRET_NAMES = (".env", ".env.local", ".env.development", ".env.production", ".env.test",
                        ".env.development.local", ".env.production.local", ".envrc")


def secret_path_glob(tok: str, cwd: str = "") -> str | None:
    """secret_path, plus: a glob like .env* or .en? is checked against what it expands to."""
    label = secret_path(tok)
    if label or not isinstance(tok, str) or not _GLOB_CHARS.search(tok):
        return label
    # a dot-glob that would match a common secret file name, whether or not it exists here
    # (shell globs only match dotfiles when the pattern itself starts with a dot)
    name = os.path.basename(tok)
    if name.startswith(".") and any(fnmatch.fnmatchcase(n, name) for n in _COMMON_SECRET_NAMES):
        return "dotenv file"
    base = cwd or os.getcwd()
    try:
        pattern = os.path.expanduser(tok)
        if not os.path.isabs(pattern):
            pattern = os.path.join(base, pattern)
        for hit in itertools.islice(glob.iglob(pattern), 200):
            label = secret_path(hit)
            if label:
                return label
    except Exception:
        return None
    return None


_DUMP_ENV_CODE = re.compile(
    r"\b(?:print|pprint|console\.(?:log|dir|info)|JSON\.stringify|puts|p|dump)\s*\(?\s*"
    r"(?:dict\s*\(\s*|list\s*\(\s*)?(?:process\.env|os\.environ|ENV|Deno\.env\.toObject\(\))"
    r"\s*(?:\.items\(\)\s*)?\)?\s*[),;]?\s*(?:$|[);\n])")
_ENV_NAME_CODE = re.compile(
    r"(?:process\.env\.|os\.environ\[\s*['\"]|os\.getenv\(\s*['\"]|os\.environ\.get\(\s*['\"]|"
    r"ENV\[\s*['\"])([A-Za-z_][A-Za-z0-9_]*)")
_PRINT_CODE = re.compile(r"\b(?:print|console\.(?:log|error|info|dir)|puts|echo|pprint)\b")


def _inline_env_leak(code: str) -> str | None:
    if not isinstance(code, str):
        return None
    if _DUMP_ENV_CODE.search(code):
        return "prints the whole environment from inline code"
    if _PRINT_CODE.search(code):
        for name in _ENV_NAME_CODE.findall(code):
            if name not in _BENIGN_VARS and _SECRET_NAME.search(name):
                return f"prints the secret variable {name} from inline code"
    return None


def _inline_secret_ref(code: str) -> str | None:
    for tok in re.findall(r"[\w./~@:-]+", code or ""):
        label = secret_path(tok)
        if label:
            return label
    return None


def _is_interpreter(head: str) -> bool:
    return head in _INTERPRETERS or bool(_INTERP_NAME.match(head))


def _heredoc_code(cmd: str) -> list[str]:
    """The code an interpreter reads from a heredoc or here-string in cmd."""
    out = []
    for m in _HEREDOC_INTERP.finditer(cmd or ""):
        if m.group(1) == "<<<":
            out.append(cmd[m.end(1):].split("\n", 1)[0])
            continue
        rest = cmd[m.end():]
        body = rest.split("\n", 1)[1] if "\n" in rest else ""
        word = m.group(3)
        if word:  # cut at the terminator line, so later commands are not read as code
            end = re.search(r"^\s*" + re.escape(word) + r"\s*$", body, re.MULTILINE)
            body = body[:end.start()] if end else body
        out.append(body)
    return out


def _pw_manager(argv: list[str]) -> str | None:
    head = os.path.basename(argv[0])
    a = argv[1:]
    sub = a[0] if a else ""
    if head == "bw" and sub in ("get", "list", "export", "unlock", "serve", "send"):
        return "Bitwarden CLI"
    if head == "op" and (sub in ("read", "inject") or
                         (sub in ("item", "document") and "get" in a)):
        return "1Password CLI"
    if head == "lpass" and sub in ("show", "export"):
        return "LastPass CLI"
    if head == "secret-tool" and sub in ("lookup", "search"):
        return "libsecret store"
    if head in ("pass", "gopass") and (sub in ("show", "cat") or (len(a) == 1 and not sub.startswith("-") and sub not in ("ls", "list", "init", "help", "version"))):
        return f"{head} password store"
    if head == "keepassxc-cli" and sub in ("show", "export", "clip"):
        return "KeePassXC CLI"
    if head == "security":
        if sub in ("dump-keychain", "export"):
            return "macOS keychain dump"
        if sub in ("find-generic-password", "find-internet-password") and any(
                t in ("-w", "-g") or re.match(r"^-[a-z]*[wg][a-z]*$", t) for t in a[1:]):
            return "macOS keychain secret"
    return None


def _token_printer(argv: list[str]) -> str | None:
    head = os.path.basename(argv[0])
    j = " ".join(argv[1:4])
    if head == "gh" and re.match(r"^auth\s+(token|status\s+.*(--show-token|-t))", " ".join(argv[1:])):
        return "GitHub CLI token"
    if head == "gcloud" and re.search(r"auth\s+(application-default\s+)?print-(access|identity)-token", " ".join(argv[1:])):
        return "gcloud access token"
    if head == "aws" and (j.startswith("configure get") or j.startswith("configure export-credentials")
                          or j.startswith("sts get-session-token")):
        return "AWS credentials"
    if head == "az" and j.startswith("account get-access-token"):
        return "Azure access token"
    if head == "kubectl" and "config" in argv and "view" in argv and "--raw" in argv:
        return "kubeconfig with credentials"
    if head == "heroku" and argv[1:2] == ["auth:token"]:
        return "Heroku token"
    if head == "heroku" and argv[1:2] in (["config"], ["config:get"]):
        return "Heroku config vars"
    if (head == "docker" and argv[1:3] == ["compose", "config"]) or \
            (head == "docker-compose" and argv[1:2] == ["config"]):
        if not any(t in ("--services", "--volumes", "--profiles", "--images", "-q", "--quiet",
                         "--no-interpolate") for t in argv):
            return "docker compose config (it prints every interpolated env value)"
    return None


def _env_dump(argv: list[str]) -> str | None:
    head = os.path.basename(argv[0])
    rest = argv[1:]
    if head in ("env", "printenv", "set") and not rest:
        return "dumps every environment variable"
    if head == "printenv" and rest:
        names = [t for t in rest if not t.startswith("-")]
        if any(_SECRET_NAME.search(n) and n not in _BENIGN_VARS for n in names):
            return "prints a secret environment variable"
    if head == "export" and (not rest or rest == ["-p"]):
        return "dumps exported environment variables"
    if head in ("declare", "typeset") and rest and re.match(r"^-[a-zA-Z]*[px]", rest[0]) and len(rest) == 1:
        return "dumps shell variables"
    return None


def _sources_env(argvs) -> bool:
    for argv in argvs:
        if os.path.basename(argv[0]) in ("source", ".") and len(argv) > 1 and secret_path(argv[1]) == "dotenv file":
            return True
    return False


_GIT_CONTENT_SAFE = {"--stat", "--shortstat", "--numstat", "--name-only", "--name-status",
                     "--quiet", "--exit-code", "--summary", "--dirstat"}


def _git_prints_secret(argv: list[str]) -> str | None:
    """git diff/show/blame/log -p naming a secret file prints its tracked contents."""
    sub = argv[1] if len(argv) > 1 else ""
    if sub not in ("diff", "show", "blame", "log", "cat-file"):
        return None
    rest = argv[2:]
    if sub == "log" and not any(t in ("-p", "-u", "--patch") or re.match(r"^-[a-zA-Z]*p", t)
                                for t in rest):
        return None  # git log -- .env lists commits only: a legit "was it ever committed?" check
    if sub != "cat-file" and any(t.split("=")[0] in _GIT_CONTENT_SAFE for t in rest):
        return None
    for tok in rest:
        if tok.startswith("-"):
            continue
        label = secret_path(tok)
        if label:
            return f"prints a {label} from git history"
    return None


def _recursive_grep_hits_env(argv: list[str], cwd: str) -> str | None:
    """grep -r KEY . walks into .env and prints its lines; rg skips it (gitignored, hidden)."""
    if os.path.basename(argv[0]) not in ("grep", "egrep", "fgrep"):
        return None
    flags = "".join(t[1:] for t in argv[1:] if t.startswith("-") and not t.startswith("--"))
    longs = [t for t in argv[1:] if t.startswith("--")]
    if not ("r" in flags or "R" in flags or any(t.startswith(("--recursive", "--dereference-recursive"))
                                                 for t in longs)):
        return None
    args = argv[1:]
    if any(t.startswith("--exclude") and ("env" in t or (i + 1 < len(args) and "env" in args[i + 1]))
           for i, t in enumerate(args)):
        return None
    pos = [t for i, t in enumerate(args) if not t.startswith("-")
           and not (i and args[i - 1] in ("--exclude", "--exclude-dir", "--include"))]
    if "e" in flags or any(t.startswith(("--regexp", "--file")) for t in longs):
        pattern, dirs = " ".join(argv), pos
    else:
        pattern, dirs = (pos[0] if pos else ""), pos[1:]
    if not _SECRET_NAME.search(pattern) and not re.search(r"(?i)(_URL|sk-|ghp_|xox[bp]-)", pattern):
        return None
    base = cwd or os.getcwd()
    for d in dirs or ["."]:
        d = os.path.expanduser(d)
        d = d if os.path.isabs(d) else os.path.join(base, d)
        try:
            if os.path.isdir(d) and any(secret_path(h) == "dotenv file"
                                        for h in itertools.islice(glob.iglob(os.path.join(d, ".env*")), 50)):
                return ("searches a directory that holds a .env file for a secret-looking name, so "
                        "it would print the .env values. Add --exclude='.env*' or use rg, which "
                        "skips gitignored files")
        except Exception:
            return None
    return None


# Names-only forms: these print the part of each line before the first "=", so on a
# file of single-line NAME=value lines they print key names and nothing else.
_NAMES_FOLLOW = {"sort", "uniq", "wc", "head", "tail"}
_SED_NAMES = re.compile(r"^s(.)=\.\*\$?\1\1(p?)$")
_AWK_NAMES = re.compile(r"^\{\s*print\s+\$1\s*;?\s*\}$")
_GREP_NAMES = re.compile(r"^\^((?:\[[A-Za-z0-9_-]+\]){1,2})[*+]=?$")
# Inside a bracket only same-kind ranges (A-Z, a-z, 0-9) and name characters: [0-z] or [--z]
# span '=' and the punctuation of a value, so grep -o '^[0-z]*' printed NAME=value whole.
_GREP_CLASS = re.compile(r"^(?:[A-Z]-[A-Z]|[a-z]-[a-z]|[0-9]-[0-9]|[A-Za-z0-9_])+-?$")
_AWK_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ASSIGN_LINE = re.compile(r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.-]*\s*=(.*)$")


def _stdin_filter(argv: list[str]) -> bool:
    """A grep that reads only stdin (one pattern, no file operand, no -f pattern file), so
    after a names-only stage it can print nothing but names."""
    if os.path.basename(argv[0]) not in _GREPS:
        return False
    pos, by_e, i, a = 0, False, 0, argv[1:]
    while i < len(a):
        t = a[i]
        if t in ("-e", "--regexp"):
            by_e, i = True, i + 2
            continue
        if t.startswith(("--file", "--recursive", "--dereference-recursive", "--include", "--exclude")):
            return False
        if t.startswith("--regexp="):
            by_e = True
        elif t.startswith("-") and not t.startswith("--"):
            if re.search(r"[frRd]", t[1:]):
                return False  # a pattern file, recursion or a directory action reads files
            if t.endswith("e"):  # -e PATTERN, also bundled as -ie
                by_e, i = True, i + 2
                continue
        elif not t.startswith("-"):
            pos += 1
        i += 1
    return pos == 0 if by_e else pos <= 1


def _names_only_files(argv: list[str]) -> list[str] | None:
    """The files a names-only command reads, or None when argv is not one of those forms."""
    head, a = os.path.basename(argv[0]), argv[1:]
    files: list[str] = []
    if head == "cut":
        delim = field = None
        i = 0
        while i < len(a):
            t = a[i]
            if t in ("-d", "-f") and i + 1 < len(a):
                delim, field = (a[i + 1], field) if t == "-d" else (delim, a[i + 1])
                i += 2
                continue
            if t.startswith(("-d", "--delimiter=")):
                delim = t.split("=", 1)[1] if t.startswith("--") else t[2:]
            elif t.startswith(("-f", "--fields=")):
                field = t.split("=", 1)[1] if t.startswith("--") else t[2:]
            elif t in ("-s", "--only-delimited"):
                pass
            elif t.startswith("-"):
                return None
            else:
                files.append(t)
            i += 1
        return files if delim == "=" and field == "1" else None
    if head == "sed":
        quiet, script, i = False, None, 0
        while i < len(a):
            t = a[i]
            if t in ("-n", "--quiet", "--silent"):
                quiet = True
            elif t in ("-E", "-r", "--regexp-extended"):
                pass
            elif t == "-e" and i + 1 < len(a) and script is None:
                script = a[i + 1]
                i += 1
            elif t.startswith("-"):
                return None
            elif script is None:
                script = t
            else:
                files.append(t)
            i += 1
        m = _SED_NAMES.match(script or "")
        return files if m and (m.group(2) == "p" or not quiet) else None
    if head in ("awk", "gawk"):
        sep, prog, i = None, None, 0
        while i < len(a):
            t = a[i]
            if t == "-F" and i + 1 < len(a):
                sep = a[i + 1]
                i += 1
            elif t.startswith("-F"):
                sep = t[2:]
            elif t.startswith("-"):
                return None
            elif prog is None:
                prog = t
            elif _AWK_ASSIGN.match(t):
                return None  # an operand FS=x (or RS=, OFS=) resets the split: $1 is the whole line
            else:
                files.append(t)
            i += 1
        return files if sep == "=" and _AWK_NAMES.match(prog or "") else None
    if head in ("grep", "egrep"):
        flags, pat = "", None
        for t in a:
            if t.startswith("-") and not t.startswith("--"):
                flags += t[1:]
            elif t.startswith("-"):
                return None
            elif pat is None:
                pat = t
            else:
                files.append(t)
        m = _GREP_NAMES.match(pat or "")
        ok = "o" in flags and set(flags) <= set("oEh") and m and all(
            _GREP_CLASS.match(cls) for cls in re.findall(r"\[([^\]]+)\]", m.group(1)))
        return files if ok else None
    return None


def _env_file_is_names_safe(path: str) -> bool:
    """Every line is blank, a comment, or a one-line NAME=value, so names-only prints no value."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(1_000_000)
    except OSError:
        return True  # missing or unreadable: the command prints nothing from it
    for line in text.splitlines():
        st = line.strip()
        if not st:
            continue
        if st.startswith("#"):
            if re.search(r"[A-Za-z0-9_+/-]{20,}", st.split("=", 1)[0]):
                return False  # a long token in a comment would be printed whole
            continue
        m = _ASSIGN_LINE.match(line)
        if not m:
            return False
        value = m.group(1).strip()
        if value[:1] in ("'", '"') and value.find(value[0], 1) == -1:
            return False  # a quoted value that runs onto the next lines
    return True


# A cd in the same command moves the shell: "cd sub && cut -d= -f1 .env" reads sub/.env while
# the hook would vouch for ./.env. Relative paths are then not checked, so not vouched for.
_CHDIR = re.compile(r"(?:^|[\s;&|(`])(?:cd|pushd|popd)(?=$|[\s;&|)])|--chdir\b|\benv\s+(?:-\S+\s+)*-C\b")


def _sourced_names_safe(pipelines, cwd: str, moved: bool) -> bool:
    """Every file the command sources is a dotenv whose values are one line each.

    "source .env && env | cut -d= -f1" lists the sourced values too, so a PEM key held in
    the sourced file printed its body lines (cut prints a line with no '=' whole)."""
    for stages in pipelines:
        for argv in stages:
            if os.path.basename(argv[0]) not in ("source", ".") or len(argv) < 2:
                continue
            tok = os.path.expanduser(argv[1])
            if not os.path.isabs(tok):
                if moved:
                    return False
                tok = os.path.join(cwd or os.getcwd(), tok)
            if secret_path(tok) not in ("dotenv file", "direnv file") or not _env_file_is_names_safe(tok):
                return False
    return True


def _names_only_ok(pipelines, cwd: str, cmd: str = "", varmap: dict | None = None):
    """ids of argvs that only list key names, plus a reason when a names-only form is unsafe."""
    ok: set[int] = set()
    moved = bool(_CHDIR.search(cmd or ""))
    for stages in pipelines:
        for i, argv in enumerate(stages):
            if not all(os.path.basename(x[0]) in _NAMES_FOLLOW or _stdin_filter(x)
                       for x in stages[i + 1:]):
                continue
            files = _names_only_files(argv)
            if files is None:
                continue
            expanded: list[str] = []
            for tok in files:
                cands, dyn = _expand(tok, varmap or {})
                if dyn:
                    break  # a name read at run time: not vouched for
                expanded.extend(cands)
            else:
                files = expanded
            if len(files) != len(expanded):
                continue
            for tok in files:
                label = secret_path_glob(tok, cwd)
                if label is None:
                    continue
                if label not in ("dotenv file", "direnv file"):
                    break
                path = os.path.expanduser(tok)
                if not os.path.isabs(path) and moved:
                    break  # the file read is not the one we can check
                path = path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)
                for hit in (glob.glob(path) if _GLOB_CHARS.search(tok) else [path]):
                    if not _env_file_is_names_safe(hit):
                        return ok, (f"would print part of a value: {tok} has lines that are not "
                                    "NAME=value (a multi-line value or a long token in a comment)")
            else:
                ok.add(id(argv))
                # env | cut -d= -f1 prints names only, unless some value spans several lines
                if i == 1 and not files and stages[0] in (["env"], ["printenv"]) \
                        and not any("\n" in v for v in os.environ.values()) \
                        and _sourced_names_safe(pipelines, cwd, moved):
                    ok.add(id(stages[0]))
    return ok, None


# ---- simple indirection: variables, loops, $(...), find -exec, xargs, copies ----------------

_DYNAMIC = "dynamic"  # a variable whose value is only known at run time (read, $(...))
_VAR_REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
_FOR = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.*?)\s*(?:;|\n)\s*do\b", re.S)
# A quote may open the binding: inside bash -c 'f=.env; cat "$f"' it follows the quote.
_SET_VAR = re.compile(r"(?:^|[\s;&|(\"'])(?:export\s+|local\s+|readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)="
                      r"(\$\([^)]*\)|`[^`]*`|\"[^\"]*\"|'[^']*'|[^\s;&|)\"']*)")
_READ_VAR = re.compile(r"(?:^|[\s;&|(\"'])read\s+(?:-[a-zA-Z]+\s+)*([A-Za-z_][A-Za-z0-9_]*)")
_COPIERS = {"cp", "mv", "ln", "install", "rsync", "ditto"}
_FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
_FIND_NAMES = ("-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename")
_SECRET_SAMPLES = _COMMON_SECRET_NAMES + ("id_rsa", "id_ed25519", "credentials.json", "secrets.json",
                                          "secrets.yaml", "server.pem", "server.key", "key.pem")


# ---- compress and archive round trips (E2-3b) ---------------------------------------------
# A compressor or archiver reads a secret without printing it, but what it writes IS the
# secret: to the screen with -c, into a pipe, or into an archive a later command reads back.
_COMPRESSORS = {"gzip", "pigz", "bzip2", "pbzip2", "xz", "lzma", "zstd", "lz4", "compress"}
_UNCOMPRESSORS = {"gunzip", "bunzip2", "unxz", "unlzma", "unzstd", "uncompress"}
_OUT_REDIRS = (">", ">>", "1>", "1>>", "&>", ">|")


def _split_redirect(argv: list[str]) -> tuple[list[str], list[str]]:
    """(argv without its redirections, the files stdout is written to with > or >>)."""
    out, targets, i = [], [], 0
    while i < len(argv):
        t = argv[i]
        if t in _OUT_REDIRS or t in ("2>", "2>>"):
            if t in _OUT_REDIRS and i + 1 < len(argv):
                targets.append(argv[i + 1])
            i += 2
            continue
        m = re.match(r"^(?:1?>>?|&>|>\|)([^>].*)$", t)
        if m:
            targets.append(m.group(1))
            i += 1
            continue
        out.append(t)
        i += 1
    return out, targets


def _short_flags(argv: list[str]) -> str:
    return "".join(t[1:] for t in argv[1:] if t.startswith("-") and not t.startswith("--") and len(t) > 1)


def _has_long(argv: list[str], *names: str) -> bool:
    return any(t == n or t.startswith(n + "=") for t in argv[1:] for n in names)


def _tar_parts(argv: list[str]) -> tuple[str | None, str | None, list[str], bool]:
    """(mode c/x/t or None, archive file, member operands, prints members to stdout)."""
    a, flags, archive, members, i = argv[1:], "", None, [], 0
    if a and not a[0].startswith("-"):  # old style: tar czf e.tgz files / tar xzOf e.tgz
        flags = a[0]
        if "f" in a[0] and len(a) > 1:
            archive, i = a[1], 2
        else:
            i = 1
    while i < len(a):
        t = a[i]
        if t in ("-f", "--file"):
            archive = a[i + 1] if i + 1 < len(a) else None
            i += 2
            continue
        if t.startswith("--file="):
            archive = t.split("=", 1)[1]
        elif t in ("-O", "--to-stdout"):
            flags += "O"
        elif t in ("--create",):
            flags += "c"
        elif t in ("--extract", "--get"):
            flags += "x"
        elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
            flags += t[1:]
            if t.endswith("f") and i + 1 < len(a):
                archive = a[i + 1]
                i += 2
                continue
        elif not t.startswith("-"):
            members.append(t)
        i += 1
    mode = "c" if "c" in flags else "x" if "x" in flags else "t" if "t" in flags else None
    return mode, archive, members, "O" in flags


def _abs(tok: str, cwd: str) -> str:
    p = os.path.expanduser(tok)
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(cwd or os.getcwd(), p))


def _archive_step(argv: list[str], cwd: str, varmap: dict, copies: dict, derived: dict):
    """Check one compressor/archiver argv. Returns (reason, category) to deny, else None;
    records archives and redirect targets made from a secret in copies and derived."""
    head = os.path.basename(argv[0])
    args, targets = _split_redirect(argv)

    def secret_of(tok):
        for cand in _expand(tok, varmap)[0]:
            label = secret_path_glob(cand, cwd)
            if label:
                return label, f"{tok}"
            if os.path.normpath(cand) in copies:
                return copies[os.path.normpath(cand)], f"{tok}, a copy of it"
            if _abs(cand, cwd) in derived:
                return derived[_abs(cand, cwd)], f"{tok}, a copy of it made earlier"
        return None

    def record(dest, label):
        copies[os.path.normpath(dest)] = label
        derived[_abs(dest, cwd)] = label

    if head in _COMPRESSORS or head in _UNCOMPRESSORS:
        sf = _short_flags(args)
        to_stdout = "c" in sf or _has_long(args, "--stdout", "--to-stdout")
        unpack = head in _UNCOMPRESSORS or "d" in sf or _has_long(args, "--decompress", "--uncompress")
        files = [t for t in args[1:] if not t.startswith("-")]
        for tok in files:
            hit = secret_of(tok)
            if not hit:
                continue
            label, shown = hit
            if to_stdout and not targets:
                verb = "decompresses" if unpack else "compresses"
                return (f"{verb} a {label} ({shown}) to the screen or a pipe, which prints it",
                        _category(label))
            for dest in targets:
                record(dest, label)
            if not to_stdout and not unpack:  # gzip .env -> .env.gz, still named like a secret
                record(tok + {"bzip2": ".bz2", "pbzip2": ".bz2", "xz": ".xz", "lzma": ".lzma",
                              "zstd": ".zst", "lz4": ".lz4", "compress": ".Z"}.get(head, ".gz"), label)
        return None
    if head == "tar":
        mode, archive, members, to_stdout = _tar_parts(args)
        if mode == "c":
            for tok in members:
                hit = secret_of(tok)
                if not hit:
                    continue
                if archive in (None, "-") and not targets:
                    return (f"archives a {hit[0]} ({hit[1]}) to the screen or a pipe, which prints it",
                            _category(hit[0]))
                for dest in ([archive] if archive not in (None, "-") else []) + targets:
                    record(dest, hit[0])
        elif mode == "x" and to_stdout and archive not in (None, "-"):
            hit = secret_of(archive)
            if hit:
                return f"prints a copy of a {hit[0]} ({hit[1]}, an archive of it)", _category(hit[0])
        return None
    if head in ("zip", "7z", "7za"):
        pos = [t for t in args[1:] if not t.startswith("-")]
        if head != "zip" and pos[:1] in (["a"], ["u"]):
            pos = pos[1:]
        if len(pos) >= 2:
            hit = next((h for h in (secret_of(t) for t in pos[1:]) if h), None)
            if hit:
                if pos[0] == "-" and not targets:
                    return (f"archives a {hit[0]} ({hit[1]}) to the screen or a pipe, which prints it",
                            _category(hit[0]))
                for dest in ([pos[0]] if pos[0] != "-" else []) + targets:
                    record(dest, hit[0])
        return None
    if head == "unzip" and re.search(r"[pc]", _short_flags(args)):
        pos = [t for t in args[1:] if not t.startswith("-")]
        if pos:
            hit = secret_of(pos[0])
            if hit:
                return f"prints a copy of a {hit[0]} ({hit[1]}, an archive of it)", _category(hit[0])
    return None


def _bind_vars(cmd: str) -> dict:
    """Variables bound inside this command: name -> list of words, or _DYNAMIC."""
    out: dict = {}

    def add(name, vals):
        if vals == _DYNAMIC or out.get(name) == _DYNAMIC:
            out[name] = _DYNAMIC
        else:
            out.setdefault(name, []).extend(vals)

    for m in _FOR.finditer(cmd):
        words = m.group(2)
        add(m.group(1), _DYNAMIC if ("$(" in words or "`" in words) else c.tokenize(words))
    for m in _SET_VAR.finditer(cmd):
        val = m.group(2)
        if "$(" in val or "`" in val:
            add(m.group(1), _DYNAMIC)
        else:
            add(m.group(1), [val.strip("'\"")])
    for m in _READ_VAR.finditer(cmd):
        add(m.group(1), _DYNAMIC)
    return out


def _expand(tok: str, varmap: dict) -> tuple[list[str], bool]:
    """tok with each bound $VAR replaced by its words; True when a bound var is dynamic."""
    outs, dyn = [tok], False
    for name in dict.fromkeys(_VAR_REF.findall(tok or "")):
        vals = varmap.get(name)
        if vals is None:
            continue  # set outside this command: not ours to guess
        if vals == _DYNAMIC:
            dyn = True
            continue
        ref = re.compile(r"\$(?:\{" + name + r"\}|" + name + r"(?![A-Za-z0-9_]))")
        outs = [ref.sub(lambda _m, v=v: v, o) for o in outs for v in vals][:64]
    return outs, dyn


def _lists_dotfiles_of_secret_dir(text: str, cwd: str) -> bool:
    """ls -a / -A on a folder that holds a .env: its output names the .env, as find . does."""
    for argv in c.all_argvs(text):
        if os.path.basename(argv[0]) != "ls":
            continue
        flags = "".join(t[1:] for t in argv[1:] if t.startswith("-") and not t.startswith("--"))
        if not (set(flags) & {"a", "A"} or "--all" in argv or "--almost-all" in argv):
            continue
        for d in [t for t in argv[1:] if not t.startswith("-")] or ["."]:
            d = os.path.expanduser(d)
            d = d if os.path.isabs(d) else os.path.join(cwd or os.getcwd(), d)
            try:
                if os.path.isdir(d) and any(secret_path(h) for h in
                                            itertools.islice(glob.iglob(os.path.join(d, ".env*")), 50)):
                    return True
            except Exception:
                return False
    return False


def _mentions_secret(text: str, cwd: str) -> str | None:
    """A label when text names a secret file (or the bare word env, as in ls -a | grep env, or
    lists the dotfiles of a folder holding .env, as in ls -A | xargs cat)."""
    text = re.sub(r"(?:^|[;&|\s])(?:source|\.)\s+\S+", " ", text or "")  # loading .env is fine
    for tok in re.findall(r"[\w./~@:*?\[\]-]+", text):
        label = secret_path_glob(tok, cwd)
        if label:
            return label
    if re.search(r"(?i)(?<![\w-])env(?![\w-])", text):
        return "dotenv file"
    if _lists_dotfiles_of_secret_dir(text, cwd):
        return "dotenv file"
    return None


def _find_reads_secret(argv: list[str], cwd: str) -> str | None:
    """find ... -exec <reader> {} on secret names, or on a folder holding .env with no name filter."""
    k = next((i for i, t in enumerate(argv) if t in _FIND_EXEC), None)
    if k is None or k + 1 >= len(argv) or os.path.basename(argv[k + 1]) not in _READERS:
        return None
    pats, negated = [], False
    for i, t in enumerate(argv[1:k], start=1):
        if t in _FIND_NAMES and i + 1 < k:
            if argv[i - 1] in ("!", "-not"):
                negated = True
                continue
            pats.append((argv[i + 1], t.startswith("-i")))
    for pat, nocase in pats:
        if secret_path(pat):
            return secret_path(pat)
        p = pat.lower() if nocase else pat
        for n in _SECRET_SAMPLES:
            if fnmatch.fnmatchcase(n, p) or fnmatch.fnmatchcase("./" + n, p):
                return secret_path(n) or "dotenv file"
    if pats and not negated:
        return None
    roots = [t for t in argv[1:k] if not t.startswith(("-", "(", "!", ")"))][:1] or ["."]
    for d in roots:
        d = os.path.expanduser(d)
        d = d if os.path.isabs(d) else os.path.join(cwd or os.getcwd(), d)
        try:
            if os.path.isdir(d) and any(secret_path(h) for h in
                                        itertools.islice(glob.iglob(os.path.join(d, ".env*")), 50)):
                return "dotenv file"
        except Exception:
            return None
    return None


def _indirect(cmd: str, cwd: str) -> tuple[str, str] | None:
    """(reason, label) for reads through $(...) or xargs fed by a command naming a secret."""
    for m in c._SUBST.finditer(cmd):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        if inner is None:
            continue  # <(...) feeds content, not file names; its command is checked on its own
        seg = re.split(r"[;&|\n]", cmd[:m.start()])[-1].split()
        while seg and seg[0] in ("(", "{", "!", "do", "then", "else", "if", "sudo"):
            seg = seg[1:]
        if seg and os.path.basename(seg[0].lstrip("(")) in _READERS:
            label = _mentions_secret(inner, cwd)
            if label:
                return (f"reads the files that $({inner.strip()}) names, and that command "
                        f"names a {label}"), label
    for pipeline in c.split_top_level(cmd):
        for j, stage in enumerate(pipeline[1:], start=1):
            toks = c.strip_grouping(c.tokenize(stage))
            if not toks or os.path.basename(toks[0]) != "xargs":
                continue
            inner = c.strip_prefixes(toks)
            if inner and os.path.basename(inner[0]) in _READERS:
                label = _mentions_secret(" ".join(pipeline[:j]), cwd)
                if label:
                    return (f"runs xargs {inner[0]} on file names from '{' | '.join(pipeline[:j])}', "
                            f"which names a {label}"), label
    return None


def _names_only_tail(stages, start: int) -> bool:
    """stages[start:] are stdin-only greps, then one names-only stage reading stdin (cut -d= -f1,
    sed 's/=.*//', awk -F= '{print $1}', grep -o '^NAME'), then only sort/uniq/wc/head/tail or
    stdin greps: whatever the greps keep, the pipe prints names only (E2-3a:
    env | grep -i '^AWS' | cut -d= -f1)."""
    k = start
    while k < len(stages) and _stdin_filter(stages[k]):
        k += 1
    if k == start:
        return False  # no grep in between: plain env | cut goes through _names_only_ok
    if k >= len(stages) or _names_only_files(stages[k]) != []:
        return False
    if not all(os.path.basename(x[0]) in _NAMES_FOLLOW or _stdin_filter(x) for x in stages[k + 1:]):
        return False
    # a multi-line value prints its continuation lines whole through cut -f1
    return not any("\n" in v for v in os.environ.values())


def _env_grep(pipelines, names_ok, cwd: str = "", cmd: str = "") -> str | None:
    """env | grep NAME prints the whole NAME=value line of every match."""
    for stages in pipelines:
        if len(stages) < 2 or id(stages[0]) in names_ok or not _env_dump(stages[0]):
            continue
        nxt = stages[1]
        if os.path.basename(nxt[0]) in _GREPS and _quiet_grep(nxt) and len(stages) == 2:
            names_ok.add(id(stages[0]))  # env | grep -q NAME / -c prints no value
            continue
        if stages[0] in (["env"], ["printenv"]) and _names_only_tail(stages, 1) \
                and _sourced_names_safe(pipelines, cwd, bool(_CHDIR.search(cmd or ""))):
            names_ok.add(id(stages[0]))  # env | grep AWS | cut -d= -f1 prints names only
            continue
        if os.path.basename(nxt[0]) in _GREPS and not _quiet_grep(nxt):
            pat = next((t for t in nxt[1:] if not t.startswith("-")), "")
            names = "env | cut -d= -f1 | " + " ".join(shlex.quote(t) for t in nxt)
            return (f"pipes the environment into {os.path.basename(nxt[0])}, which prints the whole "
                    f"NAME=value line of every variable matching '{pat}', values included. To list "
                    f"the matching names only: {names}")
    return None


_CATEGORY = {"dotenv file": "dotenv", "direnv file": "dotenv", "private key or keystore": "key",
             "SSH private key": "key", "browser credential store": "browser",
             "keychain database": "browser"}


def _category(label: str | None) -> str:
    return _CATEGORY.get(label or "", "credfile" if label else "envdump")


def evaluate_bash(cmd: str, cwd: str = "") -> str | None:
    return evaluate_bash_ex(cmd, cwd)[0]


def evaluate_bash_ex(cmd: str, cwd: str = "", derived: dict | None = None) -> tuple[str | None, str]:
    """(reason, category) for a command, or (None, "") to allow. The category picks the advice.
    derived maps absolute paths of copies and archives of a secret made earlier in the session
    to its label; this command's new ones are added to it (the caller persists them)."""
    if not isinstance(cmd, str) or not cmd.strip():
        return None, ""
    derived = {} if derived is None else derived
    pipelines = c.command_stages(cmd)
    argvs = [a for p in pipelines for a in p]
    varmap = _bind_vars(cmd)
    names_ok, names_why = _names_only_ok(pipelines, cwd, cmd, varmap)
    if names_why:
        return names_why, "dotenv"
    why = _env_grep(pipelines, names_ok, cwd, cmd)
    if why:
        return why, "envdump"
    sourced = _sources_env(argvs)
    # input redirection like  cat < .env  or  $(< .env)
    for m in re.finditer(r"<\s*([^\s<>|;&()]+)", cmd):
        if not m.group(0).startswith("<<"):
            label = secret_path(m.group(1))
            if label and not cmd[max(0, m.start() - 1):m.start()] == "<":
                return f"reads a {label} through input redirection", _category(label)
    hit = _indirect(cmd, cwd)
    if hit:
        return hit[0], _category(hit[1])
    copies: dict[str, str] = {}  # normalized destination of a cp/mv of a secret -> its label
    for argv in argvs:
        if id(argv) in names_ok:
            continue
        head = os.path.basename(argv[0])
        why = _pw_manager(argv) or _token_printer(argv)
        if why:
            return f"would print secrets from the {why}", "cli"
        why = _env_dump(argv)
        if why:
            return why, "envdump"
        if head == "printenv":
            # printenv $(env | cut -d= -f1 | grep AWS), or for k in ...; do printenv "$k": the
            # names-only listing picks the names and printenv prints their values
            for tok in argv[1:]:
                if tok.startswith("-"):
                    continue
                cands, dyn = _expand(tok, varmap)
                if dyn or "$(" in tok or "`" in tok:
                    return (f"prints environment variables whose names are chosen at run time "
                            f"({tok})"), "envdump"
                if any(n != tok and _SECRET_NAME.search(n) and n not in _BENIGN_VARS for n in cands):
                    return f"prints a secret environment variable ({tok})", "envdump"
        # browser stores and keychain files, any command
        for tok in argv[1:]:
            label = secret_path(tok)
            if label in ("browser credential store", "keychain database"):
                return f"touches a {label}", "browser"
        if head in _COPIERS:
            pos = [t for t in argv[1:] if not t.startswith("-")]
            for src in pos[:-1]:
                label = next((x for x in (secret_path_glob(e, cwd) for e in _expand(src, varmap)[0]) if x), None)
                if label:
                    dest = pos[-1]
                    copies[os.path.normpath(dest)] = label
                    copies[os.path.normpath(os.path.join(dest, os.path.basename(src)))] = label
                    derived[_abs(dest, cwd)] = label
                    derived[_abs(os.path.join(dest, os.path.basename(src)), cwd)] = label
        if head == "find":
            label = _find_reads_secret(argv, cwd)
            if label:
                return f"runs find -exec on a {label}, which prints it", _category(label)
        if head in _COMPRESSORS or head in _UNCOMPRESSORS or head in ("tar", "zip", "7z", "7za", "unzip"):
            hit = _archive_step(argv, cwd, varmap, copies, derived)
            if hit:
                return hit
        if head in _READERS:
            if head in _GREPS and _quiet_grep(argv):
                continue  # grep -q / -c / -l prints no secret values
            skip_next = False
            for tok in argv[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if tok in ("--exclude", "--exclude-dir"):
                    skip_next = True  # its value names a file NOT to read
                    continue
                if tok.startswith(("--exclude=", "--exclude-dir=")):
                    continue
                cands, dyn = _expand(tok, varmap)
                for cand in cands:
                    label = secret_path_glob(cand, cwd)
                    if label:
                        shown = tok if cand == tok else f"{tok}, which is {cand}"
                        return f"prints a {label} ({shown})", _category(label)
                    if os.path.normpath(cand) in copies:
                        label = copies[os.path.normpath(cand)]
                        return f"prints a copy of a {label} ({tok})", _category(label)
                    if _abs(cand, cwd) in derived:
                        label = derived[_abs(cand, cwd)]
                        return (f"prints a copy of a {label} ({tok}, made earlier in this session)",
                                _category(label))
                label = _mentions_secret(cmd, cwd) if dyn else None
                if label:
                    return (f"reads {tok}, a file name chosen at run time, in a command that "
                            f"names a {label}"), _category(label)
            why = _recursive_grep_hits_env(argv, cwd)
            if why:
                return why, "dotenv"
        if head in ("curl", "wget", "http", "https"):
            for tok in argv[1:]:
                if tok.startswith("@") or "=@" in tok:
                    label = secret_path(tok.split("@", 1)[1])
                    if label:
                        return f"uploads a {label}", _category(label)
        if head == "git" and len(argv) > 2:
            why = _git_prints_secret(argv)
            if why:
                return why, _category(next((secret_path(t) for t in argv[2:] if secret_path(t)), None))
        if _is_interpreter(head):
            for code in _heredoc_code(cmd):
                label = _inline_secret_ref(code)
                if label:
                    return f"opens a {label} from code fed to {head} on stdin", _category(label)
                why = _inline_env_leak(code)
                if why:
                    return why.replace("inline code", f"code fed to {head} on stdin"), "envdump"
            for j, tok in enumerate(argv[1:-1], start=1):
                if tok in ("-c", "-e", "-p", "--eval", "--print", "-r"):
                    label = _inline_secret_ref(argv[j + 1])
                    if label:
                        return f"opens a {label} from inline code", _category(label)
                    why = _inline_env_leak(argv[j + 1])
                    if why:
                        return why, "envdump"
            if head in ("perl", "ruby"):
                for tok in argv[1:]:
                    label = None if tok.startswith("-") else secret_path(tok)
                    if label:
                        return f"prints a {label} ({tok})", _category(label)
        if head in ("echo", "printf", "print"):
            for tok in argv[1:]:
                for name in _INDIRECT_VAR.findall(tok):
                    vals = varmap.get(name)
                    if vals == _DYNAMIC or (isinstance(vals, list) and any(
                            _SECRET_NAME.search(v) and v not in _BENIGN_VARS for v in vals)):
                        return (f"echoes ${{!{name}}}, the value of each variable that ${name} "
                                "names"), "envdump"
                for name in _SECRET_VAR.findall(tok):
                    if name in _BENIGN_VARS:
                        continue
                    if _SECRET_NAME.search(name) or sourced:
                        return f"echoes the variable ${name}, which may hold a secret", "envdump"
    return None, ""


ADVICE = {
    "dotenv": ("Safe forms for a .env file: list key names only (cut -d= -f1 .env), check that one "
               "is set (grep -q '^NAME=' .env && echo set), or load the values without printing them "
               "(source .env && <command>). If a value is missing or wrong, ask the human to fix the file."),
    "envdump": ("Safe forms for environment variables: list names only (env | cut -d= -f1, filter "
                "with | grep -i NAME), check that one is set (test -n \"$NAME\" && echo set), or "
                "check its length (printf %s \"$NAME\" | wc -c)."),
    "cli": ("Check login state without printing a secret: gh auth status, gcloud auth list, aws sts "
            "get-caller-identity, op whoami, bw status. Let the tool use the credential itself (op "
            "run -- <command>, or the CLI reading its own config). If the human needs to see the "
            "value, they should run the command in their own terminal outside Claude Code: running "
            "it with ! inside Claude Code puts its output into the conversation too."),
    "key": ("Check a key without printing it: ssh-keygen -l -f <file> prints only its fingerprint, "
            "and test -f <file> or ls -l <file> shows that it exists. Pass the path to the tool that "
            "needs the key instead of its contents."),
    "credfile": ("Check that it exists without printing it (test -f <file>, ls -l <file>) and let "
                 "the tool that owns it read it. Check login state with that tool: aws sts "
                 "get-caller-identity, gcloud auth list, gh auth status, docker info, kubectl config "
                 "current-context, npm whoami."),
    "browser": ("Browser password and cookie stores and keychain files are off limits. If a value "
                "is needed, ask the human to look it up and set it in the environment."),
}


def handle(event: dict) -> None:
    if c.disabled("SECRET_GUARD"):
        return
    tool = event.get("tool_name")
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    why, cat = None, ""
    if tool == "Read":
        label = secret_path(str(tin.get("file_path") or ""))
        if label:
            why, cat = f"reading this {label} would put its values into the conversation", _category(label)
    elif tool == "Grep":
        # files_with_matches / count print no values; only content mode does
        if str(tin.get("output_mode") or "files_with_matches") == "content":
            label = secret_path(str(tin.get("path") or "")) or \
                secret_path_glob(str(tin.get("glob") or ""), str(event.get("cwd") or ""))
            if label:
                why = f"grepping this {label} in content mode would put its values into the conversation"
                cat = _category(label)
    elif tool == "Bash":
        # copies and archives of a secret made by earlier commands in this session (E2-3b)
        path = c.marker(c.safe_session(event), "secret-derived")
        derived = c.read_json(path, {})
        derived = derived if isinstance(derived, dict) else {}
        before = dict(derived)
        why, cat = evaluate_bash_ex(str(tin.get("command") or ""), str(event.get("cwd") or ""), derived)
        if not why and derived != before:
            c.write_json(path, dict(list(derived.items())[-200:]))
        if why:
            why = f"this command {why}"
    if not why:
        return
    c.emit_deny(HOOK, event,
                f"Blocked: {why}. Anything a command prints or a file you read goes into the "
                f"conversation, so secrets must not be printed. {ADVICE.get(cat, ADVICE['envdump'])}",
                command=str(tin.get("command") or tin.get("file_path") or ""))


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
