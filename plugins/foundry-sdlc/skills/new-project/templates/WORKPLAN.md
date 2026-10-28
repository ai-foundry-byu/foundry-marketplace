# {{PROJECT_NAME}}: workplan

**Written:** {{DATE}} from `PRD.md` v0.1 · **Owner:** {{OWNER}}

<!-- STATUS-BEGIN -->
Progress: 0 of 0 milestones complete. Last ship: none yet.
<!-- STATUS-END -->

**Columns.**
- *Owner*: who does it, as `agent · <model>/<effort> · <review tier>` or a human role. The review tier comes from the blast radius table below, not from habit.
- *Deps*: task ids, story ids, or decision ids (D-01) that must be done first. A task with no deps can run in its own parallel lane today.
- *Status*: DONE · IN REVIEW · PARTIAL · NOT STARTED · WAITING (a dep is not done) · PARKED. Write the evidence after DONE, as each task's commit lands: `DONE 2026-11-03: commit 3f2a9c1` or `DONE 2026-11-03: PR #12`. The stage detector needs a sha, a `#PR` or a URL there.

**Review tier by blast radius** (from the project CLAUDE.md):

| Review | When the task touches |
|---|---|
| independent reviewer at top effort | auth, credentials, payments, anything that sends to real people, anything irreversible, a shared component every feature uses |
| reviewer at high effort | normal feature work: a new module, a schema change |
| reviewer at medium effort | mechanical edits, config, test-only work |
| no reviewer (builder self-checks) | docs, copy, comments |

## Next up (priority order)

1. TODO: T-01, because everything else depends on it.

## Milestones

- [ ] M1.1 TODO: the app runs from a commit (locally or deployed) and the done gate passes on its first page
- [ ] M1.2 TODO: US-01 LIVE and verified by the story-verifier on phone and desktop

## Tasks

| Id | Task | Owner | Deps | Status |
|---|---|---|---|---|
| T-01 | TODO: set up the repo, CI that runs the tests (the stories check is already in `.github/workflows/stories.yml`), and a way to run the app from a commit | agent · opus/medium · reviewer medium | - | NOT STARTED |
| T-02 | TODO: build US-01 (cite the story id in the task) | agent · opus/medium · reviewer high | T-01 | NOT STARTED |
| T-03 | TODO: done-journey.yaml for US-01 and a green done gate | agent · sonnet/medium · no reviewer | T-02 | NOT STARTED |

## Blocked on human

Each item names who, what exactly they must do, and what it unblocks. Keep it short; humans read this first.

| What | Who | Unblocks | Asked on |
|---|---|---|---|
| TODO: create the production database and share the URL | TODO: team lead | T-01 | {{DATE}} |

## Parked

- TODO: tasks for PARKED stories, with the decision id that parked them.
