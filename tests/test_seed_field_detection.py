import json
import tempfile
from pathlib import Path
import unittest

import app


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRS = [
    ROOT / "data" / "workflows",
    ROOT / "data" / "workflows" / "DGX Spark",
]


def _load_repo_workflow(name: str):
    for directory in WORKFLOW_DIRS:
        path = directory / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


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

    def test_random_generate_seed_overrides_flux2_noise_seed_field(self):
        workflow = {
            "25": {
                "class_type": "RandomNoise",
                "_meta": {"title": "RandomNoise"},
                "inputs": {"noise_seed": 2405220202},
            }
        }
        fields = app._normalize_workflow_field_values(
            workflow,
            {"25::noise_seed": 2405220202},
        )

        app._apply_generated_seed_to_seed_fields(workflow, fields, 123456789)

        self.assertEqual(fields["25::noise_seed"], 123456789)

    def test_random_generate_seed_covers_all_configured_seed_fields(self):
        generated_seed = 123456789012345
        failures = []
        for config_path in sorted((ROOT / "data" / "wf_configs").glob("*.json")):
            config = json.loads(config_path.read_text(encoding="utf-8"))
            workflow_name = config.get("workflow") or config_path.name
            workflow = _load_repo_workflow(workflow_name)
            if not workflow:
                continue
            fields = {}
            seed_fields = []
            for field_cfg in config.get("fields", []):
                if field_cfg.get("type") != "seed":
                    continue
                key = field_cfg.get("key", "")
                if "::" not in key:
                    continue
                nid, field = key.split("::", 1)
                node = workflow.get(nid, {})
                if not isinstance(node, dict):
                    continue
                fields[key] = (node.get("inputs") or {}).get(field)
                seed_fields.append((workflow_name, key, node, field))

            if not seed_fields:
                continue
            app._apply_generated_seed_to_seed_fields(workflow, fields, generated_seed)

            for workflow_name, key, node, field in seed_fields:
                expected = app._normalize_seed_value_for_field(
                    str(node.get("class_type") or ""),
                    field,
                    generated_seed,
                )
                if fields.get(key) != expected:
                    failures.append(f"{workflow_name} {key}: {fields.get(key)} != {expected}")

        self.assertEqual([], failures)

    def test_random_generate_seed_covers_all_workflow_seed_inputs(self):
        generated_seed = 987654321
        failures = []
        workflow_paths = sorted((ROOT / "data" / "workflows").glob("*.json"))
        workflow_paths += sorted((ROOT / "data" / "workflows" / "DGX Spark").glob("*.json"))
        for workflow_path in workflow_paths:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            fields = {}
            expected_fields = []
            for nid, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                inputs = node.get("inputs") or {}
                ct = str(node.get("class_type") or "")
                title = str((node.get("_meta") or {}).get("title") or "")
                for field, original_value in inputs.items():
                    if not app._looks_like_seed_field(ct, title, str(field)):
                        continue
                    key = f"{nid}::{field}"
                    fields[key] = original_value
                    expected_fields.append((workflow_path, key, node, field))
            if not expected_fields:
                continue

            app._apply_generated_seed_to_seed_fields(workflow, fields, generated_seed)

            for workflow_path, key, node, field in expected_fields:
                expected = app._normalize_seed_value_for_field(
                    str(node.get("class_type") or ""),
                    field,
                    generated_seed,
                )
                if fields.get(key) != expected:
                    failures.append(f"{workflow_path.name} {key}: {fields.get(key)} != {expected}")

        self.assertEqual([], failures)

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

    def test_ltx_director_empty_segment_prompt_defaults_to_transition(self):
        workflow = {
            "300": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": 12},
            },
            "301": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": 3},
            },
            "323": {
                "class_type": "ComfyMathExpression",
                "inputs": {"expression": "a * b + 1", "values.a": ["301", 0], "values.b": ["300", 0]},
            },
            "340": {
                "class_type": "LTXDirector",
                "inputs": {
                    "global_prompt": "A girl checks her phone at a bus stop.",
                    "duration_frames": ["323", 1],
                    "duration_seconds": ["301", 0],
                    "frame_rate": ["300", 0],
                    "timeline_data": json.dumps({
                        "segments": [
                            {"imageFile": "a.png", "start": 0, "length": 12, "prompt": ""},
                            {"imageFile": "b.png", "start": 12, "length": 12, "prompt": ""},
                        ],
                        "audioSegments": [],
                    }),
                    "local_prompts": "",
                    "segment_lengths": "",
                    "guide_strength": "",
                },
            },
        }

        fields = app._normalize_workflow_field_values(
            workflow,
            {"340::timeline_data": workflow["340"]["inputs"]["timeline_data"]},
        )

        timeline = json.loads(fields["340::timeline_data"])
        prompts = [seg["prompt"] for seg in timeline["segments"]]
        self.assertIn("next reference image", prompts[0])
        self.assertIn("final reference image", prompts[1])
        self.assertIn("A girl checks her phone", fields["340::local_prompts"])
        self.assertEqual(fields["340::segment_lengths"], "12,25")
        self.assertEqual(fields["340::guide_strength"], "0.9,0.9")


if __name__ == "__main__":
    unittest.main()
