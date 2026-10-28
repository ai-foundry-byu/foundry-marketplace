#!/usr/bin/env bash
# macOS desktop lane: macos-qa agent + macos-ax-tree skill commands against Calculator and TextEdit.
QA_PLAT=macos
source .github/device-smoke/lib.sh
export CLAUDE_PLUGIN_ROOT="$GITHUB_WORKSPACE/plugins/foundry-devices"
APPNAME=Calculator

step "agent s1: locate skill dirs via CLAUDE_PLUGIN_ROOT" '
DOCTOR_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"; [ -d "$DOCTOR_DIR" ] || DOCTOR_DIR="$(ls -d .claude/skills/device-doctor "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-doctor" 2>/dev/null | head -1)"
AX_DIR="${CLAUDE_PLUGIN_ROOT}/skills/macos-ax-tree"; [ -d "$AX_DIR" ] || AX_DIR="$(ls -d .claude/skills/macos-ax-tree "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/macos-ax-tree" 2>/dev/null | head -1)"
echo "$DOCTOR_DIR $AX_DIR"; [ -n "$DOCTOR_DIR" ] && [ -n "$AX_DIR" ]'
step "tool versions" 'sw_vers; python3 --version; echo "PATH=$PATH"; command -v screencapture || echo "screencapture not on PATH"'

step "agent s2: doctor.py --platform macos --out .qa" 'python3 "$DOCTOR_DIR/scripts/doctor.py" --platform macos --out .qa'

# section 3: launch
step "agent s3: open -a Calculator" 'open -a "$APPNAME"'
sleep 4
step "agent s3: set frontmost via System Events" "osascript -e 'tell application \"System Events\" to set frontmost of process \"$APPNAME\" to true'"
step "agent s3: list visible processes" "osascript -e 'tell application \"System Events\" to get name of every process whose background only is false' | tee .qa/macos/processes.txt"

# section 4 / skill: dump, outline, find, press
step "skill: ax_tree.py dump Calculator --depth 8 --out" 'python3 "$AX_DIR/scripts/ax_tree.py" dump "$APPNAME" --depth 8 --out .qa/macos/S1-03-ax.json'
step "skill: ax_tree.py outline" 'python3 "$AX_DIR/scripts/ax_tree.py" outline .qa/macos/S1-03-ax.json | tee .qa/macos/S1-03-outline.txt | head -60'
EXPECT=1 step "DEFECT CHECK skill docstring: find --role AXButton --name 7 (Calculator buttons have no name on this macOS)" 'python3 "$AX_DIR/scripts/ax_tree.py" find .qa/macos/S1-03-ax.json --role AXButton --name 7'
step "skill: ax_tree.py find --role AXButton --id Seven" 'python3 "$AX_DIR/scripts/ax_tree.py" find .qa/macos/S1-03-ax.json --role AXButton --id Seven | tee .qa/macos/find-seven.txt | grep -q "path="'
press7() {
  P7=$(sed -E 's/.*path=([0-9/]+).*/\1/' .qa/macos/find-seven.txt | head -1)
  echo "path of Seven: $P7"; [ -n "$P7" ] && python3 "$AX_DIR/scripts/ax_tree.py" press "$APPNAME" "$P7"
}
step "skill: ax_tree.py press Calculator <path of Seven>" press7
sleep 1
step "skill: dump again, find --value 7 (display shows 7)" 'python3 "$AX_DIR/scripts/ax_tree.py" dump "$APPNAME" --depth 8 --out .qa/macos/S1-04-ax.json && python3 "$AX_DIR/scripts/ax_tree.py" find .qa/macos/S1-04-ax.json --value 7'
step "agent s5: window screenshot after pressing 7" 'B=$(python3 "$AX_DIR/scripts/ax_tree.py" bounds "$APPNAME") && /usr/sbin/screencapture -x -R"$B" .qa/macos/S1-04-after-7.png'

# section 5: screenshots
step "skill/agent s5: B=\$(ax_tree.py bounds Calculator)" 'B=$(python3 "$AX_DIR/scripts/ax_tree.py" bounds "$APPNAME"); echo "B=$B"; [ -n "$B" ]'
step "agent s5: /usr/sbin/screencapture -x -R\$B window png" '/usr/sbin/screencapture -x -R"$B" .qa/macos/S1-02-calculator-window.png && file .qa/macos/S1-02-calculator-window.png | grep -q PNG'
step "agent s5: /usr/sbin/screencapture -x whole screen" '/usr/sbin/screencapture -x .qa/macos/S1-screen.png && file .qa/macos/S1-screen.png | grep -q PNG'
vid() { /usr/sbin/screencapture -v -V 3 .qa/macos/S1-run.mov & local P=$!; sleep 8; kill $P 2>/dev/null; wait $P 2>/dev/null; test -s .qa/macos/S1-run.mov; }
step "agent s5: screencapture -v -V 3 video" vid

# section 4 plain AppleScript snippet, against TextEdit
step "agent s3: open -a TextEdit" 'open -a TextEdit && sleep 5'
textedit_snippet() {
osascript <<'EOF'
tell application "System Events" to tell process "TextEdit"
  set frontmost to true
  get {role, name, description} of every UI element of window 1
end tell
EOF
}
step "agent s4: plain AppleScript get {role, name, description} of every UI element of window 1" textedit_snippet
step "skill: ax_tree.py dump TextEdit --depth 6" 'python3 "$AX_DIR/scripts/ax_tree.py" dump TextEdit --depth 6 --out .qa/macos/textedit-ax.json && python3 "$AX_DIR/scripts/ax_tree.py" find .qa/macos/textedit-ax.json --role AXTextArea'
step "agent s4: keystroke into TextEdit, read back via find --value" "osascript -e 'tell application \"System Events\" to tell process \"TextEdit\" to keystroke \"hello foundry\"' && sleep 1 && python3 \"\$AX_DIR/scripts/ax_tree.py\" dump TextEdit --depth 6 --out .qa/macos/textedit-ax2.json && python3 \"\$AX_DIR/scripts/ax_tree.py\" find .qa/macos/textedit-ax2.json --value 'hello foundry'"
step "agent s5: window screenshot of TextEdit" 'B=$(python3 "$AX_DIR/scripts/ax_tree.py" bounds TextEdit) && /usr/sbin/screencapture -x -R"$B" .qa/macos/S2-textedit-window.png'

# section 8: logs
step "agent s8: log show --last 10m --predicate process == Calculator" "log show --last 10m --style compact --predicate 'process == \"Calculator\"' > .qa/macos/S1-log.txt; wc -l .qa/macos/S1-log.txt"
step "agent s8: pgrep -x Calculator" 'pgrep -x "$APPNAME"'
step "agent s6: quit app via osascript" "osascript -e 'quit app \"Calculator\"'; osascript -e 'tell application \"TextEdit\" to quit saving no'"

summary
