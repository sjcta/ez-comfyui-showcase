from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CssLoadingContractTests(unittest.TestCase):
    def test_primary_stylesheet_loads_before_module_loader(self):
        index_html = (ROOT / "static/index.html").read_text()
        loader_js = (ROOT / "static/js/module_loader.js").read_text()

        css_link = '<link id="cwStyleLink" rel="stylesheet" href="static/css/style.css?v=1780506197">'
        loader_script = '<script src="static/js/module_loader.js?v=1780506197"></script>'
        self.assertIn(css_link, index_html)
        self.assertIn(loader_script, index_html)
        self.assertLess(index_html.index(css_link), index_html.index(loader_script))
        self.assertIn("if (!document.getElementById('cwStyleLink'))", loader_js)


if __name__ == "__main__":
    unittest.main()
