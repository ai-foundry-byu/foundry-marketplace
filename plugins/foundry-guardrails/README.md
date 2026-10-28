# foundry-guardrails

Claude Code hooks that turn SDLC rules from advice into gates. Your system prompt can *ask* Claude to run tests before saying "done", to stay out of `.env`, or to never force-push `main`. A hook *checks* it on every tool call and every stop, and it keeps checking when the session runs with skipped permission prompts.

Six hooks, all Python 3 standard library, all on by default except `ship-stop` (which turns on when you point it at a workplan):

| Hook | Event (matcher) | What it blocks | Default | Disable | Maturity |
|---|---|---|---|---|---|
| `destructive-guard` | PreToolUse (`Bash`) | `rm -rf` of `/`, `~`, `$HOME`, `*`, `.` or a system dir; force-push to `main`/`master` (plain `--force` anywhere); `git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f` when they would destroy uncommitted work; `DROP`/`TRUNCATE`/`DELETE` without `WHERE` sent through a DB client; `dd of=/dev/...`; `mkfs`; fork bombs; `chmod -R 777 /`; `curl ... \| sh`; `shutdown`/`reboot` | deny | `FOUNDRY_DESTRUCTIVE_GUARD=0` | new |
| `secret-guard` | PreToolUse (`Bash\|Read\|Grep`) | Reading or printing `.env`, private keys, cloud/registry credential files; browser password and cookie stores; password-manager CLIs (`bw`, `op`, `lpass`, `pass`, `security ... -w`); token printers (`gh auth token`, `gcloud auth print-access-token`, ...); `env`/`printenv` dumps; `echo $API_KEY` | deny | `FOUNDRY_SECRET_GUARD=0` | proven |
| `verify-before-done` | PreToolUse (`Bash\|Edit\|Write\|MultiEdit\|NotebookEdit`) + Stop | Stopping after editing code with no test or typecheck run since the last edit (blocks once per stop, at most 2 times per session). Irreversible commands (`git push`, `vercel --prod`, `npm publish`, `wrangler deploy`, `terraform apply`, `gh pr merge`, ...) unless the command contains `VERIFY_OK=1` | on | `FOUNDRY_VERIFY=0` | proven |
| `worktree-guard` | PreToolUse (`Edit\|Write\|MultiEdit\|NotebookEdit`) | From inside a linked git worktree, editing a file in the main checkout | deny (only acts inside a linked worktree) | `FOUNDRY_WORKTREE_GUARD=0` | proven |
| `stale-write-guard` | PreToolUse (`Write`) | A whole-file `Write` to a git-tracked file that has uncommitted changes (they would be overwritten) | warn | `FOUNDRY_STALE_WRITE_GUARD=0` | new |
| `ship-stop` | Stop | Stopping while the workplan milestone you named is still `- [ ]` (at most 20 continuations per milestone) | off until `FOUNDRY_SHIP_WORKPLAN` is set | `FOUNDRY_SHIP_STOP=0` or unset the workplan | proven |
| `guardrails-help` | skill | Tells Claude how to respond when a guardrail blocks it, and tells you how to configure the hooks | n/a | n/a | new |

`FOUNDRY_GUARDRAILS=0` turns every hook off at once.

**Maturity.** "proven" means the hook is a generalized version of a hook that runs in our own Claude Code harness every day. "new" means it was written for this marketplace from documented patterns and is tested here, but it has not been run in daily use. `destructive-guard` uses the rule set of the published `claude-deploy-kit` command guard (a library, not a hook), so it is labeled new. `stale-write-guard` is ported from a guard we wrote but never switched on, so it is labeled new too.

## Guardrails, not a security boundary

These hooks catch the mistakes a well-meaning agent actually makes: running `cat .env` to "check the config", force-pushing over a teammate, wiping a directory with a bad glob, declaring victory without running tests. They are **not** a sandbox. A determined process can get around any pattern list. Shell writes (`cat > file`), scripts that read secrets from inside a file, and commands built at runtime are invisible to them. For a real boundary, use OS-level isolation: a container or VM, a scrubbed environment with no secrets in it, and least-privilege credentials. Use both.

## Install

Add the marketplace:

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the plugin:

```text
/plugin install foundry-guardrails@ai-foundry
```

Restart Claude Code so the hooks load. Then confirm they are registered:

