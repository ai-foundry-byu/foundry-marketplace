---
name: scheduled-agents
description: Run Claude Code as an unattended job on a schedule (cron, macOS launchd, Linux systemd, Windows Task Scheduler, or GitHub Actions) and know when it silently stops. Covers headless `claude -p` auth, locks and timeouts, success-only heartbeats, a separate deadman check, alert verification, and the rule that background tasks die when a headless turn ends. Use when the user says "run this every morning", "schedule an agent", "cron job for claude", "run claude headless", "nightly agent", "automate this daily", "why did my scheduled job stop", or "my cron job runs but does nothing".
---

# scheduled-agents: headless agents on a timer, with a deadman

A scheduled agent fails in two ways: loudly (it errors) and silently (it stops running, or runs and does nothing, and every dashboard stays green). This skill prevents both.

You MUST, for every job you set up:

1. Create TWO scheduler entries: the job AND its deadman check (Step 6). A job delivered without a scheduled deadman is not done.
2. Give the deadman an alert channel that works under the scheduler: `--webhook-file` (the URL in a `chmod 600` file) or a literal URL. Never `--webhook "$ALERT_WEBHOOK_URL"`: cron and launchd do not see variables from your shell profile, so it arrives empty.
3. Live-fire the deadman once (`--max-age 1s`) and see the alert arrive before you walk away.

Bundled tools (Python 3 stdlib). Copy both into your project so the schedule does not depend on where the skill is installed (`run_headless.py` imports `deadman.py` from its own folder): `mkdir -p scripts && cp "${CLAUDE_SKILL_DIR}/scripts/run_headless.py" "${CLAUDE_SKILL_DIR}/scripts/deadman.py" scripts/`.

- `${CLAUDE_SKILL_DIR}/scripts/run_headless.py`: runs one `claude -p` job with a lock, a hard timeout, a saved transcript, and a heartbeat written only on real success.
- `${CLAUDE_SKILL_DIR}/scripts/deadman.py`: `beat` writes a heartbeat; `check` alerts when the last success is too old.
- Templates in `${CLAUDE_SKILL_DIR}/templates/`: `crontab.txt` (job and deadman lines), `launchd.plist` (job) plus `launchd-deadman.plist` (its deadman), `task-scheduler.ps1` (registers both tasks), `github-actions.yml`.

## Step 1: pick the primitive

| You need | Use |
|---|---|
| A job while the laptop is off, or on a team repo | **GitHub Actions** `schedule` (template `github-actions.yml`) |
| macOS, user-level job | **launchd** LaunchAgent (template `launchd.plist`); cron also works but launchd runs missed jobs after sleep |
| Linux server | **cron** or a **systemd timer** (`OnCalendar=`, `Persistent=true`) |
| Windows | **Task Scheduler** (template `task-scheduler.ps1`) |
| Something to happen later in THIS interactive session only | the session's own loop or schedule tools; they die when the session ends, so never use them for a standing job |
| A one-time future date | a scheduler entry with an end date, or a calendar reminder; a chat promise is a dropped promise |

Write the **off condition** in the job's header comment: when should this job be deleted? A job with no off condition runs forever after anyone remembers why.

## Step 2: write the job as one foreground turn

Headless mode is one turn: `claude -p "<prompt>"` runs, prints a result, and exits.

**The rule: background work dies when the headless turn ends.** Anything the agent starts in the background (a background shell command, a dev server, a sub-task it plans to check later, a `sleep` it means to come back from) is killed or orphaned when the process exits, and nothing comes back to collect it. So the prompt must:

- do every step in the foreground and wait for it,
- write its output to a file (or open a PR, or post to a webhook) before it finishes,
- never say "I'll check back on this later"; there is no later.

If a job truly needs to wait for something, make the wait a second scheduled job, not a background task.

A good job prompt (`prompts/digest.md`):

```markdown
You are running unattended. No one will answer questions.
1. Read open issues labeled `needs-triage` with `gh issue list --label needs-triage --json number,title,body`.
2. For each, propose one label from: bug, feature, question, duplicate.
3. Write the result to reports/triage-$(date +%F).md as a table.
4. Do not start background processes. Do not edit source files.
Finish by printing one line: TRIAGED <count>.
```

Restrict what it can do with flags after `--`:

```bash
-- --max-turns 30 --allowedTools "Read,Grep,Glob,Write,Bash(gh issue list:*)"
```

Never give an unattended job `--dangerously-skip-permissions` on a machine with your personal files and logins. Grant the specific tools it needs.

## Step 3: auth that works without you

Interactive logins live in your desktop keychain, which cron and launchd often cannot read. For unattended runs:

```bash
claude setup-token      # prints a long-lived token for your subscription
```

Put it in the job's environment as `CLAUDE_CODE_OAUTH_TOKEN` (a `chmod 600` env file sourced by the job, a CI secret, or a user environment variable on Windows). Or use an API key as `ANTHROPIC_API_KEY`. Do not put an OAuth token in `ANTHROPIC_API_KEY`; they are different credentials. Never commit either (see `secrets-hygiene`).

Test auth in a scheduler-faithful environment before scheduling:

```bash
env -i HOME="$HOME" PATH=/usr/bin:/bin CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" \
  "$(command -v claude)" -p "Reply with the word ok" --output-format json --max-turns 1
```

