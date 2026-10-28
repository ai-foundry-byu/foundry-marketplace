"""Every vendored copy listed in vendor.json is byte-identical to its canonical
file, and every skill's scripts can import their siblings from inside the skill
folder alone (so a skill copied on its own still works)."""
import ast
import json
import unittest

import _paths


class TestVendor(unittest.TestCase):
    def test_vendored_copies_match_canonical(self):
        mapping = json.loads((_paths.PLUGIN / "vendor.json").read_text())
        self.assertTrue(mapping)
        for copy, canonical in mapping.items():
            c, k = _paths.PLUGIN / copy, _paths.PLUGIN / canonical
            self.assertTrue(k.is_file(), f"canonical missing: {canonical}")
            self.assertTrue(c.is_file(), f"vendored copy missing: {copy}")
            self.assertEqual(c.read_bytes(), k.read_bytes(),
                             f"{copy} drifted from {canonical}: re-copy it")

    def test_each_skill_has_every_sibling_it_imports(self):
        for scripts in sorted(_paths.SKILLS.glob("*/scripts")):
            local = {p.stem for p in scripts.glob("*.py")}
            for py in scripts.glob("*.py"):
                tree = ast.parse(py.read_text())
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name.split(".")[0] for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                        names = [node.module.split(".")[0]]
                    for n in names:
                        if n in _paths.SCRIPT_HOME_MODULES:
                            self.assertIn(n, local, f"{py.relative_to(_paths.PLUGIN)} imports {n}, "
                                                    f"which is not in {scripts.relative_to(_paths.PLUGIN)}")


if __name__ == "__main__":
    unittest.main()
