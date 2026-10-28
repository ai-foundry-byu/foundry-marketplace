---
# Machine-read fields (persona_run.py). Everything below the second --- is for the agent.
name: <Persona name, e.g. "Commuter checking in on a phone">
devices: [phone-390x844]            # any of: desktop-1440x900, phone-390x844, tablet-820x1180
patience_seconds: 10                # time to content above this FAILS the story (patience check)
min_tap_target_px: 24               # reported once per device as a warning; 24 = WCAG 2.5.8, 44 = Apple/Google
---

# <Persona name>

## Who they are
One paragraph. Role, context, how often they use the app, how much they already know.
Base it on real interviews or analytics where you can. Do not use a real person's name or data.

## Where and how they use it
- Device and posture (one thumb on a bus, two monitors at a desk, a shared lab computer)
- Network (fast office Wi-Fi, patchy mobile data)
- Visit length (30 seconds between classes, a two-hour working session)

## What they are trying to get done (top jobs, ranked)
1. ...
2. ...
3. ...

## What makes them give up
- ... (a spinner that never resolves, jargon, a form that loses their input)

## How they judge a screen
The test they run in their head, in their words. Example: "Can I find the next thing in seconds?"

## Accessibility needs (if any)
Screen reader, zoom at 200%, keyboard only, reduced motion, color vision.

## Out of scope for this persona
Stories this persona would never attempt (so failures there are not theirs to report).
