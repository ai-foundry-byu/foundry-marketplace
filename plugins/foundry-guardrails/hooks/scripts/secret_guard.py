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

Allowed on purpose: source .env / . .env (loads without printing),
test -f .env, ls .env, cp .env.example .env, docker --env-file .env,
echo ".env" >> .gitignore, cat .env.example, cat id_ed25519.pub.

Disable: FOUNDRY_SECRET_GUARD=0
This is an accident-catcher, not a sandbox. See the plugin README.
"""
from __future__ import annotations

import fnmatch
import glob
import itertools
import os
import re
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
            "zcat", "view", "fold", "rev", "pr", "expand"}
_INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "deno", "bun", "Rscript"}
_SECRET_VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
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


def evaluate_bash(cmd: str, cwd: str = "") -> str | None:
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    argvs = c.all_argvs(cmd)
    sourced = _sources_env(argvs)
    # input redirection like  cat < .env  or  $(< .env)
    for m in re.finditer(r"<\s*([^\s<>|;&()]+)", cmd):
        if not m.group(0).startswith("<<"):
            label = secret_path(m.group(1))
            if label and not cmd[max(0, m.start() - 1):m.start()] == "<":
                return f"reads a {label} through input redirection"
    for argv in argvs:
        head = os.path.basename(argv[0])
        why = _pw_manager(argv) or _token_printer(argv)
        if why:
            return f"would print secrets from the {why}"
        why = _env_dump(argv)
        if why:
            return why
        # browser stores and keychain files, any command
        for tok in argv[1:]:
            label = secret_path(tok)
            if label in ("browser credential store", "keychain database"):
                return f"touches a {label}"
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
                label = secret_path_glob(tok, cwd)
                if label:
                    return f"prints a {label} ({tok})"
            why = _recursive_grep_hits_env(argv, cwd)
            if why:
                return why
        if head in ("curl", "wget", "http", "https"):
            for tok in argv[1:]:
                if tok.startswith("@") or "=@" in tok:
                    label = secret_path(tok.split("@", 1)[1])
                    if label:
                        return f"uploads a {label}"
        if head == "git" and len(argv) > 2:
            why = _git_prints_secret(argv)
            if why:
                return why
        if head in _INTERPRETERS:
            for j, tok in enumerate(argv[1:-1], start=1):
                if tok in ("-c", "-e", "-p", "--eval", "--print", "-r"):
                    label = _inline_secret_ref(argv[j + 1])
                    if label:
                        return f"opens a {label} from inline code"
                    why = _inline_env_leak(argv[j + 1])
                    if why:
                        return why
            if head in ("perl", "ruby"):
                for tok in argv[1:]:
                    label = None if tok.startswith("-") else secret_path(tok)
                    if label:
                        return f"prints a {label} ({tok})"
        if head in ("echo", "printf", "print"):
            for tok in argv[1:]:
                for name in _SECRET_VAR.findall(tok):
                    if name in _BENIGN_VARS:
                        continue
                    if _SECRET_NAME.search(name) or sourced:
                        return f"echoes the variable ${name}, which may hold a secret"
    return None


def handle(event: dict) -> None:
    if c.disabled("SECRET_GUARD"):
        return
    tool = event.get("tool_name")
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    why = None
    if tool == "Read":
        label = secret_path(str(tin.get("file_path") or ""))
        if label:
            why = f"reading this {label} would put its values into the conversation"
    elif tool == "Grep":
        # files_with_matches / count print no values; only content mode does
        if str(tin.get("output_mode") or "files_with_matches") == "content":
            label = secret_path(str(tin.get("path") or "")) or \
                secret_path_glob(str(tin.get("glob") or ""), str(event.get("cwd") or ""))
            if label:
                why = f"grepping this {label} in content mode would put its values into the conversation"
    elif tool == "Bash":
        why = evaluate_bash(str(tin.get("command") or ""), str(event.get("cwd") or ""))
        if why:
            why = f"this command {why}"
    if not why:
        return
    c.emit_deny(HOOK, event,
                f"Blocked: {why}. Secrets must not be printed into the transcript. Load them "
                "without printing (source .env && <command>), check existence with test -f, or "
                "read the .env.example file for key names. If you need a value, ask the human "
                "to set it in the environment.",
                command=str(tin.get("command") or tin.get("file_path") or ""))


if __name__ == "__main__":
    c.run_hook(HOOK, handle)
