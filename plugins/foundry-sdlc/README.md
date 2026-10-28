# foundry-sdlc

The deterministic 0-to-1 workflow AI Foundry uses to take software from an idea to a shipped, verified product with Claude Code agents. It has eight stages. Each stage produces one file and ends at a gate. A stage detector tells any agent which stage a project is in, so a new session (or a new teammate) picks up exactly where the last one stopped.

| # | Stage | Artifact | Item in this plugin |
|---|---|---|---|
| 0 | Scaffold | the artifact set | `new-project` skill, `skills/new-project/scripts/new_project.py` |
| 1 | Gather requirements | `REQUIREMENTS.md`, `DECISIONS.md` | `gather-requirements` skill |
| 2 | PRD + user stories | `PRD.md`, `stories.json` | `write-prd` skill, `scripts/gen_stories.py`, `prd-critic` agent |
| 3 | Workplan | `WORKPLAN.md` | `write-workplan` skill |
| 4 | Execute | branches, one per lane | `parallel-lanes` skill |
| 5 | Code QA | tests, CI | (companion: `foundry-qa` regression-check) |
| 6 | Visual QA with example users | `done-journey.yaml`, `.qa/done-gate/last.json`, `.qa/verify/<id>.md` | the battery in the `sdlc` and `ship` skills: `story-verifier` agent plus `foundry-qa` (done-gate, persona-tester, a11y-check) and `foundry-design` (design-critique); `foundry-devices` for native apps |
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

In your project, ask Claude: "Use foundry-sdlc to start a new project called Study Buddy." Or do it by hand, from the project root (leave out `--name` to take it from the folder name):

```bash
python3 "$PLUGIN/skills/new-project/scripts/new_project.py" product --name "<Project Name>" --owner "<Owner>"
```

```bash
python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --check
```

```bash
python3 "$PLUGIN/skills/sdlc/scripts/sdlc_stage.py" .
```

