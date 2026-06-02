from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class JobCompleteAnimationContractTests(unittest.TestCase):
    def test_completion_uses_blur_fade_transition_in_history_renderer(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertIn("job-card-complete-blurfade", history_js)
        self.assertIn("job-card-complete-transition", history_js)
        self.assertIn("job-card-complete-old", history_js)
        self.assertIn("job-card-complete-new", history_js)
        self.assertNotIn("job-card-complete-flip", history_js)
        self.assertNotIn("job-card-flip-scene", history_js)
        self.assertNotIn("flip-complete", history_js)
        self.assertNotIn("job-complete-wash", history_js)
        self.assertIn("window.CW._onJobDone(job)", card_manager_js)
        self.assertNotIn("job-card-complete-transition", card_manager_js)

    def test_completion_css_defines_blur_fade_without_flip_wash(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".gi.job-card.job-card-complete-blurfade", css)
        self.assertIn(".job-card-complete-transition", css)
        self.assertIn(".job-card-complete-old", css)
        self.assertIn(".job-card-complete-new", css)
        self.assertIn("@keyframes jobCompleteOldBlurFade", css)
        self.assertIn("@keyframes jobCompleteNewReveal", css)
        self.assertNotIn("jobCompleteFlipY", css)
        self.assertNotIn("jobCompleteWash", css)
        self.assertNotIn(".job-complete-wash", css)


if __name__ == "__main__":
    unittest.main()
