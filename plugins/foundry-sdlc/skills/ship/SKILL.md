---
name: ship
description: Ship it, release it, mark it live. Load this before answering any "ship it", "release this", "mark it live", "it's finished" or "is it done" request; never judge readiness from the files yourself. Stages 6 and 7 of the Foundry SDLC: commit, run the QA battery on that commit, set only fully passing stories LIVE, write the changelog, tell users what to try. Also for "deploy it", "we're ready to launch", "tell the users", "ship it locally, we have no hosting", or sdlc_stage.py stage 6 or 7.
---

# Stages 6 and 7: verify the committed build, then ship

Uses agent: story-verifier

## Rules (MUST, every time)

1. **Read before you claim.** Run `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .`, then read `.qa/done-gate/last.json` and list `.qa/verify/` before you say any report is missing or stale. Never refuse "ship it" on a stage number alone: quote the detector's failing line, then fix that line or run the gate it names.
2. **Refresh the project's tools before you use them.** A project keeps its own copy at `tools/gen_stories.py`, so fixes to this skill reach it only this way. From the project root:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/gen_stories.py" --refresh-tools .
   ```
   It prints one line. Show it to the student as is, for example `refreshed tools/gen_stories.py: unversioned -> 0.2.0 (+40 -12 lines)`. The refreshed copy goes into the commit below. The scaffold's tool files are not part of the build under test, so a refresh never makes the done gate stale.
3. **Commit first.** `git status --porcelain --untracked-files=all` must list nothing but artifact files (PRD, stories.json, WORKPLAN, CHANGELOG ...) and `.qa/`. A new untracked file is not in the commit either. An uncommitted tree is BUILT, never LIVE. The SHA you test and record is `git rev-parse HEAD`.
4. **The build under test is that commit.** Hosted: the deployed URL serving HEAD. **No hosting: start the app from the committed HEAD on a free local port. That is the build. Do not stop for lack of a deploy.** If DECISIONS.md has no `Local ship` row yet, add one now: `| D-xx | <date> | agent | "no hosting" | Local ship: the build under test is the committed HEAD served on localhost | - |`.
5. **One server, at most 3 agents at a time, all in the foreground.** Start ONE server for the whole battery (see "Server hygiene"). Launch at most 3 QA agents per message against that one URL, each with `run_in_background: false`, and wait for all of them before the next batch. Never end a turn with an agent still running.
6. **Every story-verifier gets the HEAD sha and its report path** (`.qa/verify/<id>.md`), and its report starts with `Commit: <sha>`. `--set LIVE` refuses a report that names no commit or an older build. The agent returns the report as text, one fenced block after a line naming the path: you write `.qa/verify/<id>.md` yourself with the Write tool, verbatim (the block's content, nothing added, removed or reworded), never by the agent. Claude Code refuses a subagent's Write of a report file ("Subagents should return findings as text, not write report files."), so never ask it to save the file.
7. **LIVE only when every gate passed for that story on that SHA.** Any FAIL or INCONCLUSIVE keeps it PARTIAL. Only a D-row in the user's own words can accept a known failure.
8. **Set status with the tool, never by hand.** `tools/gen_stories.py --set US-01=LIVE --evidence .qa/verify/US-01.md` refuses LIVE on an uncommitted or untracked file, without a done-gate report saying exit 0 for HEAD, or without a verifier report for HEAD, and records `commit:<sha>`.
9. **Stop the server by its PID** before you finish, even when a gate failed, and say so.

## Server hygiene

```bash
mkdir -p .qa/run
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
echo "$PORT" > .qa/run/port
python3 server/app.py --port "$PORT" > .qa/run/server.log 2>&1 &   # your start command
echo $! > .qa/run/server.pid
```

Start the server process itself (not a wrapper that forks), so the saved PID is the server. Keep pid, port and log files in `.qa/run/`, never in `/tmp`. Stop it with `kill "$(cat .qa/run/server.pid)" && rm .qa/run/server.pid`. Never `pkill -f` or `killall`: they match other projects' servers.

## The battery (stage 6), in this order

1. **Stories are current.** `python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --check` exits 0 (drop `product/` when the artifacts are at the root).
2. **Code QA (stage 5).** The tests pass on HEAD, and CI is green if the project has CI. Shared code changed: run `foundry-qa:regression-check`.
3. **Done gate.** Point `done-journey.yaml` at the stories you are shipping, then run the `foundry-qa:done-gate` skill against the build (`--port $PORT` locally). Only exit 0 counts. It writes `.qa/done-gate/last.json` (`sha`, `exit`, `journey`, `time`). A signed-in app: use the journey's `auth:` block.
4. **Example users.** The `foundry-qa` `persona-tester` agent, once per device in the stories' `devices`. Native apps: the matching `foundry-devices` agent.
5. **Independent story verification.** One `story-verifier` agent per story, in a fresh context. Give it only the story id and criteria (from `stories.json`), the build URL, screenshot paths, the HEAD sha and the report path `.qa/verify/<id>.md`. **Never** the builder's report, the PR text or a diff summary. As each verdict arrives, save it yourself (rule 6): the fenced block from its final message, verbatim, to `.qa/verify/<id>.md`.
6. **Design and accessibility.** `foundry-design:design-critique` on the changed screens (and the `ui-reviewer` agent for a large change), and `foundry-qa:a11y-check` on every surface the stories list.
7. **Every failure is fixed or ticketed** before you go on: through the `bug-to-story` skill, as a WORKPLAN task with status `FOLLOW-UP (blocks US-05)`. A FOLLOW-UP task does not hold stage 4 open; the detector lists it as stage 8 open work.

## Ship (stage 7)

1. **Set status.** Each story whose gates all passed:
   ```bash
   python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --set US-04=LIVE --evidence .qa/verify/US-04.md
   ```
   Every other story you tested: `--set US-05=PARTIAL --evidence .qa/verify/US-05.md`, and name the failing criterion in its `notes`.
2. **Workplan.** Every task whose commit landed: `DONE <date>: commit <sha>`. A task whose story is PARTIAL is still DONE when its commit landed: `DONE 2026-11-05: commit 3f2a9c1 (US-05 PARTIAL, rest in T-12)`, with T-12 as `FOLLOW-UP (blocks US-05)`. Then turn every task still open into a FOLLOW-UP ticket, or the detector stays at stage 4:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" . --mark-follow-ups
   ```
   It sets each open task (not DONE, PARKED or FOLLOW-UP) that names a story not yet LIVE to `FOLLOW-UP (blocks US-05)` and prints each change. It refuses while no story is LIVE. A task it lists as naming no open story is yours to settle: DONE with its commit, PARKED with a D-id, or `FOLLOW-UP (blocks US-xx)` by hand. Remove "Blocked on human" rows a D-row resolved. Tick the milestone if its stories are LIVE.
