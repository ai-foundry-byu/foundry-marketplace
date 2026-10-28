"""Tests for deadman.py and run_headless.py (a fake `claude` stands in for the real CLI)."""
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "scheduled-agents", "scripts")
sys.path.insert(0, SCRIPTS)

import deadman  # noqa: E402
import run_headless  # noqa: E402


class DeadmanTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.beat = os.path.join(self.dir, "sub", "job.heartbeat.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_parse_age(self):
        self.assertEqual(deadman.parse_age("90s"), 90)
        self.assertEqual(deadman.parse_age("26h"), 26 * 3600)
        self.assertEqual(deadman.parse_age("1.5d"), 1.5 * 86400)
        with self.assertRaises(ValueError):
            deadman.parse_age("soon")

    def test_fresh_stale_missing_unreadable(self):
        now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
        deadman.write_beat(self.beat, when=now - timedelta(hours=2))
        self.assertEqual(deadman.evaluate(self.beat, 3 * 3600, now=now)[0], 0)
        self.assertEqual(deadman.evaluate(self.beat, 3600, now=now)[0], 1)
        self.assertEqual(deadman.evaluate(os.path.join(self.dir, "none.json"), 3600, now=now)[0], 2)
        with open(self.beat, "w") as fh:
            fh.write("{broken")
        self.assertEqual(deadman.evaluate(self.beat, 3600, now=now)[0], 2)

    def test_uses_content_timestamp_not_mtime(self):
        old = datetime.now(timezone.utc) - timedelta(days=3)
        deadman.write_beat(self.beat, when=old)
        os.utime(self.beat, None)  # mtime is now; content says 3 days ago
        self.assertEqual(deadman.evaluate(self.beat, 26 * 3600)[0], 1)

    def test_epoch_and_naive_timestamps(self):
        with open(self.beat.replace("sub/", ""), "w") as fh:
            json.dump({"finished_at": time.time()}, fh)
        self.assertEqual(deadman.evaluate(self.beat.replace("sub/", ""), 60)[0], 0)
        with open(self.beat.replace("sub/", ""), "w") as fh:
            json.dump({"done": "2020-01-01T00:00:00"}, fh)
        self.assertEqual(deadman.evaluate(self.beat.replace("sub/", ""), 60, key="done")[0], 1)

    def test_cli_alert_cmd_and_failed_delivery(self):
        deadman.write_beat(self.beat, when=datetime.now(timezone.utc) - timedelta(days=2))
        marker = os.path.join(self.dir, "alerted.txt")
        rc = deadman.main(["check", "--file", self.beat, "--max-age", "1h",
                           "--alert-cmd", f'printf "%s" "$DEADMAN_MESSAGE" > "{marker}"'])
        self.assertEqual(rc, 1)
        with open(marker) as fh:
            self.assertIn("STALE", fh.read())
        rc = deadman.main(["check", "--file", self.beat, "--max-age", "1h", "--alert-cmd", "exit 7"])
        self.assertEqual(rc, 3)  # stale AND nobody was told
        self.assertEqual(deadman.main(["check", "--file", self.beat, "--max-age", "5d"]), 0)

    def run_cli(self, *args):
        import subprocess
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "deadman.py"), *args],
                              capture_output=True, text=True)

    def test_no_alert_channel_is_loud_and_leaves_an_alert_file(self):
        # L6-D8: stale/missing with no channel (or an EMPTY --webhook from an unset env var under cron)
        # must not look like a delivered alert.
        missing = os.path.join(self.dir, "jobs", "digest.heartbeat.json")
        for extra in ([], ["--webhook", ""], ["--webhook", "  "]):
            res = self.run_cli("check", "--name", "digest", "--file", missing, "--max-age", "1h", *extra)
            self.assertEqual(res.returncode, 3, (extra, res.stdout, res.stderr))
            self.assertIn("NO ALERT CHANNEL", res.stderr)
            alert = os.path.join(self.dir, "jobs", "digest.DEADMAN-ALERT.txt")
            self.assertTrue(os.path.exists(alert), extra)
            with open(alert) as fh:
                self.assertIn("heartbeat missing", fh.read())

    def test_alert_file_written_on_stale_and_removed_when_fresh(self):
        deadman.write_beat(self.beat, when=datetime.now(timezone.utc) - timedelta(days=2))
        alert = os.path.join(os.path.dirname(self.beat), "job.DEADMAN-ALERT.txt")
        rc = deadman.main(["check", "--file", self.beat, "--max-age", "1h", "--alert-cmd", "true"])
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.exists(alert))
        deadman.write_beat(self.beat)
        self.assertEqual(deadman.main(["check", "--file", self.beat, "--max-age", "1h"]), 0)
        self.assertFalse(os.path.exists(alert))

    def test_webhook_file_is_read_and_empty_file_counts_as_no_channel(self):
        url_file = os.path.join(self.dir, "webhook.url")
        with open(url_file, "w") as fh:
            fh.write("\n")
        missing = os.path.join(self.dir, "none.heartbeat.json")
        self.assertEqual(deadman.main(["check", "--file", missing, "--max-age", "1h", "--webhook-file", url_file]), 3)
        with open(url_file, "w") as fh:
            fh.write("https://hooks.example.invalid/abc\n")
        sent = []
        orig = deadman.send_webhook
        deadman.send_webhook = lambda url, msg, timeout=15.0: sent.append(url) or True
        try:
            rc = deadman.main(["check", "--file", missing, "--max-age", "1h", "--webhook-file", url_file])
        finally:
            deadman.send_webhook = orig
        self.assertEqual(rc, 2)
        self.assertEqual(sent, ["https://hooks.example.invalid/abc"])


