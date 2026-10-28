---
name: run-eval
description: Run an evalkit suite, read the report, and compare it with the last run honestly - score with a confidence interval, pass@k and pass^k, errors kept out of the score, case-by-case changes, cost. Use when someone asks "run the evals", "what does X score", "is X getting better or worse", "did my change help", "is this ready to ship", "can this run on its own", or "compare with the last run".
---

# run-eval: run it, read it, report only what you ran

The tool is `evalkit` (on PATH while the foundry-evals plugin is enabled) or
`python3 "${CLAUDE_SKILL_DIR}/scripts/evalkit.py"`, which works with this skill on its own. A suite is a directory with
`suite.json` and `cases.jsonl` (see the `new-eval` skill).

## The one rule

**Never report a measurement you did not run.** A score you quote must come from a run file
you can point to (`.evals/<suite>/<run_id>.json`). Not from memory, not from "it should pass
now", not from a pilot on two cases, not from a run with the judge turned off presented as the
real score. If you did not run it, say "not measured" and say what command would measure it.

## Step 1: sanity check, then a pilot

```bash
evalkit check evals/<suite>                       # free: oracles, empty output, controls
evalkit run evals/<suite> --cases <id1>,<id2>     # pilot: does the target run at all?
```

Open the pilot's markdown report and read one full output. A pilot is recorded as a subset and
never becomes a baseline. Fix any `Errors (not scored)` before the full run.

## Step 2: the full run

```bash
evalkit run evals/<suite> --reps 3 --label <what-changed>
```

Options:

| flag | use |
|---|---|
| `--reps N` | tries per case. Use 3 or more for anything model-backed; 1 is fine for deterministic code |
| `--split train\|val\|test\|all` | run one split (hill-climbing keeps test for the final check) |
| `--tag regression` | only cases with that tag (recorded as a subset) |
| `--no-judge` | skip judge graders. The score becomes an UPPER BOUND and the report says so |
| `--label L` | a name you will recognise in `evalkit history` |
| `--gate` / `--fail-under X` | exit 4 when below the suite threshold / X |
| `--fail-metric pass_hat_k` | gate on "every try passed" instead of the mean |
| `--target "cmd"` | try another target once (recorded as a subset, never a baseline) |
| `--out DIR` | results root, default `.evals` |

Each run writes `.evals/<suite>/<run_id>.json` (every trial, every grader verdict, the
fingerprint) and `.evals/<suite>/<run_id>.md` (the summary). Add `.evals/` to `.gitignore`,
or commit only the baseline files you want to keep.

Exit codes: 0 ok, 2 config error, 3 no scorable trial at all, 4 below the gate.

## Step 3: read the report in this order

1. **Warnings at the top.** Skipped judges or unscored errors mean the score is not the
   suite score yet. Errors are timeouts, crashes, invalid JSON and judge UNKNOWNs: they are left
   out of the score rather than counted as zeros, so many errors make a score look better.
2. **Cases at 0% on every rep.** Read these before anything else. A case that never passes is
   often broken (an expectation the agent was never told, or a grader that is too strict).
   Open the output and decide: agent wrong, or case wrong?
3. **Failures.** Each failing trial with the grader that failed, the reason, and the output.
4. **Flipping cases.** Pass on some reps and fail on others: the agent is unreliable there, or
   the case is ambiguous.
5. **The numbers.**
   - `score`: mean of each case's pass rate, with a 95% bootstrap interval over cases. With 20
     cases the interval is wide (often plus or minus 15 points). Say so.
   - `pass@k`: chance at least one of k tries passes. Fine when a human retries.
   - `pass^k`: chance all k tries pass. Quote this one for "can it run on its own?"
   - `by tag`: a 100% on `do` with 30% on `refuse` is a pushover, whatever the mean says.
   - cost: summed from `_meta.cost_usd` that the target and judge reported. "not reported"
     means the target did not report cost, not that it was free.

## Step 4: compare with the last run

evalkit compares each full run with the latest earlier full run on the same split, and the
markdown has a "Compared with the previous run" section. You can also run:

```bash
evalkit history evals/<suite>
evalkit compare evals/<suite>                     # last two full runs
evalkit compare .evals/<suite>/A.json .evals/<suite>/B.json
```

How to read the comparison:
- **NOT COMPARABLE: the case set changed.** You added, removed or edited cases (or their
  graders). The delta means nothing. Re-run a baseline with the new cases, then compare.
- **within noise.** The change is smaller than the noise band (the wider of the two
  confidence half-widths, or the rep-to-rep spread). Do not call it a win or a loss. Add
  cases or reps if you need to see a smaller effect.
- **improved / regressed.** Bigger than the noise band. Still read `newly_failing`: a run
  that goes up overall while breaking a `regression` case is not a win.
- `changed_surfaces` lists which files in `suite.json` `surfaces` changed between the runs
  (for example `prompt.md`), so you can say what the delta is attributable to.

## Step 5: report it

Template (fill only with numbers from run files you produced in this session):

```
Suite <name>, run <run_id> (<n> cases x <k> reps, split <split>):
score <x>% (95% CI <lo>-<hi>%), pass^<k> <y>%, <e> errors, threshold <t>% -> <PASS|FAIL>.
vs <previous run_id>: <reading>; newly failing: <ids or none>; newly passing: <ids or none>.
Cost <$ or "not reported">. Report: .evals/<suite>/<run_id>.md
Caveats: <judge skipped / errors / small sample / cases changed>.
```

## Do not

- Do not wrap evalkit in your own parallel loop. It runs trials one at a time on purpose, so
  rate limits and your machine stay healthy.
- Do not rerun until the number looks good and report that run. If you rerun, report every
  run, or report the mean over runs.
- Do not quote a `--no-judge`, `--cases` or `--tag` run as the suite score.
- Do not delete old run files to make a comparison go away.

## Maturity

Method: proven (the reliability rules, error handling and same-cases-or-no-comparison rule
come from the AI Foundry team's production eval framework). `evalkit.py`: new standalone port.
