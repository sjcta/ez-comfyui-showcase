import json
import os
import unittest

from modules.workflow_validation import describe_api_prompt_issues, validate_api_prompt


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class WorkflowValidationTest(unittest.TestCase):
    def _load_workflow(self, relpath):
        with open(os.path.join(ROOT, relpath)) as f:
            return json.load(f)

    def test_detects_ui_export_links_and_placeholders(self):
        workflow = {
            "1": {
                "class_type": "PreviewImage",
                "inputs": {
                    "images": [99, "images"],
                    "optional": [None, {"name": "optional"}],
                },
            },
        }

        issues = validate_api_prompt(workflow)
        message = describe_api_prompt_issues(issues)

        self.assertTrue(any(item.kind == "missing_node" for item in issues))
        self.assertTrue(any(item.kind == "placeholder" for item in issues))
        self.assertIn("工作流不是可提交的 ComfyUI API Prompt", message)

    def test_valid_api_prompt_passes(self):
        workflow = self._load_workflow("data/workflows/i2i-FireRed-Edit-8step.json")

        self.assertEqual(validate_api_prompt(workflow), [])


if __name__ == "__main__":
    unittest.main()
