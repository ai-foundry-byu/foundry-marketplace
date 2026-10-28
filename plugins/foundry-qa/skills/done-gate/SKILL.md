---
name: done-gate
description: Definition-of-done gate for a user-facing web feature. Optionally verifies the deployed build serves the expected commit SHA, then drives the feature's done-journey (YAML or JSON) in a real browser with Playwright on desktop, phone and tablet profiles, saves screenshots to .qa/, and returns a strict exit code (0 pass, 1 journey fail, 2 config error, 3 SHA mismatch, 6 inconclusive). Use before saying a feature is "done", "shipped", "live", "working" or "fixed", when asked to "verify the deploy", "prove it works", "run the done gate", "check prod", or to write a done-journey for a feature.
---

# done-gate

A feature is done when a real browser can do the thing a user would do, on the build that is
actually deployed, and every assertion holds. Not when the code compiles, not when unit tests
pass, not when the diff looks right.

**The rule: only say "done" on exit 0.** Every other exit code means you are not done, and
you say which one you got.

| Exit | Meaning | What you say and do |
|---|---|---|
| 0 | PASS: SHA verified (if configured) and the journey passed on every device | "Done. Done-gate passed on <devices>; evidence in .qa/done-gate/<run>/" |
| 1 | JOURNEY FAIL: a step or assertion failed on at least one device | Not done. Read the reason line and the screenshot, fix, re-run |
| 2 | CONFIG ERROR: bad arguments, invalid journey file, Playwright missing, git could not resolve HEAD | Not done. Fix the setup; nothing about the product was tested |
| 3 | SHA MISMATCH: the deployed build serves a different commit | Not done. You tested the wrong build or the deploy has not finished. Wait or redeploy, re-run |
| 6 | INCONCLUSIVE: target unreachable, no SHA readable, browser could not start, or bounced to a sign-in wall | **Not a pass.** Nothing was proven. Say "inconclusive" and why |

INCONCLUSIVE exists so the gate is never forced to guess. A gate that turns "I could not look"
into "looks fine" is worse than no gate. When one device fails and another is inconclusive,
the result is 1 (a failure is evidence; inconclusive is not).

## Setup (once per machine)

```bash
pip install playwright
python3 -m playwright install chromium        # add webkit for Safari-engine runs
```

No PyYAML needed: the gate ships a small YAML-subset parser and also accepts JSON.

The script lives at `${CLAUDE_SKILL_DIR}/scripts/done_gate.py`. For CI, copy this skill's
`scripts/` folder into your repo (for example `qa/tools/`) so the pipeline does not depend on a
plugin install. It only needs `done_gate.py` and `qa_yaml.py`.

## 1. Write the done-journey

One file per feature, kept in the repo next to the code (for example `qa/done-journey.yaml`).
Start from `${CLAUDE_SKILL_DIR}/templates/done-journey.yaml`.

```yaml
name: add an item to the cart
devices: [desktop-1440x900, phone-390x844, tablet-820x1180]
timeout_ms: 10000
steps:
  - goto: /products/blue-mug
  - click: "button:has-text('Add to cart')"
  - wait_for: "[data-testid=cart-count]"
  - fill: {selector: "#coupon", value: "STUDENT10"}
  - press: {selector: "#coupon", key: "Enter"}
assertions:
  - visible: "[data-testid=cart-count]"
  - text: {selector: "[data-testid=cart-count]", contains: "1"}
  - url_contains: /products/blue-mug
  - no_console_errors: true
screenshot: cart-add
auth_wall: [/login]
```

Format reference:

| Key | Values |
|---|---|
| `steps` (required, first must be `goto`) | `goto: <url or /path>`, `click: <selector>`, `fill: {selector, value}`, `wait_for: <selector>` (visible), `press: {selector, key}` (keys like `Enter`, `Tab`, `Escape`, `Control+A`) |
| `assertions` (at least one) | `visible: <selector>`, `text: {selector, contains}`, `url_contains: <string>`, `no_console_errors: true` |
| `devices` | `desktop-1440x900` (default), `phone-390x844` (touch, iPhone UA), `tablet-820x1180` (touch, iPad UA) |
| `screenshot` | file stem; screenshots land at `.qa/done-gate/<run>/<stem>-<device>.png` |
| `base_url` | used for relative `goto`; `--base-url` overrides it |
| `timeout_ms` | per step and per assertion (default 10000) |
| `auth_wall` | URL substrings meaning "sent to sign-in": result is 6, not 1 |
| `ignore_console` | regexes for console noise you have decided is harmless |
| `read_only` | `true` blocks every non-GET request (see below) |
| `sha_check` | `{url, header}` or `{url, json_key}` or `{url, regex}` |

Selectors are Playwright selectors: CSS (`#id`, `[data-testid=x]`), text (`text=Sign in`),
or `:has-text()`. **Quote every selector.** In YAML an unquoted value starting with `#` is a
comment, and one starting with `[` or `{` is a list or map.

Writing a good journey:
- Assert the outcome the user cares about, not that a click happened. "The cart shows 1" beats "the button was clicked".
- Prefer `data-testid` attributes over CSS classes that a restyle will rename.
- One journey per feature, short (5 to 10 steps). Long flows belong in your e2e suite.
- Include `no_console_errors: true` unless you have a reason not to.

Check the file without a browser:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/done_gate.py" --journey qa/done-journey.yaml --base-url http://localhost:3000 --validate
```

## 2. Run it locally

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/done_gate.py" --journey qa/done-journey.yaml --base-url http://localhost:3000
```

Output: one line per device (`PASS`, `FAIL`, `INCONCLUSIVE` plus the reason), then
`DONE-GATE: <verdict> (exit N)`. Evidence: `.qa/done-gate/<run>/result.json`, screenshots, and
`.qa/done-gate/latest.json`. Add `.qa/` to `.gitignore`.

## 3. Run it against the deployed build (SHA check)

Make the app report its commit. Any one of these works:
- a response header, for example `x-commit-sha` set from your CI's commit variable
- a JSON endpoint, for example `GET /api/version` returning `{"commit": "<sha>"}`
- a string in the HTML, for example `<meta name="build" content="<sha>">` (use `--sha-regex`)

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/done_gate.py" \
  --journey qa/done-journey.yaml \
  --base-url https://<your-app>.example.com \
  --sha-url https://<your-app>.example.com/api/version --sha-json-key commit \
  --expected-sha HEAD \
  --read-only
```

`--expected-sha HEAD` (the default) resolves with `git rev-parse HEAD`, so run it from the
commit you shipped. Short SHAs match by prefix (7+ characters). The gate retries
(`--sha-retries 3 --sha-wait 10`) because a deploy can take a minute to roll out; a mismatch
that persists is exit 3 and the journey does not run (testing the wrong build proves nothing).

**On production, always pass `--read-only`.** It answers every POST/PUT/PATCH/DELETE inside the
browser with `{"qaReadOnly": true}` and never sends it, so the gate cannot create orders,
send emails or delete data. The UI may then show a success state that did not really happen:
treat that as "the UI responded", and test the real write on localhost or staging.

## 4. Report

- Exit 0: say done, name the devices and the evidence folder.
- Anything else: say "not done", the exit code and its meaning, and the one-line reason the
  gate printed. Look at the screenshot before you guess at a fix.
- Never re-label a 6 as a pass, never delete an assertion to get a 0, and never claim the
  gate passed without running it in this session.

## Acceptance check for this skill

You used it correctly when: the journey file is committed, the last run's `latest.json` shows
`"exit_code": 0` for the commit you are calling done, and your message to the team quotes the
`DONE-GATE:` line.
