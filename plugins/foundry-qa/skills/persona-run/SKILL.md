---
name: persona-run
description: Run every user story as a persona (qa/personas/<name>.md) on that persona's device profiles in a real browser, read-only by default so it is safe on production data. Reads the project's own stories.json (the foundry-sdlc format) as is, waits for async data before judging, checks each story's assertions plus the persona's patience budget, horizontal overflow and console errors, reports tap-target size once per device, and reports passed, failed, needs-judgment and inconclusive separately. Use when asked to "run the persona tests", "test as a first-time user", "which stories pass for <persona>", or to set up personas for a project. The persona-tester agent runs this skill.
---

# persona-run

The mechanical half of persona testing. `persona_run.py` drives each story as the persona, on
the persona's devices, and writes evidence. The judgment half (reading each screenshot through
the persona's eyes) belongs to whoever runs it, usually the `persona-tester` agent.

## You MUST

1. Pass the project's ONE stories.json (`--stories product/stories.json` in a foundry-sdlc
   project). Never write a second stories file for this script.
2. Judge every `needs-judgment` row against its acceptance criteria: JUDGED PASS or JUDGED FAIL,
   with one sentence of why. Never count a judged row as passed.
3. Report the site-wide tap-target findings once, as warnings, not as story failures.
4. Keep it read-only on anything but localhost.

## Setup (once)

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install playwright
python3 -m playwright install chromium        # add webkit for Safari-engine runs
```

Copy the persona templates into the project, then edit them to match your real users.
Do not edit the copies inside this skill.

```bash
mkdir -p qa/personas && cp "${CLAUDE_SKILL_DIR}"/templates/personas/*.md qa/personas/
```

- `templates/personas/TEMPLATE.md`: frontmatter (`name`, `devices`, `patience_seconds`,
  `min_tap_target_px`) plus prose: who they are, where they use the app, top jobs, what makes
  them give up, how they judge a screen. Two worked examples sit beside it:
  `first-time-mobile-user.md` and `power-user-on-desktop.md`.
- A persona should come from real users (interviews, support tickets, analytics), not from
  imagination, and never from a real person's name or data.

## Stories: the project's stories.json, as is

The foundry-sdlc `gen_stories.py` writes it (a list, or `{"stories": [...]}`). Per story the
script reads `id`, `title`, `acceptance`, `surfaces`, `devices`, `status`, and an optional `qa`
block. Example with one scripted story: `templates/stories.example.json`.

| Story has | What the run does |
|---|---|
| no `qa` block | opens `surfaces[0]` (when it is a path such as `/groups` or `#/create`), waits for the page to settle, screenshots it: **needs-judgment** against `acceptance` |
| `qa: {start, steps, assertions, wait_for}` | opens `qa.start` (default `surfaces[0]`), runs the steps (done-journey format), checks the assertions: passed or failed |
| `status` NOT_BUILT or PARKED | not run (listed under "Not run"), unless you name it with `--story` |
| a device that is not a web profile (`ios-sim`, `android-emu`) | that device is skipped with a warning |
| an unknown key | ignored with a warning, never rejected |

## Run

```bash
# print the story x device matrix, run nothing
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" --persona qa/personas/first-time-mobile-user.md \
  --stories product/stories.json --base-url <url> --plan

# run it
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" --persona qa/personas/first-time-mobile-user.md \
  --stories product/stories.json --base-url <url>

# narrower, the Safari engine, or a signed-in app (see the done-gate skill, "Signed-in apps")
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" ... --story US-02 --devices phone-390x844 --browser webkit
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" ... --storage-state .qa/auth.json

# after two runs: ticket only the failures that repeated
python3 "${CLAUDE_SKILL_DIR}/scripts/persona_run.py" ... --file-tickets
```

Signed-in apps: `--storage-state FILE`, `--header "Name: value"` or `--auth FILE` (an `auth:`
block, for example your done-journey). Make the storage state with
`python3 "${CLAUDE_SKILL_DIR}/scripts/qa_session.py" login --url <sign-in url> --out .qa/auth.json`.

**Timing.** Checks and the screenshot happen after the page settles: no request for 500 ms,
then the story's `qa.wait_for` (or `--wait-for`) selector, then `--settle-ms` (default 800).
The patience check measures navigation start to content ready (the last data request done, or
the selector visible), not the load event.

Output: `.qa/persona/<persona-name>/` with `REPORT.md`, `results.json` (including
`site_findings`, `skipped` and `warnings`), a screenshot per story and device, and
`tickets/<story>-<device>.md` when `--file-tickets` finds a repeat failure.

**Read-only by default.** Every POST, PUT, PATCH and DELETE is answered inside the browser and
never sent. `--allow-writes` is refused for anything but localhost. A simulated write proves
only that the UI responded.

## Statuses and exit codes

- `passed`: every assertion and story check (patience, overflow, console) held
- `failed`: an assertion, step or story check failed
- `needs-judgment`: no mechanical assertions; a person or agent must judge the screenshot
- `inconclusive`: nothing was proven (unreachable, sign-in failed, harness error)

Tap targets under the persona's `min_tap_target_px` are a **site-wide** check: REPORT.md lists
them once per device as warnings and they never change a story's status. The WCAG 2.5.8 floor
(24 px) is checked by the a11y-check skill.

Exit `0` no failures, `1` at least one failure, `2` config error (including Playwright
missing, with the fix printed), `6` nothing failed but something was inconclusive or no story
ran.

## Acceptance check

- The run used the project's stories.json and a persona from the project, not the templates.
- Every `needs-judgment` row has a written JUDGED PASS or JUDGED FAIL with one sentence of why.
- No real write reached a non-local server.
