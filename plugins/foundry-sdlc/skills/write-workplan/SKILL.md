---
name: write-workplan
description: Stage 3 of the Foundry SDLC. Turn the PRD's stories into WORKPLAN.md, a task table (Id | Task | Owner | Deps | Status), where Owner names the model, effort and review tier chosen by blast radius, plus milestone checkboxes and a "Blocked on human" list. Dependencies are explicit so independent tasks run as parallel lanes. Use when someone says "write the workplan", "break this into tasks", "plan the build", "what can run in parallel", "who does what", "make a task list from the PRD", or when sdlc_stage.py reports stage 3.
---

# Stage 3: workplan

The workplan turns stories into work an agent can pick up without asking. It decides three things per task: who does it, how much effort and review it gets, and what has to finish first. The deps column is what makes parallel lanes safe.

## Inputs

`PRD.md` and `stories.json` (they must pass `gen_stories.py --check`), the "Already exists" audit, and DECISIONS.md.

## Procedure

1. **One task per independently mergeable change.** A task usually builds one story, or one shared piece several stories need (a schema, an auth flow, a layout shell). Cite the story ids in the task text: `Build US-04 (applicant list with wait badges)`. If a task would touch more than about 10 files, or takes more than a day, split it.
2. **Shared foundations first.** Repo setup, CI, deploy, data model and auth are tasks that others depend on. Put them at the top with no deps.
3. **Deps.** List the task ids, D-ids or R-ids that must be done first. Be strict: a missing dep causes merge conflicts or rework later. A task with `-` in Deps can start today in its own lane.
4. **Owner = who, model, effort and review tier, chosen by blast radius.** Format: `agent · <model>/<effort> · <review>`, or a human role.

   | Blast radius of the task | Build effort | Review |
   |---|---|---|
   | Auth, credentials, payments, sending to real people, irreversible data changes, a shared component every feature uses | high or top | independent reviewer at top effort |
   | Normal feature: new module, schema change, a page | low to medium | reviewer at high effort |
   | Mechanical: config, rename, test-only | low | reviewer at medium effort |
   | Docs, copy, comments | low | no reviewer (the builder self-checks) |

   Uniform top effort on every task is not thoroughness. It is unmetered spend. Pick a higher tier only where the radius earns it.
5. **Milestones** are user-visible checkpoints, written as checkboxes: `- [ ] M1.1 Applicants can sign in on a phone (US-01, US-02 LIVE)`. Each one ends with stories at LIVE, not "code written".
6. **Next up**: the top 3-5 tasks in priority order, each with one line of why.
7. **Blocked on human**: anything only a person can do, such as an account, a paid plan, a decision, an API key, or access to real users. Name who, the exact action, and what it unblocks. Keep this list short and at the top of their attention. Never mark a task DONE around a block.
8. **Status words**: DONE with evidence (`DONE 2026-11-03: commit 3f2a9c1` or `DONE 2026-11-03: PR #12`; the stage detector requires a sha, a `#PR` or a URL), IN REVIEW, PARTIAL, NOT STARTED, WAITING (a dep is not done), PARKED (with the D-id), FOLLOW-UP (a ticket written by ship or bug-to-story, `FOLLOW-UP (blocks US-05)`; it does not hold stage 4 open).

## Example

```markdown
| Id | Task | Owner | Deps | Status |
|---|---|---|---|---|
| T-01 | Repo, CI (tests + gen_stories --check), preview deploys | agent · opus/medium · reviewer medium | - | DONE 2026-11-02: PR #1 |
| T-02 | Data model: applicants, reviews (migration + seed) | agent · opus/medium · reviewer high | T-01 | IN REVIEW |
| T-03 | Magic-link auth (US-01, US-02) | agent · opus/high · independent reviewer top | T-01, D-02 | NOT STARTED |
| T-04 | Applicant list with wait badges (US-04) | agent · opus/medium · reviewer high | T-02 | WAITING |
| T-05 | done-journey.yaml for US-01..US-04 | agent · sonnet/low · no reviewer | T-03, T-04 | WAITING |
```

T-02 and T-03 both depend only on T-01, so once T-01 is done they run as two parallel lanes.

## Exit gate

- Every NOT_BUILT story in `stories.json` is cited by at least one task, or is PARKED.
- Every task has an Owner with a review tier, and Deps that form no cycle.
- At least one milestone exists, and "Blocked on human" is filled (or says "none").
- `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` reports stage 4.

Next: the `parallel-lanes` skill.
