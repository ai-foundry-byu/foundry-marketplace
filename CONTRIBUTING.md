# Contributing

Anything that helped you build with agents and would help the next cohort is welcome: a skill, an agent, a hook, a script, a template, or a fix to one of ours. Open an issue first if you are not sure where it belongs.

## Add a plugin

### Layout

```
plugins/<your-plugin>/
  .claude-plugin/plugin.json     # manifest (the only file inside .claude-plugin/)
  README.md                      # required, see below
  skills/<skill-name>/SKILL.md   # procedures the agent loads on demand
  skills/<skill-name>/scripts/   # the skill's own scripts (plus scripts/tests/)
  skills/<skill-name>/templates/ # the skill's own templates, examples/, references/
  agents/<agent-name>.md         # subagents with a fresh context; no files of their own
  hooks/hooks.json               # event hooks; scripts under hooks/scripts/
  vendor.json                    # vendored copies, see R2 below
  templates/                     # files users copy into their project
```

Components go at the plugin root, never inside `.claude-plugin/`. A skill refers to its own files as `${CLAUDE_SKILL_DIR}/...`, a hook as `${CLAUDE_PLUGIN_ROOT}/...`, and both refer to the user's project as `${CLAUDE_PROJECT_DIR}`. Never use an absolute path from your machine.

### Item rules: every item works in the plugin and on its own

People install a whole plugin, or copy one skill folder or one agent file. Inside a plugin skill Claude Code fills in both `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}`. In a copied skill only `${CLAUDE_SKILL_DIR}` is filled in; `${CLAUDE_PLUGIN_ROOT}` stays literal text. In a copied agent neither is. These rules follow from that.

- **R1. Skills are self-contained.** Every file a SKILL.md tells the model to run, read or copy lives in that skill's folder (`scripts/`, `templates/`, `examples/`, `references/`) and is written as `"${CLAUDE_SKILL_DIR}/<relative path>"`. A SKILL.md never contains `${CLAUDE_PLUGIN_ROOT}`, except a skill that truly cannot work without the plugin (it needs the plugin's hooks, MCP server, `bin/` on `PATH`, or a compiled helper). That skill puts this line right under its H1 title, then may use `${CLAUDE_PLUGIN_ROOT}`:

  ```
  Install: plugin only. <one-sentence reason>.
  ```

- **R2. One source of truth.** A script or template used by one skill lives in that skill's folder. One used by several skills has one canonical copy (in the main skill, or at plugin level if a hook also uses it) and byte-identical vendored copies in the other skills, recorded in `plugins/<plugin>/vendor.json` as `{"<copy path>": "<canonical path>"}`, both relative to the plugin root. A vendored Python script also vendors every sibling module it imports. Scripts find their siblings through `__file__`, never through `${CLAUDE_PLUGIN_ROOT}`. Edit only the canonical file, then run `python3 scripts/sync_vendor.py`.
- **R3. Agents carry no files of their own.** A script an agent runs belongs to a skill. The agent says which, on a line right under its H1 title, and finds the skill with this snippet before first use:

  ```
  Requires skill: <skill-name>[, <skill-name>]
  ```

  ```bash
  SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/<skill-name>"; [ -d "$SKILL_DIR" ] || SKILL_DIR="$(ls -d .claude/skills/<skill-name> "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/<skill-name>" 2>/dev/null | head -1)"
  ```

  then runs `"$SKILL_DIR/scripts/x.py"`. In the plugin the first path is real; copied on its own, the variable is empty and the fallback finds the copied skill. An agent that runs no scripts needs neither line. An agent that needs a plugin-only capability says `Install: plugin only. <reason>.` under its title instead.
- **R4. Hooks are plugin only.** They keep `${CLAUDE_PLUGIN_ROOT}` in `hooks/hooks.json`.

Two scripts enforce this, and CI runs both on every push and pull request:

```bash
python3 scripts/check_items.py          # R1-R3; prints path:line: rule: message, exits 1 on any violation (--json too)
```

```bash
python3 scripts/sync_vendor.py --check  # every vendor.json copy matches its canonical file; drop --check to fix
```

The site reads the same two marker lines to decide what the "Just this skill/agent" tab shows: a full-folder download for a standalone skill, the agent plus its skills for an agent that needs one, and the plugin install with the reason for a plugin-only item.

### plugin.json

```json
{
  "name": "foundry-example",
  "version": "0.1.0",
  "description": "One or two sentences on what it does and for whom.",
  "author": { "name": "AI Foundry (BYU Marriott)" },
  "license": "MIT",
  "repository": "https://github.com/ai-foundry-byu/foundry-marketplace",
  "keywords": ["qa", "playwright"]
}
```

