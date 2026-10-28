---
name: new-project
description: Stage 0 of the Foundry SDLC. Scaffold the standard artifact set (README, REQUIREMENTS, DECISIONS, PRD, WORKPLAN, CHANGELOG, stories.json, done-journey.yaml, tools/gen_stories.py) into a new or existing project from the skill's templates. Use when someone says "start a new project", "scaffold this", "set up the project docs", "new app idea", "kick off <name>", or when sdlc_stage.py reports stage 0.
---

# Stage 0: scaffold the artifact set

One scaffolder and one layout for every project, so any agent (or classmate) can open the folder and know where everything is.

## Choose where the artifacts live

- **New idea, no code yet:** a fresh folder, for example `$HOME/projects/<slug>/`. Run `git init` in it right away.
- **Existing code repo:** a `product/` folder at the repo root. This keeps the root clean, and the stage detector and hook look there automatically.

## Run the scaffolder

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/new_project.py" product --name "Study Buddy" --owner "Team 4"
```

What it does:
- It creates `README.md`, `REQUIREMENTS.md`, `DECISIONS.md`, `PRD.md`, `WORKPLAN.md`, `CHANGELOG.md`, `stories.json` (`[]`), `stories.schema.json` and `done-journey.yaml`.
- It copies `tools/gen_stories.py` into the project, so CI can run `--check` on machines that do not have the plugin. Pass `--no-tools` to skip the copy.
- It never overwrites an existing file. It prints `skipped (exists)` instead. `--force` overwrites, so use it only on a folder you just created.
- It fills `{{PROJECT_NAME}}`, `{{SLUG}}`, `{{DATE}}` and `{{OWNER}}`. Everything a human must still write is marked `TODO:`.

## Then do these four things

1. Fill the README's one sentence ("who is this for, and what can they do that they cannot do today"). If you cannot write it yet, that is fine: stage 1 will tell you.
2. Paste `${CLAUDE_SKILL_DIR}/references/CLAUDE-md-snippet.md` into the project's `CLAUDE.md`, creating the file if needed. These are the norms every agent in the project follows.
3. Add a CI step that fails when stories drift from the PRD:
   ```bash
   python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --check
   ```
4. Commit: `git add product CLAUDE.md && git commit -m "Scaffold foundry-sdlc artifact set"`.

## Acceptance check

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .
```

This must report `Current stage: 1 Gather requirements`. If it says 0, a file is missing, and the report names it.

Next: the `gather-requirements` skill.
