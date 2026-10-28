# AI Foundry Marketplace

A shared toolbox for building your own Claude Code harness. It holds a framework (the [Foundry SDLC](SDLC.md)) and the skills, agents and hooks that run it. Each item has an honest maturity label:

- **proven**: generalized from a tool that runs in production in our harness today.
- **new**: written for this marketplace from docs and best practice. It has tests, but it has not been battle-tested on real projects yet.

Install the plugins you need into your own Claude Code, or point your agent at this repo and let it read the skills and decide. Everything here is MIT licensed, so copy and adapt freely.

Built by AI Foundry at BYU Marriott for its MBA builders. Questions and fixes are welcome as issues and PRs.

## Quick start

Add the marketplace (once per machine):

```
/plugin marketplace add ai-foundry-byu/foundry-marketplace
```

Install the starter set. The SDLC framework:

```
/plugin install foundry-sdlc@ai-foundry
```

The guardrail hooks:

```
/plugin install foundry-guardrails@ai-foundry
```

The QA gates and test agents:

```
/plugin install foundry-qa@ai-foundry
```

Then start a new session in your project and say "where are we on this project?" or "start a new project". The `sdlc` skill finds your current stage and tells you what to do next.

Browse everything else:

```
/plugin
```

From a terminal instead of a session, the same commands are `claude plugin marketplace add ai-foundry-byu/foundry-marketplace` and `claude plugin install foundry-sdlc@ai-foundry`. `marketplace add` also accepts the path to a local clone of this repo, for example `claude plugin marketplace add ./foundry-marketplace`.

### Requirements

- Claude Code with plugin support.
- Python 3.9 or newer on `PATH` as `python3` (hooks and scripts are stdlib only).
- For browser QA: `pip install playwright` then `python3 -m playwright install chromium`.
- Native device QA, iPhone mirroring and some builder skills have their own requirements, listed in each plugin's README.

## Team setup

Commit this to your project's `.claude/settings.json` so every teammate gets the marketplace and the same plugins:

```json
{
  "extraKnownMarketplaces": {
    "ai-foundry": {
      "source": {
        "source": "github",
        "repo": "ai-foundry-byu/foundry-marketplace"
      }
    }
  },
  "enabledPlugins": {
    "foundry-sdlc@ai-foundry": true,
    "foundry-guardrails@ai-foundry": true,
    "foundry-qa@ai-foundry": true
  }
}
```

Committing `enabledPlugins` does not download anything. Claude Code prompts each teammate to trust the marketplace when they open the project, or they can install directly:

```
claude plugin install foundry-sdlc@ai-foundry --scope project
```

Also paste [the CLAUDE.md snippet](plugins/foundry-sdlc/skills/new-project/references/CLAUDE-md-snippet.md) into your project's `CLAUDE.md`. Plugins load skills on demand; the always-on norms (root cause first, never say done without a passing gate, review by blast radius) have to live in CLAUDE.md.

## Plugin or single item?

Every skill and most agents work two ways. Pick per item.

| | Plugin | Single skill | Single agent | Hook |
|---|---|---|---|---|
| What you install | The whole plugin, with `/plugin install` | One folder, copied to `~/.claude/skills/<name>/` or `.claude/skills/<name>/` | One `.md` file, copied to `~/.claude/agents/` or `.claude/agents/` | Plugin only |
| Updates | From the marketplace, all items together | None. Copy it again to update | None | With the plugin |
| Names | Namespaced, for example `foundry-qa:done-gate` | Plain, for example `done-gate` | Plain | n/a |
| Good for | Getting everything, staying current, hooks and MCP servers | Trying one thing, or forking it to make it yours | One reviewer or tester | Rules that must hold every time |

