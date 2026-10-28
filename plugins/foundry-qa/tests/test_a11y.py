import unittest

import _paths  # noqa: F401
import a11y_check as ac


class TestTargetSize(unittest.TestCase):
    """WCAG 2.2 2.5.8: axe passed 20x20 icon buttons, so the script measures them itself."""

    def base(self):
        return ac.summarize({"violations": [], "incomplete": [], "passes": []}, "serious")

    def test_failing_targets_become_a_blocking_violation(self):
        ts = {"failing": [{"target": 'button[aria-label="Join"]', "size": "20x20", "near": "button"}],
              "small": [{"target": "a.skip", "size": "134x20", "near": None}]}
        out = ac.merge_target_size(self.base(), ts, "serious")
        v = out["violations"][0]
        self.assertEqual((v["id"], v["impact"], v["blocking"], v["nodes"]), ("target-size-2.5.8", "serious", True, 1))
        self.assertEqual(out["blocking"], 1)
        self.assertEqual(out["target_size"]["small"][0]["target"], "a.skip")
        self.assertEqual(ac.page_verdict([out]), ac.EXIT_FAIL)

    def test_small_but_spaced_targets_are_manual_review_only(self):
        out = ac.merge_target_size(self.base(), {"failing": [], "small": [{"target": "x", "size": "10x10"}]}, "serious")
        self.assertEqual(out["blocking"], 0)
        self.assertEqual(out["violations"], [])
        self.assertEqual(ac.page_verdict([out]), ac.EXIT_PASS)

    def test_fail_on_critical_keeps_it_non_blocking(self):
        ts = {"failing": [{"target": "b", "size": "20x20", "near": "c"}], "small": []}
        out = ac.merge_target_size(self.base(), ts, "critical")
        self.assertFalse(out["violations"][0]["blocking"])


if __name__ == "__main__":
    unittest.main()
