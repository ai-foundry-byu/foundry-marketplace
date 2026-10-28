import unittest

import _paths  # noqa: F401
import explore as ex


class TestExplore(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(ex.normalize("http://h/a/#top"), "http://h/a")
        self.assertEqual(ex.normalize("http://h"), "http://h/")
        self.assertEqual(ex.normalize("http://h/a?x=1#f"), "http://h/a?x=1")

    def test_should_visit(self):
        o = "http://h:3000"
        self.assertTrue(ex.should_visit("http://h:3000/about", o))
        self.assertFalse(ex.should_visit("http://other/about", o))
        self.assertFalse(ex.should_visit("mailto:a@b.c", o))
        self.assertFalse(ex.should_visit("http://h:3000/report.pdf", o))
        self.assertFalse(ex.should_visit("http://h:3000/account/logout", o))
        self.assertFalse(ex.should_visit("http://h:3000/items/3/delete", o))

    def test_verdict(self):
        v_ok = ex.PageVisit("u", "d", findings=[ex.Finding("warn", "no-h1", "u", "")])
        v_bad = ex.PageVisit("u", "d", findings=[ex.Finding("error", "console", "u", "")])
        self.assertEqual(ex.verdict([v_ok], True), 0)
        self.assertEqual(ex.verdict([v_ok, v_bad], True), 1)
        self.assertEqual(ex.verdict([], False), 6)


if __name__ == "__main__":
    unittest.main()
