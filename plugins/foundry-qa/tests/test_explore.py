import unittest

import _paths  # noqa: F401
import explore as ex


class TestExplore(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(ex.normalize("http://h/a/#top"), "http://h/a")
        self.assertEqual(ex.normalize("http://h"), "http://h/")
        self.assertEqual(ex.normalize("http://h/a?x=1#f"), "http://h/a?x=1")

    def test_hash_routes_are_distinct_pages(self):
        self.assertEqual(ex.normalize("http://h/#/group/1"), "http://h/#/group/1")
        self.assertEqual(ex.normalize("http://h/index.html#/group/1/"), "http://h/index.html#/group/1")
        self.assertEqual(ex.normalize("http://h/#!/settings"), "http://h/#!/settings")
        self.assertEqual(ex.normalize("http://h/#/"), "http://h/")         # the empty route is the root
        self.assertNotEqual(ex.normalize("http://h/#/group/1"), ex.normalize("http://h/#/group/2"))

    def test_destructive_hash_routes_are_skipped(self):
        o = "http://h:3000"
        self.assertTrue(ex.should_visit("http://h:3000/#/group/1", o))
        self.assertFalse(ex.should_visit("http://h:3000/#/logout", o))
        self.assertFalse(ex.should_visit("http://h:3000/#/items/3/delete", o))

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
