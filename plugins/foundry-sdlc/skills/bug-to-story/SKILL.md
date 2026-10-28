---
name: bug-to-story
description: Stage 8 of the Foundry SDLC, the feedback loop. Turn every bug report, failed criterion or user complaint into a PRD story plus a regression test that fails before the fix, route it back through the gates, and track usage gates so a human can decide whether a feature graduates, gets parked or gets killed. Use when someone says "found a bug", "this is broken", "a user reported", "the verifier failed", "write a regression test", "turn this into a ticket", "should we graduate this feature", "is anyone using it", or when sdlc_stage.py reports stage 8.
---

# Stage 8: feedback (bugs become stories, usage decides graduation)

A bug fixed without a story and a test tends to come back. A feature nobody uses is not done, it is unvalidated. This stage handles both.

## Part A: a bug becomes a story and a failing test

1. **Capture it verbatim.** Add it to `REQUIREMENTS.md` as a new R-id: the reporter's words, source, date, and a screenshot or URL if you have one. Example: `R-21 | "the badge says 0 days for everyone" | S7 (reviewer chat) | 2026-11-06`.
2. **Reproduce it before changing anything.** Open the deployed build, follow the report, and capture what you see. If you cannot reproduce it, write down exactly what you tried, set the R-id to OPEN with an Open question, and stop. Never fix a bug you have not seen.
3. **Find the root cause, not the symptom.** Ask why it happened until you reach the line of code or the wrong assumption. Ask also which gate should have caught it. Did a story miss a criterion? Did the journey skip a screen? Did the verifier get the wrong evidence?
4. **Write the story.** Either add a criterion to the existing story, if the behavior was always meant to work (`US-04.5 Days waiting counts from submitted_at, not created_at.`), or add a new story with the next id. Cite the R-id. Then rerun `python3 tools/gen_stories.py`. A changed story that was LIVE should go back to PARTIAL until it is verified again.
5. **Write the regression test first, and watch it fail.** It must fail on the current code for the reason in the report:
   ```bash
   npm test -- applicants.wait-days   # or: python3 -m pytest tests/test_wait_days.py
   ```
   Paste the failing output into the task. A test that passes before the fix does not test the bug. If the bug is only visible in a browser, add an assertion to `done-journey.yaml` (or a `foundry-qa` test) that fails today.
6. **Add a task** to WORKPLAN.md (`T-09 | Fix wait-days from submitted_at (US-04.5, R-21) | agent · opus/medium · reviewer high | - | NOT STARTED`) and run it through stages 4 to 7 like any other task: lane, code QA, done gate, story-verifier, changelog.
7. **Close the loop with the reporter.** Tell them it is fixed, what to try, and when it shipped. Set the R-id status to LIVE.

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
- The story re-verified by `story-verifier` and back to LIVE, a changelog line, and the reporter told.
