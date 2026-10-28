# foundry-devices

Native and device QA agents, one per platform, so you can grab the one for your target. Each agent is an operating manual that a Claude Code subagent follows: prerequisites, a doctor check it runs first, a drive loop (launch, act, screenshot, read the UI tree, assert, repeat), evidence capture to `.qa/<platform>/`, and a report with PASS, FAIL or INCONCLUSIVE per user story.

## Honest status: read this first

Everything in this plugin is **new**. It was written for this marketplace from official documentation (Apple simctl and System Events, Android SDK, Maestro, pywinauto, Playwright) and best practice. It is **not** generalized from a tool we run in production.

**What has been run for real.** In October 2026 every script, and the exact commands from every agent's drive loop, ran on GitHub Actions runners against system apps: an Android API 34 emulator (Settings), an iOS 26.2 simulator on Xcode 16.4 (Settings), Windows Server 2025 (classic Notepad) and macOS 26 (Calculator and TextEdit). Final run: 40731526347, green on all four jobs. The screenshots show the real screens. The campaign turned up 11 defects (8 reproduced on a runner, 3 found by reading the code), all fixed in this version (see "CI-verified, and what is not" below).

**What has not.** No student's agent has yet run one of these agents end to end on a real app: building it, installing it and judging real user stories. The app build paths (`xcodebuild`, XCUITest, `gradlew` + `adb install`, Electron), Appium and WinAppDriver, a USB phone, two Android devices at once, arm64 emulator images, Windows 11 Store apps and WSL interop are all untested.

What we do run in production today, for comparison:

- A **real iPhone** driver (iPhone Mirroring on a Mac). That one lives in its own plugin, **foundry-iphone-mirror**. It is a port of a driver we use in production, but this version has not driven a phone yet, so it is labeled new.
- **Playwright mobile emulation** for web apps, in the **foundry-qa** plugin.

The labels come from our test runs on 2026-10-28, recorded in [`evidence/evidence.json`](../../evidence/evidence.json). The iOS Simulator, Android, Windows and macOS agents are **beta**: their drive loops listed below are green on real GitHub Actions runners, which is more than a written plan and less than a field record, since no student's agent has run one on a real app yet. `device-doctor` is **verified** (run live on a Mac and in CI on all four platforms); `device-matrix` is **new** (never run end to end). A script or template carries the label of the skill that ships it. **If you use one, please report back** (open an issue or a pull request on the marketplace repo) with what worked, what broke, and the exact tool versions. Two or three good field reports and we will promote an item to verified.

## Install

Add the marketplace (once):

