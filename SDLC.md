# The Foundry SDLC

How we take software from an idea to something people use, with agents doing most of the building. Eight stages, after a stage 0 scaffold. Each stage produces a file and ends at a gate. **Never skip a gate.** Agents are fast, so the slow part is fixing work built on a wrong foundation. The gates are there to stop that.

This document is the human-readable version of the `foundry-sdlc` plugin. The plugin's `sdlc` skill holds the same table, and `sdlc_stage.py` checks the same exit gates from the files on disk. If this page and the plugin ever disagree, the plugin's skills are the source of truth and this page has a bug.

## One screen

```
 0 Scaffold ---> 1 Requirements ---> 2 PRD + stories ---> 3 Workplan
  new-project     gather-requirements  write-prd             write-workplan
                                       + prd-critic agent
                                                                 |
                                                                 v
 8 Feedback <--- 7 Ship <--- 6 Visual QA <--- 5 Code QA <--- 4 Execute
  bug-to-story    ship        done-gate          regression-check  parallel-lanes
  foundry-evals   changelog   persona-tester     your CI           (one worktree
     |            LIVE        story-verifier                        per task)
     |                        design-critique
     |                        ui-reviewer
     |                        foundry-devices
     |
     +--> a bug becomes a story (2), a task (3), a fix (4), and goes back through every gate

 Hooks run the whole time (foundry-guardrails): secret-guard, destructive-guard,
 worktree-guard, verify-before-done, stale-write-guard, ship-stop.
```

Find where a project is: ask Claude "what stage are we in?". Inside Claude Code the `sdlc` skill runs its own copy of the detector. By hand, run it from the installed skill folder, from the project root:

```bash
python3 ~/.claude/skills/sdlc/scripts/sdlc_stage.py .
```

Use `.claude/skills/sdlc/` instead if you copied the skill into the project, or `plugins/foundry-sdlc/skills/sdlc/scripts/sdlc_stage.py` from a clone of this repo. The script is standard library only, so any copy works. The detector looks for the artifacts in `.`, then `product/`, then `docs/product/`, and reports the first stage whose exit check fails. With `foundry-sdlc` enabled, a SessionStart hook prints the same verdict when the project has a `PRD.md` or `REQUIREMENTS.md`.

## The stages

Template and script paths are relative to the `new-project` skill folder (`plugins/foundry-sdlc/skills/new-project/`). The skill copies the templates into your project.

### 0. Scaffold

- **Goal:** the project has the full artifact set, so every later stage has a place to write.
- **Inputs:** an empty or existing repo.
- **Artifact:** README.md, REQUIREMENTS.md, DECISIONS.md, PRD.md, WORKPLAN.md, CHANGELOG.md, stories.json, stories.schema.json, done-journey.yaml, plus `tools/gen_stories.py`. Templates: `templates/*`.
- **Gate:** all files exist. `stories.json` is compiled from the new PRD, so `python3 tools/gen_stories.py --check` passes right away.
- **Tool:** `new-project` skill (`scripts/new_project.py <dir> [--name "Project Name"]`; without `--name` the name comes from the folder). `tools/gen_stories.py` and `.github/workflows/stories.yml` go to the project root (the git root).

### 1. Gather requirements

- **Goal:** know exactly what was asked, by whom, and what already exists.
- **Inputs:** conversations, emails, interviews, existing code and tools.
- **Artifact:** `REQUIREMENTS.md` (template `templates/REQUIREMENTS.md`) with each ask verbatim and an R-id (R-01, R-02...) plus its source and date, and `DECISIONS.md` (template `templates/DECISIONS.md`) with human decisions recorded verbatim.
- **Gate:** every ask is verbatim with an R-id and a source. The "Already exists" audit is filled. No `TODO` markers remain.
- **Tool:** `gather-requirements` skill.

### 2. PRD and user stories

- **Goal:** a PRD whose stories can be checked by someone who did not write them.
- **Inputs:** REQUIREMENTS.md, DECISIONS.md.
- **Artifact:** `PRD.md` (template `templates/PRD.md`) with inline stories in the form `**US-01. Title.**` followed by numbered, observable acceptance criteria, and `stories.json` compiled from it (schema `templates/stories.schema.json`). Never hand-edit a title or a criterion in stories.json; only `status`, `notes` and `evidence` are edited there.
- **Gate:** stories have observable criteria. The `prd-critic` agent's critiques are addressed in Appendix A. `gen_stories.py --check` exits 0. Every R-id's Status in REQUIREMENTS.md is `STORIED` (or `LIVE`), or `DROPPED` citing the D-id that dropped it. DECISIONS.md has the human's dated `PRD approved` row in their own words. Approval is never inferred; after it, stop until the human asks for the workplan.
- **Tools:** `write-prd` skill, then the `prd-critic` agent (fresh context, read-only, never rewrites the PRD). For UI stories, `foundry-design`'s `ui-ux-spec` skill turns a story into a buildable spec.

### 3. Workplan

