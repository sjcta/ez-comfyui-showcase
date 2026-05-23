from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GalleryJobPatchStabilityTests(unittest.TestCase):
    def test_same_status_job_cards_are_patched_in_place(self):
        for rel in ("static/js/modules/history.js", "static/js/modules/card_manager.js"):
            source = (ROOT / rel).read_text()

            self.assertIn("function _patchStableJobCard(oldChild, newChild)", source, rel)
            self.assertIn("_jobCardStatusClass(oldChild) !== _jobCardStatusClass(newChild)", source, rel)
            self.assertIn("job.status === 'done' || job.status === 'error'", source, rel)
            self.assertIn("_patchStableJobCard(oldChild, newChild) && !_patchHistoryCardIndex", source, rel)


if __name__ == "__main__":
    unittest.main()
