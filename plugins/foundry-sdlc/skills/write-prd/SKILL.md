---
name: write-prd
description: Stage 2 of the Foundry SDLC. Write PRD.md with user stories inline as "**US-01. Title.**" plus numbered, observable acceptance criteria, compile them into stories.json with gen_stories.py, run the independent prd-critic agent, and record its findings in an "Addressed critiques" appendix. Use when someone says "write the PRD", "spec this", "PRD this", "turn requirements into user stories", "write acceptance criteria", "regenerate stories.json", or when sdlc_stage.py reports stage 2.
---

# Stage 2: PRD and user stories

The PRD is the contract every later stage tests against. Stories live **inside** the PRD, so there is one source of truth. `stories.json` is compiled from the PRD, and testers, verifiers and CI read that compiled file.

## Inputs

`REQUIREMENTS.md` (every R-id), `DECISIONS.md`, and the "Already exists" audit. If stage 1 is not finished, go back. A PRD written before the audit tends to re-specify things that already exist.

## Procedure

1. **Fill the PRD template top-down** (`PRD.md`, created by `new-project`). Section 0, the short version, comes last, once the rest is clear.
2. **Write the stories.** One story per user-visible capability:

   ```markdown
   **US-04. A reviewer sees who has waited more than a week.** (R-03, R-04)
   Surfaces: /applicants
   Devices: phone-390x844, desktop-1440x900
   Waits on: US-01
   1. /applicants lists every applicant with days waiting, oldest first.
   2. Rows waiting more than 7 days show a "Waiting 8 d" badge.
   3. With zero applicants the page says "No applicants yet", not a blank table.
   4. On a 390 px wide phone, the list needs no horizontal scroll.
      - Names longer than the row truncate with an ellipsis.
   ```

   Format rules, which the compiler enforces:
   - The heading is bold, the id is LETTERS-NUMBER (US-01, US-12a), and the title ends with a period inside the bold.
   - `(R-03, R-04)` right after the heading lists the asks the story covers. It is compiled into `covers`.
   - Optional lines: `Surfaces:`, `Devices:`, `Waits on:` (comma separated).
   - Numbered lines are criteria. Indented bullets continue the criterion above them. A story ends at the next heading, table, rule or bold line. Everything after `## Appendix` is ignored.

   Criteria rules, which you enforce:
   - **Observable.** A browser or a person can see each one pass or fail. Write "under 1.5 s", not "fast". Write "says No applicants yet", not "handles empty".
   - **Include the unhappy states:** empty, loading, error, no permission, slow network.
   - **One behavior per criterion.** The verifier reports per criterion, as `US-04.3`.
   - **No implementation detail** unless it is a binding decision. "Uses React Query" is not a criterion.
3. **Compile the stories:**
   ```bash
   python3 tools/gen_stories.py --prd PRD.md --out stories.json
   ```
   ```bash
   python3 tools/gen_stories.py --prd PRD.md --out stories.json --check
   ```
   The first command writes the file. `--check` writes nothing and exits 1 if the file is stale, a story has no criteria, an id is duplicated, or a status is not one of NOT_BUILT, BUILT, PARTIAL, LIVE, PARKED. Regenerating keeps each story's `status`, `notes`, `evidence` and any `surfaces`/`devices`/`waits_on` the PRD does not set. New stories start as NOT_BUILT. The schema is in `stories.schema.json`. (If the project has no `tools/` copy, use `${CLAUDE_PLUGIN_ROOT}/scripts/gen_stories.py`.)
4. **Coverage.** In `REQUIREMENTS.md`, fill the Story ids column for every R-id and set its status to STORIED. Any ask still OPEN is a missing story or needs a DROPPED decision.
5. **Independent critique.** Launch the `prd-critic` agent in a fresh context. Do not critique your own PRD in the same context. Give it only file paths:
   > Critique PRD.md against REQUIREMENTS.md and DECISIONS.md in <dir>. Return numbered critiques with severity and a suggested fix. Do not edit any file.

   For each critique, decide whether to accept it, accept it in part, or reject it. Apply the accepted ones to the PRD. Then fill **Appendix A. Addressed critiques**, one row per critique, including the rejected ones with your reason. Rerun `gen_stories.py` if stories changed.
6. **Push back where you should.** If an ask is wrong (it costs too much, contradicts another ask, or the audit shows it already exists), say so in Appendix B with evidence and a better path. A human decides, and the answer goes into DECISIONS.md.

## Exit gate

- `gen_stories.py --check` exits 0.
- Appendix A has a row for every prd-critic finding. No `TODO:` markers remain.
- Every R-id is STORIED or DROPPED.
- A human has read section 0 and the story list, and said yes. Record that yes in DECISIONS.md.
- `sdlc_stage.py .` reports stage 3.

Next: the `write-workplan` skill. For UI-heavy stories, consider a pre-build pass with `foundry-design:design-critique` on the plan (it is cheaper to remove a screen before it is built).