```text
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install this plugin:

```text
/plugin install foundry-devices@ai-foundry
```

From a shell instead of a session:

```bash
claude plugin install foundry-devices@ai-foundry --scope project
```

## What is inside

| item | type | what it does | SDLC stage | maturity |
|---|---|---|---|---|
| `ios-qa` | agent | iOS Simulator QA: simctl boot/install/launch/openurl/screenshot/recordVideo/privacy/status_bar, Maestro flows, optional XCUITest | QA / verify | beta (drive loop green in CI) |
| `android-qa` | agent | Android QA: AVD + emulator, adb install/am start/input/screencap, uiautomator UI tree, logcat crashes, dumpsys, Maestro, optional Appium | QA / verify | beta (drive loop green in CI) |
| `windows-qa` | agent | Windows desktop QA: pywinauto UIA backend, find by automation id/name, invoke/type, control tree, screenshots, event log; Playwright for web, WinAppDriver/Appium optional | QA / verify | beta (drive loop green in CI) |
| `macos-qa` | agent | macOS desktop QA: System Events accessibility tree, AXPress, keystroke, screencapture, cliclick, Playwright `_electron` for Electron apps | QA / verify | beta (drive loop green in CI) |
| `device-matrix` | skill | choose device lanes from each story's `devices[]`, run them in parallel, merge one matrix and verdict | QA / plan + report | new |
| `device-doctor` | skill | preflight per platform (tools present and responding, host OS, permissions), writes `.qa/<platform>/doctor.json` | QA / setup | verified (live on a Mac, CI-run on all 4 platforms) |
| `android-ui-tree` | skill | read an Android `uiautomator dump`: outline, find by text/id/desc, print a safe `adb -s <serial> shell input tap` for exactly one match | QA / drive | beta (unit-tested on a real dump, CI-run) |
| `macos-ax-tree` | skill | dump, outline, search and AXPress a macOS app's accessibility tree; window bounds for screenshots | QA / drive | beta (parsing unit-tested, CI-run) |
| `skills/device-matrix/scripts/device_matrix.py` | script | `plan`, `init`, `report` for the device matrix | QA / plan + report | new (unit-tested) |
| `skills/device-doctor/scripts/doctor.py` | script | the device-doctor check runner | QA / setup | verified |
| `skills/android-ui-tree/scripts/uitree.py` | script | the android-ui-tree helper | QA / drive | beta |
| `skills/macos-ax-tree/scripts/ax_tree.py` | script | the macos-ax-tree helper | QA / drive | beta |
| `skills/device-matrix/templates/maestro/android-sign-in.yaml` | template | Maestro sign-in flow for Android | QA / drive | beta (run in CI) |
| `skills/device-matrix/templates/maestro/ios-sign-in.yaml` | template | Maestro sign-in flow for the iOS Simulator | QA / drive | beta (run in CI) |
| `skills/device-matrix/templates/stories.example.json` | template | stories with `devices[]` | QA / plan | new |
| `skills/device-matrix/templates/results.example.json` | template | the per-lane results file every agent writes | QA / report | new |
| `skills/device-matrix/templates/matrix.template.md` | template | what a finished matrix looks like | QA / report | new |

Every script and template lives inside the skill that uses it, so each skill folder is complete on its own. The agents carry no files: they find their scripts in the skills they name.

There are no hooks in this plugin. Nothing runs unless you ask for it.

## How to use each item

### The agents

Ask for them by name or by task. Claude Code picks the agent from its description, or you can name it:

```text
Use the android-qa agent to test story S1 in stories.json against app/build/outputs/apk/debug/app-debug.apk with the test account in QA_EMAIL / QA_PASSWORD.
```

Every agent does the same four things in order:

1. **Doctor**: its first command is the device-doctor skill's `doctor.py --platform <p>`, before any check of its own, and it reports READY or the exact fixes. It stops if not ready, and it never writes `doctor.json` itself.
2. **Drive loop** per story: arrange a clean state, act through the UI tree (never guessed coordinates), wait for a condition, screenshot, assert, and look at the screenshot itself.
3. **Evidence** under `.qa/<platform>/`, named `<story>-<NN>-<step>.png` plus tree dumps and logs.
4. **Report**: `.qa/<platform>/results.json` plus a short table. PASS needs evidence, FAIL needs a reproduction note and logs, INCONCLUSIVE says what blocked it.

All agents follow the same safety rules: test accounts and test data only, never production or a real person's account unless you say so in the task, never erase devices or simulators they did not create, secrets only through environment variables.

### The device-matrix skill

```text
/foundry-devices:device-matrix
```

Or just say "run the device matrix for stories.json". The skill walks through:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/device_matrix.py" plan stories.json
python3 "${CLAUDE_SKILL_DIR}/scripts/device_matrix.py" init stories.json --qa .qa
# ... one subagent per lane, in parallel ...
python3 "${CLAUDE_SKILL_DIR}/scripts/device_matrix.py" report stories.json --qa .qa   # exit 0 PASS, 1 FAIL, 3 INCONCLUSIVE
```

### The scripts on their own

All scripts are Python 3 standard library only and print `--help`. From the plugin folder:

```bash
python3 skills/device-doctor/scripts/doctor.py --platform android
python3 skills/android-ui-tree/scripts/uitree.py tap .qa/android/ui.xml --text "Sign in" --exact --clickable --serial emulator-5554
python3 skills/macos-ax-tree/scripts/ax_tree.py dump "Calculator" --depth 8 --out .qa/macos/ax.json
python3 skills/macos-ax-tree/scripts/ax_tree.py find .qa/macos/ax.json --role AXButton --id Seven
python3 skills/macos-ax-tree/scripts/ax_tree.py press "Calculator" <path printed by find>
```

Current Calculator keys have an identifier (`Seven`, `Equals`) and no name, so search them with `--id`. Use the path `find` prints: it changes between macOS versions.

### Install one item on its own

You can copy a single skill or agent instead of installing the whole plugin.

- **Skills, standalone:** `device-matrix`, `device-doctor`, `android-ui-tree`, `macos-ax-tree`. Copy the whole skill folder (for example `skills/device-doctor/`) to `.claude/skills/` in your project or to `~/.claude/skills/`. Each folder holds every script and template it uses.
- **Agents, need skills:** copy the agent file to `.claude/agents/` or `~/.claude/agents/` and copy the skills it names on its `Requires skill:` line:
  - `ios-qa`: `device-doctor`, `device-matrix` (Maestro templates)
  - `android-qa`: `device-doctor`, `android-ui-tree`, `device-matrix` (Maestro templates)
  - `macos-qa`: `device-doctor`, `macos-ax-tree`
  - `windows-qa`: `device-doctor`
- **Plugin only:** nothing. This plugin has no hooks, MCP servers or compiled helpers. The `device-matrix` skill hands lanes to the four agents (and to the foundry-qa and foundry-iphone-mirror plugins), so install those for a full multi-device run.

## Requirements

