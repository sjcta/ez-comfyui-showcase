from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class JobPauseUiContractTests(unittest.TestCase):
    def test_job_cards_expose_pause_and_resume_controls(self):
        history_js = (ROOT / "static" / "js" / "modules" / "history.js").read_text("utf-8")
        app_js = (ROOT / "static" / "js" / "app.js").read_text("utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text("utf-8")
        sprite = (ROOT / "static" / "icons" / "sprite.svg").read_text("utf-8")

        self.assertIn("const canPauseJob = j.status === 'queued' || j.status === 'dispatching';", history_js)
        self.assertIn("CW.pauseJob", history_js)
        self.assertIn("CW.resumeJob", history_js)
        self.assertIn("job-status-text paused", history_js)
        self.assertIn("['queued', 'paused', 'preparing'", history_js)
        self.assertIn("function pauseJob", app_js)
        self.assertIn("function resumeJob", app_js)
        self.assertIn("/pause", app_js)
        self.assertIn("/resume", app_js)
        self.assertIn(".gi-pause", css)
        self.assertIn(".job-status-text.paused", css)
        self.assertIn('id="icon-pause"', sprite)


if __name__ == "__main__":
    unittest.main()
