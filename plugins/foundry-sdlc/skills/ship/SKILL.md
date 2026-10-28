---
name: ship
description: Stages 6 and 7 of the Foundry SDLC, the ship ritual. Commit, then run the full visual QA battery on that commit (done gate, persona tester per device, one story-verifier per story, design critique, accessibility), locally or on a hosted deploy, then mark only fully passing stories LIVE with the SHA as evidence, write the changelog, and tell users what to try. Use when someone says "ship it", "deploy it", "is it done", "release this", "mark it live", "we're ready to launch", "tell the users", "write the changelog", "ship it locally, we have no hosting", or when sdlc_stage.py reports stage 6 or 7.
---

# Stages 6 and 7: verify the committed build, then ship

## Rules (MUST, every time)

1. **Commit first.** `git status --porcelain --untracked-files=no` must list nothing but artifact files (PRD, stories.json, WORKPLAN, CHANGELOG ...). An uncommitted tree is BUILT, never LIVE. The SHA you test and record is `git rev-parse HEAD`.
2. **The build under test is that commit.** Hosted: the deployed URL serving HEAD. **No hosting (a class or local project): start the app from the committed HEAD on a free local port. That is the build. Do not stop for lack of a deploy.** Record it once as a D-row: `Local ship: the build under test is the committed HEAD served on localhost`.
3. **Run the whole battery (below) in the foreground.** Launch the agents, then wait for every result before you write a status or end your turn. Never leave a verifier running in the background.
4. **LIVE only when every gate passed for that story on that SHA.** Any FAIL or INCONCLUSIVE keeps it PARTIAL: a persona-tester FAIL, an a11y blocking violation, a design-critique objective regression on its screens, a story-verifier FAIL or INCONCLUSIVE. Do not ask the user whether a failing story may be LIVE; only a D-row in their words can accept a known failure.
5. **Set status with the tool, never by hand.** `tools/gen_stories.py --set US-01=LIVE --evidence <report>` refuses LIVE on a dirty tree, without a done-gate report saying exit 0 for HEAD, or without evidence, and records `commit:<sha>`.
6. **Stop every server you started** before you finish, and say so.

## The battery (stage 6), in this order

Start the build once (rule 2), for example `PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1])')`, then:

1. **Stories are current.** `python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --check` exits 0 (drop `product/` when the artifacts are at the root).
2. **Code QA (stage 5).** The tests pass on HEAD, and CI is green if the project has CI. Shared code changed: run `foundry-qa:regression-check`.
3. **Done gate.** Point `done-journey.yaml` at the stories you are shipping, then run the `foundry-qa:done-gate` skill against the build (`--port $PORT` locally). Only exit 0 counts. It writes `.qa/done-gate/last.json` (`sha`, `exit`, `journey`, `time`); the stage detector and `--set LIVE` read that file. A signed-in app: use the journey's `auth:` block (see the done-gate skill).
4. **Example users.** The `foundry-qa` `persona-tester` agent, once per device in the stories' `devices`. Native apps: the matching `foundry-devices` agent.
5. **Independent story verification.** One `story-verifier` agent per story, in a fresh context. Give it only the story id and criteria (from `stories.json`), the build URL and screenshot paths. **Never** the builder's report, the PR text or a diff summary. Write each verdict to `.qa/verify/<id>.md` as it arrives.
6. **Design and accessibility.** `foundry-design:design-critique` on the changed screens (and `ui-reviewer` for a large change), and `foundry-qa:a11y-check` on every surface the stories list.
7. **Every failure is fixed or ticketed** before you go on: a new criterion, story or task through the `bug-to-story` skill, citing the story it blocks.

## Ship (stage 7)

1. **Set status.** Each story whose gates all passed:
   ```bash
   python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --set US-04=LIVE --evidence .qa/verify/US-04.md
   ```
   Every other story you tested: `--set US-05=PARTIAL --evidence .qa/verify/US-05.md`, and name the failing criterion in its `notes`.
2. **Workplan.** Every task whose commit landed: `DONE <date>: commit <sha>`. Tasks for PARTIAL stories point at their follow-up ticket. Remove "Blocked on human" rows a D-row resolved. Tick the milestone if its stories are LIVE.
3. **Changelog.** Under today's `## YYYY-MM-DD` heading: what users can now do, the story ids, the evidence.
   ```markdown
   ## 2026-11-05
   - Reviewers see who has waited more than a week, oldest first (US-04). Commit 3f2a9c1, done gate exit 0, story-verifier 4/4 PASS. Try it: open /applicants on your phone.
   ```
4. **Commit** the status, workplan and changelog edits (`git commit -am "Ship US-04"`).
5. **Tell the users what to try.** One or two lines: where (URL, or "run it from commit 3f2a9c1"), the one thing to try, and how to report a problem. Never before steps 1 to 4.
6. **The usage window opens.** The PRD's section 7.3 gate counts from the first real use. Graduation is a human decision; see `bug-to-story`.

## What to say when a gate fails or cannot run

- "US-04 is PARTIAL at commit 3f2a9c1: the persona tester failed US-04.2 on phone-390x844 (the badge is a 22 px tap target). Ticketed as T-07."
- "US-04 is BUILT, not committed. I committed nothing because the tests fail; fixing first."

Never: "Done! Should be working now."

## Exit gate

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .
```

It reports stage 8, or names exactly what is open: tasks not DONE, no done-gate report for HEAD, a story with no verifier report, a story not LIVE. No server you started is still running.
