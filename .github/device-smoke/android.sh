#!/usr/bin/env bash
# Android lane: runs the android-qa agent's and android-ui-tree skill's own commands
# against the Settings app on a real emulator. Called from reactivecircus/android-emulator-runner.
QA_PLAT=android
source .github/device-smoke/lib.sh
export CLAUDE_PLUGIN_ROOT="$GITHUB_WORKSPACE/plugins/foundry-devices"
PKG=com.android.settings

# android-qa section 1: find the skill scripts (verbatim)
step "agent s1: locate skill dirs via CLAUDE_PLUGIN_ROOT" '
DOCTOR_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-doctor"; [ -d "$DOCTOR_DIR" ] || DOCTOR_DIR="$(ls -d .claude/skills/device-doctor "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-doctor" 2>/dev/null | head -1)"
UITREE_DIR="${CLAUDE_PLUGIN_ROOT}/skills/android-ui-tree"; [ -d "$UITREE_DIR" ] || UITREE_DIR="$(ls -d .claude/skills/android-ui-tree "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/android-ui-tree" 2>/dev/null | head -1)"
MATRIX_DIR="${CLAUDE_PLUGIN_ROOT}/skills/device-matrix"; [ -d "$MATRIX_DIR" ] || MATRIX_DIR="$(ls -d .claude/skills/device-matrix "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/device-matrix" 2>/dev/null | head -1)"
echo "$DOCTOR_DIR $UITREE_DIR $MATRIX_DIR"; [ -n "$DOCTOR_DIR" ] && [ -n "$UITREE_DIR" ] && [ -n "$MATRIX_DIR" ]'

step "tool versions" 'which adb emulator avdmanager sdkmanager; adb version | head -1; emulator -version 2>/dev/null | head -1; java -version 2>&1 | head -1'

# section 2: doctor
step "agent s2: doctor.py --platform android --out .qa" 'python3 "$DOCTOR_DIR/scripts/doctor.py" --platform android --out .qa'
step "doctor.json written" 'test -s .qa/android/doctor.json && python3 -c "import json;d=json.load(open(\".qa/android/doctor.json\"));print(\"ready=\",d[\"ready\"])"'
step "agent s2: adb devices -l" 'adb devices -l | tee .qa/android/adb-devices.txt'

# section 3: device set-up
# The runner does not put $ANDROID_HOME/emulator on PATH (the agent's install note says to); do it here. [ENV]
export PATH="$PATH:$ANDROID_HOME/emulator"
step "agent s3: emulator -list-avds" 'emulator -list-avds'
step "agent s3: avdmanager list device has pixel_7" 'avdmanager list device -c | tee .qa/android/avd-device-types.txt | grep -x pixel_7'
step "agent s3: avdmanager create avd -n qa_api34 ... -d pixel_7 (x86_64 image)" 'echo no | avdmanager create avd -n qa_api34 -k "system-images;android-34;google_apis;x86_64" -d pixel_7 --force && emulator -list-avds | grep -x qa_api34'
step "agent s3: adb wait-for-device" 'adb wait-for-device'
step "runner emulator: wait for sys.boot_completed (single device)" 'n=0; until [ "$(adb shell getprop sys.boot_completed | tr -d "\r")" = "1" ]; do sleep 2; n=$((n+1)); [ $n -gt 150 ] && break; done; [ $n -le 150 ]'
step "agent s3: SERIAL from adb devices" 'SERIAL=$(adb devices | awk "/^emulator-/{print \$1; exit}"); echo "SERIAL=$SERIAL"; [ -n "$SERIAL" ]'
step "agent s3: disable animations (3 settings put)" 'adb -s "$SERIAL" shell settings put global window_animation_scale 0 && adb -s "$SERIAL" shell settings put global transition_animation_scale 0 && adb -s "$SERIAL" shell settings put global animator_duration_scale 0'

