#!/usr/bin/env python3
"""explore: a same-origin crawler that collects the cheap, mechanical signals
a curious human tester would trip over, so the explorer agent can spend its
attention on judgment.

  python3 explore.py --url http://localhost:3000 --max-pages 40
  python3 explore.py --url https://<your-app>.example.com --max-pages 25 --devices phone-390x844

READ-ONLY by default (every non-GET/HEAD/OPTIONS request is answered locally,
never sent). It never submits forms. Double-submit and edge-case input testing
is done by the explorer agent by hand, and only on a local or staging target.

Per page it records:
  error   console errors, uncaught exceptions, HTTP >= 500, failed requests,
          a page that does not load, a broken same-origin link (HTTP 404/410)
  warn    a back-button that does not return to the previous URL, HTTP 4xx on
          a sub-request, horizontal overflow on a mobile profile, missing <title>
          or <h1>, images without alt
  look    near-empty main content (an empty state: is it designed, or blank?)

Exit codes: 0 no errors, 1 at least one error-level finding, 2 config error,
6 the start URL could not be reached (nothing explored).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_INCONCLUSIVE = 0, 1, 2, 6
SKIP_EXT = (".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".mp3", ".dmg", ".exe")
SKIP_WORDS = ("logout", "log-out", "signout", "sign-out", "delete", "remove", "unsubscribe")


@dataclass
class Finding:
    severity: str   # error | warn | look
    kind: str
    url: str
    detail: str
    device: str = ""


@dataclass
class PageVisit:
    url: str
    device: str
    status: int = 0
    title: str = ""
    screenshot: str = ""
    links: int = 0
    findings: list[Finding] = field(default_factory=list)


def normalize(url: str) -> str:
    """Drop the fragment and a trailing slash so /a and /a/ are one page. Pure."""
    u, _ = urldefrag(url)
    parts = urlsplit(u)
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme}://{parts.netloc}{path}" + (f"?{parts.query}" if parts.query else "")


def should_visit(url: str, origin: str) -> bool:
    """Same origin, http(s), not a file download, not a destructive-looking link. Pure."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    if f"{parts.scheme}://{parts.netloc}" != origin:
        return False
    low = parts.path.lower()
    if low.endswith(SKIP_EXT):
        return False
    return not any(w in low for w in SKIP_WORDS)


def verdict(visits: list[PageVisit], start_reached: bool) -> int:
    if not start_reached:
        return EXIT_INCONCLUSIVE
    return EXIT_FAIL if any(f.severity == "error" for v in visits for f in v.findings) else EXIT_PASS


CLICK_LINK_JS = """
(as, t) => {
  const norm = (h) => h.replace(/#.*$/, '').replace(/\\/$/, '');
  const a = as.find(x => norm(x.href) === norm(t));
  if (a) { a.removeAttribute('target'); a.click(); }
}
"""

PAGE_FACTS_JS = """
() => {
  const main = document.querySelector('main') || document.body;
  return {
    title: document.title || '',
    h1: document.querySelectorAll('h1').length,
    imgNoAlt: [...document.images].filter(i => !i.hasAttribute('alt')).length,
    mainText: (main ? main.innerText : '').trim().length,
    sw: document.documentElement.scrollWidth, iw: window.innerWidth,
    links: [...document.querySelectorAll('a[href]')].map(a => a.href),
  };
}
"""


