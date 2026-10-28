---
name: guardrails-help
description: What to do when a foundry-guardrails hook blocks a tool call or a stop, and how to configure or tune the hooks. Use when a tool result or stop reason starts with "[foundry-guardrails/", when a command was "Blocked destructive command", "Blocked ... secrets must not be printed", needs "VERIFY_OK=1", or a stop was blocked by verify-before-done or ship-stop. Also use when someone asks "why was this blocked", "turn off the guardrails", "allow force push", "the hook is a false positive", or "set up ship mode with a workplan".
---

# Working with foundry-guardrails

Install: plugin only. The guardrails are hooks, which only a plugin can install.

The foundry-guardrails plugin runs six hooks. A blocked call is a decision a human configured, not an error to work around. Here is what to do for each one.

## The response rule

1. Read the reason. Every message names the hook and usually the rule, for example `[foundry-guardrails/destructive-guard] ... (rule git-reset-hard)`.
2. Do the safe alternative the message names. Do **not** try another spelling of the same command (`bash -c`, `eval`, a script file, a different reader tool). Getting around a guard defeats the reason it exists, and the attempt is logged.
3. If no safe path exists, stop and tell the human what you wanted to do, why, and which rule blocked it. Quote the rule name so they can allow it if they decide to.
4. Never type `VERIFY_OK=1` before a test or typecheck run has passed. If there are no tests, hand the command to the human.
5. When two guards deny the same call, Claude Code passes only one reason to you. After fixing that one, expect the other.
6. Never write or edit `.foundry/generated.json` or `.git/foundry-lanes.json` to quiet a guard. The generator and the lane integrator own those files.

## Per hook

| Message from | What it means | Do this |
|---|---|---|
| `destructive-guard` | the command could destroy data or history | `git stash` instead of `reset --hard`; `--force-with-lease` on a feature branch instead of `--force`; name the exact directory to delete; add a `WHERE` clause; download a script to a file and read it before you run it |
| `secret-guard` | the command or Read would put a secret value in the transcript (a loop, a variable, `find -exec`, `xargs` or a copy of the file counts as the same read) | follow the advice in the message, which fits what was blocked. A `.env`: `source .env && <cmd>`, `grep -q KEY .env`, `cut -d= -f1 .env`. Environment variables: `test -n "$VAR" && echo set`, `env \| cut -d= -f1 \| grep -i NAME`. Credential CLIs: `gh auth status`, `gcloud auth list`, `aws sts get-caller-identity`. Private keys: `ssh-keygen -l -f <file>`. Do not suggest that the human run it with `!` to keep the value from the model: output of a `!` command goes into the conversation too. They should use a terminal outside Claude Code |
| `verify-before-done` (PreToolUse) | a push, deploy, publish or merge needs evidence first | run the tests or typecheck and report the result. Only after a passing run, re-run the command with `VERIFY_OK=1` in front, for example `VERIFY_OK=1 git push origin feature`. The token is refused while code changed since the last test run; in one command a test counts only as `<test> && VERIFY_OK=1 <command>` (not after `;`, `||`, `&` or a pipe). No tests, or you could not verify: do not add the token; tell the human what is unverified and let them run it |
| `verify-before-done` (Stop) | you changed code (with any tool, including `sed -i`, heredocs or scripts) and ran no test or typecheck after the change | run the project's test command (`pytest`, `python -m unittest`, `npm test`, `npx tsc --noEmit`, `go test ./...`) and report the command and its result. If there is no way to test this change, say so plainly and explain why. The stop is allowed on the next try |
| `worktree-guard` | you are in a linked worktree but edited the main checkout, or you are a lane subagent and edited the main checkout while lanes are active | redo the edit at the path the message suggests, inside your worktree. A lane subagent edits only inside its lane worktree, by absolute path. The integrator launches lanes with the Agent tool option `isolation: "worktree"` |
| `stale-write-guard` | the file has uncommitted changes this session did not make, and Write would replace all of it | use Edit for a targeted change that keeps those lines, or ask the human to commit or stash first. A Read does not lift this block |
| `ship-stop` | the workplan milestone is still `- [ ]` | keep working until its acceptance notes pass, then change it to `- [x]`. If it is truly blocked on a human (a credential, a decision, access), change it to `- [!]` with the reason on the same line, and report. After 8 continuations the stop is allowed and the human is told to look |

## Configuring (for the human)

All switches are environment variables. Set them in the `env` block of `.claude/settings.json` or `.claude/settings.local.json`, not inside a command:

```json
{ "env": { "FOUNDRY_DESTRUCTIVE_ALLOW": "git-clean", "FOUNDRY_STALE_WRITE_ENFORCE": "0" } }
```

- Turn everything off: `FOUNDRY_GUARDRAILS=0`. Turn one hook off: `FOUNDRY_DESTRUCTIVE_GUARD=0`, `FOUNDRY_SECRET_GUARD=0`, `FOUNDRY_VERIFY=0`, `FOUNDRY_WORKTREE_GUARD=0`, `FOUNDRY_STALE_WRITE_GUARD=0`, `FOUNDRY_SHIP_STOP=0`.
- Allow one destructive rule: `FOUNDRY_DESTRUCTIVE_ALLOW=<rule>`, using the rule name from the deny message.
- Let a push go out with no test run: `FOUNDRY_VERIFY=0`. Let stale-write-guard warn instead of deny: `FOUNDRY_STALE_WRITE_ENFORCE=0` (the warning comes after the write, so it protects nothing).
- Teach verify-before-done your test runner: `FOUNDRY_VERIFY_TEST_PATTERN='^just test'`. Exclude non-code files: `FOUNDRY_VERIFY_IGNORE='*.json,*.lock'`.
- Ship mode: `FOUNDRY_SHIP_WORKPLAN=WORKPLAN.md` plus an optional `FOUNDRY_SHIP_MILESTONE=M3.2`. Milestones are `- [ ] M<n>[.<n>] title` lines, and indented lines under one are its acceptance notes.

## "Stop hook error occurred" (for the human)

When a Stop guard keeps Claude working, that is the guard working, not a crash. This plugin sends it as Stop hook feedback, which Claude Code documents as the non-error path. Older plugin builds used `decision: "block"`, which Claude Code labels "Stop hook error occurred · ctrl+o to see". In either case press ctrl+o to read the reason, or check `guardrails.log`. Claude Code also ends a turn on its own once Stop hooks have continued it 8 times in a row without a tool call (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises that).

## Checking what happened

Every deny, warning and Stop block is one JSON line in `guardrails.log`, in `${CLAUDE_PLUGIN_DATA}/state/` or `${TMPDIR}/foundry-guardrails/`. To report a false positive, find the line, copy the `command` and `reason`, and either allow the rule or narrow the pattern in the hook script and add a test case under `tests/`.

## Acceptance check

You handled a block correctly when:
- you did not retry a reworded version of the blocked command
- you either took the safe alternative or told the human what was blocked, by which rule, and why you needed it
- any `VERIFY_OK=1` you used comes after a test run whose result you reported
