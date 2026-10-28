---
name: design-critique
description: Run the design gate on a UI change. A ruthless editor that asks "can this be removed" of every prompt, button, step and screen, grounded in an 8-question constitution (C1-C8), and resolves its own findings with a four-tier resolver instead of asking a human per decision. Use before building a UI change (critique the plan) and after building it (critique real screenshots), and to audit an existing surface. Triggers - "design critique", "design gate", "critique this UI", "is this screen too busy", "too many clicks", "simplify this flow", "can we cut a step", "review the UX before ship", "why does this feel cluttered".
---

# Design critique: the subtract-only editor

## Why this exists

AI agents ship features that are functional and tested while the end-user experience gets
worse. Tests check FUNCTION (it renders, it navigates, nothing overflows). Nobody checks
EXPERIENCE (you added a step, a dead button, a second screen that does the same job). Agents
generate; they do not edit. This skill is the missing editor.

## The one idea

**The critic may only SUBTRACT.** Allowed verbs: `remove`, `merge`, `relabel`, `inline`,
`escalate`. A finding that proposes ADDING a screen, button, step or control is invalid and is
rejected at parse time: the `proposal.type` enum in `${CLAUDE_SKILL_DIR}/findings.schema.json` has no `add`.
Generation is the builder's job. This is the editor.

## The 8 questions (ask every one, of every prompt, button and graphic)

| Id | Question | Short form |
|---|---|---|
| C1 | Can we remove a click? | interaction cost on the core flow |
| C2 | Is this label wrong? | the user's words, one name per action |
| C3 | Why is the user taking this step? | every step maps to the user's job, not the system's |
| C4 | Is context always present? | the user never loses their place or their key number |
| C5 | Is this navigation necessary? | a junction exists because the user needs it |
| C6 | Can we do this on one page? | primary action inline, rare things deferred |
| C7 | Can the user answer their own questions? | no manual needed |
| C8 | Two surfaces where one would do? | one component per job; a new surface names what it `replaces:` |

Full text, grounding (Nielsen, Krug, Fitts, Hick) and the blocking rules: `CONSTITUTION.md` in
this skill's directory (`${CLAUDE_SKILL_DIR}/CONSTITUTION.md`). Read it the first time you run the gate in a session.

## Set up a project for the gate (once, about 10 minutes)

Create a `design/` directory at the project root:

```
design/
  vocabulary.md          # approved words: "Save" not "Submit", "Project" not "Workspace"
  core-flows.md          # the 1-3 jobs that matter most, as numbered steps
  references/            # pinned right/wrong screenshots: good-*.png, bad-*.png
  decisions/             # one YAML file per ruling (template: ${CLAUDE_SKILL_DIR}/templates/decision.yaml)
  findings/              # one JSON array per critique run
```

`core-flows.md` example:

```markdown
## F1 Add a task (most frequent)
Goal: a new task is visible in the list.
Today: open app -> tap "+" -> type -> tap "Save"  (3 taps after first paint)
```

Optional but strongly recommended: the deterministic half (`${CLAUDE_SKILL_DIR}/scripts/design_gate.py`,
see "Post-build, part 1"). Start its config from the template:
`cp "${CLAUDE_SKILL_DIR}/templates/design-gate.config.json" design/design-gate.json`.
An example findings run is `${CLAUDE_SKILL_DIR}/templates/findings.example.json`.

## Pre-build run (cheapest: kill a surface for the price of a paragraph)

Before any UI code is written, read the plan, mockup or spec and ask C3, C5, C6 and C8 of the
PROPOSED change:

1. List every new screen, modal, step and control the plan adds.
2. For each one, ask: what user job does it serve (C3)? Could it live on an existing page (C6)?
   Does the user have to navigate to it (C5)? What existing surface does it replace (C8)?
3. A new surface with no `replaces:` answer gets a finding (`merge` or `inline`).
4. Accepted findings become constraints in the build prompt, written as prohibitions:
   "Do not add a settings screen. Inline the two options under the list header."

## Post-build run (real pixels)

### Part 1: objective, deterministic (the teeth, no model)

