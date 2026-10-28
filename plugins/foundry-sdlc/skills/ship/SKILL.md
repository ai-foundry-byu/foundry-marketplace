---
name: ship
description: Stages 6 and 7 of the Foundry SDLC, the ship ritual. Run visual QA on the deployed build in a fixed order (deterministic done gate, persona testers per device, independent story-verifier, design review), then mark stories LIVE, write the changelog, and tell users exactly what to try. Only say "done" after the gate passes. Use when someone says "ship it", "deploy", "is it done", "release this", "mark it live", "we're ready to launch", "tell the users", "write the changelog", or when sdlc_stage.py reports stage 6 or 7.
---

# Stages 6 and 7: verify on the deployed build, then ship

**"Done" means the gate passed on the deployed build.** It does not mean the code is written, the tests pass locally, or the PR is merged. Every one of those has shipped broken pages in our own harness. If a gate cannot run, the honest status is "built, not verified" (BUILT), and you say which gate is missing.

## The ritual (every feature, in this order)

1. **Stories are current.** `python3 tools/gen_stories.py --check` exits 0. The stories you are shipping are BUILT in `stories.json`.
2. **Code QA passed (stage 5).** CI is green on the merge commit. Any change to shared code had `foundry-qa:regression-check` run on it.
3. **Design gate (UI changes).** Run `foundry-design:design-critique` on the changed screens. Fix objective regressions before going further.
4. **Merge and deploy.** Note the deployed commit SHA and URL. Use a preview or staging URL if the team has one, and production after.
5. **Deterministic journey gate.** Update `done-journey.yaml` so it covers the stories you are shipping, then run the `foundry-qa` plugin's `done-gate` against the deployed URL. It checks that the deploy serves the commit you merged, runs the journey steps and assertions on each device profile, and saves screenshots. Only exit 0 counts. A timeout, a crash or "could not determine" is a failure to investigate, not a pass.
6. **Example users.** Run `foundry-qa`'s `persona-tester` with your persona file on each device in the stories' `devices` list. For a native app, use the matching `foundry-devices` plugin (iOS, Android, Windows, macOS). Persona testers find what the journey does not script: confusing copy, a dead end, a tap target too small for a thumb.
7. **Independent story verification.** For each story, launch this plugin's `story-verifier` agent in a fresh context. Give it only the story's id and acceptance criteria (from `stories.json`), the deployed URL, and the screenshot paths. **Never give it the builder's report, the PR description or the diff summary.** It returns PASS, FAIL or INCONCLUSIVE per criterion. INCONCLUSIVE is not a pass: get it the evidence it lacked, or mark the story PARTIAL.
8. **UI review (optional for small changes).** Use `foundry-design:ui-reviewer` on the screenshots, and fix its must-fix items or ticket them.
9. **Every failure is fixed or ticketed** before you go on. A ticket is a new story or task (use the `bug-to-story` skill) with the story id it blocks. A story with an open FAIL is PARTIAL, never LIVE.
10. **Set status.** In `stories.json`, set every story whose criteria all PASSED to `"status": "LIVE"`, and add `"evidence": ["<verifier report path>", "<done-gate run id or log path>"]`. Run `gen_stories.py --check` again: status edits keep it fresh.
11. **Changelog.** Add an entry to `CHANGELOG.md` under today's `## YYYY-MM-DD` heading. Say what users can now do, the story ids, and the evidence. Tick the WORKPLAN milestone if this completes it.
    ```markdown
    ## 2026-11-05
    - Reviewers see who has waited more than a week, oldest first (US-04). PR #11, commit 3f2a9c1, done gate exit 0, story-verifier 4/4 PASS. Try it: open /applicants on your phone.
    ```
12. **Tell the users what to try.** Send one or two lines to the people the feature is for. Include the URL, the one thing to try, and how to report a problem. Example: "New: open /applicants on your phone to see who has waited more than a week. Anything wrong? Reply here, and it becomes a ticket." Never announce before steps 5 to 10 pass.
13. **The usage window opens.** The PRD's section 7.3 "used fully" gate starts counting from the first real use. Graduation (flag fully on, the old workaround retired) is a human decision, made on that evidence. See `bug-to-story` for stage 8.

## What to say when a gate fails or cannot run

- "US-04 is BUILT and deployed at <url> (commit 3f2a9c1). The done gate failed on phone-390x844: the badge assertion timed out. Not shipped. Fixing in T-07."
- "US-04 is BUILT. I could not run the done gate because the preview needs a login I do not have. Added to Blocked on human: a test account for the preview."

Never: "Done! Should be working now."

## Exit gate

- Every story in this release is LIVE with evidence, or PARTIAL/BUILT with the failing criterion named and ticketed.
- CHANGELOG.md has today's dated entry, and the users have been told what to try.
- `sdlc_stage.py .` reports stage 8, or names exactly what is still open.