- **Goal:** a plan that agents can execute in parallel and humans can read in one minute.
- **Inputs:** PRD.md, stories.json.
- **Artifact:** `WORKPLAN.md` (template `templates/WORKPLAN.md`): a task table `Id | Task | Owner | Deps | Status` where Owner names the model, effort and review tier, plus milestone checkboxes (`- [ ] M1.1 title`), "Next up", and "Blocked on human".
- **Gate:** every task has an owner, model, effort and review tier. Milestones exist. The "Blocked on human" list exists.
- **Tool:** `write-workplan` skill. Review tier comes from the blast-radius table below.

### 4. Execute

- **Goal:** build each task in isolation, then merge it back.
- **Inputs:** WORKPLAN.md.
- **Artifact:** code, one branch per lane (`lane/<task-id>-<slug>`), one worktree per lane (`../<repo>-lanes/<task-id>`), one PR per lane.
- **Gate:** every task is PARKED, or DONE with evidence in its Status cell (`DONE 2026-11-03: commit 3f2a9c1`, a PR `#12` or a URL).
- **Tools:** `parallel-lanes` skill. Hooks: `worktree-guard` (a lane never edits the main checkout), `secret-guard`, `destructive-guard`, `stale-write-guard` (denies a whole-file Write over uncommitted changes this session did not make; `FOUNDRY_STALE_WRITE_ENFORCE=0` only warns), `ship-stop` (keeps working until the milestone is checked). Builder helpers: `foundry-builder-kit` (auth, secrets, LLM routing, tmux).

### 5. Code QA

- **Goal:** the code does what the tests say, and nothing downstream broke.
- **Inputs:** the merged branches.
- **Artifact:** tests and a CI run.
- **Gate:** each change has a test. The blast radius of shared changes was checked. CI is green.
- **Tools:** `foundry-qa`'s `regression-check` skill, your CI, and the `verify-before-done` hook (no stopping after code edits without a test run, no push or deploy without verification). For LLM features, `foundry-evals` is the test. The stage detector cannot see this stage from files, so CI is the evidence.

### 6. Visual QA with example users

- **Goal:** the build under test works for real kinds of users on the devices they use.
- **Inputs:** a commit, and the build of that commit: a deployed URL serving it, or, with no hosting, the app started locally from the committed HEAD (record that once as a D-row; no deploy is needed). Plus stories.json and persona files.
- **Artifact:** `done-journey.yaml` (template `templates/done-journey.yaml`), the done gate's `.qa/done-gate/last.json` (`sha`, `exit`, `journey`, `time`), one story-verifier report per story (`.qa/verify/<id>.md`), screenshots, persona reports.
- **Gate:** `last.json` says exit 0 for git HEAD (or for a commit whose only later changes are artifact files), and every story that is not PARKED has a verifier report or evidence. INCONCLUSIVE is not a pass.
- **Signed-in apps:** give the journey an `auth:` block, or pass `--storage-state`, `--header` or `--auth` to the foundry-qa scripts. `qa_session.py login` saves a storage state once.
- **Tools, in this order:** `foundry-qa`'s `done-gate`, then `persona-tester` on each device, then `foundry-sdlc`'s `story-verifier` agent per story, then `foundry-design`'s `design-critique` and `ui-reviewer`. Native apps: `foundry-devices` (iOS, Android, Windows, macOS) and `foundry-iphone-mirror` for a real iPhone.

### 7. Ship

- **Goal:** users know what they can now do, and the record says what is LIVE and why.
- **Inputs:** a passing stage 6.
- **Artifact:** `CHANGELOG.md` (template `templates/CHANGELOG.md`) with a dated entry, and story status `LIVE` with `evidence` in stories.json. Set LIVE only with `tools/gen_stories.py --set US-01=LIVE --evidence .qa/verify/US-01.md`: it refuses a dirty tracked tree, a missing or failing done-gate report for HEAD, and a story with no evidence, and it appends `commit:<sha>` to the story's evidence.
- **Gate:** every story that is not PARKED is LIVE with `commit:<sha>` evidence, and the changelog has a dated entry. Order: the gate passed, then the changelog, then the users were told what to try. Never in the other order.
- **Tool:** `ship` skill. Status words are exact: NOT_BUILT, BUILT (code exists, not verified), PARTIAL (deployed, some criteria fail), LIVE (deployed and every criterion verified), PARKED. "Done" means LIVE.

### 8. Feedback

- **Goal:** every bug makes the system stronger, and features graduate on evidence.
- **Inputs:** bug reports, usage data, user replies.
- **Artifact:** new R-ids and stories (or criteria) in the PRD, and regression tests that fail before the fix.
- **Gate:** each bug has a story and a test that fails before the fix. A human decides when a feature graduates.
- **Tools:** `bug-to-story` skill. `foundry-evals` (`run-eval`, `hillclimb`) for agent features. Loops back to stage 2.

## Rules that apply at every stage

