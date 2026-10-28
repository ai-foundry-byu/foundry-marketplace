---
name: visual-baseline
description: Screenshot baselines and pixel-diff visual regression for web pages. Captures pages on desktop, phone and tablet profiles with animations frozen and dynamic regions masked, compares them to approved baselines with a percentage threshold and per-channel noise tolerance, writes red-highlight diff images, and requires a deliberate approve step to change a baseline. Use when asked to "check for visual regressions", "did the layout change", "screenshot diff", "pixel diff", "update the baselines", or after CSS, layout, design-token or shared-component changes.
---

# visual-baseline

Tests tell you the button exists. A visual baseline tells you the button did not move 40px,
turn white on white, or push the footer over the form. Use it on pages you did not mean to
change, which is where layout regressions hide.

## Setup (once)

```bash
pip install playwright
python3 -m playwright install chromium
```

PNG decoding and diffing use only the Python standard library. If Pillow is installed it is
used for decoding (faster on very tall pages).

## The workflow

Everything lives under `.qa/visual/`:
- `current/`  the screenshots from the latest capture
- `baselines/`  the approved screenshots (**commit these**, or store them as CI artifacts)
- `diff/`  red-highlight images for anything that changed
- `report.json`  the last comparison

**1. First run: capture and approve.**

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/visual_baseline.py" capture \
  --url http://localhost:3000/ --name home \
  --url http://localhost:3000/pricing --name pricing \
  --devices desktop-1440x900,phone-390x844,tablet-820x1180
```

Open every file in `.qa/visual/current/` and look at it. A baseline is a claim that this is
correct; never approve a screenshot you have not looked at.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/visual_baseline.py" approve
```

**2. Every change after that: check.**

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/visual_baseline.py" check \
  --url http://localhost:3000/ --name home \
  --url http://localhost:3000/pricing --name pricing \
  --devices desktop-1440x900,phone-390x844,tablet-820x1180
```

Exit codes: **0** every screenshot within threshold, **1** visual regression (over threshold
or the image size changed), **2** config error, **6** inconclusive: a page has no baseline yet
or failed to load. 6 is not a pass.

**3. When something differs:** open `.qa/visual/diff/<name>-<device>.png`. Changed pixels are
solid red over a faded copy of the baseline.
- Unintended: fix the code, re-run `check`.
- Intended (you meant to change that page): look at the new screenshot, then approve just that
  one: `visual_baseline.py approve --only pricing-phone-390x844.png`. Commit the new baseline
  in the same commit as the change that caused it, so reviewers see both.

## Tuning

| Option | Default | Use |
|---|---|---|
| `--threshold` | `0.1` | percent of pixels allowed to differ. Raise to 0.5 for pages with anti-aliased charts |
| `--tolerance` | `8` | per-channel difference (0 to 255) treated as equal. Absorbs font rendering noise |
| `--mask "<selector>"` | none | paint over clocks, avatars, ads, random content. Repeatable |
| `--wait-for "<selector>"` | none | wait for the real content, not the skeleton |
| `--viewport-only` | full page | screenshot only the first screen |
| `--settle-ms` | `300` | extra wait after load for late layout |
| `--browser` | chromium | `webkit` for a Safari-engine baseline (keep separate baselines per engine) |

Captures run with reduced motion, CSS animations and transitions frozen, the caret hidden,
and `scale="css"` so phone screenshots are not 3x the size.

## Making baselines stable

Flaky baselines get ignored, which is worse than none. Before approving:
- Seed deterministic data (fixed test account, fixed dates). Freeze "today" if the page shows it.
- Mask anything that changes per run: timestamps, avatars, carousels, A/B test slots.
- Capture on the same OS and browser version every time. Fonts render differently on macOS,
  Linux and Windows, so take CI baselines in CI (the same container), not on a laptop.
- A size change always fails. That is on purpose: a page that got 200px taller usually means
  something unexpected rendered.

## Acceptance check

Baselines for the pages you touched (and their neighbors that share components) are committed,
`check` exits 0 on your branch, and any approved change is in the same commit as the code that
caused it.
