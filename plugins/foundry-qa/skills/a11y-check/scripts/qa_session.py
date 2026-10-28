#!/usr/bin/env python3
"""qa_session: browser-session helpers shared by every foundry-qa script.

  1. Signed-in apps. One `auth` block, the same in done_gate.py, persona_run.py,
     explore.py, a11y_check.py and visual_baseline.py (a journey key, or --auth FILE):

       auth: {storage_state: .qa/auth.json}                 # Playwright storage state (cookies + localStorage)
       auth: {headers: {Authorization: "Bearer ${QA_TOKEN}"}}  # ${VAR} is read from the environment at run time
       auth: {cookies: [{name: session, value: "${QA_SESSION}"}]}   # domain/path default to the base URL
       auth: {login_steps: [{goto: /login}, {fill: {...}}, {click: "..."}]}  # same step vocabulary as a journey

     Make the storage state once with the login helper (below) and never commit it.

  2. Browser launch with a readable fix when Playwright or its browser is missing.

  3. settle(): wait until async data has rendered (network quiet, an optional
     selector, then a short settle) and report WHEN the content was ready.

Login helper (saves a signed-in storage state):

  # scripted: run login steps headless, then save
  python3 qa_session.py login --url http://localhost:3000/login --steps qa/login.yaml --out .qa/auth.json
  # by hand: a browser window opens, you sign in, the state is saved when the selector appears
  python3 qa_session.py login --url http://localhost:3000/login --wait-for "[data-testid=dashboard]" --out .qa/auth.json

--steps takes a file with `login_steps: [...]`, or a journey file whose auth block has them.
Exit codes: 0 saved, 1 the sign-in did not complete in time (nothing saved), 2 config error.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_yaml  # noqa: E402

AUTH_KEYS = ("storage_state", "headers", "cookies", "login_steps")
COOKIE_KEYS = {"name", "value", "domain", "path", "url", "expires", "httpOnly", "secure", "sameSite"}
DEFAULT_SETTLE_MS = 800
NETWORK_QUIET_MS = 500


class SessionError(ValueError):
    """A bad auth block, a missing storage-state file or a missing environment variable."""


class BrowserMissing(RuntimeError):
    """Playwright, or the browser build it needs, is not installed."""


# ── Playwright missing: one fix, printed by every script ─────────────────────

def playwright_fix(browser: str = "chromium") -> str:
    return ("Playwright or its browser is not installed. Fix it inside a virtual environment:\n"
            "  python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\\Scripts\\activate\n"
            "  pip install playwright\n"
            f"  python3 -m playwright install {browser}\n"
            "then re-run this command with the venv active.")


def import_sync_playwright(browser: str = "chromium") -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserMissing(playwright_fix(browser)) from None
    return sync_playwright


def is_missing_browser(exc: BaseException) -> bool:
    msg = str(exc)
    return ("Executable doesn't exist" in msg or "playwright install" in msg
            or "Looks like Playwright" in msg)


def launch(pw: Any, browser: str = "chromium", headless: bool = True) -> Any:
    """Launch a browser. A missing browser build raises BrowserMissing with the fix, not a stack trace."""
    try:
        return getattr(pw, browser).launch(headless=headless)
    except Exception as exc:  # noqa: BLE001
        if is_missing_browser(exc):
            raise BrowserMissing(playwright_fix(browser)) from None
        raise


# ── auth block (pure parts unit-tested) ───────────────────────────────────────

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: str, env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env

    def sub(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name not in env:
            raise SessionError(f"auth uses ${{{name}}} but the environment variable {name} is not set")
        return env[name]
    return _VAR.sub(sub, value)


def parse_auth(data: Any, where: str = "auth",
               validate_step: Optional[Callable[[Any, str], dict]] = None) -> Optional[dict]:
    """Validate an auth block and return a normalized copy (None when absent)."""
    if data is None:
        return None
    if not isinstance(data, dict) or not data:
        raise SessionError(f"{where}: must be a mapping with one of {list(AUTH_KEYS)}")
    unknown = set(data) - set(AUTH_KEYS)
    if unknown:
        raise SessionError(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {list(AUTH_KEYS)}")
    out: dict = {}
    if "storage_state" in data:
        v = data["storage_state"]
        if not isinstance(v, str) or not v:
            raise SessionError(f"{where}.storage_state: needs a file path")
        out["storage_state"] = v
    if "headers" in data:
        v = data["headers"]
        if not isinstance(v, dict) or not v or not all(isinstance(k, str) and k for k in v):
            raise SessionError(f"{where}.headers: needs a mapping of header name to value")
        out["headers"] = {k: str(x) for k, x in v.items()}
    if "cookies" in data:
        v = data["cookies"]
        if not isinstance(v, list) or not v:
            raise SessionError(f"{where}.cookies: needs a list of {{name, value, domain, path}}")
        cookies = []
        for i, c in enumerate(v):
            if not isinstance(c, dict) or not isinstance(c.get("name"), str) or c.get("value") is None:
                raise SessionError(f"{where}.cookies[{i}]: needs at least name and value")
            bad = set(c) - COOKIE_KEYS
            if bad:
                raise SessionError(f"{where}.cookies[{i}]: unknown key(s) {sorted(bad)}")
            cookies.append({k: (str(x) if k in ("name", "value", "domain", "path", "url") else x)
                            for k, x in c.items()})
        out["cookies"] = cookies
    if "login_steps" in data:
        v = data["login_steps"]
        if not isinstance(v, list) or not v:
            raise SessionError(f"{where}.login_steps: needs a non-empty list of steps")
        steps = [validate_step(s, f"{where}.login_steps[{i}]") if validate_step else s for i, s in enumerate(v)]
        if not (isinstance(steps[0], dict) and "goto" in steps[0]):
            raise SessionError(f"{where}.login_steps: the first step must be a goto")
        out["login_steps"] = steps
    return out


def merge_auth(base: Optional[dict], override: Optional[dict]) -> Optional[dict]:
    """Command-line auth wins key by key over the file's auth block."""
    if not base:
        return dict(override) if override else None
    if not override:
        return dict(base)
    merged = dict(base)
    if "headers" in base and "headers" in override:
        merged["headers"] = {**base["headers"], **override["headers"]}
        override = {k: v for k, v in override.items() if k != "headers"}
    merged.update(override)
    return merged


