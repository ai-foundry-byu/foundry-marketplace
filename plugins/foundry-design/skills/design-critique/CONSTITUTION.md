# Design constitution (shared, v0.1)

The law the design gate enforces, written as testable rules. Every project inherits this file.
Project-specific taste (approved vocabulary, past rulings, reference screenshots) lives in that
project's `design/` directory, not here.

The 8 questions are the primary axis. Nielsen's heuristics and a few classic laws are the
secondary sweep.

## The prime directive

**The critic may only SUBTRACT.** Its five verbs are `remove`, `merge`, `relabel`, `inline` and
`escalate`. A finding that proposes adding a screen, button, step or control is invalid and is
rejected at parse time. Generation belongs to the builder. The critic removes.

## The 8 questions

- **C1. Can we remove a click?** Minimize interaction cost on the core flows. A step that exists
  for the system's convenience rather than the user's job is a defect. The "3-click rule" is a
  myth; the real distinction is mindless clicks (fine) versus clicks that make the user stop and
  think (costly). Grounding: Krug, *Don't Make Me Think*; NN/g on interaction cost.
- **C2. Is this label wrong?** Use the user's language, and give each action one name
  everywhere. Labels are the highest-leverage copy on a screen: when the first click is right,
  users usually finish the task. Grounding: Nielsen #2 (match the real world), #4 (consistency).
- **C3. Why is the user taking this step?** Every step maps to the user's job to be done, not
  to the system's needs (collect a setting, show a menu, confirm a choice that could be undone).
  If a step fails the walkthrough, cut it. Grounding: cognitive walkthrough; jobs to be done.
- **C4. Is context always present?** The user never loses their place or the number they care
  about, and never has to remember something from a previous screen. Each project names its key
  context in `design/core-flows.md` (for example "the cart total is visible on every checkout
  step"). Grounding: Nielsen #1 (visibility of status), #6 (recognition over recall).
- **C5. Is navigation necessary, or improvable?** A junction exists because the user needs to
  choose, not because screens accreted over time. Grounding: Nielsen #3, #7; information scent.
- **C6. Can we do this on one page?** Show the primary action inline; defer the rare. Never
  split one job across pages to make each page look simpler.
- **C7. Can the user answer their own questions?** If a user must ask "what does this do?", the
  UI failed. Good design needs no manual. Grounding: Nielsen #10 (help), #5 (error prevention).
- **C8. Two surfaces where one would do?** One component per job. A new surface must name the
  surface it replaces (`replaces:`). Duplicate surfaces are the accretion signature of
  agent-built software: each agent adds its own panel and none removes the old one.

Residue checks (secondary): **Fitts's law** (primary actions large and near the point of
decision) and **Hick's law / choice overload** (every visible option taxes every user).

## Blocking rules (objective, never reach the judge)

These hard-fail the build. They are fixed or reverted, not debated:

1. A click-count increase on a core flow, measured by the gate.
2. A new surface with no `replaces:`.
3. A violation of `design/vocabulary.md` (a banned word, or one action named two ways).
4. An accessibility floor violation on a core flow (contrast, target size, keyboard reach).
5. A missing empty state (a blank region where data could be absent).

## Autonomous resolution

The loop closes itself. A design call is resolved by the four-tier resolver, cheapest first:

1. **Objective metrics:** click count, surface count, steps to first value, context present.
2. **Constitution plus reference judge:** C1..C8 and the nearest pinned example in
   `design/references/`.
3. **Adversarial panel:** a subtract-advocate against a user-empathy advocate who role-plays the
   real user against the job; the judge rules.
4. **Empirical A/B:** ship behind a flag, measure, keep the winner.

Human input is **batch calibration**, not a gate: a periodic digest of what the loop changed and
why, and a thumbs-down that refreshes the references or this file.

## The honest limit

Pure aesthetics and novel interactions are weak spots for agents. This constitution fences them
three ways: subtract-only (no invented surfaces), reference matching for visual voice, and a ban
on the critic proposing novel interactions. For aesthetic direction use a dedicated skill such as
Anthropic's `frontend-design`; this file governs friction, not style.

## How taste compounds

Every ruling becomes a file in `design/decisions/` with the reason written plainly. The critic
loads matching entries each run and never re-raises a rejected finding on an unchanged surface.
A ruling that recurs in three or more projects is promoted into this constitution. That is the
loop: taste, then log, then law.
