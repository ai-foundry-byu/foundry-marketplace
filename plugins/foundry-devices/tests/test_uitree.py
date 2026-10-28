import io
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "android-ui-tree", "scripts"))
import uitree  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "android_login.xml")


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


if __name__ == "__main__":
    unittest.main()
