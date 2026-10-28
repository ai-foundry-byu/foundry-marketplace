import unittest

import _paths  # noqa: F401
import qa_yaml


JOURNEY = '''
# a done-journey
name: sign up
devices: [desktop-1440x900, phone-390x844]
steps:
  - goto: /signup
  - fill: {selector: "#email", value: "student@example.com"}
  - click: "button[type=submit]"
  - press:
      selector: "#search"
      key: Enter
  - wait_for: "[data-testid=welcome]"
assertions:
  - visible: "[data-testid=welcome]"
  - text: {selector: h1, contains: "Welcome, friend"}
  - url_contains: /welcome   # trailing comment
  - no_console_errors: true
timeout_ms: 8000
'''


class TestQaYaml(unittest.TestCase):
    def test_journey_shape(self):
        d = qa_yaml.loads(JOURNEY)
        self.assertEqual(d["name"], "sign up")
        self.assertEqual(d["devices"], ["desktop-1440x900", "phone-390x844"])
        self.assertEqual(d["steps"][0], {"goto": "/signup"})
        self.assertEqual(d["steps"][1], {"fill": {"selector": "#email", "value": "student@example.com"}})
        self.assertEqual(d["steps"][3], {"press": {"selector": "#search", "key": "Enter"}})
        self.assertEqual(d["assertions"][1], {"text": {"selector": "h1", "contains": "Welcome, friend"}})
        self.assertEqual(d["assertions"][2], {"url_contains": "/welcome"})
        self.assertIs(d["assertions"][3]["no_console_errors"], True)
        self.assertEqual(d["timeout_ms"], 8000)

    def test_scalars(self):
        d = qa_yaml.loads("a: 1\nb: 1.5\nc: true\nd: null\ne: yes\nf: 'it''s'\ng: \"x\\ny\"\nh: http://x:3000/a")
        self.assertEqual(d, {"a": 1, "b": 1.5, "c": True, "d": None, "e": "yes", "f": "it's", "g": "x\ny",
                             "h": "http://x:3000/a"})

    def test_hash_inside_quotes_is_not_comment(self):
        self.assertEqual(qa_yaml.loads('s: "#id" # real comment'), {"s": "#id"})

    def test_unquoted_hash_is_a_comment_like_real_yaml(self):
        self.assertEqual(qa_yaml.loads("s: #id"), {"s": None})

    def test_sequence_at_same_indent_as_key(self):
        d = qa_yaml.loads("steps:\n- goto: /\n- click: a\n")
        self.assertEqual(d, {"steps": [{"goto": "/"}, {"click": "a"}]})

    def test_nested_mapping_in_sequence(self):
        d = qa_yaml.loads("items:\n  - id: 1\n    name: one\n  - id: 2\n    name: two\n")
        self.assertEqual(d["items"], [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}])

    def test_flow_nested(self):
        self.assertEqual(qa_yaml.loads("x: {a: [1, 2, {b: c}], d: 'e, f'}"), {"x": {"a": [1, 2, {"b": "c"}], "d": "e, f"}})

    def test_empty_flow(self):
        self.assertEqual(qa_yaml.loads("a: []\nb: {}"), {"a": [], "b": {}})

    def test_colon_without_space_is_plain(self):
        self.assertEqual(qa_yaml.loads("- a:hover\n- text=Sign in"), ["a:hover", "text=Sign in"])

    def test_errors_have_line_numbers(self):
        with self.assertRaises(qa_yaml.YamlError) as cm:
            qa_yaml.loads("a: 1\n  b: 2\n")
        self.assertEqual(cm.exception.line, 2)
        with self.assertRaises(qa_yaml.YamlError):
            qa_yaml.loads("a: |\n  text\n")
        with self.assertRaises(qa_yaml.YamlError):
            qa_yaml.loads("a: 1\na: 2\n")
        with self.assertRaises(qa_yaml.YamlError):
            qa_yaml.loads("a: {b: c\n")
        with self.assertRaises(qa_yaml.YamlError):
            qa_yaml.loads("a:\n\t- x\n")

    def test_json_accepted(self):
        self.assertEqual(qa_yaml.load_text('{"steps": [{"goto": "/"}]}'), {"steps": [{"goto": "/"}]})

    def test_leading_document_marker(self):
        self.assertEqual(qa_yaml.loads("---\na: 1\n"), {"a": 1})

    def test_empty(self):
        self.assertIsNone(qa_yaml.loads("# nothing\n\n"))

    def test_matches_pyyaml_when_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        self.assertEqual(qa_yaml.loads(JOURNEY), yaml.safe_load(JOURNEY))


if __name__ == "__main__":
    unittest.main()
