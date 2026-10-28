---
name: sdlc
description: The router for building software 0 to 1 with agents. Maps the 8 stages (scaffold, requirements, PRD and stories, workplan, execute, code QA, visual QA, ship, feedback) to the artifact each one produces, the skill or agent that does it, and the gate that ends it, and works out which stage a project is in from the files that exist. Use when someone says "build me an app", "start a new project", "what's next on this project", "where are we", "what stage are we in", "take this from idea to launch", "plan this feature", or before starting any multi-step build.
---

# The Foundry SDLC: stage map and router

Eight stages, in order. Each one produces a file and ends at a gate. **Never skip a gate.** A stage is finished only when its exit check passes. Agents are fast, so the slow part is fixing work built on a wrong foundation. The gates are there to stop that.

## Step 1: find out where the project is

Run the stage detector from the project root. It reads the artifacts and reports the first stage whose exit check fails:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .
```

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" . --json
```

The detector ships inside this skill (`scripts/sdlc_stage.py`, with its helper `scripts/gen_stories.py`), so it works whether the skill came with the plugin or was copied on its own. A project scaffolded by `new-project` also has its own copy of `tools/gen_stories.py`.

It looks for the artifact set in `.`, then `product/`, then `docs/product/`. With this plugin enabled, a SessionStart hook prints the same verdict in two lines whenever the project has a `PRD.md` or `REQUIREMENTS.md`.

If no artifacts exist, you are in stage 0. Use the `new-project` skill.

## Step 2: do that stage, and only that stage

| # | Stage | Artifact | Do it with | Exit gate (what must be true to move on) |
|---|---|---|---|---|
| 0 | Scaffold | README, REQUIREMENTS, DECISIONS, PRD, WORKPLAN, CHANGELOG, stories.json, done-journey.yaml | `new-project` skill (`scripts/new_project.py`) | All files exist |
| 1 | Gather requirements | `REQUIREMENTS.md`, `DECISIONS.md` | `gather-requirements` skill | Every ask is verbatim with an R-id and a source. The "Already exists" audit is filled. No `TODO` markers remain |
| 2 | PRD + user stories | `PRD.md`, `stories.json` | `write-prd` skill, then the `prd-critic` agent | Stories have observable criteria. Critiques addressed in Appendix A. `gen_stories.py --check` exits 0. Every R-id is covered or dropped |
| 3 | Workplan | `WORKPLAN.md` | `write-workplan` skill | Task table with owner, model, effort and review tier for each task. Milestones. "Blocked on human" list |
| 4 | Execute | code, one branch per lane | `parallel-lanes` skill | Every task is DONE or PARKED, with evidence |
| 5 | Code QA | tests, CI run | `foundry-qa` plugin: `regression-check`. Your CI | Each change has a test. The blast radius has been checked. CI is green |
| 6 | Visual QA with example users | `done-journey.yaml`, screenshots, verifier reports | `foundry-qa`: `done-gate`, then `persona-tester` per device. Then this plugin's `story-verifier` agent. Then `foundry-design`: `design-critique`, `ui-reviewer`. Native apps: `foundry-devices` | Done gate exit 0 on the deployed build. Every criterion PASS (INCONCLUSIVE is not a pass) |
| 7 | Ship | `CHANGELOG.md`, story status LIVE | `ship` skill | Gate passed, then changelog, then the users are told what to try. Never in the other order |
| 8 | Feedback | new stories + failing regression tests | `bug-to-story` skill. `foundry-evals` for agent features | Each bug has a story and a test that fails before the fix. A human decides when a feature graduates |

Stage 8 loops back. A bug becomes a story in the PRD (stage 2), a task (stage 3), and a fix (stage 4), and it goes back through every gate.

## Rules that apply at every stage

1. **Never skip a gate.** If a gate cannot run (no deploy, no browser, no credentials), say so and stop. Report the stage as blocked and add the blocker to "Blocked on human" in WORKPLAN.md. Never write "done" around a gate that did not run.
2. **The PRD is the single source of stories.** Edit stories in `PRD.md`, then run `gen_stories.py`. Never hand-edit a title or a criterion in `stories.json`. Only `status`, `notes` and `evidence` are edited there.
3. **Verbatim before paraphrase.** Requests go into REQUIREMENTS.md in the requester's words, and decisions go into DECISIONS.md the same way. Agents propose. Humans decide.
4. **Reuse before build.** Fill the "Already exists" audit before the PRD. Check it again before each lane starts.
5. **Independent judges.** The agent that wrote the PRD does not critique it, and the agent that built a story does not verify it. Use `prd-critic` and `story-verifier`. Each runs in a fresh context and never sees the builder's claims.
6. **Effort and review scale with blast radius**, not habit. See the 4-tier table in `${CLAUDE_SKILL_DIR}/references/CLAUDE-md-snippet.md`, and paste that snippet into the project's CLAUDE.md.
7. **Status words are exact.** NOT_BUILT, BUILT (code exists, not verified), PARTIAL (deployed, some criteria fail), LIVE (deployed and every criterion verified), PARKED. "Done" means LIVE.

## Which companion plugin does what

| Plugin | Use it for |
|---|---|
| `foundry-sdlc` (this one) | The stage skills, templates, `gen_stories.py`, `sdlc_stage.py`, `prd-critic`, `story-verifier` |
| `foundry-guardrails` | Hooks that enforce the rules: worktree isolation, verify before done, no secrets in commits |
| `foundry-qa` | `web-qa`, `persona-tester`, `done-gate` (runs `done-journey.yaml`), `regression-check` |
| `foundry-design` | `design-critique` (subtract-only gate), `ui-reviewer` (rubric review from screenshots) |
| `foundry-devices` | iOS, Android, Windows and macOS QA for native or desktop builds |
| `foundry-evals` | Evals for agent and LLM features: the "test" for things that are not deterministic |

## Example: a fresh session on an existing project

1. Run `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .`. Suppose it prints `Current stage: 3 Workplan` and the check says `no task table`.
2. Load the `write-workplan` skill. Read PRD.md and stories.json, then write the table.
3. Run `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` again. When it says stage 4, load `parallel-lanes`.
4. Tell the human one line: the stage you finished, the gate that passed, and what is next.