Run the plugin's design gate against your local app. It measures clicks-to-goal on your core
flows, dead controls, entry-point count, primary-button count, tap-target size, contrast and
horizontal scroll, and FAILS on any regression against a committed baseline:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/design_gate.py" run --config design/design-gate.json
```

Setup and config format: the script's `--help` and docstring, the template
`${CLAUDE_SKILL_DIR}/templates/design-gate.config.json`, and (when installed as a plugin) the
plugin README, section "design_gate.py". A regression may only be
accepted with `--bless` plus a decision-log entry that says why. If you cannot run Playwright,
say so and skip to part 2; never report a gate number you did not measure.

### Part 2: model pass (judgment)

1. Capture every changed surface: phone (390x844) and desktop (1440x900) screenshots of every
   state of the core flow (empty, populated, editing, error). Write a flow map: screen -> action
   -> screen.
2. Load `design/decisions/*.yaml`. Note every entry whose `surface` matches a surface you are
   about to critique. **Never re-raise a resolved finding on an unchanged surface.**
3. For EACH of C1..C8, examine every surface and write a verdict line, even when it is clean:
   `C3 route:/settings - clean` or `C3 route:/settings - finding df-007`. A per-question verdict
   makes silent rubber-stamping impossible.
4. Emit findings as a JSON array that validates against `${CLAUDE_SKILL_DIR}/findings.schema.json`. Rules:
   - Propose a subtraction or `escalate`. Never an addition.
   - Questions 1, 5, 6 and 8 (flow shape) require a `delta` with before/after counts.
   - Every finding cites a question plus a grounding (`constitution_refs`, `log_refs`, or a gate
     metric). A finding with no grounding is taste, and is downgraded to `escalate`.
   - At most 2 `nit` findings per run. Nits off the core flow can never block.
   - Do not claim anything about animation, latency or feel from a screenshot. Those are
     `escalate` only.
   - A clean pass (zero findings) is valid and common. Do not invent findings to look useful.
5. Validate the array:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_findings.py" design/findings/2026-01-15-settings.json
```

Exit 0 = valid. Exit 1 prints each violation (an `add` verb, a missing delta, a third nit).

## Resolve every finding: the four-tier resolver (cheapest first, no per-decision human gate)

1. **Objective metric.** Fewer clicks, fewer surfaces, context preserved, no constitution
   violation: it wins. The gate's numbers decide. Most findings die here.
2. **Constitution plus reference judge.** What numbers do not settle, rule by C1..C8 and the
   closest match in `design/references/`. You are applying captured taste, not inventing it.
3. **Adversarial panel** for real ties. Write two short arguments: a subtract-advocate, and a
   user-empathy advocate who role-plays the actual user doing the job. Then rule as the
   constitution judge, citing which argument the constitution favors.
4. **Empirical A/B.** Ship both behind a flag, measure the core-flow metrics, keep the winner.
   User behavior is the final arbiter.

Every resolution appends a file to `design/decisions/` (template:
`${CLAUDE_SKILL_DIR}/templates/decision.yaml`): the finding, the ruling, the reason, the
tier. Human input is batch calibration: a periodic digest of what changed and why, and a
thumbs-down that adds a reference image. A human tunes the model of their taste; they do not
approve pixels one at a time.

`severity: block` (an objective regression: more clicks on a core flow, a new surface with no
`replaces:`, a vocabulary or accessibility violation) hard-fails the build and never reaches the
judge. It is auto-fixed or reverted.

## Keep the gate honest

- **Plant a known-bad.** Once per milestone, add a deliberate regression on a branch (an extra
  click, a disabled button, a duplicate entry point) and confirm the gate fails. A gate that has
  never caught a planted defect is assumed dead.
- **Run the critic in a separate context from the builder.** The agent that wrote the screen is
  the worst judge of it. Use a subagent (for example this plugin's `ui-reviewer` for scoring,
  then this skill for the subtract pass).
- **Track three numbers:** clicks on core flows (flat or down), surface count (flat or down),
  and the share of accepted findings that actually shipped. If accepted-but-unshipped grows, the
  gate is producing homework, not product.

## Acceptance check for one critique run

- [ ] One verdict line per question per changed surface (8 x N lines).
- [ ] Findings file validates (`validate_findings.py` exit 0).
- [ ] Every flow-shape finding has before/after counts.
- [ ] Every resolved finding has a decision file with its tier.
- [ ] Gate part 1 either ran (numbers quoted) or is listed as "not run" with the reason.

## Related

- Aesthetic direction (typography choices, a point of view): Anthropic's official
  `frontend-design` skill in the `claude-plugins-official` marketplace. This critic edits; it does
  not set a visual style.
- Spec before build: this plugin's `ui-ux-spec` skill. Scored review: the `ui-reviewer` agent.
