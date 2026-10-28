# {{PROJECT_NAME}}

**Owner:** {{OWNER}} · **Started:** {{DATE}} · **Slug:** `{{SLUG}}`

TODO: one sentence. Who is this for, and what can they do with it that they cannot do today?

## Live

- Production URL: TODO: https://<your-app>.example.com (or "not deployed yet")
- Repo: TODO: https://github.com/<org>/<repo>

## The artifact set (foundry-sdlc)

| Stage | File | What it holds |
|---|---|---|
| 1 Requirements | `REQUIREMENTS.md` | Every ask, verbatim, with an id (R-01), source and date; the audit of what already exists |
| 1-3 Decisions | `DECISIONS.md` | Every human decision, verbatim, and what it authorizes |
| 2 PRD | `PRD.md` | The product spec; user stories inline as `**US-01. Title.**` plus numbered criteria |
| 2 Stories | `stories.json` | Compiled from the PRD by `tools/gen_stories.py`. Never hand-edit titles or criteria |
| 3 Workplan | `WORKPLAN.md` | Task table, milestones, what is blocked on a human |
| 6 Visual QA | `done-journey.yaml` | The deterministic journey the done gate runs on the deployed build |
| 7 Ship | `CHANGELOG.md` | One dated entry per ship, newest first |

Check where the project is: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdlc_stage.py" .` (or ask the agent to run the `foundry-sdlc:sdlc` skill).
