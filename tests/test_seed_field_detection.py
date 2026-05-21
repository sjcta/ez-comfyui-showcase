import json
import tempfile
from pathlib import Path
import unittest

import app


class SeedFieldDetectionTests(unittest.TestCase):
    def test_primitive_value_with_global_seed_title_is_seed_field(self):
        workflow = {
            "1": {
                "class_type": "PrimitiveInt",
                "_meta": {"title": "value [global seed]"},
                "inputs": {"value": 123456},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")

            parsed = app.parse_workflow(str(path))

        self.assertEqual(len(parsed["fields"]), 1)
        field = parsed["fields"][0]
        self.assertEqual(field["class_type"], "PrimitiveInt")
        self.assertEqual(field["field"], "value")
        self.assertEqual(field["type"], "seed")
        self.assertEqual(field["label"], "value [global seed]")

    def test_workflow_analysis_marks_global_seed_value_as_advanced_seed(self):
        workflow = {
            "1": {
                "class_type": "PrimitiveInt",
                "_meta": {"title": "value [global seed]"},
                "inputs": {"value": 123456},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")

            analyzed = app.analyze_workflow(str(path))

        node = analyzed["nodes"][0]
        field = node["fields"][0]
        self.assertEqual(field["field"], "value")
        self.assertEqual(field["type"], "seed")
        self.assertEqual(field["label"], "value [global seed]")
        self.assertEqual(field["zone"], "advanced")
        self.assertTrue(field["visible"])

    def test_seedvr_seed_has_32_bit_limit_metadata(self):
        workflow = {
            "92": {
                "class_type": "SeedVR2VideoUpscaler",
                "_meta": {"title": "SeedVR2 Video Upscaler"},
                "inputs": {"seed": 2203285906, "resolution": 2048},
            }
        }
        config = {
            "fields": [
                {"key": "92::seed", "type": "seed", "label": "超分种子"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")

            parsed = app._parse_with_config(str(path), config)

        field = parsed["fields"][0]
        self.assertEqual(field["type"], "seed")
        self.assertEqual(field["max"], 4294967295)

    def test_seedvr_seed_value_is_normalized_before_submit(self):
        workflow = {
            "92": {
                "class_type": "SeedVR2VideoUpscaler",
                "inputs": {"seed": 1},
            }
        }
        fields = app._normalize_workflow_field_values(
            workflow,
            {"92::seed": 8103845055849200000},
        )

        self.assertGreaterEqual(fields["92::seed"], 0)
        self.assertLessEqual(fields["92::seed"], 4294967295)
        self.assertNotEqual(fields["92::seed"], 8103845055849200000)


if __name__ == "__main__":
    unittest.main()
