#!/usr/bin/env python3
"""Preflight checks for a device QA lane.

Usage:
    doctor.py --platform ios|android|windows|macos [--out .qa] [--json]

Checks that the host OS matches the platform and that the tools the agent
needs are installed and respond. Every external command runs with a timeout,
because some tools (for example `xcrun simctl` on a machine whose Xcode
license or first-launch setup is pending) can hang forever instead of failing.

Writes <out>/<platform>/doctor.json and prints a readable table.
Exit code: 0 if every REQUIRED check passed, 1 otherwise.
Python 3 stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform as _platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

TIMEOUT_S = 20

# The installer only edits ~/.bashrc and ~/.zshrc, so the shell that ran it (an agent's
# Bash tool included) does not see maestro until PATH is exported.
MAESTRO_FIX = ('Install: curl -fsSL "https://get.maestro.mobile.dev" | bash, then in the same shell: '
               'export PATH="$PATH:$HOME/.maestro/bin"  and check: maestro --version  (needs Java 17+)')


@dataclass
class Check:
    name: str
    required: bool
    ok: bool = False
    detail: str = ""
    fix: str = ""
    probed: bool = True     # False: the doctor cannot check this; state is unknown, never OK


@dataclass
class Report:
    platform: str
    host_os: str
    checked_at: str
    checks: list = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks if c.required)


def run(cmd: list[str], timeout: int = TIMEOUT_S) -> tuple[bool, str]:
    """Run a command; return (ok, first line of output or the error)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "not found"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s (tool is hanging; see fix)"
    out = (p.stdout or p.stderr or "").strip().splitlines()
    first = out[0] if out else ""
    return p.returncode == 0, first


def which_check(name: str, binary: str, required: bool, fix: str,
                version_args: list[str] | None = None) -> Check:
    c = Check(name=name, required=required, fix=fix)
    path = shutil.which(binary)
    if not path:
        c.detail = f"{binary} not on PATH"
        return c
    if version_args is None:
        c.ok, c.detail = True, path
        return c
    ok, line = run([path] + version_args)
    c.ok = ok
    c.detail = f"{path}: {line}" if line else path
    return c


def host_os() -> str:
    s = sys.platform
    if s == "darwin":
        return "macos"
    if s.startswith("win"):
        return "windows"
    if s.startswith("linux"):
        try:
            with open("/proc/version", encoding="utf-8") as fh:
                if "microsoft" in fh.read().lower():
                    return "wsl"
        except OSError:
            pass
        return "linux"
    return s


def os_check(want: set[str], label: str) -> Check:
    got = host_os()
    c = Check(name=f"host OS is {label}", required=True, detail=got)
    c.ok = got in want
    if got == "wsl" and "windows" in want:
        c.fix = ("You are inside WSL. UI Automation only works from native "
                 "Windows Python. Run this lane from PowerShell or cmd.")
    elif not c.ok:
        c.fix = f"This lane needs a {label} host. Run it on that machine or skip the lane."
    return c


def checks_ios() -> list[Check]:
    cs = [os_check({"macos"}, "macOS")]
    cs.append(which_check("Xcode command line tools", "xcrun", True,
                          "Install Xcode from the App Store, then run: sudo xcode-select -s /Applications/Xcode.app",
                          ["--version"]))
    c = Check(name="xcrun simctl responds", required=True,
              fix=("Open Xcode once to finish first-launch setup and accept the license "
                   "(sudo xcodebuild -license accept), and install an iOS Simulator runtime "
                   "in Xcode > Settings > Components."))
    if shutil.which("xcrun"):
        c.ok, c.detail = run(["xcrun", "simctl", "list", "runtimes"])
    else:
        c.detail = "xcrun missing"
    cs.append(c)
    cs.append(which_check("xcodebuild (needed to build the app or run XCUITest)", "xcodebuild", False,
                          "Comes with Xcode.", ["-version"]))
    cs.append(which_check("maestro (taps, asserts, UI tree)", "maestro", True,
                          MAESTRO_FIX, ["--version"]))
    cs.append(which_check("java (Maestro runtime)", "java", True,
                          "Install a JDK 17 or newer, for example: brew install openjdk@17",
                          ["-version"]))
    return cs


