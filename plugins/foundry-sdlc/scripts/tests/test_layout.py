"""Layout tests: vendored copies match their canonical file, every skill is
self-contained, and every agent locate snippet names a real skill.
Run: python3 -m unittest discover -s scripts/tests"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
SKILL_REF = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/([A-Za-z0-9_./-]+)")
PLUGIN_ONLY = re.compile(r"^# .*\n+Install: plugin only\. ", re.M)


class VendorTests(unittest.TestCase):
    def test_vendored_copies_are_byte_identical(self):
        vendor = json.loads((PLUGIN / "vendor.json").read_text(encoding="utf-8"))
        self.assertTrue(vendor)
        for copy, canon in vendor.items():
            with self.subTest(copy=copy):
                self.assertTrue((PLUGIN / canon).is_file(), canon)
                self.assertEqual((PLUGIN / copy).read_bytes(), (PLUGIN / canon).read_bytes(),
                                 f"{copy} drifted from {canon}: re-copy it")

    def test_vendored_python_has_its_imports(self):
        for script in PLUGIN.glob("skills/*/scripts/*.py"):
            for mod in re.findall(r"^import (\w+)\s+# noqa", script.read_text(encoding="utf-8"), re.M):
                with self.subTest(script=str(script.relative_to(PLUGIN)), mod=mod):
                    self.assertTrue((script.parent / f"{mod}.py").is_file())


class SkillTests(unittest.TestCase):
    def test_skills_are_self_contained(self):
        for skill_md in sorted(PLUGIN.glob("skills/*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8")
            with self.subTest(skill=skill_md.parent.name):
                if "CLAUDE_PLUGIN_ROOT" in text:
                    self.assertRegex(text, PLUGIN_ONLY)
                for ref in SKILL_REF.findall(text):
                    self.assertTrue((skill_md.parent / ref.rstrip(".")).exists(), ref)

    def test_agent_locate_snippets_name_real_skills(self):
        for agent in PLUGIN.glob("agents/*.md"):
            text = agent.read_text(encoding="utf-8")
            for name in re.findall(r"skills/([\w-]+)\"", text):
                with self.subTest(agent=agent.name, skill=name):
                    self.assertTrue((PLUGIN / "skills" / name / "SKILL.md").is_file())

    def test_standalone_copies_run(self):
        """Copy each skill that ships scripts on its own and run them from the copy."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty").mkdir()
            for sdir in sorted(PLUGIN.glob("skills/*/scripts")):
                skill = sdir.parent
                copy = Path(tmp) / "skills" / skill.name
                shutil.copytree(skill, copy)
                with self.subTest(skill=skill.name):
                    out = subprocess.run([sys.executable, str(copy / "scripts" / "sdlc_stage.py"),
                                          str(Path(tmp) / "empty"), "--json"],
                                         capture_output=True, text=True)
                    self.assertEqual(json.loads(out.stdout)["current_stage"], 0, out.stderr)
            proj = Path(tmp) / "proj"
            np = Path(tmp) / "skills" / "new-project" / "scripts" / "new_project.py"
            r = subprocess.run([sys.executable, str(np), str(proj), "--name", "Demo"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((proj / "PRD.md").is_file())
            self.assertTrue((proj / "tools" / "gen_stories.py").is_file())


class InstructionContractTests(unittest.TestCase):
    """Wave D: what the CLI does (2.1.308) and what the instructions must therefore say."""

    def read(self, rel):
        return (PLUGIN / rel).read_text(encoding="utf-8")

    def test_story_verifier_returns_its_report_as_text(self):
        """The CLI refuses a subagent's Write of a report file ("Subagents should return findings
        as text, not write report files."), so the verifier returns the exact file content."""
        text = self.read("agents/story-verifier.md")
        tools = re.search(r"^tools:(.*)$", text, re.M).group(1)
        self.assertNotIn("Write", tools)
        self.assertNotIn("Edit", tools)
        out = text[text.index("## Output format"):]
        self.assertIn("Never write the report file yourself", out)
        self.assertIn("Subagents should return findings as text, not write report files.", out)
        self.assertIn("one fenced block", out)
        self.assertRegex(out, r"first line (inside the block|of the report) is `Commit: <sha>`")
        self.assertRegex(out, r"```text\nCommit: ")

    def test_callers_write_the_verifier_report_verbatim(self):
        for rel in ("skills/ship/SKILL.md", "skills/sdlc/SKILL.md"):
            text = self.read(rel)
            with self.subTest(skill=rel):
                self.assertRegex(text, r"(?s)you write `\.qa/verify/<id>\.md` yourself.{0,200}verbatim")
                self.assertIn("never by the agent", text)

    def test_skills_refresh_project_tools_before_using_them(self):
        for rel in ("skills/new-project/SKILL.md", "skills/write-prd/SKILL.md", "skills/ship/SKILL.md"):
            with self.subTest(skill=rel):
                self.assertIn('python3 "${CLAUDE_SKILL_DIR}/scripts/gen_stories.py" --refresh-tools .',
                              self.read(rel))

    def test_ship_marks_leftover_tasks_follow_up(self):
        self.assertIn('python3 "${CLAUDE_SKILL_DIR}/scripts/sdlc_stage.py" . --mark-follow-ups',
                      self.read("skills/ship/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