```text
/hooks
```

To try it from a local clone without installing:

```bash
claude --plugin-dir ./plugins/foundry-guardrails
```

### Install one item on its own

Nothing in this plugin works on its own. The six guardrails are hooks, and only a plugin can install hooks (they live in `hooks/hooks.json` and point at `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/`).

| Item | Standalone copy? | Needs |
|---|---|---|
| all six hooks | no, plugin only | the plugin install |
| `guardrails-help` skill | no, plugin only | the hooks it explains. It references no files, so a copy in `.claude/skills/` loads, but without the hooks there is nothing for it to explain |

There are no agents in this plugin.

## Requirements

- `python3` (3.8 or newer) on your `PATH`. The hooks run in exec form (`python3 <script>`), so there is no shell quoting to break. If `python3` is missing, Claude Code treats each hook as a non-blocking error and the tool call goes ahead, so you lose the guard but your session keeps working.
- `git` for `destructive-guard` (dirty-tree checks), `worktree-guard` and `stale-write-guard`.
- macOS or Linux. Windows works when `python3` resolves to a real executable. Nothing here is tested on Windows yet.

## Configuration

Every switch is an environment variable. Put them in the `env` block of `.claude/settings.json` (project, shared with your team) or `.claude/settings.local.json` (just you), so the agent cannot change them from inside a command:

```json
{
  "env": {
    "FOUNDRY_STALE_WRITE_ENFORCE": "1",
    "FOUNDRY_VERIFY_IGNORE": "*.json,*.lock",
    "FOUNDRY_SHIP_WORKPLAN": "WORKPLAN.md",
    "FOUNDRY_SHIP_MILESTONE": "M3.2"
  }
}
```

| Variable | Hook | Effect |
|---|---|---|
| `FOUNDRY_GUARDRAILS=0` | all | disable every hook |
| `FOUNDRY_DESTRUCTIVE_GUARD=0` | destructive-guard | disable |
| `FOUNDRY_DESTRUCTIVE_ALLOW=rule1,rule2` | destructive-guard | allow named rules for the session (rule names appear in every deny message, for example `git-reset-hard`) |
| `FOUNDRY_ALLOW_FORCE_PUSH=1` | destructive-guard | allow plain `--force` to non-protected branches. `main`/`master` stay blocked |
| `FOUNDRY_PROTECTED_BRANCHES=develop,release` | destructive-guard | add protected branches (`main` and `master` are always protected) |
| `FOUNDRY_SECRET_GUARD=0` | secret-guard | disable |
| `FOUNDRY_VERIFY=0` | verify-before-done | disable |
| `FOUNDRY_VERIFY_MAX_BLOCKS=2` | verify-before-done | Stop blocks allowed per session |
| `FOUNDRY_VERIFY_TEST_PATTERN='^just test'` | verify-before-done | extra regex that counts as a test command |
| `FOUNDRY_VERIFY_IRREVERSIBLE_PATTERN='^make release'` | verify-before-done | extra regex that needs `VERIFY_OK=1` |
| `FOUNDRY_VERIFY_IGNORE='*.json,config/*'` | verify-before-done | extra globs that do not count as code edits |
| `FOUNDRY_WORKTREE_GUARD=0` | worktree-guard | disable |
| `FOUNDRY_WORKTREE_GUARD_WARN=1` | worktree-guard | warn instead of deny |
| `FOUNDRY_STALE_WRITE_GUARD=0` | stale-write-guard | disable |
| `FOUNDRY_STALE_WRITE_ENFORCE=1` | stale-write-guard | deny instead of warn |
| `FOUNDRY_SHIP_WORKPLAN=path` | ship-stop | arm it (relative paths resolve from the project directory) |
| `FOUNDRY_SHIP_MILESTONE=M3.2` | ship-stop | the milestone to finish (default: the first open one) |
| `FOUNDRY_SHIP_MAX_BLOCKS=20` | ship-stop | continuation cap per milestone per session |
| `FOUNDRY_SHIP_STOP=0` | ship-stop | disable |
| `FOUNDRY_GUARDRAILS_STATE_DIR`, `FOUNDRY_GUARDRAILS_LOG` | all | override where state and the log go |

## How each hook behaves

### destructive-guard

