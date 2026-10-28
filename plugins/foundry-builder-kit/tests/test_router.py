"""Tests for structured_router.py (no network: the transport is faked)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "cheap-llm-routing", "scripts"))

import structured_router as sr  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["billing", "bug", "other"]},
        "urgency": {"type": "integer", "minimum": 1, "maximum": 5},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
    },
    "required": ["category", "urgency"],
    "additionalProperties": False,
}

CHEAP_PUBLIC_ONLY = {"name": "cheap", "style": "openai", "base_url": "https://cheap.test/v1", "model": "m",
                     "key_env": "CHEAP_KEY", "key_prefix": "ck_", "private_ok": False}
CHEAP_PRIVATE_OK = {**CHEAP_PUBLIC_ONLY, "name": "safe-cheap", "base_url": "https://safe.test/v1",
                    "key_env": "SAFE_KEY", "private_ok": True}
PAID = {"name": "paid", "style": "anthropic", "base_url": "https://paid.test/v1", "model": "p",
        "key_env": "PAID_KEY", "key_prefix": "sk-ant-api", "private_ok": True}
ENV = {"CHEAP_KEY": "ck_123", "SAFE_KEY": "ck_456", "PAID_KEY": "sk-ant-api03-xyz"}


def openai_reply(args):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": "emit", "arguments": args}}]}}]}


def anthropic_reply(obj):
    return {"content": [{"type": "tool_use", "name": "emit", "input": obj}]}


class FakeTransport:
    def __init__(self, replies):
        self.replies = replies  # host -> reply dict or Exception
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        host = url.split("/")[2]
        self.calls.append((host, headers, body))
        r = self.replies[host]
        if isinstance(r, Exception):
            raise r
        return r


def call(providers, transport, data_class="private", env=ENV):
    return sr.call_structured(system="s", user="u", tool_name="emit", schema=SCHEMA, data_class=data_class,
                              providers=providers, transport=transport, environ=env)


class ValidateTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sr.validate({"category": "bug", "urgency": 3}, SCHEMA), [])

    def test_errors(self):
        errs = sr.validate({"category": "nope", "urgency": 9, "extra": 1, "tags": ["a", "b", "c"]}, SCHEMA)
        joined = " ".join(errs)
        for needle in ("enum", "maximum", "unexpected", "more than 2"):
            self.assertIn(needle, joined)
        self.assertTrue(any("missing required 'urgency'" in e for e in sr.validate({"category": "bug"}, SCHEMA)))

    def test_bool_is_not_integer(self):
        self.assertTrue(sr.validate({"category": "bug", "urgency": True}, SCHEMA))


class RoutingTests(unittest.TestCase):
    def test_private_data_skips_provider_that_fails_privacy_bar(self):
        t = FakeTransport({"paid.test": anthropic_reply({"category": "bug", "urgency": 2})})
        data, name = call([CHEAP_PUBLIC_ONLY, PAID], t, data_class="private")
        self.assertEqual(name, "paid")
        self.assertEqual([c[0] for c in t.calls], ["paid.test"])  # cheap was never contacted

    def test_public_data_uses_cheap_first_and_parses_string_arguments(self):
        t = FakeTransport({"cheap.test": openai_reply(json.dumps({"category": "billing", "urgency": 1}))})
        data, name = call([CHEAP_PUBLIC_ONLY, PAID], t, data_class="public")
        self.assertEqual((name, data["category"]), ("cheap", "billing"))
        body = t.calls[0][2]
        self.assertEqual(body["tool_choice"]["function"]["name"], "emit")  # forced tool call
        self.assertEqual(t.calls[0][1]["Authorization"], "Bearer ck_123")

    def test_falls_through_on_error_malformed_json_and_off_schema(self):
        for bad in (RuntimeError("HTTP 503"), openai_reply("{not json"), openai_reply('{"category": "zzz", "urgency": 1}')):
            t = FakeTransport({"safe.test": bad, "paid.test": anthropic_reply({"category": "other", "urgency": 5})})
            _, name = call([CHEAP_PRIVATE_OK, PAID], t)
            self.assertEqual(name, "paid", bad)

    def test_placeholder_key_skips_without_a_request(self):
        env = {**ENV, "SAFE_KEY": "YOUR_KEY_HERE"}
        t = FakeTransport({"paid.test": anthropic_reply({"category": "bug", "urgency": 2})})
        _, name = call([CHEAP_PRIVATE_OK, PAID], t, env=env)
        self.assertEqual(name, "paid")
        self.assertEqual(len(t.calls), 1)

    def test_all_fail_raises_with_reasons(self):
        t = FakeTransport({"paid.test": RuntimeError("HTTP 500")})
        with self.assertRaises(sr.RouterError) as ctx:
            call([CHEAP_PUBLIC_ONLY, PAID], t)
        reasons = dict(ctx.exception.attempts)
        self.assertIn("privacy", reasons["cheap"])
        self.assertIn("HTTP 500", reasons["paid"])

    def test_opt_in_local_provider(self):
        local = {"name": "local", "style": "openai", "base_url": "http://localhost:11434/v1", "model": "q",
                 "key_env": None, "private_ok": True, "enabled_env": "USE_LOCAL"}
        plan = sr.plan_route([local], "private", environ={})
        self.assertFalse(plan[0][1])
        t = FakeTransport({"localhost:11434": openai_reply('{"category": "bug", "urgency": 4}')})
        _, name = call([local], t, env={"USE_LOCAL": "1"})
        self.assertEqual(name, "local")
        self.assertNotIn("Authorization", t.calls[0][1])

    def test_bad_data_class(self):
        with self.assertRaises(ValueError):
            call([PAID], FakeTransport({}), data_class="secret")

    def test_default_providers_never_send_private_data_to_non_private_providers(self):
        env = {"GEMINI_API_KEY": "AIza" + "x" * 35, "OPENROUTER_API_KEY": "sk-or-v1-abc"}
        for p, ok, why in sr.plan_route(sr.DEFAULT_PROVIDERS, "private", environ=env):
            if not p["private_ok"]:
                self.assertFalse(ok, p["name"])


if __name__ == "__main__":
    unittest.main()