| lane | host | install |
|---|---|---|
| ios-qa | macOS | Xcode (open it once, accept the license, install an iOS runtime); Maestro: `curl -fsSL "https://get.maestro.mobile.dev" \| bash`, then `export PATH="$PATH:$HOME/.maestro/bin"` in the same shell (the installer only edits rc files) and `maestro --version`; a JDK 17+ for Maestro |
| android-qa | macOS, Linux or Windows | Android SDK platform-tools, emulator, cmdline-tools (via Android Studio or `sdkmanager`); Maestro optional (same install and `export PATH` as ios-qa); Appium optional (`npm i -g appium`, `appium driver install uiautomator2`) |
| windows-qa | native Windows 10/11 (not WSL) | Python 3, `py -m pip install pywinauto pillow`; Playwright optional for web |
| macos-qa | macOS | Accessibility and Screen Recording permission for the app running Claude Code (the doctor probes Accessibility; it cannot probe Screen Recording and shows that row as `??`, unknown); `brew install cliclick` optional; Node + `npm i -D playwright` for Electron apps |
| device-matrix | any | Python 3 |

## Tests

```bash
cd plugins/foundry-devices
python3 -m unittest discover -s tests -v
```

The tests cover the logic in the scripts (UI tree parsing and matching, the clickable-row resolution and the tap serial on a trimmed real API 34 Settings dump, the tap ambiguity guard, the accessibility tree on a trimmed real macOS 26 Calculator dump, matrix planning and verdict rules, doctor timeouts, adb parsing, the Maestro fix line and the unprobed Screen Recording row). They do not start a simulator, emulator or desktop app; the CI run below did.

## CI-verified, and what is not

The device smoke workflow (`.github/workflows/device-smoke.yml` on the `test/device-smoke` branch of the marketplace repo, helpers in `.github/device-smoke/`) runs the plugin's scripts and the agents' commands verbatim on real runners. Run 40731526347 and the code review around it found these, all fixed here:

| # | where | what was wrong | fix |
|---|---|---|---|
| D1 | ios-qa, android-qa, doctor.py | Maestro was not on `PATH` after the install line, in the same shell | `export PATH="$PATH:$HOME/.maestro/bin"` and `maestro --version` after the install, in the agents and the doctor's fix line |
| D2 | uitree.py | `--clickable` found 0 matches on list rows, the skill's own headline example | a text match resolves to its nearest clickable ancestor (the row) and taps its bounds; tested on the real dump |
| D3 | windows-qa | `window_text()` on an Edit returns its name ("Text Editor"), not its text | read Edit contents with `get_value()` |
| D4 | ios-qa | `recordVideo` + `kill -INT` hung forever when SIGINT came before "Recording started" (53 min in CI) | wait for "Recording started", bounded stop, `kill -9` fallback |
| D5 | all four agents | a plain-language session skipped the doctor and hand-wrote `doctor.json` | numbered MUST rules at the top: doctor first, stop on NOT READY, never write `doctor.json` |
| D6 | windows-qa | the PowerShell lookup failed when `CLAUDE_PLUGIN_ROOT` was only an environment variable | the lookup tries `$env:CLAUDE_PLUGIN_ROOT` too |
| D7 | ax_tree.py, macos-qa | the `--name "7"` example does not match current Calculator | examples use `--id Seven`; `find` suggests `--id` when `--name` misses |
| D8 | windows-qa | Get-WinEvent printed an error on a clean log | `-ErrorAction SilentlyContinue`, prints "no matching events" |
| D9 | doctor.py | the unprobed Screen Recording row printed `OK` | it prints `??` (unknown) and is never `ok` |
| D10 | uitree.py | the printed tap had no `-s <serial>` | `--serial`, `$ANDROID_SERIAL` or the only attached device; refuses when several are attached |
| D11 | android-qa | the emulator boot loop ran `adb` without `-s` and could spin forever | the serial is fixed by `-port` up front, every command takes `-s`, the boot wait is bounded |

Verified in CI with the corrected form: D1, D3, D4, D6, D7, D8 (the `SilentlyContinue` call). D2 was checked against the real dump that CI captured. Fixed but not yet re-run on a runner: the D2/D10 script changes as shipped (unit-tested on the real dump), the D11 boot block (`-port`, bounded wait), the D8 "no matching events" branch, and the D5 rules, which need a fresh plain-language agent session to confirm they hold.

## Known limitations

- The drive loops are CI-verified against system apps only. None has been run end to end by a student's agent on a real project yet. Expect some commands to need adjusting for your tool versions. Each agent tells you to check the tool's own `--help` and to note differences in its report.
- `xcrun simctl` subcommand options (for example `privacy` service names) change between Xcode releases.
- `ax_tree.py dump` can be slow on large windows and needs the Accessibility permission; paths go stale as soon as the UI changes.
- Windows automation needs an active, unlocked desktop session, cannot cross the UAC secure desktop, and cannot drive an elevated app from a non-elevated script.
- Apps that draw their own UI (games, some cross-platform toolkits) expose little to any accessibility tree, so agents fall back to screenshots and coordinates with lower confidence.

## License

MIT.