- `name` is kebab-case and must not start with `claude-` or `anthropic-` (those are reserved and the validator rejects them).
- Bump `version` on every change users should pick up.

### Skills and agents

- `SKILL.md` frontmatter: `name` and a `description` that says what it does **and** the phrases that should trigger it ("Use when someone says ...").
- Agent frontmatter: `name`, `description`, `tools`. Leave out `model` so the agent inherits the user's choice.
- Write for a student who has never seen your harness: concrete commands, file formats, an example, and an acceptance check ("you are done when ...").

### Hooks

- Use `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<name>.py"` in `hooks/hooks.json`.
- Fail open on your own bugs (a crashing hook must not brick a session), and fail closed only on the thing the hook exists to stop.
- Document every environment switch in the README, including how to turn the hook off.

### Scripts and tests

- Python 3 standard library only, unless the tool inherently needs something (Playwright, adb, Maestro). Then document the install in the README.
- Make scripts executable (`chmod +x`).
- Any script with logic gets tests runnable with `python3 -m unittest`, in `tests/`, `scripts/tests/` or a skill's `scripts/tests/`. CI finds and runs every one (`python3 scripts/run_plugin_tests.py`). Run them before you open the PR and paste the result in the PR description.

### README for each plugin

Cover: what it does, how to install (each `/plugin` command in its own code block), how to use each item, requirements, and a maturity label for every item. Add a short "Install one item on its own" note: which items are standalone, which agents need which skill, and which items are plugin only.

### Register it

Add an entry to `.claude-plugin/marketplace.json`:

```json
{
  "name": "foundry-example",
  "source": "./plugins/foundry-example",
  "description": "Same idea as plugin.json, one line.",
  "category": "qa",
  "tags": ["qa"]
}
```

Categories in use: `sdlc`, `guardrails`, `qa`, `design`, `devices`, `evals`, `build`, `career`. Then add every item to the catalog table in the root `README.md`, and to `SDLC.md` if it runs a stage.

An external plugin (one that lives in its own repo) uses a `github` source, or `git-subdir` if the plugin is in a subdirectory. Its entry `name` must equal the `name` in that repo's `plugin.json`. Only list repos that are real Claude Code plugins; link the rest in the README's related-repos section.

## Maturity labels

Every item gets one, in its plugin README and in the root catalog.

- **proven**: generalized from a tool that runs in production in a real harness today. You can say what it ran on and for how long.
- **new**: written from docs or best practice for this marketplace. It may have good tests. It is still new until it has run on real projects.
- A mix is fine when it is honest, for example "method proven, tooling new" or "proven (pattern)" for a pattern that is proven while this exact code is a fresh rewrite.

Never label new work proven. Students choose what to trust from these labels. A wrong "proven" costs them more than a missing feature.

## Scrub checklist (this repo is public)

Before every PR:

1. No personal data: no real home paths, emails, phone numbers, names of private people, private hostnames, private repo names, or internal service names. Use placeholders such as `<your-app>`, `$HOME`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PROJECT_DIR}`.
2. No secrets, not even expired ones. Run a scanner:

   ```bash
   python3 plugins/foundry-builder-kit/skills/secrets-hygiene/scripts/scan_secrets.py --all
   ```

3. Grep for anything from your own machine. Replace the pattern with your username, email, hostname and private project names:

   ```bash
   grep -rniE '/Users/[a-z]|/home/[a-z]|<your-email>|<your-username>|<your-hostname>' plugins/<your-plugin>
   ```

4. No em dashes, and no emoji in docs:

   ```bash
   grep -rnP '\x{2014}' plugins/<your-plugin>
   ```

5. No copied code from a repo without a license that allows it. Describe and link instead. Credit the source when you generalize an idea.
6. Remove build and run output: `__pycache__/`, `.qa/`, `.evals/`, `.DS_Store`.

## Validate

Run the item rules and the vendored-copy check (see "Item rules" above), then rebuild the site catalog:

```bash
python3 scripts/check_items.py && python3 scripts/sync_vendor.py --check && python3 scripts/build_catalog.py
```

Validate your plugin and the marketplace root. Both must pass (warnings such as a missing icon are fine):

```bash
claude plugin validate plugins/<your-plugin>
```

```bash
claude plugin validate .
```

Then try it for real from a clone:

```
/plugin marketplace add ./
```

```
/plugin install <your-plugin>@ai-foundry
```

## Open a PR

1. Branch from `main`: `git checkout -b add-<your-plugin>`.
2. Commit the plugin, the marketplace.json entry and the README catalog rows together.
3. In the PR description, list each item with its type, SDLC stage and maturity, paste the `claude plugin validate` output and the test output, and list known limitations.
4. A maintainer reviews it at a depth that matches its blast radius: a hook that blocks commands or touches secrets gets a careful review, a docs fix gets a quick one.
