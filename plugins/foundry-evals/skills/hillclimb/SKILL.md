---
name: hillclimb
description: Improve a prompt, skill, agent config or model choice against an evalkit suite by changing one thing at a time, rerunning, and keeping only changes that beat the noise band, while watching cost. Use when someone says "make X better", "improve the prompt", "hill-climb", "tune the agent", "make X cheaper without losing quality", "try a smaller model", or "why did the score drop after my edit".
---

# hillclimb: one change, rerun, keep only real improvements

Hill-climbing is a loop: read failures, make ONE change to one surface, rerun the eval, keep
the change only if the score really went up (or the cost really went down at equal score),
otherwise revert. It needs a working suite first (see `new-eval`) and a stored baseline.
The surface can be a prompt or code (rules, keyword lists, a function): the rules are the same.

## You MUST

1. **One change per round.** A round's diff changes ONE rule, instruction or function. If it
   touches two behaviors, it is two rounds: run evalkit after each.
2. **Keep a round table** and print it in the final report, even after one round:
   `| round | change | score before | score after | kept/reverted |`.
3. **Revert anything that does not beat the noise band** (the comparison reads `within noise`,
   `regressed`, or lists a `newly_failing` case). Revert means the file goes back, now.
4. **Never write rules copied from case text.** Before keeping a change, check that no word,
   phrase or id in the diff was taken from a failing case's input unless it is a general term
   the rule genuinely needs. Special-casing "money back" because one case says it is cheating.
5. **Check a held-out split before declaring a win**: decide keep/revert on `val`, confirm on
   `test` at the end. With too few cases for splits, say plainly that there was no held-out
   check and that the gain may be overfit.

Tool: `evalkit` (on PATH while the foundry-evals plugin is enabled), or
`python3 "${CLAUDE_SKILL_DIR}/scripts/evalkit.py"`, which works with this skill on its own.
Where this page says `evalkit`, either form works.

## Before the first round

1. **List the surfaces** you may change in `suite.json` `"surfaces"` (for example
   `["prompt.md"]`). evalkit fingerprints them, so every comparison says which file changed.
2. **Put the surface under git** (or copy it to `prompt.v0.md`) so a revert is one command.
3. **Know your splits.** evalkit assigns each case to `train`, `val` or `test` by a stable hash
   (default 40/20/40; override per case with `"split"`, or in `suite.json` `"splits"`).
   - read failures from **train** only,
   - decide keep or revert on **val**,
   - look at **test** only at the end, to confirm.
   With fewer than about 30 cases, splits get too small to mean much; then climb on `all`, keep
   the number of rounds small, and say in the write-up that there was no held-out check.
4. **Baseline** each split you will use, at the reps you will use every round:

```bash
evalkit run evals/<suite> --split train --reps 3 --label baseline
evalkit run evals/<suite> --split val   --reps 3 --label baseline
```

5. **Set a budget**: a maximum number of rounds (3 to 5 is typical) and, for model-backed
   targets, a cost ceiling. Every round costs a full val run.

## Each round

1. **Read train failures.** Open the latest train report's Failures and 0% sections. Name the
   failure BEHAVIOR in one sentence ("refuses nothing that is final sale", "states a 60-day
   window that does not exist").
2. **Make ONE change** to ONE surface that targets that behavior. One change means you can
   tell what caused the result. Batching "negation fix + question rule + new keywords" into one
   round makes the result unreadable and is not allowed.
3. **Rerun val** with the same reps:

```bash
evalkit run evals/<suite> --split val --reps 3 --label r1-final-sale-rule
```

4. **Decide** from the comparison block in the new report:
   - `improved` and nothing in `newly_failing` -> **keep**. Commit it with the run id in the message.
   - `within noise` -> **revert**. A change you cannot measure is not an improvement, it is
     extra text you now have to maintain.
   - `regressed`, or anything in `newly_failing` with a `regression` tag -> **revert**.
   - `NOT COMPARABLE` -> you changed cases or graders mid-climb. Undo that, or start a new baseline.
5. Add a row to the round table (round, change, score before, score after, cost, kept or
   reverted) and only then start the next round.

## Rules for prompt changes

- **Generalize the behavior, never paste case content.** Adding "TS-1006 is final sale" to
  the prompt, or adding a failing case's exact words to a keyword list, makes that case pass
  and teaches nothing. Write the rule the case exposed.
- **Cut before you add.** Platitudes and restated defaults ("be helpful", "be accurate") cost
  tokens and rarely move a score. Deleting them is a valid round.
- **Do not add thoroughness boosters** ("think step by step", "double-check everything",
  "verify your answer three times"). On current models they mostly raise cost and latency.
- **Do not edit the grader to make the score go up.** If a grader is wrong, fixing it is a
  separate change that resets the baseline (the case set fingerprint changes and evalkit
  will say NOT COMPARABLE).

## Cost climbing: same score, cheaper

When the goal is cost, the objective flips: a change is kept only if val holds at parity
(the comparison reads `within noise` or `improved`) AND cost drops by a real margin (at least
5%). Walk configuration before prose:

1. Strongest model at the lowest effort or shortest reasoning budget.
2. Then the next smaller model, at low, then medium.
3. Only then prompt rounds aimed at cost: shorter instructions, fewer examples, smaller output.

A cost number exists only if the target reports `_meta.cost_usd` (the example
`target_claude.py` passes through the CLI's reported cost). Without it, compare wall time
(`duration_s` in the summary) and say that is what you compared.

## Finish

```bash
evalkit run evals/<suite> --split test --reps 3 --label final
```

Compare the final test run with the test baseline. Report:

```
Climb on <surface>, <n> rounds, <kept> kept.
val: <baseline>% -> <final>% ; test: <baseline>% -> <final>% (<reading>).
Cost per run: <before> -> <after> (or "not reported").
Kept changes: <one line each, with run ids>.
Reverted: <one line each, with why>.

| round | change | score before | score after | kept/reverted |
|---|---|---|---|---|
| r1 | <one change> | <x>% | <y>% (<reading>) | kept / reverted |
```

If test did not move with val, you fit the val cases. Say so, and do not ship the climb.

## Worked example (the shipped template)

The example suite `refund-triage` ships with a deliberate bug in `target_rules.py`: it never
checks `final_sale`.

`evalkit init` copies the example suite, which ships with the `new-eval` skill; with this
skill installed on its own, scaffold with `new-eval` first and climb from here.

```bash
evalkit init evals/refund-triage                                # from the new-eval skill
evalkit run evals/refund-triage --no-judge --label baseline     # 77.8%, gate FAIL
# report: deny-final-sale and deny-final-sale-over-200 at 0% on every rep
# ONE change: add the final-sale rule before the $200 check in target_rules.py
evalkit run evals/refund-triage --no-judge --label r1-final-sale
# comparison: newly passing deny-final-sale, deny-final-sale-over-200; changed surfaces target_rules.py
```

The same loop on `target_claude.py` climbs `prompt.md` instead, with real model variance, so
use `--reps 3` there.

## Maturity

Method: proven (train/val/test discipline, one change per round, noise-band keep rule and
the cost staircase are how the AI Foundry team's production framework climbs prompts).
This skill runs the loop by hand with `evalkit`; the automated climber is not ported.
