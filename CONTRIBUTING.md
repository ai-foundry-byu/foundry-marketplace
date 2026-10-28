# Contributing

Anything that helped you build with agents and would help the next cohort is welcome: a skill, an agent, a hook, a script, a template, or a fix to one of ours. Open an issue first if you are not sure where it belongs.

## Add a plugin

### Layout

```
plugins/<your-plugin>/
  .claude-plugin/plugin.json     # manifest (the only file inside .claude-plugin/)
  README.md                      # required, see below
  skills/<skill-name>/SKILL.md   # procedures the agent loads on demand
  agents/<agent-name>.md         # subagents with a fresh context
  hooks/hooks.json               # event hooks; scripts under hooks/scripts/
  scripts/                       # helper scripts, plus scripts/tests/
  templates/                     # files users copy into their project
```

Components go at the plugin root, never inside `.claude-plugin/`. Reference your own files from hooks and docs as `${CLAUDE_PLUGIN_ROOT}/...` and the user's project as `${CLAUDE_PROJECT_DIR}`. Never use an absolute path from your machine.

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
- Any script with logic gets tests runnable with `python3 -m unittest`. Run them before you open the PR and paste the result in the PR description.

### README for each plugin

Cover: what it does, how to install (each `/plugin` command in its own code block), how to use each item, requirements, and a maturity label for every item.

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
   python3 plugins/foundry-builder-kit/scripts/scan_secrets.py --all
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
