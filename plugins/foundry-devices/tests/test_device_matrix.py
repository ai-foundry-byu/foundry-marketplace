import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import device_matrix as dm  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "stories.json")


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.stories = dm.load_stories(FIX)

    def test_aliases_and_profiles(self):
        self.assertEqual(dm.split_device("Android:pixel_7"), ("android", "pixel_7"))
        self.assertEqual(dm.split_device("mobile-web"), ("web-mobile", ""))
        self.assertEqual(dm.split_device("andriod"), (None, ""))

    def test_plan_groups_lanes(self):
        p = dm.plan(self.stories, host="macos")
        lanes = {l["lane"]: l for l in p["lanes"]}
        self.assertEqual(set(lanes), {"ios", "android", "web-mobile", "windows", "macos"})
        self.assertEqual(lanes["android"]["stories"], ["S1", "S2"])
        self.assertEqual(lanes["android"]["profiles"], ["pixel_7"])
        self.assertTrue(lanes["ios"]["runnable_here"])
        self.assertFalse(lanes["windows"]["runnable_here"])
        self.assertEqual(p["unknown_devices"], [{"story": "S4", "device": "andriod"}])
        self.assertEqual(p["stories_without_devices"], ["S3"])

    def test_plan_on_windows_host(self):
        p = dm.plan(self.stories, host="windows")
        lanes = {l["lane"]: l for l in p["lanes"]}
        self.assertTrue(lanes["windows"]["runnable_here"])
        self.assertFalse(lanes["ios"]["runnable_here"])

    def test_duplicate_ids_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([{"id": "A", "devices": ["ios"]}, {"id": "A", "devices": []}], fh)
        try:
            with self.assertRaises(ValueError):
                dm.load_stories(fh.name)
        finally:
            os.unlink(fh.name)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.stories = dm.load_stories(FIX)
        self.tmp = tempfile.TemporaryDirectory()
        self.qa = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, lane, rows, device="dev"):
        os.makedirs(os.path.join(self.qa, lane), exist_ok=True)
        with open(os.path.join(self.qa, lane, "results.json"), "w") as fh:
            json.dump({"lane": lane, "device": device, "build": "1.0", "stories": rows}, fh)

    def all_pass(self):
        p = dm.plan(self.stories)
        for l in p["lanes"]:
            self.write(l["lane"], [{"id": s, "status": "PASS", "evidence": []} for s in l["stories"]])

    def test_init_skeleton_does_not_clobber(self):
        written = dm.init(self.stories, self.qa)
        self.assertEqual(len(written), 5)
        self.write("ios", [{"id": "S1", "status": "PASS"}])
        self.assertEqual(dm.init(self.stories, self.qa), [])
        with open(os.path.join(self.qa, "ios", "results.json")) as fh:
            self.assertEqual(json.load(fh)["stories"][0]["status"], "PASS")

    def test_missing_lane_is_inconclusive(self):
        self.write("ios", [{"id": "S1", "status": "PASS"}])
        m = dm.build_matrix(self.stories, self.qa)
        self.assertEqual(m["verdict"], "INCONCLUSIVE")
        self.assertEqual(m["cells"]["S1"]["android"]["status"], "NOT_RUN")
        self.assertIn("no results.json", dm.render_matrix(m))

    def test_all_pass(self):
        self.all_pass()
        self.assertEqual(dm.build_matrix(self.stories, self.qa)["verdict"], "PASS")

    def test_fail_beats_inconclusive(self):
        self.all_pass()
        self.write("android", [{"id": "S1", "status": "fail", "notes": "crash on submit",
                                "evidence": [".qa/android/S1-crash.png"]},
                               {"id": "S2", "status": "INCONCLUSIVE"}])
        m = dm.build_matrix(self.stories, self.qa)
        self.assertEqual(m["verdict"], "FAIL")
        md = dm.render_matrix(m)
        self.assertIn("S1 on android: FAIL. crash on submit (.qa/android/S1-crash.png)", md)

    def test_bogus_status_becomes_inconclusive(self):
        self.all_pass()
        self.write("macos", [{"id": "S2", "status": "LGTM"}])
        m = dm.build_matrix(self.stories, self.qa)
        self.assertEqual(m["cells"]["S2"]["macos"]["status"], "INCONCLUSIVE")
        self.assertEqual(m["verdict"], "INCONCLUSIVE")

    def test_report_exit_codes_and_matrix_file(self):
        self.all_pass()
        with redirect_stdout(io.StringIO()):
            rc = dm.main(["report", FIX, "--qa", self.qa])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(self.qa, "matrix.md")))


if __name__ == "__main__":
    unittest.main()
