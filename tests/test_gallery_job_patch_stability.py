from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GalleryJobPatchStabilityTests(unittest.TestCase):
    def test_same_status_job_cards_are_patched_in_place(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _patchStableJobCard(oldChild, newChild)", source)
        self.assertIn("_jobCardStatusClass(oldChild) !== _jobCardStatusClass(newChild)", source)
        self.assertIn("job.status === 'done' || job.status === 'error'", source)
        self.assertIn("_patchStableJobCard(oldChild, newChild) && !_patchHistoryCardIndex", source)

    def test_card_manager_delegates_patch_to_history_renderer(self):
        source = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertIn("CardManager.prototype.patchJobCard", source)
        self.assertIn("window.CW._patchJobCard(job)", source)
        self.assertNotIn("function _patchStableJobCard(oldChild, newChild)", source)


if __name__ == "__main__":
    unittest.main()
