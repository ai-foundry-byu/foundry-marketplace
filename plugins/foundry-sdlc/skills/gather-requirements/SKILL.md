---
name: gather-requirements
description: Stage 1 of the Foundry SDLC. Capture every ask verbatim in REQUIREMENTS.md with a stable id (R-01), source and date, record human decisions verbatim in DECISIONS.md, and audit what already exists (code, deployed app, tools, past work) BEFORE any PRD is written. Use when someone says "gather requirements", "here's what the client wants", "capture these asks", "I pasted the feature list", "kickoff notes", "what do they actually want", "do we have all the requirements", or when sdlc_stage.py reports stage 1.
---

# Stage 1: gather requirements

Two failure modes this stage prevents. First, the PRD quietly paraphrases an ask into something the requester never said. Second, the team builds a thing that already exists. Both are cheap to stop here and expensive to find later. In our own harness, a requirements trace done late found 8 of 63 asks with no story at all. This stage exists so that never happens again.

## Inputs to collect

Gather every place the asks came from: meeting notes, a voice memo transcript, a pasted feature list, emails, chat threads, a client brief, a sketch. Each one becomes a **source row** (S1, S2, ...) with who, when, and where the original lives.

## Procedure

1. **Sources.** Fill the Sources table in `REQUIREMENTS.md`, one row per document or conversation.
2. **Asks, verbatim.** Split the sources into atomic asks, one testable want each. Write each ask in the requester's words, in quote marks when quoted directly. Give it the next id: `R-01`, `R-02`, ... Ids never change and are never reused. A dropped ask stays in the table with status DROPPED and the D-id of the decision that dropped it.
   - Too big: "a dashboard for the program". Split it into the separate things they want to see.
   - Too vague to test: keep the words, and add an Open question asking what "fast" or "simple" means to them.
3. **Priority.** Mark each ask must, should or could. If the requester did not say, write your guess and add an Open question. Never present a guess as their priority.
4. **Already exists (audit before the PRD).** Look before you design:
   - the current repo (`git log --oneline | head -30`, the README, `src/` tree, existing routes and tables);
   - the deployed app, if any (open it and click through);
   - the tools the users use today: the spreadsheet, the form, the group chat. These are your real competition;
   - work by teammates, past cohorts, and open-source projects that do 80% of the job.

   One row per area: what exists, where (path or URL), and a verdict (reuse, extend, replace, ignore), with one line of why. If an outside search is needed, run it as a separate research step and cite the URLs.
5. **Decisions.** Every time a human decides something ("yes, magic links", "skip the admin panel for now"), add a `DECISIONS.md` row with their exact words, what it authorizes, and what still needs them. Never write a decision they did not make. For anything still open, add it to "Pending decisions" as a question with your recommendation in bold, so they can answer in one word.
6. **Constraints.** Deadline, budget, stack the course or client requires, data rules (student records, client NDAs), and the devices users actually carry.

## Example rows

```markdown
| R-03 | "I want to see which applicants have been waiting more than a week" | S2 | 2026-11-01 | must | | OPEN |
| R-04 | "it has to work on my phone, I'm never at a desk" | S1 | 2026-10-30 | must | | OPEN |
```

```markdown
| auth | School SSO exists but needs IT approval (4-6 weeks) | https://<sso-docs> | ignore for MVP | timeline; see Q2 |
| applicant data | Form responses already land in a spreadsheet | <sheet link> | reuse as the source | no migration needed |
```

## Exit gate

- Every source has a row. Every ask has an R-id, a verbatim text, a source code and a date.
- "## Already exists" has at least one row per major area of the product.
- No `TODO:` markers remain in REQUIREMENTS.md.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` reports stage 2.

Then show the human the asks table and the Pending decisions, and ask: "Is anything missing or misquoted?" Their answer goes into DECISIONS.md.

Next: the `write-prd` skill.