3. **Changelog.** Under today's `## YYYY-MM-DD` heading: what users can now do, the story ids, the evidence.
   ```markdown
   ## 2026-11-05
   - Reviewers see who has waited more than a week, oldest first (US-04). Commit 3f2a9c1, done gate exit 0, story-verifier 4/4 PASS. Try it: open /applicants on your phone.
   ```
4. **Commit** the status, workplan, decisions and changelog edits (`git commit -am "Ship US-04"`).
5. **Tell the users what to try.** One or two lines: where (URL, or "run it from commit 3f2a9c1"), the one thing to try, and how to report a problem. Never before steps 1 to 4.
6. **The usage window opens.** The PRD's section 7.3 gate counts from the first real use. Graduation is a human decision; see `bug-to-story`.

## What to say when a gate fails or cannot run

- "US-04 is PARTIAL at commit 3f2a9c1: the persona tester failed US-04.2 on phone-390x844 (the badge is a 22 px tap target). Ticketed as T-07 (FOLLOW-UP)."
- "US-04 is BUILT, not committed. I committed nothing because the tests fail; fixing first."

Never: "Done! Should be working now."

## Exit gate

- `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" . --mark-follow-ups` exits 0 (no open task left), and `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` reports stage 8. After a partial ship, stage 8 lists the open work: stories not LIVE, FOLLOW-UP tasks, OPEN-FEEDBACK asks. A code change after the gate sends it back to stage 6.
- DECISIONS.md has a `Local ship` row (no hosting) or names the deploy target.
- `.qa/run/server.pid` is gone: no server you started is still running.
