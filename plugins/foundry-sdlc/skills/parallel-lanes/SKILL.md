---
name: parallel-lanes
description: Stage 4 of the Foundry SDLC. Execute the workplan as parallel lanes, one git worktree and one agent per independent task, with a branch naming scheme, a lane brief template, the "edit only inside your worktree" rule, reuse-before-build, and a merge-back procedure. Use when someone says "run these in parallel", "spin up agents for each task", "fan out the build", "git worktree", "work on several tasks at once", "execute the workplan", "merge the lanes back", or when sdlc_stage.py reports stage 4.
---

# Stage 4: execute in parallel lanes

A **lane** is one task from WORKPLAN.md, built by one agent, in its own git worktree, on its own branch. Worktrees let several agents edit the same repo at the same time without overwriting each other's files, because each lane has its own working directory and the history is shared.

## When to use lanes (and when not to)

- Use them for tasks whose Deps are all DONE and which touch mostly different files. Example: T-02 (data model) and T-03 (auth) both depend only on T-01.
- Do not use them for two tasks that edit the same file heavily. Run those in sequence, or merge the first before starting the second.
- Start with 2-3 lanes. Each lane costs review attention, and more lanes than you can review is not faster.

## The non-negotiable rule

**A lane agent edits files only inside its own worktree.** It never edits the main checkout, and never another lane's worktree. It never runs `git checkout`, `git stash` or `git reset --hard` in the main checkout. The `foundry-guardrails` plugin ships a hook that blocks out-of-worktree edits. Enable it when you run lanes.

## Create a lane

Naming: branch `lane/<task-id>-<short-slug>`, worktree directory `../<repo>-lanes/<task-id>`. The worktree lives outside the repo, so it never gets committed or picked up by a file watcher.

```bash
git fetch origin && git switch main && git pull --ff-only
```

```bash
git worktree add -b lane/T-03-magic-link ../myapp-lanes/T-03 origin/main
```

```bash
git worktree list
```

Install dependencies inside the worktree (for example `cd ../myapp-lanes/T-03 && npm ci`). Each worktree has its own `node_modules` or `.venv`. If two lanes run dev servers, give each one its own port.

Claude Code can also create a worktree for one session: start it with `claude --worktree` (or `-w`), or ask the agent to enter a worktree. Use whichever your team standardizes on, as long as each lane gets its own directory.

## Brief the lane agent

Open one Claude Code session per lane with its working directory set to the worktree. A good brief is self-contained, because the lane agent has none of your context. Template:

```text
You are lane T-03 in <repo>. Your worktree is ../myapp-lanes/T-03 on branch lane/T-03-magic-link.
Edit files ONLY inside this worktree.

Task: T-03 from product/WORKPLAN.md: magic-link sign-in.
Stories: US-01 and US-02 in product/PRD.md. Every numbered acceptance criterion must hold.
Reuse first: product/REQUIREMENTS.md "Already exists" says <what to reuse>. Search the repo
for an existing helper before you write a new one.
Out of scope: anything not in US-01/US-02. Note other problems you find in your report; do not fix them.
Effort and review: opus/high, independent reviewer at top effort (auth = high blast radius).

Done means:
1. Tests for each criterion you can test in code, all passing (run them, show the output).
2. foundry-qa:regression-check run on anything shared you changed.
3. Committed on your branch with a message citing T-03, US-01, US-02.
4. A report: files changed, tests run with results, criteria you could NOT verify in code
   (these go to visual QA), anything that surprised you.
Do not merge. Do not mark the task DONE. The integrator does both.
```

## Review and merge back

Review each lane at the tier its Owner cell names. Use an independent reviewer for high blast radius, and a self-check for docs. Then merge, one lane at a time:

```bash
cd ../myapp-lanes/T-03 && git fetch origin && git rebase origin/main
```

Run the full test suite in the worktree after the rebase, and stop if anything fails. Then push and open a PR:

```bash
git push -u origin lane/T-03-magic-link && gh pr create --fill
```

After CI is green and the PR is merged, clean up the lane:

```bash
git worktree remove ../myapp-lanes/T-03 && git branch -d lane/T-03-magic-link
```

Then update WORKPLAN.md: `DONE 2026-11-04: PR #9, CI green`. Set the stories it built to BUILT in `stories.json` (not LIVE: LIVE needs stage 6). Check the next lane's Deps again, because a task that was WAITING may now be ready.

If two lanes conflict on rebase, the second lane resolves the conflict in its own worktree, reruns its tests, and asks for review again. Never resolve conflicts in the main checkout.

## A ready-made implementation

Scott Murff's **agent-team-kit** (https://github.com/ai-foundry-byu/agent-team-kit) is a ready implementation of worktree mode for a team: `worktree-commands.sh` with `wt`, `cs` and `wtls` launchers, a multi-lane launcher, a `merge-worktree` skill, and docs on tending several agents (`docs/WORKTREE-MODE.md`, `docs/TENDING-AGENTS.md`). Follow its README to install it into your project. It is linked here, not copied, so read its repo for current usage and license.

## Exit gate

- Every task in WORKPLAN.md is DONE (with evidence) or PARKED.
- `git worktree list` shows only the main checkout (no forgotten lanes).
- `sdlc_stage.py .` reports past stage 4. Stage 5 (code QA) is checked by CI, not by files.

Next: code QA with `foundry-qa:regression-check` and CI, then stage 6 visual QA.
