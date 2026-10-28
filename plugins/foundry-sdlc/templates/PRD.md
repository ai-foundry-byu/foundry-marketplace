# {{PROJECT_NAME}}: PRD

**Version:** 0.1 ({{DATE}}) · **Owner:** {{OWNER}} · **Requirements:** `REQUIREMENTS.md` · **Decisions:** `DECISIONS.md`

Rules for this file:
- User stories live here, inline, as `**US-01. Title.**` followed by numbered acceptance criteria. `tools/gen_stories.py` compiles them into `stories.json`. Never write stories anywhere else.
- Every acceptance criterion is observable: a person or a browser can see it pass or fail. "Fast" is not a criterion; "the list paints in under 1.5 s on a phone" is.
- Every story cites the R-ids it covers. Every R-id in `REQUIREMENTS.md` is covered by a story or dropped by a decision.
- Unfilled text starts with the word TODO and a colon. The stage check fails while any remain.

## 0. The short version

TODO: five lines. Who the user is, the one job this does for them, what ships first, how we will know it worked, what we are deliberately not building.

## 1. Problem and user

- **User:** TODO: a specific person (role, context, device, how often they show up). Name the persona file if you have one.
- **Problem today:** TODO: what they do now, what it costs them, evidence (quotes from REQUIREMENTS.md by R-id).
- **Promise:** TODO: one sentence they would agree with.

## 2. Success metrics

| Metric | Baseline today | Target | How it is measured |
|---|---|---|---|
| TODO: weekly active students | TODO: 0 | TODO: 20 by week 4 | TODO: server-side event `session_started`, test accounts excluded |

## 3. Product principles (binding)

1. TODO: e.g. Phone first: every story passes at 390x844 before desktop.
2. TODO: e.g. Honest states: an empty, loading or failed state says which one it is.

## 4. Scope

- **In (MVP):** TODO: the smallest set of stories that delivers the promise.
- **Later:** TODO: stories written now, status PARKED until a decision opens them.
- **Non-goals:** TODO: what we will not build, and why.

## 5. User stories

Group by area or rollout window. Optional lines right under a heading: `Surfaces:` (routes or screens), `Devices:` (viewport profiles), `Waits on:` (story ids, R-ids or D-ids). Indented bullets continue the criterion above them.

### 5.1 TODO: area name

**US-01. TODO: a student does the one core thing.** (R-01)
Surfaces: /
Devices: phone-390x844, desktop-1440x900
1. TODO: observable criterion one.
2. TODO: observable criterion two, with a number in it.
   - TODO: an edge case that belongs to criterion two.
3. TODO: the empty, loading and error states each say which state they are.

## 6. Architecture decisions that bind the build

| Decision | Choice | Why | Alternatives rejected |
|---|---|---|---|
| TODO: data store | TODO: | TODO: | TODO: |

## 7. Rollout

### 7.1 MVP and order

TODO: which stories ship first, in which order, behind which flags.

### 7.2 Feature flags

| Flag | Default | Stories | Who may flip it |
|---|---|---|---|
| TODO: `feature_x` | off | US-01 | TODO: product owner |

### 7.3 What "used fully" means (per-feature graduation gates)

A feature graduates only when real use proves it, and a human makes the call. Measure server-side events only. Test accounts never count.

| Feature | 1. Habit | 2. Action | 3. Substitution | 4. Critical sources stay healthy | Feature-specific |
|---|---|---|---|---|---|
| TODO: feature | TODO: opened on 4 of 7 days | TODO: 10 completed actions on 3 days | TODO: the old workaround drops by half (n/a if the baseline is under 10) | TODO: the API it reads was up 95% of the window | TODO: zero lost submissions |

The gate pauses its clock while a critical source is down, and complaints ("this is wrong") become tickets tagged with the feature.

### 7.4 Ship ritual (every feature)

Follow the `foundry-sdlc:ship` skill. Only say "done" after the done gate passes on the deployed build.

## 8. Metrics and risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TODO: | TODO: | TODO: | TODO: |

## Appendix A. Addressed critiques

The `prd-critic` agent's numbered findings, each with what you did. Never delete a rejected critique; say why you rejected it.

| # | Severity | Critique (short) | Decision | What changed |
|---|---|---|---|---|
| TODO: C1 | TODO: high | TODO: | TODO: accepted, partly, rejected | TODO: section or story id |

## Appendix B. Where I push back

TODO: any ask you think is wrong, with evidence and the better path. A human decides; record the answer in DECISIONS.md.
