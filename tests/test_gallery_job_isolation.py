from pathlib import Path
import unittest

import app


ROOT = Path(__file__).resolve().parents[1]


class GalleryJobIsolationContractTests(unittest.TestCase):
    def test_ws_and_render_paths_filter_active_jobs_by_current_user(self):
        poll_manager = (ROOT / "static/js/modules/poll_manager.js").read_text()
        history = (ROOT / "static/js/modules/history.js").read_text()
        card_manager = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertIn("function _isJobVisibleToCurrentUser", poll_manager)
        self.assertIn("if (!_isJobVisibleToCurrentUser(job))", poll_manager)
        self.assertIn("serverJobs[i]", poll_manager)
        self.assertIn("_isJobVisibleToCurrentUser(serverJobs[i])", poll_manager)
        self.assertIn("function _isJobVisibleToCurrentUser", history)
        self.assertIn("function _isJobVisibleToCurrentUser", card_manager)
        self.assertIn("user.role === 'admin'", poll_manager)
        self.assertIn("user.role === 'admin'", history)
        self.assertIn("user.role === 'admin'", card_manager)
        self.assertIn("filter(_isJobVisibleToCurrentUser)", history)
        self.assertIn("filter(_isJobVisibleToCurrentUser)", card_manager)

    def test_websocket_broadcast_keeps_admin_global_visibility(self):
        app_py = (ROOT / "app.py").read_text()

        self.assertIn("def _ws_client_can_receive", app_py)
        self.assertIn("_is_admin_user(client_user)", app_py)
        self.assertIn("ws_client_users[ws] = ws_user or {}", app_py)

        payload = {"type": "job_update", "job": {"id": "job-u1", "user_id": "u1"}}
        self.assertTrue(app._ws_client_can_receive({"sub": "admin", "role": "admin"}, payload))
        self.assertTrue(app._ws_client_can_receive({"sub": "u1", "role": "user"}, payload))
        self.assertFalse(app._ws_client_can_receive({"sub": "u2", "role": "user"}, payload))

    def test_history_renderer_keeps_active_jobs_before_history_cards(self):
        history = (ROOT / "static/js/modules/history.js").read_text()
        render_start = history.index("function _renderGalleryImpl")
        job_loop = history.index("for (const j of jobCards)", render_start)
        history_loop = history.index("for (let i = 0; i < visibleItems.length", render_start)

        self.assertLess(job_loop, history_loop)


if __name__ == "__main__":
    unittest.main()
