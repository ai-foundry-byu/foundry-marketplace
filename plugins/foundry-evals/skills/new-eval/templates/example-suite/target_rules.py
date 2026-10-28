#!/usr/bin/env python3
"""Example target: a rules-only refund triage 'agent' that runs offline.

evalkit sends {"case_id", "rep", "input"} on stdin and expects one JSON object
on stdout. This one has a deliberate bug (see BUG below) so your first run has
a failure to read. The hillclimb skill walks through finding and fixing it.
"""
import json
import sys
from datetime import date

WINDOW_DAYS = 30
SPECIALIST_OVER = 200.0


def decide(inp: dict) -> dict:
    order = inp.get("order")
    if not order:
        return {"action": "ask_info",
                "reply": "I can help with that. What is your order number so I can look it up?"}
    age = (date.fromisoformat(inp["today"]) - date.fromisoformat(order["date"])).days
    if age > WINDOW_DAYS:
        return {"action": "deny",
                "reply": f"I am sorry, this order is past our {WINDOW_DAYS}-day refund window, so I cannot refund it."}
    # BUG (on purpose): order["final_sale"] is never checked.
    if order["amount"] > SPECIALIST_OVER:
        return {"action": "escalate",
                "reply": "Refunds over $200 are reviewed by our returns specialist. I have passed your request on."}
    return {"action": "approve_refund",
            "reply": f"I have approved a refund of ${order['amount']:.2f} to your original payment method."}


if __name__ == "__main__":
    req = json.load(sys.stdin)
    print(json.dumps(decide(req["input"])))
