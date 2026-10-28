# foundry-guardrails

Claude Code hooks that turn SDLC rules from advice into gates. Your system prompt can *ask* Claude to run tests before saying "done", to stay out of `.env`, or to never force-push `main`. A hook *checks* it on every tool call and every stop, and it keeps checking when the session runs with skipped permission prompts.

Six hooks, all Python 3 standard library, all on by default except `ship-stop` (which turns on when you point it at a workplan):

| Hook | Event (matcher) | What it blocks | Default | Disable | Maturity |
|---|---|---|---|---|---|
| `destructive-guard` | PreToolUse (`Bash`) | `rm -rf` of `/`, `~`, `$HOME`, `*`, `.` or a system dir; force-push to `main`/`master` (plain `--force` anywhere); `git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f` when they would destroy uncommitted work; `DROP`/`TRUNCATE`/`DELETE` without `WHERE` sent through a DB client; `dd of=/dev/...`; `mkfs`; fork bombs; `chmod -R 777 /`; `curl ... \| sh`; `shutdown`/`reboot` | deny | `FOUNDRY_DESTRUCTIVE_GUARD=0` | verified |
| `secret-guard` | PreToolUse (`Bash\|Read\|Grep`) | Reading or printing `.env`, private keys, cloud/registry credential files; browser password and cookie stores; password-manager CLIs (`bw`, `op`, `lpass`, `pass`, `security ... -w`); token printers (`gh auth token`, `gcloud auth print-access-token`, ...); `env`/`printenv` dumps and `env \| grep NAME`; `echo $API_KEY`; simple indirection (`f=.env; cat "$f"`, `for f in .env*`, `find -exec cat`, `xargs cat`, `cp .env x && cat x`). Listing key names only (`cut -d= -f1 .env`, `env \| cut -d= -f1 \| grep AWS`) is allowed | deny | `FOUNDRY_SECRET_GUARD=0` | beta |
| `verify-before-done` | PreToolUse (`Bash\|Edit\|Write\|MultiEdit\|NotebookEdit`) + Stop | Stopping after changing code with no test or typecheck run since the change (blocks once per stop, at most 2 times per session). In a git repo it detects the change by content, so edits made with `sed -i`, heredocs, `tee`, `cp` or a script count too. Irreversible commands (`git push`, `vercel --prod`, `npm publish`, `wrangler deploy`, `terraform apply`, `gh pr merge`, ...) unless the command contains `VERIFY_OK=1`, which is refused while code is untested | on | `FOUNDRY_VERIFY=0` | verified |
| `worktree-guard` | PreToolUse (`Edit\|Write\|MultiEdit\|NotebookEdit`) | From inside a linked git worktree, editing a file in the main checkout. While a lane registry (`.git/foundry-lanes.json`) is active, a subagent editing the main checkout | deny (only acts inside a linked worktree, or for a subagent while lanes are active) | `FOUNDRY_WORKTREE_GUARD=0` | verified |
| `stale-write-guard` | PreToolUse (`Write`) + PostToolUse (`Edit\|Write\|MultiEdit`) | A whole-file `Write` to a git-tracked file whose uncommitted changes were not made by this session (they would be overwritten) | deny (`FOUNDRY_STALE_WRITE_ENFORCE=0` warns instead) | `FOUNDRY_STALE_WRITE_GUARD=0` | verified |
| `ship-stop` | Stop | Stopping while the workplan milestone you named is still `- [ ]` (at most 8 continuations per milestone) | off until `FOUNDRY_SHIP_WORKPLAN` is set | `FOUNDRY_SHIP_STOP=0` or unset the workplan | verified |
| `guardrails-help` | skill | Tells Claude how to respond when a guardrail blocks it, and tells you how to configure the hooks | n/a | n/a | verified |

`FOUNDRY_GUARDRAILS=0` turns every hook off at once.

**Maturity.** The labels come from our test runs on 2026-10-28, recorded with what we ran in [`evidence/evidence.json`](../../evidence/evidence.json). "verified" means the hook's main path held in live Claude Code sessions with no known major defect left on it. "beta" means it works with known gaps: `secret-guard` still lets a key pasted into an ordinary source file reach the conversation when the agent reads that file, and it recognizes secrets by file name and command shape, so a determined workaround can still get past it. It does follow copies, compress and archive round trips (`gzip -c .env | zcat`, `tar czf e.tgz .env` then `tar xzOf e.tgz`), including a read-back in a later command of the same session, and it allows names-only listings such as `env | grep AWS | cut -d= -f1`. "new" means little or no live testing. Most hooks are generalized from hooks that run in our own Claude Code harness every day; `destructive-guard` uses the rule set of the published `claude-deploy-kit` command guard, and `stale-write-guard` is ported from a guard we wrote but never switched on.

