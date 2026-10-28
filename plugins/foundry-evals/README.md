# foundry-evals

Measure agents and prompts. Build an eval suite that can actually fail, run it, compare
with the last run without fooling yourself, and improve a prompt one change at a time.

Ships three skills, one auditing agent, and `evalkit.py`: a single-file, standard-library-only
Python runner you can also copy into any repo for CI.

## Install

Add the marketplace (once):

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the plugin:

```text
/plugin install foundry-evals@ai-foundry
```

Or from a shell:

```bash
claude plugin install foundry-evals@ai-foundry
```

## What is in it

| item | type | what it does | SDLC stage | maturity |
|---|---|---|---|---|
| `new-eval` | skill | scaffold a suite: cases, target runner, code graders first, a binary judge only where code cannot grade, do-nothing and pushover controls, a threshold | test design | method proven; tooling new |
| `run-eval` | skill | run, read the report in the right order, compare with the last run, report only measured numbers | test / verify | method proven; tooling new |
| `hillclimb` | skill | one change per round, keep only changes above the noise band, train/val/test discipline, cost staircase | improve / optimize | method proven; tooling new |
| `eval-auditor` | agent | audits a suite for ambiguous cases, cheatable or over-strict graders, missing hold cases, bad judge rubrics, saturated or noisy runs | review | new |
| `skills/new-eval/scripts/evalkit.py` (also `bin/evalkit`) | script | the runner: init, run, check, compare, history; vendored into `run-eval` and `hillclimb` | test / CI gate | new (standalone port) |
| `skills/new-eval/scripts/judge_claude.py` | script | binary LLM judge through `claude -p`: critique, then a single VERDICT line | test | new |
| `skills/new-eval/templates/example-suite` | template | `refund-triage`, a 9-case suite with an offline target, a model target, controls and a deliberate bug to find | learning | new |

**Maturity, honestly.** "Proven" here means the METHOD (code graders first, binary judges,
negative controls, errors never scored as zeros, pass^k, same cases or no comparison, one
change per climb round, train/val/test splits) is how the AI Foundry team's own eval
framework works in production today. `evalkit.py`, the judge script, the agent and the
templates are NEW: a standalone port written for this marketplace, covered by unit tests but
not yet battle-tested by other teams. Report bugs as issues.

## Quickstart (2 minutes, no API key)

```bash
evalkit init evals/refund-triage
cd evals/refund-triage
evalkit check . --no-judge
evalkit run . --no-judge --gate
```

