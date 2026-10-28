# Device QA matrix: <PASS | FAIL | INCONCLUSIVE>

Build under test: <app id + version + build number>
Run date: <YYYY-MM-DD>
Stories file: <path>

| story | ios | android | windows | macos | iphone | web-mobile |
|---|---|---|---|---|---|---|
| S1 Returning user signs in | PASS | FAIL | - | - | - | PASS |
| S2 Export monthly report | - | - | PASS | INCONCLUSIVE | - | - |

`-` means the story did not list that device. NOT_RUN means it did, and the lane never reported.

## Lanes
- ios: device `iPhone 16, iOS 18.x Simulator`, agent ios-qa, evidence `.qa/ios/`
- android: device `Pixel 7 emulator API 34`, agent android-qa, evidence `.qa/android/`

## Not passing (one line each, with evidence)
- S1 on android: FAIL. Crash after Sign in, NullPointerException in LoginViewModel.submit (.qa/android/S1-logcat-crash.txt)
- S2 on macos: INCONCLUSIVE. Save panel did not expose its file-name field to Accessibility (.qa/macos/S2-03-save-panel.png)

## Verdict rule
Any FAIL makes the matrix FAIL. Otherwise any INCONCLUSIVE or NOT_RUN makes it INCONCLUSIVE. Only an all-PASS matrix is PASS.
