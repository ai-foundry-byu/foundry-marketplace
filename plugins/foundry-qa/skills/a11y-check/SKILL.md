---
name: a11y-check
description: Accessibility check for a web app against a WCAG 2.2 AA floor. Runs axe-core in a real browser via Playwright on desktop and mobile profiles (optionally after a journey reaches the right state, or signed in), adds its own WCAG 2.2 target-size check (2.5.8), reports violations by impact with selectors and fixes, then walks the manual checks axe cannot do (keyboard, focus, zoom, reduced motion, screen reader names). Use when asked to "check accessibility", "a11y audit", "WCAG", "is this accessible", "screen reader", "keyboard navigation", "color contrast", or before shipping any new page or form.
---

# a11y-check

Two halves, and you need both:
1. **Automated:** axe-core in a real browser. Fast, repeatable, catches roughly a third to a
   half of real WCAG problems (contrast, missing names and labels, bad ARIA, missing `lang`).
2. **Manual floor:** the checks a machine cannot judge (keyboard flow, focus visibility,
   meaningful names, zoom, motion). Ten minutes per page.

A clean axe run is the floor, not the finish.

## You MUST

1. Audit the pages users actually reach, signed in when the app has sign-in (`--storage-state`
   or a journey with `auth`). An audit of only the sign-in page is not an audit of the app.
2. Confirm or dismiss every `small-targets` item the script lists.
3. Report each manual checklist section as DONE, FAILED (with the criterion) or NOT DONE.

## Setup (once)

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install playwright
python3 -m playwright install chromium
```

The first run downloads a pinned axe-core build from cdnjs into `.qa/cache/`. Offline or
behind a proxy: download `axe.min.js` once and pass `--axe-source path/to/axe.min.js`.

## 1. Automated run

```bash
# pages by URL, on desktop and phone
python3 "${CLAUDE_SKILL_DIR}/scripts/a11y_check.py" \
  --url http://localhost:3000/ --url http://localhost:3000/signup \
  --devices desktop-1440x900,phone-390x844

# the state a journey reaches (a modal open, a form with errors, a signed-in page)
python3 "${CLAUDE_SKILL_DIR}/scripts/a11y_check.py" --journey qa/done-journey.yaml --base-url http://localhost:3000

# signed-in pages by URL
python3 "${CLAUDE_SKILL_DIR}/scripts/a11y_check.py" --url http://localhost:3000/dashboard --storage-state .qa/auth.json
```

Signed-in apps: `--storage-state FILE`, `--header "Name: value"`, `--auth FILE` (an `auth:`
block), or the journey's own `auth`. Make the state once with
`python3 "${CLAUDE_SKILL_DIR}/scripts/qa_session.py" login --url <sign-in url> --out .qa/auth.json`.
Each page is audited after the network goes quiet plus `--settle-ms` (default 800), so lists
that load late are audited too.

**Target size (WCAG 2.2, 2.5.8).** axe can pass small icon buttons, so the script also measures
every visible control. Under 24x24 CSS px with another target inside its 24 px circle: a
blocking `target-size-2.5.8` violation (impact serious). Under 24x24 but spaced far enough:
listed as `small-targets` (passes only through the spacing exception; confirm or dismiss each).
Inline links inside a sentence are exempt.

Options: `--fail-on critical|serious|moderate|minor` (default `serious`), `--tags` (default
`wcag2a,wcag2aa,wcag21a,wcag21aa,wcag22aa`; add `best-practice` for more), `--browser webkit`.

Exit codes: **0** nothing at or above `--fail-on`, **1** blocking violations, **2** config
error, **6** inconclusive (a page did not load, or axe could not load). 6 is not a pass.

Output per page: `PASS/FAIL <url> @ <device>: N blocking, M total, K need manual review`, then
the top violations as `[impact] rule-id xN: help text [first selector]`. Full detail with
fix hints and Deque help links: `.qa/a11y/report.json`.

Fix in this order: critical, serious, then the "incomplete" items axe flagged for manual
review (often contrast over images or gradients).

## 2. Manual floor: WCAG 2.2 AA checklist

Do these on every new page or flow. Each line names the success criterion.

**Keyboard and focus**
- [ ] Tab through the whole page: every interactive element is reachable, in a logical order (2.1.1, 2.4.3)
- [ ] No keyboard trap: you can Tab out of every widget, modal and embed (2.1.2)
- [ ] Focus is always visible, with real contrast against the background (2.4.7)
- [ ] Focus is not hidden behind sticky headers, footers or cookie banners (2.4.11, new in 2.2)
- [ ] Opening a modal moves focus into it; closing returns focus to the trigger; Escape closes it
- [ ] A "skip to content" link or proper landmarks let a keyboard user bypass the nav (2.4.1)

**Names, labels and structure**
- [ ] Every form field has a visible label tied to it, not just a placeholder (1.3.1, 3.3.2)
- [ ] Icon-only buttons have an accessible name that says what they do ("Delete item", not "icon") (4.1.2)
- [ ] One `h1`, headings in order, no skipped levels used for styling (1.3.1, 2.4.6)
- [ ] Link text makes sense out of context ("Download the syllabus", not "click here") (2.4.4)
- [ ] Images: meaningful ones have useful `alt`; decorative ones have `alt=""` (1.1.1)
- [ ] The page has a `lang` and a unique, descriptive `<title>` (3.1.1, 2.4.2)

**Forms and errors**
- [ ] Errors are announced in text, say what is wrong and how to fix it, next to the field (3.3.1, 3.3.3)
- [ ] Required fields are marked in text, not only by color (1.4.1)
- [ ] The user is not asked to re-enter information they already gave in the same flow (3.3.7, new in 2.2)
- [ ] Sign-in does not require solving a puzzle or memorizing; paste and password managers work (3.3.8, new in 2.2)

**Visual**
- [ ] Text contrast at least 4.5:1 (3:1 for 18pt+ or 14pt bold) (1.4.3)
- [ ] Borders of inputs, focus rings and icons that carry meaning at least 3:1 (1.4.11)
- [ ] At 200% browser zoom nothing overlaps or gets cut off (1.4.4)
- [ ] At 320 CSS px wide (phone, 400% zoom) there is no horizontal scroll for normal content (1.4.10)
- [ ] Color is never the only signal (errors, status chips, chart series) (1.4.1)

**Pointer and touch**
- [ ] Targets are at least 24x24 CSS px, or spaced so a 24px circle around each does not overlap another (2.5.8, new in 2.2)
- [ ] Anything done by dragging has a single-pointer alternative (2.5.7, new in 2.2)

**Motion and time**
- [ ] With "reduce motion" on, large animations and parallax stop (good practice; 2.3.3 is AAA)
- [ ] Nothing auto-plays for more than 5 seconds without a pause control (2.2.2)
- [ ] Session timeouts warn the user and let them extend (2.2.1)

**Quick screen reader pass** (VoiceOver: Cmd+F5 on macOS; NVDA on Windows)
- [ ] Read the page top to bottom: does the order make sense, and is every control announced with its name and role?
- [ ] Status messages ("Saved", "3 results") are announced without moving focus (4.1.3)

## 3. Report

List blocking violations first (rule, impact, count, selector, fix), then each `small-targets`
item as confirmed or dismissed, then the manual checklist: every section above as **DONE**,
**FAILED** (with the criterion number) or **NOT DONE**. Never call a page "accessible" because
axe is clean.

## Acceptance check

`.qa/a11y/report.json` exists for the pages you changed with `"exit_code": 0` at
`--fail-on serious`, and your summary lists the manual checklist results by section.
