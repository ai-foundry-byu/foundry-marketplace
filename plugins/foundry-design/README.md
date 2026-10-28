# foundry-design

Design quality gates for Claude Code. Agents are good at generating screens and bad at editing
them: they ship features that pass every functional test while the experience gets worse (an
extra step, a dead button, a second panel that does the same job, gray-on-gray text). This
plugin adds the missing editor, a spec step before the build, and a scored review after it.

| Item | Type | What it does | SDLC stage | Maturity |
|---|---|---|---|---|
| `design-critique` | skill | Subtract-only critic: 8-question constitution (C1-C8), findings schema, four-tier resolver, decision log | build (pre-build) and visual QA | proven |
| `ui-ux-spec` | skill | Turns a user story into a buildable UI spec: layout per breakpoint, full state matrix, keyboard and touch, copy, tokens, machine-checkable acceptance checks | design / pre-build | proven |
| `design-system` | skill | Fill-in template for your design system (tokens, contrast table, type scale, spacing, components, vocabulary) that the other items grade against | design | new |
| `ui-reviewer` | agent | Read-only REVIEW: scores screenshots plus code on a 10-dimension 0-4 rubric, returns token-level must-fixes with file:line. Never edits source | visual QA / ship | proven |
| `design_gate.py` | script (in `design-critique`, vendored into `design-system`) | Deterministic gate: clicks-to-goal, dead controls, entry points, primary buttons, tap targets, contrast, horizontal scroll, context present; fails on regression vs a baseline | visual QA / CI | new (generalized from a proven per-project gate) |
| `validate_findings.py` | script (in `design-critique`) | Validates a critique findings file: no "add" verb, deltas on flow findings, nit cap, grounding | visual QA | new |
| `design-gate.config.json`, `findings.example.json`, `decision.yaml` | templates (in `design-critique/templates/`) | Starting files for the gate config, a findings run, and a decision-log entry | setup | new |

Maturity: **proven** means generalized from a tool that runs in production in our harness today.
**new** means written for this marketplace from docs and best practice, not yet battle-tested.
`design_gate.py` is the generalized form of a gate that runs in production for one of our apps;
the generic config-driven version, the contrast and target checks, and the validator are new.

## Install

Add the marketplace:

```
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the plugin:

```
/plugin install foundry-design@ai-foundry
```

Reload so the skills and agent appear (or restart Claude Code):

```
/reload-plugins
```

To try it from a local clone without installing:

```bash
claude --plugin-dir ./plugins/foundry-design
```

## How the pieces fit

```
user story -> ui-ux-spec (spec + acceptance checks)
           -> design-critique pre-build (C3/C5/C6/C8 on the plan)
           -> build
           -> design_gate.py (objective numbers, hard-fails regressions)
           -> ui-reviewer agent (scored rubric, must-fixes)
           -> design-critique post-build (subtract-only pass, decision log)
           -> ship
```

All project state lives in a `design/` directory at your repo root:

```
design/
  design-system.md        # from the design-system skill
  vocabulary.md           # one name per act
  core-flows.md           # the 1-3 jobs that matter, as steps
  design-gate.json        # gate config (copy skills/design-critique/templates/design-gate.config.json)
  design-baseline.json    # written by the gate's bless command, committed
  specs/<surface>.md      # from ui-ux-spec
  reviews/                # ui-reviewer reports and captures
  findings/               # design-critique runs (JSON arrays)
  decisions/              # one YAML per ruling
  references/             # pinned good-*.png / bad-*.png examples
