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

## Per hook

| Message from | What it means | Do this |
|---|---|---|
| `destructive-guard` | the command could destroy data or history | `git stash` instead of `reset --hard`; `--force-with-lease` on a feature branch instead of `--force`; name the exact directory to delete; add a `WHERE` clause; download a script to a file and read it before you run it |
| `secret-guard` | the command or Read would put a secret value in the transcript | load secrets with `source .env && <cmd>`; check presence with `test -f .env` or `grep -q KEY .env`; read `.env.example` for key names; ask the human to set a missing value |
| `verify-before-done` (PreToolUse) | a push, deploy, publish or merge needs evidence first | run the tests or typecheck, look at the result, report it, then re-run the same command with `VERIFY_OK=1` in front, for example `VERIFY_OK=1 git push origin feature`. Use the token only after you really verified |
| `verify-before-done` (Stop) | you edited code and ran no test or typecheck after the last edit | run the project's test command (`pytest`, `python -m unittest`, `npm test`, `npx tsc --noEmit`, `go test ./...`) and report the command and its result. If there is no way to test this change, say so plainly and explain why. The stop is allowed on the next try |
| `worktree-guard` | you are in a linked worktree but edited the main checkout | redo the edit at the path the message suggests, inside your worktree |
| `stale-write-guard` | the file has uncommitted changes and Write would replace all of it | Read the file again, then use Edit for a targeted change |
| `ship-stop` | the workplan milestone is still `- [ ]` | keep working until its acceptance notes pass, then change it to `- [x]`. If it is truly blocked on a human (a credential, a decision, access), change it to `- [!]` with the reason on the same line, and report |

## Configuring (for the human)

All switches are environment variables. Set them in the `env` block of `.claude/settings.json` or `.claude/settings.local.json`, not inside a command:

```json
{ "env": { "FOUNDRY_DESTRUCTIVE_ALLOW": "git-clean", "FOUNDRY_STALE_WRITE_ENFORCE": "1" } }
```

- Turn everything off: `FOUNDRY_GUARDRAILS=0`. Turn one hook off: `FOUNDRY_DESTRUCTIVE_GUARD=0`, `FOUNDRY_SECRET_GUARD=0`, `FOUNDRY_VERIFY=0`, `FOUNDRY_WORKTREE_GUARD=0`, `FOUNDRY_STALE_WRITE_GUARD=0`, `FOUNDRY_SHIP_STOP=0`.
- Allow one destructive rule: `FOUNDRY_DESTRUCTIVE_ALLOW=<rule>`, using the rule name from the deny message.
- Teach verify-before-done your test runner: `FOUNDRY_VERIFY_TEST_PATTERN='^just test'`. Exclude non-code files: `FOUNDRY_VERIFY_IGNORE='*.json,*.lock'`.
- Ship mode: `FOUNDRY_SHIP_WORKPLAN=WORKPLAN.md` plus an optional `FOUNDRY_SHIP_MILESTONE=M3.2`. Milestones are `- [ ] M<n>[.<n>] title` lines, and indented lines under one are its acceptance notes.

## Checking what happened

Every deny, warning and Stop block is one JSON line in `guardrails.log`, in `${CLAUDE_PLUGIN_DATA}/state/` or `${TMPDIR}/foundry-guardrails/`. To report a false positive, find the line, copy the `command` and `reason`, and either allow the rule or narrow the pattern in the hook script and add a test case under `tests/`.

## Acceptance check

You handled a block correctly when:
- you did not retry a reworded version of the blocked command
- you either took the safe alternative or told the human what was blocked, by which rule, and why you needed it
- any `VERIFY_OK=1` you used comes after a test run whose result you reported
