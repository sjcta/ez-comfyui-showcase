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

    def test_multi_reference_limits_and_prompt_mentions_are_rendered(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("id=\"multiRefsLimitHint\"", generate_js)
        self.assertIn("data-min-refs", generate_js)
        self.assertIn("上限 ' + escH(String(maxRefs)) + ' 张", generate_js)
        self.assertIn("id=\"promptRefMentionMenu\"", generate_js)
        self.assertIn("function _initPromptReferenceMentions()", generate_js)
        self.assertIn("function _compilePromptReferenceBindings(prompt)", generate_js)
        self.assertIn("Multi-reference image binding:", generate_js)
        self.assertIn("function _invalidPromptReferenceMentions(prompt)", generate_js)
        self.assertIn("提示词中的 ' + invalidMentions.join('、') + ' 没有对应参考图", generate_js)
        self.assertIn("prompt-ref-mention-menu", css)
        self.assertIn("multi-ref-token", css)


if __name__ == "__main__":
    unittest.main()
