"""Tests for bin/iphone-mirror, run against the worker in-process (no helper app)."""
import os
import unittest

from _support import Sandbox, run_cli, CLI


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(geometry="0 0 200 400")

    def tearDown(self):
        self.sb.close()

    def test_help_lists_commands(self):
        rc, out = run_cli(self.sb, "help")
        self.assertEqual(rc, 0)
        for cmd in ("doctor", "build", "shot", "tap", "swipe", "type", "key", "home", "map"):
            self.assertIn(f"iphone-mirror {cmd}", out)
        self.assertFalse(out.startswith("shellcheck"))

    def test_unknown_command(self):
        rc, out = run_cli(self.sb, "frobnicate")
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown command", out)

    def test_argument_validation_happens_before_any_action(self):
        for args in (("tap", "1"), ("tap", "x", "2"), ("swipe", "1", "2", "3"), ("type",), ("key",)):
            rc, out = run_cli(self.sb, *args)
            self.assertNotEqual(rc, 0, args)
        self.assertEqual(self.sb.clicks(), [])

    def test_info_then_map_round_trip(self):
        rc, out = run_cli(self.sb, "info")
        self.assertEqual((rc, out), (0, "0 0 200 400"))
        self.sb.record_shot(400, 800)
        rc, out = run_cli(self.sb, "map", "200", "400")
        self.assertEqual((rc, out), (0, "100 200"))

    def test_tap_through_client(self):
        run_cli(self.sb, "info")
        self.sb.record_shot(400, 800)
        rc, out = run_cli(self.sb, "tap", "40", "80")
        self.assertEqual(rc, 0, out)
        self.assertIn("global(20,40)", out)
        self.assertEqual(self.sb.clicks(), ["c:20,40"])

    def test_worker_error_propagates_rc(self):
        rc, out = run_cli(self.sb, "map", "1", "1")
        self.assertEqual(rc, 1)
        self.assertIn("run shot first", out)

    def test_lock_is_released(self):
        run_cli(self.sb, "info")
        self.assertFalse(os.path.exists(os.path.join(self.sb.state, "lock")))

    def test_missing_helper_is_reported(self):
        env_helper = os.path.join(self.sb.dir, "Nope.app")
        self.sb.env["IPHONE_MIRROR_HELPER"] = env_helper
        rc, out = run_cli(self.sb, "map", "1", "1", direct=False)  # map never raises the mirror window
        self.assertNotEqual(rc, 0)
        self.assertIn("helper app missing", out)

    def test_cli_is_executable(self):
        self.assertTrue(os.access(CLI, os.X_OK))


if __name__ == "__main__":
    unittest.main()
