# Review rubric: 10 dimensions, 0-4 each

Used by the `ui-reviewer` agent and by anyone grading a built screen. The 0-4 scale and the
habit of anchoring each score to observable evidence follow the Nielsen heuristic scoring
approach. The dimensions are chosen for dense, frequently used, phone-first product surfaces.

## How to score

- Score each dimension 0-4 by the **highest anchor it fully meets**. If it meets the 3 anchor
  except for one item, it is a 2 with a must-fix, never a "2.5".
- Every score cites evidence: a screenshot file, a `file:line`, or a measured number. A score
  with no evidence is invalid; mark the dimension `n/c` (not checked) and say why.
- **Gate dimensions (7 and 9)** at 0 or 1 cap the verdict at `REWORK`, whatever the total.
- Any **Blocker** also caps the verdict at `REWORK`.
- Total /40. Bands: 36-40 `SHIP`; 30-35 `SHIP AFTER MUST-FIXES`; 22-29 `REWORK`; under 22 `REDESIGN`.
- Report a table: `# | dimension | score | anchor matched | evidence | must-fix ids`.

## Severity

| Severity | Meaning | Examples |
|---|---|---|
| Blocker | Wrong, unsafe or unusable. Do not ship. | A failed data source shown as an empty list; a gesture-only action; body contrast under 3:1; a destructive act with neither undo nor confirm; horizontal page scroll at 390 px. |
| High | Users hit it this week and it costs them. | Primary content below the fold on phone; touch primaries under 44 px; a write that takes over a second to appear; focus lost after an inline edit. |
| Medium | Real friction or a visible craft gap. | Off-ladder spacing, one act with two names, an off-scale font weight, uneven row heights. |
| Nit | Polish. | `...` instead of `…`, a non-tabular number in a column. |

## 1. Job fit and flow

Can the user do the core job in the fewest mindless steps? (Nielsen 3, 7; design-critique C1,
C3, C5, C6.)

| Score | Anchor |
|---|---|
| 0 | The core job cannot be done on this surface, or needs another page. |
| 1 | Possible but buried: a detour, a modal for a routine act, more than 3 taps for the most frequent action. |
| 2 | Works, but at least one routine step exists for the system's sake (an extra confirm, a mode switch, a "Show more" before the first useful row). |
| 3 | The most frequent action is 1 tap or keystroke from first paint; secondary actions are 2. No step fails the C3 walkthrough. |
| 4 | As 3, plus the first actionable thing is in the first phone viewport, the user's place is restored on return, and the flow absorbs complexity (parsing, defaults) instead of asking. |

Measure: taps from first paint to each core-flow goal (`design_gate.py` flow metrics).

## 2. Visual hierarchy and layout

| Score | Anchor |
|---|---|
| 0 | No discernible primary element; everything competes. |
| 1 | The wrong thing dominates (meta text, disclaimers, chrome louder than content). |
| 2 | The right thing is primary, but secondary items are as loud; equal-weight sections stack without grouping. |
| 3 | One clear primary per viewport; secondary text de-emphasized with the design system's lower text tiers; grouping by proximity; obvious scan path. |
| 4 | As 3, plus hierarchy adapts per breakpoint, and nothing on screen is the system talking about itself unless it changes what the user does. |

## 3. Typography

| Score | Anchor |
|---|---|
| 0 | Text unreadable at the target size (under 12 px body on phone, or clipped). |
| 1 | More than 3 sizes and 3 weights fighting; body under 15 px on phone; inputs under 16 px. |
| 2 | A scale exists but is applied loosely: off-scale weights, non-tabular numbers in columns, long titles overflowing. |
| 3 | Sizes and weights only from the type scale; numbers tabular where they align; long text truncates or wraps on purpose; real ellipsis and quotes. |
| 4 | As 3, plus balanced headings, 45-75 character prose lines, and type alone (no boxes) carries a row's hierarchy. |

## 4. Spacing and rhythm

| Score | Anchor |
|---|---|
| 0 | Overlapping or colliding elements. |
| 1 | Arbitrary values everywhere; no consistent gap between like items. |
| 2 | Mostly consistent, with off-ladder values (13, 18, 22 px) and uneven row heights in one list. |
| 3 | Every gap on the spacing ladder; like rows identical height; more space between groups than within; more above a heading than below. |
| 4 | As 3, plus density tuned to the job, and touch targets get their size from padding, not visual bulk. |

## 5. Design-system fidelity

See your `design/design-system.md`.

| Score | Anchor |
|---|---|
| 0 | Raw colors, a foreign palette, or a theme the product does not support. |
| 1 | Several raw values or deprecated tokens in new code. |
| 2 | Tokens used, but rules broken: more than one filled primary on screen, the brand accent used for status, radii off the set. |
| 3 | All color, radius, motion and type from tokens; elevation per the system's rule; one filled primary; status on status colors. |
| 4 | As 3, plus browser surfaces themed (selection, caret, focus ring, scrollbars), and the screen reads as the same product as its siblings at a glance. |

## 6. Interaction and feedback

