#!/usr/bin/env python3
"""a11y_check: run axe-core in a real browser against pages, report WCAG violations.

  python3 a11y_check.py --url http://localhost:3000/ --url http://localhost:3000/signup
  python3 a11y_check.py --url http://localhost:3000/ --devices desktop-1440x900,phone-390x844 --fail-on moderate
  python3 a11y_check.py --journey qa/done-journey.yaml --base-url http://localhost:3000   # audit the state a journey reaches
  python3 a11y_check.py --url http://localhost:3000/dashboard --storage-state .qa/auth.json   # a signed-in page

Besides axe, it runs its own WCAG 2.2 target-size check (2.5.8, AA): every
visible control smaller than 24x24 CSS px. One whose 24 px circle overlaps
another target fails (a blocking "target-size-2.5.8" violation, impact
serious); one that is spaced far enough passes through the spacing exception
but is listed under "small targets" for manual review. Inline links in a
sentence are exempt.

Exit codes:
  0  no violation at or above --fail-on (default: serious)
  1  violations at or above --fail-on
  2  config error (bad arguments, Playwright missing, unreadable journey)
  6  inconclusive: a page could not load, or axe-core could not be loaded/run.
     Not a pass.

axe-core is loaded from --axe-source (a local file path or an https URL; the
default is a pinned cdnjs build) and cached in .qa/cache/. It is injected with
page.evaluate, so a strict Content-Security-Policy on your app does not block it.

Remember: axe finds roughly a third to a half of real WCAG problems. A clean run
is the floor, not the finish. Do the manual checks in the a11y-check skill.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_session  # noqa: E402

EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_INCONCLUSIVE = 0, 1, 2, 6
AXE_DEFAULT = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"
WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
IMPACT_ORDER = {"minor": 1, "moderate": 2, "serious": 3, "critical": 4}


def load_axe_source(source: str, cache_dir: Path) -> str:
    if not source.startswith(("http://", "https://")):
        return Path(source).read_text(encoding="utf-8")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / ("axe-" + source.rstrip("/").split("/")[-2] + ".min.js")
    if cached.exists() and cached.stat().st_size > 10000:
        return cached.read_text(encoding="utf-8")
    req = urllib.request.Request(source, headers={"User-Agent": "foundry-qa-a11y"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    cached.write_text(text, encoding="utf-8")
    return text


def summarize(raw: dict, fail_on: str) -> dict:
    """Reduce an axe result to what a reviewer needs. Pure, unit-tested."""
    floor = IMPACT_ORDER[fail_on]
    violations = []
    for v in raw.get("violations", []):
        impact = v.get("impact") or "minor"
        nodes = v.get("nodes", [])
        violations.append({
            "id": v.get("id"),
            "impact": impact,
            "blocking": IMPACT_ORDER.get(impact, 1) >= floor,
            "help": v.get("help", ""),
            "help_url": v.get("helpUrl", ""),
            "wcag": [t for t in v.get("tags", []) if t.startswith("wcag")],
            "nodes": len(nodes),
            "targets": [", ".join(map(str, n.get("target", []))) for n in nodes[:5]],
            "fix": (nodes[0].get("failureSummary", "") if nodes else "")[:400],
        })
    violations.sort(key=lambda x: (-IMPACT_ORDER.get(x["impact"], 1), -x["nodes"]))
    return {
        "violations": violations,
        "blocking": sum(1 for v in violations if v["blocking"]),
        "incomplete": len(raw.get("incomplete", [])),
        "passes": len(raw.get("passes", [])),
    }


def page_verdict(pages: list[dict]) -> int:
    if not pages:
        return EXIT_INCONCLUSIVE
    if any(p.get("error") for p in pages):
        if any(p.get("blocking", 0) for p in pages):
            return EXIT_FAIL
        return EXIT_INCONCLUSIVE
    return EXIT_FAIL if any(p["blocking"] for p in pages) else EXIT_PASS


RUN_AXE = """
async (tags) => {
  const r = await axe.run(document, { runOnly: { type: 'tag', values: tags }, resultTypes: ['violations', 'incomplete'] });
  return { violations: r.violations, incomplete: r.incomplete, passes: r.passes };
}
"""


TARGET_MIN_PX = 24
TARGET_SIZE_JS = """
(min) => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], '
    + '[role=checkbox], [role=radio], [role=switch], [role=tab], [role=menuitem], [tabindex]:not([tabindex="-1"])';
  const all = [...document.querySelectorAll(sel)].filter(el => {
    if (el.disabled || el.closest('[aria-hidden=true], [inert]')) return false;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const targets = all.filter(el => !all.some(o => o !== el && o.contains(el)));
  const rects = targets.map(el => el.getBoundingClientRect());
  const name = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.dataset && el.dataset.testid) s += '[data-testid=' + el.dataset.testid + ']';
    else if (el.getAttribute('aria-label')) s += '[aria-label="' + el.getAttribute('aria-label').slice(0, 40) + '"]';
    else if (typeof el.className === 'string' && el.className.trim()) s += '.' + el.className.trim().split(/\\s+/)[0];
    const t = (el.innerText || el.value || '').trim().slice(0, 30);
    return t ? s + ' "' + t + '"' : s;
  };
  const inline = (el) => el.tagName === 'A' && getComputedStyle(el).display === 'inline'
    && el.parentElement && (el.parentElement.innerText || '').trim().length > (el.innerText || '').trim().length + 10;
  const small = (r) => r.width < min || r.height < min;
  const failing = [], spaced = [];
  targets.forEach((el, i) => {
    const r = rects[i];
    if (!small(r) || inline(el)) return;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    let clash = null;
    targets.forEach((o, j) => {
      if (j === i || clash) return;
      const q = rects[j];
      const nx = Math.max(q.left, Math.min(cx, q.right)), ny = Math.max(q.top, Math.min(cy, q.bottom));
      if (Math.hypot(cx - nx, cy - ny) < min / 2) { clash = o; return; }
      if (small(q) && !inline(o) && Math.hypot(cx - (q.left + q.width / 2), cy - (q.top + q.height / 2)) < min) clash = o;
    });
    const item = {target: name(el), size: Math.round(r.width) + 'x' + Math.round(r.height), near: clash ? name(clash) : null};
    (clash ? failing : spaced).push(item);
  });
  return {failing, small: spaced};
}
"""


def merge_target_size(summary: dict, ts: dict, fail_on: str) -> dict:
    """Fold the 2.5.8 check into an axe summary: failures become a violation, spaced ones manual review. Pure."""
    failing, small = ts.get("failing") or [], ts.get("small") or []
    summary["target_size"] = {"min_px": TARGET_MIN_PX, "failing": failing, "small": small}
    if failing:
        blocking = IMPACT_ORDER["serious"] >= IMPACT_ORDER[fail_on]
        summary["violations"].insert(0, {
            "id": "target-size-2.5.8",
            "impact": "serious",
            "blocking": blocking,
            "help": "Target under 24x24 CSS px with another target inside its 24 px circle (foundry-qa check)",
            "help_url": "https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html",
            "wcag": ["wcag22aa", "wcag258"],
            "nodes": len(failing),
            "targets": [f"{x['target']} {x['size']}" for x in failing[:5]],
            "fix": "Make the control at least 24x24 CSS px (padding or min-width/min-height), or move it "
                   "so a 24 px circle around it touches no other control.",
        })
        summary["blocking"] = sum(1 for v in summary["violations"] if v["blocking"])
    return summary


def audit_page(page, axe_src: str, tags: list[str], fail_on: str) -> dict:
    page.evaluate("(src) => { (0, eval)(src); }", axe_src)
    if not page.evaluate("typeof window.axe !== 'undefined'"):
        raise RuntimeError("axe-core did not load into the page")
    raw = page.evaluate(RUN_AXE, tags)
    return merge_target_size(summarize(raw, fail_on), page.evaluate(TARGET_SIZE_JS, TARGET_MIN_PX), fail_on)


def main(argv: list[str] | None = None) -> int:
    from done_gate import (DEVICE_PROFILES, ConfigError, context_kwargs, load_journey, run_steps, StepFailure,
                           validate_step)
    ap = argparse.ArgumentParser(prog="a11y_check.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--journey", default=None, help="run this journey's steps first, then audit where it lands")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--devices", default="desktop-1440x900")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    ap.add_argument("--fail-on", default="serious", choices=list(IMPACT_ORDER))
    ap.add_argument("--tags", default=",".join(WCAG_TAGS), help="axe rule tags (add best-practice for more)")
    ap.add_argument("--axe-source", default=AXE_DEFAULT)
    ap.add_argument("--out", default=".qa/a11y")
    ap.add_argument("--settle-ms", type=int, default=qa_session.DEFAULT_SETTLE_MS,
                    help="extra wait after the network goes quiet, before axe runs")
    qa_session.add_auth_args(ap)
    args = ap.parse_args(argv)

    devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    if any(d not in DEVICE_PROFILES for d in devices):
        print(f"CONFIG ERROR: unknown device in {devices}; known: {sorted(DEVICE_PROFILES)}", file=sys.stderr)
        return EXIT_CONFIG
    journey = None
    if args.journey:
        try:
            journey = load_journey(args.journey)
        except ConfigError as exc:
            print(f"CONFIG ERROR: {exc}", file=sys.stderr)
            return EXIT_CONFIG
    if not args.url and not journey:
        print("CONFIG ERROR: give --url (repeatable) or --journey", file=sys.stderr)
        return EXIT_CONFIG
    try:
        auth = qa_session.merge_auth(journey.auth if journey else None, qa_session.auth_from_args(args, validate_step))
        qa_session.check_ready(auth)
        sync_playwright = qa_session.import_sync_playwright(args.browser)
    except (qa_session.SessionError, qa_session.BrowserMissing) as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    from playwright.sync_api import TimeoutError as PWTimeout
    out = Path(args.out)
    try:
        axe_src = load_axe_source(args.axe_source, out.parent / "cache")
    except Exception as exc:  # noqa: BLE001
        print(f"INCONCLUSIVE: could not load axe-core from {args.axe_source}: {exc}\n"
              "Download axe.min.js once and pass --axe-source path/to/axe.min.js", file=sys.stderr)
        return EXIT_INCONCLUSIVE
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    pages: list[dict] = []
    with sync_playwright() as pw:
        try:
            browser = qa_session.launch(pw, args.browser)
        except qa_session.BrowserMissing as exc:
            print(f"CONFIG ERROR: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        try:
            targets = [("url", u) for u in args.url] + ([("journey", journey)] if journey else [])
            for kind, target in targets:
                for device in devices:
                    base = target if kind == "url" else (args.base_url or target.base_url)
                    ctx = browser.new_context(**context_kwargs(device, args.browser), **qa_session.context_options(auth))
                    page = ctx.new_page()
                    entry = {"target": target if kind == "url" else f"journey:{target.name}", "device": device}
                    try:
                        qa_session.apply_auth(ctx, page, auth, args.base_url or base,
                                              lambda pg, st: run_steps(pg, st, args.base_url or base, 15000, [], PWTimeout))
                        tracker = qa_session.NetTracker(page)
                        if kind == "url":
                            page.goto(target, wait_until="networkidle", timeout=30000)
                        else:
                            run_steps(page, target.steps, base, target.timeout_ms, target.auth_wall, PWTimeout)
                        qa_session.settle(page, tracker, 15000, None, args.settle_ms)
                        entry["final_url"] = page.url
                        entry.update(audit_page(page, axe_src, tags, args.fail_on))
                    except StepFailure as sf:
                        entry["error"] = sf.message
                    except Exception as exc:  # noqa: BLE001
                        entry["error"] = str(exc).splitlines()[0]
                    finally:
                        ctx.close()
                    pages.append(entry)
                    if entry.get("error"):
                        print(f"INCONCLUSIVE {entry['target']} @ {device}: {entry['error']}")
                    else:
                        small = entry.get("target_size", {}).get("small", [])
                        print(f"{'FAIL' if entry['blocking'] else 'PASS':12} {entry['target']} @ {device}: "
                              f"{entry['blocking']} blocking, {len(entry['violations'])} total, "
                              f"{entry['incomplete'] + len(small)} need manual review")
                        for v in entry["violations"][:8]:
                            mark = "!" if v["blocking"] else " "
                            print(f"   {mark} [{v['impact']}] {v['id']} x{v['nodes']}: {v['help']}  {v['targets'][:1]}")
                        if small:
                            print(f"   ? small-targets x{len(small)} (under 24x24 px, passed only by the spacing "
                                  f"exception; confirm or dismiss): {', '.join(x['target'] + ' ' + x['size'] for x in small[:4])}")
        finally:
            browser.close()

    code = page_verdict(pages)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps({"exit_code": code, "fail_on": args.fail_on, "tags": tags,
                                                 "pages": pages}, indent=2))
    label = {0: "PASS", 1: "FAIL", 6: "INCONCLUSIVE (not a pass)"}[code]
    print(f"A11Y: {label} (exit {code})  report: {out / 'report.json'}")
    print("axe covers part of WCAG. Also run the manual checklist in the a11y-check skill.")
    return code


if __name__ == "__main__":
    sys.exit(main())
