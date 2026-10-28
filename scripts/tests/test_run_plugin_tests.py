"""Tests for scripts/run_plugin_tests.py.

Run: python3 -m unittest discover -s scripts/tests -v
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import run_plugin_tests as rpt  # noqa: E402


def write(root, path, text):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


PASS = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAIL = "import unittest\n\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.fail('no')\n"


class RunPluginTestsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        write(self.root, "plugins/a/tests/test_a.py", PASS)
        write(self.root, "plugins/a/tests/fixtures/tests/test_fixture.py", FAIL)  # nested: ignored
        write(self.root, "plugins/b/scripts/tests/test_b.py", PASS)
        write(self.root, "plugins/b/skills/s/scripts/tests/test_s.py", PASS)
        write(self.root, "plugins/c/tests/helper.py", "X = 1\n")  # no test*.py: not a suite

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_finds_every_suite(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(rpt.main(["--root", self.root, "--list"]), 0)
        self.assertEqual(out.getvalue().split("\n")[:-1],
                         ["a: tests", "b: scripts/tests", "b: skills/s/scripts/tests"])

    def test_runs_and_reports_failure(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(rpt.main(["--root", self.root, "--plugin", "a"]), 0)
        write(self.root, "plugins/a/tests/test_more.py", FAIL)
        devnull = open(os.devnull, "w")
        old = sys.stderr
        try:
            sys.stderr = devnull
            with redirect_stdout(io.StringIO()):
                self.assertEqual(rpt.main(["--root", self.root, "--plugin", "a"]), 1)
        finally:
            sys.stderr = old
            devnull.close()


if __name__ == "__main__":
    unittest.main()