If `evalkit` is not on PATH (the plugin's `bin/` is added only while the plugin is enabled),
run `python3 skills/new-eval/scripts/evalkit.py` from the plugin folder, or copy that one file
into your repo and run `python3 evalkit.py`.

## Install one item on its own

Every skill is self-contained: copy its folder to `.claude/skills/<name>/` or
`~/.claude/skills/<name>/` and it runs its own `scripts/evalkit.py` through
`${CLAUDE_SKILL_DIR}`.

| item | on its own | notes |
|---|---|---|
| `new-eval` | standalone | carries the canonical `evalkit.py`, `judge_claude.py` and the example suite, so `init` works |
| `run-eval` | standalone | carries a vendored `evalkit.py` (run, check, compare, history); `init` needs `new-eval` |
| `hillclimb` | standalone | carries a vendored `evalkit.py`; scaffold with `new-eval` first |
| `eval-auditor` | needs skill `run-eval` | copy `agents/eval-auditor.md` to `.claude/agents/` and `run-eval` to `.claude/skills/run-eval/`; the agent finds it and says so if it is missing |
| `bin/evalkit` | plugin only | the PATH wrapper exists only while the plugin is enabled |

Vendored copies are listed in `vendor.json` (copy path: canonical path) and must stay
byte-identical; `tests/test_evalkit.py` checks it. Edit the canonical file, then copy it over.

The first run scores 77.8% and fails the 90% gate: two final-sale cases sit at 0% because the
example target has a deliberate bug. Ask Claude "use the hillclimb skill on this suite" to
find and fix it, then rerun and read the comparison.

## How to use each item

**new-eval.** Say "add an eval for my summarizer" or "build evals for this agent". The skill
walks through: define good, scaffold with `evalkit init`, wire your target (JSON in on stdin,
one JSON object out on stdout), write cases with oracles, choose graders, add a judge only for
fuzzy criteria, add controls, set the threshold, and pass `evalkit check`.

**run-eval.** Say "run the evals" or "did my change help". It runs a pilot, the full run with
reps, reads the report (warnings, 0% cases, failures, flips, then numbers), and reads the
comparison (NOT COMPARABLE, within noise, improved, regressed).

**hillclimb.** Say "improve this prompt against the eval" or "make it cheaper without losing
quality". One change per round, keep or revert on val, confirm on test, log every round.

**eval-auditor.** Say "audit my eval suite at evals/x". It runs the free `evalkit check`,
reads every case and the latest run, and reports findings with evidence and fixes. It does not
edit files and does not run paid model calls unless you ask.

## evalkit reference

```bash
evalkit init <dir>                       # copy the example suite (plus judge.py)
evalkit check <suite> [--no-judge]       # oracles pass, empty output fails, controls score low
evalkit run <suite> [--reps N] [--split train|val|test|all] [--cases a,b] [--tag t]
                    [--label L] [--no-judge] [--target CMD] [--out DIR]
                    [--gate | --fail-under X] [--fail-metric score|pass_hat_k]
evalkit compare <suite> | <a.json> <b.json>
evalkit history <suite>
```

Target protocol: stdin `{"case_id", "rep", "input"}`; stdout one JSON object; optional
`"_meta": {"cost_usd": n}`. Non-zero exit, timeout or non-JSON output is an error trial, kept
out of the score and listed in the report.

Graders: `exact`, `contains`, `regex`, `json_field` (`equals`, `one_of`, `exists`, `is`),
`judge`. All take `path` (dotted) and `negate`.

Judge protocol: stdin `{"case_id", "input", "expected", "output", "criterion", "rubric"}`;
stdout `{"pass": true|false|null, "reason": "..."}`. `null` (UNKNOWN) is an error, not a pass.

Outputs: `<root>/<suite>/<run_id>.json` (every trial and grader verdict, fingerprints of the
case set, graders, target command and surfaces) and `<root>/<suite>/<run_id>.md` (summary,
comparison, failures, errors).

Results root: `--out DIR` if given; otherwise `.evals` in the project root, the nearest folder
above the suite that has a `.git` (else the suite's parent folder). It never depends on the
directory you run from, so every run of a suite lands in one history and compares with the
last one. `run` prints the absolute report path; `history` prints the folder first. If an older
version left runs in `./.evals`, evalkit prints a `note:` pointing at them.

`suite.json` `target` (and `judge`) is an object `{"command": ..., "timeout_s": n}`, or a bare
command string or list as shorthand (`"target": "python3 run.py"`).

Exit codes: 0 ok, 2 config error, 3 no scorable trial, 4 below gate, 5 check failed.

CI example (GitHub Actions step):

```yaml
- run: python3 tools/evalkit.py run evals/refund-triage --gate --quiet
```

## Requirements

- Python 3.9 or newer. No packages.
- Claude Code CLI on PATH only for `judge_claude.py` and the example `target_claude.py`
  (both call `claude -p --output-format json`). Set `EVALKIT_JUDGE_MODEL` and
  `EVALKIT_TARGET_MODEL` to pin models, `EVALKIT_CLAUDE_BIN` to use another binary.

## Tests

```bash
cd plugins/foundry-evals
python3 -m unittest discover -s tests -v
```

32 offline tests: every grader, pass@k and pass^k math, error handling (crash, junk stdout,
timeout), judge wiring and cost sums, the example suite end to end (baseline fails the gate,
the one-line fix passes, comparison names the two fixed cases), case-set change detection,
control and empty-output self-tests, CLI exit codes, one results history when the suite is
run from two different directories (and `--out` still overriding it), a string `target`, vendored copies byte-identical to
canonical, and a clear error when `init` runs without the example suite.

## Known limitations

- Trials run one at a time. Large suites against slow models take a while; that is deliberate.
- `claude -p` targets and judges inherit your Claude Code settings, plugins and project
  instructions from the directory they run in. For a clean measurement, run the suite from a
  directory without a project CLAUDE.md, or use your own API-based target.
- No automated hill-climber: the `hillclimb` skill drives the loop by hand with evalkit.
- No multi-turn conversation or tool-sandbox harness. For a full agent environment (mock
  store, tool-call graders, judge validation with human labels), see
  [agent-evals-starter](https://github.com/jddavenportOpen/agent-evals-starter) (MIT), which
  this plugin's control and grader ideas are adapted from.
- Bootstrap intervals over a few dozen cases are wide and somewhat optimistic (reps of one
  case are not independent). Treat small deltas as noise.

## License

MIT. Part of the [AI Foundry marketplace](https://github.com/ai-foundry-byu/foundry-marketplace).
