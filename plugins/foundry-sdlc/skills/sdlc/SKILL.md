---
name: sdlc
description: The router for building software 0 to 1 with agents. Maps the 8 stages (scaffold, requirements, PRD and stories, workplan, execute, code QA, visual QA, ship, feedback) to the artifact each one produces, the skill or agent that does it, and the gate that ends it, and works out which stage a project is in from the files that exist. It is also the entry point for the stage-6 QA battery (done gate, persona testers, story verifiers, design and accessibility checks). Use when someone says "build me an app", "start a new project", "what's next on this project", "where are we", "what stage are we in", "take this from idea to launch", "plan this feature", "check that it really works end to end", "QA everything before we call it done", or before starting any multi-step build.
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

The detector ships inside this skill (`scripts/sdlc_stage.py`, with its helper `scripts/gen_stories.py`), so it works whether the skill came with the plugin or was copied on its own. A project scaffolded by `new-project` also has `tools/gen_stories.py` at its project root; every skill runs it from there as `python3 tools/gen_stories.py --prd <dir>/PRD.md --out <dir>/stories.json`.

It looks for the artifact set in `.`, then `product/`, then `docs/product/`. With this plugin enabled, a SessionStart hook prints the same verdict in two lines whenever the project has a `PRD.md` or `REQUIREMENTS.md`.

If no artifacts exist, you are in stage 0. Use the `new-project` skill.

## Step 2: do that stage, and only that stage

| # | Stage | Artifact | Do it with | Exit gate (what must be true to move on) |
|---|---|---|---|---|
| 0 | Scaffold | README, REQUIREMENTS, DECISIONS, PRD, WORKPLAN, CHANGELOG, stories.json, done-journey.yaml | `new-project` skill (`scripts/new_project.py`) | All files exist |
| 1 | Gather requirements | `REQUIREMENTS.md`, `DECISIONS.md` | `gather-requirements` skill | Every ask is verbatim with an R-id and a source. The "Already exists" audit is filled. No `TODO` markers remain |
| 2 | PRD + user stories | `PRD.md`, `stories.json` | `write-prd` skill, then the `prd-critic` agent | Stories have observable criteria. Critiques addressed in Appendix A. `gen_stories.py --check` exits 0. Every R-id is STORIED or DROPPED (citing a D-id). DECISIONS.md has the human's dated "PRD approved" row |
| 3 | Workplan | `WORKPLAN.md` | `write-workplan` skill | Task table with owner, model, effort and review tier for each task. Milestones. "Blocked on human" list |
| 4 | Execute | code, commits | `parallel-lanes` skill (lanes, or its single-session path) | Every task is PARKED, or `DONE <date>: commit <sha>` |
| 5 | Code QA | tests, CI run | `foundry-qa` plugin: `regression-check`. Your CI | Each change has a test. The blast radius has been checked. CI is green |
| 6 | Visual QA with example users | `.qa/done-gate/last.json`, `.qa/verify/<id>.md`, screenshots | The stage-6 battery below (the `ship` skill runs it in order) | Done-gate report exit 0 for git HEAD. A verifier report for every story |
| 7 | Ship | `CHANGELOG.md`, story status LIVE | `ship` skill | Every story LIVE (set by `gen_stories.py --set`, which records the SHA) or PARTIAL with a ticket, then changelog, then the users are told what to try |
| 8 | Feedback | new stories + failing regression tests | `bug-to-story` skill. `foundry-evals` for agent features | Each bug has a story and a test that fails before the fix. A human decides when a feature graduates |

### Stage 4 without lanes (one session builds it all)

That is fine for a small app. Commit each task as it lands, and set its WORKPLAN row to `DONE <date>: commit <sha>` in the same step. Never leave a built task at PARTIAL or NOT STARTED: the detector stays at stage 4 until every task is DONE or PARKED.

### The stage-6 battery

When the user asks whether it really works ("check it end to end", "does it work on a phone", "QA it before we call it done"), or the detector says stage 6, run all five, on the **committed HEAD**. Hosting is optional: with no deploy, the build under test is the app started locally from that commit.

1. `foundry-qa:done-gate` on `done-journey.yaml` (writes `.qa/done-gate/last.json`).
2. `foundry-qa` `persona-tester` agent, once per device in the stories' `devices`.
3. This plugin's `story-verifier` agent, one per story, fresh context, verdict saved to `.qa/verify/<id>.md`.
4. `foundry-design:design-critique` on the changed screens.
5. `foundry-qa:a11y-check` on the stories' surfaces.

Wait for all of them in the foreground. A story with any FAIL or INCONCLUSIVE stays PARTIAL. Then continue with the `ship` skill. Native apps add the `foundry-devices` agents.

Stage 8 loops back. A bug becomes a story in the PRD (stage 2), a task (stage 3), and a fix (stage 4), and it goes back through every gate.

## Rules that apply at every stage

1. **Never skip a gate.** If a gate cannot run (no browser, no credentials), say so and stop. Report the stage as blocked and add the blocker to "Blocked on human" in WORKPLAN.md. Never write "done" around a gate that did not run. No hosting is not a blocker: run the gates on the committed HEAD served locally.
2. **Stop at a human gate.** When the human approves the PRD, record their words in DECISIONS.md and stop. Start the next stage only when they ask for it.
3. **The PRD is the single source of stories.** Edit stories in `PRD.md`, then run `gen_stories.py`. Never hand-edit a title or a criterion in `stories.json`. Only `status`, `notes` and `evidence` change there, and a status changes through `gen_stories.py --set`.
4. **Verbatim before paraphrase.** Requests go into REQUIREMENTS.md in the requester's words, and decisions go into DECISIONS.md the same way. Agents propose. Humans decide.
5. **Reuse before build.** Fill the "Already exists" audit before the PRD. Check it again before each lane starts.
6. **Independent judges.** The agent that wrote the PRD does not critique it, and the agent that built a story does not verify it. Use `prd-critic` and `story-verifier`. Each runs in a fresh context and never sees the builder's claims.
7. **Effort and review scale with blast radius**, not habit. See the 4-tier table in `${CLAUDE_SKILL_DIR}/references/CLAUDE-md-snippet.md`, and paste that snippet into the project's CLAUDE.md.
8. **Status words are exact.** NOT_BUILT, BUILT (code exists, not verified), PARTIAL (a gate failed or was inconclusive), LIVE (every gate passed on a committed SHA), PARKED. "Done" means LIVE.

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
