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

    def test_scheduler_dimensions_follow_latent_size_before_submit(self):
        for scheduler_type in ("Flux2Scheduler", "Ideogram4Scheduler"):
            with self.subTest(scheduler_type=scheduler_type):
                workflow = {
                    "47": {
                        "class_type": "EmptyFlux2LatentImage",
                        "inputs": {"width": 1024, "height": 1024},
                    },
                    "48": {
                        "class_type": scheduler_type,
                        "inputs": {"steps": 8, "width": 1024, "height": 1024},
                    },
                }

                fields = app._normalize_workflow_field_values(
                    workflow,
                    {
                        "47::width": 1072,
                        "47::height": 1920,
                        "48::width": 1024,
                        "48::height": 1024,
                    },
                )

                self.assertEqual(fields["48::width"], 1072)
                self.assertEqual(fields["48::height"], 1920)

    def test_official_ideogram4_uses_app_standard_size_fields(self):
        workflow = _load_repo_workflow("t2i_ideogram4_official_nvfp4.json")
        config = json.loads((ROOT / "data" / "wf_configs" / "t2i_ideogram4_official_nvfp4.json").read_text(encoding="utf-8"))

        self.assertIsInstance(workflow["11"]["inputs"]["width"], int)
        self.assertIsInstance(workflow["11"]["inputs"]["height"], int)
        self.assertEqual(workflow["17"]["inputs"]["width"], workflow["11"]["inputs"]["width"])
        self.assertEqual(workflow["17"]["inputs"]["height"], workflow["11"]["inputs"]["height"])

        field_by_key = {field["key"]: field for field in config["fields"]}
        self.assertEqual(field_by_key["11::width"].get("role"), "width")
        self.assertEqual(field_by_key["11::height"].get("role"), "height")
        self.assertEqual(field_by_key["17::width"].get("zone"), "hidden")
        self.assertNotIn("37::aspect_ratio", field_by_key)
        self.assertNotIn("37::megapixels", field_by_key)

    def test_official_ideogram4_nvfp4_uses_full_nvfp4_stack(self):
        workflow = _load_repo_workflow("t2i_ideogram4_official_nvfp4.json")
        config = json.loads((ROOT / "data" / "wf_configs" / "t2i_ideogram4_official_nvfp4.json").read_text(encoding="utf-8"))

        self.assertIn("t2i_ideogram4_official_nvfp4.json", app.IDEOGRAM4_OFFICIAL_WORKFLOWS)
        self.assertEqual(workflow["14"]["inputs"]["clip_name"], "qwen3vl_8b_nvfp4.safetensors")
        self.assertEqual(workflow["23"]["inputs"]["unet_name"], "ideogram4_nvfp4_mixed.safetensors")
        self.assertEqual(workflow["154"]["inputs"]["unet_name"], "ideogram4_unconditional_nvfp4_mixed.safetensors")
        self.assertEqual(workflow["156"]["inputs"]["choice"], "Quality")
        self.assertEqual(
            config["required_models"],
            [
                "diffusion_models/ideogram4_nvfp4_mixed.safetensors",
                "diffusion_models/ideogram4_unconditional_nvfp4_mixed.safetensors",
                "text_encoders/qwen3vl_8b_nvfp4.safetensors",
                "vae/flux2-vae.safetensors",
            ],
        )

        field_by_key = {field["key"]: field for field in config["fields"]}
        self.assertEqual(field_by_key["24::text"].get("label"), "提示词 / 布局画布（Ideogram4 JSON）")
        self.assertEqual(field_by_key["11::width"].get("role"), "width")
        self.assertEqual(field_by_key["11::height"].get("role"), "height")
        self.assertEqual(field_by_key["17::width"].get("zone"), "hidden")
        self.assertEqual(field_by_key["17::height"].get("zone"), "hidden")

    def test_ideogram4_uncen_test_bypasses_unconditional_model(self):
        workflow = _load_repo_workflow("ideogram4_uncen_test.json")
        config = json.loads((ROOT / "data" / "wf_configs" / "ideogram4_uncen_test.json").read_text(encoding="utf-8"))

        self.assertIn("ideogram4_uncen_test.json", app.IDEOGRAM4_OFFICIAL_WORKFLOWS)
        self.assertEqual(workflow["14"]["inputs"]["clip_name"], "qwen3vl_8b_nvfp4.safetensors")
        self.assertEqual(workflow["23"]["inputs"]["unet_name"], "ideogram4_nvfp4_mixed.safetensors")
        self.assertNotIn("154", workflow)
        self.assertEqual(workflow["155"]["inputs"]["model_negative"], ["157", 0])
        self.assertEqual(workflow["156"]["inputs"]["choice"], "Quality")
        self.assertEqual(workflow["158"]["inputs"]["filename_prefix"], "Ideogram_4_Uncen_Test_NVFP4")
        self.assertEqual(
            config["required_models"],
            [
                "diffusion_models/ideogram4_nvfp4_mixed.safetensors",
                "text_encoders/qwen3vl_8b_nvfp4.safetensors",
                "vae/flux2-vae.safetensors",
            ],
        )

        field_by_key = {field["key"]: field for field in config["fields"]}
        self.assertEqual(field_by_key["24::text"].get("label"), "提示词 / 布局画布（Ideogram4 JSON）")
        self.assertEqual(field_by_key["11::width"].get("role"), "width")
        self.assertEqual(field_by_key["11::height"].get("role"), "height")
        self.assertEqual(field_by_key["17::width"].get("zone"), "hidden")
        self.assertEqual(field_by_key["17::height"].get("zone"), "hidden")

    def test_official_ideogram_canvas_caption_preserves_bbox_text_and_shape_as_spatial_descriptions(self):
        caption = app._official_ideogram4_caption_from_plain(
            json.dumps(
                {
                    "prompt": {
                        "high_level_description": "A clean poster layout with two precisely placed regions.",
                        "style_description": {
                            "aesthetics": "minimal editorial poster",
                            "lighting": "even studio lighting",
                            "medium": "graphic_design",
                            "art_style": "flat design with crisp typography",
                            "color_palette": ["#ffffff", "#0f172a", "#bad"],
                        },
                        "compositional_deconstruction": {
                            "background": "Deep navy background with generous whitespace.",
                            "elements": [
                                {
                                    "type": "obj",
                                    "shape": "circle",
                                    "bbox": [0.1, 0.2, 0.5, 0.7],
                                    "desc": "glowing amber product orb",
                                    "color_palette": ["#f59e0b"],
                                },
                                {
                                    "type": "text",
                                    "shape": "rect",
                                    "bbox": [620, 120, 760, 840],
                                    "text": "DESIGN LAB",
                                    "desc": "large headline text",
                                },
                            ],
                        },
                    }
                },
                ensure_ascii=False,
            )
        )

        payload = json.loads(caption)
        style = payload["style_description"]
        elements = payload["compositional_deconstruction"]["elements"]
        self.assertEqual(style["color_palette"], ["#FFFFFF", "#0F172A"])
        self.assertEqual(elements[0]["bbox"], [100, 200, 500, 700])
        self.assertIn("Positioned in the upper area", elements[0]["desc"])
        self.assertIn("soft clustered part of the same image", elements[0]["desc"])
        self.assertEqual(elements[0]["color_palette"], ["#F59E0B"])
        self.assertEqual(elements[1]["type"], "text")
        self.assertEqual(elements[1]["text"], "DESIGN LAB")
        self.assertEqual(elements[1]["bbox"], [620, 120, 760, 840])
        self.assertIn("Positioned in the lower area", elements[1]["desc"])
        self.assertIn("large headline text", elements[1]["desc"])
        self.assertNotIn("bounded region", json.dumps(payload))

    def test_official_ideogram_caption_preserves_optional_bbox_omission(self):
        caption = app._official_ideogram4_caption_from_plain(
            json.dumps(
                {
                    "high_level_description": "A single continuous realistic park photograph with natural placement language.",
                    "style_description": {
                        "aesthetics": "coherent realistic photography",
                        "lighting": "consistent daylight",
                        "photo": "wide angle lens, one camera view",
                        "medium": "photograph",
                    },
                    "compositional_deconstruction": {
                        "background": "One continuous city park with grass, skyline, and open sky.",
                        "elements": [
                            {
                                "type": "obj",
                                "desc": "One uninterrupted photographic scene with hot air balloons toward the right side of the open sky and people on the foreground lawn, not a grid.",
                            },
                            {
                                "type": "text",
                                "text": "热气时代",
                                "desc": "Render the literal text naturally toward the left side of the open sky as integrated environmental lettering.",
                            },
                        ],
                    },
                },
                ensure_ascii=False,
            )
        )

        payload = json.loads(caption)
        elements = payload["compositional_deconstruction"]["elements"]
        self.assertEqual([list(el.keys()) for el in elements], [["type", "desc"], ["type", "text", "desc"]])
        self.assertNotIn("bbox", elements[0])
        self.assertNotIn("bbox", elements[1])
        self.assertEqual(elements[1]["text"], "热气时代")

    def test_official_ideogram_canvas_submission_fuses_objects_and_positions_text(self):
        field_values = {
            "24::text": json.dumps(
                {
                    "high_level_description": "一个女学生半夜在繁华的街道上等待的照片",
                    "style_description": {
                        "aesthetics": "precise layout",
                        "lighting": "coherent studio-like lighting",
                        "medium": "graphic_design",
                        "art_style": "structured editorial composition",
                    },
                    "compositional_deconstruction": {
                        "background": "一个女学生半夜在繁华的街道上等待的照片",
                        "elements": [
                            {
                                "type": "obj",
                                "bbox": [329, 116, 975, 504],
                                "desc": "Rectangular bounded layout region: 穿着超短裙的亚洲女学生，在人行道上",
                            },
                            {
                                "type": "text",
                                "bbox": [495, 580, 735, 1000],
                                "text": "静静地\n我在等你",
                                "desc": "Rectangular bounded layout region: render the literal text clearly",
                            },
                        ],
                    },
                },
                ensure_ascii=False,
            ),
            "__user_prompt": "一个女学生半夜在繁华的街道上等待的照片",
            "__ideogram4_canvas": json.dumps(
                {
                    "mode": "canvas",
                    "shapes": [
                        {
                            "kind": "rect",
                            "elementType": "obj",
                            "x": 11.6,
                            "y": 32.8,
                            "w": 38.7,
                            "h": 64.6,
                            "text": "穿着超短裙的亚洲女学生，在人行道上",
                        },
                        {
                            "kind": "rect",
                            "elementType": "obj",
                            "x": 65,
                            "y": 3.7,
                            "w": 35,
                            "h": 61,
                            "text": "霓虹闪烁的商业大楼",
                        },
                        {
                            "kind": "rect",
                            "elementType": "text",
                            "x": 58,
                            "y": 49.5,
                            "w": 42,
                            "h": 24,
                            "text": "静静地\n我在等你",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
        }

        normalized = app._normalize_workflow_field_values(
            {},
            field_values,
            workflow_name="ideogram4_uncen_test.json",
        )
        payload = json.loads(normalized["24::text"])
        elements = payload["compositional_deconstruction"]["elements"]

        self.assertEqual([el["type"] for el in elements], ["obj", "obj", "text"])
        self.assertEqual(elements[0]["bbox"], [328, 116, 974, 503])
        self.assertIn("official Ideogram4 coordinate metadata", elements[0]["desc"])
        self.assertIn("22岁成年女大学生", elements[0]["desc"])
        self.assertIn("霓虹闪烁的商业大楼", elements[1]["desc"])
        self.assertEqual(elements[2]["bbox"], [495, 580, 735, 1000])
        self.assertEqual(elements[2]["text"], "静静地\n我在等你")
        self.assertIn("only the letter strokes should be visible", elements[2]["desc"])
        self.assertNotIn("Rectangular bounded layout region", json.dumps(payload, ensure_ascii=False))

    def test_official_ideogram_prompt_strips_style_block_and_wraps_json_caption(self):
        workflow = {
            "24": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
            }
        }
        fields = app._normalize_workflow_field_values(
            workflow,
            {
                "24::text": json.dumps(
                    {
                        "prompt": "橙色猫形机器人在雨夜霓虹街道中央撑透明雨伞",
                        "style": {
                            "preset_id": "premium_3d",
                            "label": "3D",
                            "general_style": "High-end 3D render aesthetic",
                        },
                    },
                    ensure_ascii=False,
                ),
                "__style_preset_id": "premium_3d",
                "__style_prompt_text": "make it a render",
            },
            "t2i_ideogram4_official_nvfp4.json",
        )

        prompt = json.loads(fields["24::text"])
        self.assertIn("3D", prompt["style_description"]["aesthetics"])
        self.assertIn("High-end 3D render aesthetic", prompt["style_description"]["aesthetics"])
        self.assertNotIn("preset_id", prompt["style_description"])
        self.assertNotIn("category", prompt["style_description"])
        self.assertIn("橙色猫形机器人", prompt["high_level_description"])
        self.assertNotIn("[Style Preset:", fields["24::text"])
        self.assertIn("__style_preset_id", fields)
        self.assertIn("__style_prompt_text", fields)

    def test_official_ideogram_fallback_preserves_prompt_content(self):
        caption = app._official_ideogram4_caption_from_plain("新世纪福音战士明日香的战斗画面")

        self.assertIn("新世纪福音战士", caption)
        self.assertIn("明日香", caption)
        self.assertIn("战斗", caption)

    def test_official_ideogram_merges_existing_json_prompt_with_style_json(self):
        workflow = {
            "24": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
            }
        }
        fields = app._normalize_workflow_field_values(
            workflow,
            {
                "24::text": json.dumps(
                    {
                        "prompt": {
                            "high_level_description": "雨夜机器人",
                            "style_description": {"aesthetics": "cinematic"},
                            "compositional_deconstruction": {
                                "background": "霓虹街道",
                                "elements": [{"type": "obj", "desc": "橙色机器人"}],
                            },
                        },
                        "style": {
                            "preset_id": "premium_3d",
                            "label": "3D",
                            "general_style": "PBR render",
                        },
                    },
                    ensure_ascii=False,
                )
            },
            "t2i_ideogram4_official_nvfp4.json",
        )

        prompt = json.loads(fields["24::text"])
        self.assertEqual(prompt["high_level_description"], "雨夜机器人")
        self.assertEqual(prompt["compositional_deconstruction"]["background"], "霓虹街道")
        self.assertIn("cinematic", prompt["style_description"]["aesthetics"])
        self.assertIn("PBR render", prompt["style_description"]["aesthetics"])
        self.assertNotIn("preset_id", prompt["style_description"])
        self.assertNotIn("category", prompt["style_description"])

    def test_official_ideogram_style_merge_deduplicates_existing_bits(self):
        caption = app._official_ideogram4_caption_from_plain(
            json.dumps(
                {
                    "prompt": {
                        "high_level_description": "雨夜机器人",
                        "style_description": {
                            "aesthetics": "clean high-quality image; 3D; PBR render"
                        },
                        "compositional_deconstruction": {
                            "background": "霓虹街道",
                            "elements": [{"type": "obj", "desc": "橙色机器人"}],
                        },
                    },
                    "style": {
                        "label": "3D",
                        "general_style": "PBR render",
                    },
                },
                ensure_ascii=False,
            )
        )

        aesthetics = json.loads(caption)["style_description"]["aesthetics"]
        self.assertEqual(aesthetics.count("3D"), 1)
        self.assertEqual(aesthetics.count("PBR render"), 1)

    def test_official_ideogram_maps_custom_chinese_json_without_negative_prompt(self):
        caption = app._official_ideogram4_caption_from_plain(
            json.dumps(
                {
                    "画面描述": {
                        "场景": {"地点": "海边石滩", "背景": "阴天海岸和远山"},
                        "人物": {"主体": "年轻女性外貌倾向，穿深藏蓝宽松卫衣"},
                        "服装妆容": {"腿部服饰": "黑色过膝丝袜"},
                        "颜色光影": {"光线": "阴天自然散射光"},
                    },
                    "正向提示词": "海边石滩上的写实手机环境人像，主体穿深藏蓝宽松卫衣，阴天自然散射光。",
                    "负面提示词": {
                        "人物错误": ["年龄幼化"],
                        "服装错误": ["裸腿", "内裤"],
                    },
                },
                ensure_ascii=False,
            )
        )

        prompt = json.loads(caption)
        self.assertEqual(
            prompt["high_level_description"],
            "海边石滩上的写实手机环境人像，主体穿深藏蓝宽松卫衣，阴天自然散射光。",
        )
        self.assertIn("海边石滩", prompt["compositional_deconstruction"]["background"])
        self.assertIn("深藏蓝宽松卫衣", prompt["compositional_deconstruction"]["elements"][0]["desc"])
        self.assertNotIn("负面提示词", caption)
        self.assertNotIn("年龄幼化", caption)
        self.assertNotIn("内裤", caption)
        self.assertNotIn('\\"画面描述\\"', caption)

    def test_official_ideogram_maps_custom_json_without_positive_key_to_summary(self):
        caption = app._official_ideogram4_caption_from_plain(
            json.dumps(
                {
                    "画面描述": {
                        "基本概述": {
                            "图片内容": "一幅竖版手绘插画，人物斜倚在黑色皮质沙发上",
                            "风格": "美式漫画速写风格",
                        },
                        "主体": {"主角": "长发女性，身穿红色连衣裙"},
                    },
                    "负面提示词": ["低清晰度", "畸形手"],
                },
                ensure_ascii=False,
            )
        )

        prompt = json.loads(caption)
        self.assertIn("竖版手绘插画", prompt["high_level_description"])
        self.assertIn("美式漫画速写风格", prompt["style_description"]["aesthetics"])
        self.assertIn("长发女性", prompt["compositional_deconstruction"]["elements"][0]["desc"])
        self.assertNotIn("负面提示词", caption)
        self.assertNotIn("畸形手", caption)
        self.assertNotIn('\\"画面描述\\"', caption)

    def test_official_ideogram_llm_restructures_custom_json_when_allowed(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append((messages, kwargs))
            return json.dumps(
                {
                    "high_level_description": "海边石滩上的年轻女性环境人像",
                    "style_description": {
                        "aesthetics": "realistic mobile portrait",
                        "lighting": "overcast soft daylight",
                        "medium": "photograph",
                        "color_palette": ["navy", "gray"],
                    },
                    "compositional_deconstruction": {
                        "background": "灰黑色石滩、岩壁、海面和阴云天空",
                        "elements": [
                            {
                                "type": "obj",
                                "bbox": [80, 120, 920, 880],
                                "desc": "穿深藏蓝卫衣的人物蹲坐在石滩上",
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )

        raw = json.dumps(
            {
                "prompt": {
                    "画面描述": {"场景": "海边石滩", "主体": "年轻女性环境人像"},
                    "正向提示词": "海边石滩上的年轻女性环境人像",
                    "负面提示词": {"质量错误": ["水印", "额外手指"]},
                },
                "style": {"label": "写实摄影"},
            },
            ensure_ascii=False,
        )

        caption = app._official_ideogram4_caption_from_plain(raw, allow_llm=True, chat_fn=fake_chat)
        payload = json.loads(caption)

        self.assertEqual(payload["high_level_description"], "海边石滩上的年轻女性环境人像")
        self.assertEqual(payload["compositional_deconstruction"]["background"], "灰黑色石滩、岩壁、海面和阴云天空")
        self.assertIn("写实摄影", payload["style_description"]["aesthetics"])
        self.assertNotIn("负面提示词", caption)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["response_format"], {"type": "json_object"})

    def test_official_ideogram_llm_failure_falls_back_without_negative_block(self):
        def failing_chat(messages, **kwargs):
            raise RuntimeError("LLM unavailable")

        raw = json.dumps(
            {
                "画面描述": {
                    "整体描述": "竖版手机环境人像",
                    "主体": "穿深藏蓝卫衣的人物蹲坐在海边石滩上",
                },
                "正向提示词": "海边石滩上的人物环境人像，阴天柔光",
                "负面提示词": {"质量错误": ["水印", "文字乱码"]},
            },
            ensure_ascii=False,
        )

        caption = app._official_ideogram4_caption_from_plain(raw, allow_llm=True, chat_fn=failing_chat)
        payload = json.loads(caption)

        self.assertIn("海边石滩", payload["high_level_description"])
        self.assertNotIn("负面提示词", caption)
        self.assertNotIn("水印", caption)

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

    def test_ltx_director_preserves_anchored_tail_segment_length(self):
        workflow = {
            "300": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": 24},
            },
            "301": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": 8},
            },
            "323": {
                "class_type": "ComfyMathExpression",
                "inputs": {"expression": "a * b + 1", "values.a": ["301", 0], "values.b": ["300", 0]},
            },
            "340": {
                "class_type": "LTXDirector",
                "inputs": {
                    "global_prompt": "A slow dolly shot through a neon street.",
                    "duration_frames": ["323", 1],
                    "duration_seconds": ["301", 0],
                    "frame_rate": ["300", 0],
                    "timeline_data": json.dumps({
                        "segments": [
                            {"imageFile": "", "start": 0, "length": 158, "prompt": "build up the shot"},
                            {"imageFile": "tail.png", "start": 158, "length": 35, "prompt": ""},
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
        self.assertEqual(timeline["segments"][1]["start"], 158)
        self.assertEqual(timeline["segments"][1]["length"], 35)
        self.assertEqual(fields["340::segment_lengths"], "158,35")
        self.assertIn("final reference image", timeline["segments"][1]["prompt"])


if __name__ == "__main__":
    unittest.main()
