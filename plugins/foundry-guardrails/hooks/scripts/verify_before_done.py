#!/usr/bin/env python3
"""verify-before-done: PreToolUse + Stop hook. "Done" means "tested".

PreToolUse (Bash, Edit, Write, MultiEdit, NotebookEdit):
  * An edit to a code file marks the session dirty and clears the tested
    marker. Docs do not count: *.md, *.mdx, *.txt, *.rst, *.adoc and anything
    under a docs/ directory. Files outside the project directory do not count.
  * A Bash test or typecheck command (pytest, npm test, tsc, go test,
    cargo test, ...) marks the session tested.
  * An irreversible push/deploy/publish command (git push, vercel --prod,
    npm publish, wrangler deploy, terraform apply, ...) is DENIED unless the
    command text contains VERIFY_OK=1. That token also counts as an explicit,
    logged claim of verification for the Stop check.

Stop:
  * If code was edited since the last test run, block the stop ONCE with a
    reason telling Claude to run the tests and report the result.
  * Never loops: allows when stop_hook_active is true (Claude is already
    continuing because of a stop hook), when background tasks are still in
    flight, and after FOUNDRY_VERIFY_MAX_BLOCKS blocks in a session (default 2).

Disable: FOUNDRY_VERIFY=0
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
    return [" ".join(argv) for argv in c.all_argvs(cmd)]


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


def _paths(sid: str) -> dict:
    return {k: c.marker(sid, f"verify-{k}") for k in ("dirty", "tested", "ok", "blocks")}


def handle_pre(event: dict) -> None:
    sid = c.safe_session(event)
    m = _paths(sid)
    tool = event.get("tool_name", "")
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return
    if tool in EDIT_TOOLS:
        path = str(tin.get("file_path") or tin.get("notebook_path") or "")
        if is_code_file(path, project_dir(event)):
            try:
                with open(m["dirty"], "a", encoding="utf-8") as fh:
                    fh.write(path + "\n")
            except OSError:
                pass
            c.remove(m["tested"])
            c.remove(m["ok"])
        return
    if tool != "Bash":
        return
    cmd = str(tin.get("command") or "")
    if OVERRIDE.search(cmd):
        c.touch(m["ok"])
        c.log(HOOK, "verify-ok-token", sid, command=cmd)
        return
    if is_test_command(cmd):
        c.touch(m["tested"])
    hit = irreversible(cmd)
    if hit:
        c.emit_deny(HOOK, event,
                    f"'{hit}' is irreversible (it publishes, deploys, pushes or deletes something "
                    "other people see). Verify first: run the tests or typecheck, confirm the "
                    "change does what was asked, and report the evidence. Then re-run the same "
                    "command prefixed with VERIFY_OK=1 (for example: VERIFY_OK=1 git push).",
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
    files = _dirty_files(m["dirty"])
    if not files:
        return
    if os.path.exists(m["tested"]) or os.path.exists(m["ok"]):
        for k in ("dirty", "tested", "ok"):
            c.remove(m[k])
        return
    max_blocks = c.env_int("FOUNDRY_VERIFY_MAX_BLOCKS", 2)
    blocks = c.read_int(m["blocks"])
    reason_skip = None
    if event.get("stop_hook_active"):
        reason_skip = "stop_hook_active"
    elif event.get("background_tasks"):
        reason_skip = "background tasks in flight"
    elif blocks >= max_blocks:
        reason_skip = f"block cap {max_blocks} reached"
    if reason_skip:
        c.log(HOOK, "allow-unverified-stop", sid, why=reason_skip, files=", ".join(files[:10]))
        if reason_skip != "background tasks in flight":
            c.remove(m["dirty"])  # do not nag on the next, unrelated turn
        return
    c.touch(m["blocks"], str(blocks + 1))
    shown = ", ".join(os.path.basename(f) for f in files[:6]) + (" ..." if len(files) > 6 else "")
    c.emit_stop_block(HOOK, event,
                      f"You edited {len(files)} code file(s) ({shown}) and no test or typecheck "
                      "command has run since the last edit. Before finishing: run the project's "
                      "tests or typecheck (for example pytest, npm test, npx tsc --noEmit, go test "
                      "./...), and report the command and its result. If this change cannot be "
                      "tested, say so plainly and explain why. "
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
