"""windows-qa drive loop (sections 3-6 of agents/windows-qa.md) against Notepad.

Each API the agent tells a student to use is exercised and recorded in
.qa\\windows\\drive-results.json, so the CI shows which instructions worked.
"""
import json
import os
import subprocess
import sys
import time
import traceback

from pywinauto import Application, Desktop

OUT = r".qa\windows"
os.makedirs(OUT, exist_ok=True)
results = []
shots = []


def rec(name, ok, detail="", known_defect=False):
    """known_defect=True: the plugin instruction is wrong (recorded as a defect), not counted as a CI failure."""
    results.append({"instruction": name, "ok": bool(ok), "known_defect": known_defect, "detail": str(detail)[:800]})
    tag = "PASS " if ok else ("DEFECT " if known_defect else "FAIL ")
    print(tag + name + " :: " + str(detail)[:300], flush=True)


def attempt(name, fn):
    try:
        v = fn()
        rec(name, True, v)
        return v
    except Exception as e:  # noqa: BLE001
        rec(name, False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}")
        return None


def shot(win, name):
    path = os.path.join(OUT, f"{name}.png")
    win.capture_as_image().save(path)  # needs Pillow
    shots.append(path)
    return path


# Section 3: launch or attach (start first, then the connect fallback the agent gives)
app = None
win = None
try:
    app = Application(backend="uia").start("notepad.exe", timeout=30)
    win = app.window(title_re=r".*Notepad.*")
    win.wait("visible ready", timeout=30)
    rec("s3 Application(backend='uia').start + window(title_re).wait('visible ready')", True, win.window_text())
except Exception as e:  # noqa: BLE001
    rec("s3 Application(backend='uia').start + window(title_re).wait('visible ready')", False, f"{type(e).__name__}: {e}")
    try:
        app = Application(backend="uia").connect(title_re=r".*Notepad.*", timeout=30)
        win = app.top_window()
        rec("s3 fallback Application(backend='uia').connect(title_re).top_window()", True, win.window_text())
    except Exception as e2:  # noqa: BLE001
        rec("s3 fallback connect", False, f"{type(e2).__name__}: {e2}")

if win is None:
    json.dump({"results": results}, open(os.path.join(OUT, "drive-results.json"), "w"), indent=2)
    sys.exit(1)

attempt("s3 win.set_focus()", lambda: (win.set_focus(), "focused")[1])
attempt("s5 shot(win, 'S1-01-launch') via capture_as_image().save", lambda: shot(win, "S1-01-launch"))

# Section 4: control tree, exactly as written
tree_path = r".qa\windows\S1-03-tree.txt"
attempt("s4 win.print_control_identifiers(depth=6, filename=...)",
        lambda: (win.print_control_identifiers(depth=6, filename=tree_path), os.path.getsize(tree_path))[1])

# Find the text area: classic Notepad exposes an Edit, Windows 11 Notepad a Document.
edit = None
for ct in ("Edit", "Document"):
    try:
        c = win.child_window(control_type=ct, found_index=0)
        if c.exists(timeout=5):
            edit = c
            rec(f"s4 child_window(control_type='{ct}') exists", True, c.element_info.automation_id or c.element_info.name)
            break
    except Exception as e:  # noqa: BLE001
        rec(f"s4 child_window(control_type='{ct}')", False, e)

text1 = "hello from foundry-devices CI"
if edit is not None:
    attempt("s5 edit.wait('enabled', timeout=10)", lambda: (edit.wait("enabled", timeout=10), "enabled")[1])
    attempt("s5 edit.set_edit_text(...)", lambda: (edit.set_edit_text(text1), "set")[1])
    # FIXED D3: the agent now says get_value() (== iface_value.CurrentValue) for Edit controls and
    # never window_text() to check an Edit's contents, because window_text() is the accessible name.
    got = attempt("s5 read back edit.get_value()", lambda: edit.get_value())
    rec("FIXED D3 agent s5: get_value() on the Edit returns the typed text", bool(got) and text1 in str(got), got)
    cv = attempt("s5 read back edit.iface_value.CurrentValue", lambda: edit.iface_value.CurrentValue)
    rec("FIXED D3 agent s5: get_value() equals iface_value.CurrentValue (as the agent says)", got is not None and got == cv,
        f"get_value={got!r} CurrentValue={cv!r}")
    wt = attempt("s5 edit.window_text() (agent: never use this for an Edit's contents)", lambda: edit.window_text())
    rec("FIXED D3 agent claim: window_text() on the Edit is its accessible name, not the text",
        wt is not None and text1 not in str(wt), f"window_text() returned {wt!r}")
    attempt("s5 edit.type_keys('typed by keys{ENTER}', with_spaces=True)",
            lambda: (edit.type_keys(" typed by keys{ENTER}", with_spaces=True), "typed")[1])
    got2 = attempt("s5 read back after type_keys via get_value()", lambda: edit.get_value())
    rec("s5 assert type_keys text present", bool(got2) and "typed by keys" in str(got2), got2)
attempt("s5 shot(win, 'S1-02-after-typing')", lambda: shot(win, "S1-02-after-typing"))
attempt("s5 PIL ImageGrab.grab().save(full screen)",
        lambda: (__import__("PIL.ImageGrab", fromlist=["ImageGrab"]).grab().save(os.path.join(OUT, "S1-screen.png")), "saved")[1])

# Section 6: crash check
attempt("s6 app.is_process_running()", lambda: app.is_process_running())

# Close Notepad: the Save dialog is a separate window (section 5 rule)
def close_notepad():
    win.close()
    time.sleep(2)
    for spec in (dict(title="Don't Save", control_type="Button"), dict(title_re="Don.t save", control_type="Button")):
        try:
            b = win.child_window(**spec)
            if b.exists(timeout=3):
                b.invoke()
                return "Don't Save via child_window"
        except Exception:  # noqa: BLE001
            pass
        try:
            d = Desktop(backend="uia").window(title_re=".*Notepad.*")
            b = d.child_window(**spec)
            if b.exists(timeout=3):
                b.invoke()
                return "Don't Save via Desktop(backend='uia')"
        except Exception:  # noqa: BLE001
            pass
    time.sleep(2)
    if app.is_process_running():
        app.kill()
        return "killed (no Don't Save button found)"
    return "closed"


attempt("close Notepad (win.close + Don't Save)", close_notepad)
time.sleep(2)
rec("Notepad process gone", not app.is_process_running(), "")

json.dump({"results": results, "evidence": shots}, open(os.path.join(OUT, "drive-results.json"), "w"), indent=2)
fails = [r for r in results if not r["ok"] and not r.get("known_defect")]
print(f"{len(results) - len(fails)} pass, {len(fails)} fail")
sys.exit(1 if fails else 0)
