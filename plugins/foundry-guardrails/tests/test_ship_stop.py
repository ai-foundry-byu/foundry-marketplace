import os
import unittest

from helpers import HookCase

import ship_stop as ss

S = "ship_stop.py"

PLAN = """# Workplan

- [x] M1 Scaffold the repo
- [ ] M2 Export endpoint returns CSV
  - acceptance: GET /export?fmt=csv returns 200 with a header row
  - acceptance: pytest tests/test_export.py passes
- [!] M3 Payment webhook (blocked: needs a sandbox key from a human)
- [ ] M4.1 Docs page
"""


class Parse(unittest.TestCase):
    def test_parse(self):
        items = ss.parse_workplan(PLAN)
        self.assertEqual([i["id"] for i in items], ["M1", "M2", "M3", "M4.1"])
        self.assertEqual([i["state"] for i in items], ["done", "open", "blocked", "open"])
        self.assertEqual(len(items[1]["details"]), 2)
        self.assertEqual(ss.pick(items, "")["id"], "M2")
        self.assertEqual(ss.pick(items, "M4.1")["id"], "M4.1")
        self.assertIsNone(ss.pick(items, "M9"))

    def test_garbage(self):
        self.assertEqual(ss.parse_workplan("no checkboxes here\n- [ ] not a milestone"), [])


class Hook(HookCase):
    def setUp(self):
        super().setUp()
        self.plan = os.path.join(self.tmp, "WORKPLAN.md")
        with open(self.plan, "w") as fh:
            fh.write(PLAN)
        self.env["FOUNDRY_SHIP_WORKPLAN"] = self.plan

    def stop(self, **kw):
        return self.run_hook(S, HookCase.stop(cwd=self.tmp, **kw))

    def assertBlocked(self, result, contains=""):
        code, out, _ = result
        self.assertEqual(code, 0)
        self.assertEqual(out["decision"], "block")
        if contains:
            self.assertIn(contains, out["reason"])

    def test_unarmed_is_noop(self):
        self.env.pop("FOUNDRY_SHIP_WORKPLAN")
        self.assertAllowed(self.stop())

    def test_blocks_on_named_open_milestone(self):
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M2"
        self.assertBlocked(self.stop(), "M2")
        self.assertBlocked(self.stop(active=True), "acceptance: GET /export")

    def test_first_open_milestone_when_none_named(self):
        self.assertBlocked(self.stop(), "M2 'Export endpoint")

    def test_done_and_blocked_milestones_allow(self):
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M1"
        self.assertAllowed(self.stop())
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M3"
        self.assertAllowed(self.stop())

    def test_ticking_the_box_releases(self):
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M2"
        self.assertBlocked(self.stop())
        with open(self.plan, "w") as fh:
            fh.write(PLAN.replace("- [ ] M2", "- [x] M2"))
        self.assertAllowed(self.stop())

    def test_cap(self):
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M2"
        self.env["FOUNDRY_SHIP_MAX_BLOCKS"] = "3"
        for _ in range(3):
            self.assertBlocked(self.stop(active=True))
        code, out, err = self.stop(active=True)
        self.assertIsNone(out)
        self.assertIn("human", err)
        self.assertEqual(self.log_lines()[-1]["action"], "allow-cap-reached")

    def test_default_cap_is_20(self):
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M2"
        blocks = 0
        for _ in range(25):
            _, out, _ = self.stop(active=True)
            blocks += 1 if out else 0
        self.assertEqual(blocks, 20)

    def test_unknown_milestone_and_missing_file(self):
        self.env["FOUNDRY_SHIP_MILESTONE"] = "M42"
        self.assertAllowed(self.stop())
        self.env["FOUNDRY_SHIP_WORKPLAN"] = os.path.join(self.tmp, "missing.md")
        self.assertAllowed(self.stop())

    def test_relative_workplan_uses_project_dir(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.tmp
        self.env["FOUNDRY_SHIP_WORKPLAN"] = "WORKPLAN.md"
        self.assertBlocked(self.stop())

    def test_background_tasks_allow(self):
        self.assertAllowed(self.stop(background_tasks=[{"id": "x", "type": "shell"}]))

    def test_disable(self):
        self.env["FOUNDRY_SHIP_STOP"] = "0"
        self.assertAllowed(self.stop())

    def test_malformed(self):
        for raw in ["", "{{", "42"]:
            self.assertAllowed(self.run_hook(S, None, raw=raw))


if __name__ == "__main__":
    unittest.main()
