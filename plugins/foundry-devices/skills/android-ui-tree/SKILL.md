---
name: android-ui-tree
description: Read an Android screen's UI tree from a uiautomator dump instead of guessing tap coordinates. Outlines the meaningful nodes, finds a control by text, content-desc or resource-id, and prints a safe "adb shell input tap X Y" only when exactly one node matches. Use when driving an Android app or emulator with adb, when someone says "find the Sign in button on the Android screen", "what can I tap here", "read the uiautomator dump", or when a tap keeps hitting the wrong control.
---

# Android UI tree

Maturity: **beta** (unit-tested, including on a real API 34 Settings dump; outline, find and tap were run against an API 34 emulator in CI). Python 3 standard library only.

Get a dump from the device, then read it:

```bash
adb -s "$SERIAL" shell uiautomator dump /sdcard/ui.xml && adb -s "$SERIAL" pull /sdcard/ui.xml .qa/android/ui.xml
python3 "${CLAUDE_SKILL_DIR}/scripts/uitree.py" outline .qa/android/ui.xml
python3 "${CLAUDE_SKILL_DIR}/scripts/uitree.py" find .qa/android/ui.xml --id email
python3 "${CLAUDE_SKILL_DIR}/scripts/uitree.py" find .qa/android/ui.xml --desc "Open menu" --json
python3 "${CLAUDE_SKILL_DIR}/scripts/uitree.py" tap .qa/android/ui.xml --text "Sign in" --exact --clickable --serial "$SERIAL"
```

- `outline` prints every node with text, content-desc, resource-id or a clickable flag, plus its center point.
- `find` matches `--text` and `--desc` as case-insensitive substrings unless `--exact` is given. `--id` matches the full resource-id or the part after `:id/`.
- `--clickable` returns the node that takes the tap. In lists (Android Settings, most RecyclerView rows) the text node is not clickable but its row is, so a text match resolves to its nearest clickable ancestor and `tap` uses the row's bounds. Several matches inside one row count once.
- `tap` prints the `adb -s <serial> shell input tap X Y` command for exactly one match. It exits `2` and lists all candidates when zero or several nodes match, so a script never taps the wrong thing silently.
- The serial comes from `--serial`, else `$ANDROID_SERIAL`, else the only device `adb devices` lists. With several devices attached and no serial, `tap` exits `2` and names them.

Rules:

- Dump again after every action. Positions go stale as soon as the screen changes.
- With more than one device attached, every adb command takes `-s <serial>`.
- `uiautomator dump` fails with "could not get idle state" on screens that animate forever. Use `maestro hierarchy` there, or wait for the animation to end.
- A control with no text, no content-desc and no resource-id is an accessibility finding: TalkBack users cannot reach it either. Report it.

Used by the android-qa agent in the foundry-devices plugin, and works on its own.