def crawl(start: str, max_pages: int, devices: list[str], browser_name: str, out: Path,
          read_only: bool, back_checks: int) -> tuple[list[PageVisit], bool]:
    from playwright.sync_api import sync_playwright
    from done_gate import DEVICE_PROFILES, context_kwargs, install_read_only_guard
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(start))
    visits: list[PageVisit] = []
    start_reached = False
    (out / "screenshots").mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        try:
            for device in devices:
                ctx = browser.new_context(**context_kwargs(device, browser_name))
                blocked: list[dict] = []
                if read_only:
                    install_read_only_guard(ctx, blocked)
                page = ctx.new_page()
                events: list[Finding] = []
                page.on("console", lambda m: events.append(Finding("error", "console", page.url, m.text[:300], device))
                        if m.type == "error" else None)
                page.on("pageerror", lambda e: events.append(Finding("error", "uncaught", page.url, str(e)[:300], device)))
                page.on("requestfailed", lambda r: events.append(
                    Finding("error", "request-failed", page.url, f"{r.method} {r.url} {r.failure}", device))
                    if "ERR_ABORTED" not in str(r.failure) else None)
                page.on("response", lambda r: events.append(Finding(
                    "error" if r.status >= 500 else "warn", f"http-{r.status}", page.url,
                    f"{r.request.method} {r.url}", device)) if r.status >= 400 and r.request.resource_type != "document" else None)
                queue: deque[tuple[str, str | None]] = deque([(normalize(start), None)])
                seen: set[str] = {normalize(start)}
                backs_done = 0
                n = 0
                while queue and n < max_pages:
                    url, parent = queue.popleft()
                    n += 1
                    visit = PageVisit(url=url, device=device)
                    events.clear()
                    try:
                        resp = page.goto(url, wait_until="networkidle", timeout=20000)
                        visit.status = resp.status if resp else 0
                        if url == normalize(start):
                            start_reached = True
                    except Exception as exc:  # noqa: BLE001
                        visit.findings.append(Finding("error", "load-failed", url, str(exc).splitlines()[0], device))
                        visits.append(visit)
                        continue
                    if visit.status in (404, 410):
                        visit.findings.append(Finding("error", "broken-link", url,
                                                      f"HTTP {visit.status}, linked from {parent}", device))
                    elif visit.status >= 500:
                        visit.findings.append(Finding("error", f"http-{visit.status}", url, "page failed", device))
                    facts = page.evaluate(PAGE_FACTS_JS)
                    visit.title = facts["title"]
                    if not facts["title"]:
                        visit.findings.append(Finding("warn", "no-title", url, "page has no <title>", device))
                    if facts["h1"] == 0:
                        visit.findings.append(Finding("warn", "no-h1", url, "page has no <h1>", device))
                    if facts["imgNoAlt"]:
                        visit.findings.append(Finding("warn", "img-no-alt", url, f"{facts['imgNoAlt']} image(s) without alt", device))
                    if facts["mainText"] < 40:
                        visit.findings.append(Finding("look", "empty-state", url,
                                                      f"main content has {facts['mainText']} characters: designed empty state or blank?", device))
                    if DEVICE_PROFILES[device].get("is_mobile") and facts["sw"] > facts["iw"] + 1:
                        visit.findings.append(Finding("warn", "overflow", url,
                                                      f"{facts['sw']}px wide in a {facts['iw']}px viewport", device))
                    shot = out / "screenshots" / f"{device}-{n:03d}.png"
                    try:
                        page.screenshot(path=str(shot), full_page=True)
                        visit.screenshot = str(shot)
                    except Exception:  # noqa: BLE001
                        pass
                    links = [normalize(h) for h in facts["links"]]
                    visit.links = len(links)
                    for link in links:
                        if link not in seen and should_visit(link, origin):
                            seen.add(link)
                            queue.append((link, url))
                    # back-button check: click the first unvisited-in-this-check link, go back, compare.
                    if backs_done < back_checks:
                        target = next((l for l in links if should_visit(l, origin) and l != url), None)
                        if target:
                            backs_done += 1
                            try:
                                with page.expect_navigation(timeout=10000):
                                    page.locator("a[href]").evaluate_all(CLICK_LINK_JS, target)
                                page.wait_for_load_state("networkidle", timeout=10000)
                                if normalize(page.url) != url:
                                    page.go_back(wait_until="networkidle", timeout=10000)
                                    if normalize(page.url) != url:
                                        visit.findings.append(Finding("warn", "back-button", url,
                                                                      f"after opening {target}, Back landed on {page.url}", device))
                            except Exception as exc:  # noqa: BLE001
                                visit.findings.append(Finding("look", "back-button", url,
                                                              f"could not complete the back check: {str(exc).splitlines()[0]}", device))
                    visit.findings.extend(events)
                    visits.append(visit)
                if blocked:
                    visits.append(PageVisit(url="(read-only guard)", device=device, findings=[
                        Finding("look", "blocked-writes", start, f"{len(blocked)} write request(s) blocked during the crawl", device)]))
                ctx.close()
        finally:
            browser.close()
    return visits, start_reached


def main(argv: list[str] | None = None) -> int:
    from done_gate import DEVICE_PROFILES
    from persona_run import writes_allowed
    ap = argparse.ArgumentParser(prog="explore.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--devices", default="desktop-1440x900")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    ap.add_argument("--back-checks", type=int, default=10)
    ap.add_argument("--out", default=".qa/explore")
    ap.add_argument("--allow-writes", action="store_true", help="local targets only")
    args = ap.parse_args(argv)
    devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    if any(d not in DEVICE_PROFILES for d in devices) or args.max_pages < 1:
        print(f"CONFIG ERROR: check --devices (known: {sorted(DEVICE_PROFILES)}) and --max-pages", file=sys.stderr)
        return EXIT_CONFIG
    if args.allow_writes and not writes_allowed(args.url):
        print("CONFIG ERROR: --allow-writes is only allowed against localhost", file=sys.stderr)
        return EXIT_CONFIG
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("CONFIG ERROR: pip install playwright && python3 -m playwright install chromium", file=sys.stderr)
        return EXIT_CONFIG
    out = Path(args.out)
    visits, reached = crawl(args.url, args.max_pages, devices, args.browser, out, not args.allow_writes, args.back_checks)
    code = verdict(visits, reached)
    findings = [asdict(f) for v in visits for f in v.findings]
    (out / "findings.json").write_text(json.dumps({"exit_code": code, "pages": [asdict(v) for v in visits]}, indent=2))
    for sev in ("error", "warn", "look"):
        group = [f for f in findings if f["severity"] == sev]
        for f in group[:40]:
            print(f"{sev.upper():6} {f['kind']:16} {f['url']}  {f['detail'][:140]}")
    pages = len([v for v in visits if not v.url.startswith("(")])
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("error", "warn", "look")}
    label = {0: "NO ERRORS", 1: "ERRORS FOUND", 6: "INCONCLUSIVE (start URL unreachable)"}[code]
    print(f"EXPLORE: {label} (exit {code}): {pages} page visit(s), {counts['error']} error, "
          f"{counts['warn']} warn, {counts['look']} look.  findings: {out / 'findings.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
