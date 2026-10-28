#!/usr/bin/env python3
"""structured_router.py: route a narrow, schema-pinned LLM task to the cheapest
provider that is allowed to see the data, with a guaranteed fallback.

The task shape: one forced tool call against a small JSON Schema (fixed enums,
bounded arrays). Extraction, classification, scoring, short structured grading.
Not long-form writing and not hard reasoning.

Rules this code enforces:
  1. Privacy bar first. A request marked data_class="private" (anything a real
     person typed: resumes, tickets, messages) never goes to a provider whose
     `private_ok` is False, however generous its free tier is.
  2. Forced tool call, never "please reply in JSON". The model cannot answer in prose.
  3. Validate the result against the schema. A 200 with off-schema content is a failure.
  4. Never the only path. Each provider's failure falls through to the next; the
     last provider should be a paid one you trust, so an outage costs cents, not a feature.
  5. "Configured" means the key has the right prefix, not just that the variable is set.

Library use:
  from structured_router import call_structured
  data, provider = call_structured(system=..., user=..., tool_name="emit_label",
                                   schema={...}, data_class="private")

CLI:
  structured_router.py --schema schema.json --system "Classify the ticket." \
      --input ticket.txt --data-class private
  structured_router.py --schema schema.json --data-class private --plan   # show the route, call nothing
  structured_router.py --schema schema.json --input ticket.txt --mock-response mock.json
      # the full call path with no keys and no network: every eligible provider "answers" with
      # the object in mock.json (or {"per_provider": {"groq": {...}, ...}}; a provider missing
      # there fails as a simulated outage), so you can watch validation and fall-through work.

Providers come from DEFAULT_PROVIDERS, or a JSON file given with --providers or
the env var STRUCTURED_ROUTER_PROVIDERS. Check every provider's data policy and model
names yourself before relying on them; both change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

# private_ok: may this provider see real user data? Set from the provider's data
# processing terms for the tier you are on, checked by you, with a date.
DEFAULT_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "ollama-local",
        "style": "openai",
        "base_url": "http://localhost:11434/v1",
        "model": os.environ.get("ROUTER_OLLAMA_MODEL", "qwen2.5:7b-instruct"),
        "key_env": None,
        "key_prefix": None,
        "private_ok": True,  # runs on your machine
        "enabled_env": "ROUTER_USE_OLLAMA",  # opt in: only tried when this env var is "1"
    },
    {
        "name": "groq",
        "style": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "model": os.environ.get("ROUTER_GROQ_MODEL", "llama-3.3-70b-versatile"),
        "key_env": "GROQ_API_KEY",
        "key_prefix": "gsk_",
        "private_ok": True,  # DPA read 2026-08: no training on customer data, same terms on free tier. Re-check.
    },
    {
        "name": "gemini-free",
        "style": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": os.environ.get("ROUTER_GEMINI_MODEL", "gemini-2.5-flash"),
        "key_env": "GEMINI_API_KEY",
        "key_prefix": "AIza",
        "private_ok": False,  # free tier terms allow use of inputs to improve products
    },
    {
        "name": "openrouter-free",
        "style": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "model": os.environ.get("ROUTER_OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        "key_env": "OPENROUTER_API_KEY",
        "key_prefix": "sk-or-",
        "private_ok": False,  # depends on the downstream provider; free routes may log or train
    },
    {
        "name": "anthropic",
        "style": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": os.environ.get("ROUTER_ANTHROPIC_MODEL", "claude-haiku-4-5"),
        "key_env": "ANTHROPIC_API_KEY",
        "key_prefix": "sk-ant-api",
        "private_ok": True,  # paid API; commercial terms do not train on inputs by default
    },
]


class RouterError(Exception):
    """Raised when every eligible provider failed. `attempts` lists why."""

    def __init__(self, msg: str, attempts: list[tuple[str, str]]):
        super().__init__(msg)
        self.attempts = attempts


# ---------------------------------------------------------------- schema check

def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """A small JSON Schema subset validator. Returns a list of error strings."""
    errs: list[str] = []
    t = schema.get("type")
    type_ok = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(type_ok.get(x, lambda v: True)(value) for x in types):
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in enum {schema['enum']}")
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errs.extend(validate(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing required {req!r}")
        for k, v in value.items():
            if k in props:
                errs.extend(validate(v, props[k], f"{path}.{k}"))
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property {k!r}")
    return errs


# ---------------------------------------------------------------- transport

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def http_post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"network: {type(exc).__name__}") from None


# ---------------------------------------------------------------- providers

def is_configured(p: dict[str, Any], environ=os.environ) -> tuple[bool, str]:
    if p.get("enabled_env") and environ.get(p["enabled_env"]) != "1":
        return False, f"opt-in env {p['enabled_env']}=1 not set"
    if not p.get("key_env"):
        return True, "no key needed"
    key = environ.get(p["key_env"], "").strip()
    if not key:
        return False, f"${p['key_env']} unset"
    prefix = p.get("key_prefix")
    if prefix and not key.startswith(prefix):
        return False, f"${p['key_env']} does not start with {prefix!r} (placeholder?)"
    return True, "key ok"


def plan_route(providers: list[dict[str, Any]], data_class: str, environ=os.environ) -> list[tuple[dict, bool, str]]:
    out = []
    for p in providers:
        if data_class == "private" and not p.get("private_ok"):
            out.append((p, False, "fails privacy bar for private data"))
            continue
        ok, why = is_configured(p, environ)
        out.append((p, ok, why))
    return out


def _call_openai_style(p, key, system, user, tool_name, tool_desc, schema, max_tokens, transport, timeout):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    body = {
        "model": p["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "tools": [{"type": "function", "function": {
            "name": tool_name, "description": tool_desc, "parameters": schema}}],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    resp = transport(p["base_url"].rstrip("/") + "/chat/completions", headers, body, timeout)
    try:
        calls = resp["choices"][0]["message"]["tool_calls"]
        args = calls[0]["function"]["arguments"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("no tool call in response") from None
    # OpenAI-style APIs return arguments as a JSON STRING; parse it defensively.
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            raise RuntimeError("tool arguments were not valid JSON") from None
    return args


def _call_anthropic_style(p, key, system, user, tool_name, tool_desc, schema, max_tokens, transport, timeout):
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    body = {
        "model": p["model"],
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "tools": [{"name": tool_name, "description": tool_desc, "input_schema": schema}],
        "tool_choice": {"type": "tool", "name": tool_name},
        "max_tokens": max_tokens,
    }
    resp = transport(p["base_url"].rstrip("/") + "/messages", headers, body, timeout)
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == tool_name:
            return block.get("input")  # already an object, unlike OpenAI-style arguments
    raise RuntimeError("no tool_use block in response")


STYLES = {"openai": _call_openai_style, "anthropic": _call_anthropic_style}


def call_structured(*, system: str, user: str, tool_name: str, schema: dict[str, Any],
                    data_class: str = "private", tool_description: str = "Return the structured result.",
                    providers: list[dict[str, Any]] | None = None, max_tokens: int = 800,
                    timeout: float = 30.0, transport: Transport = http_post_json,
                    environ=os.environ, log: Callable[[str], None] | None = None) -> tuple[Any, str]:
    """Return (validated_data, provider_name). Raises RouterError if all fail."""
    if data_class not in ("private", "public"):
        raise ValueError("data_class must be 'private' or 'public'")
    providers = providers if providers is not None else DEFAULT_PROVIDERS
    attempts: list[tuple[str, str]] = []
    for p, eligible, why in plan_route(providers, data_class, environ):
        if not eligible:
            attempts.append((p["name"], f"skipped: {why}"))
            continue
        key = environ.get(p["key_env"], "").strip() if p.get("key_env") else ""
        try:
            data = STYLES[p.get("style", "openai")](p, key, system, user, tool_name, tool_description,
                                                    schema, max_tokens, transport, timeout)
        except RuntimeError as exc:
            attempts.append((p["name"], f"failed: {exc}"))
            if log:
                log(f"{p['name']} failed: {exc}; falling through")
            continue
        errors = validate(data, schema)
        if errors:
            attempts.append((p["name"], f"off-schema: {errors[:3]}"))
            if log:
                log(f"{p['name']} returned off-schema output; falling through")
            continue
        return data, p["name"]
    raise RouterError("every eligible provider failed or was skipped", attempts)


def mock_environ(providers: list[dict[str, Any]], environ=os.environ) -> dict[str, str]:
    """A copy of environ where every unset provider key holds a fake key with the right prefix."""
    env = dict(environ)
    for p in providers:
        if p.get("key_env") and not env.get(p["key_env"], "").strip():
            env[p["key_env"]] = (p.get("key_prefix") or "") + "mock"
    return env


def mock_transport(spec: Any, providers: list[dict[str, Any]]) -> Transport:
    """A transport that never opens a socket and answers like the provider's real API would."""
    per = spec.get("per_provider") if isinstance(spec, dict) and "per_provider" in spec else None

    def transport(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
        p = next((p for p in providers if url.startswith(p["base_url"].rstrip("/"))), None)
        name = p["name"] if p else url
        args = spec if per is None else per.get(name)
        if args is None:
            raise RuntimeError(f"mock: no response for {name} (simulated outage)")
        if url.endswith("/messages"):
            tool = body["tools"][0]["name"]
            return {"content": [{"type": "tool_use", "name": tool, "input": args}]}
        tool = body["tools"][0]["function"]["name"]
        return {"choices": [{"message": {"tool_calls": [
            {"function": {"name": tool, "arguments": json.dumps(args)}}]}}]}

    return transport


def load_providers(path: str | None) -> list[dict[str, Any]]:
    path = path or os.environ.get("STRUCTURED_ROUTER_PROVIDERS")
    if not path:
        return DEFAULT_PROVIDERS
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Forced-tool-call structured extraction with a privacy-aware fallback chain.")
    ap.add_argument("--schema", required=True, help="JSON Schema file for the tool parameters")
    ap.add_argument("--tool-name", default="emit_result")
    ap.add_argument("--system", default="Extract the requested fields. Use only information in the input.")
    ap.add_argument("--input", help="file with the user content (default: stdin)")
    ap.add_argument("--data-class", choices=["private", "public"], default="private",
                    help="private = real user data (default, the safe choice)")
    ap.add_argument("--providers", help="JSON file with a provider list (overrides defaults)")
    ap.add_argument("--plan", action="store_true", help="print the route and exit without calling anything")
    ap.add_argument("--mock-response", metavar="FILE",
                    help="offline demo: no keys, no network; every eligible provider returns the JSON in FILE")
    a = ap.parse_args(argv)

    with open(a.schema, encoding="utf-8") as fh:
        schema = json.load(fh)
    providers = load_providers(a.providers)
    environ: Any = os.environ
    transport: Transport = http_post_json
    if a.mock_response:
        with open(a.mock_response, encoding="utf-8") as fh:
            spec = json.load(fh)
        real = dict(os.environ)
        environ = mock_environ(providers, real)
        transport = mock_transport(spec, providers)
        print("structured_router: MOCK mode (no network, fake keys for unset variables)", file=sys.stderr)

    if a.plan:
        for p, ok, why in plan_route(providers, a.data_class, environ):
            if ok and a.mock_response and p.get("key_env") and not os.environ.get(p["key_env"], "").strip():
                why = "mock key"
            print(f"{'TRY ' if ok else 'SKIP'} {p['name']:16s} {p.get('model', '')}  ({why})")
        return 0

    user = open(a.input, encoding="utf-8").read() if a.input else sys.stdin.read()
    try:
        data, name = call_structured(system=a.system, user=user, tool_name=a.tool_name, schema=schema,
                                     data_class=a.data_class, providers=providers,
                                     transport=transport, environ=environ,
                                     log=lambda m: print(m, file=sys.stderr))
    except RouterError as exc:
        print(f"structured_router: {exc}", file=sys.stderr)
        for name, why in exc.attempts:
            print(f"  {name}: {why}", file=sys.stderr)
        return 1
    print(f"provider: {name}{' (mock)' if a.mock_response else ''}", file=sys.stderr)
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
