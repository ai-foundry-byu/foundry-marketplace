# CLAUDE.md snippet: always-on engineering norms

Paste everything below the line into your project's `CLAUDE.md`. Plugin skills load only when they are needed. These norms have to apply to every turn, so they belong in CLAUDE.md, which Claude Code loads at session start. (A `CLAUDE.md` inside a plugin is not loaded, which is why this is a snippet you paste.)

---

## How we build (foundry-sdlc)

This project follows the Foundry SDLC: scaffold, requirements, PRD and stories, workplan, execute, code QA, visual QA, ship, feedback. To find the current stage, run the `sdlc` skill (`foundry-sdlc:sdlc` when it came with the plugin). It runs the stage detector, `scripts/sdlc_stage.py`, that ships inside the skill. **Never skip a gate.** If a gate cannot run, say so and stop.

### Root cause first
- Reproduce the problem before you change code. Never fix a bug you have not seen.
- Ask "why" until you reach the actual cause, a line of code or a wrong assumption. Fix that, not the symptom. A retry, a sleep, a broad try/except or a special case for one input is a bandaid. Use one only as a labeled stopgap, with a task to find the cause.
- Every fix adds a regression test that fails before the fix and passes after.

### Surgical changes
- Make the smallest change that fully solves the task. Do not refactor, rename or reformat code you were not asked to touch.
- If you find another problem, write it down (in your report, or as a task in WORKPLAN.md). Do not fix it in the same change.
- Before you edit a shared file (anything other modules import), list its consumers and check each one. The `foundry-qa:regression-check` skill does this.

### Never say "done" without a passing gate
- "Done" means the gate passed on the deployed build: the done-gate journey exited 0, and the story-verifier marked every criterion PASS. INCONCLUSIVE is not a pass.
- Without that, report the real state with its evidence: "built, tests pass locally, not deployed", or "deployed, done gate not run because <reason>".
- Never write "should work now". Run it and show the output.

### Reuse before build
- Before writing a new module, helper, component or service, search the repo (`grep -rn`, the README, the "Already exists" table in REQUIREMENTS.md) and check whether a maintained library already does it.
- Extend what exists when it is 80% right. Explain in one line why, if you build new anyway.

### Review effort scales with blast radius
Choose build effort, review depth, and whether an independent reviewer is needed by what the change can break. Do not apply the same level to everything. Uniform top effort on every task is not thoroughness, it is unmetered spend.

| Review tier | Blast radius |
|---|---|
| Top effort, independent reviewer | Auth, credentials, secrets, payments, anything that sends to real people or spends money, anything irreversible (data deletes, migrations on production), a shared component every feature depends on |
| High | Normal engineering: a new module, a schema change, a page, a change to a live loop's behavior |
| Medium | Mechanical edits, config, cadence changes, test-only work |
| No review agent | Docs, copy, comments, log text. The builder self-checks. A second agent adds nothing |

Building agents run at low or medium effort for normal work, and at high or above only for the top tier. An independent verifier is for the top tier. Below that, the builder's own tests are the verification.

### Artifacts and status words
- Stories live only in `PRD.md` (`**US-01. Title.**` plus numbered criteria). `stories.json` is compiled by `tools/gen_stories.py`. Never hand-edit a story's title or criteria there.
- Story status: NOT_BUILT, BUILT (code exists, not verified), PARTIAL (deployed, some criteria fail), LIVE (deployed and every criterion verified), PARKED.
- Requests and human decisions are recorded verbatim, in `REQUIREMENTS.md` and `DECISIONS.md`. Agents propose. Humans decide.

### Parallel work
- One task per lane, one git worktree per lane. A lane agent edits only inside its own worktree, and never in the main checkout. See the `foundry-sdlc:parallel-lanes` skill.
