# foundry-sdlc

The deterministic 0-to-1 workflow AI Foundry uses to take software from an idea to a shipped, verified product with Claude Code agents. It has eight stages. Each stage produces one file and ends at a gate. A stage detector tells any agent which stage a project is in, so a new session (or a new teammate) picks up exactly where the last one stopped.

| # | Stage | Artifact | Item in this plugin |
|---|---|---|---|
| 0 | Scaffold | the artifact set | `new-project` skill, `scripts/new_project.py` |
| 1 | Gather requirements | `REQUIREMENTS.md`, `DECISIONS.md` | `gather-requirements` skill |
| 2 | PRD + user stories | `PRD.md`, `stories.json` | `write-prd` skill, `scripts/gen_stories.py`, `prd-critic` agent |
| 3 | Workplan | `WORKPLAN.md` | `write-workplan` skill |
| 4 | Execute | branches, one per lane | `parallel-lanes` skill |
| 5 | Code QA | tests, CI | (companion: `foundry-qa` regression-check) |
| 6 | Visual QA with example users | `done-journey.yaml`, screenshots | `story-verifier` agent (companions: `foundry-qa`, `foundry-design`, `foundry-devices`) |
| 7 | Ship | `CHANGELOG.md`, stories LIVE | `ship` skill |
| 8 | Feedback | new stories + failing tests | `bug-to-story` skill (companion: `foundry-evals`) |

The `sdlc` skill is the router. It holds the full map and the one rule that matters most: **never skip a gate**.

## Install

Add the marketplace once:

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install this plugin:

```text
/plugin install foundry-sdlc@ai-foundry
```

From a shell instead (for example, to install for the whole project):

```bash
claude plugin install foundry-sdlc@ai-foundry --scope project
```

The companion plugins are installed the same way: `foundry-guardrails`, `foundry-qa`, `foundry-design`, `foundry-devices`, `foundry-evals`.

## Quick start

In your project, ask Claude: "Use foundry-sdlc to start a new project called Study Buddy." Or do it by hand:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new_project.py" product --name "Study Buddy" --owner "Team 4"
```

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdlc_stage.py" .
```

