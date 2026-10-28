---
name: persona-run
description: Run every user story as a persona (qa/personas/<name>.md) on that persona's device profiles in a real browser, read-only by default so it is safe on production data. Checks each story's assertions plus the persona's patience budget, horizontal overflow, tap-target size and console errors, and reports passed, failed, needs-judgment and inconclusive separately. Use when asked to "run the persona tests", "test as a first-time user", "which stories pass for <persona>", or to set up personas and stories for a project. The persona-tester agent runs this skill.
---

# persona-run

The mechanical half of persona testing. `persona_run.py` drives each story as the persona, on
the persona's devices, and writes evidence. The judgment half (reading each screenshot through
the persona's eyes) belongs to whoever runs it, usually the `persona-tester` agent.

## Setup (once)

```bash
pip install playwright
python3 -m playwright install chromium        # add webkit for Safari-engine runs
```

Copy the templates into the project, then edit them to match your real users and stories.
Do not edit the copies inside this skill.

```bash
mkdir -p qa/personas && cp "${CLAUDE_SKILL_DIR}"/templates/personas/*.md qa/personas/ && cp "${CLAUDE_SKILL_DIR}/templates/stories.example.json" qa/stories.json
```

- `templates/personas/TEMPLATE.md`: frontmatter (`name`, `devices`, `patience_seconds`,
  `min_tap_target_px`) plus prose: who they are, where they use the app, top jobs, what makes
  them give up, how they judge a screen. Two worked examples sit beside it:
  `first-time-mobile-user.md` and `power-user-on-desktop.md`.
- `templates/stories.example.json`: each story has `id`, `title`, `start` (path), optional
  `steps` and `assertions` (the done-journey format), optional human `acceptance` criteria,
  optional `devices`, and `writes: true` if the story saves something.

A persona should come from real users (interviews, support tickets, analytics), not from
imagination, and never from a real person's name or data.

## Run

```bash
# print the story x device matrix, run nothing
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" --persona qa/personas/first-time-mobile-user.md \
  --stories qa/stories.json --base-url <url> --plan

# run it
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" --persona qa/personas/first-time-mobile-user.md \
  --stories qa/stories.json --base-url <url>

# narrower, or the Safari engine
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" ... --story S-2 --story S-4 --devices phone-390x844 --browser webkit

# after two runs: ticket only the failures that repeated
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" ... --file-tickets
```

Output: `.qa/persona/<persona-name>/` with `REPORT.md`, `results.json`, a screenshot per story
and device, and `tickets/<story>-<device>.md` when `--file-tickets` finds a repeat failure.

**Read-only by default.** Every POST, PUT, PATCH and DELETE is answered inside the browser and
never sent. `--allow-writes` is refused for anything but localhost. A simulated write proves
only that the UI responded.

## Statuses and exit codes

- `passed`: every assertion and persona check held
- `failed`: an assertion, step or persona check failed
- `needs-judgment`: no mechanical assertions; a person or agent must judge the screenshot
- `inconclusive`: nothing was proven (unreachable, sign-in wall, harness error)

Exit `0` no failures, `1` at least one failure, `2` config error, `6` nothing failed but
something was inconclusive or no story ran. Report judged rows as JUDGED PASS or JUDGED FAIL,
never folded into the passed count.

## Acceptance check

- The run used a persona and stories file from the project, not the templates in this skill.
- Every `needs-judgment` row has a written JUDGED PASS or JUDGED FAIL with one sentence of why.
- No real write reached a non-local server.
