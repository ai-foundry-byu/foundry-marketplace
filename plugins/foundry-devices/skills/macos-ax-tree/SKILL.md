---
name: macos-ax-tree
description: Read and act on a macOS app's accessibility tree through System Events instead of guessing click coordinates. Dumps the tree to JSON, outlines it, finds elements by role, name, description, value or identifier, presses one with AXPress, and prints a window's bounds for screencapture -R. Use when driving a Mac desktop app (AppKit, SwiftUI, Catalyst, Electron), when someone says "what buttons does this Mac app have", "press Sign In in the Mac app", "dump the accessibility tree", or "screenshot just the app window".
---

# macOS accessibility tree

Maturity: **new** (parsing unit-tested; dump, find, press and bounds were run against Calculator and TextEdit on a macOS 26 CI runner; the live calls need a Mac). Python 3 standard library only; it shells out to `osascript`.

Needs Accessibility permission for the app that runs Claude Code (Terminal, iTerm, VS Code): System Settings > Privacy & Security > Accessibility, then quit and reopen that app. Without it, System Events calls fail with `-25211` or hang on a permission prompt.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ax_tree.py" dump "<YourApp>" --depth 8 --out .qa/macos/ax.json
python3 "${CLAUDE_SKILL_DIR}/scripts/ax_tree.py" outline .qa/macos/ax.json
python3 "${CLAUDE_SKILL_DIR}/scripts/ax_tree.py" find .qa/macos/ax.json --role AXButton --name "Sign In"
python3 "${CLAUDE_SKILL_DIR}/scripts/ax_tree.py" find .qa/macos/ax.json --role AXButton --id Seven   # Calculator's 7 key
python3 "${CLAUDE_SKILL_DIR}/scripts/ax_tree.py" press "<YourApp>" <path printed by find>      # AXPress that element
B=$(python3 "${CLAUDE_SKILL_DIR}/scripts/ax_tree.py" bounds "<YourApp>")      # x,y,w,h of window 1
/usr/sbin/screencapture -x -R"$B" .qa/macos/window.png
```

- A path is the window number followed by 1-based child indexes, exactly as `dump` prints it. Paths go stale whenever the UI changes, so dump again after each action.
- `find` matches `--name`, `--desc`, `--value` and `--id` as case-insensitive substrings and `--role` exactly.
- Many apps, SwiftUI ones especially, expose an identifier but no name. Current Calculator's keys have no name, the description `button` and identifiers like `Seven` or `Equals`, so `--name 7` finds nothing and `--id Seven` finds the key. When `--name` comes back empty, `find` says so and suggests `--id`.
- A deep dump of a big window can take tens of seconds. Start with a low `--depth` and go deeper only where needed.
- Prefer `press` on a specific element over keystrokes: keystrokes go to whatever app is frontmost.
- A control with no name, description or identifier is an accessibility finding: VoiceOver users cannot reach it either. Report it.

Used by the macos-qa agent in the foundry-devices plugin, and works on its own.
