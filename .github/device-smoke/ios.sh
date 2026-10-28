#!/usr/bin/env bash
# iOS lane: runs the ios-qa agent's own commands against a fresh simulator and the Settings app.
QA_PLAT=ios
source .github/device-smoke/lib.sh
export CLAUDE_PLUGIN_ROOT="$GITHUB_WORKSPACE/plugins/foundry-devices"
BUNDLE=com.apple.Preferences

# ios-qa section 1 (verbatim)
step "agent s1: locate skill dirs via CLAUDE_PLUGIN_ROOT" '
DOCTOR_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"; [ -d "$DOCTOR_DIR" ] || DOCTOR_DIR="$(ls -d .claude/skills/device-doctor "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-doctor" 2>/dev/null | head -1)"
MATRIX_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-matrix"; [ -d "$MATRIX_DIR" ] || MATRIX_DIR="$(ls -d .claude/skills/device-matrix "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-matrix" 2>/dev/null | head -1)"
echo "$DOCTOR_DIR $MATRIX_DIR"; [ -n "$DOCTOR_DIR" ] && [ -n "$MATRIX_DIR" ]'

# Fallback path of the same snippet: plugin root unset, skill copied to .claude/skills (standalone install)
fallback_lookup() {
  mkdir -p .claude/skills && cp -R "$CLAUDE_PLUGIN_ROOT/skills/device-doctor" .claude/skills/
  local D
  D=$(CLAUDE_PLUGIN_ROOT= bash -c 'DOCTOR_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"; [ -d "$DOCTOR_DIR" ] || DOCTOR_DIR="$(ls -d .claude/skills/device-doctor "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-doctor" 2>/dev/null | head -1)"; echo "$DOCTOR_DIR"')
  echo "fallback DOCTOR_DIR=$D"; rm -rf .claude
  [ "$D" = ".claude/skills/device-doctor" ]
}
step "agent s1: fallback lookup finds .claude/skills/device-doctor when plugin root unset" fallback_lookup

step "tool versions" 'sw_vers; xcodebuild -version; xcrun simctl help | head -3; java -version 2>&1 | head -1'

# section 2: doctor (Maestro not installed yet: expect NOT READY with the Maestro fix line)
EXPECT=1 step "agent s2: doctor.py --platform ios before Maestro install (expect NOT READY)" 'python3 "$DOCTOR_DIR/scripts/doctor.py" --platform ios --out .qa'
step "agent s2: xcrun simctl list runtimes" 'xcrun simctl list runtimes | tee .qa/ios/runtimes.txt | grep -q iOS'
step "agent s2: xcrun simctl list devices available" 'xcrun simctl list devices available > .qa/ios/devices.txt; head -20 .qa/ios/devices.txt'

