---
name: bug-to-story
description: Stage 8 of the Foundry SDLC, the feedback loop, and the one path for every bug report. Turn a bug report, failed criterion or user complaint into an R-id in the reporter's words, a PRD story criterion, a regression test that fails before the fix, a workplan task and a changelog line, and route it back through the gates; a report you cannot reproduce still gets an R-id and an open question. Also tracks usage gates so a human can decide whether a feature graduates. Use when someone says "found a bug", "this is broken", "a classmate says X is broken", "a user reported", "X finds nothing", "X doesn't work for me", "handle this bug report", "the verifier failed", "turn this into a ticket", "should we graduate this feature", "is anyone using it", or when sdlc_stage.py reports stage 8.
---

# Stage 8: feedback (bugs become stories, usage decides graduation)

Uses agent: story-verifier

A bug fixed without a story and a test tends to come back. A feature nobody uses is not done, it is unvalidated. This stage handles both.

## Rules (MUST, for every report)

1. The report gets an R-id in REQUIREMENTS.md in the reporter's words **before** you change code, even if you cannot reproduce it. Its status starts as `OPEN-FEEDBACK: reported` (never plain `OPEN`, which sends the stage detector back to stage 2).
2. Not reproduced: status `OPEN-FEEDBACK: not reproduced` (or `OPEN-FEEDBACK: needs <who>` while waiting on a human), list what you tried, add an open question, and stop. No code change. The detector lists the row as stage 8 open work.
3. Reproduced: a story criterion cites the R-id (status STORIED), a test fails first, a WORKPLAN task tracks it, and CHANGELOG.md gets a line when it ships. Fixing the code alone is not handling the report.
4. **A fix is committed, never left in the tree.** After the failing test passes, commit the fix, set its task to `DONE <date>: commit <sha>`, and run the gates on that commit (Part A step 7). If you cannot run them now, hand off to `ship` with the exact next command, and say the story is BUILT, not LIVE. Never end with an uncommitted fix, and never ask "should I commit this?": committing is part of the fix.

## Part A: a bug becomes a story and a failing test

1. **Capture it verbatim.** Add it to `REQUIREMENTS.md` as a new R-id: the reporter's words, source, date, and a screenshot or URL if you have one. Example: `R-21 | "the badge says 0 days for everyone" | S7 (reviewer chat) | 2026-11-06`.
2. **Reproduce it before changing anything.** Open the build (deployed, or run locally from HEAD), follow the report, and capture what you see. If you cannot reproduce it, write down exactly what you tried, set the R-id to `OPEN-FEEDBACK: not reproduced` with an Open question, and stop. Never fix a bug you have not seen.
3. **Find the root cause, not the symptom.** Ask why it happened until you reach the line of code or the wrong assumption. Ask also which gate should have caught it. Did a story miss a criterion? Did the journey skip a screen? Did the verifier get the wrong evidence?
4. **Write the story.** Either add a criterion to the existing story, if the behavior was always meant to work (`US-04.5 Days waiting counts from submitted_at, not created_at.`), or add a new story with the next id. Cite the R-id, and set the R-id's Status to STORIED. Then rerun `python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json` (drop `product/` when the artifacts are at the root). A changed story that was LIVE goes back to PARTIAL (`--set US-04=PARTIAL`) until it is verified again.
5. **Write the regression test first, and watch it fail.** It must fail on the current code for the reason in the report:
   ```bash
   npm test -- applicants.wait-days   # or: python3 -m pytest tests/test_wait_days.py
   ```
   Paste the failing output into the task. A test that passes before the fix does not test the bug. If the bug is only visible in a browser, add an assertion to `done-journey.yaml` (or a `foundry-qa` test) that fails today.
6. **Add a task** to WORKPLAN.md (`T-09 | Fix wait-days from submitted_at (US-04.5, R-21) | agent · opus/medium · reviewer high | - | NOT STARTED`). A ticket you file now but do not fix in this session is `FOLLOW-UP (blocks US-04)` instead: it does not hold stage 4 open, and the detector lists it as stage 8 open work.
7. **Fix, commit, and route it through the gates.** Make the test pass, run the project's tests, then:
   ```bash
   git add -A && git commit -m "T-09: fix R-21 wait-days from submitted_at (US-04.5)"
   ```
   Set the task to `DONE <date>: commit <sha>` (`git rev-parse --short HEAD`) and the story to BUILT (`--set US-04=BUILT`). Then run the stage-6 battery on that commit with the `ship` skill: the done gate, and a `story-verifier` agent for the affected story given the new HEAD sha. If you stop here, the last line you write is the handoff, for example: `Committed 3f2a9c1. Next: /foundry-sdlc:ship to verify US-04 on 3f2a9c1 (it is BUILT, not LIVE).`
8. **Log it.** Add a CHANGELOG.md line under today's date with the R-id and story id when the story is LIVE again.
9. **Close the loop with the reporter.** Tell them it is fixed, what to try, and when it shipped. Set the R-id status to LIVE once the story is LIVE again.

Persona-tester and story-verifier failures follow the same path. Each FAIL becomes a criterion or story, plus a failing test.

## Part B: usage gates and graduation

The PRD's section 7.3 defines "used fully" per feature, with four standard measures plus feature-specific ones:

| Measure | Question it answers | Example |
|---|---|---|
| Habit | Do they come back without being told? | opened on 4 of 7 days |
| Action | Do they do the job, not just look? | 10 completed reviews on 3 days |
| Substitution | Did the old workaround go away? | "who's waiting?" messages in the team chat drop by half (n/a if the baseline was under 10) |
| Healthy sources | Was the feature actually working during the window? | the data source it reads was up 95% of the time |

Rules:
- Count server-side events only (a row written, an action completed). Never count client page views alone, and never count test or QA accounts.
- Measure over a fixed window (for example 7 or 14 days) that starts at the first real use after ship.
- If a source the feature depends on was down, pause the window clock and say so. A feature cannot fail its habit gate during an outage.
- Each week, write a short readout per feature: each gate's number against its target, then a recommendation (graduate, extend the window, fix X first, park, kill).
- **A human decides.** The agent recommends. A human graduates, parks or kills, and the answer goes into DECISIONS.md verbatim. Graduation means the flag is on for everyone and the old workaround is retired.

## Exit gate (per bug)

- An R-id with the reporter's words, and a story or criterion that cites it.
- A regression test that failed before the fix and passes after, with both outputs recorded.
- A WORKPLAN task, DONE with its commit sha. `git status --porcelain --untracked-files=all` lists no code file: nothing is left uncommitted.
- An unreproduced report: `OPEN-FEEDBACK: not reproduced` and an open question; no code change.
- The story re-verified by `story-verifier` and back to LIVE, a changelog line, and the reporter told.
