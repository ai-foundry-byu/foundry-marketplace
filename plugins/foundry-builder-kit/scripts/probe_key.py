#!/usr/bin/env python3
"""probe_key.py: ask a provider whether a credential still authenticates.

Probe BEFORE you rotate or panic, and probe AFTER you revoke. A leaked string that
no longer authenticates is a cleanup task; one that still authenticates is an incident.

The key is read from an environment variable, never from argv (argv shows up in
`ps` and in shell history). Nothing is printed except the provider, the variable
name, a 6-character prefix, and the verdict.

Usage:
  OPENAI_API_KEY=... probe_key.py openai:OPENAI_API_KEY
  probe_key.py anthropic:OLD_ANTHROPIC_KEY github:LEAKED_GH_TOKEN
  probe_key.py --list

Verdicts:
  LIVE  the provider accepted the key (HTTP 2xx)
  DEAD  the provider rejected the key as invalid (HTTP 401)
  ERR   anything else: network error, 403, 429, 5xx, unset variable.
        ERR is never an all-clear. Re-run until every key is LIVE or DEAD.

Exit codes: 0 every probed key is DEAD (all clear), 1 at least one LIVE,
            2 no LIVE but at least one ERR, 3 usage error.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from typing import Callable

# provider -> (url, header builder). Every probe is a cheap, read-only GET.
PROVIDERS: dict[str, tuple[str, Callable[[str], dict[str, str]]]] = {
    "openai": ("https://api.openai.com/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "anthropic": (
        "https://api.anthropic.com/v1/models",
        lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"},
    ),
    "groq": ("https://api.groq.com/openai/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "openrouter": ("https://openrouter.ai/api/v1/key", lambda k: {"Authorization": f"Bearer {k}"}),
    "github": (
        "https://api.github.com/user",
        lambda k: {"Authorization": f"Bearer {k}", "Accept": "application/vnd.github+json"},
    ),
    "stripe": ("https://api.stripe.com/v1/balance", lambda k: {"Authorization": f"Bearer {k}"}),
    "resend": ("https://api.resend.com/domains", lambda k: {"Authorization": f"Bearer {k}"}),
    "vercel": ("https://api.vercel.com/v2/user", lambda k: {"Authorization": f"Bearer {k}"}),
}

LIVE, DEAD, ERR = "LIVE", "DEAD", "ERR"


def classify(status: int | None) -> str:
    if status is None:
        return ERR
    if 200 <= status < 300:
        return LIVE
    if status == 401:
        return DEAD
    return ERR


def http_status(url: str, headers: dict[str, str], timeout: float = 15.0) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "probe-key/0.1", **headers}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, type(exc).__name__


def probe(provider: str, env_name: str, fetch=http_status, environ=os.environ) -> tuple[str, str]:
    """Return (verdict, detail)."""
    if provider not in PROVIDERS:
        return ERR, f"unknown provider {provider!r}"
    key = environ.get(env_name, "").strip()
    if not key:
        return ERR, f"${env_name} is unset or empty"
    url, build = PROVIDERS[provider]
    status, err = fetch(url, build(key))
    verdict = classify(status)
    detail = f"HTTP {status}" if status is not None else f"network error ({err})"
    if status == 403:
        detail += " (forbidden: the key may be valid but lack scope; treat as not cleared)"
    if status == 429:
        detail += " (rate limited: retry later)"
    return verdict, f"{key[:6]}*** {detail}"


def main(argv: list[str] | None = None, fetch=http_status, environ=os.environ) -> int:
    ap = argparse.ArgumentParser(description="Probe whether credentials still authenticate.")
    ap.add_argument("checks", nargs="*", help="provider:ENV_VAR pairs")
    ap.add_argument("--list", action="store_true", help="list supported providers")
    a = ap.parse_args(argv)
    if a.list:
        for name, (url, _) in sorted(PROVIDERS.items()):
            print(f"{name:12s} GET {url}")
        return 0
    if not a.checks:
        ap.print_usage(sys.stderr)
        return 3
    verdicts = []
    for check in a.checks:
        if ":" not in check:
            print(f"bad check {check!r}: expected provider:ENV_VAR", file=sys.stderr)
            return 3
        provider, env_name = check.split(":", 1)
        verdict, detail = probe(provider.strip().lower(), env_name.strip(), fetch=fetch, environ=environ)
        verdicts.append(verdict)
        print(f"{verdict:4s}  {provider}:{env_name}  {detail}")
    if LIVE in verdicts:
        return 1
    if ERR in verdicts:
        return 2
    print("ALL CLEAR: every probed key is rejected by its provider.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
