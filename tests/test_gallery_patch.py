import pathlib
import unittest


class GalleryPatchTest(unittest.TestCase):
    def test_history_patch_treats_openlb_source_argument_as_index_only_change(self):
        src = pathlib.Path("static/js/modules/history.js").read_text()

        self.assertIn(r"CW\.openLB\(\d+(?:,\s*this)?\)", src)


if __name__ == "__main__":
    unittest.main()
