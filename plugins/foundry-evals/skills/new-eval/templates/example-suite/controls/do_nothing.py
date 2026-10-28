#!/usr/bin/env python3
"""Negative control: a do-nothing agent. Every suite must score it near zero.

If it scores well, a grader is checking for "nothing happened" without also
checking what the agent said or decided.
"""
import json
import sys

json.load(sys.stdin)
print(json.dumps({"action": "none", "reply": ""}))