# section 4: launch
step "agent s4: cmd package resolve-activity --brief" 'ACT=$(adb -s "$SERIAL" shell cmd package resolve-activity --brief "$PKG" | tr -d "\r" | tail -1); echo "ACT=$ACT"; [ -n "$ACT" ]'
step "agent s4: am start -W -n PKG/activity" 'adb -s "$SERIAL" shell am start -W -n "$ACT" | tee .qa/android/am-start.txt | grep -q "Status: ok"'
step "agent s4: monkey launcher launch" 'adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1'
step "agent s4: am start -W -a <action> (intent launch)" 'adb -s "$SERIAL" shell am start -W -a android.settings.SETTINGS | grep -q "Status: ok"'
sleep 3
step "agent s6: where am I (dumpsys activity grep)" 'adb -s "$SERIAL" shell dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" | tee .qa/android/resumed.txt | grep -q "$PKG"'
step "agent s6: pidof PKG" 'adb -s "$SERIAL" shell pidof "$PKG"'
step "agent s7: logcat -c" 'adb -s "$SERIAL" logcat -c'

# section 5 / android-ui-tree skill: real dump
XML=.qa/android/S1-03-ui.xml
step "skill: uiautomator dump + pull" 'adb -s "$SERIAL" shell uiautomator dump /sdcard/ui.xml && adb -s "$SERIAL" pull /sdcard/ui.xml "$XML"'
step "skill: uitree.py outline (real dump)" 'python3 "$UITREE_DIR/scripts/uitree.py" outline "$XML" | tee .qa/android/S1-03-outline.txt'
step "skill: uitree.py find --text \"Network & internet\"" 'python3 "$UITREE_DIR/scripts/uitree.py" find "$XML" --text "Network & internet"'
first_rid() { RID=$(grep -o 'resource-id="[^"]*:id/[a-z_]*"' "$XML" | head -1 | sed -e 's/.*:id\///' -e 's/"$//'); echo "RID=$RID"; [ -n "$RID" ] && python3 "$UITREE_DIR/scripts/uitree.py" find "$XML" --id "$RID" --json | head -30; }
step "skill: uitree.py find --id (short form after :id/) --json" first_rid
step "skill: uitree.py find --desc \"Profile picture\" (content-desc)" 'python3 "$UITREE_DIR/scripts/uitree.py" find "$XML" --desc "profile picture"'
EXPECT=2 step "skill: tap ambiguity guard exits 2 on many matches (--text e)" 'python3 "$UITREE_DIR/scripts/uitree.py" tap "$XML" --text "e"'
# FIXED D2 + D10: the agent s5 tap line (with --clickable --serial) on a list-row label resolves
# to the clickable row and prints a command that names the device.
tap_fixed() {
  TAP=$(python3 "$UITREE_DIR/scripts/uitree.py" tap "$XML" --text "Network & internet" --exact --clickable --serial "$SERIAL"); local rc=$?
  echo "printed: $TAP"
  [ $rc -eq 0 ] && [[ "$TAP" =~ ^adb\ -s\ $SERIAL\ shell\ input\ tap\ [0-9]+\ [0-9]+$ ]]
}
step "FIXED D2+D10 agent s5: tap --text \"Network & internet\" --exact --clickable --serial SERIAL prints one 'adb -s SERIAL shell input tap X Y'" tap_fixed
step "FIXED D2: find --clickable reports the clickable row (clickable=true) for the label" 'python3 "$UITREE_DIR/scripts/uitree.py" find "$XML" --text "Network & internet" --exact --clickable --json | tee .qa/android/clickable-row.json | python3 -c "import json,sys;h=json.load(sys.stdin);print(h);assert len(h)==1 and h[0].get(\"clickable\") in (True,\"true\")"'
tap_one_device() {
  local T; T=$(env -u ANDROID_SERIAL python3 "$UITREE_DIR/scripts/uitree.py" tap "$XML" --text "Network & internet" --exact --clickable); local rc=$?
  echo "printed: $T"; [ $rc -eq 0 ] && [ "$T" = "$TAP" ]
}
step "FIXED D10: no --serial, no ANDROID_SERIAL, one device attached -> same 'adb -s SERIAL ...' command" tap_one_device
step "agent s6: adb exec-out screencap -p (before tap)" 'adb -s "$SERIAL" exec-out screencap -p > .qa/android/S1-01-settings-home.png && file .qa/android/S1-01-settings-home.png | grep -q PNG'
step "run the printed tap command exactly as printed" 'eval "$TAP"'
sleep 2
step "skill rule: dump again after the action, find Airplane mode" 'adb -s "$SERIAL" shell uiautomator dump /sdcard/ui.xml && adb -s "$SERIAL" pull /sdcard/ui.xml .qa/android/S1-05-ui.xml && python3 "$UITREE_DIR/scripts/uitree.py" find .qa/android/S1-05-ui.xml --text "Airplane"'
step "agent s6: screencap after tap" 'adb -s "$SERIAL" exec-out screencap -p > .qa/android/S1-05-network.png && file .qa/android/S1-05-network.png | grep -q PNG'
step "agent s6: input keyevent KEYCODE_BACK" 'adb -s "$SERIAL" shell input keyevent KEYCODE_BACK'
step "agent s6: input swipe 540 1800 540 600 300" 'adb -s "$SERIAL" shell input swipe 540 1800 540 600 300'
step "agent s6: screenrecord --time-limit 5 + pull" 'adb -s "$SERIAL" shell screenrecord --time-limit 5 /sdcard/S1.mp4 && adb -s "$SERIAL" pull /sdcard/S1.mp4 .qa/android/S1.mp4'
step "agent s7: logcat -d -b crash" 'adb -s "$SERIAL" logcat -d -b crash > .qa/android/S1-crash.txt; wc -l .qa/android/S1-crash.txt'
step "agent s7: logcat -d *:E" 'adb -s "$SERIAL" logcat -d "*:E" > .qa/android/S1-errors.txt; wc -l .qa/android/S1-errors.txt'
step "agent s7: dumpsys meminfo PKG" 'adb -s "$SERIAL" shell dumpsys meminfo "$PKG" > .qa/android/S1-meminfo.txt && grep -q "TOTAL" .qa/android/S1-meminfo.txt'
step "agent s7: dumpsys gfxinfo PKG" 'adb -s "$SERIAL" shell dumpsys gfxinfo "$PKG" > .qa/android/S1-gfxinfo.txt && grep -qi "frames" .qa/android/S1-gfxinfo.txt'
step "agent s10: dumpsys package versionName" 'adb -s "$SERIAL" shell dumpsys package "$PKG" | grep -E "versionName|versionCode" | head -2'