def add_auth_args(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("signed-in apps (see qa_session.py)")
    g.add_argument("--auth", default=None, metavar="FILE",
                   help="a file holding an auth block, or any journey file with an auth: block")
    g.add_argument("--storage-state", default=None, metavar="FILE",
                   help="Playwright storage state saved by `qa_session.py login`")
    g.add_argument("--header", action="append", default=[], metavar="'Name: value'",
                   help="extra request header, repeatable; ${VAR} is read from the environment")


def auth_from_args(args: argparse.Namespace,
                   validate_step: Optional[Callable[[Any, str], dict]] = None) -> Optional[dict]:
    auth: Optional[dict] = None
    if getattr(args, "auth", None):
        try:
            data = qa_yaml.load_file(args.auth)
        except FileNotFoundError:
            raise SessionError(f"--auth file not found: {args.auth}")
        except Exception as exc:  # noqa: BLE001  (YamlError or JSONDecodeError)
            raise SessionError(f"--auth {args.auth}: {exc}")
        block = data.get("auth") if isinstance(data, dict) and "auth" in data else data
        if block is None:
            raise SessionError(f"--auth {args.auth}: no auth block found")
        auth = parse_auth(block, f"{args.auth} auth", validate_step)
    cli: dict = {}
    if getattr(args, "storage_state", None):
        cli["storage_state"] = args.storage_state
    headers = {}
    for h in getattr(args, "header", None) or []:
        name, sep, value = h.partition(":")
        if not sep or not name.strip():
            raise SessionError(f"--header {h!r}: use 'Name: value'")
        headers[name.strip()] = value.strip()
    if headers:
        cli["headers"] = headers
    return merge_auth(auth, parse_auth(cli, "command line") if cli else None)


def check_ready(auth: Optional[dict]) -> None:
    """Fail early (config error) on a missing storage-state file or environment variable."""
    if not auth:
        return
    ss = auth.get("storage_state")
    if ss and not Path(ss).is_file():
        raise SessionError(
            f"storage_state {ss} does not exist. Create it once with:\n"
            f"  python3 {Path(__file__).resolve()} login --url <sign-in url> --out {ss}")
    for v in (auth.get("headers") or {}).values():
        expand_env(v)
    for c in auth.get("cookies") or []:
        expand_env(str(c.get("value", "")))


def context_options(auth: Optional[dict]) -> dict:
    """Extra Playwright new_context() kwargs for an auth block."""
    if not auth:
        return {}
    kw: dict = {}
    if auth.get("storage_state"):
        check_ready({"storage_state": auth["storage_state"]})
        kw["storage_state"] = auth["storage_state"]
    if auth.get("headers"):
        kw["extra_http_headers"] = {k: expand_env(v) for k, v in auth["headers"].items()}
    return kw


def cookies_for(auth: Optional[dict], base_url: str) -> list[dict]:
    """Cookies ready for context.add_cookies(): env expanded, url filled from base_url when no domain."""
    out = []
    parts = urlsplit(base_url or "")
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    for c in (auth or {}).get("cookies") or []:
        c = {k: (expand_env(v) if isinstance(v, str) else v) for k, v in c.items()}
        if not c.get("url") and not c.get("domain"):
            if not origin:
                raise SessionError(f"cookie {c['name']!r} has no domain; give it one or pass a base URL")
            c["url"] = origin
        elif c.get("domain") and not c.get("path"):
            c["path"] = "/"
        out.append(c)
    return out


def apply_auth(context: Any, page: Any, auth: Optional[dict], base_url: str,
               run_login_steps: Optional[Callable[[Any, list], None]] = None) -> None:
    """Add cookies, then run login_steps on the page. Call BEFORE any read-only guard."""
    if not auth:
        return
    cookies = cookies_for(auth, base_url)
    if cookies:
        context.add_cookies(cookies)
    if auth.get("login_steps"):
        if run_login_steps is None:
            raise SessionError("login_steps need a step runner")
        run_login_steps(page, auth["login_steps"])


# ── settle: wait for async content, and say when it was ready ────────────────

class NetTracker:
    """Counts in-flight requests on a page and remembers when the last one ended."""

    def __init__(self, page: Any):
        self.inflight = 0
        self.last = time.monotonic()
        page.on("request", self._start)
        page.on("requestfinished", self._end)
        page.on("requestfailed", self._end)

    def _start(self, _r: Any) -> None:
        self.inflight += 1
        self.last = time.monotonic()

    def _end(self, _r: Any) -> None:
        self.inflight = max(0, self.inflight - 1)
        self.last = time.monotonic()


def settle(page: Any, tracker: Optional[NetTracker], timeout_ms: int, wait_for: Optional[str] = None,
           settle_ms: int = DEFAULT_SETTLE_MS) -> tuple[float, str]:
    """Wait for network quiet (no request for 500 ms), then `wait_for` visible, then settle_ms.

    Returns (monotonic time the content was ready, note). Ready = when the last
    request finished or the selector appeared, whichever is later; not the
    load event. A `wait_for` that never appears raises the Playwright timeout.
    """
    note = ""
    ready = time.monotonic()
    if tracker is not None:
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            now = time.monotonic()
            if tracker.inflight == 0 and (now - tracker.last) * 1000 >= NETWORK_QUIET_MS:
                ready = max(ready, tracker.last)
                break
            if now >= deadline:
                note = f"network never went quiet within {timeout_ms} ms"
                ready = now
                break
            page.wait_for_timeout(100)
    if wait_for:
        page.locator(wait_for).first.wait_for(state="visible", timeout=timeout_ms)
        ready = max(ready, time.monotonic())
    if settle_ms > 0:
        page.wait_for_timeout(settle_ms)
    return ready, note


# ── login helper ──────────────────────────────────────────────────────────────

def _load_login_steps(path: str, validate_step: Callable[[Any, str], dict]) -> list[dict]:
    try:
        data = qa_yaml.load_file(path)
    except FileNotFoundError:
        raise SessionError(f"--steps file not found: {path}")
    except Exception as exc:  # noqa: BLE001
        raise SessionError(f"--steps {path}: {exc}")
    steps = None
    if isinstance(data, dict):
        steps = data.get("login_steps") or (data.get("auth") or {}).get("login_steps")
    elif isinstance(data, list):
        steps = data
    if not steps:
        raise SessionError(f"--steps {path}: no login_steps found (a list, login_steps: [...], or auth.login_steps)")
    return parse_auth({"login_steps": steps}, path, validate_step)["login_steps"]


def login_main(argv: Optional[list[str]] = None) -> int:
    import done_gate as dg
    ap = argparse.ArgumentParser(prog="qa_session.py login", description="save a signed-in Playwright storage state")
    ap.add_argument("--url", required=True, help="the sign-in page (or the base URL when --steps has absolute gotos)")
    ap.add_argument("--out", default=".qa/auth.json")
    ap.add_argument("--steps", default=None, help="file with login_steps: run them headless instead of waiting for a human")
    ap.add_argument("--wait-for", default=None, help="selector that is visible only when signed in")
    ap.add_argument("--url-contains", default=None, help="URL text that means signed in (for example /dashboard)")
    ap.add_argument("--timeout-s", type=int, default=300, help="how long to wait for a human sign-in")
    ap.add_argument("--device", default="desktop-1440x900")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    ap.add_argument("--headed", action="store_true", help="show the browser for scripted --steps too")
    args = ap.parse_args(argv)
    try:
        if args.device not in dg.DEVICE_PROFILES:
            raise SessionError(f"unknown device {args.device}; known: {sorted(dg.DEVICE_PROFILES)}")
        steps = _load_login_steps(args.steps, dg.validate_step) if args.steps else None
        if not steps and not (args.wait_for or args.url_contains):
            raise SessionError("a human sign-in needs --wait-for or --url-contains so the helper knows when you are in")
        sync_playwright = import_sync_playwright(args.browser)
    except (SessionError, dg.ConfigError) as exc:
        print(f"LOGIN: CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    except BrowserMissing as exc:
        print(f"LOGIN: CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    from playwright.sync_api import TimeoutError as PWTimeout
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        try:
            browser = launch(pw, args.browser, headless=bool(steps) and not args.headed)
        except BrowserMissing as exc:
            print(f"LOGIN: CONFIG ERROR: {exc}", file=sys.stderr)
            return 2
        try:
            ctx = browser.new_context(**dg.context_kwargs(args.device, args.browser))
            page = ctx.new_page()
            timeout_ms = args.timeout_s * 1000
            try:
                if steps:
                    dg.run_steps(page, steps, args.url, 15000, [], PWTimeout)
                else:
                    page.goto(args.url, wait_until="load", timeout=30000)
                    print(f"Sign in in the browser window (waiting up to {args.timeout_s} s).", flush=True)
                if args.wait_for:
                    page.locator(args.wait_for).first.wait_for(state="visible", timeout=timeout_ms if not steps else 15000)
                if args.url_contains:
                    page.wait_for_url(re.compile(re.escape(args.url_contains)), timeout=timeout_ms if not steps else 15000)
                page.wait_for_timeout(300)
            except dg.StepFailure as sf:
                print(f"LOGIN: NOT SAVED: sign-in step failed: {sf.message}", file=sys.stderr)
                return 1
            except PWTimeout:
                print("LOGIN: NOT SAVED: the signed-in signal never appeared "
                      f"({args.wait_for or args.url_contains}). Nothing was written.", file=sys.stderr)
                return 1
            ctx.storage_state(path=str(out))
            try:
                os.chmod(out, 0o600)
            except OSError:
                pass
            ctx.close()
        finally:
            browser.close()
    print(f"LOGIN: SAVED {out}. It is a live session: keep it out of git (add .qa/ to .gitignore).\n"
          f"Use it with --storage-state {out}, or auth: {{storage_state: {out}}} in a journey.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "login":
        print(__doc__)
        return 2
    return login_main(argv[1:])


if __name__ == "__main__":
    import qa_session as _self  # run as the importable module so classes match done_gate's
    sys.exit(_self.main())
