import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class JobTimerEstimateUiTest(unittest.TestCase):
    def test_attribute_escape_handles_non_string_values(self):
        source = (ROOT / "static/js/app.js").read_text()

        self.assertIn("function escA(s)", source)
        self.assertIn("String(s == null ? '' : s).replace", source)

    def test_timer_renders_estimated_duration_label(self):
        for rel in ("static/js/modules/history.js", "static/js/modules/card_manager.js"):
            source = (ROOT / rel).read_text()
            self.assertIn("formatJobElapsedWithEstimate", source)
            self.assertIn("estimated_duration_label", source)
            self.assertIn("generating_at", source)
            self.assertIn("data-estimate-label", source)

    def test_poll_timer_preserves_estimated_duration_label(self):
        source = (ROOT / "static/js/modules/poll_manager.js").read_text()
        self.assertIn("formatJobElapsedWithEstimate", source)
        self.assertIn("estimateLabel", source)

    def test_queued_jobs_do_not_render_running_timer(self):
        for rel in ("static/js/modules/history.js", "static/js/modules/card_manager.js"):
            source = (ROOT / rel).read_text()
            match = re.search(r"function _jobShowsTimer\(j\) \{(?P<body>.*?)\n  \}", source, re.S)
            self.assertIsNotNone(match, rel)
            body = match.group("body")
            self.assertNotIn("status === 'queued'", body, rel)
            self.assertNotIn('status === "queued"', body, rel)
            self.assertNotIn("status === 'preparing'", body, rel)
            self.assertNotIn("status === 'starting_comfyui'", body, rel)
            self.assertNotIn("status === 'submitting'", body, rel)
            self.assertIn("status === 'generating'", body, rel)

    def test_timer_uses_generation_start_only(self):
        for rel in ("static/js/modules/history.js", "static/js/modules/card_manager.js"):
            source = (ROOT / rel).read_text()
            match = re.search(r"function _jobTimerTs\(j\) \{(?P<body>.*?)\n  \}", source, re.S)
            self.assertIsNotNone(match, rel)
            body = match.group("body")
            self.assertIn("generating_at", body, rel)
            self.assertNotIn("submitted_at", body, rel)
            self.assertNotIn("created_at_ts", body, rel)

    def test_poll_timer_skips_queued_cards(self):
        source = (ROOT / "static/js/modules/poll_manager.js").read_text()
        self.assertIn("closest('.job-card.queued')", source)


if __name__ == "__main__":
    unittest.main()