## Guardrails, not a security boundary

These hooks catch the mistakes a well-meaning agent actually makes: running `cat .env` to "check the config", force-pushing over a teammate, wiping a directory with a bad glob, declaring victory without running tests. They are **not** a sandbox. A determined process can get around any pattern list. Scripts that read secrets from inside a file and commands built at runtime are invisible to them, a secret pasted into an ordinary source file (`settings.py`, `config.js`) reaches the conversation in full when the agent reads that file, and only `verify-before-done` sees shell writes such as `cat > file` (by their effect on the files; `worktree-guard` and `stale-write-guard` watch only the edit tools). For a real boundary, use OS-level isolation: a container or VM, a scrubbed environment with no secrets in it, and least-privilege credentials. Use both.

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
| `FOUNDRY_SECRET_GUARD=0` | secret-guard | disable. The foundry-builder-kit commit guard is a separate hook with its own switch, `FOUNDRY_COMMIT_SECRET_GUARD=0` |
| `FOUNDRY_VERIFY=0` | verify-before-done | disable (also the human override when a push must go out unverified) |
| `FOUNDRY_VERIFY_MAX_BLOCKS=2` | verify-before-done | Stop blocks allowed per session |
| `FOUNDRY_VERIFY_TEST_PATTERN='^just test'` | verify-before-done | extra regex that counts as a test command |
| `FOUNDRY_VERIFY_IRREVERSIBLE_PATTERN='^make release'` | verify-before-done | extra regex that needs `VERIFY_OK=1` |
| `FOUNDRY_VERIFY_IGNORE='*.json,config/*'` | verify-before-done | extra globs that do not count as code edits |
| `FOUNDRY_WORKTREE_GUARD=0` | worktree-guard | disable |
| `FOUNDRY_WORKTREE_GUARD_WARN=1` | worktree-guard | warn instead of deny |
| `FOUNDRY_STALE_WRITE_GUARD=0` | stale-write-guard | disable |
| `FOUNDRY_STALE_WRITE_ENFORCE=0` | stale-write-guard | warn instead of deny (the warning arrives after the write, so it protects nothing) |
| `FOUNDRY_SHIP_WORKPLAN=path` | ship-stop | arm it (relative paths resolve from the project directory) |
| `FOUNDRY_SHIP_MILESTONE=M3.2` | ship-stop | the milestone to finish (default: the first open one) |
| `FOUNDRY_SHIP_MAX_BLOCKS=8` | ship-stop | continuation cap per milestone per session (above 8, Claude Code's own cap may end the turn first; see ship-stop) |
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

SQL rules apply only when the command calls a database client (`psql`, `mysql`, `sqlite3`, `duckdb`, `supabase db`, `prisma db execute`, `wrangler d1 execute`, ...). An `echo "DROP TABLE"` is not blocked. A `WHERE` that is always true (`WHERE 1`, `WHERE 1=1`, `WHERE true`, `WHERE 'x'='x'`, `WHERE id=id`, `WHERE id=2 OR 1=1`) counts as no `WHERE`.

### secret-guard

Anything a command prints, or a file Claude reads, goes into the conversation and to the model provider. The guard denies the read or print, and points Claude at the safe forms:

| Allowed | Denied |
|---|---|
| `source .env && npm run dev` | `cat .env`, `head .env`, `grep KEY .env`, `Read(.env)` |
| `test -f .env`, `ls -la .env`, `grep -q KEY .env` | `echo $API_KEY`, `source .env && echo $DATABASE_URL` |
| `cp .env.example .env`, `cat .env.example` | `env`, `printenv`, `printenv OPENAI_API_KEY`, `env \| grep AWS` |
| `docker run --env-file .env app` | `gh auth token`, `op read ...`, `security find-generic-password -w` |
| `cat ~/.ssh/id_ed25519.pub` | `cat ~/.ssh/id_ed25519`, `git show HEAD:.env` |
| `for f in *.py; do cat "$f"; done`, `find . -name '*.py' -exec cat {} \;` | `f=.env; cat "$f"`, `for f in .env*; do cat "$f"; done`, `find . -name '.env*' -exec cat {} \;`, `ls -a \| grep env \| xargs cat`, `cp .env x && cat x` |
| key names only: `cut -d= -f1 .env`, `sed 's/=.*//' .env`, `awk -F= '{print $1}' .env`, `grep -o '^[A-Za-z_][A-Za-z0-9_]*' .env`, `env \| cut -d= -f1` (optionally piped into `sort`, `uniq`, `wc`, `head`, `tail`, or a grep that reads only stdin: `env \| cut -d= -f1 \| grep -i AWS`) | `cut -d= -f2 .env`, `awk -F= '{print $2}' .env`, names-only forms on a `.env` with a multi-line value or a long token in a comment (they would print part of it) |

Simple indirection is followed: a variable bound in the same command (`f=.env; cat "$f"`, `for f in .env*; do cat "$f"; done`, `... | while read f; do cat "$f"; done`), a reader of `$(...)` whose command names a secret file (`cat $(ls -a | grep env)`), `find ... -exec cat {}` on a secret name or on a folder holding `.env` with no name filter, `... | xargs cat` fed by a command that names a secret file, a copy read later in the same command (`cp .env x && cat x`), `ls -a`/`ls -A` of a folder holding `.env` feeding a reader (`ls -A | xargs cat`), `printenv` of names picked at run time (`printenv $(env | cut -d= -f1 | grep AWS)`, `for k in ...; do printenv "$k"`, `echo "${!k}"`), and code fed to an interpreter on stdin (`python3 - <<'PY' ... open('.env') ... PY`, `python3 <<< '...'`; versioned names such as `python3.12 -c` too). Anything less direct (a script file, a variable set in an earlier command, a name built at run time) is not seen.

`env | grep NAME` stays denied: grep prints the whole `NAME=value` line of each match. The deny says so and gives the names-only form, `env | cut -d= -f1 | grep NAME`. `env | grep -q NAME` and `-c` print no value and are allowed.

Each deny's advice fits what was blocked: names-only and `source` forms for a `.env`; `env | cut -d= -f1` and `test -n "$NAME"` for environment variables; `gh auth status`, `gcloud auth list`, `aws sts get-caller-identity`, `op whoami` for credential CLIs; `ssh-keygen -l -f <file>` (fingerprint only) for private keys.

What it does not hide:

- A secret pasted into an ordinary source file. The guard knows secrets by file name and command shape, so `cat settings.py` or `git diff` prints a hardcoded key in full, and it goes to the model provider. Keep keys in `.env`. The foundry-builder-kit commit guard still blocks committing them.
- Output of a `!` command. Running a command with `!` in the Claude Code prompt puts its output into the conversation, the same as when Claude runs it. To look at a secret yourself, use a terminal outside Claude Code.

Secret files: `.env` and `.env.*` (but not `.env.example`, `.sample`, `.template`, `.dist`), `.envrc`, `*.pem`, `*.key`, `*.p12`, SSH private keys, `~/.aws/credentials`, `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`, docker and kube configs, the GitHub CLI hosts file, gcloud credentials, `credentials.json`, `service-account*.json`, `secrets.{json,yaml,toml}`.

### verify-before-done

1. A code change marks the session "untested". The hook sees it two ways:
   - **By effect, in a git repo.** At the session's first hook call it records every dirty or untracked source file with its content hash, plus `HEAD`. At Stop (and when `VERIFY_OK=1` is used) it compares again. A source file whose content changed, including in a commit made since, is a change, whatever tool made it: `Edit`, `sed -i`, `cat > f <<EOF`, `tee`, `cp`/`mv`, a Python script, `git apply`. Source means code extensions (`.py`, `.ts`, `.go`, `.html`, `.css`, `.sql`, ... and `Makefile`, `Dockerfile`). Docs (`*.md`, `*.txt`, `*.rst`, `docs/`), data and side-effect files a program writes (`.json`, `.db`, `.log`, lockfiles), dependency and build folders, files outside the project, and files that were already dirty and that the session did not touch do not count.
   - **By tool.** Every `Edit`/`Write` to a non-doc file inside the project (in git, not once the file is back to what it was).
   - Effects cannot tell who made a change: an edit you make in your editor, or another Claude session in the same checkout, counts too. Run parallel sessions in separate worktrees.
   - **Outside git**, a command-pattern fallback: the targets of `>`/`>>`, `tee`, `sed -i`, `perl -i`, `cp`, `mv`, inline `python -`/`node -e` code that writes a file (by the literal path it opens, so a heredoc that rewrites `README.md` is a doc edit; a path held in a variable shows as "a file written by a shell command"), `git apply` and `patch`. A script file that writes code (`python gen.py`) is not seen there. When the session started outside git and the project becomes a repo (`git init`), the hook measures effects from that point on.
   - **Generated files.** A file a generator wrote does not count while its bytes are unchanged. The generator lists its files in `.foundry/generated.json` at the project root or the repo root (paths are relative to the folder that holds `.foundry/`):

     ```json
     {"version": 1, "generator": "foundry-sdlc/new-project",
      "files": [{"path": "tools/gen_stories.py", "sha256": "<hex SHA-256 of the file bytes>"}]}
     ```

     A listed file whose SHA-256 still matches is skipped (logged as `skip-generated`). Once anyone edits it, it counts again. A missing or malformed manifest, an absolute path or a path outside that folder is ignored. The foundry-sdlc scaffolder writes it, so right after a scaffold the hook does not ask for a test run of the scaffolded `tools/gen_stories.py`. The manifest is trusted as written: like `VERIFY_OK=1`, it is an audit aid, not an approval.
2. A Bash test or typecheck marks it "tested" and moves the baseline to the code that test saw: `pytest`, `python -m unittest`, `uv run pytest`, `npm test`, `npm run test:unit`, `pnpm typecheck`, `npx tsc --noEmit`, `vitest`, `jest`, `go test`, `cargo test`, `mvn test`, `gradle test`, `dotnet test`, `make test`, and more. The command has to start a stage, so `echo pytest` does not count.
3. On Stop: if code changed since the last test run, Claude gets one "keep working" message with this reason, then continues:

   ```text
   [foundry-guardrails/verify-before-done] Code changed in 2 file(s) (app.py, api.py) and no test
   or typecheck command has run since. Before finishing: run the project's tests or
   typecheck ..., and report the command and its result. If this change cannot be tested, say so
   plainly and explain why. (block 1 of at most 2 this session; FOUNDRY_VERIFY=0 disables)
   ```

   It is sent as Stop hook feedback (`hookSpecificOutput.additionalContext`, the documented non-error path), so Claude Code labels it "Stop hook feedback". Earlier versions of this plugin used `decision: "block"`, which Claude Code labels "Stop hook error occurred · ctrl+o to see". Either way it is the guard working, not a crash: press ctrl+o to read the reason, or check `guardrails.log`.
4. It cannot loop. When Claude stops again while `stop_hook_active` is true after this hook's own message, the stop is allowed, an "unverified stop" line is logged, and the baseline resets so the next turn is not nagged about the same change. When a different Stop hook (ship-stop) is what kept Claude going, the check still runs, so code written during those continuations is still checked. The session-wide cap (default 2) and Claude Code's own cap back that up. While background tasks are still running (a test run in the background, for example), the stop is allowed and the change stays pending.
5. Irreversible commands are denied until the command carries `VERIFY_OK=1`, for example `VERIFY_OK=1 git push origin feature`, and the token is refused while code changed since the last test run: "run the tests first; VERIFY_OK=1 is for after they pass". Tests in the same command count only when they gate the push: `pytest && VERIFY_OK=1 git push`. With `;`, `||`, `&` or a pipe in between (`pytest; VERIFY_OK=1 git push`, `npm test | tail && ...`) the push would run whatever the tests report, so it is refused. A command the hook denies never runs, so its tests do not count either. The token is logged. If the project has no tests, the agent is told to hand the command to you instead; `FOUNDRY_VERIFY=0` is the human override.
6. When `destructive-guard` also denies a command (a force push to `main`, for example), this hook stays silent. Claude Code passes only one deny reason to the model when two hooks deny the same call, so the more important one is the one Claude gets.

### worktree-guard

When the session's working directory is inside a linked worktree (`git worktree add`, or Claude Code's own worktrees), an edit through an absolute path into the main checkout is denied, and the reason names the same file inside your worktree. Edits inside your worktree, to `/tmp`, to another repo, or to another worktree are allowed.

