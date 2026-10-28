#!/bin/bash
# shellcheck disable=SC2015  # 'A && B || die' is intended: die is the last word.
# worker.sh: the PRIVILEGED half of foundry-iphone-mirror.
#
# build-helper-app.sh copies this file INTO the helper app bundle
# (Contents/Resources/worker.sh), where the code signature seals it. The client
# (bin/iphone-mirror) launches the helper app through LaunchServices once per
# action, so the helper app is its own "responsible process" and the macOS TCC
# grants (Accessibility + Screen Recording) attach to the helper app, not to your
# terminal, your editor, or the Python process running Claude Code.
#
# Performs ONE action, writes the result to $STATE/{result,rc,done}, exits.
# Editing this source file changes nothing until you rebuild the helper app, and a
# rebuild re-signs the bundle, so macOS asks you to approve it again. That is the
# security model: the code holding the grant is always code you rebuilt on purpose.
#
# Commands: geometry shot tap tapxy swipe type key home map selftest

set -o pipefail

APP_NAME="${IPHONE_MIRROR_APP_NAME:-iPhone Mirroring}"
SCAP=/usr/sbin/screencapture
# State dir must match the client. LaunchServices does not forward the caller's
# environment, so the default is derived from $HOME (which it does set). The env
# override exists for the unit tests, which run this file directly.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Inside the signed bundle, every IPHONE_MIRROR_* test hook is ignored. The helper
# app holds TCC grants, so nothing another process can set (launchd env, files in
# the state dir) may change which binary it runs or inject shell code into it.
IN_BUNDLE=0
case "$HERE" in */Contents/Resources) IN_BUNDLE=1 ;; esac
if [ "$IN_BUNDLE" = 1 ]; then
  unset IPHONE_MIRROR_STATE IPHONE_MIRROR_CLICLICK IPHONE_MIRROR_FAKE_GEOMETRY IPHONE_MIRROR_APP_NAME
  APP_NAME="iPhone Mirroring"
fi
STATE="${IPHONE_MIRROR_STATE:-$HOME/Library/Caches/foundry-iphone-mirror}"
GEOM="$STATE/geom.env"
mkdir -p "$STATE"

# cliclick location: build-helper-app.sh records it in config.env next to this
# file (inside the sealed bundle). LaunchServices gives apps a minimal PATH, so we
# never rely on PATH lookup alone.
CLICLICK=""
if [ -f "$HERE/config.env" ]; then
  # shellcheck disable=SC1091
  . "$HERE/config.env"
fi
# Test hook (only reachable when the worker is run directly; LaunchServices does
# not forward the caller's environment into the helper app).
[ -n "${IPHONE_MIRROR_CLICLICK:-}" ] && CLICLICK="$IPHONE_MIRROR_CLICLICK"
if [ -z "$CLICLICK" ] || [ ! -x "$CLICLICK" ]; then
  for c in /opt/homebrew/bin/cliclick /usr/local/bin/cliclick "$(command -v cliclick 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] && { CLICLICK="$c"; break; }
  done
fi

# ---- IPC: capture everything this run emits, hand it back through files ----
exec 3>&1 4>&2
TMPOUT="$(mktemp)"
exec 1>"$TMPOUT" 2>&1

finish() {
  local rc=$1
  exec 1>&3 2>&4
  cat "$TMPOUT" > "$STATE/result"
  echo "$rc" > "$STATE/rc"
  rm -f "$TMPOUT"
  touch "$STATE/done"
  exit "$rc"
}
die() { echo "ERROR: $*"; finish 1; }
need_cliclick() { [ -n "$CLICLICK" ] && [ -x "$CLICLICK" ] || die "cliclick not found (brew install cliclick, then rebuild the helper app)"; }
is_int() { [[ "$1" =~ ^-?[0-9]+$ ]]; }

