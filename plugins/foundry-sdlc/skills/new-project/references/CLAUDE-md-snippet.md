# CLAUDE.md snippet: always-on engineering norms

Paste everything below the line into your project's `CLAUDE.md`. Plugin skills load only when they are needed. These norms have to apply to every turn, so they belong in CLAUDE.md, which Claude Code loads at session start. (A `CLAUDE.md` inside a plugin is not loaded, which is why this is a snippet you paste.)

---

## How we build (foundry-sdlc)

This project follows the Foundry SDLC: scaffold, requirements, PRD and stories, workplan, execute, code QA, visual QA, ship, feedback. To find the current stage, run the `sdlc` skill (`foundry-sdlc:sdlc` when it came with the plugin). It runs the stage detector, `scripts/sdlc_stage.py`, that ships inside the skill. **Never skip a gate.** If a gate cannot run, say so and stop.

### Bug reports go through bug-to-story
- **Every bug report or failed check goes through the `bug-to-story` skill** (`foundry-sdlc:bug-to-story`): "a classmate says X is broken", "a user can't Y", "handle this bug", a verifier or persona FAIL. In order: record the reporter's words as a new R-id in REQUIREMENTS.md, reproduce, add or extend a story criterion in PRD.md, write the failing test first, add a WORKPLAN task, fix, commit, rerun the gates, and log it in CHANGELOG.md. Do not fix a reported bug outside that skill, and never leave a fix uncommitted.
- A report you cannot reproduce still gets its R-id (status `OPEN-FEEDBACK: not reproduced`) and an open question saying what you tried.

### Root cause first
- Reproduce the problem before you change code. Never fix a bug you have not seen.
- Ask "why" until you reach the actual cause, a line of code or a wrong assumption. Fix that, not the symptom. A retry, a sleep, a broad try/except or a special case for one input is a bandaid. Use one only as a labeled stopgap, with a task to find the cause.
- Every fix adds a regression test that fails before the fix and passes after.

### Surgical changes
- Make the smallest change that fully solves the task. Do not refactor, rename or reformat code you were not asked to touch.
- If you find another problem, write it down (in your report, or as a task in WORKPLAN.md). Do not fix it in the same change.
- Before you edit a shared file (anything other modules import), list its consumers and check each one. The `foundry-qa:regression-check` skill does this.

### Never say "done" without a passing gate
- "Done" means every stage-6 gate passed on a **committed SHA**: the done-gate journey exited 0, persona-tester, a11y-check and design-critique found no blocking failure, and the story-verifier marked every criterion PASS. INCONCLUSIVE is not a pass. The ship skill runs these.
- The build under test is the committed HEAD: the deployed URL when there is hosting, or the app started locally from that commit when there is none (a class project). Hosting is optional; a commit is not.
- Without that, report the real state with its evidence: "built, tests pass, not committed", or "committed at 3f2a9c1, done gate not run because <reason>".
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
- Stories live only in `PRD.md` (`**US-01. Title.**` plus numbered criteria). `stories.json` is compiled from it. From the project root: `python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json` (drop `product/` when the artifacts are at the root; add `--check` in CI). Never hand-edit a story's title or criteria there.
- Story status: NOT_BUILT, BUILT (code exists, not verified), PARTIAL (a gate failed or was inconclusive), LIVE (every gate passed on a committed SHA; set it with `tools/gen_stories.py ... --set US-01=LIVE --evidence <report>`, which refuses otherwise), PARKED.
- Every WORKPLAN task goes to `DONE <date>: commit <sha>` as its commit lands, whether it was built in a lane or in this session. A ticket written by ship or bug-to-story is `FOLLOW-UP (blocks US-xx)` until someone starts it.
- Ask status in REQUIREMENTS.md: OPEN, STORIED, LIVE, `DROPPED (D-xx)`, `PARTIAL (D-xx): <what survives>`, and `OPEN-FEEDBACK: <why>` for a bug report with no story yet. After a ship, FOLLOW-UP tasks and OPEN-FEEDBACK asks are stage 8 open work.
- Requests and human decisions are recorded verbatim, in `REQUIREMENTS.md` and `DECISIONS.md`. Agents propose. Humans decide.

### Parallel work
- One lane per set of WORKPLAN task ids, one git worktree per lane (Agent tool lanes use `isolation: "worktree"`). A lane agent edits only inside its own worktree, and never in the main checkout. See the `foundry-sdlc:parallel-lanes` skill.
