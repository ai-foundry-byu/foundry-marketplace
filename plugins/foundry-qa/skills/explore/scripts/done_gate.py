#!/usr/bin/env python3
"""done_gate: a Definition-of-Done gate for user-facing web features.

A feature is DONE only when this exits 0:

  1. (optional) the deployed build serves the commit you expect, read from a
     URL you configure (a response header, a JSON key, or a regex on the body);
  2. a real browser (Playwright) runs your done-journey on every device
     profile, and every assertion holds.

Exit codes (the contract; scripts and agents branch on these):
  0  PASS          SHA verified (when configured) and every journey passed
  1  JOURNEY FAIL  a step or assertion failed on at least one device
  2  CONFIG ERROR  bad arguments, unreadable or invalid journey file,
                   Playwright or its browser build missing (the fix is
                   printed), a missing storage-state file, base_url still
                   holding PORT with no --port, git could not resolve the SHA
  3  SHA MISMATCH  the deployed build serves a different commit
  6  INCONCLUSIVE  nothing was proven: the target or SHA endpoint was
                   unreachable, no SHA could be read, the browser could not
                   launch, or the journey was bounced to a sign-in wall.
                   INCONCLUSIVE IS NOT A PASS. Never report "done" on 6.

Usage:
  python3 done_gate.py --journey qa/done-journey.yaml --base-url http://localhost:3000
  python3 done_gate.py --journey qa/done-journey.yaml \\
      --base-url https://<your-app>.example.com \\
      --sha-url https://<your-app>.example.com/api/version --sha-json-key commit \\
      --expected-sha HEAD --read-only
  python3 done_gate.py --journey qa/done-journey.yaml --validate   # parse only, no browser
  python3 done_gate.py --journey qa/done-journey.yaml --port 5173   # base_url: http://localhost:PORT
  python3 done_gate.py --journey qa/done-journey.yaml --storage-state .qa/auth.json   # signed-in app

After every run (not --validate) the gate writes .qa/done-gate/last.json:
  {sha, exit, journey, devices, stories, time, failures[]}   (sha = git HEAD when available)
and .qa/done-gate/latest.json (the full result).

Requires: Python 3.9+, and for browser runs (inside a venv):
  pip install playwright && python3 -m playwright install chromium
The journey file is YAML (a built-in subset, see qa_yaml.py) or JSON. PyYAML is
not needed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_session  # noqa: E402
import qa_yaml  # noqa: E402

EXIT_PASS = 0
EXIT_JOURNEY_FAIL = 1
EXIT_CONFIG = 2
EXIT_SHA_MISMATCH = 3
EXIT_INCONCLUSIVE = 6

EXIT_LABELS = {
    EXIT_PASS: "PASS",
    EXIT_JOURNEY_FAIL: "JOURNEY FAIL",
    EXIT_CONFIG: "CONFIG ERROR",
    EXIT_SHA_MISMATCH: "SHA MISMATCH",
    EXIT_INCONCLUSIVE: "INCONCLUSIVE (not a pass)",
}

# ── device profiles ───────────────────────────────────────────────────────────

_IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
_IPAD_UA = ("Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

DEVICE_PROFILES: dict[str, dict[str, Any]] = {
    "desktop-1440x900": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1,
                         "is_mobile": False, "has_touch": False},
    "phone-390x844": {"viewport": {"width": 390, "height": 844}, "user_agent": _IPHONE_UA,
                      "device_scale_factor": 3, "is_mobile": True, "has_touch": True},
    "tablet-820x1180": {"viewport": {"width": 820, "height": 1180}, "user_agent": _IPAD_UA,
                        "device_scale_factor": 2, "is_mobile": True, "has_touch": True},
}
DEFAULT_DEVICES = ["desktop-1440x900"]


def context_kwargs(device: str, browser: str) -> dict[str, Any]:
    """Playwright new_context() kwargs. Firefox has no is_mobile support."""
    kw = json.loads(json.dumps(DEVICE_PROFILES[device]))
    if browser == "firefox":
        kw.pop("is_mobile", None)
    return kw


# ── journey model + validation (pure, unit-tested) ────────────────────────────

STEP_KINDS = {"goto", "click", "fill", "wait_for", "press"}
ASSERT_KINDS = {"visible", "text", "url_contains", "no_console_errors"}
JOURNEY_KEYS = {"name", "base_url", "steps", "assertions", "screenshot", "devices", "stories", "auth",
                "timeout_ms", "auth_wall", "ignore_console", "sha_check", "read_only"}
SHA_CHECK_KEYS = {"url", "header", "json_key", "regex"}


class ConfigError(Exception):
    pass


@dataclass
class Journey:
    name: str
    steps: list[dict]
    assertions: list[dict]
    screenshot: str
    devices: list[str]
    base_url: str = ""
    timeout_ms: int = 10000
    auth_wall: list[str] = field(default_factory=list)
    ignore_console: list[str] = field(default_factory=list)
    sha_check: Optional[dict] = None
    read_only: bool = False
    source: str = ""
    stories: list[str] = field(default_factory=list)
    auth: Optional[dict] = None


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-").lower()
    return s or "journey"


def validate_step(step: Any, where: str) -> dict:
    if not isinstance(step, dict) or len(step) != 1:
        raise ConfigError(f"{where}: each step must be a mapping with exactly one key, got {step!r}")
    (kind, arg), = step.items()
    if kind not in STEP_KINDS:
        raise ConfigError(f"{where}: unknown step '{kind}' (expected one of {sorted(STEP_KINDS)})")
    if kind in ("goto", "click", "wait_for"):
        if not isinstance(arg, str) or not arg:
            raise ConfigError(f"{where}: '{kind}' needs a non-empty string")
    elif kind == "fill":
        if not isinstance(arg, dict) or set(arg) != {"selector", "value"}:
            raise ConfigError(f"{where}: 'fill' needs {{selector, value}}, got {arg!r}")
        if not isinstance(arg["selector"], str) or arg["value"] is None:
            raise ConfigError(f"{where}: 'fill' selector must be a string and value must be set")
        arg = {"selector": arg["selector"], "value": str(arg["value"])}
    elif kind == "press":
        if not isinstance(arg, dict) or set(arg) != {"selector", "key"}:
            raise ConfigError(f"{where}: 'press' needs {{selector, key}}, got {arg!r}")
        if not all(isinstance(arg[k], str) and arg[k] for k in ("selector", "key")):
            raise ConfigError(f"{where}: 'press' selector and key must be non-empty strings")
    return {kind: arg}


def validate_assertion(a: Any, where: str) -> dict:
    if not isinstance(a, dict) or len(a) != 1:
        raise ConfigError(f"{where}: each assertion must be a mapping with exactly one key, got {a!r}")
    (kind, arg), = a.items()
    if kind not in ASSERT_KINDS:
        raise ConfigError(f"{where}: unknown assertion '{kind}' (expected one of {sorted(ASSERT_KINDS)})")
    if kind in ("visible", "url_contains"):
        if not isinstance(arg, str) or not arg:
            raise ConfigError(f"{where}: '{kind}' needs a non-empty string")
    elif kind == "text":
        if not isinstance(arg, dict) or set(arg) != {"selector", "contains"}:
            raise ConfigError(f"{where}: 'text' needs {{selector, contains}}, got {arg!r}")
        arg = {"selector": str(arg["selector"]), "contains": str(arg["contains"])}
    elif kind == "no_console_errors":
        if arg is not True:
            raise ConfigError(f"{where}: 'no_console_errors' must be true (delete the line to skip it)")
    return {kind: arg}


def validate_journey(data: Any, source: str = "") -> Journey:
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: the journey must be a mapping at the top level")
    unknown = set(data) - JOURNEY_KEYS
    if unknown:
        raise ConfigError(f"{source}: unknown key(s) {sorted(unknown)}; allowed: {sorted(JOURNEY_KEYS)}")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ConfigError(f"{source}: 'steps' must be a non-empty list")
    vsteps = [validate_step(s, f"{source} steps[{i}]") for i, s in enumerate(steps)]
    if "goto" not in vsteps[0]:
        raise ConfigError(f"{source}: the first step must be a goto")
    assertions = data.get("assertions") or []
    if not isinstance(assertions, list):
        raise ConfigError(f"{source}: 'assertions' must be a list")
    vasserts = [validate_assertion(a, f"{source} assertions[{i}]") for i, a in enumerate(assertions)]
    if not vasserts:
        raise ConfigError(f"{source}: add at least one assertion; a journey that asserts nothing proves nothing")
    devices = data.get("devices") or list(DEFAULT_DEVICES)
    if isinstance(devices, str):
        devices = [devices]
    bad = [d for d in devices if d not in DEVICE_PROFILES]
    if bad:
        raise ConfigError(f"{source}: unknown device(s) {bad}; known: {sorted(DEVICE_PROFILES)}")
    name = str(data.get("name") or Path(source).stem or "journey")
    sha_check = data.get("sha_check")
    if sha_check is not None:
        if not isinstance(sha_check, dict) or "url" not in sha_check:
            raise ConfigError(f"{source}: 'sha_check' needs at least a url")
        if set(sha_check) - SHA_CHECK_KEYS:
            raise ConfigError(f"{source}: sha_check keys must be among {sorted(SHA_CHECK_KEYS)}")
    timeout = data.get("timeout_ms", 10000)
    if not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError(f"{source}: timeout_ms must be a positive integer")
    def _strlist(key: str) -> list[str]:
        v = data.get(key) or []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ConfigError(f"{source}: '{key}' must be a list of strings")
        return v
    ignore = _strlist("ignore_console")
    stories = _strlist("stories")
    try:
        auth = qa_session.parse_auth(data.get("auth"), f"{source} auth", validate_step)
    except qa_session.SessionError as exc:
        raise ConfigError(str(exc))
    for pat in ignore:
        try:
            re.compile(pat)
        except re.error as exc:
            raise ConfigError(f"{source}: ignore_console pattern {pat!r} is not a valid regex: {exc}")
    return Journey(
        name=name,
        steps=vsteps,
        assertions=vasserts,
        screenshot=_slug(str(data.get("screenshot") or name)),
        devices=list(devices),
        base_url=str(data.get("base_url") or ""),
        timeout_ms=timeout,
        auth_wall=_strlist("auth_wall"),
        ignore_console=ignore,
        sha_check=sha_check,
        read_only=bool(data.get("read_only", False)),
        source=source,
        stories=stories,
        auth=auth,
    )


def load_journey(path: str) -> Journey:
    try:
        data = qa_yaml.load_file(path)
    except FileNotFoundError:
        raise ConfigError(f"journey file not found: {path}")
    except (qa_yaml.YamlError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}")
    return validate_journey(data, source=path)


_PORT = re.compile(r"\bPORT\b")


def resolve_base(base_url: str, port: Any = None) -> str:
    """Fill a PORT placeholder (base_url: http://localhost:PORT) from --port.

    Deliberately not from the PORT environment variable: a stray PORT in a shell
    would point the gate at whatever else is listening there.
    """
    if not base_url or not _PORT.search(base_url):
        return base_url
    if not port:
        raise ConfigError(f"base_url {base_url!r} holds PORT: pass --port N (the port your app is on) "
                          "or pass --base-url")
    if not str(port).isdigit():
        raise ConfigError(f"port {port!r} is not a number")
    return _PORT.sub(str(port), base_url)


def resolve_url(target: str, base_url: str) -> str:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return target
    if not base_url:
        raise ConfigError(f"relative goto '{target}' needs --base-url or base_url in the journey")
    return urljoin(base_url.rstrip("/") + "/", target.lstrip("/"))


# ── SHA check (pure parts unit-tested) ────────────────────────────────────────

_HEX40 = re.compile(r"\b[0-9a-f]{40}\b", re.I)
_SHA_LIKE = re.compile(r"^[0-9a-f]{7,40}$", re.I)
DEFAULT_JSON_KEYS = ("sha", "commit", "commitSha", "gitSha", "git_sha", "version")


def _dig(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def extract_sha(headers: dict[str, str], body: str, header: str | None = None,
                json_key: str | None = None, regex: str | None = None) -> str | None:
    """Pull a commit SHA out of a response. Explicit config wins; else best effort."""
    lower = {k.lower(): v for k, v in headers.items()}
    if header:
        v = lower.get(header.lower())
        return v.strip() if v and _SHA_LIKE.match(v.strip()) else None
    if regex:
        m = re.search(regex, body)
        if not m:
            return None
        v = (m.group(1) if m.groups() else m.group(0)).strip()
        return v if _SHA_LIKE.match(v) else None
    data = None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        pass
    if json_key:
        v = _dig(data, json_key) if data is not None else None
        return str(v).strip() if v is not None and _SHA_LIKE.match(str(v).strip()) else None
    if isinstance(data, dict):
        for k in DEFAULT_JSON_KEYS:
            v = data.get(k)
            if isinstance(v, str) and _SHA_LIKE.match(v.strip()):
                return v.strip()
    m = _HEX40.search(body)
    return m.group(0) if m else None


def sha_matches(expected: str, found: str) -> bool:
    """Prefix match, case-insensitive, at least 7 hex chars on both sides."""
    e, f = expected.strip().lower(), found.strip().lower()
    if len(e) < 7 or len(f) < 7 or not _SHA_LIKE.match(e) or not _SHA_LIKE.match(f):
        return False
    return e.startswith(f) or f.startswith(e)


def resolve_expected_sha(value: str | None) -> str:
    if value and value != "HEAD":
        if not _SHA_LIKE.match(value.strip()):
            raise ConfigError(f"--expected-sha {value!r} is not a 7-40 char hex SHA (or HEAD)")
        return value.strip()
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f"could not run git to resolve HEAD: {exc}")
    if out.returncode != 0:
        raise ConfigError(f"git rev-parse HEAD failed: {out.stderr.strip()}")
    return out.stdout.strip()


@dataclass
class ShaResult:
    status: str  # "match" | "mismatch" | "unreadable" | "skipped"
    expected: str = ""
    found: str = ""
    detail: str = ""


def fetch_sha(url: str, header: str | None, json_key: str | None, regex: str | None,
              timeout: float = 15.0,
              opener: Callable[..., Any] = urllib.request.urlopen) -> tuple[str | None, str]:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "foundry-qa-done-gate"})
    try:
        with opener(req, timeout=timeout) as resp:
            headers = dict(resp.headers.items())
            body = resp.read(512 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        headers = dict(exc.headers.items()) if exc.headers else {}
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        sha = extract_sha(headers, body, header, json_key, regex)
        return sha, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return None, f"unreachable: {exc}"
    sha = extract_sha(headers, body, header, json_key, regex)
    return sha, "ok" if sha else "no SHA found in response"


def check_sha(expected: str, url: str, header: str | None = None, json_key: str | None = None,
              regex: str | None = None, retries: int = 3, wait_s: float = 10.0,
              fetch: Optional[Callable[..., tuple[str | None, str]]] = None,
              sleep: Callable[[float], None] = time.sleep) -> ShaResult:
    """Retry on mismatch and on unreadable (a deploy may still be rolling out)."""
    fetch = fetch or fetch_sha
    last = ShaResult(status="unreadable", expected=expected)
    for attempt in range(max(1, retries)):
        found, detail = fetch(url, header, json_key, regex)
        if found and sha_matches(expected, found):
            return ShaResult("match", expected, found, f"attempt {attempt + 1}")
        if found:
            last = ShaResult("mismatch", expected, found, f"deployed {found[:12]}, expected {expected[:12]}")
        else:
            last = ShaResult("unreadable", expected, "", detail)
        if attempt + 1 < retries:
            sleep(wait_s)
    return last


# ── results + the exit-code rule (pure, unit-tested) ──────────────────────────

@dataclass
class DeviceResult:
    journey: str
    device: str
    status: str  # "pass" | "fail" | "inconclusive"
    reason: str = ""
    failed_step: Optional[int] = None
    assertions: list[dict] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    blocked_writes: list[dict] = field(default_factory=list)
    screenshot: str = ""
    final_url: str = ""
    duration_s: float = 0.0


def overall_exit(sha: ShaResult | None, results: list[DeviceResult]) -> int:
    """The gate's verdict.

    Order matters: SHA mismatch beats everything (you tested the wrong build);
    an unreadable SHA is inconclusive; then any real failure beats an
    inconclusive sibling, because a failure is evidence and inconclusive is not.
    No results at all is inconclusive, never a pass.
    """
    if sha is not None and sha.status == "mismatch":
        return EXIT_SHA_MISMATCH
    if sha is not None and sha.status == "unreadable":
        return EXIT_INCONCLUSIVE
    if not results:
        return EXIT_INCONCLUSIVE
    if any(r.status == "fail" for r in results):
        return EXIT_JOURNEY_FAIL
    if any(r.status != "pass" for r in results):
        return EXIT_INCONCLUSIVE
    return EXIT_PASS


# ── read-only request guard (pure decide + Playwright handler) ────────────────

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def decide_request(method: str) -> str:
    """'allow' for safe methods, 'block' for anything that can write."""
    return "allow" if (method or "GET").upper() in SAFE_METHODS else "block"


def install_read_only_guard(context: Any, log: list[dict]) -> None:
    """Every non-GET/HEAD/OPTIONS request is recorded and answered locally.

    It never reaches the server, so a click on Save, Pay, Send or Delete cannot
    change real data. The page receives a 200 with {"qaReadOnly": true}; the
    UI may show a success state that did not really happen, so judge that
    state as "UI responded", never as "it saved".
    """
    def handler(route: Any, request: Any) -> None:
        if decide_request(request.method) == "allow":
            route.continue_()
            return
        parts = urlsplit(request.url)
        body = request.post_data_buffer or b""
        log.append({"method": request.method, "path": parts.path, "host": parts.netloc,
                    "body_bytes": len(body)})
        route.fulfill(status=200, content_type="application/json", body='{"qaReadOnly": true}')
    context.route("**/*", handler)


# ── browser execution ─────────────────────────────────────────────────────────

NETWORK_ERROR_MARKERS = ("net::ERR_", "NS_ERROR_", "Could not connect", "Connection refused",
                         "ECONNREFUSED", "ENOTFOUND", "nodename nor servname")


def _is_network_error(message: str) -> bool:
    return any(m in message for m in NETWORK_ERROR_MARKERS)


def _hit_auth_wall(url: str, walls: list[str]) -> str | None:
    for w in walls:
        if w and w in url:
            return w
    return None


class StepFailure(Exception):
    def __init__(self, status: str, message: str, step: int | None = None):
        self.status, self.message, self.step = status, message, step
        super().__init__(message)


def run_steps(page: Any, steps: list[dict], base_url: str, timeout_ms: int,
              auth_wall: list[str], pw_timeout_error: type) -> None:
    """Run journey steps on a page. Raises StepFailure(status, message, step)."""
    for i, step in enumerate(steps):
        (kind, arg), = step.items()
        try:
            if kind == "goto":
                url = resolve_url(arg, base_url)
                try:
                    resp = page.goto(url, wait_until="load", timeout=max(timeout_ms, 15000))
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc).splitlines()[0]
                    if _is_network_error(str(exc)):
                        raise StepFailure("inconclusive", f"target unreachable: {msg}", i)
                    raise
                if resp is not None and resp.status >= 500:
                    raise StepFailure("fail", f"goto {url} returned HTTP {resp.status}", i)
                wall = _hit_auth_wall(page.url, auth_wall)
                if wall:
                    raise StepFailure("inconclusive", f"bounced to a sign-in wall ({wall!r} in {page.url})", i)
            elif kind == "click":
                page.locator(arg).first.click(timeout=timeout_ms)
            elif kind == "fill":
                page.locator(arg["selector"]).first.fill(arg["value"], timeout=timeout_ms)
            elif kind == "wait_for":
                page.locator(arg).first.wait_for(state="visible", timeout=timeout_ms)
            elif kind == "press":
                page.locator(arg["selector"]).first.press(arg["key"], timeout=timeout_ms)
        except StepFailure:
            raise
        except pw_timeout_error as exc:
            raise StepFailure("fail", f"step {i + 1} ({kind}) timed out: {str(exc).splitlines()[0]}", i)
        except ConfigError as exc:
            raise StepFailure("config", str(exc), i)
        except Exception as exc:  # noqa: BLE001
            raise StepFailure("fail", f"step {i + 1} ({kind}) failed: {str(exc).splitlines()[0]}", i)
        if kind != "goto":
            wall = _hit_auth_wall(page.url, auth_wall)
            if wall:
                raise StepFailure("inconclusive", f"bounced to a sign-in wall ({wall!r} in {page.url})", i)


def _poll(fn: Callable[[], bool], timeout_ms: int, interval_s: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        try:
            if fn():
                return True
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)


def filter_console(errors: list[str], ignore: list[str]) -> list[str]:
    pats = [re.compile(p) for p in ignore]
    return [e for e in errors if not any(p.search(e) for p in pats)]


def check_assertions(page: Any, assertions: list[dict], timeout_ms: int,
                     console_errors: list[str], ignore_console: list[str]) -> list[dict]:
    out = []
    for a in assertions:
        (kind, arg), = a.items()
        ok, detail = False, ""
        if kind == "visible":
            ok = _poll(lambda: page.locator(arg).first.is_visible(), timeout_ms)
            detail = f"{arg} visible" if ok else f"{arg} not visible within {timeout_ms} ms"
        elif kind == "text":
            seen = {"text": ""}
            def _has() -> bool:
                seen["text"] = page.locator(arg["selector"]).first.inner_text(timeout=1000)
                return arg["contains"] in seen["text"]
            ok = _poll(_has, timeout_ms)
            detail = (f"{arg['selector']} contains {arg['contains']!r}" if ok else
                      f"{arg['selector']} text {seen['text'][:120]!r} lacks {arg['contains']!r}")
        elif kind == "url_contains":
            ok = _poll(lambda: arg in page.url, timeout_ms)
            detail = f"url {page.url}" + ("" if ok else f" lacks {arg!r}")
        elif kind == "no_console_errors":
            errs = filter_console(console_errors, ignore_console)
            ok = not errs
            detail = "no console errors" if ok else f"{len(errs)} console error(s): {errs[0][:160]}"
        out.append({"assertion": kind, "arg": arg, "passed": ok, "detail": detail})
    return out


def run_on_device(pw: Any, browser_name: str, journey: Journey, device: str, base_url: str,
                  out_dir: Path, read_only: bool, headed: bool) -> DeviceResult:
    from playwright.sync_api import TimeoutError as PWTimeout

    res = DeviceResult(journey=journey.name, device=device, status="inconclusive")
    t0 = time.monotonic()
    try:
        browser = qa_session.launch(pw, browser_name, headless=not headed)
    except qa_session.BrowserMissing:
        raise
    except Exception as exc:  # noqa: BLE001
        res.reason = f"browser could not launch ({browser_name}): {str(exc).splitlines()[0]}"
        return res
    try:
        context = browser.new_context(**context_kwargs(device, browser_name),
                                      **qa_session.context_options(journey.auth))
        page = context.new_page()
        try:
            try:  # sign in first: login_steps run before the read-only guard, so a sign-in POST goes through
                qa_session.apply_auth(context, page, journey.auth, base_url,
                                      lambda pg, st: run_steps(pg, st, base_url, journey.timeout_ms, [], PWTimeout))
            except StepFailure as sf:
                raise StepFailure("inconclusive", f"sign-in (auth.login_steps) failed: {sf.message}") from None
            if read_only:
                install_read_only_guard(context, res.blocked_writes)
            page.on("console", lambda m: res.console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: res.console_errors.append(f"uncaught: {e}"))
            page.on("requestfailed", lambda r: res.failed_requests.append(f"{r.method} {r.url} ({r.failure})"))
            page.on("response", lambda r: res.failed_requests.append(f"HTTP {r.status} {r.request.method} {r.url}")
                    if r.status >= 500 else None)
            run_steps(page, journey.steps, base_url, journey.timeout_ms, journey.auth_wall, PWTimeout)
            res.assertions = check_assertions(page, journey.assertions, journey.timeout_ms,
                                              res.console_errors, journey.ignore_console)
            failed = [a for a in res.assertions if not a["passed"]]
            res.status = "fail" if failed else "pass"
            res.reason = failed[0]["detail"] if failed else "all assertions passed"
        except StepFailure as sf:
            res.status = "fail" if sf.status == "fail" else "inconclusive"
            res.reason, res.failed_step = sf.message, sf.step
        res.final_url = page.url
        shot = out_dir / f"{journey.screenshot}-{device}.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
            res.screenshot = str(shot)
        except Exception as exc:  # noqa: BLE001
            res.screenshot = f"(screenshot failed: {str(exc).splitlines()[0]})"
        context.close()
    except Exception as exc:  # noqa: BLE001  harness trouble is not a product verdict
        res.status = "inconclusive"
        res.reason = f"harness error: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}"
    finally:
        browser.close()
        res.duration_s = round(time.monotonic() - t0, 2)
    return res


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="done_gate.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--journey", action="append", required=True, help="journey file (YAML subset or JSON); repeatable")
    p.add_argument("--base-url", default="", help="base URL for relative goto steps (overrides the journey's base_url)")
    p.add_argument("--devices", default="", help="comma list overriding the journey's devices")
    p.add_argument("--browser", default="chromium", choices=["chromium", "webkit", "firefox"])
    p.add_argument("--out", default=".qa/done-gate", help="output root (default .qa/done-gate)")
    p.add_argument("--read-only", action="store_true", help="block every non-GET/HEAD/OPTIONS request (use on production)")
    p.add_argument("--headed", action="store_true", help="show the browser")
    p.add_argument("--expected-sha", default=None, help="commit the deploy must serve; HEAD (default) = git rev-parse HEAD")
    p.add_argument("--sha-url", default=None, help="URL whose response carries the deployed SHA")
    p.add_argument("--sha-header", default=None, help="response header holding the SHA")
    p.add_argument("--sha-json-key", default=None, help="dotted JSON key holding the SHA, e.g. build.commit")
    p.add_argument("--sha-regex", default=None, help="regex on the body; group 1 is the SHA")
    p.add_argument("--sha-retries", type=int, default=3)
    p.add_argument("--sha-wait", type=float, default=10.0, help="seconds between SHA retries")
    p.add_argument("--validate", action="store_true", help="parse and validate only; no network, no browser")
    p.add_argument("--port", default=None, help="fills PORT in base_url, for example --port 5173")
    qa_session.add_auth_args(p)
    return p


def git_head() -> Optional[str]:
    """The commit under test when run from a git checkout, else None. Never raises."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and _SHA_LIKE.match(sha) else None


def last_record(code: int, journeys: list[Journey], sha: Optional[str], failures: list[dict],
                when: Optional[datetime] = None, sha_result: Optional[ShaResult] = None) -> dict:
    """The small, stable summary other tools read (.qa/done-gate/last.json). Pure."""
    sources = [j.source for j in journeys]
    devices = list(dict.fromkeys(d for j in journeys for d in j.devices))
    stories = list(dict.fromkeys(s for j in journeys for s in j.stories))
    return {
        "sha": sha,
        "exit": code,
        "verdict": EXIT_LABELS[code],
        "journey": ", ".join(sources),
        "journeys": sources,
        "devices": devices,
        "stories": stories,
        "time": (when or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "deployed_sha": (sha_result.found or None) if sha_result else None,
        "failures": failures,
    }


def failures_from(results: list[DeviceResult], sha_result: Optional[ShaResult]) -> list[dict]:
    out = []
    if sha_result is not None and sha_result.status in ("mismatch", "unreadable"):
        out.append({"journey": "", "device": "", "status": f"sha-{sha_result.status}", "reason": sha_result.detail})
    out += [{"journey": r.journey, "device": r.device, "status": r.status, "reason": r.reason}
            for r in results if r.status != "pass"]
    return out


def write_last(out_root: str, record: dict) -> None:
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "last.json").write_text(json.dumps(record, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    journeys: list[Journey] = []

    def config_error(msg: str) -> int:
        print(f"DONE-GATE: CONFIG ERROR: {msg}", file=sys.stderr)
        if not args.validate:
            write_last(args.out, last_record(EXIT_CONFIG, journeys, git_head(),
                                             [{"journey": "", "device": "", "status": "config", "reason": msg}]))
        return EXIT_CONFIG

    try:
        journeys = [load_journey(j) for j in args.journey]
        if args.devices:
            devs = [d.strip() for d in args.devices.split(",") if d.strip()]
            bad = [d for d in devs if d not in DEVICE_PROFILES]
            if bad:
                raise ConfigError(f"unknown device(s) {bad}; known: {sorted(DEVICE_PROFILES)}")
            for j in journeys:
                j.devices = devs
        cli_auth = qa_session.auth_from_args(args, validate_step)
        for j in journeys:
            j.auth = qa_session.merge_auth(j.auth, cli_auth)
            base = args.base_url or j.base_url
            for s in j.steps:
                if "goto" in s:
                    resolve_url(s["goto"], base)
        if not args.validate:
            for j in journeys:
                base = resolve_base(args.base_url or j.base_url, args.port)
                if "TODO" in base or "<your-app>" in base:
                    raise ConfigError(f"{j.source}: base_url {base!r} is still the template placeholder; "
                                      "set it, or pass --base-url")
                qa_session.check_ready(j.auth)
    except (ConfigError, qa_session.SessionError) as exc:
        return config_error(str(exc))

    if args.validate:
        for j in journeys:
            extra = f", stories {j.stories}" if j.stories else ""
            extra += f", auth {sorted(j.auth)}" if j.auth else ""
            print(f"ok  {j.source}: '{j.name}' {len(j.steps)} steps, {len(j.assertions)} assertions, "
                  f"devices {j.devices}{extra}")
        return EXIT_PASS

    # SHA config: CLI wins, else the first journey that declares sha_check.
    sha_cfg = None
    if args.sha_url:
        sha_cfg = {"url": args.sha_url, "header": args.sha_header, "json_key": args.sha_json_key,
                   "regex": args.sha_regex}
    else:
        for j in journeys:
            if j.sha_check:
                sha_cfg = {"url": j.sha_check["url"], "header": j.sha_check.get("header"),
                           "json_key": j.sha_check.get("json_key"), "regex": j.sha_check.get("regex")}
                break

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (Path(args.out) / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sha_result: ShaResult | None = None
    if sha_cfg:
        try:
            expected = resolve_expected_sha(args.expected_sha)
        except ConfigError as exc:
            return config_error(str(exc))
        sha_result = check_sha(expected, sha_cfg["url"], sha_cfg["header"], sha_cfg["json_key"],
                               sha_cfg["regex"], retries=args.sha_retries, wait_s=args.sha_wait)
        print(f"sha: {sha_result.status} ({sha_result.detail})")

    results: list[DeviceResult] = []
    if sha_result is None or sha_result.status == "match":
        try:
            sync_playwright = qa_session.import_sync_playwright(args.browser)
            with sync_playwright() as pw:
                for j in journeys:
                    base = resolve_base(args.base_url or j.base_url, args.port)
                    for device in j.devices:
                        r = run_on_device(pw, args.browser, j, device, base, out_dir,
                                          read_only=args.read_only or j.read_only, headed=args.headed)
                        results.append(r)
                        print(f"{r.status.upper():13} {j.name} @ {device}: {r.reason}"
                              + (f"  [{len(r.blocked_writes)} write(s) blocked]" if r.blocked_writes else ""))
        except qa_session.BrowserMissing as exc:
            return config_error(str(exc))

    code = overall_exit(sha_result, results)
    head = git_head()
    summary = {
        "exit_code": code,
        "verdict": EXIT_LABELS[code],
        "run_id": run_id,
        "browser": args.browser,
        "git_head": head,
        "stories": list(dict.fromkeys(s for j in journeys for s in j.stories)),
        "sha": asdict(sha_result) if sha_result else None,
        "results": [asdict(r) for r in results],
    }
    (out_dir / "result.json").write_text(json.dumps(summary, indent=2))
    (Path(args.out) / "latest.json").write_text(json.dumps(summary, indent=2))
    write_last(args.out, last_record(code, journeys, head, failures_from(results, sha_result), sha_result=sha_result))
    print(f"DONE-GATE: {EXIT_LABELS[code]} (exit {code})  evidence: {out_dir}")
    if code == EXIT_INCONCLUSIVE:
        print("Nothing was proven. Do not report done. Fix the reason above and re-run.")
    return code


if __name__ == "__main__":
    sys.exit(main())
