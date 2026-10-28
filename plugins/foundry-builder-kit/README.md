# foundry-builder-kit

Day-one build skills for student projects. Install it before you write your first route: it adds sign-in, gets the app ready for real users, keeps your API keys out of git, cuts your LLM bill on simple calls, runs agents on a schedule without silent failures, and lets an agent drive interactive terminals.

Part of the AI Foundry (BYU Marriott) marketplace.

## Install

Add the marketplace (once):

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the plugin:

```text
/plugin install foundry-builder-kit@ai-foundry
```

From a shell instead of a session:

```bash
claude plugin marketplace add ai-foundry-byu/foundry-marketplace
```

```bash
claude plugin install foundry-builder-kit@ai-foundry
```

Not using plugins? See "Install one item on its own" below. Every script runs on its own with `python3`.

## What is inside

| Item | Type | What it does | SDLC stage | Maturity |
|---|---|---|---|---|
| `add-auth` | skill | Audits the project, recommends an auth provider with the trade-off, implements sign-in, verifies with a build and a protected-route check | build | proven |
| `scale-10k` | skill | Launch-readiness audit (auth cost, DB pooling, sessions, rate limits, email, compliance, monitoring) with a scorecard, cost table and ordered fixes | ship | proven |
| `secrets-hygiene` | skill | `.env` patterns, gitignore, gitleaks pre-commit and CI, and the probe-first rotation flow for a leaked key | build / operate | proven (rotation flow); new (templates) |
| `cheap-llm-routing` | skill | Route schema-pinned extraction or classification to a free or cheap model, with a privacy bar and a paid fallback | build | proven |
| `scheduled-agents` | skill | Headless `claude -p` on cron, launchd, Task Scheduler or GitHub Actions, with locks, timeouts, success-only heartbeats and a deadman | operate | proven (cron/launchd, deadman); new (Windows, GitHub Actions) |
| `tmux-agents` | skill | Drive REPLs, dev servers, installers and parallel coding agents through tmux on a private socket | build / test | proven |
| commit secret guard | hook | `skills/secrets-hygiene/scripts/commit_secret_guard.py`, wired in `hooks/hooks.json`. Blocks a `git commit` the agent runs when the staged change contains a secret (gitleaks if installed, stdlib scanner otherwise) | build | new |
| `skills/secrets-hygiene/scripts/scan_secrets.py` | script | Stdlib secret scanner: `--staged`, `--worktree`, `--all`, or paths; redacted output | build | new |
| `skills/secrets-hygiene/scripts/probe_key.py` | script | Asks a provider whether a key still authenticates: LIVE, DEAD or ERR (ERR is never an all-clear) | operate | new |
| `skills/cheap-llm-routing/scripts/structured_router.py` | script | Forced-tool-call structured extraction across a privacy-aware provider chain with schema validation | build | new |
| `skills/scheduled-agents/scripts/run_headless.py` | script | Runs one `claude -p` job with a lock, timeout, saved transcript and success-only heartbeat | operate | new |
| `skills/scheduled-agents/scripts/deadman.py` | script | Writes heartbeats and alerts (webhook or command) when the last success is too old; reports failed alert delivery | operate | new |
| `skills/tmux-agents/scripts/tmux_agent.py` | script | start, send, keys, read, wait, run, ls, kill on a private tmux socket | build / test | new |
| `skills/secrets-hygiene/templates/` | template | `.gitignore` block, `.env.example`, `.pre-commit-config.yaml`, plain git hook, GitHub Actions secret scan | build | new |
| `skills/scheduled-agents/templates/` | template | crontab lines, LaunchAgent plist, Task Scheduler PowerShell, GitHub Actions workflow | operate | new |

**Maturity labels.** "proven" means the skill is generalized from a tool or runbook that runs in production in our own harness today. "new" means it was written for this marketplace from documentation and best practice and has unit tests, but has not yet been battle-tested in production. Where a skill mixes both, the table says which part is which.

Notes on the "proven" labels, so you can weigh them:

- `add-auth` and `scale-10k` are lightly edited from skills installed in our harness. The decision trees and audit checklists are what we use; we have not run every provider path ourselves. Provider prices and APIs change, so the skills tell the agent to check the pricing page and the installed framework version.
- `cheap-llm-routing`: the rules (privacy bar, forced tool call, key-prefix gate, paid fallback) come from a production feature that moved a structured matching task to a free tier. The bundled router script is new.
- `scheduled-agents`: the guard patterns (success-only logging, content-timestamp deadman, alert-delivery check, launchd env gotcha) run in our harness daily. The Windows and GitHub Actions templates and both scripts are new.
- `tmux-agents`: the pattern drives our parallel agent runs. The helper script is new.

