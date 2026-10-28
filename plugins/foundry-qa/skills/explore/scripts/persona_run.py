#!/usr/bin/env python3
"""persona_run: test every user story AS a persona, on that persona's devices, read-only.

  python3 persona_run.py --persona qa/personas/first-time-mobile-user.md \\
      --stories qa/stories.json --base-url http://localhost:3000
  python3 persona_run.py ... --story S-2 --story S-5 --devices phone-390x844
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

Persona checks (on top of the story's own assertions):
  patience      story finished within the persona's patience_seconds
  no-overflow   on mobile/tablet profiles, no horizontal page scroll
  tap-targets   no visible control smaller than min_tap_target_px (default 24, WCAG 2.5.8)
  console       no uncaught errors or console.error output

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
    start: str
    steps: list[dict]
    assertions: list[dict]
    acceptance: list[str]
    devices: Optional[list[str]] = None
    writes: bool = False


STORY_KEYS = {"id", "title", "start", "steps", "assertions", "acceptance", "devices", "writes", "as_a", "notes"}


def parse_stories(data: Any, source: str = "") -> list[Story]:
    items = data.get("stories") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{source}: expected {{\"stories\": [...]}} with at least one story")
    out, seen = [], set()
    for i, s in enumerate(items):
        where = f"{source} stories[{i}]"
        if not isinstance(s, dict):
            raise ConfigError(f"{where}: each story must be an object")
        unknown = set(s) - STORY_KEYS
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")
        for k in ("id", "title", "start"):
            if not isinstance(s.get(k), str) or not s.get(k):
                raise ConfigError(f"{where}: '{k}' is required")
        if s["id"] in seen:
            raise ConfigError(f"{where}: duplicate story id {s['id']}")
        seen.add(s["id"])
        steps = [validate_step(x, f"{where}.steps[{j}]") for j, x in enumerate(s.get("steps") or [])]
        asserts = [validate_assertion(x, f"{where}.assertions[{j}]") for j, x in enumerate(s.get("assertions") or [])]
        acc = s.get("acceptance") or []
        if not isinstance(acc, list) or not all(isinstance(a, str) for a in acc):
            raise ConfigError(f"{where}: 'acceptance' must be a list of strings")
        if not asserts and not acc:
            raise ConfigError(f"{where}: give mechanical 'assertions', human 'acceptance' criteria, or both")
        devs = s.get("devices")
        if devs is not None:
            bad = [d for d in devs if d not in DEVICE_PROFILES]
            if bad:
                raise ConfigError(f"{where}: unknown device(s) {bad}")
        out.append(Story(id=s["id"], title=s["title"], start=s["start"], steps=steps, assertions=asserts,
                         acceptance=acc, devices=devs, writes=bool(s.get("writes", False))))
    return out


def plan(stories: list[Story], persona: Persona, only_devices: list[str] | None) -> list[tuple[Story, str]]:
    """Story x device matrix: a story's own device list narrows the persona's."""
    pairs = []
    for s in stories:
        devs = only_devices or persona.devices
        if s.devices:
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
    screenshot: str = ""
    final_url: str = ""
    elapsed_s: float = 0.0
    steps: list[dict] = field(default_factory=list)


def classify(assertions: list[dict], checks: list[dict], has_assertions: bool) -> tuple[str, str]:
    failed_a = [a for a in assertions if not a["passed"]]
    failed_c = [c for c in checks if not c["passed"]]
    if failed_a:
        return "failed", failed_a[0]["detail"]
    if failed_c:
        return "failed", f"{failed_c[0]['check']}: {failed_c[0]['detail']}"
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
    failed = [c for c in r.get("checks", []) if not c["passed"]] + [a for a in r.get("assertions", []) if not a["passed"]]
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
- Screenshot: {r.get('screenshot', '')}
- Console errors: {len(r.get('console_errors', []))}
- Writes blocked by the read-only guard: {len(r.get('blocked_writes', []))}
"""