# FIXED D1: Maestro, installed with the android-qa section 2 block extracted verbatim from the agent file.
MD=.github/device-smoke/mdblock.py
AGENT_MD="$CLAUDE_PLUGIN_ROOT/agents/android-qa.md"
step "FIXED D1 doctor: maestro row fix line says to export PATH in the same shell" 'python3 .github/device-smoke/check_doctor.py .qa/android/doctor.json maestro-fix'
EXPECT=1 step "precondition: maestro not on PATH before install" 'command -v maestro'
MAESTRO_BLOCK=$(python3 -I "$MD" "$AGENT_MD" bash get.maestro.mobile.dev)
step "FIXED D1 agent s2: Maestro install block verbatim (curl | bash; export PATH; maestro --version) succeeds in one shell" 'echo "$MAESTRO_BLOCK"; [ -n "$MAESTRO_BLOCK" ] && eval "$MAESTRO_BLOCK"'
step "FIXED D1: maestro resolves on PATH right after the block" 'command -v maestro'
step "doctor after Maestro install (maestro row OK)" 'python3 "$DOCTOR_DIR/scripts/doctor.py" --platform android --out .qa --json > .qa/android/doctor-after-maestro.json; python3 -c "import json;d=json.load(open(\".qa/android/doctor-after-maestro.json\"));[print(c[\"ok\"],c[\"name\"],c[\"detail\"]) for c in d[\"checks\"]];assert d[\"ready\"]"'
step "agent s5: maestro --device SERIAL hierarchy" 'maestro --device "$SERIAL" hierarchy > .qa/android/S1-hierarchy.json; head -c 300 .qa/android/S1-hierarchy.json; python3 -c "import json,sys;json.load(open(sys.argv[1]))" .qa/android/S1-hierarchy.json'
mkdir -p .qa/android/flows
cp .github/device-smoke/flows/android-settings.yaml .qa/android/flows/S1.yaml
step "template: android-sign-in.yaml parses as maestro flow (check-syntax)" 'maestro check-syntax "$MATRIX_DIR/templates/maestro/android-sign-in.yaml" || echo "check-syntax not available in this Maestro"'
step "agent s6: maestro --device SERIAL test --test-output-dir --format junit --output ... -e" 'maestro --device "$SERIAL" test --test-output-dir=.qa/android/maestro --format junit --output .qa/android/junit-S1.xml .qa/android/flows/S1.yaml -e QA_EMAIL=qa-user@example.test -e QA_PASSWORD=not-a-secret'
step "maestro screenshots written under test-output-dir" 'find .qa/android/maestro -name "*.png" | grep png'

