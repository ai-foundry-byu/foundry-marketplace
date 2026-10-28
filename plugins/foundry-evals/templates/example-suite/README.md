# Example suite: refund-triage

A support agent for a fictional outdoor store, Trailhead Supply, decides what to do with one
refund request (`approve_refund`, `deny`, `escalate`, `ask_info`) and writes the reply.
Rules are in `prompt.md`. Today's date is pinned to 2026-10-05 in every case.

| file | what it is |
|---|---|
| `suite.json` | target command, suite-wide graders, judge, controls, threshold 0.9 |
| `cases.jsonl` | 9 cases: 3 approve, 2 escalate, 3 deny, 1 ask; each has an `oracle` |
| `target_rules.py` | offline rules target with ONE deliberate bug (final sale is never checked) |
| `target_claude.py` | the same task through `claude -p`, reading `prompt.md` |
| `judge.py` | binary judge (added by `evalkit init`) |
| `controls/` | do-nothing and pushover agents; both must score low |

Try it:

```bash
evalkit check . --no-judge                 # oracles pass, empty fails, controls 0% and 33%
evalkit run . --no-judge --gate            # 77.8%, two final-sale cases at 0%, exit 4
# fix the bug in target_rules.py, then:
evalkit run . --no-judge --gate            # 100%, comparison lists the two newly passing cases
evalkit run . --target "python3 target_claude.py" --reps 3   # the model version, with judges
```

To make it yours: replace the cases, the target command and the graders. Keep the controls.