Each command is normalized before matching. `sudo`, `env VAR=x`, `nohup`, `timeout`, `xargs` and leading `VAR=x` assignments are stripped. `bash -c '...'`, `sh -c`, `eval` and `$(...)` are unwrapped and checked as their own commands. Chains (`;`, `&&`, `||`, `|`) are split. Text inside a commit message or an `echo` is not a command, so `git commit -m "never rm -rf /"` is allowed.

Allowed on purpose, because blocking them would get the guard switched off: `rm -rf node_modules`, `rm -rf ./dist`, `git status`, `git push --force-with-lease` to a feature branch, `git reset --hard` on a clean tree, `DELETE FROM t WHERE ...`, `curl ... -o install.sh`.

Example deny, as Claude sees it:

```text
[foundry-guardrails/destructive-guard] Blocked destructive command (rule git-reset-hard):
git reset --hard would throw away uncommitted changes. Run git stash (recoverable) or
commit first. ...
```

SQL rules apply only when the command calls a database client (`psql`, `mysql`, `sqlite3`, `duckdb`, `supabase db`, `prisma db execute`, `wrangler d1 execute`, ...). An `echo "DROP TABLE"` is not blocked.

### secret-guard

Anything a command prints, or a file Claude reads, goes into the conversation and to the model provider. The guard denies the read or print, and points Claude at the safe forms:

| Allowed | Denied |
|---|---|
| `source .env && npm run dev` | `cat .env`, `head .env`, `grep KEY .env`, `Read(.env)` |
| `test -f .env`, `ls -la .env`, `grep -q KEY .env` | `echo $API_KEY`, `source .env && echo $DATABASE_URL` |
| `cp .env.example .env`, `cat .env.example` | `env`, `printenv`, `printenv OPENAI_API_KEY` |
| `docker run --env-file .env app` | `gh auth token`, `op read ...`, `security find-generic-password -w` |
| `cat ~/.ssh/id_ed25519.pub` | `cat ~/.ssh/id_ed25519`, `git show HEAD:.env` |

Secret files: `.env` and `.env.*` (but not `.env.example`, `.sample`, `.template`, `.dist`), `.envrc`, `*.pem`, `*.key`, `*.p12`, SSH private keys, `~/.aws/credentials`, `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`, docker and kube configs, the GitHub CLI hosts file, gcloud credentials, `credentials.json`, `service-account*.json`, `secrets.{json,yaml,toml}`.

### verify-before-done

1. Every `Edit`/`Write` to a code file inside the project marks the session "dirty" and clears "tested". Docs (`*.md`, `*.mdx`, `*.txt`, `*.rst`, `*.adoc`, anything under `docs/`) and files outside the project do not count.
2. A Bash test or typecheck marks it "tested": `pytest`, `python -m unittest`, `uv run pytest`, `npm test`, `npm run test:unit`, `pnpm typecheck`, `npx tsc --noEmit`, `vitest`, `jest`, `go test`, `cargo test`, `mvn test`, `gradle test`, `dotnet test`, `make test`, and more. The command has to start a stage, so `echo pytest` does not count.
3. On Stop: if the session is dirty and untested, Claude gets one block with this reason, then continues:

   ```text
   [foundry-guardrails/verify-before-done] You edited 2 code file(s) (app.py, api.py) and no test
   or typecheck command has run since the last edit. Before finishing: run the project's tests or
   typecheck ..., and report the command and its result. If this change cannot be tested, say so
   plainly and explain why. (block 1 of at most 2 this session; FOUNDRY_VERIFY=0 disables)
   ```

4. It cannot loop. When Claude stops again while `stop_hook_active` is true, the stop is allowed and an "unverified stop" line is logged. The session-wide cap (default 2) and Claude Code's own limit of 8 consecutive continuations back that up. While background tasks are still running (a test run in the background, for example), the stop is allowed and the session stays dirty.
5. Irreversible commands are denied until the command carries `VERIFY_OK=1`, for example `VERIFY_OK=1 git push origin feature`. The token is logged and also counts as verification for the Stop check. It is an explicit claim that the agent verified the work, and it shows up in review. It is not a lock.

### worktree-guard

When the session's working directory is inside a linked worktree (`git worktree add`, or Claude Code's own worktrees), an edit through an absolute path into the main checkout is denied, and the reason names the same file inside your worktree. Edits inside your worktree, to `/tmp`, to another repo, or to another worktree are allowed. In the main checkout the hook does nothing.