**Subagent lanes.** A subagent started with the Agent tool and no isolation runs in the parent's working directory, the main checkout, so the rule above cannot fire for it. Its tool calls carry `agent_id` in the hook input; the parent session's own calls do not. When a subagent edits the main checkout while the lane registry says lanes are active, the edit is denied, and the message tells the integrator to launch lanes with the Agent tool option `isolation: "worktree"` (or as their own `claude` session started in the lane worktree). Edits inside a registered lane worktree, any linked worktree, `.claude/worktrees/`, or outside the repo are allowed. The registry is `<git common dir>/foundry-lanes.json` (normally `.git/foundry-lanes.json`), written by the foundry-sdlc parallel-lanes skill:

```json
{"active": true, "lanes": [{"id": "T-03", "tasks": ["T-03"], "branch": "lane/T-03-magic-link",
  "worktree": "../myapp-lanes/T-03"}]}
```

A relative `worktree` resolves from the main checkout. Lanes whose `worktree` is still `null` (the skill writes the registry before launch, and fills in each path when that lane reports) count as active, so the main checkout is protected while they run. A `worktree` at or above the main checkout (`"."`, `"~"`) is ignored rather than allowing the whole checkout. The repo is found from the working directory, or else from the target path, so a session started in the folder above the repo is covered too. With no registry, `"active": false`, an empty `lanes` list or unreadable JSON, nothing changes, so ordinary subagents and the main session are unaffected. A subagent started with `isolation: "worktree"` runs inside its own worktree and gets the normal worktree rule.

