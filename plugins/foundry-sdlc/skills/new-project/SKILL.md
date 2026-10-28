---
name: new-project
description: Stage 0 of the Foundry SDLC. Scaffold the standard artifact set (README, REQUIREMENTS, DECISIONS, PRD, WORKPLAN, CHANGELOG, stories.json, done-journey.yaml) into a new or existing project from the skill's templates, plus tools/gen_stories.py and a CI check at the project root. Use when someone says "start a new project", "scaffold this", "set up the project docs", "set it up the right way", "new app idea", "kick off <name>", or when sdlc_stage.py reports stage 0.
---

# Stage 0: scaffold the artifact set

One scaffolder and one layout for every project, so any agent (or classmate) can open the folder and know where everything is.

## Rules (MUST)

1. **Name.** Use the name the user gave. If they gave none, leave `--name` out: the script derives it from the project folder (`study-group-finder` becomes "Study Group Finder") and prints it. Ask only if the folder name is meaningless (`tmp`, `new-folder`). Never reuse a name or owner from an example.
2. **Owner.** Use the owner the user gave, or leave `--owner` out (the README then says `TODO: team or owner`). Never invent one.
3. **Never overwrite.** Run without `--force` on any folder that already has files.

## Choose where the artifacts live

- **New idea, no code yet:** a fresh folder, for example `$HOME/projects/<slug>/`. Run `git init` in it first, then scaffold into `.`.
- **Existing code repo:** a `product/` folder at the repo root. This keeps the root clean, and the stage detector and hook look there automatically.

## Run the scaffolder

From the project root:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/new_project.py" product --name "<Project Name>" --owner "<Owner>"
```

What it does:
- It creates `README.md`, `REQUIREMENTS.md`, `DECISIONS.md`, `PRD.md`, `WORKPLAN.md`, `CHANGELOG.md`, `stories.schema.json`, `done-journey.yaml`, and `stories.json` compiled from the new PRD, so the story check passes from the first commit.
- At the **project root** (the git root, else the folder above `product/`), it copies `tools/gen_stories.py` and writes `.github/workflows/stories.yml`, which runs the story check in CI. `--no-tools` and `--no-ci` skip them; `--root <dir>` sets the root by hand.
- It never overwrites an existing file. It prints `skipped (exists)` instead.
- It prints the exact stories command for this layout. Every skill uses the same form, from the project root:
  ```bash
  python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json
  ```
  (With the artifacts at the root: `--prd PRD.md --out stories.json`.)

## Then do these three things

1. Fill the README's one sentence ("who is this for, and what can they do that they cannot do today"). If you cannot write it yet, that is fine: stage 1 will tell you.
2. Paste `${CLAUDE_SKILL_DIR}/references/CLAUDE-md-snippet.md` (everything below its line) into the project's `CLAUDE.md`, creating the file if needed. If the artifacts are at the root, drop `product/` from its stories command.
3. Commit: `git add -A && git commit -m "Scaffold foundry-sdlc artifact set"`.

## Acceptance check

```bash
python3 tools/gen_stories.py --prd product/PRD.md --out product/stories.json --check
```

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" .
```

The first must exit 0. The second must report `Current stage: 1 Gather requirements`. If it says 0, a file is missing, and the report names it.

Next: the `gather-requirements` skill.