Nielsen 1, 3, 5; the Doherty threshold (about 400 ms keeps attention; under 100 ms feels instant).

| Score | Anchor |
|---|---|
| 0 | Actions give no feedback, or lose data silently. |
| 1 | Feedback lags (spinners on routine acts, writes visible after more than 1 s, list jumps during edit); destructive acts immediate with no undo. |
| 2 | Optimistic for some acts, undo for some; states incomplete (no pressed, loading or error state on a control that can fail). |
| 3 | Every routine act optimistic (visible under 100 ms) and reconciled; every reversible destructive act has an undo window; every control has hover, focus-visible, pressed, disabled, loading and error states; inline edit commits on Enter or blur and cancels on Escape. |
| 4 | As 3, plus edits never lose focus, the list never reflows under the pointer, failures roll back visibly with a reason and retry, and one undo stack covers the session. |

## 7. Accessibility (WCAG 2.2 AA) - GATE

| Score | Anchor |
|---|---|
| 0 | A core action unreachable by keyboard or screen reader, or body contrast under 3:1. |
| 1 | Body or placeholder contrast under 4.5:1; focus invisible; gesture-only actions (2.5.7); unlabeled icon buttons. |
| 2 | Contrast and labels pass, but focus order is wrong, focus is hidden by a sticky bar (2.4.11), async changes are not announced, or targets under 24 px (2.5.8). |
| 3 | Semantic elements; visible `:focus-visible`; status changes in `aria-live="polite"`; every gesture has a single-pointer and keyboard alternative; reduced motion honored; zoom allowed. |
| 4 | As 3, plus a screen-reader pass of the core flow and a 200% zoom pass with no loss of function, and inline edit fields have names that include the item. |

## 8. Mobile, touch and keyboard

Fitts's law; platform target sizes.

| Score | Anchor |
|---|---|
| 0 | Horizontal page scroll at 390 px, or primary actions off screen or under the home indicator. |
| 1 | Touch primaries under 44 px; inputs under 16 px; no safe-area handling; no keyboard path for routine desktop acts. |
| 2 | Targets fine, but the thumb zone is ignored (primary action at the top on phone), sheets leak overscroll, or the soft keyboard covers the active field. |
| 3 | 44 px targets; bottom-reachable primary above the safe area; `touch-action: manipulation`; contained overscroll; desktop shortcuts for routine acts with a discoverable list. |
| 4 | As 3, plus verified on WebKit, swipe actions mirror visible buttons, and shortcuts match the conventions of tools the users already know. |

## 9. Honest status and resilience - GATE

| Score | Anchor |
|---|---|
| 0 | A source that could not be read renders as empty or as 0; or stale data is shown as current. |
| 1 | Unknown states exist but read as errors or vanish; no empty state (a blank region). |
| 2 | Empty, error and unknown are distinct but noisy (disclaimers crowd content), or long content and offline are unhandled. |
| 3 | Every data source shows its status; counts from non-live sources show unknown, not 0; empty states are one line plus the next action; errors say what happened and what to do; 0, 1, many, long and offline all handled. |
| 4 | As 3, plus status is quiet when healthy and loud only when it changes what the user should do, and relative times are computed on the client so a cached page cannot lie. |

## 10. Copy and vocabulary

Nielsen 2, 4, 9; design-critique C2, C7.

| Score | Anchor |
|---|---|
| 0 | Labels mislead (a button promises something it cannot do). |
| 1 | Internal jargon or IDs on screen (ticket codes, database names, raw IDs as the main label). |
| 2 | Plain, but inconsistent: one act named two ways; generic labels ("Submit", "Continue"); a time printed twice. |
| 3 | One case convention; specific verbs; one name per act across the product; errors name the fix; placeholders show an example; dates via `Intl.DateTimeFormat`. |
| 4 | As 3, plus the UI needs no explanatory copy (C7), and the strings sound like the product, not like the system describing itself. |

## Personas (one paragraph each, run through the core flow)

Replace the first persona with your real primary user. Keep the other two.

- **Primary user, in their real context.** Example: "a nurse between patients, phone, one hand,
  20 seconds." Can they see what matters without scrolling? Do the core job? Undo a mis-tap?
- **Alex, keyboard power user.** Every routine act without the mouse; no modal for add or edit;
  shortcuts discoverable.
- **Sam, assistive-technology user.** Screen reader announces additions, completions and undo;
  focus never lost; 200% zoom works; reduced motion honored.

## Output skeleton

```
REVIEW  /settings  verdict: SHIP AFTER MUST-FIXES  score: 31/40  (captured: chromium + webkit, phone + desktop)

Must-fixes
MF-1 Blocker  Honest status   evidence ...  problem ...  fix ...  verify ...
MF-2 High     Interaction     ...

Rubric
| # | Dimension | Score | Anchor | Evidence | MF |

Personas
Primary user: ...
Alex: ...
Sam: ...

Floor sweep (file:line)
src/components/Row.tsx:42 - icon button missing aria-label

Nits

Not checked
- screen reader pass: judged from markup only
```