def render_report(persona: Persona, results: list[StoryResult], base_url: str, read_only: bool) -> str:
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
    judge = [r for r in results if r.status == "needs-judgment"]
    if judge:
        lines += ["", "## Needs judgment (look at each screenshot, then report it as JUDGED pass or JUDGED fail)", ""]
        for r in judge:
            lines.append(f"- **{r.story} @ {r.device}**: {r.screenshot}")
            lines += [f"  - [ ] {a}" for a in r.acceptance]
    writes = [(r, w) for r in results for w in r.blocked_writes]
    if writes:
        lines += ["", "## Writes the guard blocked (the UI may show success that did not happen)", ""]
        for r, w in writes[:50]:
            lines.append(f"- {r.story} @ {r.device}: {w['method']} {w['path']} ({w['body_bytes']} bytes)")
    return "\n".join(lines) + "\n"


# ── browser checks ────────────────────────────────────────────────────────────

OVERFLOW_JS = "() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})"
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


def persona_checks(page: Any, persona: Persona, device: str, elapsed: float, console_errors: list[str]) -> list[dict]:
    checks = [{"check": "patience", "passed": elapsed <= persona.patience_seconds,
               "detail": f"{elapsed:.1f}s against a {persona.patience_seconds:g}s budget"}]
    if DEVICE_PROFILES[device].get("is_mobile"):
        dims = page.evaluate(OVERFLOW_JS)
        ok = dims["sw"] <= dims["iw"] + 1
        checks.append({"check": "no-overflow", "passed": ok,
                       "detail": "no horizontal scroll" if ok else f"page is {dims['sw']}px wide in a {dims['iw']}px viewport"})
    if persona.min_tap_target_px:
        small = page.evaluate(TAP_JS, persona.min_tap_target_px)
        checks.append({"check": "tap-targets", "passed": not small,
                       "detail": "all controls large enough" if not small else
                       f"{len(small)} control(s) under {persona.min_tap_target_px}px, e.g. {small[0]}"})
    checks.append({"check": "console", "passed": not console_errors,
                   "detail": "clean" if not console_errors else f"{len(console_errors)} error(s): {console_errors[0][:160]}"})
    return checks


