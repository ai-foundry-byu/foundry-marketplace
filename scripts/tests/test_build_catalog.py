"""Tests for scripts/build_catalog.py against a tiny fixture repo.

Run: python3 -m unittest discover -s scripts/tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import io
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_catalog as bc  # noqa: E402


def write(root, path, text):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text).lstrip("\n"))


MARKETPLACE = {
    "name": "ai-foundry",
    "description": "Fixture marketplace.",
    "owner": {"name": "Fixture"},
    "metadata": {"version": "0.0.1"},
    "plugins": [
        {"name": "demo", "source": "./plugins/demo", "description": "Demo plugin.",
         "category": "qa", "tags": ["starter"]},
        {"name": "outside", "source": {"source": "github", "repo": "someone/outside"},
         "description": "External plugin.", "category": "career", "tags": ["external"],
         "homepage": "https://github.com/someone/outside"},
        {"name": "sub", "source": {"source": "git-subdir", "url": "https://example.com/r.git", "path": "p"},
         "description": "Subdir plugin."},
    ],
}


def make_fixture(root):
    write(root, ".claude-plugin/marketplace.json", json.dumps(MARKETPLACE))
    write(root, "SDLC.md", """
        # SDLC
        ### 0. Scaffold
        - **Goal:** have files.
        - **Gate:** all files exist.
        ### 5. Code QA
        - **Goal:** tests pass.
        - **Tools:** `check-it` skill, the `tidy-guard` hook.
        ### 6. Visual QA with example users
        - **Tools:** `checker` agent.
        """)
    write(root, "plugins/demo/.claude-plugin/plugin.json",
          json.dumps({"name": "demo", "version": "1.2.3", "keywords": ["x"]}))
    write(root, "plugins/demo/README.md", """
        # demo

        | Item | Type | What it does | SDLC stage | Maturity |
        |---|---|---|---|---|
        | `check-it` | skill | Checks it | verify | proven |
        | `checker` | agent | An agent | verify | new |
        | `other-skill` | skill | Other | ship | proven (pattern) |
        | `templates/thing.md` | template | A thing to copy | requirements | new |
        | `templates/kit/*.yaml` | template | Kit files | build | new |

        | Hook | Event | What it blocks | Disable | Maturity |
        |---|---|---|---|---|
        | `tidy-guard` | PreToolUse (`Bash\\|Read`) | Messy commands | `DEMO_TIDY=0` | proven |

        ## How to use each item

        ### word-hook (hook)

        Turn it off with `export DEMO_WORD=0` for one session.
        """)
    write(root, "plugins/demo/skills/check-it/SKILL.md", """
        ---
        name: check-it
        description: >
          Check the thing
          carefully. Use when "check it".
        ---

        # Check it

        Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/x.py"`.
        """)
    write(root, "plugins/demo/skills/check-it/references/notes.md", "notes\n")
    write(root, "plugins/demo/skills/other-skill/SKILL.md", """
        ---
        name: other-skill
        description: "Quoted: with a colon"
        stage: 7
        ---
        Maturity: **new**. Written for this marketplace.

        Body only.
        """)
    write(root, "plugins/demo/skills/no-label/SKILL.md", """
        ---
        name: no-label
        description: Nothing says how mature I am.
        ---
        Hello.
        """)
    write(root, "plugins/demo/agents/checker.md", """
        ---
        name: checker
        description: Independent checker.
        tools: Read, Grep, Glob
        model: sonnet
        ---
        You check.
        """)
    write(root, "plugins/demo/skills/runner-dir/SKILL.md", """
        ---
        name: runner
        description: Runs its own script.
        ---
        # Runner

        Run `python3 "${CLAUDE_SKILL_DIR}/scripts/run.py"`.
        """)
    write(root, "plugins/demo/skills/runner-dir/scripts/run.py", "print(1)\n")
    write(root, "plugins/demo/skills/runner-dir/scripts/lib/util.py", "X = 1\n")
    write(root, "plugins/demo/skills/served/SKILL.md", """
        ---
        name: served
        description: Talks to the MCP server.
        ---
        # Served

        Install: plugin only. It needs the plugin's MCP server.

        Call `${CLAUDE_PLUGIN_ROOT}/bin/helper`.
        """)
    write(root, "plugins/demo/agents/runner-agent.md", """
        ---
        name: runner-agent
        description: Uses the runner skill.
        ---
        # Runner agent

        Requires skill: runner-dir

        ```bash
        SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/runner-dir"; [ -d "$SKILL_DIR" ] || SKILL_DIR="$(ls -d .claude/skills/runner-dir "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/runner-dir" 2>/dev/null | head -1)"
        python3 "$SKILL_DIR/scripts/run.py"
        ```
        """)
    write(root, "plugins/demo/agents/mcp-agent.md", """
        ---
        name: mcp-agent
        description: Drives the server.
        ---
        # MCP agent

        Install: plugin only. It drives the plugin's MCP server.
        """)
    write(root, "plugins/demo/hooks/hooks.json", json.dumps({
        "description": "demo hooks",
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash|Read", "hooks": [
                    {"type": "command", "command": "python3",
                     "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/scripts/tidy_guard.py"], "timeout": 5}]},
            ],
            "Stop": [
                {"hooks": [{"type": "command",
                            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/word-hook.sh\""}]},
            ],
        },
    }))
    write(root, "plugins/demo/hooks/scripts/tidy_guard.py", '''
        #!/usr/bin/env python3
        """tidy_guard.py: keep commands tidy.

        Blocks messy commands.
        """
        print("ok")
        ''')
    write(root, "plugins/demo/hooks/scripts/word-hook.sh", """
        #!/bin/sh
        # word-hook: says a word when the agent stops.
        # Maturity is not in a table for this one.
        echo word
        """)
    write(root, "plugins/demo/skills/drafter/SKILL.md", """
        ---
        name: drafter
        description: Writes a draft, then hands it to the checker.
        ---
        # Drafter

        Uses agent: checker, runner-agent

        Write the draft, then launch the `checker` agent.
        """)
    write(root, "evidence/evidence.json", json.dumps({
        "demo/skill/check-it": {"label": "verified", "date": "2026-10-28", "note": "Ran live twice."},
        "demo/skill/other-skill": {"label": "beta", "date": "2026-10-28", "note": "One gap."},
        "demo/agent/checker": {"label": "new", "date": "2026-10-28", "note": "Not run yet."},
        "demo/hook/tidy-guard": {"label": "verified", "date": "2026-10-27", "note": "Denied 3/3."},
        "demo/template/thing.md": {"label": "beta", "date": "2026-10-28", "note": "Copied once."},
        "demo/skill/no-label": {"label": "proven", "date": "2026-10-28", "note": "Not a valid label."},
        "outside/plugin/outside": {"label": "beta", "date": "2026-10-28", "note": "Installed once."},
    }, indent=1))
    write(root, "plugins/demo/templates/thing.md", "# Thing\n\nA template for things.\n")
    write(root, "plugins/demo/templates/kit/a.yaml", "a: 1\n")
    write(root, "plugins/demo/templates/kit/b.yaml", "b: 2\n")


class FrontmatterTests(unittest.TestCase):
    def test_folded_and_quoted_and_list(self):
        fm, body = bc.parse_frontmatter(textwrap.dedent("""\
            ---
            name: x
            description: >
              one
              two
            title: "a: b"
            tools: [Read, "Grep"]
            items:
              - first
              - 'second'
            flag: true
            ---
            # Body
            """))
        self.assertEqual(fm["name"], "x")
        self.assertEqual(fm["description"], "one two")
        self.assertEqual(fm["title"], "a: b")
        self.assertEqual(fm["tools"], ["Read", "Grep"])
        self.assertEqual(fm["items"], ["first", "second"])
        self.assertIs(fm["flag"], True)
        self.assertEqual(body, "# Body\n")

    def test_literal_block_and_plain_continuation(self):
        fm, _ = bc.parse_frontmatter("---\nnote: |\n  line one\n  line two\ndesc: starts here\n  and continues\n---\n")
        self.assertEqual(fm["note"], "line one\nline two")
        self.assertEqual(fm["desc"], "starts here and continues")

    def test_no_frontmatter(self):
        fm, body = bc.parse_frontmatter("# Just markdown\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# Just markdown\n")

    def test_unclosed_frontmatter_is_body(self):
        fm, body = bc.parse_frontmatter("---\nname: x\n")
        self.assertEqual(fm, {})


class HelperTests(unittest.TestCase):
    def test_classify_maturity(self):
        self.assertEqual(bc.classify_maturity("proven (pattern)"), "proven")
        self.assertEqual(bc.classify_maturity("new (generalized from a proven gate)"), "new")
        self.assertEqual(bc.classify_maturity("method proven; tooling new"), "proven")
        self.assertEqual(bc.classify_maturity("**new**. Written here"), "new")
        self.assertEqual(bc.classify_maturity("verified"), "verified")
        self.assertEqual(bc.classify_maturity("**beta** (CI-tested)"), "beta")
        self.assertEqual(bc.classify_maturity("beta; the shell-edit path is verified"), "beta")
        self.assertIsNone(bc.classify_maturity("n/a"))
        self.assertIsNone(bc.classify_maturity(""))

    def test_norm_key(self):
        self.assertEqual(bc.norm_key("`scripts/Foo_bar.py`"), "foo-bar")
        self.assertEqual(bc.norm_key("commit secret guard"), "commit-secret-guard")

    def test_split_row_keeps_escaped_pipe_and_code(self):
        self.assertEqual(bc.split_row("| a | `B\\|C` | d |"), ["a", "`B|C`", "d"])

    def test_stages_from_text(self):
        self.assertEqual(bc.stages_from_text("QA / verify"), [6])
        self.assertEqual(bc.stages_from_text("build / test"), [4, 5])
        self.assertEqual(bc.stages_from_text("build (pre-build) and visual QA"), [2, 4, 6])
        self.assertEqual(bc.stages_from_text("support"), [])

    def test_docstring_python_and_shell(self):
        d = tempfile.mkdtemp()
        try:
            py = os.path.join(d, "a.py")
            sh = os.path.join(d, "b.sh")
            with open(py, "w") as fh:
                fh.write('#!/usr/bin/env python3\n"""Head line.\n\nMore."""\nx=1\n')
            with open(sh, "w") as fh:
                fh.write("#!/bin/sh\n# one\n# two\necho\n")
            self.assertEqual(bc.docstring(py), "Head line.\n\nMore.")
            self.assertEqual(bc.docstring(sh), "one\ntwo")
        finally:
            shutil.rmtree(d)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        make_fixture(cls.root)
        cls.data = bc.build(cls.root)
        cls.items = {i["id"]: i for i in cls.data["items"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_plugins_and_marketplace(self):
        names = [p["name"] for p in self.data["plugins"]]
        self.assertEqual(names, ["demo", "outside", "sub"])
        demo = self.data["plugins"][0]
        self.assertEqual(demo["version"], "1.2.3")
        self.assertTrue(demo["starter"])
        self.assertEqual(demo["install"][1], "/plugin install demo@ai-foundry")
        self.assertEqual(self.data["marketplace"]["name"], "ai-foundry")
        self.assertEqual(len(self.data["stages"]), 9)
        self.assertEqual(self.data["stages"][0]["gate"], "all files exist.")

    def test_skill_fields(self):
        s = self.items["demo/check-it"]
        self.assertEqual(s["type"], "skill")
        self.assertEqual(s["description"], 'Check the thing carefully. Use when "check it".')
        self.assertEqual(s["maturity"], "verified")  # from evidence/evidence.json
        self.assertEqual(s["readme_maturity"], "proven")
        self.assertEqual(s["evidence"], {"label": "verified", "note": "Ran live twice.", "date": "2026-10-28"})
        self.assertEqual(s["stages"], [5])  # SDLC.md wins over the README "verify" cell
        self.assertTrue(s["body"].startswith("# Check it"))
        self.assertTrue(s["needs_plugin"])
        self.assertEqual([f["path"] for f in s["files"]], ["SKILL.md", "references/notes.md"])
        self.assertEqual(s["raw_url"], bc.RAW_BASE + "plugins/demo/skills/check-it/SKILL.md")
        self.assertEqual(s["files"][1]["raw_url"],
                         bc.RAW_BASE + "plugins/demo/skills/check-it/references/notes.md")

    def test_maturity_line_beats_table_and_frontmatter_stage(self):
        s = self.items["demo/other-skill"]
        self.assertEqual(s["readme_maturity"], "new")
        self.assertEqual(s["maturity"], "beta")
        self.assertEqual(s["stages"], [7])
        self.assertEqual(s["description"], "Quoted: with a colon")
        self.assertFalse(s["needs_plugin"])

    def test_unlabeled(self):
        nl = self.items["demo/no-label"]
        self.assertEqual(nl["readme_maturity"], "unlabeled")
        # an invalid evidence label counts as no evidence: the item is "new"
        self.assertEqual(nl["maturity"], "new")
        self.assertIsNone(nl["evidence"])
        # no SDLC.md mention, no README row: category default (qa -> 6)
        self.assertEqual(self.items["demo/no-label"]["stages"], [6])

    def test_agent(self):
        a = self.items["demo/checker"]
        self.assertEqual(a["tools"], ["Read", "Grep", "Glob"])
        self.assertEqual(a["model"], "sonnet")
        self.assertEqual(a["maturity"], "new")
        self.assertEqual(a["readme_maturity"], "new")
        self.assertEqual(a["stages"], [6])
        self.assertEqual(a["body"].strip(), "You check.")

    def test_hook_from_args_and_table(self):
        h = self.items["demo/tidy-guard"]
        self.assertEqual(h["type"], "hook")
        self.assertEqual(h["maturity"], "verified")
        self.assertEqual(h["evidence"]["date"], "2026-10-27")
        self.assertEqual(h["disable"], "DEMO_TIDY=0")
        self.assertEqual(h["triggers"][0]["event"], "PreToolUse")
        self.assertEqual(h["triggers"][0]["matcher"], "Bash|Read")
        self.assertIn("tidy_guard.py", h["triggers"][0]["command"])
        self.assertEqual(h["description"], "Blocks messy commands")
        self.assertIn("keep commands tidy", h["script_doc"])
        self.assertTrue(h["needs_plugin"])
        self.assertEqual(h["stages"], [5])

    def test_install_modes(self):
        s = self.items["demo/runner"]
        self.assertEqual(s["install_mode"], "standalone")
        self.assertEqual(s["dir"], "runner-dir")
        self.assertFalse(s["needs_plugin"])
        self.assertEqual([f["path"] for f in s["files"]],
                         ["SKILL.md", "scripts/lib/util.py", "scripts/run.py"])
        served = self.items["demo/served"]
        self.assertEqual(served["install_mode"], "plugin-only")
        self.assertEqual(served["plugin_only_reason"], "It needs the plugin's MCP server.")
        self.assertTrue(served["needs_plugin"])
        # unmarked ${CLAUDE_PLUGIN_ROOT}: still plugin only, with a generic reason
        chk = self.items["demo/check-it"]
        self.assertEqual(chk["install_mode"], "plugin-only")
        self.assertIn("CLAUDE_PLUGIN_ROOT", chk["plugin_only_reason"])
        ra = self.items["demo/runner-agent"]
        self.assertEqual(ra["install_mode"], "needs-skill")
        self.assertEqual(ra["requires_skills"], ["runner-dir"])
        self.assertEqual(ra["requires_skill_ids"], ["demo/runner"])
        self.assertFalse(ra["needs_plugin"])
        self.assertEqual(self.items["demo/mcp-agent"]["install_mode"], "plugin-only")
        self.assertEqual(self.items["demo/checker"]["install_mode"], "standalone")
        self.assertEqual(self.items["demo/tidy-guard"]["install_mode"], "plugin-only")
        self.assertTrue(self.items["demo/tidy-guard"]["plugin_only_reason"])
        self.assertEqual(self.items["demo/thing.md"]["install_mode"], "standalone")
        self.assertEqual(self.items["outside/outside"]["install_mode"], "plugin-only")
        for it in self.data["items"]:
            self.assertIn(it["install_mode"], ("standalone", "needs-skill", "plugin-only"), it["id"])
            self.assertIn("requires_skills", it)
            self.assertIn("plugin_only_reason", it)
            self.assertIn("uses_agent_ids", it)
            self.assertIn(it["maturity"], ("verified", "beta", "new"), it["id"])

    def test_uses_agents(self):
        d = self.items["demo/drafter"]
        self.assertEqual(d["uses_agents"], ["checker", "runner-agent"])
        self.assertEqual(d["uses_agent_ids"], ["demo/checker", "demo/runner-agent"])
        self.assertEqual(d["install_mode"], "standalone")
        self.assertEqual(self.items["demo/runner"]["uses_agent_ids"], [])
        # agents never carry a uses list of their own
        self.assertEqual(self.items["demo/checker"]["uses_agents"], [])

    def test_plugin_maturity_from_evidence(self):
        demo = self.data["plugins"][0]
        self.assertEqual(demo["maturity"], "mixed")
        self.assertEqual(self.data["plugins"][1]["maturity"], "external")
        self.assertEqual(set(self.data["labels"]), {"verified", "beta", "new"})

    def test_hook_from_command_string_and_section_switch(self):
        h = self.items["demo/word-hook"]
        self.assertEqual(h["triggers"][0]["event"], "Stop")
        self.assertEqual(h["disable"], "DEMO_WORD=0")
        self.assertEqual(h["readme_maturity"], "unlabeled")
        self.assertEqual(h["maturity"], "new")  # no evidence entry
        self.assertIn("says a word", h["description"])

    def test_templates(self):
        t = self.items["demo/thing.md"]
        self.assertEqual(t["readme_maturity"], "new")
        self.assertEqual(t["maturity"], "beta")
        self.assertEqual(t["stages"], [1])
        self.assertEqual(t["description"], "A thing to copy")
        kit = self.items["demo/kit"]
        self.assertEqual([f["path"] for f in kit["files"]], ["kit/a.yaml", "kit/b.yaml"])
        self.assertEqual(kit["readme_maturity"], "new")
        self.assertEqual(kit["maturity"], "new")
        self.assertEqual(kit["description"], "Kit files.")
        self.assertEqual(kit["raw_url"], "")

    def test_external_plugins(self):
        o = self.items["outside/outside"]
        self.assertEqual(o["type"], "plugin")
        self.assertTrue(o["external"])
        self.assertEqual(o["source_url"], "https://github.com/someone/outside")
        self.assertEqual(o["maturity"], "beta")  # external items take an evidence label too
        self.assertEqual(self.items["sub/sub"]["maturity"], "new")
        sub = self.items["sub/sub"]
        self.assertIn("example.com/r.git", sub["external_repo"])

    def test_ids_unique(self):
        ids = [i["id"] for i in self.data["items"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_main_writes_and_check(self):
        out = os.path.join(self.root, "site", "catalog.json")
        index = os.path.join(self.root, "site", "catalog-index.json")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(bc.main(["--root", self.root, "--out", out]), 0)
            with open(out) as fh:
                self.assertEqual(json.load(fh)["schema"], 1)
            with open(index) as fh:
                self.assertEqual(json.load(fh)["schema"], 1)
            self.assertEqual(bc.main(["--root", self.root, "--out", out, "--check"]), 0)
            with open(index, "a") as fh:
                fh.write(" ")
            self.assertEqual(bc.main(["--root", self.root, "--out", out, "--check"]), 1)  # stale index alone fails
            self.assertEqual(bc.main(["--root", self.root, "--out", out]), 0)
            with open(out, "a") as fh:
                fh.write(" ")
            self.assertEqual(bc.main(["--root", self.root, "--out", out, "--check"]), 1)

    def test_index_is_slim_and_complete(self):
        idx = bc.build_index(self.data)
        text = bc.dump_index(idx)
        self.assertEqual(json.loads(text), idx)
        self.assertEqual(len(idx["items"]), len(self.data["items"]))
        for row in idx["items"]:
            for key in ("id", "plugin", "type", "name", "description", "stages", "maturity", "install_mode",
                        "requires_skills", "uses_agents", "page_url", "raw_url", "files"):
                self.assertIn(key, row, row["id"])
            for key in ("body", "readme", "script_doc", "evidence"):
                self.assertNotIn(key, row, row["id"])
            self.assertTrue(row["page_url"].startswith(bc.SITE_URL + "#/item/"), row["page_url"])
        rows = {r["id"]: r for r in idx["items"]}
        self.assertEqual(rows["demo/runner"]["dir"], "runner-dir")
        self.assertEqual([f["path"] for f in rows["demo/runner"]["files"]],
                         ["SKILL.md", "scripts/lib/util.py", "scripts/run.py"])
        self.assertEqual(rows["demo/runner"]["files"][2]["raw_url"],
                         bc.RAW_BASE + "plugins/demo/skills/runner-dir/scripts/run.py")
        self.assertEqual(rows["demo/runner-agent"]["requires_skills"], ["demo/runner"])
        self.assertEqual(rows["demo/drafter"]["uses_agents"], ["demo/checker", "demo/runner-agent"])
        self.assertEqual(rows["demo/check-it"]["maturity"], "verified")
        self.assertIn("demo", [p["name"] for p in idx["plugins"]])
        self.assertNotIn("readme", idx["plugins"][0])
        self.assertIn("--scope project", idx["install"]["plugin"][0])
        # one plugin or item per line, so an agent can grep it
        item_lines = [ln for ln in text.split("\n") if ln.startswith(' {"id": ')]
        self.assertEqual(len(item_lines), len(idx["items"]))

    def test_real_repo_index_is_small(self):
        """The repo's own index stays readable in one tool call (R7-D1: catalog.json overflowed at 612 KB)."""
        repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        data = bc.build(repo)
        text = bc.dump_index(bc.build_index(data))
        self.assertLess(len(text.encode("utf-8")), 120 * 1024)
        self.assertLess(len(text), len(json.dumps(data)) / 4)

    def test_no_local_paths_leak(self):
        blob = json.dumps(self.data)
        self.assertNotIn(self.root, blob)


if __name__ == "__main__":
    unittest.main()