### stale-write-guard

A `Write` replaces the whole file with what Claude holds in context. The hook protects uncommitted changes that this session did not make (yours, a formatter's, another session's). After every `Edit`/`Write`/`MultiEdit` the session makes, it records the file's content hash. A `Write` is then allowed when the file is new, untracked, outside git, clean against `HEAD`, identical to the new content, or still exactly what this session last wrote. Otherwise it is **denied**, even after a Read, and Claude is told to use `Edit` for a targeted change, or to ask you to commit or stash first. With `FOUNDRY_STALE_WRITE_ENFORCE=0` it only warns, and the warning reaches Claude after the write has already replaced the file, so warn mode does not prevent the overwrite. The warning says that: the uncommitted lines were overwritten and may be unrecoverable, and Claude should tell you which file it was.

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
- After 8 continuations on one milestone (`FOUNDRY_SHIP_MAX_BLOCKS`), the stop is allowed and you see "a human needs to look at it" (a `systemMessage`). The default is 8 because Claude Code ends the turn itself once Stop hooks have continued it 8 times in a row with no tool call in between: it overrides the 9th block and says "A hook blocked the turn from ending 9 consecutive times" (observed on Claude Code 2.1.308). `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises that limit. With a plugin cap above Claude Code's, the plugin's message may never show.
- Each continuation is sent as Stop hook feedback, not an error (see verify-before-done, point 3). Older builds showed "Stop hook error occurred" here; that was the guard working.
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

200 tests. They cover the allow and deny cases for each rule, the false positives listed above, malformed stdin, the disable switches, the Stop loop caps, and real temporary git repos and worktrees. The hooks were also checked end to end in a live `claude -p --plugin-dir` session: `cat .env` was denied, and a code edit with no tests got exactly one Stop block.

## Known limitations

- Pattern matching cannot see inside script files. `python leak.py` that prints `.env`, or `psql -f drop.sql`, is not caught.
- `verify-before-done` sees that a test command *ran*, not that it *passed*. The Stop message asks Claude to report the result. Review it.
- `VERIFY_OK=1` can be typed by the agent itself. It is refused while code is untested, but a test command that ran is not a test that passed. It is an audit token, not an approval. If you need a human approval step, deny the command and have the human run it.
- `secret-guard` denies `sed -i` on `.env` (a reader command naming a secret file). Edit `.env` yourself.
- The worktree guard only sees the `Edit`/`Write`/`NotebookEdit` tools, not shell writes. For subagent lanes it acts only while the lane registry is active, and it cannot tell one lane subagent from another: a lane started without isolation can still edit a sibling lane's worktree.
- `verify-before-done` outside git reads write targets from the command text only. Inside git, a `git pull` that changes code files mid-session also counts as a change.
- `stale-write-guard` counts the session's own `sed`/heredoc changes as "not this session's", because it records only edit-tool writes. Claude is told to use `Edit` in that case.

## Credits

These hooks are small, self-contained versions of two fuller MIT-licensed projects. Use those when you need more:

- [ethos-gate](https://github.com/jddavenportOpen/ethos-gate): irreversible-action guard, credential-scrape policy with strict and sandbox tiers, an outbound GitHub action gate with an LLM judge, and a lethal-trifecta audit.
- [claude-deploy-kit](https://github.com/jddavenportOpen/claude-deploy-kit): the destructive command rule set, policy and eval gates, and the audit trail for fleets of headless agents.

For a full team harness (agents, skills, memory, hooks) built for the AI Foundry cohort, see [agent-team-kit](https://github.com/ai-foundry-byu/agent-team-kit).

## License

MIT. See [LICENSE](LICENSE).
