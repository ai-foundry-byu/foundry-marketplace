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


    def test_same_page_anchor(self):
        """R3-D3: a skip link (#app) is not a route; #/ and #!/x are."""
        for raw in ("#app", "#top", "#", "#main-content"):
            self.assertTrue(ex.is_same_page_anchor(raw), raw)
        for raw in ("#/", "#/group/1", "#!/settings", "/about", "about.html", "http://h/x#app", ""):
            self.assertFalse(ex.is_same_page_anchor(raw), raw)

    def test_back_check_target_skips_skip_links(self):
        o = "http://h"
        links = [{"href": "http://h/#app", "raw": "#app"}, {"href": "http://h/#/", "raw": "#/"},
                 {"href": "http://h/#/two", "raw": "#/two"}]
        self.assertEqual(ex.back_check_target(links, "http://h/#/one", o), "http://h/")
        self.assertEqual(ex.back_check_target(links, "http://h/", o), "http://h/#/two")
        self.assertIsNone(ex.back_check_target(links[:1], "http://h/#/one", o))



class TestExploreSource(unittest.TestCase):
    def test_compiles_without_syntax_warnings(self):
        import warnings
        src = _paths.script("explore.py").read_text()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(src, "explore.py", "exec")


if __name__ == "__main__":
    unittest.main()
