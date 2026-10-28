"""Shared helpers for the foundry-iphone-mirror tests. Nothing here touches a phone,
a window, or a TCC grant: geometry is faked and cliclick is replaced by a recorder."""
import os
import stat
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(ROOT, "engine", "worker.sh")
CLI = os.path.join(ROOT, "bin", "iphone-mirror")
SERVER = os.path.join(ROOT, "mcp", "server.py")


def read(path):
    with open(path) as f:
        return f.read()


def write_exe(path, body):
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Sandbox:
    """A temp state dir plus a fake cliclick that appends its argv to a log."""

    def __init__(self, geometry="100 50 300 600"):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.state = os.path.join(self.dir, "state")
        os.makedirs(self.state)
        self.click_log = os.path.join(self.dir, "clicks.log")
        self.cliclick = write_exe(os.path.join(self.dir, "cliclick"),
                                  f'#!/bin/bash\necho "$@" >> "{self.click_log}"\n')
        self.env = dict(os.environ)
        self.env.update({
            "IPHONE_MIRROR_STATE": self.state,
            "IPHONE_MIRROR_CLICLICK": self.cliclick,
            "IPHONE_MIRROR_FAKE_GEOMETRY": geometry,
            "IPHONE_MIRROR_TIMEOUT": "5",
            "HOME": self.dir,  # keep the CLI away from the real ~/Library
        })

    def clicks(self):
        if not os.path.exists(self.click_log):
            return []
        with open(self.click_log) as f:
            return [line.strip() for line in f if line.strip()]

    def record_shot(self, w, h):
        """Pretend `shot` ran: append the image size the way the worker does."""
        with open(os.path.join(self.state, "geom.env"), "a") as f:
            f.write(f"IMG=/x.png\nIMGW={w}\nIMGH={h}\n")

    def close(self):
        self.tmp.cleanup()


def run_worker(sb, *args):
    """Run worker.sh directly; return (rc, result-file text)."""
    p = subprocess.run(["/bin/bash", WORKER, *args], env=sb.env, capture_output=True, text=True, timeout=20)
    result_path = os.path.join(sb.state, "result")
    text = read(result_path).strip() if os.path.exists(result_path) else ""
    return p.returncode, text


def run_cli(sb, *args, direct=True):
    env = dict(sb.env)
    if direct:
        env["IPHONE_MIRROR_WORKER_DIRECT"] = WORKER
    p = subprocess.run([CLI, *args], env=env, capture_output=True, text=True, timeout=30)
    return p.returncode, (p.stdout + p.stderr).strip()
