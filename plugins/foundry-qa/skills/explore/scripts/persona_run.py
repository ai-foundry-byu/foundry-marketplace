#!/usr/bin/env python3
"""persona_run: test every user story AS a persona, on that persona's devices, read-only.

  python3 persona_run.py --persona qa/personas/first-time-mobile-user.md \\
      --stories product/stories.json --base-url http://localhost:3000
  python3 persona_run.py ... --story US-02 --story US-05 --devices phone-390x844
  python3 persona_run.py ... --storage-state .qa/auth.json   # a signed-in app (see qa_session.py)

Stories: the project's ONE stories.json (the foundry-sdlc format, a list or
{"stories": [...]}). Per story: id, title, acceptance, surfaces, devices, status,
plus an optional "qa" block {start, steps, assertions, wait_for, params}. A
story with no steps and no assertions opens EVERY path in surfaces, one after
the other in the same session, runs the persona checks on each, screenshots
each (<story>-<device>-<n>.png when there are several), and marks the row
needs-judgment against the acceptance criteria. A story with steps or
assertions runs them once, from qa.start or else surfaces[0]. A route pattern
(/groups/:id, /groups/{id}, /groups/[id]) is never opened literally: qa.params
{"id": 1} fills it, qa.start gives a real path; otherwise the row is
INCONCLUSIVE "needs a concrete URL (add qa.start)". Unknown keys are ignored
with a warning. NOT_BUILT and PARKED stories are skipped unless named
with --story. Device ids that are not web profiles (ios-sim, android-emu) are
skipped with a warning.
  python3 persona_run.py ... --plan            # print the story x device matrix, run nothing
  python3 persona_run.py ... --file-tickets    # write tickets for failures seen on 2 runs in a row

READ-ONLY BY DEFAULT. Every request that is not GET/HEAD/OPTIONS is recorded
and answered inside the browser; it never reaches your server. So the run is
safe against production data. --allow-writes turns the guard off, and is
refused unless --base-url is localhost / 127.0.0.1 / [::1].

Each story x device gets one status:
  passed          every mechanical assertion held and every persona check is clean
  failed          an assertion, a step, or a persona check failed
  needs-judgment  the story has no mechanical assertions; a screenshot was taken
                  and the persona-tester agent must judge it against the
                  acceptance criteria. Report these as JUDGED, never as passed.
  inconclusive    nothing was proven (target unreachable, sign-in wall, harness error)

Every check runs after the page settles: network quiet (no request for 500 ms),
the story's wait_for selector visible, then --settle-ms (default 800).

Story checks (they decide the story's status, with its assertions):
  patience      navigation start to content ready (last data request done, or
                wait_for visible) within the persona's patience_seconds
  no-overflow   on mobile/tablet profiles, no horizontal page scroll
  console       no uncaught errors or console.error output
Site-wide check (reported ONCE per device in REPORT.md, never a story failure):
  tap-targets   visible controls smaller than the persona's min_tap_target_px

Exit codes: 0 no failures, 1 at least one failure, 2 config error,
6 nothing failed but something was inconclusive or no story ran.
needs-judgment alone does not fail the run, and does not make it a pass for a
human either: read REPORT.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_yaml  # noqa: E402
import qa_session  # noqa: E402
from done_gate import (  # noqa: E402
    DEVICE_PROFILES, ConfigError, StepFailure, check_assertions, context_kwargs,
    install_read_only_guard, resolve_url, run_steps, validate_assertion, validate_step,
)

EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_INCONCLUSIVE = 0, 1, 2, 6


# ── persona + stories (pure, unit-tested) ─────────────────────────────────────

@dataclass
class Persona:
    name: str
    devices: list[str]
    patience_seconds: float = 10.0
    min_tap_target_px: int = 24
    body: str = ""
    source: str = ""


def parse_persona(text: str, source: str = "") -> Persona:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise ConfigError(f"{source}: persona file needs YAML frontmatter between --- lines")
    try:
        meta = qa_yaml.loads(m.group(1)) or {}
    except qa_yaml.YamlError as exc:
        raise ConfigError(f"{source}: frontmatter: {exc}")
    if not isinstance(meta, dict) or not meta.get("name"):
        raise ConfigError(f"{source}: frontmatter needs at least 'name'")
    devices = meta.get("devices") or ["phone-390x844", "desktop-1440x900"]
    if isinstance(devices, str):
        devices = [devices]
    bad = [d for d in devices if d not in DEVICE_PROFILES]
    if bad:
        raise ConfigError(f"{source}: unknown device(s) {bad}; known: {sorted(DEVICE_PROFILES)}")
    patience = meta.get("patience_seconds", 10)
    tap = meta.get("min_tap_target_px", 24)
    if not isinstance(patience, (int, float)) or patience <= 0:
        raise ConfigError(f"{source}: patience_seconds must be a positive number")
    if not isinstance(tap, int) or tap < 0:
        raise ConfigError(f"{source}: min_tap_target_px must be a non-negative integer")
    return Persona(name=str(meta["name"]), devices=list(devices), patience_seconds=float(patience),
                   min_tap_target_px=tap, body=m.group(2).strip(), source=source)


@dataclass
class Story:
    id: str
    title: str
    start: Optional[str]
    steps: list[dict]
    assertions: list[dict]
    acceptance: list[str]
    devices: Optional[list[str]] = None
    writes: bool = False
    status: str = ""
    wait_for: Optional[str] = None
    scripted: bool = False             # True when the story carries a qa block (or legacy start/steps/assertions)
    skip_reason: str = ""
    pages: list[str] = field(default_factory=list)       # every concrete path the run opens, in order
    unresolved: list[str] = field(default_factory=list)  # route-pattern surfaces nothing filled in
    inconclusive: str = ""             # set when nothing concrete can be opened: reported, never a 404 failure
    expect_console: list[str] = field(default_factory=list)  # substrings of console errors the story expects


# The foundry-sdlc stories.json shape (contract C1), plus foundry-qa's optional keys.
STORY_KEYS = {"id", "title", "acceptance", "surfaces", "devices", "status", "waits_on", "covers",
              "notes", "evidence", "qa", "writes", "as_a",
              "start", "steps", "assertions", "wait_for"}   # last row: legacy top-level qa keys
QA_KEYS = {"start", "steps", "assertions", "wait_for", "params", "expect_console"}
SKIP_STATUSES = {"NOT_BUILT", "PARKED"}


def _is_path(v: Any) -> bool:
    return isinstance(v, str) and (v.startswith(("/", "#/", "#!/")) or re.match(r"^https?://", v) is not None)


# /groups/:id, /groups/{id}, /groups/<id>, /groups/[id] (Express, OpenAPI, prose, Next.js)
_PARAM_RE = re.compile(r"(?<=/):([A-Za-z_][\w-]*)|\{([^}/]+)\}|<([^>/]+)>|\[([^\]/]+)\]")


def is_route_pattern(path: str) -> bool:
    """True for a path with an unfilled route parameter. Pure."""
    return bool(_PARAM_RE.search(urlsplit(path).path + "/" + (urlsplit(path).fragment or "")))


def fill_params(path: str, params: dict) -> str:
    """Fill :id / {id} / <id> / [id] from params; a name not in params stays a pattern. Pure."""
    def sub(m: "re.Match[str]") -> str:
        name = next(g for g in m.groups() if g is not None)
        return str(params[name]) if name in params else m.group(0)
    return _PARAM_RE.sub(sub, path)


def needs_url(patterns: list[str]) -> str:
    return (f"needs a concrete URL (add qa.start): {', '.join(patterns)} is a route pattern; set qa.start "
            f"to a real path such as /groups/1, or qa.params such as {{\"id\": 1}}")


def parse_stories(data: Any, source: str = "", warnings: Optional[list[str]] = None) -> list[Story]:
    """Read the project's stories.json. Unknown keys are warnings, never errors."""
    warn = warnings if warnings is not None else []
    items = data.get("stories") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{source}: expected a list of stories or {{\"stories\": [...]}} with at least one story")
    out, seen = [], set()
    for i, s in enumerate(items):
        where = f"{source} stories[{i}]"
        if not isinstance(s, dict):
            raise ConfigError(f"{where}: each story must be an object")
        for k in ("id", "title"):
            if not isinstance(s.get(k), str) or not s.get(k):
                raise ConfigError(f"{where}: '{k}' is required")
        sid = s["id"]
        if sid in seen:
            raise ConfigError(f"{where}: duplicate story id {sid}")
        seen.add(sid)
        unknown = set(s) - STORY_KEYS
        if unknown:
            warn.append(f"{sid}: ignoring unknown key(s) {sorted(unknown)}")
        qa = s.get("qa")
        if qa is not None and not isinstance(qa, dict):
            raise ConfigError(f"{where}: 'qa' must be an object {{start, steps, assertions, wait_for}}")
        legacy = {k: s[k] for k in QA_KEYS if k in s}
        if qa is None and legacy:
            qa = legacy
        elif qa is not None and legacy:
            warn.append(f"{sid}: top-level {sorted(legacy)} ignored because a qa block is present")
        qa = qa or {}
        bad_qa = set(qa) - QA_KEYS
        if bad_qa:
            warn.append(f"{sid}: ignoring unknown qa key(s) {sorted(bad_qa)}")
        steps = [validate_step(x, f"{where}.qa.steps[{j}]") for j, x in enumerate(qa.get("steps") or [])]
        asserts = [validate_assertion(x, f"{where}.qa.assertions[{j}]") for j, x in enumerate(qa.get("assertions") or [])]
        acc = s.get("acceptance") or []
        if not isinstance(acc, list) or not all(isinstance(a, str) for a in acc):
            raise ConfigError(f"{where}: 'acceptance' must be a list of strings")
        if not asserts and not acc:
            raise ConfigError(f"{where}: give 'acceptance' criteria, qa 'assertions', or both")
        wait_for = qa.get("wait_for")
        if wait_for is not None and (not isinstance(wait_for, str) or not wait_for):
            raise ConfigError(f"{where}: qa.wait_for must be a selector string")
        surfaces = s.get("surfaces") or []
        if not isinstance(surfaces, list):
            raise ConfigError(f"{where}: 'surfaces' must be a list")
        start = qa.get("start")
        if start is not None and (not isinstance(start, str) or not start):
            raise ConfigError(f"{where}: qa.start must be a path or URL")
        expect_console = qa.get("expect_console") or []
        if not isinstance(expect_console, list) or not all(isinstance(x, str) and x for x in expect_console):
            raise ConfigError(f"{where}: qa.expect_console must be a list of non-empty strings, "
                              "each a substring of a console error the story expects (an intentional 404)")
        params = qa.get("params") or {}
        if not isinstance(params, dict):
            raise ConfigError(f"{where}: qa.params must be an object such as {{\"id\": 1}}")
        skip, inconclusive, pages, unresolved = "", "", [], []
        mechanical = bool(steps or asserts)
        if start:
            start = fill_params(start, params)
            if is_route_pattern(start):
                inconclusive, start = needs_url([start]), None
            else:
                pages = [start]
        else:
            paths = [x for x in surfaces if _is_path(x)]
            other = [x for x in surfaces if not _is_path(x)]
            if paths and other:
                warn.append(f"{sid}: surface(s) {other} are not paths and are not opened")
            filled = [fill_params(x, params) for x in paths]
            if mechanical:
                filled = filled[:1]          # steps and assertions belong to the first surface
            for orig, x in zip(paths, filled):
                if is_route_pattern(x):
                    unresolved.append(orig)
                elif x not in pages:
                    pages.append(x)
            start = pages[0] if pages else None
            if not paths:
                skip = ("no start path: add qa.start, or make surfaces[0] a path like /login"
                        if not surfaces else f"surfaces[0] {surfaces[0]!r} is not a path; add qa.start")
            elif not pages:
                inconclusive = needs_url(unresolved)
        devs = s.get("devices")
        if devs is not None:
            if isinstance(devs, str):
                devs = [devs]
            if not isinstance(devs, list):
                raise ConfigError(f"{where}: 'devices' must be a list")
            other = [d for d in devs if d not in DEVICE_PROFILES]
            if other:
                warn.append(f"{sid}: skipping non-web device(s) {other} (persona_run drives web profiles only)")
                devs = [d for d in devs if d in DEVICE_PROFILES]
                if not devs:
                    skip = skip or f"no web device in {other}"
            elif not devs:
                devs = None   # an empty list means "not narrowed"
        status = str(s.get("status") or "")
        out.append(Story(id=sid, title=s["title"], start=start, steps=steps, assertions=asserts,
                         acceptance=acc, devices=devs, writes=bool(s.get("writes", False)), status=status,
                         wait_for=wait_for, scripted=bool(qa), skip_reason=skip, pages=pages,
                         unresolved=unresolved, inconclusive=inconclusive, expect_console=list(expect_console)))
    return out


def select_stories(stories: list[Story], wanted: Optional[list[str]]) -> tuple[list[Story], list[tuple[Story, str]]]:
    """(stories to run, [(story, why skipped)]). Naming a story with --story runs it whatever its status."""
    if wanted:
        missing = set(wanted) - {s.id for s in stories}
        if missing:
            raise ConfigError(f"unknown story id(s): {sorted(missing)}")
    run, skipped = [], []
    for s in stories:
        if wanted and s.id not in wanted:
            continue
        if s.skip_reason:
            skipped.append((s, s.skip_reason))
        elif not wanted and s.status in SKIP_STATUSES:
            skipped.append((s, f"status {s.status}"))
        else:
            run.append(s)
    return run, skipped


def plan(stories: list[Story], persona: Persona, only_devices: list[str] | None) -> list[tuple[Story, str]]:
    """Story x device matrix: a story's own device list narrows the persona's."""
    pairs = []
    for s in stories:
        devs = only_devices or persona.devices
        if s.devices is not None:
            devs = [d for d in devs if d in s.devices]
        pairs.extend((s, d) for d in devs)
    return pairs


def writes_allowed(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost") or host.startswith("127.")


# ── results, verdict, tickets (pure, unit-tested) ─────────────────────────────

@dataclass
class StoryResult:
    story: str
    title: str
    device: str
    status: str                       # passed | failed | needs-judgment | inconclusive
    reason: str = ""
    checks: list[dict] = field(default_factory=list)
    assertions: list[dict] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    blocked_writes: list[dict] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    expected_console: list[str] = field(default_factory=list)  # errors qa.expect_console matched: not failures
    screenshot: str = ""
    screenshots: list[dict] = field(default_factory=list)   # [{surface, path}], one per surface opened
    final_url: str = ""
    elapsed_s: float = 0.0
    steps: list[dict] = field(default_factory=list)


def unexpected_console(errors: list[str], expected: list[str]) -> list[str]:
    """Console errors no qa.expect_console substring matches. Pure."""
    return [e for e in errors if not any(x in e for x in expected)]


def failure_lines(assertions: list[dict], checks: list[dict]) -> list[str]:
    """Every failing assertion and story-scoped check, in order. Site-wide checks are not story failures."""
    return ([a["detail"] for a in assertions if not a["passed"]]
            + [f"{c['check']}: {c['detail']}" for c in checks if not c["passed"] and c.get("scope") != "site"])


def classify(assertions: list[dict], checks: list[dict], has_assertions: bool) -> tuple[str, str]:
    """A story's status comes from its assertions and story-scoped checks; site-wide checks never fail it."""
    failed = failure_lines(assertions, checks)
    if len(failed) == 1:
        return "failed", failed[0]
    if failed:
        return "failed", f"{len(failed)} checks failed: " + "; ".join(failed)
    if not has_assertions:
        return "needs-judgment", "no mechanical assertions; judge the screenshot against the acceptance criteria"
    return "passed", "all assertions and persona checks passed"


def run_verdict(results: list[StoryResult]) -> int:
    if not results:
        return EXIT_INCONCLUSIVE
    if any(r.status == "failed" for r in results):
        return EXIT_FAIL
    if any(r.status == "inconclusive" for r in results):
        return EXIT_INCONCLUSIVE
    return EXIT_PASS


def reproduced_failures(previous: list[dict], current: list[dict]) -> list[dict]:
    """Failures present in BOTH runs for the same story and device. One-off flakes do not become tickets."""
    prev_failed = {(r["story"], r["device"]) for r in previous if r.get("status") == "failed"}
    return [r for r in current if r.get("status") == "failed" and (r["story"], r["device"]) in prev_failed]


def render_ticket(r: dict, persona: str, base_url: str) -> str:
    steps = "\n".join(f"{i + 1}. {k} {json.dumps(v)}" for i, s in enumerate(r.get("steps", [])) for k, v in s.items())
    failed = ([c for c in r.get("checks", []) if not c["passed"] and c.get("scope") != "site"]
              + [a for a in r.get("assertions", []) if not a["passed"]])
    failed_lines = "\n".join(f"- {f.get('check') or f.get('assertion')}: {f['detail']}" for f in failed) or f"- {r['reason']}"
    acc = "\n".join(f"- {a}" for a in r.get("acceptance", [])) or "- (none written)"
    return f"""# [{r['story']}] {r['title']} fails on {r['device']} for {persona}

Reproduced on two consecutive persona runs.

**Persona:** {persona}
**Device profile:** {r['device']}
**Base URL:** {base_url}
**Final URL:** {r.get('final_url', '')}

## Steps to reproduce
{steps}

## What failed
{failed_lines}

## Acceptance criteria
{acc}

## Evidence
- Screenshot(s): {', '.join(x['path'] for x in r.get('screenshots') or []) or r.get('screenshot', '')}
- Console errors: {len(r.get('console_errors', []))}
- Writes blocked by the read-only guard: {len(r.get('blocked_writes', []))}
"""


def site_findings(results: list[StoryResult]) -> dict[str, list[str]]:
    """Site-wide check results, merged once per device (deduplicated across stories). Pure."""
    out: dict[str, list[str]] = {}
    for r in results:
        for c in r.checks:
            if c.get("scope") == "site" and not c["passed"]:
                seen = out.setdefault(r.device, [])
                for item in c.get("items", []):
                    if item not in seen:
                        seen.append(item)
    return out


def render_report(persona: Persona, results: list[StoryResult], base_url: str, read_only: bool,
                  skipped: Optional[list[tuple[str, str]]] = None, warnings: Optional[list[str]] = None) -> str:
    counts = {k: sum(1 for r in results if r.status == k) for k in ("passed", "failed", "needs-judgment", "inconclusive")}
    lines = [
        f"# Persona run: {persona.name}",
        "",
        f"Tested as {persona.name}: {counts['passed']} of {len(results)} pass, {counts['failed']} fail, "
        f"{counts['needs-judgment']} need judgment, {counts['inconclusive']} inconclusive.",
        "",
        f"- Base URL: {base_url}",
        f"- Mode: {'READ-ONLY (writes recorded, never sent)' if read_only else 'WRITES ALLOWED (local target)'}",
        f"- Patience budget: {persona.patience_seconds:g}s, minimum tap target: {persona.min_tap_target_px}px",
        "",
        "| Story | Device | Status | Reason | Time |",
        "|---|---|---|---|---|",
    ]
    order = {"failed": 0, "inconclusive": 1, "needs-judgment": 2, "passed": 3}
    for r in sorted(results, key=lambda x: (order[x.status], x.story, x.device)):
        reason = r.reason.replace("|", "/")[:140]
        lines.append(f"| {r.story} | {r.device} | {r.status} | {reason} | {r.elapsed_s:.1f}s |")
    site = site_findings(results)
    if site:
        lines += ["", "## Site-wide persona checks (once per device; warnings, not story failures)", ""]
        for device, items in site.items():
            lines.append(f"- **{device}**: {len(items)} control(s) under {persona.min_tap_target_px}px "
                         f"(the persona's preference; WCAG 2.5.8 is 24px, see the a11y-check skill)")
            lines += [f"  - {x}" for x in items[:25]]
    judge = [r for r in results if r.status == "needs-judgment"]
    if judge:
        lines += ["", "## Needs judgment (look at each screenshot, then report it as JUDGED pass or JUDGED fail)", ""]
        for r in judge:
            shots = r.screenshots or [{"surface": "", "path": r.screenshot}]
            if len(shots) == 1:
                lines.append(f"- **{r.story} @ {r.device}**: {shots[0]['path']}")
            else:
                lines.append(f"- **{r.story} @ {r.device}**: {len(shots)} screenshots, judge every one")
                lines += [f"  - {x['surface']}: {x['path']}" for x in shots]
            lines += [f"  - [ ] {a}" for a in r.acceptance]
    failing = [(r, failure_lines(r.assertions, r.checks)) for r in results if r.status == "failed"]
    failing = [(r, f) for r, f in failing if f]
    if failing:
        lines += ["", "## Every failing check (the table's Reason column is cut at 140 characters)", ""]
        for r, f in failing:
            lines.append(f"- **{r.story} @ {r.device}**:")
            lines += [f"  - {x}" for x in f]
    expected = [r for r in results if r.expected_console]
    if expected:
        lines += ["", "## Console errors the stories expected (qa.expect_console; not failures)", ""]
        for r in expected:
            lines.append(f"- {r.story} @ {r.device}: {len(r.expected_console)}, e.g. {r.expected_console[0][:160]}")
    shown = [r for r in results if r.status in ("failed", "inconclusive") and r.screenshots]
    if shown:
        lines += ["", "## Screenshots of failed and inconclusive rows", ""]
        for r in shown:
            lines.append(f"- **{r.story} @ {r.device}** ({r.status}):")
            lines += [f"  - {x['surface']}: {x['path']}" for x in r.screenshots]
    writes = [(r, w) for r in results for w in r.blocked_writes]
    if writes:
        lines += ["", "## Writes the guard blocked (the UI may show success that did not happen)", ""]
        for r, w in writes[:50]:
            lines.append(f"- {r.story} @ {r.device}: {w['method']} {w['path']} ({w['body_bytes']} bytes)")
    if skipped:
        lines += ["", "## Not run", ""]
        lines += [f"- {sid}: {why}" for sid, why in skipped]
    if warnings:
        lines += ["", "## Warnings (stories.json)", ""]
        lines += [f"- {w}" for w in warnings]
    return "\n".join(lines) + "\n"


# ── browser checks ────────────────────────────────────────────────────────────

# clientWidth is the layout viewport. Under mobile emulation window.innerWidth grows to the
# content width (939 = 939 on a 939 px page at 390), so comparing against it hides overflow.
OVERFLOW_JS = "() => ({sw: document.documentElement.scrollWidth, iw: document.documentElement.clientWidth})"
TAP_JS = """
(min) => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=tab], [role=checkbox]';
  const small = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (el.closest('p, li') && el.tagName === 'A' && r.height >= 16) continue;  // inline text links are exempt (WCAG 2.5.8)
    if (r.width < min || r.height < min) {
      const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.name || '').trim().slice(0, 40);
      small.push(`${el.tagName.toLowerCase()} "${label}" ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  return small;
}
"""


def persona_checks(page: Any, persona: Persona, device: str, elapsed: float, console_errors: list[str],
                   note: str = "", surface: str = "") -> list[dict]:
    checks = [{"check": "patience", "passed": elapsed <= persona.patience_seconds,
               "detail": f"{elapsed:.1f}s to content against a {persona.patience_seconds:g}s budget"
                         + (f" ({note})" if note else "")}]
    if DEVICE_PROFILES[device].get("is_mobile"):
        dims = page.evaluate(OVERFLOW_JS)
        ok = dims["sw"] <= dims["iw"] + 1
        checks.append({"check": "no-overflow", "passed": ok,
                       "detail": "no horizontal scroll" if ok else f"page is {dims['sw']}px wide in a {dims['iw']}px viewport"})
    if persona.min_tap_target_px:
        small = page.evaluate(TAP_JS, persona.min_tap_target_px)
        checks.append({"check": "tap-targets", "scope": "site", "passed": not small, "items": small,
                       "detail": "all controls large enough" if not small else
                       f"{len(small)} control(s) under {persona.min_tap_target_px}px, e.g. {small[0]}"})
    checks.append({"check": "console", "passed": not console_errors,
                   "detail": "clean" if not console_errors else f"{len(console_errors)} error(s): {console_errors[0][:160]}"})
    if surface:
        for c in checks:
            c["surface"] = surface
            c["detail"] = f"{surface}: {c['detail']}"
    return checks


def inconclusive_result(story: Story, device: str) -> StoryResult:
    """A row for a story nothing concrete can be opened for (a route pattern): no browser, no 404 failure."""
    return StoryResult(story=story.id, title=story.title, device=device, status="inconclusive",
                       reason=story.inconclusive, acceptance=story.acceptance)


def run_one(pw: Any, browser_name: str, persona: Persona, story: Story, device: str, base_url: str,
            out_dir: Path, read_only: bool, timeout_ms: int, auth: Optional[dict] = None,
            settle_ms: int = qa_session.DEFAULT_SETTLE_MS, wait_for: Optional[str] = None) -> StoryResult:
    from playwright.sync_api import TimeoutError as PWTimeout
    if story.inconclusive:
        return inconclusive_result(story, device)
    pages = story.pages or [story.start]
    many = len(pages) > 1
    steps = [{"goto": story.start}] + story.steps
    res = StoryResult(story=story.id, title=story.title, device=device, status="inconclusive",
                      acceptance=story.acceptance, steps=steps if not many else [{"goto": p} for p in pages])
    browser = qa_session.launch(pw, browser_name)

    def shoot(n: int, surface: str) -> None:
        name = f"{story.id}-{device}-{n}.png" if many else f"{story.id}-{device}.png"
        shot = out_dir / "screenshots" / name
        shot.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(shot), full_page=True)
            res.screenshots.append({"surface": surface, "path": str(shot)})
            res.screenshot = res.screenshot or str(shot)
        except Exception:  # noqa: BLE001
            pass

    try:
        ctx = browser.new_context(**context_kwargs(device, browser_name), **qa_session.context_options(auth))
        page = ctx.new_page()
        t0 = time.monotonic()
        n = 0
        try:
            try:  # sign in before the read-only guard, so a sign-in POST goes through
                qa_session.apply_auth(ctx, page, auth, base_url,
                                      lambda pg, st: run_steps(pg, st, base_url, timeout_ms, [], PWTimeout))
            except StepFailure as sf:
                raise StepFailure("inconclusive", f"sign-in (auth.login_steps) failed: {sf.message}") from None
            if read_only:
                install_read_only_guard(ctx, res.blocked_writes)
            page.on("console", lambda m: res.console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: res.console_errors.append(f"uncaught: {e}"))
            tracker = qa_session.NetTracker(page)
            selector = story.wait_for or wait_for
            for n, surface in enumerate(pages, 1):
                first_error = len(res.console_errors)
                t0 = time.monotonic()                  # navigation start
                run_steps(page, steps if n == 1 else [{"goto": surface}], base_url, timeout_ms, [], PWTimeout)
                try:
                    ready, note = qa_session.settle(page, tracker, timeout_ms, selector, settle_ms)
                except PWTimeout:
                    raise StepFailure("fail", f"content never appeared{' on ' + surface if many else ''}: "
                                              f"{selector} not visible within {timeout_ms} ms") from None
                res.elapsed_s = max(res.elapsed_s, round(ready - t0, 2))
                if n == 1:
                    res.assertions = check_assertions(page, story.assertions, timeout_ms,
                                                      unexpected_console(res.console_errors, story.expect_console), [])
                res.checks += persona_checks(page, persona, device, round(ready - t0, 2),
                                             unexpected_console(res.console_errors[first_error:], story.expect_console),
                                             note, surface if many else "")
                res.final_url = page.url
                shoot(n, surface)
            res.expected_console = [e for e in res.console_errors if any(x in e for x in story.expect_console)]
            res.status, res.reason = classify(res.assertions, res.checks, bool(story.assertions))
            if story.unresolved and res.status != "failed":
                res.status, res.reason = "inconclusive", needs_url(story.unresolved) + (
                    f" ({len(res.screenshots)} other surface(s) opened, see the screenshots)" if res.screenshots else "")
            if story.writes and read_only and res.blocked_writes:
                res.reason += " (writes were simulated by the read-only guard)"
        except StepFailure as sf:
            res.elapsed_s = max(res.elapsed_s, round(time.monotonic() - t0, 2))
            res.status = "failed" if sf.status == "fail" else "inconclusive"
            res.reason = sf.message
            res.final_url = page.url
            shoot(max(n, 1), pages[max(n, 1) - 1])
        ctx.close()
    except qa_session.SessionError:
        raise
    except Exception as exc:  # noqa: BLE001
        res.status, res.reason = "inconclusive", f"harness error: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}"
    finally:
        browser.close()
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="persona_run.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", required=True)
    ap.add_argument("--stories", required=True, help="the project's stories.json (for example product/stories.json)")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--story", action="append", default=None, help="only these story ids (runs them whatever their status)")
    ap.add_argument("--devices", default="", help="comma list overriding the persona's devices")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    ap.add_argument("--out", default=None, help="default .qa/persona/<persona-name>")
    ap.add_argument("--timeout-ms", type=int, default=10000)
    ap.add_argument("--settle-ms", type=int, default=qa_session.DEFAULT_SETTLE_MS,
                    help="extra wait after the network goes quiet, before checks and the screenshot")
    ap.add_argument("--wait-for", default=None, help="selector that means 'content is here' for stories without qa.wait_for")
    ap.add_argument("--allow-writes", action="store_true", help="local targets only")
    ap.add_argument("--file-tickets", action="store_true", help="ticket failures that reproduced on the previous run")
    ap.add_argument("--plan", action="store_true", help="print the matrix and exit")
    qa_session.add_auth_args(ap)
    args = ap.parse_args(argv)

    warnings: list[str] = []
    try:
        persona = parse_persona(Path(args.persona).read_text(encoding="utf-8"), args.persona)
        stories, skipped = select_stories(parse_stories(qa_yaml.load_file(args.stories), args.stories, warnings),
                                          args.story)
        only = [d.strip() for d in args.devices.split(",") if d.strip()] or None
        if only and any(d not in DEVICE_PROFILES for d in only):
            raise ConfigError(f"unknown device in {only}; known: {sorted(DEVICE_PROFILES)}")
        for s in stories:
            for path in s.pages:
                resolve_url(path, args.base_url)
        if args.allow_writes and not writes_allowed(args.base_url):
            raise ConfigError(f"--allow-writes is refused for {args.base_url}: only localhost targets may take writes")
        auth = qa_session.auth_from_args(args, validate_step)
        if not args.plan:
            qa_session.check_ready(auth)
    except (OSError, ConfigError, qa_session.SessionError, qa_yaml.YamlError, json.JSONDecodeError) as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    skipped_rows = [(s.id, why) for s, why in skipped]

    matrix = plan(stories, persona, only)
    if args.plan:
        for s, d in matrix:
            if s.inconclusive:
                print(f"{s.id:10} {d:18} INCONCLUSIVE: {s.inconclusive}")
                continue
            mode = "scripted" if (s.steps or s.assertions) else "judge acceptance"
            where = s.start if len(s.pages) < 2 else f"{s.start} (+{len(s.pages) - 1} more)"
            print(f"{s.id:10} {d:18} {where:24} {mode:17} {s.title}")
        for sid, why in skipped_rows:
            print(f"{sid:10} {'(skipped)':18} {why}")
        print(f"{len(matrix)} run(s) for persona {persona.name}")
        return EXIT_PASS
    try:
        sync_playwright = qa_session.import_sync_playwright(args.browser)
    except qa_session.BrowserMissing as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    slug = re.sub(r"[^a-z0-9]+", "-", persona.name.lower()).strip("-") or "persona"
    out = Path(args.out or f".qa/persona/{slug}")
    out.mkdir(parents=True, exist_ok=True)
    read_only = not args.allow_writes
    results: list[StoryResult] = []
    try:
        with sync_playwright() as pw:
            for story, device in matrix:
                r = run_one(pw, args.browser, persona, story, device, args.base_url, out, read_only, args.timeout_ms,
                            auth=auth, settle_ms=args.settle_ms, wait_for=args.wait_for)
                results.append(r)
                print(f"{r.status.upper():15} {story.id} @ {device}: {r.reason}")
    except (qa_session.BrowserMissing, qa_session.SessionError) as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    current = [asdict(r) for r in results]
    res_path, prev_path = out / "results.json", out / "previous-results.json"
    previous = []
    if res_path.exists():
        try:
            previous = json.loads(res_path.read_text()).get("results", [])
        except (json.JSONDecodeError, OSError):
            previous = []
        res_path.replace(prev_path)
    code = run_verdict(results)
    site = site_findings(results)
    res_path.write_text(json.dumps({"persona": persona.name, "base_url": args.base_url, "read_only": read_only,
                                    "ran_at": datetime.now(timezone.utc).isoformat(), "exit_code": code,
                                    "site_findings": site, "skipped": [{"story": a, "why": b} for a, b in skipped_rows],
                                    "warnings": warnings, "results": current}, indent=2))
    (out / "REPORT.md").write_text(render_report(persona, results, args.base_url, read_only, skipped_rows, warnings))
    if args.file_tickets:
        repro = reproduced_failures(previous, current)
        tdir = out / "tickets"
        tdir.mkdir(exist_ok=True)
        for r in repro:
            (tdir / f"{r['story']}-{r['device']}.md").write_text(render_ticket(r, persona.name, args.base_url))
        print(f"{len(repro)} ticket(s) written to {tdir} (failures seen on two runs in a row)")
    counts = {k: sum(1 for r in results if r.status == k) for k in ("passed", "failed", "needs-judgment", "inconclusive")}
    for device, items in site.items():
        print(f"SITE-WIDE  {device}: {len(items)} control(s) under {persona.min_tap_target_px}px (warning, see REPORT.md)")
    print(f"Tested as {persona.name}: {counts['passed']} of {len(results)} pass, {counts['failed']} fail, "
          f"{counts['needs-judgment']} need judgment, {counts['inconclusive']} inconclusive"
          + (f", {len(skipped_rows)} not run" if skipped_rows else "") + f".  report: {out / 'REPORT.md'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