```

## Install one item on its own

Every skill works when its folder is copied on its own into `.claude/skills/<name>/` or
`~/.claude/skills/<name>/`: each skill carries every file it runs or reads, referenced as
`${CLAUDE_SKILL_DIR}/...`.

| Item | Standalone? | Needs |
|---|---|---|
| `design-critique` skill | yes | nothing (holds `design_gate.py`, `validate_findings.py`, the schema and templates) |
| `ui-ux-spec` skill | yes | nothing |
| `design-system` skill | yes | nothing (carries a vendored copy of `design_gate.py` for the contrast math) |
| `ui-reviewer` agent | yes, with skills | the `ui-ux-spec` skill (rubric, floor) and the `design-critique` skill (gate); it tells you if either is missing |

This plugin has no hooks and no plugin-only items. Vendored copies are listed in `vendor.json`
and must stay byte-identical to their canonical file.

## Using each item

### design-critique (skill, proven)

Ask: "run the design critique on the settings page" or `/foundry-design:design-critique`.
Pre-build it critiques the plan; post-build it runs the gate, then examines every changed screen
against C1-C8 and writes a findings file. The critic may only propose `remove`, `merge`,
`relabel`, `inline` or `escalate`. Validate the findings:

```bash
python3 skills/design-critique/scripts/validate_findings.py design/findings/2026-01-15-settings.json
```

Inside a session the skill uses `${CLAUDE_SKILL_DIR}/scripts/...`, which Claude Code expands to
the skill's own folder. From a terminal, locate the scripts:

```bash
find "$HOME/.claude/plugins" "$HOME/.claude/skills" .claude/skills -path '*design-critique/scripts/*' -name '*.py' 2>/dev/null
```

For CI, copy `skills/design-critique/scripts/design_gate.py` and
`skills/design-critique/scripts/validate_findings.py` into your repo (MIT). Each is a single
stdlib file; `validate_findings.py` reads `../findings.schema.json` by default (pass `--schema`
to point elsewhere).

### ui-ux-spec (skill, proven)

Ask: "spec the checkout screen from story US-14" or `/foundry-design:ui-ux-spec`. It fills
`references/spec-template.md` into `design/specs/<surface>.md`, self-checks against
`references/floor-checklist.md`, and maps its acceptance checks to gate metrics.

### design-system (skill, new)

Ask: "set up our design system" or `/foundry-design:design-system`. It inventories the raw
values your code actually uses, collapses them into tokens, measures contrast for every
text/background pair, and writes `design/design-system.md` from the template. For choosing an
aesthetic direction on a greenfield product, use Anthropic's official `frontend-design` skill from
the `claude-plugins-official` marketplace; this plugin does not copy it.

### ui-reviewer (agent, proven)

Ask: "have the ui-reviewer score the dashboard against design/specs/dashboard.md". It captures
screenshots (via the gate or Playwright), reads the code, scores 10 dimensions 0-4, and returns a
verdict (`SHIP`, `SHIP AFTER MUST-FIXES`, `REWORK`, `REDESIGN`) with must-fixes that each carry
evidence, problem, a token-level fix and a verification step. It writes only under
`design/reviews/` and never edits product source. The rubric is
`skills/ui-ux-spec/references/rubric.md`.

### design_gate.py (script, new)

1. Install Playwright (only the measuring step needs it):

   ```bash
   python3 -m pip install playwright
   python3 -m playwright install chromium
   ```

2. Copy `skills/design-critique/templates/design-gate.config.json` to `design/design-gate.json` and edit `base_url`,
   `pages`, `flows` (click steps to a goal selector), `context_checks` and
   `selectors.primary_button`.
3. Start your app locally, then establish the baseline and commit it:

   ```bash
   python3 path/to/design_gate.py run --config design/design-gate.json --bless
   ```

4. On every UI change:

   ```bash
   python3 path/to/design_gate.py run --config design/design-gate.json
   ```

Exit codes: 0 pass, 1 regression or hard-limit violation, 2 config error, 3 refused a
non-local `base_url` (flows can write data, so the gate only drives localhost unless you set
`"allow_remote": true` for a read-only target).

Hard limits (fail even without a baseline, each can be set to `null` to rely on the baseline
only, which helps when adopting the gate on an existing app): one primary button per screen,
no horizontal scroll, zero targets under 44 px (touch) or 24 px (pointer), zero text under
4.5:1 (3:1 large), zero unlabeled buttons, every core flow reaches its goal. Regressions against
the baseline: any increase in clicks, dead controls, entry points or the counts above, any
context check or flow that stops holding, and any metric that disappears.

`check` and `bless` are stdlib only, so a collector in another language can write the metrics
JSON and reuse the comparison:

```bash
python3 design_gate.py check --current metrics.json --baseline design/design-baseline.json
```

Keep the gate honest: plant a known-bad on a branch (an extra click, a disabled button, a second
primary) and confirm the gate exits 1. The unit tests do exactly this.

## Tests

```bash
cd plugins/foundry-design
python3 -m unittest discover -s skills/design-critique/scripts/tests -v
```

44 tests: color math and WCAG contrast, page evaluation, hard limits, planted regressions,
config validation, the CLI, the findings validator, and one end-to-end Playwright run against a
local fixture page (skipped when Playwright or Chromium is not installed).

## Requirements

- Claude Code with plugin support.
- Python 3.9+ (stdlib) for the scripts.
- Playwright for Python plus a Chromium (or WebKit) build, only for `design_gate.py measure|run`
  and for the reviewer's own captures.

## Known limitations

- Contrast is computed from computed `color` and `background-color` only. Text over background
  images or gradients is counted as unknown, and element `opacity` and `mix-blend-mode` are
  ignored. Check those by eye.
- Clicks-to-goal counts the `click` steps you wrote in the config; it does not discover a shorter
  path. Keep flows written as the real user path.
- `entry_points` and `primary_buttons` depend on your selectors; a wrong selector silently counts
  0 (an invalid selector counts -1).
- The reviewer's screen-reader and latency claims are judgment, not measurement, unless you add
  tests for them; the agent labels them so.
- The design system template is a starting point, not a token pipeline: it does not generate CSS.

## License

MIT. Grounding references (WCAG, Nielsen heuristics, platform guidelines) are cited by link; no
third-party text is vendored.
