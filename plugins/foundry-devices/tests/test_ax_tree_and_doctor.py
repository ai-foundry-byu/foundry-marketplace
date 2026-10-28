import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "macos-ax-tree", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "device-doctor", "scripts"))
import ax_tree  # noqa: E402
import doctor  # noqa: E402

AX = os.path.join(HERE, "fixtures", "ax_calc.json")


class TestAxTree(unittest.TestCase):
    def setUp(self):
        with open(AX) as fh:
            self.tree = json.load(fh)

    def test_find_role_and_desc(self):
        hits = ax_tree.find(self.tree, role="AXButton", desc="7")
        self.assertEqual([h["path"] for h in hits], ["1/3/7"])

    def test_find_by_identifier_and_value(self):
        self.assertEqual(ax_tree.find(self.tree, ident="clear")[0]["path"], "1/3/8")
        self.assertEqual(ax_tree.find(self.tree, value="42")[0]["role"], "AXStaticText")

    def test_center_and_label(self):
        seven = ax_tree.find(self.tree, ident="Seven")[0]
        self.assertEqual(ax_tree.center(seven), (135, 230))
        lab = ax_tree.label(ax_tree.find(self.tree, ident="Clear")[0])
        self.assertIn("[disabled]", lab)
        self.assertIn("path=1/3/8", lab)

    def test_outline_skips_unlabeled(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ax_tree.main(["outline", AX])
        self.assertIn("AXButton", buf.getvalue())
        bare = {"path": "1/9", "depth": 1, "role": "AXGroup", "name": None,
                "description": "", "value": "missing value", "identifier": None}
        self.assertFalse(ax_tree.meaningful(bare))
        self.assertTrue(ax_tree.meaningful(self.tree[2]))

    def test_missing_file_exit_2(self):
        self.assertEqual(ax_tree.main(["outline", "/nonexistent/ax.json"]), 2)


class TestDoctor(unittest.TestCase):
    def test_parse_adb_devices(self):
        out = ("* daemon not running; starting now at tcp:5037\n"
               "List of devices attached\n"
               "emulator-5554\tdevice\n"
               "R58M123\tunauthorized\n\n")
        self.assertEqual(doctor.parse_adb_devices(out),
                         [("emulator-5554", "device"), ("R58M123", "unauthorized")])

    def test_run_missing_binary(self):
        ok, detail = doctor.run(["definitely-not-a-real-binary-xyz"])
        self.assertFalse(ok)
        self.assertEqual(detail, "not found")

    def test_run_timeout_reported_not_raised(self):
        ok, detail = doctor.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
        self.assertFalse(ok)
        self.assertIn("timed out", detail)

    def test_ready_only_counts_required(self):
        rep = doctor.Report(platform="x", host_os="y", checked_at="z", checks=[
            doctor.Check("a", required=True, ok=True),
            doctor.Check("b", required=False, ok=False)])
        self.assertTrue(rep.ready)
        rep.checks.append(doctor.Check("c", required=True, ok=False))
        self.assertFalse(rep.ready)


if __name__ == "__main__":
    unittest.main()
