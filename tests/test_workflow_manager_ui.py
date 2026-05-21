from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkflowManagerUiContractTests(unittest.TestCase):
    def test_drag_handle_stretches_with_workflow_card_height(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".wf-mgr-card .wf-mgr-drag", css)
        self.assertIn("align-self: stretch", css)
        self.assertIn("height: auto", css)
        self.assertIn("align-items: stretch", css)

    def test_workflow_picker_preview_updates_from_completed_jobs(self):
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertIn("function refreshWorkflowPreviewFromJob", workflows_js)
        self.assertIn("window.CW.refreshWorkflowPreviewFromJob = refreshWorkflowPreviewFromJob", workflows_js)
        self.assertIn("CW.refreshWorkflowPreviewFromJob(job)", history_js)
        self.assertIn("CW.refreshWorkflowPreviewFromJob(job)", card_manager_js)
        self.assertNotIn("window.CW.refreshWorkflowPreviewFromJob = _refreshWorkflowPreviewFromJob", history_js)
        self.assertIn("refresh workflow previews after delete failed", history_js)

    def test_workflow_picker_preview_reuses_sensitive_blur_treatment(self):
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _isSensitiveWorkflowPreview", workflows_js)
        self.assertIn("preview.classList.toggle('wf-sensitive'", workflows_js)
        self.assertIn("previewInfo.sensitive ? ' wf-sensitive' : ''", workflows_js)
        self.assertIn(".wf-card-preview.wf-sensitive img", css)
        self.assertIn("filter: blur(7px) saturate(.82) brightness(.9)", css)

    def test_mobile_workflow_picker_spacing_is_even(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("gap: 14px", css)
        self.assertIn("padding: 6px 16px 18px", css)
        self.assertIn("scroll-padding-left: 16px", css)
        self.assertNotIn("gap: 8px; padding: 0 12px 16px", css)

    def test_workflow_titles_use_custom_name_before_filename_fallback(self):
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()
        node_editor_js = (ROOT / "static/js/modules/node-editor.js").read_text()
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()

        self.assertIn("function workflowDisplayName(fname, meta)", workflows_js)
        self.assertIn("var custom = String((meta && meta.name) || '').trim();", workflows_js)
        self.assertIn("if (custom) return custom;", workflows_js)
        self.assertIn("return String(fname || '').replace(/\\.json$/i, '');", workflows_js)
        self.assertIn("genTitleText.textContent = displayName + ' 快速出图';", workflows_js)
        self.assertIn("if (ws) ws.textContent = displayName;", workflows_js)
        self.assertIn("window.CW.workflowDisplayName = workflowDisplayName;", workflows_js)
        self.assertIn("$('#wfEditName').value = String(meta.name || '').trim();", workflows_js)
        self.assertIn("CW.workflowDisplayName(fname)", node_editor_js)
        self.assertIn("CW.workflowDisplayName(workflow, meta)", auth_js)
        self.assertNotIn("name.replace('.json', '') + ' 快速出图'", workflows_js)


if __name__ == "__main__":
    unittest.main()
