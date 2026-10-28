---
name: tmux-agents
description: Drive interactive CLIs and long-running processes from an agent through tmux. Start a REPL, dev server, database shell, SSH session, or another coding agent in a detached pane, type into it, wait for a prompt or a log line, read the output, and clean up. Includes running several coding agents in parallel in separate git worktrees. Use when the user says "run this in tmux", "keep the dev server running", "drive this REPL", "interactive prompt", "the command needs a TTY", "run several agents in parallel", "watch the logs while you work", or when a command hangs waiting for input.
---

# tmux-agents: give the agent a terminal that stays open

Use tmux only when you need one of these:

- an **interactive** program (a REPL, `psql`, `ssh`, an installer that asks questions, another agent's TUI)
- a **long-running** process the agent must keep alive and check on while it works (a dev server, a watcher, a log tail)
- a session a **human can attach to** and watch

For a one-shot command that finishes on its own, just run it. tmux adds moving parts.

Bundled helper: `${CLAUDE_SKILL_DIR}/scripts/tmux_agent.py` (Python 3 stdlib, calls `tmux`). Install tmux first: `brew install tmux` (macOS), `sudo apt install tmux` (Ubuntu/WSL). On Windows, use WSL.

Every command uses a **private socket** (`$TMUX_AGENT_SOCKET`, or a per-user path under the temp dir), so the agent never types into the user's own tmux sessions.

## The five moves

```bash
T="python3 ${CLAUDE_SKILL_DIR}/scripts/tmux_agent.py"

$T start dev --cwd "$PWD" --cmd "npm run dev"      # 1. start a named session, optionally launch a program
$T wait dev "Local:.*http://localhost:\d+" --timeout 60   # 2. wait for a line (regex; --fixed for plain text)
$T read dev --lines 50                              # 3. read recent output
$T send dev "rs"                                    # 4. type text; Enter is sent separately
$T keys dev C-c                                     #    or send control keys: C-c, C-d, Escape, Up, Tab
$T kill dev                                         # 5. clean up (or: kill --all)
```

Run a shell command in a pane and get its output and exit code back:

```bash
$T start sh --cwd "$PWD"
$T run sh "pytest -q tests/test_api.py" --timeout 300 ; echo "exit=$?"
```

`run` wraps the command in unique begin and end markers, waits for the end marker, and returns the real exit code (124 on timeout, and the command keeps running so you can inspect or `keys sh C-c`).

After starting a session, tell the user how to watch it; `start` prints the exact line:

```
tmux -S <socket> attach -t dev      (detach with Ctrl-b then d)
```

## Rules that prevent the classic failures

1. **Wait for a signal, never sleep and hope.** `wait` for the prompt (`>>> `, `=# `, `\$ $`) or a log line before sending the next input. A fixed `sleep 5` is too long on a fast machine and too short on a loaded one.
2. **Send text and Enter separately** for full-screen apps (Claude Code, Codex, other TUIs). They can treat text and Enter that arrive together as a paste and not submit it. `send` already does this with a 0.3 s pause; raise `--delay` if submissions still get lost.
3. **Send literally.** `send` uses `send-keys -l`, so text like `C-c` or `Enter` inside your string is typed, not interpreted. Use `keys` for real control keys.
4. **Python REPL:** start it with `PYTHON_BASIC_REPL=1 python3 -q`. The newer interactive REPL (3.13+) does auto-indent and paste handling that break typed input.
5. **Read with joined lines.** `read` uses `capture-pane -J`, which rejoins wrapped lines so a regex can match a long line.
6. **Clean up.** Kill every session you started before you finish. A forgotten dev server holds the port, and the next run fails with "address in use".
7. **Never type secrets into a pane.** Pane history is readable by anyone who can attach. Export them in the environment before `start`.

## Recipes

**Dev server plus tests against it**

```bash
$T start web --cwd "$PWD" --cmd "npm run dev"
$T wait web "ready|Local:" --timeout 90
curl -fsS http://localhost:3000/api/health
$T run sh "npx playwright test" --timeout 600
$T kill web
```

**Database shell**

```bash
$T start db --cmd 'psql "$DATABASE_URL"'
$T wait db "=[#>] $" --timeout 20
$T send db "\dt"
$T wait db "=[#>] $" && $T read db --lines 40
$T send db "\q"
```

**An installer that asks questions**

```bash
$T start setup --cwd "$PWD" --cmd "npx create-next-app@latest my-app"
$T wait setup "TypeScript\?" --timeout 120 && $T send setup "y"
$T wait setup "ESLint\?" && $T send setup "y"
```

(Many installers also accept flags such as `--yes` or `--ts`; prefer those when they exist.)

**Parallel coding agents in separate worktrees**

Each agent gets its own git worktree, so they never edit the same checkout:

```bash
for n in 1 2 3; do
  git worktree add "../<your-app>-task$n" -b "task$n"
  $T start "agent$n" --cwd "../<your-app>-task$n" --cmd "claude"
done
$T wait agent1 "for shortcuts|>" --timeout 60          # the TUI is ready; the pattern depends on the version
$T send agent1 "Fix the failing test in tests/test_dates.py. Run the tests before you stop."
$T send agent2 "Add input validation to app/api/signup/route.ts with tests."
$T read agent1 --lines 80                              # check progress
```

Notes for parallel agents:

- Run the project's install step in each worktree before starting the agent.
- Detecting "done" from a TUI screen is fragile (prompt glyphs change between versions). For unattended work prefer headless mode, `claude -p "..." --output-format json`, and use tmux only for sessions a person will watch or steer.
- Two agents running the same dev server port collide. Give each worktree its own `PORT`.
- Remove worktrees after merging: `git worktree remove ../<your-app>-task1`.

## Raw tmux equivalents (when the helper is not available)

```bash
S="${TMPDIR:-/tmp}/tmux-agent.sock"
tmux -S "$S" new-session -d -s dev -c "$PWD"
tmux -S "$S" send-keys -t dev:0.0 -l -- 'npm run dev' && sleep 0.3 && tmux -S "$S" send-keys -t dev:0.0 Enter
tmux -S "$S" capture-pane -p -J -t dev:0.0 -S -200
tmux -S "$S" send-keys -t dev:0.0 C-c
tmux -S "$S" kill-session -t dev
tmux -S "$S" list-sessions
```

## Verify

```bash
$T start check --cmd "PYTHON_BASIC_REPL=1 python3 -q"
$T wait check ">>> " --timeout 10
$T send check "print(6*7)"
$T wait check "^42$" --timeout 10 && echo PASS
$T kill check
$T ls      # expect: (no sessions)
```

Credit: the send-text-then-Enter timing and the private-socket convention follow the tmux skill published by the OpenClaw project (MIT). The helper here is a fresh implementation.
