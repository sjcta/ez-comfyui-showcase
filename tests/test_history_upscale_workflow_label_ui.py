import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class HistoryUpscaleWorkflowLabelUITests(unittest.TestCase):
    def test_upscale_generic_preview_uses_custom_workflow_name(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text(encoding="utf-8")

        self.assertIn("function _workflowCustomDisplayName(workflow)", history_js)
        self.assertIn("function _displayPromptForWorkflowItem(item, text)", history_js)
        self.assertIn("_isGenericUpscaleLabel(text)", history_js)
        self.assertIn("return _displayPromptForWorkflowItem(item, text);", history_js)
        self.assertIn("const label = _displayPromptForWorkflowItem(j, rawLabel) || rawLabel;", history_js)
        self.assertIn("const displayPrompt = _displayPromptForWorkflowItem(job, rawDisplayPrompt) || rawDisplayPrompt;", history_js)

    def test_completed_upscale_card_avoids_duplicate_workflow_label(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text(encoding="utf-8")

        self.assertIn("const showWfLabel = wfLabel && wfLabel !== label;", history_js)
        self.assertIn("const showWfLabel = wfLabel && wfLabel !== displayPrompt;", history_js)


if __name__ == "__main__":
    unittest.main()
