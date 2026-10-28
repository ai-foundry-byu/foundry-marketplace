# <Product name> design system

<!--
Fill-in template. Copy to design/design-system.md and replace every <placeholder>.
Delete each guidance comment once its section is filled. Example values in the tables
are a neutral light theme so you can see the shape; replace them with yours.
-->

- Source of truth: `<path to tokens file, for example src/styles/tokens.css>` at commit `<sha>`.
  If this document and the code disagree, the code wins and this document is updated.
- Themes supported: `<light | dark | both>`
- Owner: `<team or person role>`  |  Last verified: `<date>`

## 1. The idea in five lines

<!-- Five short rules a builder can hold in their head. Example:
1. Calm and dense: content first, chrome quiet.
2. Elevation is a lighter surface plus a hairline border; shadows only on overlays.
3. One filled primary action per screen.
4. Status colors are muted and never the brand accent.
5. Numbers are tabular; prose is sentence case. -->

1. <...>
2. <...>
3. <...>
4. <...>
5. <...>

## 2. Color tokens

### Surfaces

| Token | Value (light) | Value (dark) | Use |
|---|---|---|---|
| `--bg-canvas` | `#ffffff` | `<...>` | App background |
| `--surface-1` | `#fafafa` | `<...>` | Panels, sidebars |
| `--surface-2` | `#f4f4f5` | `<...>` | Cards |
| `--surface-3` | `#e4e4e7` | `<...>` | Hover, menus |

### Text

| Token | Value (light) | Value (dark) | Use |
|---|---|---|---|
| `--text-1` | `#18181b` | `<...>` | Headings, body |
| `--text-2` | `#3f3f46` | `<...>` | Labels, secondary |
| `--text-3` | `#52525b` | `<...>` | Meta, timestamps, placeholders (lowest readable tier) |
| `--text-disabled` | `#a1a1aa` | `<...>` | Disabled only, never readable content |

### Borders

| Token | Value | Use |
|---|---|---|
| `--border-subtle` | `<...>` | Internal dividers |
| `--border-default` | `<...>` | Card and input edges |
| `--focus-ring` | `<...>` | `:focus-visible` outline (must be >= 3:1 against adjacent colors) |

### Accent (brand)

| Token | Value | Use |
|---|---|---|
| `--accent` | `<...>` | The one filled primary action per screen |
| `--accent-hover` | `<...>` | Hover state |
| `--accent-active` | `<...>` | Pressed state |
| `--on-accent` | `<...>` | Text on a filled accent |
| `--accent-text` | `<...>` | Accent links and icons on surfaces |

### Status (never the accent)

| Token | Value | Tint (background) | Meaning |
|---|---|---|---|
| `--status-success` | `<...>` | `<...>` | Done, healthy |
| `--status-warning` | `<...>` | `<...>` | Needs attention soon |
| `--status-danger` | `<...>` | `<...>` | Failed, destructive |
| `--status-info` | `<...>` | `<...>` | Neutral notice |
| `--status-unknown` | `<...>` | `<...>` | Could not be read (never shown as empty or 0) |

### Contrast table (measured, required)

<!-- Every text/background pair used anywhere. Measure with the snippet in the
design-system skill. Body text needs 4.5:1; large text and UI boundaries need 3:1. -->

| Foreground | Background | Ratio | Allowed for |
|---|---|---|---|
| `--text-1` | `--bg-canvas` | `<17.7:1>` | all text |
| `--text-3` | `--surface-2` | `<7.0:1>` | all text |
| `--on-accent` | `--accent` | `<...>` | button labels |
| `--text-disabled` | `--bg-canvas` | `<2.56:1>` | disabled only |

## 3. Typography

- Sans family: `<font stack>`  |  Mono family (data, code, timestamps): `<font stack>`
- Weights allowed: `<for example 400, 500, 600>` (anything else is a review finding)
- Numbers that align (tables, timers, counts): `font-variant-numeric: tabular-nums`

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--type-caption` | `12px / 16px` | `<...>` | Meta, badges (never body) |
| `--type-small` | `14px / 20px` | `<...>` | Secondary text |
| `--type-body` | `16px / 24px` | `<...>` | Body, inputs (16px minimum on touch) |
| `--type-title` | `20px / 28px` | `<...>` | Section titles |
| `--type-heading` | `24px / 32px` | `<...>` | Page heading (one h1) |
| `--type-display` | `32px / 40px` | `<...>` | Rare, marketing only |

## 4. Spacing ladder

<!-- A short explicit list. Every margin, padding and gap comes from here. -->

| Token | Value |
|---|---|
| `--space-1` | 4px |
| `--space-2` | 8px |
| `--space-3` | 12px |
| `--space-4` | 16px |
| `--space-5` | 20px |
| `--space-6` | 24px |
| `--space-8` | 32px |
| `--space-12` | 48px |

Rules: equal gaps between like items; larger gaps between groups; more space above a heading
than below it; page side gutter `<--space-4>` on phone.

## 5. Shape, elevation, motion

| Token | Value | Use |
|---|---|---|
| `--radius-sm` | `<6px>` | Inputs, chips |
| `--radius-md` | `<8px>` | Buttons, cards |
| `--radius-lg` | `<12px>` | Sheets, dialogs |
| `--shadow-overlay` | `<...>` | Popovers, dialogs only |
| `--dur-fast` | `<120ms>` | Hover, press |
| `--dur-base` | `<200ms>` | Enter, exit |
| `--ease-out` | `<cubic-bezier(...)>` | Default easing |

Elevation rule: `<lighter surface + border | shadow | border only>`. Motion rule: animate
`transform` and `opacity` only; every animation has a `prefers-reduced-motion` variant.

## 6. Components

<!-- One block per shared component. The reviewer checks code against these. -->

### Button

- Variants: `primary` (filled `--accent`, at most one visible per screen), `secondary`
  (outline `--border-default`), `ghost` (text only), `danger` (`--status-danger`).
- Primary selector in code (used by design_gate.py `selectors.primary_button`): `<[data-variant='primary']>`
- Sizes: min height `<40px>` desktop, `44px` touch; horizontal padding `--space-4`.
- States: default, hover, focus-visible (`--focus-ring`), pressed, disabled, loading (label kept,
  spinner inline, width fixed), error.

### Input

- Height `<40px>` desktop / `44px` touch; font `--type-body` (16px on touch).
- Label always visible above the field; placeholder shows an example and ends in `…`.
- Error: border `--status-danger`, message below in `--type-small` naming the fix.

### <List row | Card | Toast | Dialog | Tabs ...>

- Anatomy: `<...>`  |  Sizes: `<...>`  |  Tokens: `<...>`  |  States: `<...>`

## 7. Vocabulary

<!-- One name per act. Copy this table to design/vocabulary.md for design-critique. -->

| Act | Use | Never |
|---|---|---|
| Remove an item | `<Delete>` | `<Remove, Trash, Discard>` |
| Persist edits | `<Save>` | `<Submit, OK, Apply>` |
| <...> | <...> | <...> |

Case: `<Sentence case | Title Case>` for buttons and headings.

## 8. Migration (raw values found in code, and their replacement)

| Raw value | Where (count) | Replace with |
|---|---|---|
| `#6b7280` | `src/components/*.tsx (14)` | `--text-3` |
| `13px` gap | `src/components/List.css (3)` | `--space-3` |