def checks_android() -> list[Check]:
    cs = [Check(name="host OS supports the Android emulator", required=True,
                ok=host_os() in {"macos", "linux", "windows"}, detail=host_os(),
                fix="Run on macOS, Linux or native Windows. Nested virtualization in WSL is unreliable.")]
    cs.append(which_check("adb", "adb", True,
                          "Install Android SDK platform-tools (Android Studio > SDK Manager, or "
                          "sdkmanager \"platform-tools\") and put $ANDROID_HOME/platform-tools on PATH.",
                          ["version"]))
    cs.append(which_check("emulator", "emulator", False,
                          "sdkmanager \"emulator\", then add $ANDROID_HOME/emulator to PATH. Not needed for a real device.",
                          ["-version"]))
    cs.append(which_check("avdmanager", "avdmanager", False,
                          "Install Android SDK cmdline-tools and add $ANDROID_HOME/cmdline-tools/latest/bin to PATH."))
    c = Check(name="a device or emulator is attached", required=True,
              fix="Start an emulator (emulator -avd <name>) or plug in a device with USB debugging on, then: adb devices")
    if shutil.which("adb"):
        try:
            out = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                                 timeout=TIMEOUT_S).stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            out = ""
        devices = parse_adb_devices(out)
        c.ok = any(state == "device" for _, state in devices)
        c.detail = ", ".join(f"{s}:{st}" for s, st in devices) or "none"
    else:
        c.detail = "adb missing"
    cs.append(c)
    cs.append(which_check("maestro (optional flow runner)", "maestro", False,
                          MAESTRO_FIX, ["--version"]))
    return cs


def parse_adb_devices(text: str) -> list[tuple[str, str]]:
    """Parse `adb devices` output into (serial, state) pairs."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def checks_windows() -> list[Check]:
    cs = [os_check({"windows"}, "native Windows")]
    for mod, req, fix in [
        ("pywinauto", True, "py -m pip install pywinauto"),
        ("PIL", False, "py -m pip install pillow  (for ImageGrab screenshots)"),
    ]:
        c = Check(name=f"python module {mod}", required=req, fix=fix)
        try:
            __import__(mod)
            c.ok, c.detail = True, "importable"
        except Exception as e:  # noqa: BLE001 - report any import failure
            c.detail = f"{type(e).__name__}: {e}"
        cs.append(c)
    cs.append(which_check("powershell (fallback screenshots)", "powershell", False,
                          "Ships with Windows."))
    return cs


def checks_macos() -> list[Check]:
    cs = [os_check({"macos"}, "macOS")]
    cs.append(which_check("osascript", "osascript", True, "Ships with macOS."))
    sc = which_check("screencapture", "screencapture", True,
                     "Ships with macOS at /usr/sbin/screencapture. Add /usr/sbin to PATH or call it by full path.")
    if not sc.ok and os.path.exists("/usr/sbin/screencapture"):
        sc.ok, sc.detail = True, "/usr/sbin/screencapture (not on PATH: call it by full path)"
    cs.append(sc)
    c = Check(name="Accessibility permission for this terminal", required=True,
              fix=("System Settings > Privacy & Security > Accessibility: enable the app that "
                   "runs Claude Code (Terminal, iTerm, your IDE). Restart that app afterwards. "
                   "Error -25211, or a timeout while a permission prompt waits on screen, means this permission is missing."))
    if shutil.which("osascript"):
        c.ok, c.detail = run(["osascript", "-e",
                              'tell application "System Events" to count UI elements of '
                              '(first process whose frontmost is true)'])
    else:
        c.detail = "osascript missing"
    cs.append(c)
    cs.append(screen_recording_check())
    cs.append(which_check("cliclick (optional coordinate clicks)", "cliclick", False,
                          "brew install cliclick"))
    cs.append(which_check("node (optional, Playwright for Electron apps)", "node", False,
                          "Install Node 18+, then: npm i -D playwright", ["--version"]))
    return cs


def screen_recording_check() -> Check:
    """Screen Recording cannot be probed reliably from a script, so report it as unknown."""
    return Check(name="Screen Recording permission", required=False, ok=False, probed=False,
                 detail=("not probed: if screenshots show only the wallpaper and menu bar, "
                         "this permission is missing"),
                 fix="System Settings > Privacy & Security > Screen & System Audio Recording: enable the same app.")


PLATFORMS = {
    "ios": checks_ios,
    "android": checks_android,
    "windows": checks_windows,
    "macos": checks_macos,
}


def render(rep: Report) -> str:
    lines = [f"doctor: {rep.platform} on {rep.host_os} ({rep.checked_at})"]
    for c in rep.checks:
        if not c.probed:
            mark = "??  "
        else:
            mark = "OK  " if c.ok else ("FAIL" if c.required else "warn")
        req = "required" if c.required else "optional"
        lines.append(f"  [{mark}] {c.name} ({req}): {c.detail}")
        if not c.ok and c.fix:
            lines.append(f"         fix: {c.fix}")
    lines.append("READY" if rep.ready else "NOT READY: fix the FAIL rows before driving the app")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--out", default=".qa", help="evidence root (default .qa)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = ap.parse_args(argv)

    rep = Report(platform=a.platform, host_os=host_os(),
                 checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 checks=PLATFORMS[a.platform]())
    data = asdict(rep)
    data["ready"] = rep.ready
    data["python"] = _platform.python_version()
    outdir = os.path.join(a.out, a.platform)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "doctor.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(json.dumps(data, indent=2) if a.json else render(rep))
    return 0 if rep.ready else 1


if __name__ == "__main__":
    sys.exit(main())
