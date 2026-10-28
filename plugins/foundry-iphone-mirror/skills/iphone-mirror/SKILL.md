---
name: iphone-mirror
description: Drive a real iPhone from this Mac through macOS iPhone Mirroring, using a screenshot, read, act, verify loop (tap, type, swipe, home). Use when a task must happen ON the iPhone and has no Mac-side API, such as QA of an iOS app on a real device, walking through an onboarding flow, toggling a Setting, or building a Shortcut. Trigger phrases include "on my iPhone", "tap through the app on the phone", "test the iOS build on a real device", "iPhone Mirroring", "screenshot my phone", "drive the phone".
---

# Drive an iPhone through iPhone Mirroring

Install: plugin only. It drives the phone through the plugin's `iphone-mirror` CLI on PATH (bin/), its `iphone` MCP server, and the compiled helper app built from the plugin's engine/.

An iPhone has no Mac-side API for most apps. iPhone Mirroring (macOS 15+) shows the
phone's screen in a Mac window and forwards clicks and keystrokes to the phone. This
skill drives that window: take a screenshot, read it, inject one action, take another
screenshot to verify. A click inside the window is a tap on the phone.

## Three front doors, one engine

| Door | When to use it |
|---|---|
| CLI `iphone-mirror` (on PATH while the plugin is enabled; also at `${CLAUDE_PLUGIN_ROOT}/bin/iphone-mirror`) | default; works from Bash in any session |
| MCP tools `mcp__plugin_foundry-iphone-mirror_iphone__iphone_*` | when you want the screenshot inline, without a separate Read |
| Subagent `iphone-driver` | a long task (more than about 5 actions); its screenshots stay out of your context and you get only the outcome |

All three call the same client, which launches the helper app (default
`$HOME/Applications/FoundryPhone.app`) once per action. The helper app holds the
Accessibility, Screen Recording and Automation grants, so it works the same from a terminal, an
editor, or a headless agent.

## Step 0: preflight, every time

```bash
iphone-mirror doctor
```

You want `N ok, 0 fail`. If any line says `[FAIL]`, stop and give the user the exact
fix from that line. Most common:

| Doctor line | Fix (the user does it) |
|---|---|
| helper app missing | `iphone-mirror build` |
| cliclick missing | `brew install cliclick`, then `iphone-mirror build` |
| iPhone Mirroring not running | `iphone-mirror open`, then unlock or approve on the phone |
| Accessibility FAIL | System Settings > Privacy & Security > Accessibility > [+] > add the helper app |
| Screen Recording FAIL | System Settings > Privacy & Security > Screen Recording > [+] > add the helper app |
| System Events did not answer | click Allow on the "wants to control System Events" prompt, or switch it on under Privacy & Security > Automation |
| signature does not verify | `iphone-mirror build`, then re-approve the grants |

Never try to click a System Settings permission dialog yourself. macOS blocks synthetic
input there by design, and the grant must be the user's decision.

## The loop: screenshot, read, act, verify

```bash
iphone-mirror shot /tmp/iphone-shots/01.png
# -> /tmp/iphone-shots/01.png 652x1414px window 326x707pt
```

1. **Screenshot.** `iphone-mirror shot <path>` captures only the Mirroring window and
   prints its pixel size and window size in points. It also records the geometry used
   by `tap` and `swipe`.
2. **Read it.** Open the PNG with the Read tool. Find the target and estimate its
   center in that image's pixels (top-left is 0,0). Aim for the middle of a button, not
   its edge.
3. **Act, once.** `iphone-mirror tap <px> <py>`. The client converts screenshot pixels
   to screen points for you (it handles Retina 2x).
4. **Verify.** Take a new screenshot and Read it. Confirm the screen changed the way you
   expected before the next action. If it did not, re-plan from the new screenshot.

Never chain taps without a screenshot between them. iOS animates, scrolls and shows
sheets, so coordinates from an old screenshot go stale, and one missed tap desyncs
everything after it.

Dry-run a tap without touching the phone:

```bash
iphone-mirror map 326 700   # prints the screen point a tap would hit
```

## Commands

| Command | What it does |
|---|---|
| `iphone-mirror doctor` | preflight: macOS, Mirroring, cliclick, helper app and signature, all three grants |
| `iphone-mirror build [--app PATH] [--bundle-id ID] [--name NAME]` | build and sign the helper app |
| `iphone-mirror open` | launch and focus iPhone Mirroring |
| `iphone-mirror shot [out.png]` | screenshot the phone window |
| `iphone-mirror tap <px> <py>` | tap at pixel coords from the last shot |
| `iphone-mirror swipe <px1> <py1> <px2> <py2>` | drag, in shot pixels |
| `iphone-mirror type "text"` | type into the focused field |
| `iphone-mirror key <name>` | `return`, `esc`, `tab`, `space`, `delete`, `arrow-up`, `arrow-down`, `arrow-left`, `arrow-right` |
| `iphone-mirror home` | swipe-up home gesture |
| `iphone-mirror info` | window geometry in points (resets the mapping: shoot again before tapping) |
| `iphone-mirror tapxy <gx> <gy>` | tap at absolute screen points (rarely needed) |
| `iphone-mirror map <px> <py>` | where a tap would land; injects nothing |

MCP equivalents: `iphone_doctor`, `iphone_open`, `iphone_screenshot`, `iphone_tap`,
`iphone_swipe`, `iphone_type`, `iphone_key`, `iphone_home`, `iphone_info`, `iphone_tapxy`.

## Recipes

**Scroll a list down** (content moves up): drag from low on the screen to high.

```bash
iphone-mirror swipe 326 1100 326 400
```

**Fill a text field:** tap the field, screenshot to confirm the cursor or keyboard,
then type, then screenshot to confirm the text landed.

```bash
iphone-mirror tap 326 520
iphone-mirror shot /tmp/iphone-shots/02.png   # Read it: is the keyboard up?
iphone-mirror type "test-user-01"
iphone-mirror key return
```

**Open an app:** `home`, then swipe down from the middle of the home screen to open
Spotlight, type the app name, `key return`. Verify with a screenshot after each step.

**Real-device QA pass on your iOS build:** write the acceptance checks first (for
example "after sign-up, the Home tab shows the user's name"), then run the loop per
check and save each verifying screenshot as evidence (`qa-01-signup.png`,
`qa-02-home.png`). Report pass or fail per check with the screenshot path. A check you
did not screenshot is not verified.

## Rules

- `doctor` first. On any FAIL, stop and report the fix.
- One action, then one screenshot. Always.
- Locked phone, "iPhone in Use", or a connect screen: the user must act on the physical
  phone (unlock it, or lock it again so Mirroring can take over). Report it, do not tap.
- Secrets: `type` sends literal keystrokes that show on the mirror and may be captured
  in screenshots. Do not type passwords or API keys unless the user explicitly asks, and
  never repeat a secret in your report.
- Go slow. A shot round-trip takes about a second, and the mirror lags the phone.
- If taps land in the wrong place, the window moved or resized. Take a new screenshot;
  never reuse coords across windows of different sizes.
- One phone, one action at a time. The client holds a lock, so a second caller waits.

## Acceptance check for "the setup works"

1. `iphone-mirror doctor` ends with `0 fail`.
2. `iphone-mirror shot /tmp/iphone-shots/s.png`, then open the PNG: it shows the phone.
3. Tap a visible app icon from that PNG, then shoot again: the app is open.
4. `iphone-mirror home`, then shoot: the home screen is back.
