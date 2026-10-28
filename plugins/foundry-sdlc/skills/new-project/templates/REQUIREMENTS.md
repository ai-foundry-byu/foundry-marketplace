# {{PROJECT_NAME}}: requirements

**Captured:** {{DATE}} · **Owner:** {{OWNER}}

This file is the verbatim source of truth. Write each ask in the requester's own words. Paraphrase goes in the PRD, never here. Every ask gets an id that never changes and never gets reused, even if the ask is dropped.

## Sources

| Code | Source | Who | Date | Where the original lives |
|---|---|---|---|---|
| S1 | TODO: kickoff call | TODO: client or sponsor role | {{DATE}} | TODO: notes link or file path |

Source codes in the table below: S1, S2, ... from this table.

## Asks

| Id | The ask (verbatim; quote marks for direct quotes) | Src | Date | Priority (must, should, could) | Story ids | Status |
|---|---|---|---|---|---|---|
| R-01 | TODO: "exact words of the ask" | S1 | {{DATE}} | must | (filled in stage 2) | OPEN |

Status: OPEN (no story yet), STORIED (at least one story covers it), LIVE (its stories are LIVE), DROPPED (a decision in DECISIONS.md dropped it; write `DROPPED (D-03)`), PARTIAL (a decision overrides it in part; write `PARTIAL (D-03): <what survives>`, never STORIED), OPEN-FEEDBACK (a bug report with no story yet, written by bug-to-story; write `OPEN-FEEDBACK: not reproduced` or `OPEN-FEEDBACK: needs <who>`).

## Already exists

Audit BEFORE writing the PRD. Read the current code, the deployed app, the tools the users already use, and anything a teammate or a past cohort built. Reuse before build.

| Area | What exists today | Path or URL | Verdict (reuse, extend, replace, ignore) | Why |
|---|---|---|---|---|
| TODO: auth | TODO: what you found | TODO: `src/lib/auth.ts` or a URL | TODO: reuse | TODO: one line |

## Constraints

- TODO: budget, deadline, required stack, data rules (FERPA, client NDA), devices the users carry.

## Open questions

Each question names who can answer it. When answered, record the answer in `DECISIONS.md` and link the D-id here.

| Q | Question | Who answers | Blocks | Answer (D-id) |
|---|---|---|---|---|
| Q1 | TODO: question | TODO: role | R-01 | |

## Coverage check (stage 2 exit)

Every R-id is STORIED, LIVE, `DROPPED (D-xx)` or `PARTIAL (D-xx)`. An OPEN row at the end of stage 2 is a missing story; the stage detector names it. OPEN-FEEDBACK rows are not a stage 2 failure: the detector lists them as stage 8 open work.
