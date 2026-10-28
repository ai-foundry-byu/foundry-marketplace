---
name: ui-ux-spec
description: Turn a user story or job into a buildable UI spec before any code is written - layout per breakpoint, the full state matrix (default, hover, focus, pressed, disabled, loading, empty, error, stale, offline, long content), keyboard and touch maps, exact copy, design tokens, and machine-checkable acceptance checks the build is graded on. Use before building a new screen or reshaping an existing one. Triggers - "spec this screen", "design spec", "UI spec", "spec the UI before we build", "write the interaction spec", "what states does this need", "acceptance criteria for this page", "design this screen".
---

# UI/UX spec: say what good looks like before anyone builds

## Why this exists

A screen that passes every functional test can still be terrible to use. The cheapest place to
fix that is before the build, in a document a builder can implement without guessing and a
reviewer can grade without vibes. This skill produces that document.

The output is a markdown file that follows `${CLAUDE_SKILL_DIR}/references/spec-template.md`
section by section. Its acceptance checks (section 11) are what the build is graded
on by the `ui-reviewer` agent and by the design gate (`design_gate.py` in the `design-critique` skill).

## The ordering when sources disagree (higher wins)

1. **Your project's explicit rules and the user's own words.**
2. **Your design system**: `design/design-system.md` (create it with this plugin's
   `design-system` skill). Tokens, type scale, spacing ladder, component rules, vocabulary.
3. **The accessibility and craft floor**: WCAG 2.2 AA, then `${CLAUDE_SKILL_DIR}/references/floor-checklist.md`.
4. **Proven patterns from tools your users already know** (Jakob's law): if the job is a task
   list, behave like the task apps your users use; if it is checkout, behave like the stores they
   buy from. Invent only where no pattern fits, and say that you did.
5. **The editor**: the `design-critique` skill (subtract-only, C1-C8) runs on your spec last.

Aesthetic direction (a typographic point of view, a memorable visual voice) is a separate
concern. For that, use Anthropic's official `frontend-design` skill from the
`claude-plugins-official` marketplace. For a daily productivity tool, default to calm, dense and
fast unless someone asks for boldness.

## Workflow

1. **Read the inputs.** The user story or PRD section, any audit of the current screen, and
   `design/design-system.md` if it exists. If there is no design system yet, either run the
   `design-system` skill first or name every value you invent in section 6 and mark it
   "proposed token".
2. **Write the job in one sentence, and the success test in one more.** The success test names
   who, on which device, in what time budget, with what outcome. Example: "A returning shopper
   reorders last week's groceries on a phone, one thumb, in under 15 seconds, and sees the order
   confirmed."
3. **Critique your own plan before writing it up** (design-critique C3, C5, C6, C8). List every
   new screen, modal and step. Each new surface names the surface it `replaces:`, or it does not
   ship. Record the answers in section 2 of the spec.
4. **Map each story to a pattern** (section 3). Name the precedent ("inline add row like a
   to-do app", "undo toast like a mail client"). Note every deviation and why.
5. **Fill the template completely.** "N/A" needs a reason. The sections builders most often get
   wrong, so never leave them implicit:
   - **Layout at 375-430, 768-1024 and 1440 px**, with what is above the fold on the phone. A box
     sketch in ASCII per breakpoint is enough.
   - **The state matrix**: every component times every state. Empty, error, unknown/stale and long
     content are where most shipped bugs live.
   - **Keyboard**: what Enter, Escape, Tab, Backspace and each shortcut do, and where focus goes
     after every act (add, edit, complete, remove, undo, close).
   - **Touch**: tap, long-press, swipe, and the visible alternative for every gesture (WCAG 2.5.7).
   - **Writes**: optimistic or not, latency budget (ms to visible, ms to durable), rollback on
     failure, undo window for reversible destructive acts.
   - **Exact copy**: every string, sentence case, in the product's vocabulary, including empty
     states, errors (what happened and what to do), toasts and screen-reader announcements.
   - **Tokens, named**: spacing from the ladder, radii, colors, type sizes and weights, motion
     durations, all by token name from the design system, never raw values.
6. **Write acceptance checks a machine can decide** (section 11). Each check has a selector or a
   measurable number. "Feels fast" is not a check; "new row visible within 100 ms of Enter" is.
7. **Self-check against `${CLAUDE_SKILL_DIR}/references/floor-checklist.md`.** A spec that specifies an inaccessible
   interaction is a defect you shipped. Fix it in the spec.
8. **Hand it over.** Save to `design/specs/<surface>.md` (or the path you were given), never into
   product source. Tell the builder which acceptance checks map to `design_gate.py` metrics.

## Worked example (abbreviated)

```markdown
## 1. Job
- Job: "Add a to-do in one motion, from wherever I am in the list."
- Success test: a phone user adds three to-dos by pasting three lines, one thumb, under 10 s,
  each visible immediately.

## 7. State matrix (excerpt)
| Component | default | focus-visible | loading | empty | error | long content |
| AddRow | placeholder "Add a to-do, for example Call the dentist…" text-3 | 2px focus ring token focus-ring | n/a: optimistic | the list's only row, with the hint below | row turns error tint, "Couldn't save. Retry" inline button | wraps to 3 lines, then clamps with … |

## 11. Acceptance checks (excerpt)
- [ ] No horizontal page scroll at 375 and 390 (documentElement.scrollWidth == innerWidth).
- [ ] `[data-testid=add-row] button` is at least 44x44 on touch.
- [ ] Pasting 3 lines into `[data-testid=add-row] input` creates 3 `li[data-task]` within 300 ms.
- [ ] After Enter, focus stays in the add input (document.activeElement is the input).
- [ ] Remove shows `[role=status]` with an Undo button for at least 5 s; Undo restores the row
      at its original index.
```

## Acceptance check for the spec itself

- [ ] Every section of the template is filled or carries "N/A because ...".
- [ ] Every new surface has a `replaces:` line in section 2.
- [ ] The state matrix has no empty cell.
- [ ] Every gesture has a visible and a keyboard alternative.
- [ ] Every string the UI shows is in the copy deck.
- [ ] Every color, size, radius and duration is a token name.
- [ ] Section 11 has at least one check per story, and each is decidable by a script.
- [ ] The floor checklist was run and nothing on it is violated by the spec.
