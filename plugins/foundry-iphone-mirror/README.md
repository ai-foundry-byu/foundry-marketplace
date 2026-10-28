# foundry-iphone-mirror

Drive a real iPhone from your Mac with Claude Code. The plugin uses macOS **iPhone
Mirroring**: it screenshots the mirrored phone, lets the model read the screenshot,
injects one tap, swipe or keystroke, and screenshots again to verify. Use it for
real-device QA of your iOS app and for any on-phone task that has no Mac-side API.

**Status: proven engine, port not yet device-tested.** The engine runs in production in
our own harness today, driving a real iPhone. This marketplace port of it has passed its
unit tests but has not yet been run on a real device. Expect rough edges on first setup,
and please report what broke.

It is the only real-device iOS path in this marketplace. It does not use the iOS
Simulator, XCUITest or Appium, and it does not need a developer account or a cable.

## What's inside

| Item | Type | What it gives you | Maturity |
|---|---|---|---|
| `iphone-mirror` | skill | the screenshot, read, act, verify loop, command reference, recipes, rules | new (port of a proven engine; not yet run on a device) |
| `iphone-driver` | agent | delegate a whole on-phone task; screenshots stay in its context, you get the outcome | new (port of a proven engine; not yet run on a device) |
| `iphone-mirror` | script (CLI, on PATH) | `doctor`, `build`, `open`, `shot`, `tap`, `swipe`, `type`, `key`, `home`, `info`, `tapxy`, `map` | new (port of a proven engine; not yet run on a device) |
| `engine/worker.sh` + `engine/launcher.c` | script | the privileged worker and the Mach-O launcher sealed inside the helper app | new (port of a proven engine; not yet run on a device) |
| `engine/build-helper-app.sh` | script | builds, ad hoc signs and registers the helper app | new (port of a proven engine; not yet run on a device) |
| `iphone` | MCP server (`mcp/server.py`) | typed `iphone_*` tools; `iphone_screenshot` returns the PNG inline | new (rewrite; not yet run on a device) |

**What the labels mean.** "new" means written or changed for this marketplace and not
yet run on a real device. Every item here is new for now. The CLI, worker, launcher,
build script, skill and agent are a port of a tool that runs in production in our own
harness today, driving a real iPhone; the port changed that engine in small ways
(listed under "Changes from the source" below) that are unit-tested but not yet run on
a device. The MCP server is a rewrite: our production server uses the `mcp` Python
package, and this one is standard-library only so you install nothing. Its tool surface
is the same and it is covered by protocol tests. The labels move to "proven" once a
device run passes the acceptance check in the skill.

## Install one item on its own

Nothing in this plugin works when copied on its own. Install the whole plugin.

| Item | Standalone? | Why |
|---|---|---|
| `iphone-mirror` skill | plugin only | needs the `iphone-mirror` CLI on PATH (bin/), the `iphone` MCP server, and the helper app compiled from engine/ |
| `iphone-driver` agent | plugin only | calls the same CLI and helper app |
| `iphone` MCP server | plugin only | registered by the plugin's `.mcp.json` via `${CLAUDE_PLUGIN_ROOT}` |

## Requirements

- macOS 15 (Sequoia) or newer, with the **iPhone Mirroring** app. Not offered in every
  region (it has been unavailable in the EU).
- An iPhone on iOS 18 or newer, signed in to the same Apple Account as the Mac, nearby,
  with Wi-Fi and Bluetooth on. Pair it once by opening iPhone Mirroring and following
  the prompts.
- Xcode Command Line Tools for `clang` (one-time, to build the helper app):
  `xcode-select --install`
- `cliclick` for clicks and keystrokes: `brew install cliclick`
- Python 3 (any 3.8+) for the MCP server. Standard library only.

## Install

Add the marketplace:

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the plugin:

```text
/plugin install foundry-iphone-mirror@ai-foundry
```

Then restart Claude Code so the skill, agent, CLI and MCP server load.

From a shell instead:

```bash
claude plugin install foundry-iphone-mirror@ai-foundry
```

## One-time setup (about 5 minutes)

**1. Install the tools.**

```bash
xcode-select --install
brew install cliclick
```

**2. Build the helper app.** This compiles a tiny launcher, copies the worker into an
app bundle, signs it ad hoc and registers it. Default location
`$HOME/Applications/FoundryPhone.app`.

```bash
iphone-mirror build
```

Options: `--app PATH` (must end in `.app`), `--bundle-id ID`, `--name NAME`. The chosen
path is remembered in `$HOME/Library/Application Support/foundry-iphone-mirror/helper-path`,
so the CLI and the MCP server find it without environment variables.

If `iphone-mirror` is not on your PATH (for example in a plain terminal outside Claude
Code), run it by full path from the plugin directory, `<plugin-dir>/bin/iphone-mirror`.
`claude plugin details foundry-iphone-mirror` shows where the plugin is installed.

**3. Open iPhone Mirroring and connect the phone.**

```bash
iphone-mirror open
```

Unlock or approve on the phone if asked. Keep the Mirroring window on screen (it can
be behind other windows; the CLI raises it before each capture and tap).

