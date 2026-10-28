---
name: done-gate
description: Definition-of-done gate for a user-facing web feature. Optionally verifies the deployed build serves the expected commit SHA, then drives the feature's done-journey (YAML or JSON) in a real browser with Playwright on desktop, phone and tablet profiles, signed in when the app needs it, saves screenshots to .qa/, and returns a strict exit code (0 pass, 1 journey fail, 2 config error, 3 SHA mismatch, 6 inconclusive). Use before saying a feature is "done", "shipped", "live", "working" or "fixed", when asked to "check that it really works end to end", "test it end to end", "does it work on a phone", "make sure it works on mobile and desktop", "verify the deploy", "prove it works", "run the done gate", "check prod", or to write a done-journey for a feature.
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
| 2 | CONFIG ERROR: bad arguments, invalid journey file, Playwright or its browser missing (the fix is printed), `PORT` with no `--port`, missing storage-state file, git could not resolve HEAD | Not done. Fix the setup; nothing about the product was tested |
| 3 | SHA MISMATCH: the deployed build serves a different commit | Not done. You tested the wrong build or the deploy has not finished. Wait or redeploy, re-run |
| 6 | INCONCLUSIVE: target unreachable, no SHA readable, browser could not start, or bounced to a sign-in wall | **Not a pass.** Nothing was proven. Say "inconclusive" and why |

INCONCLUSIVE exists so the gate is never forced to guess. A gate that turns "I could not look"
into "looks fine" is worse than no gate. When one device fails and another is inconclusive,
the result is 1 (a failure is evidence; inconclusive is not).

## You MUST

1. Run the gate before you say done, and quote its `DONE-GATE:` line. Only exit 0 is done.
2. Run it on every device in the journey, phone included (`phone-390x844`). "Works on a phone"
   means the gate passed on the phone profile.
3. No hosting (a class or local project)? Start the app from a committed SHA on a local port and
   run the gate against it (`--port N`). Say that it ran on a local build.
4. Signed-in app? Give the gate a session (`auth`, section 4). A page you could not reach is
   never a pass.
5. Never delete an assertion to get a 0, and never re-label a 6 as a pass.

## Setup (once per machine)

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install playwright
python3 -m playwright install chromium        # add webkit for Safari-engine runs
```

If Playwright or its browser is missing, every foundry-qa script exits 2 and prints these
lines instead of a stack trace. No PyYAML needed: the gate ships a small YAML-subset parser
and also accepts JSON.

The script lives at `${CLAUDE_SKILL_DIR}/scripts/done_gate.py`. For CI, copy this skill's
`scripts/` folder into your repo (for example `qa/tools/`) so the pipeline does not depend on a
plugin install. It needs `done_gate.py`, `qa_yaml.py` and `qa_session.py`.

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
| `base_url` | used for relative `goto`; may hold `PORT` (`http://localhost:PORT`, filled by `--port`); `--base-url` overrides it |
| `stories` | story ids the journey covers (`[US-01]`); metadata for the story-verifier |
| `auth` | a signed-in session, see section 4 |
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
`DONE-GATE: <verdict> (exit N)`. Evidence: `.qa/done-gate/<run>/result.json`, screenshots,
`.qa/done-gate/latest.json` (the full result) and `.qa/done-gate/last.json`, written after every
run except `--validate`: `{sha, exit, journey, devices, stories, time, failures[]}`, where `sha`
is the git HEAD the gate ran from (null outside git). The foundry-sdlc stage detector reads
`last.json`. Add `.qa/` to `.gitignore`.

With `base_url: http://localhost:PORT` (the template), pass the port your app runs on:
`--port 5173`. The gate never reads PORT from the environment, so a stray PORT cannot point it
at some other server.

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

## 4. Signed-in apps (`auth`)

The same `auth` block works in every foundry-qa script: as a journey key, or through
`--auth FILE` (any file that holds one). Pick one form:

```yaml
auth: {storage_state: .qa/auth.json}                       # saved by the login helper below
auth: {headers: {Authorization: "Bearer ${QA_TOKEN}"}}     # ${VAR} is read from the environment
auth: {cookies: [{name: session, value: "${QA_SESSION}"}]} # domain and path default to base_url
auth: {login_steps: [{goto: /login}, {fill: {selector: "#email", value: "qa@example.com"}}, {click: "button[type=submit]"}]}
```

Shortcuts: `--storage-state .qa/auth.json`, `--header "X-QA-Token: <value>"`. `login_steps`
run before the read-only guard switches on, so the sign-in POST goes through; nothing else does.

Make the storage state once with the login helper, scripted or by hand (it opens a browser
window, you sign in, it saves when the selector appears):

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/qa_session.py" login --url http://localhost:3000/login --steps qa/login.yaml --out .qa/auth.json
python3 "${CLAUDE_SKILL_DIR}/scripts/qa_session.py" login --url http://localhost:3000/login --wait-for "[data-testid=dashboard]" --out .qa/auth.json
```

The saved file is a live session: keep it in `.qa/` (gitignored) and use a QA test account,
never a real user's.

**Magic-link or OAuth sign-in** cannot be scripted against the real provider. Add a test-only
sign-in route that signs in a fixed QA account, guarded by an environment flag that is never
set in production (for example `QA_LOGIN=1` on localhost or a preview only), and point
`login_steps` at it: `[{goto: /test-login}, {wait_for: "[data-testid=app-shell]"}]`.

## 5. Report

- Exit 0: say done, name the devices and the evidence folder.
- Anything else: say "not done", the exit code and its meaning, and the one-line reason the
  gate printed. Look at the screenshot before you guess at a fix.
- Never re-label a 6 as a pass, never delete an assertion to get a 0, and never claim the
  gate passed without running it in this session.

## Acceptance check for this skill

You used it correctly when: the journey file is committed, `.qa/done-gate/last.json` shows
`"exit": 0` with the `sha` of the commit you are calling done, and your message to the team
quotes the `DONE-GATE:` line.
