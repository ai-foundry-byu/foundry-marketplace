# Shared helpers for the device-smoke workflow. Sourced by each platform script.
# Every instruction from the plugin is run through `step`, which records its exit
# code in .qa/<platform>/steps.tsv so the job summary shows PASS/FAIL per instruction.
# EXPECT=<rc> step ...   marks a step whose expected exit code is not 0.
# Steps tagged "FIXED Dn" assert the fixed behavior for defect Dn.

QA_PLAT="${QA_PLAT:?set QA_PLAT}"
mkdir -p ".qa/$QA_PLAT"
STEPS=".qa/$QA_PLAT/steps.tsv"
: > "$STEPS"
FAILS=0

step() {
  local name="$1"; shift
  local want="${EXPECT:-0}"
  echo "::group::$name"
  echo "+ $*"
  eval "$@"
  local rc=$?
  echo "::endgroup::"
  local verdict=PASS
  if [ "$rc" != "$want" ]; then verdict=FAIL; FAILS=$((FAILS+1)); echo "::warning title=$QA_PLAT step failed::$name (rc=$rc, expected $want)"; fi
  printf '%s\t%s\t%s\t%s\n' "$verdict" "$rc" "$want" "$name" >> "$STEPS"
  return 0
}

summary() {
  {
    echo "### $QA_PLAT: $(grep -c '^PASS' "$STEPS") pass, $(grep -c '^FAIL' "$STEPS") fail"
    echo
    echo "| verdict | rc | expected | instruction |"
    echo "|---|---|---|---|"
    while IFS=$'\t' read -r v rc want name; do echo "| $v | $rc | $want | ${name//|/\\|} |"; done < "$STEPS"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
  cat "$STEPS"
  [ "$FAILS" -eq 0 ]
}
