---
name: device-doctor
description: Preflight a device QA lane before testing anything. Checks that the host OS matches the platform (ios, android, windows, macos) and that the tools the lane needs (xcrun simctl, adb, emulator, Maestro, pywinauto, osascript, screencapture, Accessibility permission) are installed and actually respond, with a timeout on every call. Writes .qa/<platform>/doctor.json and prints READY or the exact fixes. Use when someone says "is my machine ready to test iOS/Android/Windows/macOS", "run the device doctor", "why won't the simulator start", or before any ios-qa, android-qa, windows-qa or macos-qa run.
---

# Device doctor

One command per platform. It never installs or changes anything; it only checks and tells you the fix.

Maturity: **new** (unit-tested; run on real Android API 34, iOS 26.2 simulator, Windows Server 2025 and macOS 26 CI runners).

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/doctor.py" --platform ios --out .qa       # or android, windows, macos
python3 "${CLAUDE_SKILL_DIR}/scripts/doctor.py" --platform android --json      # machine-readable
```

On Windows, run it with native Windows Python (not WSL): `py -3 "<skill dir>\scripts\doctor.py" --platform windows --out .qa`.

What it checks:

| platform | required | optional |
|---|---|---|
| `ios` | macOS host, `xcrun`, `xcrun simctl` answers within 20 s (it hangs when the Xcode license or first-launch setup is pending), `maestro`, `java` (Maestro runtime) | `xcodebuild` (to build the app or run XCUITest) |
| `android` | a host OS that runs the emulator, `adb`, an attached device in state `device` | `emulator`, `avdmanager`, `maestro` |
| `windows` | native Windows (flags WSL), `pywinauto` | Pillow, PowerShell |
| `macos` | macOS host, `osascript`, `screencapture` (in `/usr/sbin`), Accessibility permission for the app running Claude Code | Screen Recording (reported, not probed), `cliclick`, Node |

Exit code `0` when every required check passed (READY), `1` otherwise (NOT READY). It writes `<out>/<platform>/doctor.json` with one row per check and its fix line. Rows print as `OK`, `FAIL` (required) or `warn` (optional). A row the doctor cannot check prints `??` with `"probed": false` and `"ok": false` in the JSON: today that is only macOS Screen Recording. Treat it as unknown, never as granted.

Only `doctor.py` writes `doctor.json`. Do not write or edit it by hand: the device-matrix report and the agents read its format.

If it says NOT READY, stop and report the FAIL rows with their fix lines. Do not start testing on a machine the doctor rejected: the run will end INCONCLUSIVE anyway, after wasting time.

Used by the ios-qa, android-qa, windows-qa and macos-qa agents in the foundry-devices plugin, and works on its own.
