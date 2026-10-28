#!/bin/bash
# build-helper-app.sh: build, sign (ad hoc) and register the helper app that
# holds the macOS permissions for foundry-iphone-mirror.
#
# Why a helper app: macOS TCC grants (Accessibility, Screen Recording, Automation) attach to
# the "responsible process". If you grant your terminal, only that terminal works,
# and a headless agent process may have no way to answer the prompt at all. The
# helper app is launched through LaunchServices per action, so it is always its
# own responsible process and carries its own grant, whoever calls it.
#
# The worker script is copied INTO the bundle and sealed by the signature. Every
# rebuild re-signs, which changes the code hash, so macOS asks you to approve the
# app again. That is deliberate: the code holding the grant is code you rebuilt.
#
# Usage:
#   build-helper-app.sh [--app PATH] [--bundle-id ID] [--name NAME]
# Defaults:
#   --app        $HOME/Applications/FoundryPhone.app
#   --bundle-id  local.foundry.iphone-mirror
#   --name       FoundryPhone
#
# The app lives OUTSIDE the plugin on purpose: the plugin directory moves on every
# plugin update, and a moved bundle loses its grant.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${IPHONE_MIRROR_HELPER:-$HOME/Applications/FoundryPhone.app}"
BUNDLE_ID="local.foundry.iphone-mirror"
NAME="FoundryPhone"
CONF_DIR="$HOME/Library/Application Support/foundry-iphone-mirror"

while [ $# -gt 0 ]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    --bundle-id) BUNDLE_ID="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$APP" in *.app) ;; *) echo "--app must end in .app (got $APP)" >&2; exit 2 ;; esac
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "--name may only use letters, digits, . _ -" >&2; exit 2; }
[[ "$BUNDLE_ID" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "--bundle-id may only use letters, digits, . -" >&2; exit 2; }
[ "$(uname -s)" = "Darwin" ] || { echo "macOS only" >&2; exit 1; }
command -v clang >/dev/null 2>&1 || { echo "clang not found: run  xcode-select --install  and retry" >&2; exit 1; }

CLICLICK_PATH="$(command -v cliclick 2>/dev/null || true)"
for c in /opt/homebrew/bin/cliclick /usr/local/bin/cliclick; do
  [ -z "$CLICLICK_PATH" ] && [ -x "$c" ] && CLICLICK_PATH="$c"
done
[ -n "$CLICLICK_PATH" ] || echo "WARNING: cliclick not found (brew install cliclick). Screenshots will work, taps will not, until you install it and rebuild." >&2

mkdir -p "$(dirname "$APP")"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

clang -O2 -o "$APP/Contents/MacOS/$NAME" "$HERE/launcher.c"
cp "$HERE/worker.sh" "$APP/Contents/Resources/worker.sh"
chmod +x "$APP/Contents/Resources/worker.sh"
{
  echo "# written by build-helper-app.sh; sealed by the bundle signature"
  printf 'CLICLICK=%q\n' "$CLICLICK_PATH"
  [ -n "${IPHONE_MIRROR_APP_NAME:-}" ] && printf 'APP_NAME=%q\n' "$IPHONE_MIRROR_APP_NAME"
  true
} > "$APP/Contents/Resources/config.env"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME (iPhone Mirror Driver)</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

codesign --force --deep --sign - --identifier "$BUNDLE_ID" "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true

# Remember where the helper lives so the CLI and MCP server find it without env vars.
mkdir -p "$CONF_DIR"
printf '%s\n' "$APP" > "$CONF_DIR/helper-path"

echo "built:   $APP"
codesign -dv "$APP" 2>&1 | grep -E "^Identifier|^Signature" || true
cat <<NEXT

Next, the grants only you can give (System Settings > Privacy & Security):
  Accessibility     -> [+] -> Cmd-Shift-G -> paste: $APP -> add, switch on
  Screen Recording  -> [+] -> same path -> add, switch on
  Automation        -> run iphone-mirror doctor; click Allow when $NAME asks to control System Events
Then run:  iphone-mirror doctor     (repeat until it reports 0 fail)
NEXT
