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

    def test_flux2_scheduler_dimensions_follow_latent_size_before_submit(self):
        workflow = {
            "47": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": 1024, "height": 1024},
            },
            "48": {
                "class_type": "Flux2Scheduler",
                "inputs": {"steps": 8, "width": 1024, "height": 1024},
            },
        }

        fields = app._normalize_workflow_field_values(
            workflow,
            {"47::width": 1072, "47::height": 1920},
        )

        self.assertEqual(fields["48::width"], 1072)
        self.assertEqual(fields["48::height"], 1920)

    def test_ltx_audio_fps_follows_visible_primitive_fps(self):
        workflow = {
            "4978": {
                "class_type": "PrimitiveFloat",
                "_meta": {"title": "fps"},
                "inputs": {"value": 24},
            },
            "4986": {
                "class_type": "PrimitiveInt",
                "_meta": {"title": "audio fps"},
                "inputs": {"value": 24},
            },
            "3980": {
                "class_type": "LTXVEmptyLatentAudio",
                "inputs": {"frame_rate": ["4986", 0], "frames_number": 121},
            },
            "1241": {
                "class_type": "LTXVConditioning",
                "inputs": {"frame_rate": ["4978", 0]},
            },
            "4819": {
                "class_type": "CreateVideo",
                "inputs": {"fps": ["4978", 0]},
            },
        }

        fields = app._normalize_workflow_field_values(
            workflow,
            {"4978::value": 12},
        )

        self.assertEqual(fields["4986::value"], 12)
        self.assertEqual(fields["3980::frame_rate"], ["4986", 0])
        self.assertEqual(fields["4819::fps"], 12)


if __name__ == "__main__":
    unittest.main()
