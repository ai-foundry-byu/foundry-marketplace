#!/usr/bin/env bash
# Windows lane, Git Bash half: windows-qa install line, doctor (Git Bash lookup verbatim), drive loop.
QA_PLAT=windows
source .github/device-smoke/lib.sh
export CLAUDE_PLUGIN_ROOT="$GITHUB_WORKSPACE/plugins/foundry-devices"

step "tool versions" 'py --version; py -0p; python --version; uname -a'
step "agent s2 fix: py -m pip install pywinauto pillow" 'py -m pip install pywinauto pillow'
step "agent s2 (Git Bash): SKILL_DIR lookup + py -3 doctor.py --platform windows --out .qa" '
SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"; [ -d "$SKILL_DIR" ] || SKILL_DIR="$(ls -d .claude/skills/device-doctor "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-doctor" 2>/dev/null | head -1)"
echo "SKILL_DIR=$SKILL_DIR"
py -3 "$SKILL_DIR/scripts/doctor.py" --platform windows --out .qa'
step "doctor.json written at .qa/windows/doctor.json" 'test -s .qa/windows/doctor.json && cat .qa/windows/doctor.json'
step "skill (windows form): py -3 \"<skill dir>\\scripts\\doctor.py\" --platform windows --json" 'py -3 "$(cygpath -w "$SKILL_DIR")\scripts\doctor.py" --platform windows --json > .qa/windows/doctor-skill-form.json; tail -3 .qa/windows/doctor-skill-form.json'
step "pywinauto version" 'py -3 -c "import pywinauto,PIL;print(pywinauto.__version__, PIL.__version__)"'
step "agent s3-s6: drive loop on Notepad (windows_drive.py)" 'py -3 .github/device-smoke/windows_drive.py'
summary
