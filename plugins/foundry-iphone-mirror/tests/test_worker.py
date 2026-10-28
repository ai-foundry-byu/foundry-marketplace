"""Unit tests for engine/worker.sh: pixel->point math, state handling, guards."""
import os
import shutil
import subprocess
import unittest

from _support import Sandbox, run_worker, read, write_exe, WORKER


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(geometry="100 50 300 600")  # window at (100,50), 300x600 pt

    def tearDown(self):
        self.sb.close()

    def test_selftest(self):
        rc, out = run_worker(self.sb, "selftest")
        self.assertEqual(rc, 0, out)
        self.assertIn("helper worker alive", out)
        self.assertTrue(os.path.exists(os.path.join(self.sb.state, "done")))

    def test_geometry_writes_cache(self):
        rc, out = run_worker(self.sb, "geometry")
        self.assertEqual((rc, out), (0, "100 50 300 600"))
        geom = read(os.path.join(self.sb.state, "geom.env"))
        self.assertIn("WW=300", geom)

    def test_map_needs_geometry(self):
        rc, out = run_worker(self.sb, "map", "10", "10")
        self.assertEqual(rc, 1)
        self.assertIn("run shot first", out)

    def test_map_needs_a_shot_after_geometry(self):
        run_worker(self.sb, "geometry")
        rc, out = run_worker(self.sb, "map", "10", "10")
        self.assertEqual(rc, 1)
        self.assertIn("no screenshot recorded", out)

    def test_map_retina_2x(self):
        run_worker(self.sb, "geometry")
        self.sb.record_shot(600, 1200)  # 2x pixels
        rc, out = run_worker(self.sb, "map", "300", "600")
        self.assertEqual((rc, out), (0, "250 350"))  # 100+150, 50+300
        rc, out = run_worker(self.sb, "map", "0", "0")
        self.assertEqual(out, "100 50")

    def test_map_rejects_out_of_bounds(self):
        run_worker(self.sb, "geometry")
        self.sb.record_shot(600, 1200)
        rc, out = run_worker(self.sb, "map", "601", "10")
        self.assertEqual(rc, 1)
        self.assertIn("outside the last screenshot", out)

    def test_map_rejects_non_integers(self):
        run_worker(self.sb, "geometry")
        self.sb.record_shot(600, 1200)
        for bad in ("1.5", "abc", "1;rm", ""):
            rc, out = run_worker(self.sb, "map", bad, "10")
            self.assertEqual(rc, 1, bad)

    def test_tap_maps_and_clicks(self):
        run_worker(self.sb, "geometry")
        self.sb.record_shot(600, 1200)
        rc, out = run_worker(self.sb, "tap", "60", "120")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sb.clicks(), ["c:130,110"])

    def test_swipe_maps_both_ends(self):
        run_worker(self.sb, "geometry")
        self.sb.record_shot(600, 1200)
        rc, out = run_worker(self.sb, "swipe", "300", "1000", "300", "200")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sb.clicks(), ["dd:250,550 dm:250,150 du:250,150"])

    def test_home_gesture_from_bottom_center(self):
        rc, out = run_worker(self.sb, "home")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sb.clicks(), ["dd:250,645 dm:250,450 du:250,450"])

    def test_type_does_not_echo_text(self):
        rc, out = run_worker(self.sb, "type", "hunter2")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("hunter2", out)
        self.assertEqual(self.sb.clicks(), ["t:hunter2"])

    def test_geometry_errors_are_reported(self):
        for fake, want in (("ERR_NOT_RUNNING", "not running"), ("ERR_NO_WINDOW", "no window"),
                           ("0 0 0 0", "zero size"), ("a b c d", "unexpected geometry")):
            self.sb.env["IPHONE_MIRROR_FAKE_GEOMETRY"] = fake
            rc, out = run_worker(self.sb, "geometry")
            self.assertEqual(rc, 1, fake)
            self.assertIn(want, out, fake)

    def test_geom_file_is_parsed_not_sourced(self):
        marker = os.path.join(self.sb.dir, "pwned")
        with open(os.path.join(self.sb.state, "geom.env"), "w") as f:
            f.write(f"WX=1\nWY=1\nWW=10\nWH=10\nIMGW=10\nIMGH=10\n$(touch {marker})\ntouch {marker}\n")
        rc, out = run_worker(self.sb, "map", "5", "5")
        self.assertEqual((rc, out), (0, "6 6"))
        self.assertFalse(os.path.exists(marker), "geom.env content was executed")

    def test_test_hooks_ignored_inside_a_bundle(self):
        res = os.path.join(self.sb.dir, "Fake.app", "Contents", "Resources")
        os.makedirs(res)
        shutil.copy(WORKER, res)
        # config.env with no cliclick, and a fake cliclick in the env: inside a bundle
        # the env hook must be ignored, so the recorder must never be called.
        with open(os.path.join(res, "config.env"), "w") as f:
            f.write("CLICLICK=/nonexistent\n")
        env = dict(self.sb.env)
        env["PATH"] = "/usr/bin:/bin"
        p = subprocess.run(["/bin/bash", os.path.join(res, "worker.sh"), "selftest"], env=env,
                           capture_output=True, text=True, timeout=20)
        # State dir override is ignored too, so the result lands under $HOME/Library/Caches.
        result = os.path.join(self.sb.dir, "Library", "Caches", "foundry-iphone-mirror", "result")
        self.assertEqual(p.returncode, 0)
        text = read(result)
        self.assertNotIn(self.sb.cliclick, text)

    def _fake_osascript(self, body):
        bindir = os.path.join(self.sb.dir, "fakebin")
        os.makedirs(bindir, exist_ok=True)
        write_exe(os.path.join(bindir, "osascript"), "#!/bin/bash\ncat >/dev/null\n" + body)
        del self.sb.env["IPHONE_MIRROR_FAKE_GEOMETRY"]
        self.sb.env["PATH"] = bindir + ":/usr/bin:/bin:/usr/sbin"

    def test_real_geometry_path_parses_osascript(self):
        self._fake_osascript('[ "$2" = "iPhone Mirroring" ] && echo "10 20 300 600"\n')
        rc, out = run_worker(self.sb, "geometry")
        self.assertEqual((rc, out), (0, "10 20 300 600"))

    def test_unanswered_automation_prompt_times_out(self):
        self._fake_osascript("exec sleep 30\n")
        rc, out = run_worker(self.sb, "geometry")
        self.assertEqual(rc, 1)
        self.assertIn("Automation", out)

    def test_unknown_command(self):
        rc, out = run_worker(self.sb, "launch-missiles")
        self.assertEqual(rc, 1)
        self.assertIn("unknown worker command", out)


if __name__ == "__main__":
    unittest.main()
