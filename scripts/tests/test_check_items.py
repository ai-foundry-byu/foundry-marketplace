"""Tests for scripts/check_items.py and scripts/sync_vendor.py on small fixture plugins.

Run: python3 -m unittest discover -s scripts/tests -v
"""
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import check_items as ci  # noqa: E402
import sync_vendor as sv  # noqa: E402

SNIP = ('SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/%s"; [ -d "$SKILL_DIR" ] || '
        'SKILL_DIR="$(ls -d .claude/skills/%s "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/%s" 2>/dev/null | head -1)"')


def write(root, path, text, mode=None):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text).lstrip("\n") if isinstance(text, str) else text)
    if mode:
        os.chmod(full, mode)


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def good_plugin(root, name="good"):
    """A plugin that follows every rule."""
    p = "plugins/%s/" % name
    write(root, p + ".claude-plugin/plugin.json", json.dumps({"name": name, "version": "0.1.0"}))
    write(root, p + "skills/runner/SKILL.md", """
        ---
        name: runner
        description: Runs things.
        ---

        # Runner

        Run `python3 "${CLAUDE_SKILL_DIR}/scripts/run.py"` and read
        `${CLAUDE_SKILL_DIR}/references/notes.md`. Copy `${CLAUDE_SKILL_DIR}/templates/<name>.md`.
        The folder `${CLAUDE_SKILL_DIR}/templates/` holds starters.
        """)
    write(root, p + "skills/runner/scripts/run.py", "import os\nimport helper\nHERE = os.path.dirname(__file__)\n")
    write(root, p + "skills/runner/scripts/helper.py", "X = 1\n")
    write(root, p + "skills/runner/references/notes.md", "notes\n")
    write(root, p + "skills/runner/templates/a.md", "a\n")
    write(root, p + "skills/other/SKILL.md", """
        ---
        name: other
        description: Uses the same runner.
        ---
        # Other

        Run `python3 "${CLAUDE_SKILL_DIR}/scripts/run.py"`.
        """)
    write(root, p + "skills/other/scripts/run.py", "import os\nimport helper\nHERE = os.path.dirname(__file__)\n")
    write(root, p + "skills/other/scripts/helper.py", "X = 1\n")
    write(root, p + "vendor.json", json.dumps({
        "skills/other/scripts/run.py": "skills/runner/scripts/run.py",
        "skills/other/scripts/helper.py": "skills/runner/scripts/helper.py",
    }, indent=1))
    write(root, p + "skills/mcp-thing/SKILL.md", """
        ---
        name: mcp-thing
        description: Needs the MCP server.
        ---
        # MCP thing

        Install: plugin only. It talks to the plugin's MCP server.

        Run `${CLAUDE_PLUGIN_ROOT}/bin/helper`.
        """)
    write(root, p + "agents/checker.md", """
        ---
        name: checker
        description: Checks with the runner.
        ---
        # Checker

        Requires skill: runner

        ```bash
        %s
        python3 "$SKILL_DIR/scripts/run.py"
        ```
        """ % (SNIP % ("runner", "runner", "runner")))
    write(root, p + "agents/plain.md", """
        ---
        name: plain
        description: Needs no scripts.
        ---
        You read code.
        """)
    write(root, p + "agents/mcp-agent.md", """
        ---
        name: mcp-agent
        description: Uses the MCP server.
        ---
        # MCP agent

        Install: plugin only. It drives the plugin's MCP server.

        Run `${CLAUDE_PLUGIN_ROOT}/bin/helper`.
        """)
    write(root, p + "hooks/hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/h.py\""}]}]}}))
    write(root, p + "hooks/scripts/h.py", "import os\nprint(os.environ.get('CLAUDE_PLUGIN_ROOT'))\n")


def run_checks(root, plugin=None):
    return ci.Checker(root).run([plugin] if plugin else None)


class GoodPluginTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        good_plugin(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_good_plugin_is_clean(self):
        self.assertEqual([v.text() for v in run_checks(self.root)], [])

    def test_main_exit_codes_and_json(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(ci.main(["--root", self.root]), 0)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(ci.main(["--root", self.root, "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["violations"], [])

    def test_marker_helpers(self):
        sk = os.path.join(self.root, "plugins/good/skills/mcp-thing/SKILL.md")
        text = slurp(sk)
        self.assertTrue(ci.is_plugin_only(text))
        self.assertEqual(ci.plugin_only_reason(text), "It talks to the plugin's MCP server.")
        agent = slurp(os.path.join(self.root, "plugins/good/agents/checker.md"))
        self.assertEqual(ci.requires_skills(agent), ["runner"])
        self.assertEqual(ci.snippet_skills(agent), ["runner"])
        self.assertEqual(ci.requires_skills("# A\n\nRequires skill: `x`, y\n"), ["x", "y"])
        self.assertFalse(ci.is_plugin_only("# A\n\nSome text.\n\nInstall: plugin only. Late.\n"))


class ViolationTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        good_plugin(self.root)
        self.p = os.path.join(self.root, "plugins/good")

    def tearDown(self):
        shutil.rmtree(self.root)

    def rules(self):
        return [(v.path, v.line, v.rule) for v in run_checks(self.root)]

    def only(self, rule):
        found = run_checks(self.root)
        self.assertTrue(found, "expected a %s violation" % rule)
        self.assertEqual({v.rule for v in found}, {rule}, [v.text() for v in found])
        return found

    def test_r1a_plugin_root_in_skill(self):
        write(self.p, "skills/runner/SKILL.md", """
            ---
            name: runner
            description: x
            ---
            # Runner

            Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`.
            """)
        v = self.only("R1a")
        self.assertEqual(v[0].path, "plugins/good/skills/runner/SKILL.md")
        self.assertEqual(v[0].line, 7)
        self.assertIn("stays literal", v[0].message)

    def test_r1a_marker_needs_reason(self):
        write(self.p, "skills/mcp-thing/SKILL.md", "# MCP\n\nInstall: plugin only.\n\n${CLAUDE_PLUGIN_ROOT}/bin/x\n")
        v = self.only("R1a")
        self.assertIn("reason", v[0].message)

    def test_r1m_marker_not_under_title(self):
        write(self.p, "skills/mcp-thing/SKILL.md", """
            # MCP

            Some intro first.

            Install: plugin only. Needs the server.

            ${CLAUDE_PLUGIN_ROOT}/bin/x
            """)
        got = {r for _, _, r in self.rules()}
        self.assertEqual(got, {"R1m", "R1a"})

    def test_r1b_missing_skill_file(self):
        write(self.p, "skills/runner/SKILL.md", """
            # Runner

            Run `python3 "${CLAUDE_SKILL_DIR}/scripts/gone.py"`, then `${CLAUDE_SKILL_DIR}/../other/SKILL.md`.
            """)
        found = self.only("R1b")
        msgs = sorted(v.message for v in found)
        self.assertTrue(any("does not exist" in m for m in msgs))
        self.assertTrue(any("outside the skill folder" in m for m in msgs))

    def test_r1b_ignores_fenced_placeholder_and_glob(self):
        write(self.p, "skills/runner/SKILL.md", """
            # Runner

            ```bash
            ls "${CLAUDE_SKILL_DIR}/templates/"*.md "${CLAUDE_SKILL_DIR}/templates/<x>"
            ```
            """)
        self.assertEqual(self.rules(), [])

    def test_r2c_copy_differs(self):
        write(self.p, "skills/other/scripts/helper.py", "X = 2\n")
        v = self.only("R2c")
        self.assertEqual(v[0].path, "plugins/good/vendor.json")
        self.assertEqual(v[0].line, 3)
        self.assertIn("differs", v[0].message)

    def test_r2c_copy_and_source_missing(self):
        write(self.p, "vendor.json", json.dumps({
            "skills/other/scripts/run.py": "skills/runner/scripts/run.py",
            "skills/other/scripts/helper.py": "skills/runner/scripts/helper.py",
            "skills/other/scripts/new.py": "skills/runner/scripts/new.py",
            "skills/other/templates/a.md": "skills/runner/templates/a.md",
        }, indent=1))
        msgs = sorted(v.message for v in self.only("R2c"))
        self.assertTrue(any("canonical source skills/runner/scripts/new.py does not exist" in m for m in msgs))
        self.assertTrue(any("vendored copy skills/other/templates/a.md does not exist" in m for m in msgs))

    def test_r2c_bad_json(self):
        write(self.p, "vendor.json", "{not json")
        self.only("R2c")

    def test_r2f_vendored_py_missing_sibling(self):
        os.remove(os.path.join(self.p, "skills/other/scripts/helper.py"))
        write(self.p, "vendor.json", json.dumps({"skills/other/scripts/run.py": "skills/runner/scripts/run.py"}))
        v = self.only("R2f")
        self.assertIn("imports helper", v[0].message)

    def test_r2f_sibling_differs_and_not_vendored(self):
        write(self.p, "skills/other/scripts/helper.py", "X = 3\n")
        write(self.p, "vendor.json", json.dumps({"skills/other/scripts/run.py": "skills/runner/scripts/run.py"}))
        v = self.only("R2f")
        self.assertIn("not in vendor.json", v[0].message)

    def test_r2f_relative_and_from_imports(self):
        self.assertEqual(ci.imported_modules("from . import a\nfrom .b import c\nfrom d.e import f\nimport g.h\n"),
                         ["a", "b", "d", "g"])

    def test_r2g_skill_script_reads_plugin_root(self):
        write(self.p, "skills/runner/scripts/helper.py", "import os\nROOT = os.environ['CLAUDE_PLUGIN_ROOT']\n")
        write(self.p, "skills/other/scripts/helper.py", "import os\nROOT = os.environ['CLAUDE_PLUGIN_ROOT']\n")
        found = self.only("R2g")
        self.assertEqual(found[0].line, 2)

    def test_r3d_snippet_without_requires(self):
        write(self.p, "agents/checker.md", "# Checker\n\n" + SNIP % ("runner", "runner", "runner") + "\n")
        v = self.only("R3d")
        self.assertIn('no "Requires skill', v[0].message)

    def test_r3d_requires_unknown_skill(self):
        write(self.p, "agents/checker.md", "# Checker\n\nRequires skill: runner, nope\n\n" +
              SNIP % ("runner", "runner", "runner") + "\n")
        v = self.only("R3d")
        self.assertIn('"nope"', v[0].message)
        self.assertEqual(v[0].line, 3)

    def test_r3d_snippet_skill_not_listed(self):
        write(self.p, "agents/checker.md", "# Checker\n\nRequires skill: runner\n\n" +
              SNIP % ("other", "other", "other") + "\n")
        v = self.only("R3d")
        self.assertIn('uses skill "other"', v[0].message)

    def test_r3d_malformed_or_mismatched_snippet(self):
        write(self.p, "agents/checker.md", "# Checker\n\nRequires skill: runner\n\n"
              'SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/runner"\n' +
              SNIP % ("runner", "other", "runner") + "\n")
        msgs = [v.message for v in self.only("R3d")]
        self.assertTrue(any("exact shape" in m for m in msgs))
        self.assertTrue(any("different skills" in m for m in msgs))

    def test_powershell_snippet(self):
        ok = ('# Checker\n\nRequires skill: runner\n\n```powershell\n'
              '$SKILL_DIR = "${CLAUDE_PLUGIN_ROOT}/skills/runner"\n'
              'if (-not (Test-Path $SKILL_DIR)) { $SKILL_DIR = @(".claude/skills/runner", '
              '"$HOME/.claude/skills/runner") | Where-Object { Test-Path $_ } | Select-Object -First 1 }\n```\n')
        write(self.p, "agents/checker.md", ok)
        self.assertEqual(self.rules(), [])
        write(self.p, "agents/checker.md", ok.replace(".claude/skills/runner\"", ".claude/skills/other\"", 1))
        v = self.only("R3d")
        self.assertIn("PowerShell", v[0].message)

    def test_r3d_direct_skill_path(self):
        write(self.p, "agents/checker.md", "# Checker\n\nRun `${CLAUDE_PLUGIN_ROOT}/skills/runner/scripts/run.py`.\n")
        v = self.only("R3d")
        self.assertIn("locate snippet", v[0].message)

    def test_r3e_agent_plugin_scripts(self):
        write(self.p, "agents/plain.md", "# Plain\n\nRun `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/x.py`.\n")
        v = self.only("R3e")
        self.assertIn("scripts/x.py", v[0].message)
        self.assertEqual(v[0].line, 3)

    def test_requires_skill_matches_frontmatter_name(self):
        write(self.p, "skills/runner/SKILL.md", "---\nname: run-it\ndescription: x\n---\n# Runner\n")
        write(self.p, "agents/checker.md", "# Checker\n\nRequires skill: run-it\n\n" +
              SNIP % ("runner", "runner", "runner") + "\n")
        self.assertEqual(self.rules(), [])

    def test_text_format_and_exit_code(self):
        write(self.p, "agents/plain.md", "# Plain\n\n${CLAUDE_PLUGIN_ROOT}/scripts/x.py\n")
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(ci.main(["--root", self.root]), 1)
        self.assertRegex(out.getvalue().strip(), r"^plugins/good/agents/plain\.md:3: R3e: ")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(ci.main(["--root", self.root, "--json"]), 1)
        data = json.loads(out.getvalue())
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["violations"][0]["rule"], "R3e")

    def test_plugin_filter(self):
        good_plugin(self.root, "second")
        write(self.root, "plugins/second/agents/plain.md", "# Plain\n\n${CLAUDE_PLUGIN_ROOT}/x\n")
        self.assertEqual(run_checks(self.root, "good"), [])
        self.assertEqual(len(run_checks(self.root, "second")), 1)


class SyncVendorTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        good_plugin(self.root)
        self.p = os.path.join(self.root, "plugins/good")

    def tearDown(self):
        shutil.rmtree(self.root)

    def quiet(self, argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return sv.main(argv)

    def test_in_sync(self):
        self.assertEqual(self.quiet(["--root", self.root, "--check"]), 0)
        self.assertEqual(self.quiet(["--root", self.root]), 0)

    def test_check_reports_and_sync_fixes(self):
        write(self.p, "skills/runner/scripts/helper.py", "X = 42\n", mode=0o755)
        os.remove(os.path.join(self.p, "skills/other/scripts/run.py"))
        bad, report = sv.sync(self.root, check=True)
        self.assertEqual(bad, 2)
        self.assertTrue(any("missing" in r for r in report))
        self.assertTrue(any("stale" in r for r in report))
        self.assertEqual(self.quiet(["--root", self.root, "--check"]), 1)
        # --check changed nothing
        self.assertFalse(os.path.exists(os.path.join(self.p, "skills/other/scripts/run.py")))
        self.assertEqual(self.quiet(["--root", self.root]), 0)
        copy = os.path.join(self.p, "skills/other/scripts/helper.py")
        self.assertEqual(slurp(copy), "X = 42\n")
        self.assertTrue(os.access(copy, os.X_OK))
        self.assertTrue(os.path.exists(os.path.join(self.p, "skills/other/scripts/run.py")))
        self.assertEqual(self.quiet(["--root", self.root, "--check"]), 0)
        self.assertEqual(run_checks(self.root), [])

    def test_creates_missing_folders(self):
        write(self.p, "vendor.json", json.dumps({"skills/other/templates/deep/a.md": "skills/runner/templates/a.md"}))
        self.assertEqual(self.quiet(["--root", self.root]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.p, "skills/other/templates/deep/a.md")))

    def test_missing_canonical_fails_both_modes(self):
        write(self.p, "vendor.json", json.dumps({"skills/other/x.md": "skills/runner/nope.md"}))
        self.assertEqual(self.quiet(["--root", self.root]), 1)
        self.assertEqual(self.quiet(["--root", self.root, "--check"]), 1)

    def test_bad_vendor_json(self):
        write(self.p, "vendor.json", '["not", "a", "map"]')
        self.assertEqual(self.quiet(["--root", self.root, "--check"]), 1)

    def test_no_vendor_files(self):
        os.remove(os.path.join(self.p, "vendor.json"))
        self.assertEqual(self.quiet(["--root", self.root, "--check"]), 0)


if __name__ == "__main__":
    unittest.main()
