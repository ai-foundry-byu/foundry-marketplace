"""Tests for validate_findings.py. Run from the plugin root:

    python3 -m unittest discover -s skills/design-critique/scripts/tests -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import validate_findings as v  # noqa: E402

with open(v.DEFAULT_SCHEMA, encoding="utf-8") as _fh:
    SCHEMA = json.load(_fh)


def finding(**over):
    f = {
        "id": "df-1",
        "question": 6,
        "surface": "route:/settings",
        "claim": "Two toggles live on their own page.",
        "proposal": {"type": "inline", "diff_hint": "move the two toggles under the profile header"},
        "delta": {"clicks_before": 4, "clicks_after": 3},
        "class": "agent-fixes",
        "severity": "flag",
        "constitution_refs": ["C6"],
    }
    f.update(over)
    return f


class ValidateTests(unittest.TestCase):
    def errs(self, data):
        return v.validate(data, SCHEMA)[0]

    def test_valid_finding(self):
        self.assertEqual(self.errs([finding()]), [])

    def test_empty_run_is_valid(self):
        self.assertEqual(self.errs([]), [])
        self.assertEqual(self.errs({"findings": []}), [])

    def test_add_verb_rejected(self):
        e = self.errs([finding(proposal={"type": "add"})])
        self.assertTrue(any("not one of" in x for x in e), e)

    def test_missing_required(self):
        f = finding()
        del f["claim"]
        self.assertTrue(any("claim" in x for x in self.errs([f])))

    def test_unknown_field_rejected(self):
        self.assertTrue(any("unknown field" in x for x in self.errs([finding(mood="bad")])))

    def test_question_range(self):
        self.assertTrue(self.errs([finding(question=9)]))
        self.assertTrue(self.errs([finding(question=True)]))  # bool is not an integer here

    def test_flow_shape_needs_delta(self):
        f = finding()
        del f["delta"]
        self.assertTrue(any("flow-shape" in x for x in self.errs([f])))
        # C2 (a label) needs no delta
        self.assertEqual(self.errs([f | {"question": 2, "proposal": {"type": "relabel"}}]), [])
        # escalations need no delta
        self.assertEqual(self.errs([f | {"proposal": {"type": "escalate"}}]), [])

    def test_delta_cannot_grow(self):
        e = self.errs([finding(delta={"clicks_before": 2, "clicks_after": 3})])
        self.assertTrue(any("cannot add" in x for x in e))

    def test_nit_cap(self):
        nits = [finding(id=f"n{i}", severity="nit") for i in range(3)]
        self.assertTrue(any("nits" in x for x in self.errs(nits)))
        self.assertEqual(self.errs(nits[:2]), [])

    def test_duplicate_ids(self):
        self.assertTrue(any("duplicate" in x for x in self.errs([finding(), finding()])))

    def test_ungrounded_must_escalate(self):
        f = finding()
        del f["constitution_refs"]
        self.assertTrue(any("grounding" in x for x in self.errs([f])))
        self.assertEqual(self.errs([f | {"proposal": {"type": "escalate"}}]), [])

    def test_addition_language_warns(self):
        errs, warns = v.validate([finding(proposal={"type": "merge", "diff_hint": "add a new button for export"})], SCHEMA)
        self.assertEqual(errs, [])
        self.assertTrue(warns)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.json")
            bad = os.path.join(tmp, "bad.json")
            with open(good, "w") as fh:
                json.dump([finding()], fh)
            with open(bad, "w") as fh:
                json.dump([finding(proposal={"type": "add"})], fh)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(v.main([good]), 0)
                self.assertEqual(v.main([bad]), 1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(v.main([os.path.join(tmp, "missing.json")]), 2)

    def test_example_findings_file_is_valid(self):
        path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "templates", "findings.example.json")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(self.errs(json.load(fh)), [])


if __name__ == "__main__":
    unittest.main()
