"""Compile engine/launcher.c and check it execs Resources/worker.sh with its args,
dropping the legacy -psn argument. Skipped off macOS (the launcher is a macOS app-bundle
helper that uses macOS APIs) and when clang is not installed."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _support import ROOT, write_exe


@unittest.skipUnless(sys.platform == "darwin", "the launcher is a macOS app-bundle helper")
@unittest.skipUnless(shutil.which("clang"), "clang not installed (xcode-select --install)")
class LauncherTests(unittest.TestCase):
    def test_launcher_execs_worker_with_args(self):
        with tempfile.TemporaryDirectory() as d:
            macos = os.path.join(d, "T.app", "Contents", "MacOS")
            res = os.path.join(d, "T.app", "Contents", "Resources")
            os.makedirs(macos)
            os.makedirs(res)
            exe = os.path.join(macos, "T")
            subprocess.run(["clang", "-O2", "-o", exe, os.path.join(ROOT, "engine", "launcher.c")], check=True)
            write_exe(os.path.join(res, "worker.sh"), '#!/bin/bash\nprintf "[%s]" "$@"\n')
            p = subprocess.run([exe, "-psn_0_12345", "tap", "10", "two words"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, "[tap][10][two words]")


if __name__ == "__main__":
    unittest.main()