FAKE_CLAUDE = """#!{py}
import json, os, sys, time
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "ok":
    print(json.dumps({{"type": "result", "is_error": False, "result": "TRIAGED 3"}}))
elif mode == "error":
    print(json.dumps({{"type": "result", "is_error": True, "subtype": "error_max_turns", "result": ""}}))
elif mode == "empty":
    print(json.dumps({{"type": "result", "is_error": False, "result": "  "}}))
elif mode == "crash":
    sys.exit(3)
elif mode == "hang":
    time.sleep(30)
with open(os.environ["FAKE_ARGV_FILE"], "w") as fh:
    json.dump(sys.argv[1:], fh)
"""


class RunHeadlessTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.claude = os.path.join(self.dir, "claude")
        with open(self.claude, "w") as fh:
            fh.write(FAKE_CLAUDE.format(py=sys.executable))
        os.chmod(self.claude, os.stat(self.claude).st_mode | stat.S_IEXEC)
        self.argv_file = os.path.join(self.dir, "argv.json")
        os.environ["FAKE_ARGV_FILE"] = self.argv_file
        self.beat = os.path.join(self.dir, ".agent-jobs", "job.heartbeat.json")

    def tearDown(self):
        os.environ.pop("FAKE_MODE", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_job(self, mode, minutes="1", extra=()):
        os.environ["FAKE_MODE"] = mode
        return run_headless.main(["--name", "job", "--prompt", "do it", "--workdir", self.dir,
                                  "--claude-bin", self.claude, "--max-minutes", minutes, "--", *extra])

    def test_success_writes_heartbeat_and_passes_args(self):
        self.assertEqual(self.run_job("ok", extra=["--max-turns", "5"]), 0)
        with open(self.beat) as fh:
            self.assertEqual(json.load(fh)["detail"], "TRIAGED 3")
        with open(self.argv_file) as fh:
            argv = json.load(fh)
        self.assertEqual(argv[:4], ["-p", "do it", "--output-format", "json"])
        self.assertEqual(argv[-2:], ["--max-turns", "5"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".agent-jobs", "job.lock")))
        self.assertTrue(os.listdir(os.path.join(self.dir, ".agent-jobs", "logs")))

    def test_failures_never_write_heartbeat(self):
        for mode in ("error", "empty", "crash"):
            self.assertEqual(self.run_job(mode), 1, mode)
            self.assertFalse(os.path.exists(self.beat), mode)

    def test_timeout(self):
        self.assertEqual(self.run_job("hang", minutes="0.02"), 5)
        self.assertFalse(os.path.exists(self.beat))

    def test_lock_prevents_overlap_and_stale_lock_is_cleared(self):
        lock = os.path.join(self.dir, ".agent-jobs", "job.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, "w") as fh:
            fh.write("999 0\n")
        self.assertEqual(self.run_job("ok"), 4)
        old = time.time() - 3600
        os.utime(lock, (old, old))
        self.assertEqual(self.run_job("ok"), 0)

    def test_missing_binary(self):
        rc = run_headless.main(["--name", "j", "--prompt", "x", "--workdir", self.dir,
                                "--claude-bin", "definitely-not-a-real-binary-xyz"])
        self.assertEqual(rc, 6)

    def test_judge_list_output(self):
        events = [{"type": "system"}, {"type": "result", "is_error": False, "result": "done"}]
        self.assertEqual(run_headless.judge(0, json.dumps(events)), (True, "done"))


class SchedulerTemplateTests(unittest.TestCase):
    """L6-D13: every scheduler template ships the deadman too, with a channel that works under the scheduler."""
    TEMPLATES = os.path.join(os.path.dirname(SCRIPTS), "templates")

    def read(self, name):
        with open(os.path.join(self.TEMPLATES, name)) as fh:
            return fh.read()

    def test_launchd_deadman_plist(self):
        import plistlib
        with open(os.path.join(self.TEMPLATES, "launchd-deadman.plist"), "rb") as fh:
            plist = plistlib.load(fh)
        args = plist["ProgramArguments"]
        self.assertTrue(args[1].endswith("deadman.py"))
        self.assertIn("check", args)
        self.assertIn("--webhook-file", args)
        self.assertIn("StartCalendarInterval", plist)
        self.assertNotIn("$", " ".join(args))  # launchd expands nothing

    def test_no_template_relies_on_shell_env_for_the_alert(self):
        for name in ("crontab.txt", "launchd.plist", "launchd-deadman.plist", "task-scheduler.ps1"):
            self.assertIsNone(re.search(r'--webhook\s+"?\$\{?ALERT_WEBHOOK_URL', self.read(name)), name)
        cron = [ln for ln in self.read("crontab.txt").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertEqual(len(cron), 2)
        self.assertIn("deadman.py\" check", cron[1])
        self.assertIn("--webhook-file", cron[1])
        self.assertIn("daily-digest-deadman", self.read("task-scheduler.ps1"))


if __name__ == "__main__":
    unittest.main()
