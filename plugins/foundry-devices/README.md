# foundry-devices

Native and device QA agents, one per platform, so you can grab the one for your target. Each agent is an operating manual that a Claude Code subagent follows: prerequisites, a doctor check it runs first, a drive loop (launch, act, screenshot, read the UI tree, assert, repeat), evidence capture to `.qa/<platform>/`, and a report with PASS, FAIL or INCONCLUSIVE per user story.

## Honest status: read this first

Everything in this plugin is **new**. It was written for this marketplace from official documentation (Apple simctl and System Events, Android SDK, Maestro, pywinauto, Playwright) and best practice. It is **not** generalized from a tool we run in production.

What we do run in production today, for comparison:

- A **real iPhone** driver (iPhone Mirroring on a Mac). That one is proven and lives in its own plugin, **foundry-iphone-mirror**. Use it for stories that need real hardware.
- **Playwright mobile emulation** for web apps, in the **foundry-qa** plugin.

We have nothing proven for the iOS Simulator, Android native, Windows desktop or macOS desktop apps. These agents are our best written plan for those targets. **If you use one, please report back** (open an issue or a pull request on the marketplace repo) with what worked, what broke, and the exact tool versions. Two or three good field reports and we will promote an item to proven.

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
| `ios-qa` | agent | iOS Simulator QA: simctl boot/install/launch/openurl/screenshot/recordVideo/privacy/status_bar, Maestro flows, optional XCUITest | QA / verify | new |
| `android-qa` | agent | Android QA: AVD + emulator, adb install/am start/input/screencap, uiautomator UI tree, logcat crashes, dumpsys, Maestro, optional Appium | QA / verify | new |
| `windows-qa` | agent | Windows desktop QA: pywinauto UIA backend, find by automation id/name, invoke/type, control tree, screenshots, event log; Playwright for web, WinAppDriver/Appium optional | QA / verify | new |
| `macos-qa` | agent | macOS desktop QA: System Events accessibility tree, AXPress, keystroke, screencapture, cliclick, Playwright `_electron` for Electron apps | QA / verify | new |
| `device-matrix` | skill | choose device lanes from each story's `devices[]`, run them in parallel, merge one matrix and verdict | QA / plan + report | new |
| `scripts/doctor.py` | script | preflight per platform (tools present and responding, host OS, permissions), writes `.qa/<platform>/doctor.json` | QA / setup | new (unit-tested) |
| `scripts/uitree.py` | script | read an Android `uiautomator dump`: outline, find by text/id/desc, print a safe `adb shell input tap` for exactly one match | QA / drive | new (unit-tested) |
| `scripts/ax_tree.py` | script | dump, outline, search and AXPress a macOS app's accessibility tree; window bounds for screenshots | QA / drive | new (parsing unit-tested) |
| `scripts/device_matrix.py` | script | `plan`, `init`, `report` for the device matrix | QA / plan + report | new (unit-tested) |
| `templates/maestro/android-sign-in.yaml` | template | Maestro sign-in flow for Android | QA / drive | new |
| `templates/maestro/ios-sign-in.yaml` | template | Maestro sign-in flow for the iOS Simulator | QA / drive | new |
| `templates/stories.example.json` | template | stories with `devices[]` | QA / plan | new |
| `templates/results.example.json` | template | the per-lane results file every agent writes | QA / report | new |
| `templates/matrix.template.md` | template | what a finished matrix looks like | QA / report | new |

There are no hooks in this plugin. Nothing runs unless you ask for it.

## How to use each item

### The agents

Ask for them by name or by task. Claude Code picks the agent from its description, or you can name it:

```text
Use the android-qa agent to test story S1 in stories.json against app/build/outputs/apk/debug/app-debug.apk with the test account in QA_EMAIL / QA_PASSWORD.
```

Every agent does the same four things in order:

1. **Doctor**: runs `scripts/doctor.py --platform <p>` and reports READY or the exact fixes. It stops if not ready.
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/device_matrix.py" plan stories.json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/device_matrix.py" init stories.json --qa .qa
# ... one subagent per lane, in parallel ...
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/device_matrix.py" report stories.json --qa .qa   # exit 0 PASS, 1 FAIL, 3 INCONCLUSIVE
```

### The scripts on their own

All scripts are Python 3 standard library only and print `--help`.

```bash
python3 scripts/doctor.py --platform android
python3 scripts/uitree.py tap .qa/android/ui.xml --text "Sign in" --exact --clickable
python3 scripts/ax_tree.py dump "Calculator" --depth 6 --out .qa/macos/ax.json
```

## Requirements

| lane | host | install |
|---|---|---|
| ios-qa | macOS | Xcode (open it once, accept the license, install an iOS runtime); Maestro: `curl -fsSL "https://get.maestro.mobile.dev" \| bash`; a JDK 17+ for Maestro |
| android-qa | macOS, Linux or Windows | Android SDK platform-tools, emulator, cmdline-tools (via Android Studio or `sdkmanager`); Maestro optional; Appium optional (`npm i -g appium`, `appium driver install uiautomator2`) |
| windows-qa | native Windows 10/11 (not WSL) | Python 3, `py -m pip install pywinauto pillow`; Playwright optional for web |
| macos-qa | macOS | Accessibility and Screen Recording permission for the app running Claude Code; `brew install cliclick` optional; Node + `npm i -D playwright` for Electron apps |
| device-matrix | any | Python 3 |

## Tests

```bash
cd plugins/foundry-devices
python3 -m unittest discover -s tests -v
```

The tests cover the logic in the scripts (UI tree parsing and matching, the tap ambiguity guard, matrix planning and verdict rules, doctor timeouts and adb parsing). They do not start a simulator, emulator or desktop app.

## Known limitations

- None of the drive loops have been run end to end by us on real projects yet. Expect some commands to need adjusting for your tool versions. Each agent tells you to check the tool's own `--help` and to note differences in its report.
- `xcrun simctl` subcommand options (for example `privacy` service names) change between Xcode releases.
- `ax_tree.py dump` can be slow on large windows and needs the Accessibility permission; paths go stale as soon as the UI changes.
- Windows automation needs an active, unlocked desktop session, cannot cross the UAC secure desktop, and cannot drive an elevated app from a non-elevated script.
- Apps that draw their own UI (games, some cross-platform toolkits) expose little to any accessibility tree, so agents fall back to screenshots and coordinates with lower confidence.

## License

MIT.
