#!/usr/bin/env python3
"""deadman.py: heartbeats for scheduled jobs, and the check that notices when they stop.

A scheduled job that silently stops running looks exactly like one that has nothing
to report. The fix is two halves that never share a failure:

  1. The job writes a heartbeat ONLY when it truly succeeded:
       deadman.py beat --file state/digest.heartbeat.json --detail "12 items"
  2. A separate schedule checks that heartbeat's CONTENT timestamp:
       deadman.py check --file state/digest.heartbeat.json --max-age 26h \
           --webhook "$ALERT_WEBHOOK_URL"

The check reads the timestamp written inside the file, not the file's mtime
(a `cp` or a restore can refresh mtime on a dead job).

Exit codes for `check`: 0 fresh, 1 stale, 2 missing or unreadable, 3 alert delivery failed.
Ages: 90s, 45m, 26h, 7d.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$")
UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_age(text: str) -> float:
    m = AGE_RE.match(text)
    if not m:
        raise ValueError(f"bad age {text!r}; use forms like 90s, 45m, 26h, 7d")
    return float(m.group(1)) * UNIT[m.group(2)]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def write_beat(path: str, status: str = "ok", detail: str = "", when: datetime | None = None) -> dict:
    when = when or now_utc()
    record = {"finished_at": when.isoformat(timespec="seconds"), "status": status, "detail": detail}
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".beat-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    os.replace(tmp, path)  # atomic: a reader never sees half a file
    return record


def read_beat_time(path: str, key: str = "finished_at") -> datetime:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    raw = data[key]
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def evaluate(path: str, max_age_s: float, key: str = "finished_at", now: datetime | None = None) -> tuple[int, str]:
    now = now or now_utc()
    if not os.path.exists(path):
        return 2, f"heartbeat missing: {path}"
    try:
        ts = read_beat_time(path, key)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return 2, f"heartbeat unreadable: {path} ({type(exc).__name__}: {exc})"
    age = (now - ts).total_seconds()
    if age > max_age_s:
        return 1, f"STALE: {path} last success {ts.isoformat()} ({age / 3600:.1f}h ago, limit {max_age_s / 3600:.1f}h)"
    return 0, f"fresh: {path} last success {ts.isoformat()} ({age / 3600:.1f}h ago)"


def send_webhook(url: str, message: str, timeout: float = 15.0) -> bool:
    """POST a message that Slack ("text") and Discord ("content") both accept. True only on 2xx."""
    body = json.dumps({"text": message, "content": message}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Heartbeat writer and deadman check for scheduled jobs.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("beat", help="record a successful run")
    b.add_argument("--file", required=True)
    b.add_argument("--status", default="ok")
    b.add_argument("--detail", default="")

    c = sub.add_parser("check", help="alert if the last success is too old")
    c.add_argument("--file", required=True)
    c.add_argument("--max-age", required=True, help="e.g. 26h for a daily job (about 1x period + slack)")
    c.add_argument("--key", default="finished_at", help="JSON key holding the timestamp")
    c.add_argument("--name", default=None, help="job name used in the alert text")
    c.add_argument("--webhook", default=None, help="Slack/Discord-style incoming webhook URL")
    c.add_argument("--alert-cmd", default=None, help="shell command to run when stale; message in $DEADMAN_MESSAGE")
    a = ap.parse_args(argv)

    if a.cmd == "beat":
        rec = write_beat(a.file, a.status, a.detail)
        print(f"beat: {a.file} {rec['finished_at']}")
        return 0

    try:
        max_age = parse_age(a.max_age)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    code, msg = evaluate(a.file, max_age, a.key)
    print(msg)
    if code == 0:
        return 0
    text = f"[deadman] {a.name or os.path.basename(a.file)}: {msg}"
    delivered = True
    if a.webhook:
        delivered = send_webhook(a.webhook, text) and delivered
    if a.alert_cmd:
        env = {**os.environ, "DEADMAN_MESSAGE": text}
        delivered = subprocess.run(a.alert_cmd, shell=True, env=env).returncode == 0 and delivered
    if not delivered:
        print("deadman: ALERT DELIVERY FAILED; the job is stale and nobody was told", file=sys.stderr)
        return 3
    return code


if __name__ == "__main__":
    sys.exit(main())
