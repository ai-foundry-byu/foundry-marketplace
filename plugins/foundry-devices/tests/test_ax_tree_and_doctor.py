import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "macos-ax-tree", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "device-doctor", "scripts"))
import ax_tree  # noqa: E402
import doctor  # noqa: E402

AX = os.path.join(HERE, "fixtures", "ax_calc.json")
# Trimmed from a real dump: Calculator on macOS 26.6.2, GitHub Actions run 40731526347.
AX_REAL = os.path.join(HERE, "fixtures", "ax_calc_macos26.json")


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


class TestAxTreeRealCalculator(unittest.TestCase):
    """Current Calculator keys have an AXIdentifier ("Seven"), description "button", no name."""

    def setUp(self):
        with open(AX_REAL) as fh:
            self.tree = json.load(fh)

    def test_name_finds_nothing_on_current_calculator(self):
        self.assertEqual(ax_tree.find(self.tree, role="AXButton", name="7"), [])

    def test_find_by_id_seven(self):
        hits = ax_tree.find(self.tree, role="AXButton", ident="Seven")
        self.assertEqual([h["path"] for h in hits], ["1/1/1/1/1/6"])
        self.assertEqual(ax_tree.center(hits[0]), (96, 563))   # what CI printed before pressing it

    def test_name_miss_prints_id_hint(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = ax_tree.main(["find", AX_REAL, "--role", "AXButton", "--name", "7"])
        self.assertEqual(rc, 1)
        self.assertIn("--id", err.getvalue())

    def test_docstring_example_matches_real_tree(self):
        self.assertIn("--id Seven", ax_tree.__doc__)
        self.assertNotIn('--name "7"', ax_tree.__doc__)


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

    def test_screen_recording_row_is_never_ok_when_not_probed(self):
        c = doctor.screen_recording_check()
        self.assertFalse(c.ok)
        self.assertFalse(c.required)
        self.assertFalse(c.probed)
        self.assertIn("not probed", c.detail)
        rep = doctor.Report(platform="macos", host_os="macos", checked_at="z",
                            checks=[doctor.Check("osascript", required=True, ok=True), c])
        text = doctor.render(rep)
        line = [ln for ln in text.splitlines() if "Screen Recording" in ln][0]
        self.assertNotIn("[OK", line)
        self.assertIn("not probed", line)
        self.assertTrue(rep.ready)          # optional and unknown: does not block READY
        self.assertIn("fix:", text)          # the fix line is shown for an unknown row

    def test_maestro_fix_lines_put_it_on_path(self):
        # The installer only edits shell rc files, so the same shell needs the export
        # (CI: `command -v maestro` exits 1 right after the install line).
        real_which = doctor.shutil.which
        doctor.shutil.which = lambda _b: None      # nothing installed: no subprocess runs
        try:
            for checks in (doctor.checks_ios, doctor.checks_android):
                row = [c for c in checks() if c.name.startswith("maestro")][0]
                self.assertIn('export PATH="$PATH:$HOME/.maestro/bin"', row.fix, checks.__name__)
                self.assertIn("get.maestro.mobile.dev", row.fix)
        finally:
            doctor.shutil.which = real_which

    def test_ready_only_counts_required(self):
        rep = doctor.Report(platform="x", host_os="y", checked_at="z", checks=[
            doctor.Check("a", required=True, ok=True),
            doctor.Check("b", required=False, ok=False)])
        self.assertTrue(rep.ready)
        rep.checks.append(doctor.Check("c", required=True, ok=False))
        self.assertFalse(rep.ready)


if __name__ == "__main__":
    unittest.main()
