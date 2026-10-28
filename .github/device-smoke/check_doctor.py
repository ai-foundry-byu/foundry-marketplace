"""Assert one fixed doctor behavior from a doctor.json the plugin's doctor.py wrote.

    check_doctor.py DOCTOR_JSON maestro-fix        # D1: Maestro row's fix exports PATH in the same shell
    check_doctor.py DOCTOR_JSON screen-recording   # D9: Screen Recording row is not probed, never OK, never blocks READY
"""
import json
import sys

path, what = sys.argv[1], sys.argv[2]
d = json.load(open(path, encoding="utf-8"))
rows = d["checks"]


def row(fragment):
    hits = [c for c in rows if fragment.lower() in c["name"].lower()]
    if not hits:
        sys.exit(f"no row named like {fragment!r}: {[c['name'] for c in rows]}")
    print(json.dumps(hits[0], indent=2))
    return hits[0]


if what == "maestro-fix":
    m = row("maestro")
    want = 'export PATH="$PATH:$HOME/.maestro/bin"'
    assert want in (m.get("fix") or ""), f"fix line lacks {want!r}"
elif what == "screen-recording":
    s = row("screen recording")
    assert s.get("probed") is False, "probed should be false"
    assert s.get("ok") is False, "ok should be false (unknown is never OK)"
    assert s.get("required") is False, "must not be required"
    print("ready =", d["ready"])
    assert d["ready"] is True, "an unprobed optional row must not block READY"
else:
    sys.exit(f"unknown check {what}")
print("OK", what)
