# The floor: one checklist for specs and reviews

The minimum every screen must meet before taste even enters the conversation. Use it two ways:
as the self-check on a spec before handover, and as the sweep in a review, reported as
`file:line - problem`.

Sources, for the principle behind each line (read them, do not paste them):
- W3C, WCAG 2.2: https://www.w3.org/TR/WCAG22/ (success criteria cited by number)
- Vercel, Web Interface Guidelines: https://vercel.com/design/guidelines
- Apple Human Interface Guidelines and Google Material Design, for touch target sizing
- Nielsen Norman Group's 10 usability heuristics: https://www.nngroup.com/articles/ten-usability-heuristics/

## 1. Accessibility (Blocker if violated on a core flow)

- Body and placeholder text at least 4.5:1 contrast; large text (24 px, or 18.66 px bold) and
  UI component boundaries at least 3:1 (WCAG 1.4.3, 1.4.11).
- State is never conveyed by color alone; pair it with text, an icon shape or position (1.4.1).
- Semantic elements before ARIA: `<button>` for actions, `<a>` for navigation, `<label>` for
  inputs, real lists for lists. No clickable `<div>`.
- Icon-only buttons have an accessible name that names the action and the item
  ("Delete: Buy milk", not "Delete").
- Decorative icons are `aria-hidden="true"`.
- Visible focus on every interactive element via `:focus-visible`. Never `outline: none` without
  a replacement.
- Focus is never hidden behind a sticky header, bottom bar or toast (2.4.11).
- Async changes (added, saved, failed, undo available) are announced through one
  `aria-live="polite"` region, as complete phrases, without moving focus.
- Every drag has a single-pointer alternative and a keyboard path (2.5.7).
- Pointer targets at least 24 x 24 CSS px (2.5.8); touch primaries at least 44 x 44.
- One `h1` per page; headings in order.
- Zoom is never disabled (`user-scalable=no` and `maximum-scale=1` are Blockers).
- `prefers-reduced-motion` is honored: every animation has a reduced variant or none; loops stop.
- After a client-side route change, focus moves to the main region or the new heading.

## 2. Interaction and feedback

- Visible response to every tap or keypress within about 100 ms. Routine writes are optimistic
  and reconciled with the server result.
- Destructive but reversible acts (remove, archive, complete, move) get an undo window (a toast
  for about 5 s, plus Cmd/Ctrl+Z on desktop) instead of a confirm dialog. Confirm only what is
  truly irreversible.
- Typed but unsaved text survives closing a sheet (kept as a draft) or the user is warned.
- Every control has hover (fine pointers), focus-visible, pressed, disabled, loading and error
  states, and pressed states never shift layout.
- Routine acts never block on a full-screen spinner.
- Inline edit: Enter commits, Escape cancels and restores, blur commits; one write per edit, not
  per keystroke.
- Errors appear next to what failed, say what happened and what to do, and offer a retry. A
  failed optimistic write rolls back visibly.
- Paste is never blocked.
- `autofocus` only for a single primary input on desktop; never on mobile page load (it raises
  the keyboard and hides the page).
- The list never re-sorts or jumps under the pointer during an edit; reserve space for content
  that loads late.

## 3. Layout, spacing, typography

- No horizontal page scroll at 375 and 390 px. Flex children holding text get `min-width: 0`;
  long text truncates or wraps on purpose.
- Spacing only from the design system's ladder. Equal gaps between like items, larger gaps
  between groups, more space above a heading than below it.
- Font weights and sizes only from the design system's type scale.
- Numbers in tables, timers and counters use tabular figures (`font-variant-numeric: tabular-nums`).
- Inputs at least 16 px font size on touch devices, or iOS Safari zooms on focus.
- Use the real ellipsis character and curly quotes in UI copy ("Loading…", not "Loading...").
- Headings use `text-wrap: balance`; prose lines run 45-75 characters.
- Use `min-height: 100dvh`, not `100vh`, on mobile.
- Fixed and sticky bars reserve their height so content scrolls clear of them.
- On mobile, the primary job is in the first viewport; secondary content folds below.
- Dates and times come from `Intl.DateTimeFormat` in the user's time zone, never hand-built
  strings. Relative labels ("in 20 min") are computed on the client so a cached page cannot lie.

## 4. Mobile, touch, keyboard

- Touch primaries at least 44 x 44 px with at least 8 px between adjacent targets. Grow the hit
  area with padding rather than the visual.
- `touch-action: manipulation` on interactive elements (no double-tap zoom delay).
- `overscroll-behavior: contain` in sheets, drawers and inner scrollers.
- Bottom bars and inputs sit above `env(safe-area-inset-bottom)`; nothing under the home
  indicator or notch.
- Every swipe action has a visible equivalent (a button or a row menu).
- No horizontal swipe on main content that fights the browser's back gesture.
- Desktop: routine acts have shortcuts, shortcuts never fire while typing, and the set is
  discoverable (a `?` overlay or a command palette).
- Test WebKit as well as Chromium: every iPhone browser is WebKit.

## 5. Visual craft

- Tokens only: no raw hex or rgb values in component code.
- One filled primary action per screen. Status colors are separate from the brand accent.
- Elevation is consistent (by surface lightness or by shadow, per the design system, not both
  at random).
- Avoid: identical icon-heading-text card grids as the whole page structure; gradient text;
  decorative glass; thick colored side stripes on cards; cards nested in cards; emoji as icons.
- Icons from one family, one stroke weight.
- Browser surfaces are themed: selection color, caret, focus ring, scrollbars on fine pointers.
- One deliberate motion moment per flow; animate transform and opacity with durations from the
  design system; never `transition: all`.

## 6. Honest status and resilience

- Every state designed: empty, loading (a skeleton for anything under about a second),
  error, unknown or stale, offline, one item, many items (long lists virtualized), very long text.
- A data source that could not be read is never shown as empty or as 0. Show "unknown" (or `?`
  in a count) and the reason.
- Empty states are one line plus the next action.
- Offline: reads show the last data with its age; writes queue or say they cannot be saved.

## 7. Copy

- Sentence case for headings and buttons, unless your design system says otherwise.
- Specific verb labels ("Place order", not "Submit"; "Save changes", not "OK").
- Active voice, second person, numerals for counts.
- No internal IDs, ticket codes or database names as visible labels.
- The same act has one name everywhere (design-critique C2; `design/vocabulary.md`).
- Placeholders show an example and end with `…`.

## 8. Code smells to grep in a review

```bash
# scoped to the changed files
grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\(' <files>                 # raw colors outside the token file
grep -nE 'transition:\s*all|transition-all' <files>            # transition all
grep -nE 'outline:\s*none|outline-none' <files>                 # confirm a focus-visible replacement
grep -nE '<div[^>]*onClick|<span[^>]*onClick' <files>          # click handler on a non-button
grep -nE 'autoFocus|autofocus' <files>
grep -nE 'user-scalable=no|maximum-scale=1' <files>
grep -nE "getHours\(\)|getMinutes\(\)|padStart\(2" <files>      # hand-built times
grep -nE '[0-9]+px' <files>                                     # compare each against the spacing ladder
```

Each hit is a lead, not a finding, until you have read the line in context.