### stale-write-guard

A `Write` replaces the whole file with what Claude holds in context. If the tracked file has uncommitted changes (from you, a formatter, or another session), the hook warns Claude by default. The warning goes into Claude's context and the write still happens. With `FOUNDRY_STALE_WRITE_ENFORCE=1` it denies the write and tells Claude to read the file again and use `Edit`. New files, untracked files, files outside git, clean files and identical content always pass.

### ship-stop

Keeps Claude working until a milestone in your workplan is checked off. The workplan format:

```markdown
- [x] M3.1 Schema migration
- [ ] M3.2 Export endpoint returns CSV
  - acceptance: GET /export?fmt=csv returns 200 with a header row
  - acceptance: pytest tests/test_export.py passes
- [!] M3.3 Payment webhook (blocked: needs a sandbox key from a human)
```

- `- [ ]` is open, `- [x]` is done, and `- [!]` or `- [-]` is blocked or deferred, with the reason on the same line. Only an open milestone blocks.
- Indented lines under a milestone are quoted back to Claude as its acceptance notes.
- After 20 continuations on one milestone (`FOUNDRY_SHIP_MAX_BLOCKS`), the stop is allowed and stderr says a human needs to look.
- A missing file, an unknown milestone id, or background tasks still running all allow the stop.

Arm it for one run:

```bash
FOUNDRY_SHIP_WORKPLAN=WORKPLAN.md FOUNDRY_SHIP_MILESTONE=M3.2 claude
```

## State and logs

Per-session markers and the log go in `${CLAUDE_PLUGIN_DATA}/state/` when Claude Code provides it, and otherwise in `${TMPDIR}/foundry-guardrails/`. Every deny, warning, Stop block and unverified stop is one JSON line in `guardrails.log`:

```json
{"ts": "2026-10-28T07:40:46", "hook": "secret-guard", "action": "deny", "session": "abc123", "tool": "Bash", "reason": "Blocked: this command prints a dotenv file (.env). ...", "command": "cat .env"}
```

Read it to see what the agent tried, and to tune false positives.

## Failure behavior

Every hook **fails open**. Malformed stdin, a missing `git`, an unwritable state directory or a bug in the hook itself leads to exit 0 with no output, so the tool call goes ahead and an `error-fail-open` line is logged. A broken guard must never brick a session. The cost is that a broken guard is silent, so check the log after you change a hook.

## Tests

```bash
cd plugins/foundry-guardrails
python3 -m unittest discover -s tests -v
```

108 tests. They cover the allow and deny cases for each rule, the false positives listed above, malformed stdin, the disable switches, the Stop loop caps, and real temporary git repos and worktrees. The hooks were also checked end to end in a live `claude -p --plugin-dir` session: `cat .env` was denied, and a code edit with no tests got exactly one Stop block.

## Known limitations

- Pattern matching cannot see inside script files. `python leak.py` that prints `.env`, or `psql -f drop.sql`, is not caught.
- `verify-before-done` sees that a test command *ran*, not that it *passed*. The Stop message asks Claude to report the result. Review it.
- `VERIFY_OK=1` can be typed by the agent itself. It is an audit token, not an approval. If you need a human approval step, deny the command and have the human run it.
- `secret-guard` denies `sed -i` on `.env` (a reader command naming a secret file). Edit `.env` yourself.
- The worktree guard only sees the `Edit`/`Write`/`NotebookEdit` tools, not shell writes.
- `stale-write-guard` warns whenever a tracked file is dirty, including when the dirt is Claude's own earlier edit in the same session. That is why it warns by default.

## Credits

These hooks are small, self-contained versions of two fuller MIT-licensed projects. Use those when you need more:

- [ethos-gate](https://github.com/jddavenportOpen/ethos-gate): irreversible-action guard, credential-scrape policy with strict and sandbox tiers, an outbound GitHub action gate with an LLM judge, and a lethal-trifecta audit.
- [claude-deploy-kit](https://github.com/jddavenportOpen/claude-deploy-kit): the destructive command rule set, policy and eval gates, and the audit trail for fleets of headless agents.

For a full team harness (agents, skills, memory, hooks) built for the AI Foundry cohort, see [agent-team-kit](https://github.com/ai-foundry-byu/agent-team-kit).

## License

MIT. See [LICENSE](LICENSE).