geometry_raw() {
  # Test hook: lets the unit tests exercise the math without a real window.
  if [ -n "${IPHONE_MIRROR_FAKE_GEOMETRY:-}" ]; then echo "$IPHONE_MIRROR_FAKE_GEOMETRY"; return; fi
  # Bounded: the FIRST run asks "<helper> wants to control System Events" (the
  # Automation grant). Unanswered, osascript would block forever, so give up after
  # a few seconds and say which grant is missing.
  local out; out="$(mktemp)"
  osascript - "$APP_NAME" > "$out" 2>/dev/null 3>&- 4>&- <<'AS' &
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if not (exists process appName) then return "ERR_NOT_RUNNING"
    tell process appName
      if (count of windows) is 0 then return "ERR_NO_WINDOW"
      set p to position of window 1
      set s to size of window 1
      return ((item 1 of p) as string) & " " & ((item 2 of p) as string) & " " & ((item 1 of s) as string) & " " & ((item 2 of s) as string)
    end tell
  end tell
end run
AS
  local pid=$! i=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 0.2; i=$((i+1))
    if [ "$i" -gt 40 ]; then kill "$pid" 2>/dev/null; rm -f "$out"; echo "ERR_TIMEOUT"; return; fi
  done
  cat "$out"; rm -f "$out"
}

# Sets WX WY WW WH and writes them to geom.env, dropping any recorded shot size
# (a fresh geometry read means the old pixel mapping can no longer be trusted).
# Never call these helpers inside $(...): die() must run in the main shell so its
# message reaches the result file.
save_geometry() {
  local g; g="$(geometry_raw)"
  case "$g" in
    ERR_NOT_RUNNING) die "$APP_NAME is not running (iphone-mirror open)" ;;
    ERR_NO_WINDOW)   die "$APP_NAME has no window (bring it on screen, not minimized)" ;;
    ERR_TIMEOUT)     die "System Events did not answer in 8s: approve the prompt that the helper app 'wants to control System Events', or switch it on under Privacy & Security > Automation" ;;
    "" )             die "window geometry unreadable: Accessibility is not granted to the helper app" ;;
  esac
  read -r WX WY WW WH <<< "$g"
  is_int "$WX" && is_int "$WY" && is_int "$WW" && is_int "$WH" || die "unexpected geometry: '$g'"
  [ "$WW" -gt 0 ] && [ "$WH" -gt 0 ] || die "window has zero size: '$g'"
  printf 'WX=%s\nWY=%s\nWW=%s\nWH=%s\n' "$WX" "$WY" "$WW" "$WH" > "$GEOM"
}

# Read geom.env as data, never `source` it: the file lives in a user-writable
# directory and this process holds TCC grants. Only integer values of known keys
# are accepted.
load_geom() {
  WX=""; WY=""; WW=""; WH=""; IMGW=""; IMGH=""
  local k v
  while IFS='=' read -r k v; do
    is_int "$v" || continue
    case "$k" in
      WX) WX=$v ;; WY) WY=$v ;; WW) WW=$v ;; WH) WH=$v ;; IMGW) IMGW=$v ;; IMGH) IMGH=$v ;;
    esac
  done < "$GEOM"
  [ -n "$WX" ] && [ -n "$WY" ] && [ -n "$WW" ] && [ -n "$WH" ] || die "geometry cache is incomplete: run shot again"
}

# Screenshot pixel -> global screen point (sets GX GY), using the geometry and
# image size recorded by the most recent `shot`.
px2pt() {
  is_int "$1" && is_int "$2" || die "pixel coords must be integers, got '$1' '$2'"
  [ -f "$GEOM" ] || die "no geometry cached: run shot first"
  load_geom
  [ -n "$IMGW" ] && [ -n "$IMGH" ] || die "no screenshot recorded since the last geometry read: run shot first"
  local r
  r="$(awk -v wx="$WX" -v wy="$WY" -v ww="$WW" -v wh="$WH" -v iw="$IMGW" -v ih="$IMGH" -v px="$1" -v py="$2" \
    'BEGIN{ if (px < 0 || py < 0 || px > iw || py > ih) { print "OUT"; exit } printf "%d %d", wx + px*(ww/iw), wy + py*(wh/ih) }')"
  [ "$r" = "OUT" ] && die "pixel ($1,$2) is outside the last screenshot (${IMGW}x${IMGH}px)"
  read -r GX GY <<< "$r"
}

