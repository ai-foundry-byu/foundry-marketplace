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

Install the browser tooling the scripts use (once per machine):

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
| `done-gate` | skill | Definition-of-done gate: deployed SHA check, then a Playwright journey on each device, strict exit codes | ship / verify | proven |
| `regression-check` | skill | Stack-neutral blast-radius method: grep every consumer, judge each, behavior-test the at-risk ones | build / verify | proven |
| `a11y-check` | skill | axe-core in a real browser plus a manual WCAG 2.2 AA floor checklist | verify | proven |
| `visual-baseline` | skill | Screenshot baselines, pixel diff with threshold and tolerance, deliberate approve step | verify | proven |
| `web-qa` | agent | Drives the app with Playwright: journeys, a11y, visual, console and network errors, mobile emulation; files findings with repro steps | verify | proven |
| `persona-tester` | agent | Tests every user story as a persona across device profiles, read-only by default; reports judged versus passed; tickets repeated failures | verify / user acceptance | proven |
| `explorer` | agent | Curious-human crawler plus a manual probe list: edge cases, empty states, Back, refresh, double submit | verify | proven (pattern) |
| `scripts/done_gate.py` | script | The gate itself (journey runner, SHA check, read-only guard) | ship / verify | proven |
| `scripts/persona_run.py` | script | Persona story runner with persona checks and ticket filing | verify | proven |
| `scripts/a11y_check.py` | script | axe-core runner | verify | proven |
| `scripts/visual_baseline.py` | script | capture / compare / check / approve | verify | proven |
| `scripts/explore.py` | script | Same-origin read-only crawler | verify | proven (pattern) |
| `scripts/qa_yaml.py` | script | Dependency-free YAML subset parser so students do not need PyYAML | support | new |
| `templates/done-journey.yaml` | template | Annotated journey to copy into your repo | ship | new |
| `templates/stories.example.json` | template | Example user stories for persona runs | requirements / verify | new |
| `templates/personas/*.md` | template | Persona template plus two examples: first-time mobile user, power user on desktop | requirements / verify | new |

### What "maturity" means here

- **proven**: generalized from a tool that runs in production in our own Claude Code harness
  today. The method and the exit-code contracts come from that tool. The code in this plugin is
  a fresh, dependency-light rewrite of it for public use, tested against a fixture site in a
  real browser (see Tests below).
- **proven (pattern)**: the approach runs in production in our harness; this version's
  details (the crawl signals and probe list) were written for this marketplace.
- **new**: written for this marketplace from documentation and best practice, not yet
  battle-tested.

## How to use each item

### done-gate (skill)

Ask: "run the done gate on the signup feature" or "is this done? prove it". The skill walks
the agent through writing `qa/done-journey.yaml` and running:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/done_gate.py" --journey qa/done-journey.yaml --base-url http://localhost:3000
```

Against a deployed build, with the commit check and production-safe read-only mode:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/done_gate.py" --journey qa/done-journey.yaml \
  --base-url https://<your-app>.example.com \
  --sha-url https://<your-app>.example.com/api/version --sha-json-key commit --read-only
```

Exit codes: `0` pass, `1` journey fail, `2` config error, `3` SHA mismatch, `6` inconclusive.
**Only say "done" on exit 0. Inconclusive is not a pass.** Evidence goes to `.qa/done-gate/`.

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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/a11y_check.py" --url http://localhost:3000/signup --devices desktop-1440x900,phone-390x844
```

Exit `0` clean at `--fail-on serious`, `1` blocking violations, `2` config, `6` inconclusive.
Then the agent walks the manual WCAG 2.2 AA checklist in the skill (keyboard, focus, labels,
contrast, zoom, target size, motion).

### visual-baseline (skill)

Ask: "check for visual regressions on home and pricing".

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/visual_baseline.py" check --url http://localhost:3000/ --name home --devices desktop-1440x900,phone-390x844
```

First run exits `6` (no baselines). Look at `.qa/visual/current/`, then `approve`. After that,
`check` exits `1` on a diff over threshold and writes red-highlight images to `.qa/visual/diff/`.

### web-qa (agent)

Ask: "use web-qa to QA the checkout flow on localhost" or "QA prod after the deploy
(read-only)". It plans journeys from your acceptance criteria, runs journeys, axe, visual and
a crawl, reads the screenshots, re-runs failures, and files findings with numbered repro steps
in `.qa/findings.md`.

### persona-tester (agent)

Copy the templates into your project:

```bash
mkdir -p qa/personas && cp "${CLAUDE_PLUGIN_ROOT}"/templates/personas/*.md qa/personas/ && cp "${CLAUDE_PLUGIN_ROOT}/templates/stories.example.json" qa/stories.json
```

Edit them to match your real users and stories, then ask: "use persona-tester to test every
story as the first-time mobile user on staging". Under the hood:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/persona_run.py" --persona qa/personas/first-time-mobile-user.md --stories qa/stories.json --base-url <url>
```

It is **read-only by default**: every POST/PUT/PATCH/DELETE is answered inside the browser and
never sent, so it is safe against production. `--allow-writes` is refused for anything but
localhost. It reports `passed`, `failed`, `needs-judgment` and `inconclusive` separately, and
the agent labels its own screenshot judgments JUDGED, never passed. `--file-tickets` writes a
ticket only for failures seen on two runs in a row.

### explorer (agent)

Ask: "use explorer to find bugs on localhost:3000". It runs the read-only crawler:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/explore.py" --url http://localhost:3000 --max-pages 30
```

then probes by hand (Back, refresh mid-flow, double submit, odd input, slow network, empty
states), with submit and double-submit probes only on local or staging.

### Running the scripts without the plugin (CI)

`${CLAUDE_PLUGIN_ROOT}` is filled in by Claude Code inside skills and agents. In CI or a plain
terminal, copy the `scripts/` folder into your repo (for example `qa/tools/`) and call it
there:

```bash
python3 qa/tools/done_gate.py --journey qa/done-journey.yaml --base-url "$PREVIEW_URL" --read-only
```

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

The unit tests (YAML parser, journey validation, SHA extraction and matching, the exit-code
contract, PNG codec, pixel diff, persona and story parsing, read-only rules, ticket logic,
crawler URL rules) need no browser. `test_browser_integration.py` starts a local fixture site
and runs every script in headless Chromium; it skips itself if Playwright or Chromium is not
installed, and the a11y case skips if axe-core cannot be downloaded.

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
- The persona judgments are an agent's reading of screenshots. They are labeled JUDGED for a
  reason: they are not a substitute for watching real users.

## License

MIT. Copyright AI Foundry, BYU Marriott School of Business.