**4. Grant the helper app three permissions.** Only you can do this. In System Settings >
Privacy & Security:

- **Accessibility** > [+] > press Cmd-Shift-G > paste `~/Applications/FoundryPhone.app` >
  Open > switch it on.
- **Screen Recording** (called "Screen & System Audio Recording" on newer macOS) > [+] >
  same path > switch it on.

- **Automation**: the first `iphone-mirror doctor` run shows a prompt that the helper app
  "wants to control System Events" (that is how it reads the Mirroring window's position).
  Click **Allow**. If you missed it, find the helper app under Automation and switch on
  System Events. Unanswered, the doctor reports a System Events timeout after 8 seconds.

Grants take effect immediately. No restart.

**5. Run the doctor until it is clean.**

```bash
iphone-mirror doctor
```

Expected ending: `=== 9 ok, 0 fail, 0 warn ===`. Each `[FAIL]` line names its fix.

### Why a helper app?

macOS attaches Accessibility, Screen Recording and Automation grants to the *responsible process*.
Grant your terminal and only that terminal works; a headless agent process may have no
way to answer the prompt at all. The client launches the helper app through
LaunchServices once per action, so the helper is always its own responsible process
and carries its own grant, whoever calls it: a terminal, VS Code, Claude Code running
headless, or the MCP server.

The helper lives outside the plugin on purpose. The plugin directory changes on every
plugin update, and a moved bundle loses its grant.

### Security model

- The worker script is copied into the bundle and covered by the code signature.
  `doctor` runs `codesign --verify --deep --strict` on the helper and fails if anything
  edited the bundle since you built it.
- Every rebuild re-signs the app, so macOS treats it as new and asks you to approve
  the grants again. That is by design: the code holding the grant is code you rebuilt.
- Inside the bundle the worker ignores all `IPHONE_MIRROR_*` test hooks, and it parses
  its geometry cache as integers instead of sourcing it, so environment variables and
  files in the state folder cannot change what the granted app runs.
- Limit: macOS does not re-check the bundle's resources on every launch, so a process
  running as you could still edit the bundle itself. `doctor` catches that through the
  signature check; run it at the start of every session (the skill and agent do).
- To remove everything: delete the helper app, remove it from the Privacy lists
  (`tccutil reset All local.foundry.iphone-mirror` does all three for the default bundle ID), and
  delete `$HOME/Library/Caches/foundry-iphone-mirror` and
  `$HOME/Library/Application Support/foundry-iphone-mirror`.

## How to use it

### The loop: screenshot, read, act, verify

```bash
iphone-mirror shot /tmp/iphone-shots/01.png    # prints: path WxHpx window WxHpt
# Read the PNG, pick a target by its pixel position (top-left origin)
iphone-mirror tap 326 700                      # pixels from THAT screenshot
iphone-mirror shot /tmp/iphone-shots/02.png    # verify the screen changed
```

The client converts screenshot pixels to screen points using the geometry recorded by
the last `shot` (Retina 2x handled). Never send two actions without a screenshot
between them: iOS animates and scrolls, so stale coordinates miss. `iphone-mirror map
<px> <py>` prints where a tap would land without touching the phone.

### From Claude Code

- **Ask in plain words** ("open Settings on my iPhone and turn on Dark Mode", or "is my
  setup ready to test on my real iPhone?"). The `iphone-mirror` skill is meant to load
  on these phrasings, but the model may call the `iphone_*` MCP tools directly instead,
  so those tool descriptions carry the same core rules: run `iphone_doctor` first, stop
  on any FAIL, and act on the phone only for a task you asked for. If you want the full
  loop for sure, say "use the iphone-mirror skill".
- **Delegate long tasks** to the subagent: "Use the iphone-driver agent to walk
  through sign-up in my TestFlight build and screenshot each step." You get back an
  outcome, a step list and evidence paths, not 40 screenshots.
- **MCP tools** are available as `mcp__plugin_foundry-iphone-mirror_iphone__iphone_screenshot`,
  `..._iphone_tap`, `..._iphone_swipe`, `..._iphone_type`, `..._iphone_key`,
  `..._iphone_home`, `..._iphone_doctor`, `..._iphone_open`, `..._iphone_info`,
  `..._iphone_tapxy`. The screenshot comes back inline as an image.

### Real-device QA example

Write acceptance checks first, then run one loop per check and keep a screenshot as
evidence:

```text
Use the iphone-driver agent. App: <your-app> (installed from TestFlight).
Checks:
1. Launch shows the welcome screen with a "Get started" button.
2. Sign up with test account test-user-01 reaches the Home tab.
3. Home tab shows "Hi, test-user-01".
Save one screenshot per check as /tmp/iphone-shots/qa-<n>.png and report pass/fail per check.
```

## Limits

- **iPhone Mirroring must be open, connected and showing the phone.** If the phone is
  unlocked and in use, Mirroring shows "iPhone in Use" and cannot drive it: lock the
  phone. If the session drops, a human may need to approve on the device again.
- **Coordinate taps from screenshots, not element selectors.** There is no
  accessibility tree of the iOS app. Accuracy depends on the model reading the
  screenshot; small or crowded targets can miss, which is why every action is verified.
- **One phone, one action at a time.** Mirroring connects one iPhone to one Mac. The
  client holds a lock, so parallel callers queue.
- **The Mac session must be logged in and unlocked.** A Mac with no display attached
  may capture nothing; use a display or a dummy HDMI plug.
- **Some phone features do not mirror.** The camera, and some protected or
  DRM screens, appear blank or are blocked. Face ID prompts must be answered on the
  phone.
- **Gestures are basic.** Tap, drag-swipe and the home swipe. No multi-touch (pinch,
  rotate), no long-press primitive, no hardware buttons.
- **Typing sends literal keystrokes** that show on the mirror. Do not type secrets.
- **Rebuilding the helper app resets its grants.** After a plugin update, `doctor`
  warns if your helper was built from an older worker; rebuild and re-approve when
  convenient.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `helper app missing` | `iphone-mirror build` |
| `is not running` | `iphone-mirror open`, then approve on the phone |
| `has no window` | the Mirroring window is closed or minimized; bring it back on screen |
| `window geometry unreadable` / Accessibility FAIL | add the helper app (not your terminal) under Accessibility |
| `System Events did not answer in 8s` | allow the helper app to control System Events (the prompt, or Privacy & Security > Automation) |
| `screenshot empty` / Screen Recording FAIL | add the helper app under Screen Recording |
| `cliclick not found` | `brew install cliclick`, then `iphone-mirror build` and re-approve |
| `no screenshot recorded since the last geometry read` | run `shot` before `tap` or `swipe` (`info` resets the mapping) |
| taps land in the wrong spot | the window moved or resized: take a fresh `shot` |
| LaunchServices error -10669 | the bundle is damaged: `iphone-mirror build` |
| `worker timeout` | the helper did not finish in 30s; check `doctor`, or raise `IPHONE_MIRROR_TIMEOUT` |

## Files

```
foundry-iphone-mirror/
  .claude-plugin/plugin.json
  .mcp.json                     registers the "iphone" MCP server via ${CLAUDE_PLUGIN_ROOT}
  bin/iphone-mirror             the CLI (added to PATH while the plugin is enabled)
  engine/worker.sh              privileged worker, copied into the helper app
  engine/launcher.c             helper app main executable (execs worker.sh)
  engine/build-helper-app.sh    build + sign + register the helper app
  mcp/server.py                 stdlib MCP server over the CLI
  skills/iphone-mirror/SKILL.md the loop and rules
  agents/iphone-driver.md       the delegation subagent
  tests/                        unit tests (no phone needed)
```

State lives in `$HOME/Library/Caches/foundry-iphone-mirror` (geometry cache, IPC
files, default screenshots). It is fixed on purpose: LaunchServices does not pass
environment variables to the helper app, so the client, the MCP server and the helper
all derive it from `$HOME`. `IPHONE_MIRROR_STATE` is honored only by the unit tests,
which run the worker in-process.

## Tests

No phone, window or permission is needed: geometry is faked and `cliclick` is replaced
by a recorder. Inside the test files, the worker is run directly instead of through the
helper app.

```bash
cd <plugin-dir> && python3 -m unittest discover -s tests -v
```

Covers pixel-to-point math (including Retina 2x and bounds), worker guards, the
geom-cache injection guard, test hooks being ignored inside a bundle, client argument
validation and locking, no `open -a "iPhone Mirroring"` when the helper app is missing
(a stub `open` on PATH), the fixed state dir, the doctor naming all three grants,
the safety rules in the MCP tool descriptions, the launcher (compiled with clang, skipped without it), and the
MCP protocol (initialize, tools/list, tools/call, inline PNG, errors).

## Changes from the source

Ported from our production plugin. What changed and why:

- Absolute paths, a personal helper app name and a personal bundle ID were replaced by
  `$HOME` defaults plus `--app`, `--bundle-id` and `--name` build options.
- State moved from a shared `/tmp` folder to a per-user `~/Library/Caches` folder.
- The worker now parses its geometry cache instead of `source`-ing it, ignores test
  hooks inside the bundle, validates coordinates and bounds, and no longer echoes typed
  text back. A helper-function bug that could swallow error messages was fixed.
- The client adds a lock (one action at a time), a `map` dry-run, and a `build` command.
  It checks that the helper app exists before raising iPhone Mirroring, so a call that
  is bound to fail never switches your screen to the phone, and `info` no longer raises
  the window at all.
  `doctor` adds macOS version, signature and version-drift checks.
- `cliclick`'s location is recorded at build time, since apps launched by LaunchServices
  get a minimal PATH.
- The MCP server was rewritten on the standard library (no `mcp` package needed).
- The System Events call that reads the window is now bounded (8 seconds), and the
  Automation grant it needs is documented. The source relied on a one-time prompt that
  could leave a fresh install hanging with no explanation.

## License

MIT. Part of the [AI Foundry marketplace](https://github.com/ai-foundry-byu/foundry-marketplace).
