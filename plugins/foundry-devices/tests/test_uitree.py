import io
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "android-ui-tree", "scripts"))
import uitree  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "android_login.xml")
SETTINGS = os.path.join(HERE, "fixtures", "android_settings_api34.xml")


def _no_adb():
    return None


_saved = {}


def setUpModule():
    # tap probes `adb devices` when no serial is given. Keep the tests independent of
    # whatever adb and devices the test host has.
    _saved["probe"] = uitree.attached_serials
    _saved["serial"] = os.environ.pop("ANDROID_SERIAL", None)
    uitree.attached_serials = _no_adb


def tearDownModule():
    uitree.attached_serials = _saved["probe"]
    if _saved["serial"] is not None:
        os.environ["ANDROID_SERIAL"] = _saved["serial"]


def load():
    with open(FIX, encoding="utf-8") as fh:
        return uitree.parse(fh.read())


class TestUiTree(unittest.TestCase):
    def test_parse_bounds(self):
        self.assertEqual(uitree.parse_bounds("[0,10][20,30]"), (0, 10, 20, 30))
        self.assertIsNone(uitree.parse_bounds("garbage"))

    def test_parse_tolerates_trailing_status_line(self):
        nodes = load()
        self.assertEqual(len(nodes), 6)
        self.assertEqual(nodes[0].cls, "android.widget.FrameLayout")

    def test_center(self):
        btn = uitree.find(load(), rid="sign_in")[0]
        self.assertEqual(btn.center, (540, 960))

    def test_text_substring_case_insensitive(self):
        hits = uitree.find(load(), text="sign in")
        self.assertEqual([h.resource_id.split("/")[-1] for h in hits], ["sign_in", "sso"])

    def test_exact(self):
        hits = uitree.find(load(), text="Sign in", exact=True)
        self.assertEqual(len(hits), 1)

    def test_desc_and_full_id(self):
        self.assertEqual(len(uitree.find(load(), desc="email")), 1)
        self.assertEqual(len(uitree.find(load(), rid="com.example.app:id/email")), 1)

    def test_zero_size_skipped(self):
        self.assertEqual(uitree.find(load(), text="Hidden"), [])

    def test_disabled_flag_in_label(self):
        sso = uitree.find(load(), rid="sso")[0]
        self.assertIn("disabled", sso.label())

    def test_tap_unique(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = uitree.main(["tap", FIX, "--text", "Sign in", "--exact"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "adb shell input tap 540 960")

    def test_tap_ambiguous_refuses(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = uitree.main(["tap", FIX, "--text", "sign in"])
        self.assertEqual(rc, 2)
        self.assertIn("found 2", err.getvalue())

    def test_find_no_match_exit_1(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(uitree.main(["find", FIX, "--text", "nope"]), 1)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = uitree.main(argv)
    return rc, out.getvalue().strip(), err.getvalue()


class TestRealSettingsDump(unittest.TestCase):
    """A trimmed real dump (API 34 emulator, Settings home, CI run 40731526347).

    On list screens the text node is not clickable; its row ancestor is. The
    skill's headline `tap --text X --exact --clickable` used to find 0 matches.
    """

    def tearDown(self):
        uitree.attached_serials = _no_adb   # tests below swap the probe; put the stub back

    def test_clickable_resolves_to_row_ancestor(self):
        with open(SETTINGS, encoding="utf-8") as fh:
            nodes = uitree.parse(fh.read())
        hits = uitree.find(nodes, text="Network & internet", exact=True, clickable_only=True)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].clickable)
        self.assertEqual(hits[0].cls, "android.widget.LinearLayout")
        self.assertEqual(hits[0].center, (160, 313))

    def test_clickable_dedupes_title_and_summary_of_one_row(self):
        with open(SETTINGS, encoding="utf-8") as fh:
            nodes = uitree.parse(fh.read())
        # A substring that hits several text nodes of one row returns that row once,
        # and the title and the summary of a row resolve to the same row.
        hits = uitree.find(nodes, text="i", clickable_only=True)
        self.assertEqual(len({h.index_path for h in hits}), len(hits))
        rows = uitree.find(nodes, text="Network", clickable_only=True)
        summary = uitree.find(nodes, text="hotspot", clickable_only=True)
        self.assertEqual([h.index_path for h in rows], [h.index_path for h in summary])

    def test_clickable_node_itself_is_kept(self):
        with open(SETTINGS, encoding="utf-8") as fh:
            nodes = uitree.parse(fh.read())
        hits = uitree.find(nodes, rid="search_action_bar", clickable_only=True)
        self.assertEqual([h.center for h in hits], [(160, 227)])

    def test_headline_tap_example_on_real_dump(self):
        rc, out, err = run_main(["tap", SETTINGS, "--text", "Network & internet", "--exact", "--clickable"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "adb shell input tap 160 313")

    def test_without_clickable_still_returns_the_text_node(self):
        rc, out, _ = run_main(["tap", SETTINGS, "--text", "Network & internet", "--exact"])
        self.assertEqual((rc, out), (0, "adb shell input tap 155 303"))

    def test_tap_with_serial_prints_dash_s(self):
        rc, out, _ = run_main(["tap", SETTINGS, "--text", "Network & internet", "--exact",
                               "--clickable", "--serial", "emulator-5554"])
        self.assertEqual((rc, out), (0, "adb -s emulator-5554 shell input tap 160 313"))

    def test_tap_serial_from_android_serial_env(self):
        os.environ["ANDROID_SERIAL"] = "R58M123"
        try:
            rc, out, _ = run_main(["tap", SETTINGS, "--text", "Network & internet", "--exact"])
        finally:
            del os.environ["ANDROID_SERIAL"]
        self.assertEqual((rc, out), (0, "adb -s R58M123 shell input tap 155 303"))

    def test_tap_single_attached_device_gets_its_serial(self):
        uitree.attached_serials = lambda: ["emulator-5554"]
        rc, out, _ = run_main(["tap", SETTINGS, "--text", "Network & internet", "--exact"])
        self.assertEqual((rc, out), (0, "adb -s emulator-5554 shell input tap 155 303"))

    def test_tap_refuses_when_several_devices_and_no_serial(self):
        uitree.attached_serials = lambda: ["emulator-5554", "R58M123"]
        rc, out, err = run_main(["tap", SETTINGS, "--text", "Network & internet", "--exact"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("--serial", err)
        self.assertIn("R58M123", err)

    def test_parse_adb_devices_keeps_only_ready_devices(self):
        text = ("List of devices attached\nemulator-5554\tdevice\nR58M123\tunauthorized\n"
                "0A1B\tdevice usb:1-1 product:x model:Pixel_7\n")
        self.assertEqual(uitree.parse_adb_devices(text), ["emulator-5554", "0A1B"])


if __name__ == "__main__":
    unittest.main()