(`${CLAUDE_PLUGIN_ROOT}` is the plugin's install directory. If it is empty in your shell, the plugin lives at `$HOME/.claude/plugins/cache/ai-foundry/foundry-sdlc/<version>/`, or use your clone of this repo.) Then paste `docs/CLAUDE-md-snippet.md` into your project's `CLAUDE.md`.

## Items

### Skills

Invoke a skill by asking in plain words, for example "write the PRD", or by name: `/foundry-sdlc:write-prd`.

| Skill | What it does | Maturity |
|---|---|---|
| `sdlc` | The router. Stage map, which artifact and which skill or agent each stage uses, and how to detect the current stage | proven |
| `new-project` | Scaffolds the artifact set from `templates/`, copies `tools/gen_stories.py`, and sets up the CI check | proven |
| `gather-requirements` | Verbatim asks with R-ids and sources, a DECISIONS table, and an "Already exists" audit before the PRD | proven |
| `write-prd` | The PRD with inline `**US-01. Title.**` stories and observable criteria. Compiles stories.json, runs the prd-critic, and fills "Addressed critiques" | proven |
| `write-workplan` | Task table (Id, Task, Owner with model, effort and review tier by blast radius, Deps, Status), milestones, "Blocked on human" | proven |
| `parallel-lanes` | One git worktree and one agent per independent task: naming, the lane brief, the "edit only inside your worktree" rule, merge back | proven |
| `ship` | The ship ritual: done gate, persona testers, story-verifier, design review, then LIVE, changelog, and "go try X" | proven |
| `bug-to-story` | Each bug becomes a story plus a failing regression test. Usage gates, with graduation decided by a human | proven |

### Agents

| Agent | What it does | Maturity |
|---|---|---|
| `prd-critic` | Adversarial PRD review in a fresh context. Returns numbered critiques (C1..) with severity, location and a suggested fix. Read-only: never rewrites the PRD | proven (pattern) |
| `story-verifier` | Checks one story on the deployed build from its criteria, the URL and screenshots only. Returns PASS, FAIL or INCONCLUSIVE per criterion with evidence. Never reads the builder's claims | proven (pattern) |

Use them by asking, for example "Use the prd-critic agent on product/PRD.md", or let the `write-prd` and `ship` skills call them.

### Hook

| Hook | What it does | Maturity |
|---|---|---|
| SessionStart stage hint | Runs `sdlc_stage.py --hook`. If the project has a `PRD.md` or `REQUIREMENTS.md` (in the root, `product/` or `docs/product/`), it prints two lines: the current stage and the failing exit check. Silent otherwise. It never blocks a session | new |

### Scripts

| Script | What it does | Maturity |
|---|---|---|
| `scripts/gen_stories.py` | Compiles PRD stories into `stories.json`. `--check` exits 1 if the file is stale, a story has no criteria, an id is duplicated, or a status is invalid. Regenerating keeps `status`, `notes`, `evidence` and any meta the PRD does not set | proven (generalized port) |
| `scripts/new_project.py` | Scaffolds the artifact set. Never overwrites without `--force` | new |
| `scripts/sdlc_stage.py` | Reports the current stage from the files on disk (`--json` for machines, `--hook` for the SessionStart hook) | new |

### Templates and docs

| File | Purpose | Maturity |
|---|---|---|
| `templates/REQUIREMENTS.md` | Sources, verbatim asks (R-01..), "Already exists" audit, constraints, open questions | proven |
| `templates/DECISIONS.md` | Verbatim human decisions with what each one authorizes, and pending questions with a recommendation | proven |
| `templates/PRD.md` | Short version, user, metrics, principles, scope, stories, architecture, rollout with "used fully" gates, risks, Appendix A (addressed critiques), Appendix B (push back) | proven |
| `templates/WORKPLAN.md` | Status block, blast-radius tiers, Next up, milestones, task table, Blocked on human, Parked | proven |
| `templates/stories.schema.json` | JSON Schema for stories.json (id, title, acceptance[], surfaces[], devices[], status, waits_on[], optional covers/notes/evidence) | proven |
| `templates/done-journey.yaml` | Journey for the `foundry-qa` done gate: `steps` (goto, click, fill, wait_for), `assertions` (visible, text, url_contains), `screenshot` | proven (format) |
| `templates/CHANGELOG.md` | One dated heading per ship, one bullet per user-visible change, with evidence | proven |
| `templates/README.md` | Project README that indexes the artifact set | new |
| `docs/CLAUDE-md-snippet.md` | Always-on norms to paste into a project CLAUDE.md: root cause first, surgical changes, never "done" without a passing gate, the 4-tier blast-radius table, reuse before build | proven |

**What the maturity labels mean.** "proven" means the item is generalized from a workflow, format or tool that runs in production in our harness today. "proven (pattern)" means the agent's role and rules are what we use in production, rewritten here as a portable agent definition. "new" means it was written for this marketplace and is not yet battle-tested. Please report problems.

## Requirements

- Claude Code with plugin support.
- Python 3.8 or later for the scripts (standard library only).
- git 2.5 or later for worktrees (`parallel-lanes`).
- For `story-verifier` to drive a browser: Playwright for Python (`pip install playwright`, then `python3 -m playwright install chromium`). Without it, the verifier judges from screenshots and HTTP checks, and marks the rest INCONCLUSIVE.
- For stages 5 and 6: the companion plugins `foundry-qa` (done-gate, persona-tester, regression-check) and `foundry-design`. Native apps need `foundry-devices`.

## Tests

```bash
cd plugins/foundry-sdlc && python3 -m unittest discover -s scripts/tests -v
```

## Related work

Scott Murff's **agent-team-kit** (https://github.com/ai-foundry-byu/agent-team-kit) is a complementary team harness. It covers spec, mockup, build-spec, worktree launchers, merge-worktree, a regression check and release skills, installed with its own `install.sh`. This plugin does not copy any of its files. See its repository for license and usage.

## License

MIT. Copyright AI Foundry (BYU Marriott).
