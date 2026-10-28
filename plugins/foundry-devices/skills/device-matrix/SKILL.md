---
name: device-matrix
description: Decide which device QA agents to run for a set of user stories, run them as parallel lanes (ios-qa, android-qa, windows-qa, macos-qa, a real iPhone, web), and merge their results into one PASS/FAIL/INCONCLUSIVE matrix. Use when someone says "test this on every device", "which devices do we need to test", "run the device matrix", "cross-platform QA", "test on iOS and Android", or when user stories carry a devices[] field.
---

# Device matrix

A user story says which devices it must work on. This skill turns that into lanes (one QA agent per platform), runs the lanes in parallel where the host allows, and merges the evidence into one matrix with one verdict.

Maturity: **new**. The planner and report script (`scripts/device_matrix.py`) are unit-tested; the end-to-end multi-lane run has not been battle-tested by the cohort yet. Please report back what broke.

## 1. Give every story a devices[] field

Stories live in a JSON file (a list, or `{"stories": [...]}`), or a folder of `*.json` files. Copy `${CLAUDE_PLUGIN_ROOT}/templates/stories.example.json` to start.

```json
{"id": "S1", "title": "Returning user signs in",
 "devices": ["ios", "android:pixel_7", "web-mobile"],
 "steps": ["Open the app", "Enter the test account", "Tap Sign in"],
 "expect": ["Home screen shows Welcome", "No error banner"]}
```

Device names (aliases in parentheses). Anything after a colon is a profile hint passed to the lane, for example `android:pixel_7` or `ios:iPad`.

| device | lane runs with | needs host |
|---|---|---|
| `ios` (`ios-sim`, `iphone-sim`, `ipad-sim`) | **ios-qa** agent, iOS Simulator | macOS with Xcode |
| `iphone` (`iphone-real`, `ios-device`) | **foundry-iphone-mirror** plugin, real iPhone over iPhone Mirroring | macOS |
| `android` (`android-emulator`, `android-device`) | **android-qa** agent | macOS, Linux or Windows |
| `windows` (`win`) | **windows-qa** agent | native Windows |
| `macos` (`mac`) | **macos-qa** agent | macOS |
| `web` (`web-desktop`) | **foundry-qa** plugin, Playwright desktop browsers | any |
| `web-mobile` (`mobile-web`) | **foundry-qa** plugin, Playwright mobile emulation | any |

How to choose devices for a story (write the reason into the story if it is not obvious):

- Native mobile app: `ios` and `android` at minimum. Add `iphone` when the story touches camera, push delivery, biometrics, Bluetooth, performance or anything the simulator fakes.
- Responsive web app: `web` and `web-mobile`. Add `ios` only if Safari-on-iOS specifics matter (and then test Safari in the simulator, which ios-qa can open with `xcrun simctl openurl`).
- Desktop app: each OS you ship to. Electron counts as both `windows` and `macos` if you ship both.
- Pure API or backend story: no devices. Leave `devices` empty; the planner lists it so nobody mistakes "not device-tested" for "passed".

## 2. Plan the lanes

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/device_matrix.py" plan stories.json
```

Output: one row per lane with its agent, whether it can run **on this machine**, its stories and profiles. It also lists unknown device names (typos like `andriod`) and stories with no devices. Fix unknown names before running anything.

A lane that cannot run here (for example `windows` on a Mac) is not skipped silently: run it on a machine that can, or let it report NOT_RUN, which makes the matrix INCONCLUSIVE.

## 3. Run the lanes in parallel

Create the result skeletons, one `results.json` per lane, all stories `NOT_RUN`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/device_matrix.py" init stories.json --qa .qa
```

Then start one subagent per runnable lane **in the same turn** so they run concurrently. Give each one the same contract:

> You are the `<lane>` lane. Stories: `<ids>` from `stories.json`. Profile hints: `<profiles>`. Build under test: `<path or version>`. Use test accounts only. Run your doctor first and stop if NOT READY. Write evidence under `.qa/<lane>/` and fill in `.qa/<lane>/results.json` with PASS, FAIL or INCONCLUSIVE per story, with evidence paths and one-line notes.

Parallelism limits, so lanes do not fight:

- **One machine, many lanes is fine** when they use different devices: ios-qa (simulator), android-qa (emulator) and macos-qa can run side by side on one Mac, if it has the memory. An emulator and a simulator together want roughly 8 GB of free RAM; check before starting a third heavy lane.
- **Two lanes must not share one device.** Two Android stories in parallel need two emulators (each with its own `-s <serial>`), or run them in sequence in one lane.
- **macos-qa and windows-qa own the real mouse and keyboard** when they use real input. Run at most one input-driving desktop lane per machine, and nothing else that types into the GUI at the same time.
- The real-iPhone lane drives one physical phone: one lane at a time.

## 4. Merge into one matrix

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/device_matrix.py" report stories.json --qa .qa
```

It reads every lane's `results.json`, writes `.qa/matrix.md`, prints it, and exits `0` PASS, `1` FAIL, `3` INCONCLUSIVE (use the exit code in CI). Verdict rules:

- Any FAIL anywhere: **FAIL**.
- Otherwise any INCONCLUSIVE, any NOT_RUN, or a lane that never wrote results: **INCONCLUSIVE**.
- Only when every story passed on every device it lists: **PASS**.
- A status that is not one of PASS, FAIL, INCONCLUSIVE, NOT_RUN (for example "LGTM") is counted as INCONCLUSIVE.

The shape each lane writes (see `${CLAUDE_PLUGIN_ROOT}/templates/results.example.json`):

```json
{"lane": "android", "agent": "android-qa", "device": "Pixel 7 emulator, API 34", "build": "1.4.2 (87)",
 "stories": [{"id": "S1", "status": "FAIL", "evidence": [".qa/android/S1-crash.txt"], "notes": "NPE on Sign in"}]}
```

`${CLAUDE_PLUGIN_ROOT}/templates/matrix.template.md` shows what a finished matrix looks like, if you want to write one by hand.

## 5. Acceptance checks before you call it done

- `plan` shows no unknown device names, and every story that should be device-tested has devices.
- Every lane wrote a `doctor.json` and a `results.json`.
- Every PASS cell has at least one evidence file that exists. Spot-check: `ls` the paths in the report.
- Every FAIL has a reproduction note (steps, attempt count) and the log or crash file.
- Every INCONCLUSIVE says what blocked it and what would unblock it.
- `.qa/` is in `.gitignore` (screenshots can contain test data), unless the team chose to commit evidence.

## Maestro flow templates

`${CLAUDE_PLUGIN_ROOT}/templates/maestro/android-sign-in.yaml` and `ios-sign-in.yaml` are working starting points for a sign-in story: fresh state, wait for the screen, type from `-e` variables, tap, assert, screenshot. Copy one per story into `.qa/<lane>/flows/` and change the `appId`, ids and texts.
