# foundry-qa

Web QA for Claude Code, in code and with example users. It gives your agent a strict
definition of done, a way to find what a change could break, accessibility and visual
regression checks, and three QA agents that drive your app in a real browser.

Part of the [AI Foundry marketplace](https://github.com/ai-foundry-byu/foundry-marketplace).

## Install

Add the marketplace (once):

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the plugin:

```text
/plugin install foundry-qa@ai-foundry
```

Install the browser tooling the scripts use (once per machine, inside a virtual environment):

```bash
python3 -m venv .venv && . .venv/bin/activate
```

```bash
pip install playwright
```

```bash
python3 -m playwright install chromium
```

Optional, for Safari-engine runs:

```bash
python3 -m playwright install webkit
```

## What is in it

| Item | Type | What it does | SDLC stage | Maturity |
|---|---|---|---|---|
| `done-gate` | skill | Definition-of-done gate: deployed SHA check, then a Playwright journey on each device, strict exit codes | ship / verify | verified |
| `regression-check` | skill | Stack-neutral blast-radius method: grep every consumer, judge each, behavior-test the at-risk ones | build / verify | verified |
| `a11y-check` | skill | axe-core in a real browser plus a manual WCAG 2.2 AA floor checklist | verify | verified |
| `visual-baseline` | skill | Screenshot baselines, pixel diff with threshold and tolerance, deliberate approve step | verify | beta |
| `persona-run` | skill | Runs every user story as a persona on its devices, read-only; persona checks and repeat-failure tickets (used by persona-tester) | verify / user acceptance | verified |
| `explore` | skill | Read-only same-origin crawler for console errors, broken links, 5xx, overflow and empty states (used by explorer and web-qa) | verify | verified |
| `web-qa` | agent | Drives the app with Playwright: journeys, a11y, visual, console and network errors, mobile emulation; files findings with repro steps | verify | verified |
| `persona-tester` | agent | Tests every user story as a persona across device profiles, read-only by default; reports judged versus passed; tickets repeated failures | verify / user acceptance | beta |
| `explorer` | agent | Curious-human crawler plus a manual probe list: edge cases, empty states, Back, refresh, double submit | verify | beta |
| `skills/done-gate/scripts/done_gate.py` | script | The gate itself (journey runner, SHA check, read-only guard) | ship / verify | verified |
| `skills/persona-run/scripts/persona_run.py` | script | Persona story runner with persona checks and ticket filing | verify | verified |
| `skills/a11y-check/scripts/a11y_check.py` | script | axe-core runner | verify | verified |
| `skills/visual-baseline/scripts/visual_baseline.py` | script | capture / compare / check / approve | verify | beta |
| `skills/explore/scripts/explore.py` | script | Same-origin read-only crawler | verify | verified |
| `skills/done-gate/scripts/qa_yaml.py` | script | Dependency-free YAML subset parser so students do not need PyYAML | support | verified |
| `skills/done-gate/scripts/qa_session.py` | script | Shared browser-session helper: the `auth` block for signed-in apps (storage state, headers, cookies, login steps), the `login` helper that saves a storage state, the settle wait, and the Playwright-missing fix | support | verified |
| `skills/done-gate/templates/done-journey.yaml` | template | Annotated journey to copy into your repo | ship | verified |
| `skills/persona-run/templates/stories.example.json` | template | Example of the foundry-sdlc stories.json shape, with an optional `qa` block on scripted stories | requirements / verify | verified |
| `skills/persona-run/templates/personas/*.md` | template | Persona template plus two examples: first-time mobile user, power user on desktop | requirements / verify | verified |

Every script lives inside the skill that uses it, so each skill folder works on its own.
`done_gate.py`, `qa_yaml.py` and `qa_session.py` are shared: the canonical copies are in `skills/done-gate/scripts/`,
and byte-identical copies sit in the other skills that import them (`explore` also carries a
copy of `persona_run.py`). `vendor.json` lists every copy and its canonical file, and
`tests/test_vendor.py` fails if a copy drifts. Edit the canonical file, then re-copy.

### What "maturity" means here

The labels come from our test runs on 2026-10-28, recorded with what we ran in
[`evidence/evidence.json`](../../evidence/evidence.json). A script or template carries the
label of the skill that ships it.

- **verified**: the main path passed a live end-to-end run in a real Claude Code session, with
  no known major defect left on it. The method and exit-code contracts come from tools that run
  in production in our own harness; the code here is a fresh, dependency-light rewrite.
- **beta**: works with known gaps. `visual-baseline`: an agent once read the red diff marker as
  the page's colour, and the doc fix has not been re-run live. `explorer`: its fixes for finding
  a test sign-in route and reporting every crawler finding are not re-run live yet.
  `persona-tester`: in its one live run after the fixes it found 7 of 12 planted defects and
  4 of 8 story verdicts matched.
- **new**: little or no live testing yet.

## How to use each item

### done-gate (skill)

Ask: "run the done gate on the signup feature" or "is this done? prove it". The skill walks
the agent through writing `qa/done-journey.yaml` and running:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/done-gate/scripts/done_gate.py" --journey qa/done-journey.yaml --base-url http://localhost:3000
```

Against a deployed build, with the commit check and production-safe read-only mode:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/done-gate/scripts/done_gate.py" --journey qa/done-journey.yaml \
  --base-url https://<your-app>.example.com \
  --sha-url https://<your-app>.example.com/api/version --sha-json-key commit --read-only
```

Exit codes: `0` pass, `1` journey fail, `2` config error, `3` SHA mismatch, `6` inconclusive.
**Only say "done" on exit 0. Inconclusive is not a pass.** Evidence goes to `.qa/done-gate/`;
after every run the gate also writes `.qa/done-gate/last.json`
(`{sha, exit, journey, devices, stories, time, failures[]}`, `sha` = the git HEAD it ran from),
which the foundry-sdlc stage detector reads. The template's `base_url: http://localhost:PORT`
takes `--port 5173` (never the PORT environment variable).

Signed-in apps: add `auth` to the journey, or pass `--storage-state`, `--header` or `--auth FILE`
to any script. Save a storage state once with the login helper:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/done-gate/scripts/qa_session.py" login --url http://localhost:3000/login --wait-for "[data-testid=dashboard]" --out .qa/auth.json
```

For magic-link or OAuth sign-in, add a test-only sign-in route behind an environment flag that
is never set in production, and point `auth.login_steps` at it.

Journey format (YAML subset or JSON):

```yaml
steps:
  - goto: /
  - click: "text=Get started"
  - fill: {selector: "#email", value: "qa@example.com"}
  - press: {selector: "#email", key: "Enter"}
  - wait_for: "[data-testid=dashboard]"
assertions:
  - visible: "[data-testid=dashboard]"
  - text: {selector: "h1", contains: "Welcome"}
  - url_contains: /dashboard
  - no_console_errors: true
screenshot: signup
devices: [desktop-1440x900, phone-390x844, tablet-820x1180]
stories: [US-01]                      # optional metadata: the story ids this journey covers
# auth: {storage_state: .qa/auth.json} # optional: a signed-in session
```

### regression-check (skill)

Ask: "what could this change break?" or "run a regression check before we merge". The agent
lists what changed, greps every consumer, writes a consumer table with an at-risk verdict for
each, and runs the smallest test that proves each at-risk consumer still works. This method
comes from Scott Murff's
[agent-team-kit](https://github.com/ai-foundry-byu/agent-team-kit) (`skills/regression-check`),
which is written for a SvelteKit project; this is a stack-neutral version.

### a11y-check (skill)

Ask: "check accessibility on the signup page".

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/a11y-check/scripts/a11y_check.py" --url http://localhost:3000/signup --devices desktop-1440x900,phone-390x844
```

Exit `0` clean at `--fail-on serious`, `1` blocking violations, `2` config, `6` inconclusive.
Besides axe, the script runs its own WCAG 2.2 target-size check (2.5.8): a control under
24x24 CSS px with another target inside its 24 px circle is a blocking `target-size-2.5.8`
violation; a small but well-spaced one is listed as `small-targets` for manual review. Then the
agent walks the manual WCAG 2.2 AA checklist in the skill and reports each section as DONE,
FAILED or NOT DONE.

### visual-baseline (skill)

Ask: "check for visual regressions on home and pricing".

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/visual-baseline/scripts/visual_baseline.py" check --url http://localhost:3000/ --name home --devices desktop-1440x900,phone-390x844
```

First run exits `6` (no baselines). Look at `.qa/visual/current/`, then `approve`. After that,
`check` exits `1` on a diff over threshold and writes red-highlight images to `.qa/visual/diff/`.
The red is a marker for changed pixels, not the page's color: compare `current/` with
`baselines/` to say what changed (`report.json` gives the `changed_box`).

### web-qa (agent)

Ask: "use web-qa to QA the checkout flow on localhost" or "QA prod after the deploy
(read-only)". It plans journeys from your acceptance criteria (or one per core flow when there
are none), runs the done gate on desktop and phone, axe, a visual check and a crawl, reads the
screenshots, re-runs failures, and ends every run with the full text of `.qa/findings.md` in
one fenced block, each finding with a severity, numbered Repro steps and a `Reproduced: N of N`
line. The calling session saves that block to `.qa/findings.md` verbatim: Claude Code refuses a
subagent's Write of a report file, so the agent returns it as text. explorer and
persona-tester also report as text; their scripts write their own `.qa/` outputs. Plain
requests such as "QA this app like a tester" are meant to route to it.

### persona-tester (agent)

Copy the persona templates into your project:

```bash
mkdir -p qa/personas && cp "${CLAUDE_PLUGIN_ROOT}"/skills/persona-run/templates/personas/*.md qa/personas/
```

Edit them to match your real users, then ask: "use persona-tester to test every story as the
first-time mobile user on staging". It reads the project's ONE stories.json as is (the
foundry-sdlc format, `product/stories.json`; unknown keys are warnings, never errors). A story
with no steps or assertions opens **every** path in `surfaces`, checks and screenshots each,
and is judged against its acceptance criteria; a `qa: {start, steps, assertions, wait_for}`
block makes it scripted. A route pattern such as `/groups/:id` is never opened literally: add
`qa.params: {"id": 1}` or `qa.start: /groups/1`, otherwise the row is `inconclusive` "needs a
concrete URL (add qa.start)" rather than a false 404 failure. The agent reports one row per
story and device and judges every needs-judgment screenshot. Under the hood it runs the
`persona-run` skill:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/persona-run/scripts/persona_run.py" --persona qa/personas/first-time-mobile-user.md --stories product/stories.json --base-url <url>
```

Checks run after the page settles (network quiet, then `qa.wait_for`, then 800 ms), and the
patience check measures navigation start to content ready. Tap targets under the persona's
minimum are reported once per device as site-wide warnings, not as story failures.

The script is **read-only by default**: every POST/PUT/PATCH/DELETE its browser makes is
answered inside the browser and never sent. Only the script's guard is read-only, so the skill
and the agent forbid hand-written probes (curl, fetch, a Playwright script) that submit a form or
send a write. `--allow-writes` is refused for anything but localhost. It reports `passed`, `failed`, `needs-judgment` and `inconclusive` separately, and
the agent labels its own screenshot judgments JUDGED, never passed. `--file-tickets` writes a
ticket only for failures seen on two runs in a row.

### explorer (agent)

Ask: "use explorer to find bugs on localhost:3000". It runs the read-only crawler from the `explore` skill:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/explore/scripts/explore.py" --url http://localhost:3000 --max-pages 30
```

It crawls hash routes (`#/group/1`) as pages and keeps each page's console and network errors
on that page. Phone and tablet overflow compares `scrollWidth` with
`document.documentElement.clientWidth`, so a 939 px page on a 390 px phone is caught (mobile
emulation widens `window.innerWidth` to the content, which hid it before). The Back-button check
never clicks a skip link or `#anchor`, and skips a click that does not navigate within 3 s. The
agent carries every crawler `error` and `warn` into its report. Then the agent always runs four probes on the core flow (Back after a search keeps
its state, a slow first load shows a loading indicator, the empty state has a message, double
submit), then the rest of its list (refresh mid-flow, odd input, deep links), with submit and
double-submit probes only on local or staging.

### Running the scripts without the plugin (CI)

`${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` are filled in by Claude Code inside skills
and agents. In CI or a plain terminal, copy one skill's `scripts/` folder into your repo (for
example `skills/done-gate/scripts/` to `qa/tools/`; each folder already holds every module its
script imports) and call it there:

```bash
python3 qa/tools/done_gate.py --journey qa/done-journey.yaml --base-url "$PREVIEW_URL" --read-only
```

### Install one item on its own

Every skill works copied on its own: copy `skills/<name>/` into your project's
`.claude/skills/` (or `~/.claude/skills/`). Each skill folder holds its scripts and templates,
and its SKILL.md points at them through `${CLAUDE_SKILL_DIR}`.

| Item | On its own |
|---|---|
| `done-gate`, `a11y-check`, `visual-baseline`, `persona-run`, `explore`, `regression-check` (skills) | standalone |
| `web-qa` (agent) | needs skills `done-gate`, `a11y-check`, `visual-baseline`, `explore` (it skips a job whose skill is missing and says so) |
| `persona-tester` (agent) | needs skill `persona-run` |
| `explorer` (agent) | needs skill `explore` |
| plugin only | nothing: this plugin has no hooks, MCP server or compiled helper |

To copy an agent, put `agents/<name>.md` in `.claude/agents/` (or `~/.claude/agents/`) and the
skills it lists under `Requires skill:` in `.claude/skills/`. The agent finds them there.

## Requirements

- Python 3.9 or newer. Standard library only, except Playwright for anything that opens a browser.
- Playwright for Python and a browser build (`python3 -m playwright install chromium`).
- `a11y_check.py` downloads a pinned axe-core build from cdnjs once (cached in `.qa/cache/`),
  or uses a local file via `--axe-source`.
- Optional: Pillow speeds up decoding of very large screenshots. Not required.
- Add `.qa/` to your project's `.gitignore` (screenshots can contain real data). Commit
  `.qa/visual/baselines/` only if you want baselines in git; otherwise point `--root` elsewhere.

## Tests

From the plugin directory:

```bash
cd tests && python3 -m unittest -v
```

The unit tests (vendored copies match their canonical files, YAML parser, journey validation
including the foundry-sdlc template keys, `last.json`, SHA extraction and matching, the
exit-code contract, PNG codec, pixel diff, persona and foundry-sdlc stories.json parsing,
site-wide checks, route patterns and `qa.params`, the auth block and login-step validation, the
Playwright-missing fix, read-only rules, ticket logic, crawler URL rules for hash routes and the
Back-check target choice) need no browser. `test_browser_integration.py` starts a local fixture site
and runs every script in headless Chromium, including a list that loads 1.2 s after the load
event, a hash-routed page, a hash app with a skip link, a page 939 px wide at a 390 px phone, a
story with several surfaces and one with a route pattern, and a page behind sign-in (headers, cookies, login steps and a saved
storage state); it skips itself if Playwright or Chromium is not installed, and the a11y cases
skip if axe-core cannot be downloaded.

Maturity note: signed-in sessions (`qa_session.py`), the 2.5.8 target-size check, hash-route
crawling and the settle wait were used in live student-journey runs as well as against the
fixture sites.

## Known limitations

- The YAML parser is a subset: no block scalars (`|`, `>`), anchors or tags. Quote selectors.
  Use JSON if you prefer.
- `--read-only` answers blocked writes with a fake `200 {"qaReadOnly": true}`. Apps that expect
  a specific response shape may show an error state instead of success. Either way, a simulated
  write proves only that the UI responded.
- The read-only guard sees HTTP requests the page makes. It cannot stop writes sent over
  WebSockets or by a service worker that was already installed, or server-side effects of a GET.
  Never rely on it alone against a production app that changes data on GET.
- Device profiles emulate viewport, touch and user agent in Chromium. They are not real devices.
  Run `--browser webkit` for Safari-engine behavior, and test on a real phone before launch.
- Visual baselines are sensitive to OS fonts and browser version. Capture baselines and checks
  in the same environment.
- axe-core catches only part of WCAG. The manual checklist is not optional.
- The QA agents look for a documented test-only sign-in route (README, `docs/`, stories
  `notes`) before giving up on signed-in pages, so describe yours there. They keep probes, cookie
  jars and temp files under `.qa/` and never search outside the project.
- A console 404 your story expects counts as a failure unless the story lists it in
  `qa.expect_console` (substrings, matched against each console error).
- Claude Code refuses a subagent's Write of a report file. web-qa returns `.qa/findings.md` as
  one fenced block for the calling session to save; if the session does not save it, the file
  is not there. In our test the main session printed the list after a background run instead
  of saving it, so ask it to save the block.
- The persona judgments are an agent's reading of screenshots. They are labeled JUDGED for a
  reason: they are not a substitute for watching real users.

## License

MIT. Copyright AI Foundry, BYU Marriott School of Business.
