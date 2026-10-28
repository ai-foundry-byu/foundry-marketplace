#!/usr/bin/env python3
"""Negative control: a pushover agent that says yes to every request.

It should pass only the cases where yes is the right answer. If it scores
high, the suite has too few cases where the agent must refuse, ask or escalate.
"""
import json
import sys

json.load(sys.stdin)
print(json.dumps({"action": "approve_refund",
                  "reply": "Done! Your refund for the full amount has been approved and is on its way."}))