(`$PLUGIN` is the plugin's install directory, `$HOME/.claude/plugins/cache/ai-foundry/foundry-sdlc/<version>/`, or your clone of this repo at `plugins/foundry-sdlc`.) The scaffolder writes the artifacts to `product/`, and `tools/gen_stories.py` plus `.github/workflows/stories.yml` to the project root (the git root). The story check passes right after scaffolding. Then paste `skills/new-project/references/CLAUDE-md-snippet.md` into your project's `CLAUDE.md`.

**Shipping without hosting.** A class project needs no deploy: the build under test is the app started locally from the committed HEAD. What it does need is a commit. `gen_stories.py --set US-01=LIVE` refuses a modified or untracked file outside the artifacts and `.qa/` (`git status --porcelain --untracked-files=all`; a rename counts its source, a changed submodule counts, and so does an edit to a file marked assume-unchanged or skip-worktree), a missing or failing done-gate report for HEAD (its `sha` must be a commit id: `"HEAD"` or a branch name is refused), and a story whose story-verifier report does not name the build at HEAD on its `Commit: <sha>` line.

**After a ship.** Once a story is LIVE and the gates are current on HEAD, the detector reports stage 8 and lists the open work: stories not LIVE yet, `FOLLOW-UP (blocks US-xx)` tasks (tickets from `ship` or `bug-to-story`, which do not hold stage 4 open), and `OPEN-FEEDBACK: <why>` asks (bug reports with no story yet, which do not send the project back to stage 2). A code change after the gate, committed or not, sends it back to stage 6.

## Install one item on its own

Every skill in this plugin is self-contained: the scripts, templates and references it runs or copies live inside its own folder and are addressed as `${CLAUDE_SKILL_DIR}/...`. So you can copy one skill folder into `.claude/skills/<name>/` (one project) or `~/.claude/skills/<name>/` (all projects) without the rest of the plugin.

| Item | On its own? | Notes |
|---|---|---|
| `sdlc`, `gather-requirements`, `write-prd`, `write-workplan`, `parallel-lanes`, `ship` | standalone | Each carries its own copy of `scripts/sdlc_stage.py` and its helper `scripts/gen_stories.py` |
| `new-project` | standalone | Carries `scripts/new_project.py`, `scripts/gen_stories.py` (copied to `tools/` at the project root), `scripts/sdlc_stage.py`, all of `templates/` and `references/CLAUDE-md-snippet.md` |
| `bug-to-story` | standalone | Runs only the project's own `tools/gen_stories.py`, so it ships no files |
| `prd-critic`, `story-verifier` agents | standalone | Copy the `.md` into `.claude/agents/` or `~/.claude/agents/`. Neither runs a plugin script, so neither needs a skill |
| SessionStart stage hint | plugin only | Hooks need the plugin's `hooks/hooks.json` |

When run on their own, the skills are named `sdlc`, `write-prd` and so on, without the `foundry-sdlc:` prefix.

**Single source of truth.** Files used by several skills have one canonical copy and byte-identical copies in the other skills, listed in `vendor.json` (copy path: canonical path). `scripts/sdlc_stage.py` and `scripts/gen_stories.py` stay at the plugin root because the hook runs them there. The CLAUDE.md snippet's canonical copy is in `new-project`. Edit the canonical file, then re-copy it: `scripts/tests/test_layout.py` fails when a copy drifts.

## Items

### Skills

Invoke a skill by asking in plain words, for example "write the PRD", or by name: `/foundry-sdlc:write-prd`.

| Skill | What it does | Maturity |
|---|---|---|
| `sdlc` | The router. Stage map, which artifact and which skill or agent each stage uses, how to detect the current stage, the single-session build path, and the stage-6 battery ("check that it really works end to end") | verified |
| `new-project` | Scaffolds the artifact set from its `templates/`, compiles `stories.json` from the new PRD, and writes `tools/gen_stories.py` and the CI check at the project root, plus `.foundry/generated.json` (each file it wrote, with its SHA-256) so the `foundry-guardrails` verify-before-done hook does not count the scaffold as an untested code edit. An older `tools/gen_stories.py` is refreshed, with a one-line diff summary. Derives the name from the folder when none is given | verified |
| `gather-requirements` | Verbatim asks with R-ids and sources, a DECISIONS table, and an "Already exists" audit before the PRD | verified |
| `write-prd` | The PRD with inline `**US-01. Title.**` stories and observable criteria. Compiles stories.json, runs the prd-critic, fills "Addressed critiques", and on the human's yes records a dated `PRD approved` D-row and stops | verified |
| `write-workplan` | Task table (Id, Task, Owner with model, effort and review tier by blast radius, Deps, Status), milestones, "Blocked on human" | verified |
| `parallel-lanes` | One git worktree and one agent per set of WORKPLAN task ids, launched with the Agent tool's `isolation: "worktree"`; a lane registry (`.git/foundry-lanes.json`) that `foundry-guardrails` worktree-guard reads; a file-ownership check for "can these run at the same time"; the lane brief; merge back with task and story bookkeeping. Also the single-session path. Either way each task goes `DONE <date>: commit <sha>` and its stories BUILT as it lands | verified |
| `ship` | The ship ritual: commit, then done gate, persona testers, one story-verifier per story, design critique and a11y on that commit (local or hosted), at most 3 agents at a time against one server, all in the foreground; server pid and logs in `.qa/run/`, stopped by PID; LIVE only through the guarded `--set`; failures ticketed as FOLLOW-UP tasks, and leftover tasks turned into FOLLOW-UP tickets with `sdlc_stage.py --mark-follow-ups`; changelog; "go try X" | beta |
| `bug-to-story` | Every bug report (also "a classmate says X is broken") becomes an R-id (`OPEN-FEEDBACK: not reproduced` until it is storied), a story criterion, a failing regression test, a task, a committed fix routed back through the gates, and a changelog line. Usage gates, with graduation decided by a human | verified |

### Agents

| Agent | What it does | Maturity |
|---|---|---|
| `prd-critic` | Adversarial PRD review in a fresh context. Returns numbered critiques (C1..) with severity, location and a suggested fix. Read-only: never rewrites the PRD | verified |
| `story-verifier` | Checks one story on the build under test (deployed or local) from its criteria, the URL and screenshots only. One per story, before anything is marked LIVE. Returns PASS, FAIL or INCONCLUSIVE per criterion with evidence, under a `Commit: <sha>` first line, as text: the calling session saves it to `.qa/verify/<id>.md` verbatim (Claude Code refuses a subagent's Write of a report file). Never reads the builder's claims | verified |

Use them by asking, for example "Use the prd-critic agent on product/PRD.md", or let the `write-prd` and `ship` skills call them.

### Hook

| Hook | What it does | Maturity |
|---|---|---|
| SessionStart stage hint | Runs `sdlc_stage.py --hook`. If the project has a `PRD.md` or `REQUIREMENTS.md` (in the root, `product/` or `docs/product/`), it prints two lines: the current stage and the failing exit check. Silent otherwise. It never blocks a session | verified |

### Scripts

| Script | What it does | Maturity |
|---|---|---|
| `scripts/gen_stories.py` (canonical; copied into each skill that runs the detector) | Compiles PRD stories into `stories.json`, shape `{"stories": [...]}` (contract C1, shared with `foundry-qa`). `--check` exits 1 if the file is stale (or the old bare-array format), a story has no criteria, an id is duplicated, or a status is invalid. Regenerating keeps `status`, `notes`, `evidence`, a `qa` block, extra keys and any meta the PRD does not set. `--set US-01=LIVE --evidence <path>` refuses LIVE unless the tree is committed (no modified or untracked file outside the artifacts and `.qa/`), the done-gate report says exit 0 for HEAD, and the story's verifier report names HEAD, and records `commit:<sha>`. `--version` prints its version stamp; `--refresh-tools <root>` replaces an older `<root>/tools/gen_stories.py` (the project's own copy, which never updates itself) with this one and prints a one-line diff summary | verified |
| `skills/new-project/scripts/new_project.py` | Scaffolds the artifact set, compiles `stories.json`, writes `tools/` and `.github/workflows/stories.yml` at the project root. Never overwrites without `--force` | verified |
| `scripts/sdlc_stage.py` (canonical; used by the hook, copied into each skill that runs it) | Reports the current stage from the files on disk (`--json` for machines, `--hook` for the SessionStart hook). Stage 2 needs every R-id STORIED, OPEN-FEEDBACK, or `DROPPED (D-xx)` / `PARTIAL (D-xx)`, and a dated `PRD approved` D-row; stage 4 needs every task DONE with a sha, PR or URL, PARKED or FOLLOW-UP; stage 6 needs a committed tree, `.qa/done-gate/last.json` with exit 0 for HEAD and a `.qa/verify/<id>.md` naming HEAD per story not yet LIVE; stage 7 needs every LIVE story to carry `commit:<sha>` evidence; after a ship it reports stage 8 with the open work listed. It notes "project tools out of date" when the project's `tools/gen_stories.py` differs from its own copy. `--mark-follow-ups` turns open tasks that name a story not yet LIVE into `FOLLOW-UP (blocks US-xx)` after a partial ship | verified |

### Templates and references

All templates live in `skills/new-project/templates/`, since only the scaffolder uses them.

| File | Purpose | Maturity |
|---|---|---|
| `skills/new-project/templates/REQUIREMENTS.md` | Sources, verbatim asks (R-01..), "Already exists" audit, constraints, open questions | verified |
| `skills/new-project/templates/DECISIONS.md` | Verbatim human decisions with what each one authorizes, and pending questions with a recommendation | verified |
| `skills/new-project/templates/PRD.md` | Short version, user, metrics, principles, scope, stories, architecture, rollout with "used fully" gates, risks, Appendix A (addressed critiques), Appendix B (push back) | verified |
| `skills/new-project/templates/WORKPLAN.md` | Status block, blast-radius tiers, Next up, milestones, task table, Blocked on human, Parked | verified |
| `skills/new-project/templates/stories.schema.json` | JSON Schema for stories.json: `{"stories": [{id, title, acceptance[], surfaces[], devices[], status, waits_on[], covers[], notes, evidence[], optional qa}]}` | verified |
| `skills/new-project/templates/done-journey.yaml` | Byte-identical copy of `foundry-qa`'s canonical `skills/done-gate/templates/done-journey.yaml` (contract C2): `name`, `base_url`, `devices`, `stories`, optional `auth`, `steps`, `assertions`, `screenshot`. A test checks it matches and passes `done_gate.py --validate` | verified |
| `skills/new-project/templates/stories-ci.yml` | GitHub Actions job that runs `python3 tools/gen_stories.py --prd <PRD> --out <stories> --check`; the scaffolder fills in the paths | new |
| `skills/new-project/templates/CHANGELOG.md` | One dated heading per ship, one bullet per user-visible change, with evidence | verified |
| `skills/new-project/templates/README.md` | Project README that indexes the artifact set | verified |
| `skills/new-project/references/CLAUDE-md-snippet.md` (copied into `sdlc`) | Always-on norms to paste into a project CLAUDE.md: every bug report through `bug-to-story`, root cause first, surgical changes, never "done" without passing gates on a committed SHA, the 4-tier blast-radius table, reuse before build | verified |

**What the maturity labels mean.** The labels come from our test runs on 2026-10-28, recorded with what we ran in [`evidence/evidence.json`](../../evidence/evidence.json). "verified" means the item's main path passed a live end-to-end run in a real Claude Code session with no known major defect left on it. "beta" means it works with known gaps (`ship`: marking leftover open tasks `FOLLOW-UP` and refreshing an old `tools/gen_stories.py` are unit-tested only, not yet run in a live ship). "new" means little or no live testing (`stories-ci.yml` has not run in GitHub Actions yet). A script or template carries the label of the skill that ships it. Most items are generalized from a workflow, format or tool that runs in production in our harness today. Please report problems.

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