# section 3
pick() {
  xcrun simctl list devicetypes | grep -i iphone | tail -5
  read -r RUNTIME DEVTYPE < <(xcrun simctl list runtimes -j | python3 -c 'import json,sys
r=[x for x in json.load(sys.stdin)["runtimes"] if x.get("platform")=="iOS" and x.get("isAvailable")]
rt=r[-1]; names=[d["name"] for d in rt.get("supportedDeviceTypes",[]) if d["name"].startswith("iPhone")]
plain=sorted([n for n in names if n.replace("iPhone ","").isdigit()], key=lambda n: int(n.split()[1]))
print(rt["identifier"], (plain or names)[-1].replace(" ","_"))')
  DEVTYPE=${DEVTYPE//_/ }
  echo "RUNTIME=$RUNTIME DEVTYPE=$DEVTYPE"; [ -n "$RUNTIME" ] && [ -n "$DEVTYPE" ]
}
step "agent s3: xcrun simctl list devicetypes | grep -i iphone; pick runtime" pick
step "agent s3: UDID=\$(xcrun simctl create \"QA iPhone\" <type> <runtime>)" 'UDID=$(xcrun simctl create "QA iPhone" "$DEVTYPE" "$RUNTIME"); echo "UDID=$UDID"; [ -n "$UDID" ]'
step "agent s3: xcrun simctl boot UDID" 'xcrun simctl boot "$UDID"'
step "agent s3: xcrun simctl bootstatus UDID -b" 'xcrun simctl bootstatus "$UDID" -b'
step "agent s3: status_bar override (exact flags)" 'xcrun simctl status_bar "$UDID" override --time "9:41" --batteryState charged --batteryLevel 100 --dataNetwork wifi --wifiMode active --wifiBars 3 --cellularMode active --cellularBars 4'
step "agent s3: simctl ui appearance light" 'xcrun simctl ui "$UDID" appearance light'

# section 4: device controls (system app as the app under test)
step "agent s4: simctl launch UDID BUNDLE" 'xcrun simctl launch "$UDID" "$BUNDLE"'
sleep 5
step "agent s6: simctl io screenshot --type=png" 'xcrun simctl io "$UDID" screenshot --type=png .qa/ios/S1-01-settings.png && file .qa/ios/S1-01-settings.png | grep -q PNG'
openurl_retry() {
  # First boot of a fresh simulator runs data migration; openurl can time out (code=60) until it settles. [ENV]
  for i in 1 2 3; do xcrun simctl openurl "$UDID" "https://example.com" && return 0; echo "openurl attempt $i failed, waiting 30 s"; sleep 30; done; return 1
}
step "agent s4: simctl openurl https://example.com (Safari), up to 3 tries" openurl_retry
sleep 8
step "agent s6: screenshot after openurl" 'xcrun simctl io "$UDID" screenshot --type=png .qa/ios/S1-02-openurl.png'
step "agent s4: simctl help privacy lists services" 'xcrun simctl help privacy 2>&1 | tee .qa/ios/privacy-help.txt | grep -qi photos'
step "agent s4: simctl privacy grant photos BUNDLE" 'xcrun simctl privacy "$UDID" grant photos "$BUNDLE"'
step "agent s4: simctl terminate UDID BUNDLE (after a fresh launch)" 'xcrun simctl launch "$UDID" "$BUNDLE" && sleep 3 && xcrun simctl terminate "$UDID" "$BUNDLE"'
step "agent s4: simctl addmedia (a png)" 'xcrun simctl addmedia "$UDID" .qa/ios/S1-01-settings.png'
step "agent s4: simctl get_app_container data (system app)" 'xcrun simctl get_app_container "$UDID" "$BUNDLE" data'
alive_for() { local pid=$1 n=$2; for i in $(seq "$n"); do kill -0 "$pid" 2>/dev/null || return 1; sleep 1; done; return 0; }
# FIXED D4: the ios-qa section 6 ad hoc screenshot + video block, extracted verbatim from the agent
# file. The "# ... drive the story ..." line is replaced by a Settings launch and 3 s of screen time.
MD=.github/device-smoke/mdblock.py
AGENT_MD="$CLAUDE_PLUGIN_ROOT/agents/ios-qa.md"
REC_BLOCK=$(python3 -I "$MD" "$AGENT_MD" bash recordVideo)
REC_BLOCK=${REC_BLOCK/'# ... drive the story ...'/'xcrun simctl launch "$UDID" "$BUNDLE"; sleep 3'}
rec_block() {
  echo "$REC_BLOCK"; [ -n "$REC_BLOCK" ] || return 1
  rm -f .qa/ios/S1-run.mov .qa/ios/S1-rec.log
  local t0=$SECONDS out rc k=0
  # watchdog (macOS has no timeout(1)): the block bounds itself at 30 s start + 3 s drive + 15 s stop,
  # so anything past 90 s is a hang
  UDID="$UDID" BUNDLE="$BUNDLE" bash -c "$REC_BLOCK" > .qa/ios/rec-block.out 2>&1 & local B=$!
  while kill -0 $B 2>/dev/null; do sleep 1; k=$((k+1)); [ $k -ge 90 ] && { echo "WATCHDOG: block hung"; kill -9 $B; pkill -9 -f "recordVideo.*S1-run.mov"; break; }; done
  wait $B; rc=$?
  out=$(cat .qa/ios/rec-block.out)
  local dt=$((SECONDS-t0))
  echo "$out"; echo "--- recorder log:"; cat .qa/ios/S1-rec.log; echo "--- block rc=$rc, took ${dt}s"
  ls -l .qa/ios/S1-run.mov; file .qa/ios/S1-run.mov
  pgrep -fl "recordVideo.*S1-run.mov" && { echo "recorder still running"; return 1; }
  [ $rc -eq 0 ] || return 1
  grep -q "Recording started" .qa/ios/S1-rec.log || { echo "never saw Recording started"; return 1; }
  echo "$out" | grep -qE "never started|did not stop" && return 1
  [ $dt -le 48 ] || { echo "took longer than the block's own bound"; return 1; }
  test -s .qa/ios/S1-run.mov && file .qa/ios/S1-run.mov | grep -qiE "quicktime|ISO Media"
}
step "FIXED D4 agent s6: recordVideo block verbatim starts, stops within its bound, writes a non-empty .mov" rec_block
log_stream() {
  xcrun simctl spawn "$UDID" log stream --level debug --predicate 'process == "Preferences"' > .qa/ios/S1-log.txt & LOG=$!
  xcrun simctl launch "$UDID" "$BUNDLE"; sleep 5; kill $LOG; wait $LOG 2>/dev/null; wc -l .qa/ios/S1-log.txt
  test -s .qa/ios/S1-log.txt
}
step "agent s7: simctl spawn log stream --level debug --predicate" log_stream

# FIXED D1: Maestro with the ios-qa section 2 block extracted verbatim from the agent file
step "FIXED D1 doctor: NOT READY run's Maestro fix line says to export PATH in the same shell" 'python3 .github/device-smoke/check_doctor.py .qa/ios/doctor.json maestro-fix'
EXPECT=1 step "precondition: maestro not on PATH before install" 'command -v maestro'
MAESTRO_BLOCK=$(python3 -I "$MD" "$AGENT_MD" bash get.maestro.mobile.dev)
step "FIXED D1 agent s2: Maestro install block verbatim (curl | bash; export PATH; maestro --version) succeeds in one shell" 'echo "$MAESTRO_BLOCK"; [ -n "$MAESTRO_BLOCK" ] && eval "$MAESTRO_BLOCK"'
step "FIXED D1: maestro resolves on PATH right after the block" 'command -v maestro'
step "agent s2: doctor.py --platform ios after Maestro install (READY)" 'python3 "$DOCTOR_DIR/scripts/doctor.py" --platform ios --out .qa'
step "agent s5: maestro --device UDID hierarchy > json" 'maestro --device "$UDID" hierarchy > .qa/ios/S1-03-hierarchy.json; head -c 300 .qa/ios/S1-03-hierarchy.json; echo; python3 -c "import json,sys;json.load(open(sys.argv[1]))" .qa/ios/S1-03-hierarchy.json'
mkdir -p .qa/ios/flows
cp .github/device-smoke/flows/ios-settings.yaml .qa/ios/flows/S1.yaml
step "agent s6: maestro --device UDID test --test-output-dir --format junit --output ... -e" 'maestro --device "$UDID" test --test-output-dir=.qa/ios/maestro --format junit --output .qa/ios/junit-S1.xml .qa/ios/flows/S1.yaml -e QA_EMAIL=qa-user@example.test -e QA_PASSWORD=not-a-secret'
step "maestro screenshots written under test-output-dir" 'find .qa/ios/maestro -name "*.png" | grep png'

# section 10 clean-up
step "agent s10: status_bar clear" 'xcrun simctl status_bar "$UDID" clear'
step "agent s10: shutdown" 'xcrun simctl shutdown "$UDID"'
step "agent s10: delete" 'xcrun simctl delete "$UDID"'

summary
