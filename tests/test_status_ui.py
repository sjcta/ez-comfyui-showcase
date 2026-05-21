from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StatusUiContractTests(unittest.TestCase):
    def test_vram_status_filters_raw_ssh_errors(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("function _safeVramMessage", status_js)
        self.assertIn("connection\\s+closed", status_js)
        self.assertIn("port\\s+\\d+", status_js)
        self.assertIn("VRAM 暂不可用", status_js)
        self.assertIn("_safeVramMessage(gpu)", status_js)
        self.assertNotIn("gpu && gpu.message ? gpu.message", status_js)

    def test_statusbar_vram_gap_is_compact(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".sb-vram { display: flex; align-items: center; gap: 5px;", css)
        self.assertIn(".sb-vram { max-width: none; min-width: 0; flex: 1 1 auto; gap: 5px; }", css)

    def test_status_poll_sends_current_device_target(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("new URLSearchParams()", status_js)
        self.assertIn("target_node_id", status_js)
        self.assertIn("target_instance", status_js)

    def test_prompt_aux_card_uses_queue_counts_for_busy_state(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("var instBusy = (inst.queue_running || 0) > 0 || (inst.queue_pending || 0) > 0", status_js)
        self.assertIn("isAux && instBusy", status_js)

    def test_service_button_keeps_state_text_compact(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("const pendingInst = (target && (target.queue_pending || 0) > 0)", status_js)
        self.assertIn("|| runningInst || pendingInst", status_js)
        self.assertIn("comfyState.textContent = stateText", status_js)
        self.assertIn("GPU ${util}%", status_js)
        self.assertIn("util >= 70", status_js)
        self.assertIn("util >= 95", status_js)
        self.assertIn("function _runningInstanceSummaries", status_js)
        self.assertIn("function _runningStateText", status_js)
        self.assertIn("return item.label + ': ' + (item.text || (item.pct + '%'))", status_js)
        self.assertIn(".join(' | ')", status_js)
        self.assertNotIn("showTargetName", status_js)
        self.assertNotIn("targetName + ' ' + stateText", status_js)

    def test_service_button_preserves_multi_instance_progress_on_job_updates(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()
        poll_js = (ROOT / "static/js/modules/poll_manager.js").read_text()

        self.assertIn("var _lastRunningSummaries = []", status_js)
        self.assertIn("function _activeJobStatesByInstance", status_js)
        self.assertIn("function _mergeRunningSummaries", status_js)
        self.assertIn("_rememberRunningSummaries(runningSummaries, anyRunning || localRunning)", status_js)
        self.assertIn("var runningSummaries = _mergeRunningSummaries(_lastRunningSummaries, _activeJobStatesByInstance())", status_js)
        self.assertIn("comfyState.textContent = _runningStateText(runningSummaries, activePct)", status_js)
        self.assertIn("if (window.CW.syncComfyServiceButton) window.CW.syncComfyServiceButton();", poll_js)

    def test_service_button_labels_untracked_remote_running_without_zero_percent(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("remote_untracked_running", status_js)
        self.assertIn("progress_known === false", status_js)
        self.assertIn("'未追踪任务中'", status_js)
        self.assertIn("item.text || (item.pct + '%')", status_js)
        self.assertIn("if ((summaries || []).length === 1 && summaries[0].text) return summaries[0].text", status_js)
        self.assertNotIn("外部任务", status_js)

    def test_instance_cards_do_not_offer_manual_target_selection(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertNotIn("当前目标", status_js)
        self.assertNotIn("设为目标", status_js)
        self.assertNotIn("setTargetInstance", status_js)

    def test_instance_popup_does_not_show_explanatory_note(self):
        index_html = (ROOT / "static/index.html").read_text()

        self.assertNotIn("inst-popup-note", index_html)
        self.assertNotIn("集中查看实例状态", index_html)
        self.assertNotIn("实例卡片状态语义保持不变", index_html)


if __name__ == "__main__":
    unittest.main()