- A **skill** is self-contained: its scripts, templates and references live in its own folder, so the copy runs exactly like the plugin version.
- An **agent** that runs scripts says `Requires skill: <name>` under its title. Install that skill too; the agent finds it in either skills folder. The site's "Just this agent" tab gives one script that installs both.
- A few items say `Install: plugin only.` with the reason (they need the plugin's hooks, MCP server or a compiled helper). **Hooks** always need the plugin, because `hooks.json` and the scripts it runs install together.

Each plugin README lists which of its items are standalone, which need a skill, and which are plugin only. The [site](https://ai-foundry-byu.github.io/foundry-marketplace/) shows the install for each item.

## Let your agent do it

Paste this into Claude Code from your project root:

> Read the catalog at https://github.com/ai-foundry-byu/foundry-marketplace (README.md, SDLC.md and .claude-plugin/marketplace.json). Look at this project: its stack, whether it is web or native, whether it has a PRD, tests, CI or a deploy, and whether it has an LLM feature. Recommend the smallest set of plugins from that marketplace that fits, with one line each on why and its maturity label. Do not recommend a "new" item as if it were proven. Then give me the exact /plugin commands to add the marketplace and install them, and the lines to add to .claude/settings.json for my team. Do not install anything or edit any file until I say yes.

## Catalog

Every item in every plugin. Stage numbers follow [SDLC.md](SDLC.md): 0 scaffold, 1 requirements, 2 PRD and stories, 3 workplan, 4 execute, 5 code QA, 6 visual QA, 7 ship, 8 feedback.

### foundry-sdlc (the framework)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| sdlc | skill | Router: the 8-stage map, the exit gate per stage, and current-stage detection | all | proven |
| new-project | skill | Scaffolds the artifact set from templates into your project | 0 | proven |
| gather-requirements | skill | Verbatim asks with R-ids and sources, a decisions log, and an "Already exists" audit | 1 | proven |
| write-prd | skill | PRD with inline user stories and observable criteria, compiled to stories.json, critiqued | 2 | proven |
| write-workplan | skill | Task table with owner, model, effort and review tier by blast radius, plus milestones | 3 | proven |
| parallel-lanes | skill | One git worktree and one agent per task, lane brief, merge-back | 4 | proven |
| ship | skill | The ship ritual: done gate, persona testers, independent verifier, then LIVE and changelog | 6, 7 | proven |
| bug-to-story | skill | Every bug becomes a story plus a regression test that fails before the fix | 8 | proven |
| prd-critic | agent | Adversarial read-only PRD reviewer in a fresh context | 2 | proven (pattern) |
| story-verifier | agent | Verifies one story on the deployed build from criteria and evidence only | 6 | proven (pattern) |
| SessionStart stage hint | hook | Prints the current stage and failing check when the project has a PRD.md or REQUIREMENTS.md | all | new |
| gen_stories.py | script | Compiles PRD stories into stories.json; `--check` fails if stale or malformed | 2 | proven (generalized port) |
| new_project.py | script | Scaffolds the artifact set, never overwrites without `--force` | 0 | new |
| sdlc_stage.py | script | Deterministic stage detector from files on disk | all | new |
| REQUIREMENTS.md | template | Verbatim asks table, Already exists audit, open questions | 1 | proven |
| DECISIONS.md | template | Verbatim human decisions and what each authorizes | 1-3 | proven |
| PRD.md | template | PRD with stories, rollout gates, Addressed critiques appendix | 2 | proven |
| WORKPLAN.md | template | Status, review tiers, milestones, task table, Blocked on human | 3 | proven |
| stories.schema.json | template | JSON Schema for stories.json | 2 | proven |
| done-journey.yaml | template | The journey the done gate runs | 6 | proven (format) |
| CHANGELOG.md | template | Dated entries with story ids and evidence | 7 | proven |
| README.md | template | Project README that indexes the artifact set | 0 | new |
| CLAUDE-md-snippet.md | template | Always-on norms to paste into your CLAUDE.md | all | proven |

### foundry-guardrails (hooks)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| destructive-guard | hook | Blocks rm -rf of root or home, force-push to main, reset --hard on a dirty tree, DROP/TRUNCATE, curl pipe sh, and similar | 4, 7 | new |
| secret-guard | hook | Keeps secrets out of the transcript: denies reading .env, keys, token printers and env dumps | 4 | proven |
| verify-before-done | hook | Blocks stopping after code edits with no test run, and blocks push or deploy without verification | 5, 7 | proven |
| worktree-guard | hook | Inside a linked worktree, denies edits that land in the main checkout | 4 | proven |
| stale-write-guard | hook | Warns (or denies) a whole-file Write over uncommitted changes | 4 | new |
| ship-stop | hook | Keeps the agent working until the named WORKPLAN milestone is checked | 3, 4 | proven |
| _common.py | script | Shared hook library: command normalizer, fail-open runner, deny log | all | new |
| guardrails-help | skill | How to respond when a hook blocks you, and every config switch | all | new |
| WORKPLAN milestone format | template | The `- [ ] M3.2 title` checkbox format ship-stop enforces | 3 | new |

### foundry-qa (web QA)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| done-gate | skill | Deployed-SHA check plus a Playwright journey on 3 devices; only exit 0 is done | 6, 7 | proven |
| regression-check | skill | Stack-neutral blast-radius method: list changes, grep consumers, test the at-risk ones | 5 | proven |
| a11y-check | skill | axe-core on device profiles plus a manual WCAG 2.2 AA floor checklist | 6 | proven |
| visual-baseline | skill | Screenshot baselines with pixel diff and a deliberate approve step | 6 | proven |
| web-qa | agent | Drives the app: journeys, axe, baselines, console and network errors; files findings | 6 | proven |
| persona-tester | agent | Tests every story as a persona across devices, read-only by default | 6 | proven |
| explorer | agent | Curious-human tester: read-only crawl plus a manual probe list | 6 | proven (pattern) |
| done_gate.py | script | The done gate runner with an exit-code contract and evidence in .qa/ | 6, 7 | proven |
| persona_run.py | script | Persona story runner with patience, overflow and tap-target checks | 6 | proven |
| a11y_check.py | script | axe-core runner with an impact floor | 6 | proven |
| visual_baseline.py | script | capture, compare, check, approve with a stdlib PNG diff | 6 | proven |
| explore.py | script | Read-only same-origin crawler | 6 | proven (pattern) |
| qa_yaml.py | script | Dependency-free YAML subset parser | support | new |
| done-journey.yaml | template | Annotated journey covering every step and assertion kind | 6 | new |
| stories.example.json | template | Example stories mixing mechanical and human criteria | 2, 6 | new |
| personas/ | template | Persona template plus two example personas | 6 | new |

The foundry-qa scripts are clean-room rewrites of production tools: the method and contracts are proven, the code is tested against a fixture site.

### foundry-design (design gates)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| design-critique | skill | Subtract-only design critic: 8-question constitution, findings schema with no "add" verb, a four-tier resolver | 4, 6 | proven |
| ui-ux-spec | skill | Turns a story into a buildable UI spec: breakpoints, state matrix, keyboard and touch, copy, checkable acceptance | 2-4 | proven |
| design-system | skill | Inventories raw values, collapses them to tokens, measures contrast, fills a template | 2 | new |
| ui-reviewer | agent | Read-only review from screenshots and code with a 10-dimension rubric and token-level must-fixes | 6, 7 | proven |
| design_gate.py | script | Deterministic gate: clicks to goal, dead controls, tap targets, contrast, labels, regressions vs a baseline | 6 | new |
| validate_findings.py | script | Validates critique findings files against the schema and rules | 6 | new |
| design-gate.config.json | template | Example gate config | setup | new |
| findings.example.json | template | Example critique run | 6 | new |
| decision.yaml | template | Design decision log entry | 6, 8 | new |

### foundry-devices (native and desktop QA)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| ios-qa | agent | iOS Simulator QA with simctl and Maestro, crash and log capture | 6 | new |
| android-qa | agent | Android QA with emulator, adb, uiautomator and Maestro | 6 | new |
| windows-qa | agent | Windows desktop QA with pywinauto (UIA) and PowerShell | 6 | new |
| macos-qa | agent | macOS desktop QA via the accessibility tree, plus Playwright for Electron | 6 | new |
| device-matrix | skill | Maps stories' devices to lanes, runs them in parallel, merges one verdict | 6 | new |
| doctor.py | script | Per-platform preflight: are the tools present and answering | setup | new |
| uitree.py | script | Reads an Android uiautomator dump; prints a tap only for a unique match | 6 | new |
| ax_tree.py | script | macOS accessibility helper: dump, find, press, window bounds | 6 | new |
| device_matrix.py | script | plan, init and report for the device matrix | 6 | new |
| maestro flows | template | Android and iOS sign-in flows | 6 | new |
| stories / results / matrix examples | template | stories.example.json, results.example.json, matrix.template.md | 6 | new |

### foundry-iphone-mirror (real iPhone)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| iphone-mirror | skill | The screenshot, read, act, verify loop through macOS iPhone Mirroring | 6 | proven |
| iphone-driver | agent | Takes a whole on-phone task, one verified action at a time | 6 | proven |
| bin/iphone-mirror | script | CLI: doctor, build, shot, tap, swipe, type, key, home | 6 | proven |
| engine/ | script | The signed helper app's worker and launcher | 6 | proven |
| build-helper-app.sh | script | Builds, signs and registers the helper app | setup | proven |
| mcp/server.py | script | Stdlib MCP server with typed iphone_* tools | 6 | new |
| tests/ | template | 38 tests that need no phone | 6 | new |

The engine changes from the proven original are unit-tested but have not driven a real phone yet; see that plugin's README.

### foundry-evals (agent and LLM features)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| new-eval | skill | Scaffold a suite: cases with oracles, code graders first, a binary judge, negative controls, a threshold | 5, 8 | method proven, tooling new |
| run-eval | skill | Pilot, full run, read the report and the comparison, report only measured numbers | 5, 8 | method proven, tooling new |
| hillclimb | skill | One change per round, keep or revert on val by the noise band, confirm on test | 8 | method proven, manual loop |
| eval-auditor | agent | Read-only audit of a suite and its last run: cheatable graders, missing controls, noisy runs | 5 | new |
| evalkit.py | script | Stdlib runner: init, run, check, compare, history, with CI gating | 5, 8 | new |
| judge_claude.py | script | Binary LLM judge via `claude -p` | 5 | new |
| test_evalkit.py | script | 24 offline tests | 5 | new |
| example-suite | template | 9-case refund-triage suite with a deliberate bug to find | learning | new |

### foundry-builder-kit (day-one build skills)

| Item | Type | What it does | Stage | Maturity |
|---|---|---|---|---|
| add-auth | skill | Pick an auth provider, implement sign-in, verify protected routes | 4 | proven |
| scale-10k | skill | Launch-readiness audit for 10k+ users with a scorecard and ordered fixes | 7 | proven |
| secrets-hygiene | skill | Prevent leaks, and the probe-first rotation flow when one happens | 4, ops | proven (rotation), new (templates) |
| cheap-llm-routing | skill | Route schema-pinned extraction to free or cheap models with a privacy bar and a paid fallback | 4 | proven (pattern) |
| scheduled-agents | skill | Headless `claude -p` jobs on cron, launchd, systemd, Task Scheduler or GitHub Actions, with a deadman | ops | proven (cron, launchd), new (Windows, Actions) |
| tmux-agents | skill | Drive REPLs, dev servers and parallel agents through tmux | 4, 5 | proven (pattern) |
| commit-secret-guard | hook | Blocks an agent-run git commit that contains a secret | 4 | new |
| scan_secrets.py | script | Stdlib secret scanner with redacted output | 4 | new |
| probe_key.py | script | Asks a provider whether a key still authenticates (LIVE/DEAD/ERR) | ops | new |
| structured_router.py | script | Forced-tool-call structured output across a privacy-aware provider chain | 4 | new |
| run_headless.py | script | One `claude -p` job with a lock, timeout, transcript and heartbeat | ops | new |
| deadman.py | script | Heartbeat writer and staleness alert | ops | new |
| tmux_agent.py | script | start, send, read, wait, run on a private tmux socket | 4, 5 | new |
| secrets-hygiene templates | template | gitignore lines, env.example, pre-commit config, CI secret scan | 4 | new |
| scheduled-agents templates | template | crontab, launchd plist, Task Scheduler script, GitHub Actions workflow | ops | new |
| cheap-llm-routing examples | template | Schema, synthetic input, provider policy file | 4 | new |

### External plugins

| Plugin | What it does | Install | Maturity |
|---|---|---|---|
| recruit (from jddavenportOpen/recruit-copilot) | Resume builder and job finder: experience bank, role scoring, tailored ATS-safe resumes. Never applies for you | `/plugin install recruit@ai-foundry` | external, MIT, maintained in its own repo |

## Related Foundry and community repos

These are not installed by this marketplace. Some are complementary, some are alternatives.

- **[ai-foundry-byu/agent-team-kit](https://github.com/ai-foundry-byu/agent-team-kit)** by Scott Murff. A project-install harness kit: spec, build-spec, mockup and ux-critique skills, worktree launchers, git guard hooks and a team memory pack. Install it with its `install.sh` into a project (see its README). It is complementary to this marketplace, and its spec and build-spec skills are an equivalent path through stages 2 to 4. [SDLC.md](SDLC.md) maps its skills onto our stages.
- **[ai-foundry-byu/app-feedback-loop](https://github.com/ai-foundry-byu/app-feedback-loop)** (MIT). An in-app bug report to fix loop: a widget captures the screenshot and context, an admin inbox hands the report to Claude Code, and the fix commit closes it. Pairs with stage 8.
- **[ai-foundry-byu/software-design-canon](https://github.com/ai-foundry-byu/software-design-canon)**. A curated, link-checked index of the free primary sources on software design and architecture (papers, articles, talks), with no pirated books. Good for grounding an agent's design advice in a real source.
- **[jddavenportOpen/claude-bug-squash](https://github.com/jddavenportOpen/claude-bug-squash)** (MIT). Gated autonomous bug fixing with a 3-seat review panel. It is a real Claude Code plugin, but it is not listed in this marketplace yet because its plugin name starts with the reserved prefix `claude-`. Install it from its own marketplace (see its README).
- **[jddavenportOpen/ethos-gate](https://github.com/jddavenportOpen/ethos-gate)** (MIT). A PreToolUse gate that blocks irreversible or outward actions (sends, spends, deploys) unless a human approved that exact content.
- **[jddavenportOpen/claude-deploy-kit](https://github.com/jddavenportOpen/claude-deploy-kit)** (MIT). Enterprise controls for Claude agents: a policy chokepoint, a destructive-command hook, an eval gate, a redacting audit log.
- **[jddavenportOpen/deep-research-agent](https://github.com/jddavenportOpen/deep-research-agent)** (MIT). Multi-source research agent with an adversarial verification pass. Useful in stage 1.
- **[jddavenportOpen/agent-evals-starter](https://github.com/jddavenportOpen/agent-evals-starter)** (MIT). Learn agent evals by running them: a support agent, 24 tasks, graders, a judge and controls. The longer course behind foundry-evals.
- **[jddavenportOpen/mcp-judge](https://github.com/jddavenportOpen/mcp-judge)** (MIT). A calibrated multi-persona LLM judge as an MCP server.
- **[jddavenportOpen/ccstitch](https://github.com/jddavenportOpen/ccstitch)** (MIT). A local trace store and viewer for Claude Code OpenTelemetry spans.
- **[jddavenportOpen/harnessview](https://github.com/jddavenportOpen/harnessview)** (MIT). Inspect and visualize an agent harness and its run history (`npx harnessview`).
- **[jddavenportOpen/warden](https://github.com/jddavenportOpen/warden)** (MIT). A governor for autonomous agents: autonomy admitted by reversibility, rollback and trust demotion.
- **[jddavenportOpen/clawdling](https://github.com/jddavenportOpen/clawdling)** (AGPL-3.0, link only). Your Claude Code as a whole org: an agent per project, an org map, needs-you status. Copyleft, so we link it and do not bundle it.

## Build your own harness

A harness is everything around the model that makes it behave the way your team needs. Claude Code gives you five mechanisms. Pick the weakest one that does the job.

| Mechanism | What it is | Use it when | Example here |
|---|---|---|---|
| **CLAUDE.md** | Text loaded into every session | A norm must apply on every turn | [CLAUDE-md-snippet.md](plugins/foundry-sdlc/skills/new-project/references/CLAUDE-md-snippet.md): root cause first, never say done without a gate |
| **Skills** | Procedures the agent loads on demand, by description | A multi-step method is needed sometimes, not always | `write-prd`, `done-gate`, `regression-check` |
| **Agents** | A subagent with its own fresh context and tool list | You need independent judgment that has not seen the builder's reasoning | `prd-critic`, `story-verifier`, `persona-tester` |
| **Hooks** | Scripts the harness runs on events (before a tool call, at stop) | A rule is non-negotiable. The harness enforces it, not the model's memory | `secret-guard`, `verify-before-done`, `worktree-guard` |
| **Events and schedules** | Cron, launchd, CI or a scheduled cloud agent running `claude -p` | Work recurs or must run while nobody is at the keyboard | `scheduled-agents` skill, `run_headless.py`, `deadman.py` |

Rules of thumb:

- If you keep repeating an instruction in chat, put it in CLAUDE.md.
- If CLAUDE.md is getting long with procedures, move each procedure into a skill.
- If the same agent that did the work is grading the work, move the grading into an agent with a fresh context.
- If the model breaks a rule even though it is written down, make it a hook. A hook is the only one of these the model cannot talk its way past.
- If a job only works when someone remembers to run it, schedule it, and add a deadman so you hear when it stops.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the plugin layout, the maturity rules, the scrub checklist and how to validate before opening a PR.

## License

[MIT](LICENSE). Copyright (c) 2026 AI Foundry, BYU Marriott School of Business. External plugins and linked repos carry their own licenses.
