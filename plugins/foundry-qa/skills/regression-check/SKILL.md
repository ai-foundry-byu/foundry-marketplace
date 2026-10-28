---
name: regression-check
description: Stack-neutral blast-radius check before calling a change done. Maps every consumer of what you changed (functions, exports, API routes, env vars, config keys, database columns, CSS classes, CLI flags) with grep, judges whether each one relies on the behavior you changed, and behavior-tests the at-risk ones. Use before declaring done on any edit to shared code, when asked "what could this break", "check for regressions", "blast radius", "who uses this", or after changing a signature, schema, route, or shared component.
---

# regression-check

A one-line edit to shared code can quietly break something three folders away that imports
it. Type checkers and unit tests catch some of that. This skill catches the rest by making
you **find every consumer, judge each one, and test the ones at risk** before you say done.

Origin: this is the blast-radius pattern from Scott Murff's agent-team-kit for the BYU AI
Foundry ([ai-foundry-byu/agent-team-kit](https://github.com/ai-foundry-byu/agent-team-kit),
`skills/regression-check`). That version is written for a SvelteKit project. This one is a
stack-neutral rewrite of the same method. If your project uses the kit, use its version.

## When to run it

Run it when the change touches something another part of the code depends on:
- an exported function, class, hook or component (its signature, return shape, defaults, errors)
- an API route or response shape, a webhook payload, an event name
- a database table or column, a migration, a query helper
- an environment variable, config key, feature flag or CLI flag
- a shared CSS class, design token or layout component
- a script, cron job or CI step that other steps chain off

Skip it for leaf changes nobody else consumes (a new page nothing links to, copy edits, a
private helper used in one file). Do not ceremony-tax trivial edits.

## Step 1: map the blast radius (find, do not guess)

List exactly what changed:

```bash
git diff --stat main...HEAD
git diff main...HEAD | grep -E '^[-+].*(export|def |function |class |interface |type |route|env|process\.env|os\.environ)'
```

Then grep for every consumer of each changed name. Use `rg` (ripgrep) if you have it, `grep -rn` otherwise. Exclude build output:

```bash
# a function, component or export
rg -n "\bformatPrice\b" --glob '!node_modules' --glob '!dist' --glob '!.next' --glob '!build'

# a module path (who imports the file you changed)
rg -n "from ['\"].*lib/pricing['\"]|require\(['\"].*lib/pricing['\"]\)|import .*pricing"

# an API route (callers in the frontend, tests, other services)
rg -n "/api/orders" --glob '!node_modules'

# an env var or config key
rg -n "STRIPE_WEBHOOK_SECRET|stripeWebhookSecret"

# a database column (writers AND readers, including raw SQL and ORM models)
rg -n "\bdiscount_cents\b|discountCents"

# a CSS class or token
rg -n "\bbtn-primary\b|--color-accent"
```

Also check the places grep is likely to miss:
- dynamic access (`obj[key]`, `getattr`, string-built route names), templates, and config files (YAML, JSON, `.env.example`)
- other repos or services that call your API (mobile app, a separate worker, a partner integration)
- scheduled jobs, CI workflows (`.github/workflows/*`), and seed or fixture data
- docs and READMEs that tell humans to use the old name

Write the consumer list down, one per line. **A long list is a signal the change is risky:
test more, not less.**

## Step 2: judge each consumer (one line each)

For each consumer answer: *does my change alter behavior this consumer relies on?*

Common silent breakers:
- changed signature, argument order, return shape or default value
- a field renamed or removed from a JSON response or a database row
- `null` or an empty list where there used to be a value (or the reverse)
- a different error type or status code (callers may catch the old one)
- stricter validation that now rejects input a caller still sends
- sync to async, new ordering, new latency, a timeout that is now shorter
- a CSS change that shifts layout on a page you did not open

Write it as a table in your notes:

| Consumer | Relies on | At risk? | Why |
|---|---|---|---|
| `app/cart/page.tsx:42` | `formatPrice` returns a string | yes | now returns `{text, currency}` |
| `tests/pricing.test.ts` | same | yes | asserts on string output |
| `emails/receipt.html` | `discount_cents` column | no | column unchanged |

## Step 3: behavior-test the at-risk ones

For every "yes", run the smallest test that proves the behavior still holds. An actual run
beats reasoning:
- run that consumer's existing tests (`npm test -- cart`, `pytest tests/test_cart.py`, `go test ./cart/...`)
- if it has none, call the changed function with a real input from the consumer and check the shape
- for an API change, hit the route the way the caller does (`curl -s localhost:3000/api/orders | jq .`) and compare to what the caller reads
- for a database change, write a row and read it back through the consumer's query
- for a UI change, open the consumer page in a browser: use the `done-gate` skill with a short journey, or the `visual-baseline` skill to catch layout shifts on pages you did not mean to touch

Then run the project's normal nets (type check, lint, unit tests, e2e tagged critical) as the
last step, not the first. They are the backstop, not the method.

## Output

End with a short note in your summary:

> **Changed:** `formatPrice` now returns `{text, currency}`.
> **Consumers (5):** cart page, checkout page, receipt email, admin export, pricing tests.
> **At risk (3):** cart, checkout, pricing tests. **Tested:** cart and checkout done-journeys pass on desktop and phone; pricing tests updated and green.
> **Result:** no regressions found.

If you find a break, fix it in the same change. Do not ship the shared change and leave the
breakage as a follow-up ticket.

## Acceptance check

You ran this skill when your summary names the consumers you found (with file paths), says
which were at risk and why, and names the test or run that proved each at-risk one still works.