## Step 4: wrap it with run_headless.py

```bash
python3 scripts/run_headless.py --name daily-digest --prompt-file prompts/digest.md \
  --workdir "$HOME/projects/<your-app>" --claude-bin "$(command -v claude)" --max-minutes 20 \
  -- --max-turns 30 --allowedTools "Read,Grep,Glob,Write"
```

It creates `<workdir>/.agent-jobs/` (add it to `.gitignore`) holding:

- `daily-digest.lock`: present while running; a second run exits 4 instead of overlapping
- `logs/daily-digest-<UTC stamp>.json`: the full JSON result
- `daily-digest.heartbeat.json`: rewritten only when claude exited 0, the result is not an error, and the result text is non-empty

Exit codes: 0 ok, 1 failed, 4 already running, 5 timed out, 6 claude not found.

## Step 5: schedule it (copy a template)

Generate BOTH entries, job and deadman, for the chosen scheduler; `crontab.txt` and `task-scheduler.ps1` already hold both, and launchd needs `launchd.plist` plus `launchd-deadman.plist`.

All templates use absolute paths. Schedulers run with a tiny `PATH`, no login shell and none of your exported variables, which is the most common reason a job "works when I run it" and fails on schedule.

- cron: `${CLAUDE_SKILL_DIR}/templates/crontab.txt`. `cd` into the project before anything relative; in POSIX `sh` a failed `. ./file` aborts the whole line.
- launchd: `${CLAUDE_SKILL_DIR}/templates/launchd.plist` and `${CLAUDE_SKILL_DIR}/templates/launchd-deadman.plist`. `plutil -lint` both first; an unescaped `&` makes launchd ignore the file without an error. After changing `EnvironmentVariables`, `bootout` then `bootstrap`; `kickstart` does not re-read them.
- Windows: `${CLAUDE_SKILL_DIR}/templates/task-scheduler.ps1`. `-MultipleInstances IgnoreNew` is the overlap guard.
- GitHub Actions: `${CLAUDE_SKILL_DIR}/templates/github-actions.yml`. Times are UTC, runs can start late, and on public repos scheduled workflows are disabled after 60 days without activity.

Never schedule the same job in two systems (for example cron and launchd). It double-runs and the lock hides it.

## Step 6: add the deadman (the job is not done without it)

The deadman is a **separate** scheduled entry that checks the heartbeat's content timestamp:

```bash
# once: the alert URL in a file the scheduler can read (cron and launchd do not see your shell's env)
mkdir -p ~/.config/agent-alerts && printf '%s\n' 'https://hooks.slack.com/services/...' > ~/.config/agent-alerts/webhook.url
chmod 600 ~/.config/agent-alerts/webhook.url

python3 scripts/deadman.py check --name daily-digest \
  --file "$HOME/projects/<your-app>/.agent-jobs/daily-digest.heartbeat.json" \
  --max-age 26h --webhook-file "$HOME/.config/agent-alerts/webhook.url"
```

- `--max-age` is about one period plus slack (daily job: 26h; hourly job: 2h).
- It reads the `finished_at` written inside the file, not the file's modification time, which a copy or restore can refresh.
- It exits 3 and says so when the alert itself fails to deliver, and also when no channel is set (no `--webhook`, `--webhook-file` or `--alert-cmd`, or only an empty one): stderr says `NO ALERT CHANNEL`. An alert that was never delivered is not an alert.
- On every stale or missing check it also writes `<name>.DEADMAN-ALERT.txt` next to the heartbeat, and removes it on the next fresh check, so a failure leaves a trail on disk even when every channel is down.
- `--alert-cmd` runs any command with the text in `$DEADMAN_MESSAGE` (for example a mail or notification command); it counts as delivered only when the command exits 0.
- Run the deadman somewhere the job's failure cannot also take down: a different scheduler entry at minimum, a different machine or GitHub Actions if the job matters.

Guard rules:

1. **Log success conditionally.** "OK" only on exit 0 and a fresh artifact. `my-job; echo done` prints done after a crash.
2. **Live-fire the alarm once.** Point `--max-age 1s` at the heartbeat and watch the alert arrive before calling the guard done.
3. **Never send the alarm through the thing it watches.** A job that posts to Slack should not be the only path for "the Slack poster is down".

## Verify (all must hold before you walk away)

```bash
# 1. the job runs in a scheduler-faithful env and writes a heartbeat
env -i HOME="$HOME" PATH=/usr/bin:/bin sh -c '<the exact line from your crontab>' ; echo "exit=$?"
cat "$HOME/projects/<your-app>/.agent-jobs/daily-digest.heartbeat.json"

# 2. the scheduler has it
crontab -l | grep daily-digest                       # cron: expect TWO lines, job and deadman
launchctl print gui/$(id -u)/com.example.daily-digest | head -5           # launchd: the job
launchctl print gui/$(id -u)/com.example.daily-digest-deadman | head -5   # launchd: its deadman
# Windows: Get-ScheduledTaskInfo -TaskName daily-digest ; GitHub: Actions tab, run once with "Run workflow"

# 3. the deadman fires: expect exit 1 and an alert that actually arrives
python3 scripts/deadman.py check --file .agent-jobs/daily-digest.heartbeat.json --max-age 1s --webhook-file ~/.config/agent-alerts/webhook.url
```

Then write the off condition in the job's header comment.
