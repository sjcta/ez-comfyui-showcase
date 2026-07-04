from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MultiReferenceUiTests(unittest.TestCase):
    def test_single_multi_reference_mode_preserves_first_reference(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("function _ensureMultiRefsStartWithSingleReference()", generate_js)
        self.assertIn("function _syncSingleReferenceFromFirstMultiRef(trimMulti)", generate_js)
        self.assertIn("if (nextMode === 'multi') _ensureMultiRefsStartWithSingleReference();", generate_js)
        self.assertIn("else _syncSingleReferenceFromFirstMultiRef(true);", generate_js)
        self.assertIn("if (_imageReferenceModeNeedsMultiRefs(_currentImageReferenceMode())) {\n        _ensureMultiRefsStartWithSingleReference();", generate_js)
        self.assertIn("if (!_imageReferenceModeNeedsMultiRefs(_currentImageReferenceMode())) {\n          _syncSingleReferenceFromFirstMultiRef(true);", generate_js)


if __name__ == "__main__":
    unittest.main()
