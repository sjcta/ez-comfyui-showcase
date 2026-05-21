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


if __name__ == "__main__":
    unittest.main()