CMD="${1:-}"; shift 2>/dev/null
case "$CMD" in
  geometry)
    save_geometry
    echo "$WX $WY $WW $WH"; finish 0 ;;
  shot)
    OUT="${1:-$STATE/shot.png}"; mkdir -p "$(dirname "$OUT")"
    save_geometry
    "$SCAP" -x -o -R "${WX},${WY},${WW},${WH}" "$OUT" || die "screencapture failed: Screen Recording is not granted to the helper app"
    [ -s "$OUT" ] || die "screenshot empty: Screen Recording is not granted to the helper app"
    pw=$(sips -g pixelWidth "$OUT" 2>/dev/null | awk '/pixelWidth/{print $2}')
    ph=$(sips -g pixelHeight "$OUT" 2>/dev/null | awk '/pixelHeight/{print $2}')
    { echo "IMG=$OUT"; echo "IMGW=$pw"; echo "IMGH=$ph"; } >> "$GEOM"
    echo "$OUT ${pw}x${ph}px window ${WW}x${WH}pt"; finish 0 ;;
  map)
    # Pure math, no input injected: prints the global point a tap would hit.
    [ $# -eq 2 ] || die "usage: map px py"
    px2pt "$1" "$2"
    echo "$GX $GY"; finish 0 ;;
  tap)
    [ $# -eq 2 ] || die "usage: tap px py"
    need_cliclick
    px2pt "$1" "$2"
    "$CLICLICK" "c:${GX},${GY}" || die "cliclick failed: Accessibility is not granted to the helper app"
    echo "tapped pixel($1,$2) -> global($GX,$GY)"; finish 0 ;;
  tapxy)
    [ $# -eq 2 ] || die "usage: tapxy gx gy"
    is_int "$1" && is_int "$2" || die "screen points must be integers"
    need_cliclick
    "$CLICLICK" "c:${1},${2}" || die "cliclick failed"
    echo "tapped global($1,$2)"; finish 0 ;;
  swipe)
    [ $# -eq 4 ] || die "usage: swipe px1 py1 px2 py2"
    need_cliclick
    px2pt "$1" "$2"; gx1=$GX; gy1=$GY
    px2pt "$3" "$4"; gx2=$GX; gy2=$GY
    "$CLICLICK" "dd:${gx1},${gy1}" "dm:${gx2},${gy2}" "du:${gx2},${gy2}" || die "cliclick failed"
    echo "swiped ($gx1,$gy1)->($gx2,$gy2)"; finish 0 ;;
  type)
    [ -n "${1:-}" ] || die "usage: type text"
    need_cliclick
    "$CLICLICK" "t:$1" || die "cliclick failed"
    echo "typed ${#1} chars"; finish 0 ;;
  key)
    [ -n "${1:-}" ] || die "usage: key name"
    need_cliclick
    "$CLICLICK" "kp:$1" || die "cliclick failed (valid names include: return esc tab space delete arrow-up arrow-down arrow-left arrow-right)"
    echo "key: $1"; finish 0 ;;
  home)
    need_cliclick
    save_geometry
    x=$(( WX + WW/2 )); y1=$(( WY + WH - 5 )); y2=$(( WY + WH - 200 ))
    "$CLICLICK" "dd:${x},${y1}" "dm:${x},${y2}" "du:${x},${y2}" || die "cliclick failed"
    echo "home gesture"; finish 0 ;;
  selftest)
    echo "helper worker alive; cliclick=${CLICLICK:-missing}; state=$STATE"; finish 0 ;;
  *) die "unknown worker command: '$CMD'" ;;
esac