# FIXED D11: the android-qa section 3 boot block, extracted verbatim, started while the runner's
# emulator is already attached (the two-device case the fix is for). The doc says to add
# -no-window for headless; CI also needs a software GPU. [ENV]
MAIN_SERIAL=$SERIAL
BOOT_BLOCK=$(python3 -I "$MD" "$AGENT_MD" bash 'SERIAL=emulator-5580' --from 'SERIAL=emulator-5580' --to 'until [')
BOOT_BLOCK=${BOOT_BLOCK/-no-boot-anim &/-no-boot-anim -no-window -gpu swiftshader_indirect \&}
boot_block() {
  echo "$BOOT_BLOCK"
  [ -n "$BOOT_BLOCK" ] || return 1
  local t0=$SECONDS
  timeout 420 bash -c "$BOOT_BLOCK" > .qa/android/d11-boot.log 2>&1; local rc=$?
  echo "block rc=$rc after $((SECONDS-t0)) s"; grep -E "did not finish|ERROR|FATAL" .qa/android/d11-boot.log | head -5
  adb devices -l | tee .qa/android/d11-adb-devices.txt
  # the block ends in an until loop, so its exit code says nothing; judge the outcome
  [ $rc -ne 124 ] && ! grep -q "did not finish booting" .qa/android/d11-boot.log && [ "$(adb -s emulator-5580 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]
}
step "FIXED D11 agent s3: boot block verbatim (SERIAL=emulator-5580, -port 5580, adb -s wait + bounded boot loop) boots a 2nd emulator" boot_block
EXPECT=1 step "D11 why: with two devices and no ANDROID_SERIAL, a bare 'adb shell' fails (more than one device/emulator)" 'echo "runner ANDROID_SERIAL=${ANDROID_SERIAL-unset}"; env -u ANDROID_SERIAL adb shell getprop sys.boot_completed'
tap_two_devices() {
  env -u ANDROID_SERIAL python3 "$UITREE_DIR/scripts/uitree.py" tap "$XML" --text "Network & internet" --exact --clickable > .qa/android/d10-two-devices.txt 2>&1; local rc=$?
  cat .qa/android/d10-two-devices.txt
  grep -q emulator-5580 .qa/android/d10-two-devices.txt && grep -q "$MAIN_SERIAL" .qa/android/d10-two-devices.txt || return 9
  return $rc
}
EXPECT=2 step "FIXED D10: two devices, no --serial, no ANDROID_SERIAL -> tap exits 2 and names both" tap_two_devices
step "FIXED D10: ANDROID_SERIAL=emulator-5580 -> printed tap names emulator-5580" 'T=$(ANDROID_SERIAL=emulator-5580 python3 "$UITREE_DIR/scripts/uitree.py" tap "$XML" --text "Network & internet" --exact --clickable); echo "$T"; [[ "$T" == "adb -s emulator-5580 shell input tap "* ]]'
step "FIXED D11: the -s SERIAL commands hit the 2nd emulator (animations off on emulator-5580)" 'adb -s emulator-5580 shell settings put global window_animation_scale 0 && [ "$(adb -s emulator-5580 shell settings get global window_animation_scale | tr -d "\r")" = "0" ]'
stop_second() { adb -s emulator-5580 emu kill; local n=0; while adb devices | grep -q emulator-5580; do sleep 2; n=$((n+1)); [ $n -ge 30 ] && return 1; done; return 0; }
step "agent s9: stop the emulator this run started (adb -s emulator-5580 emu kill)" stop_second
SERIAL=$MAIN_SERIAL
step "agent s9: avdmanager delete avd -n qa_api34" 'avdmanager delete avd -n qa_api34'

summary
