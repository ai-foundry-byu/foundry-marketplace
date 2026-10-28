# Design spec template

Copy the skeleton below into `design/specs/<surface>.md` and fill every section. "N/A" needs a
reason. Section 11 (acceptance checks) is what the build is graded on, by the `ui-reviewer`
agent, by `design_gate.py`, and by your own review, so write each check so a script can decide
pass or fail.

Token names below (`--space-*`, `--radius-*`, `--text-*`, `--dur-*`) are placeholders. Use the
names from your `design/design-system.md`.

```markdown
# <Surface> design spec  (<author>, <date>, for <branch or ticket>)

## 1. Job
- Job in one sentence, in the user's words: ...
- Success test (who, device, time budget, outcome): ...
- Stories covered: <ids>  |  Stories changed or retired: <ids + why>

## 2. Pre-build critique (design-critique C3 / C5 / C6 / C8 on this plan)
- C3 every step maps to the job: ...
- C5 navigation needed: ...
- C6 one page: ...
- C8 surfaces: new surface X `replaces:` Y   (no `replaces:` = it does not ship)

## 3. Patterns used
| Story | Pattern (named precedent) | Deviation and why |

## 4. Information architecture
- What is on the surface, in priority order, and what is deliberately NOT (and where it goes).
- Data honesty: each data source, the states it can be in (live, stale, unknown, failed), and
  what renders when it is not live. A source that could not be read is never shown as empty or 0.

## 5. Layout
| Breakpoint | Structure | Above the fold | Scroll regions | Fixed elements + safe areas |
| 375-430 phone | | | | |
| 768-1024 tablet | | | | |
| >= 1024 desktop | | | | |
Include a box sketch (ASCII is fine) per breakpoint.

## 6. Components
For each component: anatomy (parts, order), sizes (from the spacing ladder), tokens (surface,
border, text tier, radius), type (size and weight from the type scale).

## 7. State matrix
| Component | default | hover | focus-visible | pressed | disabled | loading | empty | error | unknown/stale | offline | long content |
Every cell filled: what it looks like and what it says.

## 8. Interaction
- Pointer: click / double-click / drag (+ the single-pointer alternative for every drag).
- Touch: tap / long-press / swipe (+ the visible alternative for every gesture).
- Keyboard: full key map, focus order, where focus goes after each act (add, edit, complete,
  remove, undo, close sheet). Shortcuts never fire while typing in a field.
- Writes: which API call each interaction makes, optimistic behavior, reconciliation key,
  rollback on failure, latency budget (ms to visible; ms to durable).
- Undo: which acts, window length, what Undo restores, where focus lands.
- Irreversible acts (if any): what protects the user (confirm, typed confirmation, delay).

## 9. Motion
| Moment | Property | Duration token | Easing token | Reduced-motion variant |
One deliberate motion moment per flow; everything else instant or a short micro-transition.
Animate transform and opacity only.

## 10. Copy deck
| Key | String (exact, sentence case) | Where | Screen-reader text if different |
Include empty states, errors (what happened + what to do), toasts, aria-live phrases, placeholders.

## 11. Acceptance checks (machine-checkable)
- [ ] No horizontal page scroll at 375 and 390 (documentElement.scrollWidth == innerWidth).
- [ ] Touch primaries >= 44x44 (list selectors); all pointer targets >= 24x24.
- [ ] Text contrast >= 4.5:1 (3:1 for large text) for every text/surface pair used.
- [ ] Inputs >= 16 px font-size on touch.
- [ ] At most one primary-styled button visible per screen.
- [ ] Focus visible on every interactive element; focus order = <list>.
- [ ] Each drag or swipe has a button or menu alternative (selectors).
- [ ] Add -> visible in < 100 ms (optimistic); durable and re-read in < N s.
- [ ] Remove -> undo toast present for ~5 s; Undo restores in place.
- [ ] Non-live data source renders its status, never an empty list or 0.
- [ ] Reduced motion: no looping animation; state changes still legible.
- [ ] Core flow <name> takes <= N clicks from first paint (design_gate.py flow metric).
- [ ] No raw color values, off-scale weights or off-ladder spacing in changed files (grep).

## 12. Out of scope / later
## 13. Open questions (each with a recommended answer)
```

## Mapping acceptance checks to design_gate.py

| Spec check | Gate metric |
|---|---|
| No horizontal scroll | `page.<p>@<vp>.h_scroll` |
| Target sizes | `page.<p>@<vp>.small_target_count` |
| Contrast | `page.<p>@<vp>.contrast_failure_count` |
| Inputs >= 16 px on touch | `page.<p>@<vp>.inputs_under_16px` |
| One primary per screen | `page.<p>@<vp>.primary_buttons` |
| Core flow click budget | `flow.<name>@<vp>.clicks` and `.reached` |
| Key context always visible | `context.<name>@<vp>.present` |

Checks the gate does not cover (latency, undo, focus order, reduced motion) need a Playwright
test of their own, or are verified by the `ui-reviewer` agent and labeled as such.
