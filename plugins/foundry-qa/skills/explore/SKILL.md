---
name: explore
description: Read-only same-origin crawler for a web app (a URL, a local server, or a local folder of HTML pages served on localhost), including hash-routed pages (#/route) and signed-in pages. Follows links (skipping logout, delete and downloads) and records per page console errors, uncaught exceptions, 5xx and failed requests, broken links, a Back button that does not return, horizontal overflow on phone, missing title or h1, images without alt, and near-empty pages, with a screenshot each. Use when asked to "crawl the app", "find broken links", "dead links", "check every page for errors", "go through every page of my site", "click around my site and tell me what's broken", "click around and see what's busted", "which pages are busted", or as the first pass of exploratory testing. The explorer and web-qa agents run this skill.
---

# explore

The mechanical first pass of exploratory testing. It collects the cheap signals a curious
human would trip over so the tester can spend attention on judgment. It never submits forms,
and it is read-only by default (every non-GET/HEAD/OPTIONS request is answered locally, never
sent), so it is safe to point at production.

## You MUST

1. Run the crawler; do not read the HTML by hand and call that a crawl.
2. Quote the `EXPLORE:` headline (pages, errors, warnings, exit code).
3. Open the screenshot of every `error` and `look` page before reporting it.
4. Say what the crawl did not reach (pages past `--max-pages`, flows behind forms).

## Setup (once)

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install playwright
python3 -m playwright install chromium        # add webkit for Safari-engine runs
```

A local folder of HTML files: serve it first (`python3 -m http.server 4173 --directory site`)
and crawl `http://127.0.0.1:4173/`.

## Run

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/explore.py" --url <base-url> --max-pages 30
python3 "${CLAUDE_SKILL_DIR}/scripts/explore.py" --url <base-url> --max-pages 15 --devices phone-390x844
```

Options: `--devices` (`desktop-1440x900`, `phone-390x844`, `tablet-820x1180`), `--browser
webkit`, `--back-checks N`, `--settle-ms N` (default 300, extra wait after the network goes
quiet), `--out DIR` (default `.qa/explore`), `--allow-writes` (local targets only).
Signed-in pages: `--storage-state .qa/auth.json`, `--header "Name: value"` or `--auth FILE`
(see the done-gate skill, "Signed-in apps"; `scripts/qa_session.py login` makes the state).

Hash-routed apps: a link like `#/group/1` or `#!/settings` is its own page (a plain anchor
like `#top` is not), pages are deduplicated on the full URL, and the crawl stops at
`--max-pages`. Each page is checked after the network goes quiet, so data that arrives after
the load event is there. Errors logged while the Back-button check opens another page belong
to that page, not the one being checked.

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
