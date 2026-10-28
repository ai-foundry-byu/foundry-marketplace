---
name: parallel-lanes
description: Stage 4 of the Foundry SDLC. Execute the workplan, either as parallel lanes (one git worktree and one agent per set of independent tasks, launched with the Agent tool's worktree isolation, a lane brief that names its task ids, a lane registry, the "edit only inside your worktree" rule and a merge-back procedure) or in one session, and mark each task DONE with its commit sha as it lands. It also answers whether tasks can safely run at the same time (a file-ownership check per task). Use when someone says "build it", "execute the workplan", "run these in parallel", "can three agents work on these tasks at the same time", "can several Claude agents work on this without stepping on each other's files", "split the workplan across agents", "spin up agents for each task", "fan out the build", "git worktree", "work on several tasks at once", "merge the lanes back", or when sdlc_stage.py reports stage 4.
---

# Stage 4: execute in parallel lanes

A **lane** is one or more WORKPLAN tasks, built by one agent, in its own git worktree, on its own branch. Worktrees let several agents edit the same repo at the same time without overwriting each other's files: each lane has its own working directory, and the history is shared.

## Rules (MUST, lanes or not)

1. **Every lane runs in its own worktree.** Launch it with the Agent tool and `isolation: "worktree"`, or as its own `claude` session started inside a worktree. A subagent launched without isolation runs in the main checkout, so it is not a lane.
2. **Every lane names its WORKPLAN task ids** in its brief (`Tasks this lane covers: T-02, T-03`). If you want to group the work differently, first edit WORKPLAN.md so each lane maps to task ids.
3. **Write the lane registry before you launch** (`.git/foundry-lanes.json`, below) and set `"active": false` after the last merge.
4. **Commit every task as it lands.** Uncommitted work is not done, and nothing later can be LIVE without a commit.
5. **Bookkeeping in the same step as each merge or commit:** every task it covers becomes `DONE 2026-11-04: commit 3f2a9c1`, and every story it built becomes BUILT (`python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --set US-04=BUILT`; drop `product/` when the artifacts are at the root). Never LIVE: LIVE needs stage 6. Then rerun `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` and check it no longer lists those tasks.

## Can these tasks run at the same time?

Answer with a file-ownership check, not from the Deps column alone. For each task, list the files it will create or change (from its stories' `Surfaces:` and a `grep -rn` of the repo). Two tasks can run in parallel when:

- every Dep of each is DONE, and
- their file lists do not overlap, counting shared files: `package.json` or `requirements.txt`, the database schema or migrations, a routes index, a shared layout or stylesheet.

Report a short table (task, files it owns, verdict), then run the safe ones as lanes and the rest in sequence. Start with 2 or 3 lanes: more lanes than you can review is not faster.

## Single-session build (no lanes)

For a small app, or tasks that touch the same files, one session builds the tasks in dependency order. For each task: write the tests, build, run the tests, `git add -A && git commit -m "T-03: magic-link sign-in (US-01, US-02)"`, then apply rule 5 with that commit's short sha (`git rev-parse --short HEAD`).

## Launch lanes with the Agent tool

1. **Commit the main checkout first.** A lane starts from a commit, never from your uncommitted edits. Add `.claude/worktrees/` to `.gitignore` once, so `git add -A` never picks up a lane.
2. **Write the registry** in the main checkout's git directory (`.git` in a normal clone):
   ```bash
   cat > "$(git rev-parse --git-common-dir)/foundry-lanes.json" <<'JSON'
   {"active": true, "lanes": [
     {"id": "L1", "tasks": ["T-02"], "branch": null, "worktree": null},
     {"id": "L2", "tasks": ["T-03", "T-04"], "branch": null, "worktree": null}
   ]}
   JSON
   ```
   When a lane reports, fill in its `branch` and `worktree` the same way.
3. **Launch up to 3 lanes in one message**, each an Agent call with `subagent_type: "general-purpose"`, `isolation: "worktree"`, `run_in_background: false`, and the brief below as its prompt. Wait for every lane to return.

What happens: Claude Code creates `<repo>/.claude/worktrees/agent-<id>` on branch `worktree-agent-<id>`, and every tool call of that lane runs with that worktree as its working directory. A worktree with changes is left in place for you to merge. If a result does not name its worktree, run `git worktree list`.

**What protects a lane.** With the `foundry-guardrails` plugin, its `worktree-guard` hook does exactly two things for Edit, Write, MultiEdit and NotebookEdit calls:
- A call whose working directory is a linked worktree (every `isolation: "worktree"` lane) is denied when it targets a file in the main checkout. The denial names the same path inside the lane's worktree.
- While the registry says `"active": true`, a subagent call from the main checkout (a lane launched without isolation) is denied when it targets a file in the main checkout outside `.claude/worktrees/`, a linked worktree or a registered lane worktree.

It does not stop shell writes (`sed -i`, `>`, `cp`, `git checkout`), and it does not stop a lane from editing another lane's worktree. The brief's rule covers those. Your own calls as the integrator are never blocked.

## Brief the lane agent

The lane agent has none of your context, so the brief is self-contained. Template:

```text
You are lane L2 in <repo>. Tasks this lane covers: T-03, T-04 (from product/WORKPLAN.md).
First, print `git rev-parse --show-toplevel` and `git branch --show-current`, and put both in your
report. If the top level is the main checkout <main path>, stop: you are not in a worktree.
Edit files ONLY inside your worktree, by paths inside it. Never edit the main checkout or another
lane's worktree. Never run git checkout, git stash or git reset --hard outside your worktree.

Stories: US-01 and US-02 in product/PRD.md. Every numbered acceptance criterion must hold.
Reuse first: product/REQUIREMENTS.md "Already exists" says <what to reuse>. Search the repo
for an existing helper before you write a new one.
Out of scope: anything not in US-01/US-02. Note other problems in your report; do not fix them.

Done means:
1. Tests for each criterion you can test in code, all passing (run them, show the output).
2. foundry-qa:regression-check run on anything shared you changed.
3. Committed on your branch, one commit per task, each message citing its task and story ids.
4. A report: worktree path, branch, commit sha per task, files changed, tests run with results,
   criteria you could NOT verify in code (these go to visual QA), anything that surprised you.
Do not merge. Do not edit WORKPLAN.md or stories.json. The integrator does both.
```

## Review and merge back

Review each lane at the tier its Owner cell names (an independent reviewer for high blast radius, a self-check for docs). Then, from the main checkout, one lane at a time:

```bash
git -C .claude/worktrees/agent-<id> rebase main
```

Run the full test suite in the lane's worktree after the rebase. If the rebase conflicts, resolve it there, never in the main checkout. Then merge:

```bash
git merge --no-ff worktree-agent-<id> -m "Merge lane L2: T-03, T-04 (US-01, US-02)"
```

Run the tests again on main, then apply rule 5 for every task in the lane's `tasks` (`DONE <date>: commit <merge sha>`, its stories BUILT), commit that bookkeeping, and remove the lane:

```bash
git worktree remove .claude/worktrees/agent-<id> && git branch -d worktree-agent-<id>
```

After the last lane, set `"active": false` in the registry. Check the next tasks' Deps again: a WAITING task may now be ready.

## Lanes as separate sessions (a team, or several terminals)

Each lane can instead be its own `claude` session started inside a worktree you create: `git worktree add -b lane/T-03-magic-link ../myapp-lanes/T-03 main`, then `cd ../myapp-lanes/T-03 && claude` (or `claude --worktree`). Install dependencies inside the worktree, and give each dev server its own port. Register the lane the same way (`"worktree": "../myapp-lanes/T-03"`). Merge back as above, or push the branch and open a PR (`git push -u origin lane/T-03-magic-link && gh pr create --fill`); the task is then `DONE <date>: PR #9`.

Scott Murff's **agent-team-kit** (https://github.com/ai-foundry-byu/agent-team-kit) is a ready implementation of this mode for a team: `wt`, `cs` and `wtls` launchers, a multi-lane launcher, a `merge-worktree` skill, and docs on tending several agents. It is linked here, not copied, so read its repo for current usage and license.

## Exit gate

- Every task in WORKPLAN.md is `DONE <date>: commit <sha>` (or a PR), PARKED or FOLLOW-UP, and every story a lane built is BUILT.
- `git worktree list` shows only the main checkout, and the registry says `"active": false`.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .` reports past stage 4. Stage 5 (code QA) is checked by CI, not by files.

Next: code QA with `foundry-qa:regression-check` and CI, then stage 6 visual QA with the `ship` skill.
