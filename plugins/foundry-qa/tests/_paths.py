import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Each script lives in the skill that owns it (the canonical copy). Copies of
# shared modules vendored into other skills are listed in vendor.json and
# checked byte-identical by test_vendor.py.
SCRIPT_HOME = {
    "done_gate.py": SKILLS / "done-gate" / "scripts",
    "qa_yaml.py": SKILLS / "done-gate" / "scripts",
    "a11y_check.py": SKILLS / "a11y-check" / "scripts",
    "visual_baseline.py": SKILLS / "visual-baseline" / "scripts",
    "persona_run.py": SKILLS / "persona-run" / "scripts",
    "explore.py": SKILLS / "explore" / "scripts",
}
DONE_GATE_TEMPLATES = SKILLS / "done-gate" / "templates"
PERSONA_TEMPLATES = SKILLS / "persona-run" / "templates"


def script(name):
    return SCRIPT_HOME[name] / name


# Canonical dirs go first on sys.path, in SCRIPT_HOME order, so an import
# always resolves to the canonical copy rather than a vendored one.
for d in reversed(list(dict.fromkeys(SCRIPT_HOME.values()))):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
SCRIPT_HOME_MODULES = {n[:-3] for n in SCRIPT_HOME}