## How to use each item

### add-auth

Ask: "add sign-in to this app", or run `/foundry-builder-kit:add-auth` (optionally with `clerk`, `supabase`, `better-auth`, `authjs`, or `--dry-run`). The agent audits first, recommends one provider with the trade-off, asks before changing code, then verifies: build passes, an anonymous request to a protected route is redirected, sign-out works, `.env.local` is gitignored.

### scale-10k

Ask: "is this ready for launch?" or run `/foundry-builder-kit:scale-10k` (or `scale-10k rate-limiting`, `--audit-only`, `--cost-estimate`). You get a READY / NEEDS WORK / CRITICAL scorecard with file and line citations, a cost table at 1k, 5k, 10k and 50k users, and fixes in priority order.

### secrets-hygiene

Ask: "set up secret scanning" or "I committed my OpenAI key". Prevention takes about 10 minutes: gitignore block, `.env.example`, gitleaks pre-commit hook, CI scan. For a leak, the order is: probe the key, map every place it is used, mint a new one, swap all consumers, revoke the old one, probe again until it reports DEAD, and only then scrub git history.

```bash
LEAKED=sk-... python3 "${CLAUDE_PLUGIN_ROOT}/skills/secrets-hygiene/scripts/probe_key.py" openai:LEAKED
```

### Commit secret guard (hook)

Enabled automatically with the plugin. It looks at every Bash command, ignores everything except `git commit`, and blocks the commit (with redacted findings) when the staged change, or the tracked changes for `git commit -a`, contain something that looks like a key. It guards commits the agent makes; install the git pre-commit hook from `secrets-hygiene` for the commits you type. Turn it off for a session with `export FOUNDRY_SECRETS_GUARD=0`. Mark a deliberate fake with the comment `secrets-hygiene: allow`.

### cheap-llm-routing

Ask: "make this classification call free" or "use Groq for this, with a fallback". Mark each call `private` (real user data) or `public`. Private data never goes to a provider whose terms allow training on inputs.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cheap-llm-routing/scripts/structured_router.py" --schema schema.json --data-class private --plan
```

### scheduled-agents

Ask: "run this agent every morning" or "why did my cron job stop". The agent writes the job as one foreground turn, wraps it with `run_headless.py`, schedules it from a template, and adds a separate `deadman.py check` so a silent stop becomes an alert.

### tmux-agents

Ask: "keep the dev server running while you test" or "drive this REPL". The agent uses `tmux_agent.py` to start a named session, wait for a prompt, send input, read output, and clean up.

## Install one item on its own

Every skill is self-contained: its scripts, templates and examples live inside its own folder and are referenced through `${CLAUDE_SKILL_DIR}`, so you can copy one folder without the rest of the plugin.

```bash
cp -R skills/secrets-hygiene ~/.claude/skills/        # personal, every project
cp -R skills/secrets-hygiene .claude/skills/          # this project only
```

- Standalone: `add-auth`, `scale-10k`, `cheap-llm-routing`, `scheduled-agents`, `tmux-agents`, `secrets-hygiene`. Each works when copied on its own.
- Needs a skill: no agents ship in this plugin, so nothing depends on another item.
- Plugin only: the commit secret guard hook. Copying `secrets-hygiene` brings the scanner and the guard script, but nothing runs the guard on agent commits unless the plugin is installed. Without the plugin, install the git pre-commit hook from `secrets-hygiene` instead.

## Requirements

- Claude Code with plugin support.
- Python 3.9+ on PATH as `python3` (scripts are stdlib only). On Windows, if your Python is `py` or `python`, the hook will not find `python3`; create an alias or install Python from python.org with the "add to PATH" option, or use WSL.
- `git` for the secret scanner and hook.
- Optional: `gitleaks` (recommended, `brew install gitleaks` or a release binary), `tmux` for `tmux-agents` (macOS, Linux, or WSL), and accounts with whichever auth, LLM, and email providers you choose.

## Tests

From this plugin directory:

```bash
python3 -m unittest discover -s tests -v
```

The tmux tests are skipped when tmux is not installed; the gitleaks test is skipped when gitleaks is not installed. No test touches the network.

## Related

For a fuller team harness (memory, hooks, team skills) see the cohort's agent team kit: https://github.com/ai-foundry-byu/agent-team-kit

## License

MIT. The tmux send-text-then-Enter timing follows the tmux skill from the OpenClaw project (MIT); the helper here is a fresh implementation.
