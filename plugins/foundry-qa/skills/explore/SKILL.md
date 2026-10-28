---
name: explore
description: Read-only same-origin crawler for a web app. Follows links (skipping logout, delete and downloads) and records per page console errors, uncaught exceptions, 5xx and failed requests, broken links, a Back button that does not return, horizontal overflow on phone, missing title or h1, images without alt, and near-empty pages, with a screenshot each. Use when asked to "crawl the app", "find broken links", "check every page for errors", or as the first pass of exploratory testing. The explorer and web-qa agents run this skill.
---

# explore

The mechanical first pass of exploratory testing. It collects the cheap signals a curious
human would trip over so the tester can spend attention on judgment. It never submits forms,
and it is read-only by default (every non-GET/HEAD/OPTIONS request is answered locally, never
sent), so it is safe to point at production.

## Setup (once)

```bash
pip install playwright
python3 -m playwright install chromium        # add webkit for Safari-engine runs
```

## Run

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/explore.py" --url <base-url> --max-pages 30
python3 "${CLAUDE_SKILL_DIR}/scripts/explore.py" --url <base-url> --max-pages 15 --devices phone-390x844
```

Options: `--devices` (`desktop-1440x900`, `phone-390x844`, `tablet-820x1180`), `--browser
webkit`, `--back-checks N`, `--out DIR` (default `.qa/explore`), `--allow-writes` (local
targets only).

Output: `.qa/explore/findings.json` and `.qa/explore/screenshots/`. Each finding is
`error` (console errors, uncaught exceptions, HTTP 5xx, failed requests, a page that does not
load, a broken same-origin link), `warn` (Back does not return, 4xx on a sub-request, overflow
on a mobile profile, missing `<title>` or `<h1>`, images without alt) or `look` (near-empty
main content: is the empty state designed, or blank?).

Exit `0` no errors, `1` at least one error-level finding, `2` config error, `6` the start URL
could not be reached (nothing explored, not a pass).

## After the crawl

Open the screenshot of every `error` and `look` page. The crawl does not test edge cases,
double submits, refresh mid-flow or odd input; do those by hand, and only submit anything on a
local or staging target. The `explorer` agent carries the full probe list.

## Acceptance check

- The report quotes the crawl headline (pages, errors, warnings) and the exit code.
- Every `error` finding was opened and either confirmed with repro steps or marked flaky.
