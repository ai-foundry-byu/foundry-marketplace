"""Unit tests for evalkit.py and judge_claude.py. Offline, stdlib only.

Run from the plugin root:  python3 -m unittest discover -s scripts/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import evalkit as ek  # noqa: E402
import judge_claude as jc  # noqa: E402

PY = sys.executable


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def make_suite(root: Path, target_src: str, cases: list, **extra) -> Path:
    write(root / "target.py", target_src)
    suite = {"name": "t", "target": {"command": [PY, "target.py"], "timeout_s": 10},
             "graders": [], **extra}
    write(root / "suite.json", json.dumps(suite))
    write(root / "cases.jsonl", "\n".join(json.dumps(c) for c in cases) + "\n")
    return root


ECHO = "import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'output': r['input']}))\n"


def quiet(fn, *a, **k):
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
        rc = fn(*a, **k)
    return rc, out.getvalue()


class TestGetPath(unittest.TestCase):
    def test_paths(self):
        o = {"a": {"b": [10, {"c": "x"}]}}
        self.assertEqual(ek.get_path(o, "a.b.1.c"), (True, "x"))
        self.assertEqual(ek.get_path(o, "a.b.-1.c"), (True, "x"))
        self.assertEqual(ek.get_path(o, "a.b.5"), (False, None))
        self.assertEqual(ek.get_path(o, "a.z"), (False, None))
        self.assertEqual(ek.get_path(o, ""), (True, o))


class TestGraders(unittest.TestCase):
    def g(self, grader, output, case=None, judge=None):
        ek.validate_grader(grader, "test")
        return ek.grade_one(grader, output, case or {"id": "c", "input": None}, judge)[0]

    def test_exact(self):
        self.assertTrue(self.g({"type": "exact", "value": "Yes"}, {"output": " Yes "}))
        self.assertFalse(self.g({"type": "exact", "value": "Yes"}, {"output": "yes"}))
        self.assertTrue(self.g({"type": "exact", "value": "Yes", "ignore_case": True}, {"output": "yes"}))
        self.assertTrue(self.g({"type": "exact", "value": 3, "path": "n"}, {"n": 3}))
        self.assertFalse(self.g({"type": "exact", "value": "x"}, {}))  # missing field fails

    def test_contains(self):
        out = {"output": "Your Refund is approved"}
        self.assertTrue(self.g({"type": "contains", "value": "refund", "ignore_case": True}, out))
        self.assertFalse(self.g({"type": "contains", "value": ["refund", "credit"], "ignore_case": True}, out))
        self.assertTrue(self.g({"type": "contains", "any": ["credit", "approved"]}, out))
        self.assertTrue(self.g({"type": "contains", "value": "credit", "negate": True}, out))

    def test_regex(self):
        out = {"reply": "Ask for the Order Number please"}
        self.assertTrue(self.g({"type": "regex", "path": "reply", "pattern": "order (number|id)", "flags": "i"}, out))
        self.assertFalse(self.g({"type": "regex", "path": "reply", "pattern": "order (number|id)"}, out))
        self.assertFalse(self.g({"type": "regex", "path": "reply", "pattern": "Order", "negate": True}, out))

    def test_regex_on_non_string_uses_json(self):
        self.assertTrue(self.g({"type": "regex", "path": "x", "pattern": '"k": 1'}, {"x": {"k": 1}}))

    def test_json_field(self):
        out = {"action": "deny", "n": 2, "flag": True}
        self.assertTrue(self.g({"type": "json_field", "path": "action", "equals": "deny"}, out))
        self.assertFalse(self.g({"type": "json_field", "path": "action", "one_of": ["escalate"]}, out))
        self.assertTrue(self.g({"type": "json_field", "path": "n", "is": "number"}, out))
        self.assertFalse(self.g({"type": "json_field", "path": "flag", "is": "number"}, out))  # bool is not a number
        self.assertTrue(self.g({"type": "json_field", "path": "missing", "exists": False}, out))
        self.assertFalse(self.g({"type": "json_field", "path": "action", "exists": True, "equals": "x"}, out))

    def test_validation_errors(self):
        for bad in ({"type": "nope"}, {"type": "regex", "pattern": "("}, {"type": "exact"},
                    {"type": "json_field", "path": "a"}, {"type": "json_field", "path": "a", "is": "int"},
                    {"type": "judge"}):
            with self.assertRaises(ek.ConfigError, msg=bad):
                ek.validate_grader(bad, "t")

    def test_judge_none_means_skip_and_unknown(self):
        g = {"type": "judge", "criterion": "tone"}
        self.assertEqual(ek.grade_one(g, {}, {"id": "c"}, None)[0], None)
        self.assertEqual(ek.grade_one(g, {}, {"id": "c"}, lambda c, o, g: (None, "unk"))[0], None)
        self.assertEqual(ek.grade_one(g, {}, {"id": "c"}, lambda c, o, g: (True, "ok"))[0], True)


class TestStats(unittest.TestCase):
    def test_pass_k(self):
        self.assertAlmostEqual(ek.pass_at_k(3, 1, 3), 1.0)
        self.assertAlmostEqual(ek.pass_hat_k(3, 1, 3), 0.0)
        self.assertAlmostEqual(ek.pass_hat_k(3, 3, 3), 1.0)
        self.assertAlmostEqual(ek.pass_at_k(4, 1, 2), 0.5)  # 1 - C(3,2)/C(4,2)
        self.assertAlmostEqual(ek.pass_hat_k(4, 3, 2), 0.5)  # C(3,2)/C(4,2)
        self.assertAlmostEqual(ek.pass_at_k(5, 0, 2), 0.0)

    def test_summary_excludes_errors_and_counts_flips(self):
        rows = [
            {"case_id": "a", "rep": 0, "status": "ok", "pass": True, "duration_s": 0, "tags": ["x"]},
            {"case_id": "a", "rep": 1, "status": "ok", "pass": False, "duration_s": 0, "tags": ["x"]},
            {"case_id": "b", "rep": 0, "status": "ok", "pass": True, "duration_s": 0, "tags": []},
            {"case_id": "b", "rep": 1, "status": "error", "pass": None, "duration_s": 0, "tags": []},
        ]
        s = ek.summarize(rows, reps=2, threshold=0.9)
        self.assertEqual(s["score"], 0.75)
        self.assertEqual(s["n_errors"], 1)
        self.assertEqual(s["flipping_cases"], ["a"])
        self.assertEqual(s["pass_k_short"], ["b"])
        self.assertEqual(s["pass_at_k"], 1.0)
        self.assertEqual(s["pass_hat_k"], 0.0)
        self.assertEqual(s["verdict"], "FAIL")
        self.assertEqual(s["by_tag"], {"x": 0.5})

    def test_split_is_stable(self):
        a = ek.assign_split("s", "case-1", ek.DEFAULT_SPLITS)
        self.assertEqual(a, ek.assign_split("s", "case-1", ek.DEFAULT_SPLITS))
        names = {ek.assign_split("s", f"c{i}", ek.DEFAULT_SPLITS) for i in range(200)}
        self.assertEqual(names, {"train", "val", "test"})


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_errors_are_not_zeros(self):
        src = ("import json,sys\nr=json.load(sys.stdin)\n"
               "if r['case_id']=='crash': sys.exit(3)\n"
               "if r['case_id']=='junk': print('not json'); sys.exit(0)\n"
               "print(json.dumps({'output': 'hi'}))\n")
        cases = [{"id": i, "input": "x", "graders": [{"type": "exact", "value": "hi"}]} for i in ("ok", "crash", "junk")]
        suite = ek.load_suite(make_suite(self.root, src, cases))
        rows, _ = ek.run_trials(suite, ek.load_cases(suite), reps=1)
        st = {r["case_id"]: r["status"] for r in rows}
        self.assertEqual(st, {"ok": "ok", "crash": "error", "junk": "error"})
        self.assertIn("exit 3", [r for r in rows if r["case_id"] == "crash"][0]["error"])
        self.assertEqual(ek.summarize(rows, 1)["score"], 1.0)

    def test_timeout(self):
        src = "import time,json,sys\njson.load(sys.stdin)\ntime.sleep(5)\n"
        cases = [{"id": "slow", "input": 1, "graders": [{"type": "exact", "value": 1}]}]
        p = make_suite(self.root, src, cases)
        s = json.loads((p / "suite.json").read_text())
        s["target"]["timeout_s"] = 0.5
        (p / "suite.json").write_text(json.dumps(s))
        suite = ek.load_suite(p)
        rows, _ = ek.run_trials(suite, ek.load_cases(suite), reps=1)
        self.assertIn("timeout", rows[0]["error"])

    def test_stdout_log_lines_then_json(self):
        src = "import json,sys\njson.load(sys.stdin)\nprint('loading model...')\nprint(json.dumps({'output':'ok'}))\n"
        cases = [{"id": "a", "input": 1, "graders": [{"type": "exact", "value": "ok"}]}]
        suite = ek.load_suite(make_suite(self.root, src, cases))
        rows, _ = ek.run_trials(suite, ek.load_cases(suite), reps=1)
        self.assertTrue(rows[0]["pass"])

    def test_judge_command_and_cost(self):
        write(self.root / "judge.py", "import json,sys\nr=json.load(sys.stdin)\n"
              "print(json.dumps({'pass': r['output']['output']=='good', 'reason':'r', '_meta':{'cost_usd':0.01}}))\n")
        src = "import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'output': r['input'], '_meta': {'cost_usd': 0.02}}))\n"
        cases = [{"id": i, "input": i, "graders": [{"type": "judge", "criterion": "is_good", "rubric": "r"}]}
                 for i in ("good", "bad")]
        p = make_suite(self.root, src, cases, judge={"command": [PY, "judge.py"]})
        suite = ek.load_suite(p)
        rec = ek.execute_run(suite, ek.load_cases(suite), reps=1, split="all", subset=False)
        s = rec["summary"]
        self.assertEqual(s["score"], 0.5)
        self.assertAlmostEqual(s["target_cost_usd"], 0.04)
        self.assertAlmostEqual(s["judge_cost_usd"], 0.02)
        self.assertAlmostEqual(s["total_cost_usd"], 0.06)
        rec2 = ek.execute_run(suite, ek.load_cases(suite), reps=1, split="all", subset=False, use_judge=False)
        self.assertEqual(rec2["summary"]["n_ok"], 0)  # every grader skipped -> unscorable, not a pass

    def test_load_errors(self):
        p = make_suite(self.root, ECHO, [{"id": "a", "input": 1}])  # no graders anywhere
        with self.assertRaises(ek.ConfigError):
            ek.load_cases(ek.load_suite(p))
        write(self.root / "cases.jsonl", '{"id":"a","input":1,"graders":[{"type":"exact","value":1}]}\n'
              '{"id":"a","input":2,"graders":[{"type":"exact","value":1}]}\n')
        with self.assertRaises(ek.ConfigError):
            ek.load_cases(ek.load_suite(p))


class TestCompareAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.suite = self.root / "suite"
        self.out = self.root / ".evals"
        self.ek = str(SCRIPTS / "evalkit.py")

    def tearDown(self):
        self.tmp.cleanup()

    def test_example_suite_end_to_end(self):
        rc, _ = quiet(ek.main, ["init", str(self.suite)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.suite / "judge.py").is_file())
        # Self-test and controls pass on the shipped example (fake judge, no model call).
        os.environ["EVALKIT_JUDGE_FAKE"] = "PASS"
        try:
            rc, out = quiet(ek.main, ["check", str(self.suite)])
        finally:
            del os.environ["EVALKIT_JUDGE_FAKE"]
        self.assertEqual(rc, 0, out)
        self.assertIn("control pushover", out)
        # Baseline: the deliberate final-sale bug fails 2 of 9 cases and the gate.
        rc, out = quiet(ek.main, ["run", str(self.suite), "--no-judge", "--quiet", "--gate",
                                  "--out", str(self.out), "--label", "baseline"])
        self.assertEqual(rc, ek.EXIT_BELOW, out)
        runs = ek.list_runs(self.out / "refund-triage")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["summary"]["score"], 0.7778)
        self.assertEqual(sorted(runs[0]["summary"]["always_failing_cases"]),
                         ["deny-final-sale", "deny-final-sale-over-200"])
        self.assertTrue(Path(runs[0]["_path"]).with_suffix(".md").is_file())
        # Fix the bug (one change), rerun: improvement is detected case by case.
        t = self.suite / "target_rules.py"
        t.write_text(t.read_text().replace(
            "    # BUG (on purpose): order[\"final_sale\"] is never checked.\n",
            "    if order[\"final_sale\"]:\n"
            "        return {\"action\": \"deny\", \"reply\": \"Sorry, final sale items cannot be refunded.\"}\n"))
        rc, out = quiet(ek.main, ["run", str(self.suite), "--no-judge", "--quiet", "--gate", "--out", str(self.out)])
        self.assertEqual(rc, 0, out)
        runs = ek.list_runs(self.out / "refund-triage")
        cmp_ = runs[-1]["comparison"]
        self.assertEqual(cmp_["newly_passing"], ["deny-final-sale", "deny-final-sale-over-200"])
        self.assertEqual(cmp_["newly_failing"], [])
        self.assertIn("target_rules.py", cmp_["changed_surfaces"])
        self.assertTrue(cmp_["comparable"])
        # A pilot (--cases) is a subset and never becomes the comparison baseline.
        quiet(ek.main, ["run", str(self.suite), "--no-judge", "--quiet", "--out", str(self.out),
                        "--cases", "approve-small"])
        runs = ek.list_runs(self.out / "refund-triage")
        self.assertTrue(runs[-1]["subset"])
        self.assertEqual(ek.previous_comparable(runs, {"run_id": "zz", "split": "all",
                                                       "started_at": "9999"})["run_id"], runs[-2]["run_id"])
        rc, out = quiet(ek.main, ["history", str(self.suite), "--out", str(self.out)])
        self.assertIn("baseline", out)

    def test_compare_flags_changed_case_set(self):
        cases = [{"id": "a", "input": "x", "graders": [{"type": "exact", "value": "x"}]}]
        p = make_suite(self.suite, ECHO, cases)
        quiet(ek.main, ["run", str(p), "--quiet", "--out", str(self.out)])
        cases.append({"id": "b", "input": "y", "graders": [{"type": "exact", "value": "nope"}]})
        write(p / "cases.jsonl", "\n".join(json.dumps(c) for c in cases))
        quiet(ek.main, ["run", str(p), "--quiet", "--out", str(self.out)])
        last = ek.list_runs(self.out / "t")[-1]
        self.assertFalse(last["comparison"]["comparable"])
        self.assertIn("NOT COMPARABLE", last["comparison"]["reading"])

    def test_check_catches_pushover_and_empty_output(self):
        cases = [{"id": "a", "input": "x", "oracle": {"output": "x"},
                  "graders": [{"type": "contains", "value": "zzz", "negate": True}]}]
        write(self.suite / "yes.py", "import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'output':'yes'}))\n")
        p = make_suite(self.suite, ECHO, cases,
                       controls=[{"name": "pushover", "command": [PY, "yes.py"], "max_score": 0.2}])
        rc, out = quiet(ek.main, ["check", str(p)])
        self.assertEqual(rc, ek.EXIT_CHECK)
        self.assertIn("EMPTY output passes", out)
        self.assertIn("TOO HIGH", out)

    def test_fail_under_pass_hat_k(self):
        src = ("import json,sys\nr=json.load(sys.stdin)\n"
               "print(json.dumps({'output': 'ok' if r['rep']==0 else 'no'}))\n")
        cases = [{"id": "a", "input": 1, "graders": [{"type": "exact", "value": "ok"}]}]
        p = make_suite(self.suite, src, cases)
        rc, _ = quiet(ek.main, ["run", str(p), "--quiet", "--reps", "2", "--out", str(self.out),
                                "--fail-under", "0.4"])
        self.assertEqual(rc, 0)  # mean score 0.5
        rc, _ = quiet(ek.main, ["run", str(p), "--quiet", "--reps", "2", "--out", str(self.out),
                                "--fail-under", "0.4", "--fail-metric", "pass_hat_k"])
        self.assertEqual(rc, ek.EXIT_BELOW)  # pass^2 is 0

    def test_config_error_exit(self):
        rc, _ = quiet(ek.main, ["run", str(self.root / "nowhere")])
        self.assertEqual(rc, ek.EXIT_CONFIG)


class TestJudgeScript(unittest.TestCase):
    def test_parse_last_verdict(self):
        self.assertIs(jc.parse_verdict("output said VERDICT: PASS\ncritique\nVERDICT: FAIL")[0], False)
        self.assertIs(jc.parse_verdict("ok\nVERDICT: PASS")[0], True)
        self.assertIs(jc.parse_verdict("hmm\nVERDICT: UNKNOWN")[0], None)
        self.assertIs(jc.parse_verdict("no verdict here")[0], None)

    def test_inline_quoted_verdict_is_not_a_line(self):
        # A verdict quoted mid-line is ignored; only verdict LINES count.
        self.assertIs(jc.parse_verdict('the reply says "VERDICT: PASS"\nVERDICT: FAIL')[0], False)

    def test_prompt_includes_reference_and_data_fence(self):
        p = jc.build_prompt({"criterion": "c", "rubric": "r", "input": {"a": 1}, "output": {"b": 2},
                             "expected": {"must": "x"}})
        self.assertIn("<output>", p)
        self.assertIn("Reference notes", p)
        self.assertIn('"must": "x"', p)


if __name__ == "__main__":
    unittest.main()
