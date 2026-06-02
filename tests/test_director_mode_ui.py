from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DirectorModeUiTests(unittest.TestCase):
    def test_quick_form_has_director_panel_and_submission_sync(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("function _hasDirectorWorkflow(fields)", generate_js)
        self.assertIn("LTXDirector", generate_js)
        self.assertIn("directorModeBtn", generate_js)
        self.assertIn("自动导入提示词", generate_js)
        self.assertIn("function _directorParsePromptSegments(text)", generate_js)
        self.assertIn("function _directorDefaultSegmentPrompt(seg, idx, segments)", generate_js)
        self.assertIn("function _initDirectorTrackDrag(panel)", generate_js)
        self.assertIn("function _mountDirectorPanelToBody()", generate_js)
        self.assertIn("function _removeBodyDirectorPanel()", generate_js)
        self.assertIn("data-director-drag=\"move\"", generate_js)
        self.assertIn("data-director-field=\"end\"", generate_js)
        self.assertIn("function _renderDirectorTrackOnly()", generate_js)
        self.assertIn("directorShotImageInput", generate_js)
        self.assertIn("function selectDirectorShotImage(id)", generate_js)
        self.assertIn("function _handleDirectorShotFile(file, shotId)", generate_js)
        self.assertIn("Smooth cinematic transition from this reference image to the next reference image", generate_js)
        self.assertIn("local_prompts: segments.map(function(seg) { return seg.prompt || ''; }).join('|')", generate_js)
        self.assertIn("var existing = (_directorState.segments || []).slice();", generate_js)
        self.assertIn("imageFile: old.imageFile || ''", generate_js)
        self.assertIn("未清空多出的", generate_js)
        self.assertIn("if (field === 'prompt') {\n          seg.prompt = ev.target.value;\n          _renderDirectorTrackOnly();\n          _syncDirectorInputs();\n          return;\n        }", generate_js)
        self.assertIn("if (field === 'end') {", generate_js)
        self.assertIn("_syncDirectorShotControls(seg);", generate_js)
        self.assertIn("application/x-ez-history-image", generate_js)
        self.assertIn("await _waitForDirectorUploads();", generate_js)
        self.assertIn("$$('#quickFormFields [data-key]').forEach(collectSubmitControl);", generate_js)
        self.assertIn("$$('#directorPanel [data-key]').forEach(collectSubmitControl);", generate_js)
        self.assertIn("window.CW.toggleDirectorPanel = toggleDirectorPanel;", generate_js)
        self.assertIn("window.CW.removeDirectorShot = removeDirectorShot;", generate_js)
        self.assertIn("window.CW.importDirectorPromptSegments = importDirectorPromptSegments;", generate_js)
        self.assertIn("window.CW.selectDirectorShotImage = selectDirectorShotImage;", generate_js)

    def test_director_panel_has_floating_layout_styles(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".director-panel", css)
        self.assertIn("position: fixed;", css)
        self.assertIn(".director-drop", css)
        self.assertIn(".director-tools", css)
        self.assertIn(".director-shot-thumb.is-text-only", css)
        self.assertIn(".director-shot-actions", css)
        self.assertIn(".director-shot-image-btn", css)
        self.assertIn(".director-track", css)
        self.assertIn("touch-action: none;", css)
        self.assertIn(".director-timeline-handle", css)
        self.assertIn(".director-shot-list", css)
        self.assertIn("bottom: max(10px, env(safe-area-inset-bottom));", css)
        self.assertIn("padding-bottom: max(72px, env(safe-area-inset-bottom));", css)


if __name__ == "__main__":
    unittest.main()
