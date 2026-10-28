#!/usr/bin/env python3
"""Example target: the same task done by a model, through the Claude Code CLI.

Point suite.json at it with:  "target": {"command": ["python3", "target_claude.py"], "timeout_s": 180}
or for one run:               evalkit.py run . --target "python3 target_claude.py"

prompt.md is the surface you hill-climb. The model's own JSON reply is passed
through, and the CLI-reported cost goes in _meta.cost_usd so evalkit can sum it.
Set EVALKIT_TARGET_MODEL to pin a model; EVALKIT_CLAUDE_BIN to use another binary.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    req = json.load(sys.stdin)
    system = (HERE / "prompt.md").read_text()
    prompt = f"{system}\n\nThe request:\n{json.dumps(req['input'], indent=2)}"
    cmd = [os.environ.get("EVALKIT_CLAUDE_BIN", "claude"), "-p", prompt, "--output-format", "json"]
    if os.environ.get("EVALKIT_TARGET_MODEL"):
        cmd += ["--model", os.environ["EVALKIT_TARGET_MODEL"]]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=170)
    if p.returncode != 0:
        print(p.stderr[-500:], file=sys.stderr)
        return 1
    envelope = json.loads(p.stdout)
    text = str(envelope.get("result", ""))
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        print(f"model reply had no JSON object: {text[:300]}", file=sys.stderr)
        return 1
    out = json.loads(m.group(0))
    cost = envelope.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        out["_meta"] = {"cost_usd": cost}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