1. **Never skip a gate.** If a gate cannot run (no browser, no credentials), say so and stop, and add the blocker to "Blocked on human". No hosting is not a blocker: ship the committed HEAD locally.
2. **The PRD is the single source of stories.**
3. **Verbatim before paraphrase.** Agents propose. Humans decide.
4. **Reuse before build.** Fill the "Already exists" audit before the PRD, and check it again before each lane.
5. **Independent judges.** The agent that wrote the PRD does not critique it, and the agent that built a story does not verify it.
6. **Effort and review scale with blast radius**, not habit.
7. **Status words are exact.**

## The four layers of QA (plus design review)

Each layer catches what the one before it cannot. Passing one says nothing about the next.

| Layer | What it is | What it catches | Tool |
|---|---|---|---|
| 1. Code tests | Unit and integration tests in CI, plus a blast-radius check on shared code | Logic bugs, broken contracts, a consumer you forgot | your test runner, `regression-check`, `verify-before-done` hook |
| 2. Deterministic journey gate | A scripted journey (steps and assertions) run with Playwright on desktop, phone and tablet against the build under test: a deploy, after confirming it serves the commit you merged, or the committed HEAD run locally | "Works on my machine", a stale deploy, a page that crashes on phone width | `done-gate` (`done_gate.py`, exit 0 only) |
| 3. Independent story verifier | A fresh-context agent that gets only a story's criteria, the URL and screenshots, never the builder's claims, and returns PASS, FAIL or INCONCLUSIVE per criterion | The builder grading its own homework, criteria the journey does not script | `story-verifier` agent |
| 4. Persona testers across devices | Agents that use the app as a described person (patience, device, goals) on each device in the story's `devices` list | Confusing copy, dead ends, tap targets too small, a flow that is technically correct and still loses people | `persona-tester`, `explorer`, `foundry-devices`, `iphone-driver` |
| Plus: design review | A subtract-only critic and a rubric review from screenshots and code, with a deterministic design gate for objective regressions | Clutter, an extra click, contrast and target-size failures, a second primary button | `design-critique`, `ui-reviewer`, `design_gate.py`, `a11y-check`, `visual-baseline` |

## Review effort scales with blast radius

Choose build effort, review depth, and whether an independent reviewer is needed by what the change can break. Uniform top effort on every task is not thoroughness, it is unmetered spend.

| Review tier | Blast radius |
|---|---|
| Top effort, independent reviewer | Auth, credentials, secrets, payments, anything that sends to real people or spends money, anything irreversible (data deletes, migrations on production), a shared component every feature depends on |
| High | Normal engineering: a new module, a schema change, a page, a change to a live loop's behavior |
| Medium | Mechanical edits, config, cadence changes, test-only work |
| No review agent | Docs, copy, comments, log text. The builder self-checks. A second agent adds nothing |

Building agents run at low or medium effort for normal work, and at high or above only for the top tier. An independent verifier is for the top tier. Below that, the builder's own tests are the verification. This table is also in `plugins/foundry-sdlc/skills/new-project/references/CLAUDE-md-snippet.md`, ready to paste into your CLAUDE.md.

## Already using agent-team-kit?

[ai-foundry-byu/agent-team-kit](https://github.com/ai-foundry-byu/agent-team-kit) by Scott Murff is a project-install kit (via its `install.sh`), not a plugin. Its skills are an equivalent path through much of this framework. Keep using them; add the stages and tools it does not cover.

| Foundry stage | agent-team-kit | This marketplace adds |
|---|---|---|
| 0 Scaffold | `install.sh` (skills, hooks, CLAUDE.md sections, memory pack) | `new-project` artifact set, stage detector |
| 1 Requirements | (inside `spec`) | `gather-requirements`: verbatim R-ids and the Already exists audit |
| 2 PRD + stories | `spec` (`.specs/<slug>/spec.md`, stories, criteria, punch list, stops for approval), `mockup` | `write-prd`, `gen_stories.py`, `prd-critic`, `ui-ux-spec` |
| 3 Workplan | punch list inside `spec` | `write-workplan`: per-task model, effort and review tier, milestones, `ship-stop` hook |
| 4 Execute | `build-spec`, worktree launchers, `merge-worktree`, git guard hooks | `parallel-lanes`, `worktree-guard`, `secret-guard`, `destructive-guard` |
| 5 Code QA | `regression-check` (SvelteKit-pathed) | stack-neutral `regression-check`, `verify-before-done`, `foundry-evals` |
| 6 Visual QA | `ux-critique`, `userflow-map`, walk and crawler specs | `done-gate`, `story-verifier`, `persona-tester`, `foundry-design`, `foundry-devices`, `foundry-iphone-mirror` |
| 7 Ship | `push`, `stage`, `promote`, `remove-flag` (project-coupled, adapt them) | `ship` ritual (gate, then changelog, then tell users) |
| 8 Feedback | `fix-bug` (see also [app-feedback-loop](https://github.com/ai-foundry-byu/app-feedback-loop), MIT) | `bug-to-story`, `hillclimb` |

If you use both, pick one owner per stage so two skills do not fight over the same artifact. A reasonable split: agent-team-kit's `spec` and `build-spec` for stages 2 to 4, and this marketplace's gates for stages 5 to 8.
