"""Protocol tests for mcp/server.py against a fake CLI (no phone, no helper app)."""
import base64
import json
import os
import subprocess
import sys
import unittest

from _support import Sandbox, read, write_exe, SERVER

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.argv_log = os.path.join(self.sb.dir, "argv.log")
        png = os.path.join(self.sb.dir, "one.png")
        with open(png, "wb") as f:
            f.write(PNG_1PX)
        self.fake_cli = write_exe(os.path.join(self.sb.dir, "fake-cli"), f"""#!/bin/bash
printf '%s\\n' "$*" >> "{self.argv_log}"
case "$1" in
  shot) cp "{png}" "$2"; echo "$2 1x1px window 1x1pt" ;;
  fail) echo "boom" >&2; exit 3 ;;
  tap)  [ "$2" = 999 ] && {{ echo "ERROR: outside" ; exit 1; }}; echo "tapped $2 $3" ;;
  *) echo "ok $*" ;;
esac
""")
        env = dict(self.sb.env)
        env["IPHONE_MIRROR_CLI"] = self.fake_cli
        self.proc = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, env=env)
        self.next_id = 0

    def tearDown(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.sb.close()

    def rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        resp = json.loads(self.proc.stdout.readline())
        self.assertEqual(resp["id"], self.next_id)
        return resp

    def call(self, name, args=None):
        return self.rpc("tools/call", {"name": name, "arguments": args or {}})["result"]

    def argv(self):
        return read(self.argv_log).split("\n")[:-1] if os.path.exists(self.argv_log) else []

    def test_initialize_and_notification(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "t", "version": "0"}})["result"]
        self.assertEqual(r["protocolVersion"], "2025-03-26")
        self.assertIn("tools", r["capabilities"])
        self.assertEqual(r["serverInfo"]["name"], "iphone")
        self.assertIsNone(self.rpc("notifications/initialized", notify=True))
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_tools_list(self):
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(set(tools), {"iphone_doctor", "iphone_open", "iphone_info", "iphone_screenshot",
                                      "iphone_tap", "iphone_swipe", "iphone_type", "iphone_key",
                                      "iphone_home", "iphone_tapxy"})
        self.assertEqual(tools["iphone_tap"]["inputSchema"]["required"], ["px", "py"])
        self.assertEqual(tools["iphone_type"]["inputSchema"]["properties"]["text"]["type"], "string")

    def test_descriptions_carry_the_safety_rules(self):
        # L8-D2 + L2-D2: the model reaches these tools without the skill, so the
        # descriptions themselves must carry the grant count and the go-ahead rule.
        tools = {t["name"]: t["description"] for t in self.rpc("tools/list")["result"]["tools"]}
        doc = tools["iphone_doctor"]
        for word in ("Accessibility", "Screen Recording", "Automation", "three"):
            self.assertIn(word, doc)
        self.assertNotIn("both", doc)
        for name in ("iphone_open", "iphone_tap", "iphone_swipe", "iphone_type", "iphone_key",
                     "iphone_home", "iphone_tapxy", "iphone_screenshot"):
            self.assertIn("iphone_doctor", tools[name], name)
            self.assertIn("go-ahead", tools[name], name)

    def test_tap_passes_integer_args(self):
        r = self.call("iphone_tap", {"px": 10, "py": 20})
        self.assertFalse(r["isError"])
        self.assertEqual(r["content"][0]["text"], "tapped 10 20")
        self.assertEqual(self.argv(), ["tap 10 20"])

    def test_tool_error_sets_is_error(self):
        r = self.call("iphone_tap", {"px": 999, "py": 1})
        self.assertTrue(r["isError"])
        self.assertIn("[rc=1]", r["content"][0]["text"])

    def test_invalid_arguments_never_reach_cli(self):
        for args in ({"px": "10", "py": 1}, {"px": 1.5, "py": 1}, {"px": True, "py": 1}, {"px": 1}):
            r = self.call("iphone_tap", args)
            self.assertTrue(r["isError"], args)
            self.assertIn("invalid arguments", r["content"][0]["text"])
        r = self.call("iphone_type", {"text": ""})
        self.assertTrue(r["isError"])
        self.assertEqual(self.argv(), [])

    def test_type_text_with_spaces_is_one_arg(self):
        self.call("iphone_type", {"text": "hello world; rm -rf x"})
        self.assertEqual(self.argv(), ["type hello world; rm -rf x"])

    def test_swipe(self):
        self.call("iphone_swipe", {"px1": 1, "py1": 2, "px2": 3, "py2": 4})
        self.assertEqual(self.argv(), ["swipe 1 2 3 4"])

    def test_screenshot_returns_inline_png(self):
        r = self.call("iphone_screenshot")
        self.assertFalse(r["isError"], r)
        kinds = [c["type"] for c in r["content"]]
        self.assertEqual(kinds, ["text", "image"])
        img = r["content"][1]
        self.assertEqual(img["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(img["data"]), PNG_1PX)
        # L8-D3: outside the in-process test worker the state dir is always the default.
        default = os.path.join(self.sb.dir, "Library", "Caches", "foundry-iphone-mirror")
        self.assertTrue(self.argv()[0].startswith("shot " + default), self.argv())

    def test_unknown_tool_and_method(self):
        r = self.rpc("tools/call", {"name": "iphone_selfdestruct", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)
        r = self.rpc("resources/list")
        self.assertEqual(r["error"]["code"], -32601)

    def test_parse_error(self):
        self.proc.stdin.write("{not json\n")
        self.proc.stdin.flush()
        resp = json.loads(self.proc.stdout.readline())
        self.assertEqual(resp["error"]["code"], -32700)


class MissingCliTest(unittest.TestCase):
    def test_missing_cli_is_a_tool_error(self):
        sys.path.insert(0, os.path.dirname(SERVER))
        import importlib
        os.environ["IPHONE_MIRROR_CLI"] = "/nonexistent/iphone-mirror"
        try:
            import server
            importlib.reload(server)
            r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "iphone_home", "arguments": {}}})
            self.assertTrue(r["result"]["isError"])
            self.assertIn("not found", r["result"]["content"][0]["text"])
        finally:
            del os.environ["IPHONE_MIRROR_CLI"]
            sys.path.remove(os.path.dirname(SERVER))


if __name__ == "__main__":
    unittest.main()
