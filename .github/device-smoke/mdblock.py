"""Print a fenced code block from a plugin markdown file, verbatim, so CI runs the
exact text an agent tells a student to run.

    mdblock.py FILE LANG NEEDLE [--from TEXT] [--to TEXT]

Picks the first ```LANG block (indented fences allowed, e.g. inside a list item)
whose body contains NEEDLE, removes the fence's indentation, and optionally keeps
only the lines from the first one containing --from through the first one after it
containing --to. Exits 1 if no block matches.
"""
import argparse
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("lang")
ap.add_argument("needle")
ap.add_argument("--from", dest="start")
ap.add_argument("--to", dest="end")
a = ap.parse_args()

text = open(a.file, encoding="utf-8").read()
for m in re.finditer(r"(?ms)^([ \t]*)```" + re.escape(a.lang) + r"[ \t]*\n(.*?)^\1```", text):
    indent, body = m.group(1), m.group(2)
    if a.needle not in body:
        continue
    lines = [ln[len(indent):] if ln.startswith(indent) else ln for ln in body.splitlines()]
    if a.start:
        i = next((k for k, ln in enumerate(lines) if a.start in ln), None)
        if i is None:
            sys.exit(f"--from {a.start!r} not in the block")
        lines = lines[i:]
    if a.end:
        j = next((k for k, ln in enumerate(lines) if a.end in ln), None)
        if j is None:
            sys.exit(f"--to {a.end!r} not in the block")
        lines = lines[: j + 1]
    print("\n".join(lines))
    sys.exit(0)
sys.exit(f"no ```{a.lang} block containing {a.needle!r} in {a.file}")
