---
name: write-prd
description: Stage 2 of the Foundry SDLC. Write PRD.md with user stories inline as "**US-01. Title.**" plus numbered, observable acceptance criteria, compile them into stories.json with gen_stories.py, run the independent prd-critic agent, and record its findings in an "Addressed critiques" appendix. Use when someone says "write the PRD", "spec this", "PRD this", "turn requirements into user stories", "write acceptance criteria", "regenerate stories.json", when the human answers a PRD review with "approved" or "looks good", or when sdlc_stage.py reports stage 2.
---

# Stage 2: PRD and user stories

The PRD is the contract every later stage tests against. Stories live **inside** the PRD, so there is one source of truth. `stories.json` is compiled from the PRD, and testers, verifiers and CI read that compiled file.

## Rules (MUST)

1. Stories live only in PRD.md; `stories.json` is compiled from it.
2. The `prd-critic` agent critiques the PRD in a fresh context, never you.
3. Every R-id ends STORIED or `DROPPED (D-xx)`.
4. When the human approves, record the `PRD approved` D-row in their words and **stop** (see "When the human approves"). The workplan waits until they ask.

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
3. **Compile the stories**, from the project root (drop `product/` when the artifacts are at the root):
   ```bash
   python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json
   ```
   ```bash
   python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --check
   ```
   The first command writes the file. `--check` writes nothing and exits 1 if the file is stale, a story has no criteria, an id is duplicated, or a status is not one of NOT_BUILT, BUILT, PARTIAL, LIVE, PARKED. Regenerating keeps each story's `status`, `notes`, `evidence` and any `surfaces`/`devices`/`waits_on` the PRD does not set. New stories start as NOT_BUILT. The schema is in `stories.schema.json`. (If the project has no `tools/` copy, run `${CLAUDE_SKILL_DIR}/scripts/gen_stories.py` with the same arguments.)
4. **Coverage.** In `REQUIREMENTS.md`, fill the Story ids column for every R-id and set its Status to STORIED. Any ask still OPEN is a missing story, or the human drops it: then its Status is `DROPPED (D-03)`, citing the decision. The stage detector fails on any other status.
5. **Independent critique.** Launch the `prd-critic` agent in a fresh context. Do not critique your own PRD in the same context. Give it only file paths:
   > Critique PRD.md against REQUIREMENTS.md and DECISIONS.md in <dir>. Return numbered critiques with severity and a suggested fix. Do not edit any file.

   For each critique, decide whether to accept it, accept it in part, or reject it. Apply the accepted ones to the PRD. Then fill **Appendix A. Addressed critiques**, one row per critique, including the rejected ones with your reason. Rerun `gen_stories.py` if stories changed.
6. **Push back where you should.** If an ask is wrong (it costs too much, contradicts another ask, or the audit shows it already exists), say so in Appendix B with evidence and a better path. A human decides, and the answer goes into DECISIONS.md.

7. **Ask for approval.** Show the human section 0, the story list and any OPEN R-id, and ask: "Approve the PRD and these stories?"

## When the human approves (MUST)

When they say "approved", "looks good", "yes", "ship the PRD" or similar:

1. Add one row to the DECISIONS.md table, in exactly this form (next D-id, today's date, their exact words):
   ```markdown
   | D-04 | 2026-11-02 | product owner | "Approved." | PRD approved: PRD.md v0.1 and stories US-01 to US-09 | the workplan starts when they ask |
   ```
   The stage detector looks for a dated `| D-` row containing `PRD approved`.
2. Rerun the detector, tell them stage 2 is done, and **stop**. Do not write the workplan in the same turn. Next is `write-workplan`, when they ask for it.

If they approve with changes, apply the changes and ask again. Approval is never inferred from silence.

## Exit gate

- `gen_stories.py --check` exits 0.
- Appendix A has a row for every prd-critic finding. No `TODO:` markers remain.
- Every R-id is STORIED or `DROPPED (D-xx)`.
- DECISIONS.md has the dated `PRD approved` row in the human's words.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` reports stage 3.

Next: the `write-workplan` skill, when the human asks for it. For UI-heavy stories, consider a pre-build pass with `foundry-design:design-critique` on the plan (it is cheaper to remove a screen before it is built).