def run_one(pw: Any, browser_name: str, persona: Persona, story: Story, device: str, base_url: str,
            out_dir: Path, read_only: bool, timeout_ms: int) -> StoryResult:
    from playwright.sync_api import TimeoutError as PWTimeout
    steps = [{"goto": story.start}] + story.steps
    res = StoryResult(story=story.id, title=story.title, device=device, status="inconclusive",
                      acceptance=story.acceptance, steps=steps)
    browser = getattr(pw, browser_name).launch()
    try:
        ctx = browser.new_context(**context_kwargs(device, browser_name))
        if read_only:
            install_read_only_guard(ctx, res.blocked_writes)
        page = ctx.new_page()
        page.on("console", lambda m: res.console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: res.console_errors.append(f"uncaught: {e}"))
        t0 = time.monotonic()
        try:
            run_steps(page, steps, base_url, timeout_ms, [], PWTimeout)
            res.elapsed_s = round(time.monotonic() - t0, 2)
            res.assertions = check_assertions(page, story.assertions, timeout_ms, res.console_errors, [])
            res.checks = persona_checks(page, persona, device, res.elapsed_s, res.console_errors)
            res.status, res.reason = classify(res.assertions, res.checks, bool(story.assertions))
            if story.writes and read_only and res.blocked_writes:
                res.reason += " (writes were simulated by the read-only guard)"
        except StepFailure as sf:
            res.elapsed_s = round(time.monotonic() - t0, 2)
            res.status = "failed" if sf.status == "fail" else "inconclusive"
            res.reason = sf.message
        res.final_url = page.url
        shot = out_dir / "screenshots" / f"{story.id}-{device}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(shot), full_page=True)
            res.screenshot = str(shot)
        except Exception:  # noqa: BLE001
            pass
        ctx.close()
    except Exception as exc:  # noqa: BLE001
        res.status, res.reason = "inconclusive", f"harness error: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}"
    finally:
        browser.close()
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="persona_run.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", required=True)
    ap.add_argument("--stories", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--story", action="append", default=None, help="only these story ids")
    ap.add_argument("--devices", default="", help="comma list overriding the persona's devices")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    ap.add_argument("--out", default=None, help="default .qa/persona/<persona-name>")
    ap.add_argument("--timeout-ms", type=int, default=10000)
    ap.add_argument("--allow-writes", action="store_true", help="local targets only")
    ap.add_argument("--file-tickets", action="store_true", help="ticket failures that reproduced on the previous run")
    ap.add_argument("--plan", action="store_true", help="print the matrix and exit")
    args = ap.parse_args(argv)

    try:
        persona = parse_persona(Path(args.persona).read_text(encoding="utf-8"), args.persona)
        stories = parse_stories(qa_yaml.load_file(args.stories), args.stories)
        if args.story:
            wanted = set(args.story)
            missing = wanted - {s.id for s in stories}
            if missing:
                raise ConfigError(f"unknown story id(s): {sorted(missing)}")
            stories = [s for s in stories if s.id in wanted]
        only = [d.strip() for d in args.devices.split(",") if d.strip()] or None
        if only and any(d not in DEVICE_PROFILES for d in only):
            raise ConfigError(f"unknown device in {only}; known: {sorted(DEVICE_PROFILES)}")
        for s in stories:
            resolve_url(s.start, args.base_url)
        if args.allow_writes and not writes_allowed(args.base_url):
            raise ConfigError(f"--allow-writes is refused for {args.base_url}: only localhost targets may take writes")
    except (OSError, ConfigError, qa_yaml.YamlError, json.JSONDecodeError) as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    matrix = plan(stories, persona, only)
    if args.plan:
        for s, d in matrix:
            print(f"{s.id:10} {d:18} {s.title}")
        print(f"{len(matrix)} run(s) for persona {persona.name}")
        return EXIT_PASS
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("CONFIG ERROR: Playwright is not installed. Run:\n"
              "  pip install playwright && python3 -m playwright install chromium", file=sys.stderr)
        return EXIT_CONFIG

    slug = re.sub(r"[^a-z0-9]+", "-", persona.name.lower()).strip("-") or "persona"
    out = Path(args.out or f".qa/persona/{slug}")
    out.mkdir(parents=True, exist_ok=True)
    read_only = not args.allow_writes
    results: list[StoryResult] = []
    with sync_playwright() as pw:
        for story, device in matrix:
            r = run_one(pw, args.browser, persona, story, device, args.base_url, out, read_only, args.timeout_ms)
            results.append(r)
            print(f"{r.status.upper():15} {story.id} @ {device}: {r.reason}")

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
    res_path.write_text(json.dumps({"persona": persona.name, "base_url": args.base_url, "read_only": read_only,
                                    "ran_at": datetime.now(timezone.utc).isoformat(), "exit_code": code,
                                    "results": current}, indent=2))
    (out / "REPORT.md").write_text(render_report(persona, results, args.base_url, read_only))
    if args.file_tickets:
        repro = reproduced_failures(previous, current)
        tdir = out / "tickets"
        tdir.mkdir(exist_ok=True)
        for r in repro:
            (tdir / f"{r['story']}-{r['device']}.md").write_text(render_ticket(r, persona.name, args.base_url))
        print(f"{len(repro)} ticket(s) written to {tdir} (failures seen on two runs in a row)")
    counts = {k: sum(1 for r in results if r.status == k) for k in ("passed", "failed", "needs-judgment", "inconclusive")}
    print(f"Tested as {persona.name}: {counts['passed']} of {len(results)} pass, {counts['failed']} fail, "
          f"{counts['needs-judgment']} need judgment, {counts['inconclusive']} inconclusive.  report: {out / 'REPORT.md'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
