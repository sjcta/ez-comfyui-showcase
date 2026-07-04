import json
import pathlib
import tempfile
import unittest

import app


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data/workflows/DGX Spark"
CONFIG_DIR = ROOT / "data/wf_configs"
META = ROOT / "data/wf_meta.json"


class BooguWorkflowsTest(unittest.TestCase):
    def test_t2i_base_nvfp4_uses_comfy_org_stack(self):
        workflow = json.loads((WORKFLOW_DIR / "t2i_boogu_image_base_nvfp4.json").read_text())
        config = json.loads((CONFIG_DIR / "t2i_boogu_image_base_nvfp4.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["37"]["inputs"]["unet_name"], "boogu_image_base_nvfp4.safetensors")
        self.assertEqual(workflow["38"]["inputs"]["clip_name"], "qwen3vl_8b_fp8_scaled.safetensors")
        self.assertEqual(workflow["38"]["inputs"]["type"], "boogu")
        self.assertEqual(workflow["39"]["inputs"]["vae_name"], "flux1_vae_bf16.safetensors")
        self.assertEqual(workflow["58"]["class_type"], "EmptySD3LatentImage")
        self.assertEqual(workflow["66"]["class_type"], "ModelSamplingAuraFlow")
        self.assertEqual(workflow["66"]["inputs"]["shift"], 3.16)
        self.assertEqual(workflow["3"]["inputs"]["steps"], 40)
        self.assertEqual(workflow["3"]["inputs"]["cfg"], 4)
        self.assertEqual(fields["58::width"]["role"], "width")
        self.assertEqual(fields["58::height"]["role"], "height")
        self.assertEqual(fields["58::width"]["max"], 2048)
        self.assertEqual(
            config["required_models"],
            [
                "diffusion_models/boogu_image_base_nvfp4.safetensors",
                "text_encoders/qwen3vl_8b_fp8_scaled.safetensors",
                "vae/flux1_vae_bf16.safetensors",
            ],
        )

    def test_i2i_edit_nvfp4_uses_user_tested_sampler_stack(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_nvfp4.json").read_text())
        config = json.loads((CONFIG_DIR / "i2i_boogu_image_edit_nvfp4.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["2"]["inputs"]["unet_name"], "boogu_image_edit_nvfp4.safetensors")
        self.assertEqual(workflow["7"]["inputs"]["clip_name"], "qwen3vl_8b_fp8_scaled.safetensors")
        self.assertEqual(workflow["7"]["inputs"]["type"], "boogu")
        self.assertEqual(workflow["5"]["inputs"]["vae_name"], "flux1_vae_bf16.safetensors")
        self.assertEqual(workflow["8"]["class_type"], "EmptyLatentImage")
        self.assertEqual(workflow["8"]["inputs"]["width"], ["47", 0])
        self.assertEqual(workflow["8"]["inputs"]["height"], ["47", 1])
        self.assertEqual(workflow["21"]["class_type"], "SamplerCustom")
        self.assertEqual(workflow["21"]["inputs"]["noise_seed"], 0)
        self.assertEqual(workflow["21"]["inputs"]["cfg"], 3.5)
        self.assertEqual(workflow["21"]["inputs"]["model"], ["2", 0])
        self.assertEqual(workflow["22"]["class_type"], "KSamplerSelect")
        self.assertEqual(workflow["22"]["inputs"]["sampler_name"], "dpmpp_2m")
        self.assertEqual(workflow["26"]["class_type"], "BasicScheduler")
        self.assertEqual(workflow["26"]["inputs"]["scheduler"], "simple")
        self.assertEqual(workflow["26"]["inputs"]["steps"], 25)
        self.assertEqual(workflow["26"]["inputs"]["model"], ["33", 0])
        self.assertEqual(workflow["33"]["class_type"], "ModelSamplingAuraFlow")
        self.assertEqual(workflow["33"]["inputs"]["shift"], 3.16)
        self.assertEqual(workflow["36"]["class_type"], "TextEncodeBooguEdit")
        self.assertEqual(workflow["36"]["inputs"]["prompt"], ["46", 0])
        self.assertEqual(workflow["36"]["inputs"]["negative_prompt"], "")
        self.assertEqual(workflow["36"]["inputs"]["images.image_1"], ["32", 0])
        self.assertNotIn("images", workflow["36"]["inputs"])
        self.assertEqual(workflow["46"]["class_type"], "Text")
        self.assertEqual(workflow["47"]["class_type"], "GetImageSize")
        self.assertNotIn("112", workflow)
        self.assertNotIn("111", workflow)
        self.assertNotIn("58", workflow)
        self.assertNotIn("37", workflow)
        self.assertFalse(any(node.get("class_type") == "Get Image Size" for node in workflow.values()))
        self.assertFalse(any(node.get("class_type") == "JjkText" for node in workflow.values()))
        self.assertEqual(fields["32::image"]["type"], "image")
        self.assertEqual(fields["46::text"]["label"], "编辑提示词")
        self.assertEqual(fields["21::noise_seed"]["type"], "seed")
        self.assertEqual(fields["26::steps"]["value"], 25)
        self.assertEqual(fields["21::cfg"]["value"], 3.5)
        self.assertEqual(fields["36::negative_prompt"]["value"], "")
        self.assertNotIn("36::__boogu_enable_thinking", fields)
        self.assertNotIn("112::image_guidance_scale", fields)
        self.assertNotIn("8::width", fields)
        self.assertNotIn("8::height", fields)
        self.assertEqual(
            config["required_models"],
            [
                "diffusion_models/boogu_image_edit_nvfp4.safetensors",
                "text_encoders/qwen3vl_8b_fp8_scaled.safetensors",
                "vae/flux1_vae_bf16.safetensors",
            ],
        )

    def test_i2i_edit_fp8_scaled_uses_user_tested_sampler_stack(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_fp8_scaled.json").read_text())
        config = json.loads((CONFIG_DIR / "i2i_boogu_image_edit_fp8_scaled.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["2"]["inputs"]["unet_name"], "boogu_image_edit_fp8_scaled.safetensors")
        self.assertEqual(workflow["7"]["inputs"]["clip_name"], "qwen3vl_8b_fp8_scaled.safetensors")
        self.assertEqual(workflow["7"]["inputs"]["type"], "boogu")
        self.assertEqual(workflow["5"]["inputs"]["vae_name"], "flux1_vae_bf16.safetensors")
        self.assertEqual(workflow["8"]["class_type"], "EmptyLatentImage")
        self.assertEqual(workflow["8"]["inputs"]["width"], ["47", 0])
        self.assertEqual(workflow["8"]["inputs"]["height"], ["47", 1])
        self.assertEqual(workflow["21"]["inputs"]["noise_seed"], 0)
        self.assertEqual(workflow["21"]["class_type"], "SamplerCustom")
        self.assertEqual(workflow["21"]["inputs"]["cfg"], 3.5)
        self.assertEqual(workflow["21"]["inputs"]["model"], ["2", 0])
        self.assertEqual(workflow["22"]["class_type"], "KSamplerSelect")
        self.assertEqual(workflow["22"]["inputs"]["sampler_name"], "dpmpp_2m")
        self.assertEqual(workflow["26"]["class_type"], "BasicScheduler")
        self.assertEqual(workflow["26"]["inputs"]["scheduler"], "simple")
        self.assertEqual(workflow["26"]["inputs"]["steps"], 25)
        self.assertEqual(workflow["26"]["inputs"]["model"], ["33", 0])
        self.assertEqual(workflow["33"]["class_type"], "ModelSamplingAuraFlow")
        self.assertEqual(workflow["33"]["inputs"]["shift"], 3.16)
        self.assertNotIn("45", workflow)
        self.assertEqual(workflow["46"]["class_type"], "Text")
        self.assertEqual(workflow["47"]["class_type"], "GetImageSize")
        self.assertEqual(workflow["36"]["class_type"], "TextEncodeBooguEdit")
        self.assertEqual(workflow["36"]["inputs"]["prompt"], ["46", 0])
        self.assertEqual(workflow["36"]["inputs"]["negative_prompt"], "")
        self.assertEqual(workflow["36"]["inputs"]["images.image_1"], ["32", 0])
        self.assertNotIn("images", workflow["36"]["inputs"])
        self.assertEqual(workflow["44"]["class_type"], "SaveImage")
        self.assertNotIn("50", workflow)
        self.assertFalse(any(node.get("class_type") == "Get Image Size" for node in workflow.values()))
        self.assertFalse(any(node.get("class_type") == "JjkText" for node in workflow.values()))
        self.assertFalse(any(node.get("class_type") == "DF_Get_image_size" for node in workflow.values()))
        self.assertFalse(any(node.get("class_type") == "Image Comparer (rgthree)" for node in workflow.values()))
        self.assertEqual(fields["32::image"]["type"], "image")
        self.assertEqual(fields["46::text"]["label"], "编辑提示词")
        self.assertEqual(fields["21::noise_seed"]["type"], "seed")
        self.assertNotIn("36::__boogu_enable_thinking", fields)
        self.assertNotIn("45::image_guidance_scale", fields)
        self.assertNotIn("112::image_guidance_scale", fields)
        self.assertEqual(fields["26::steps"]["value"], 25)
        self.assertEqual(fields["21::cfg"]["value"], 3.5)
        self.assertEqual(fields["36::negative_prompt"]["value"], "")
        self.assertNotIn("36::images", fields)
        self.assertIn("44::filename_prefix", fields)
        self.assertNotIn("8::width", fields)
        self.assertNotIn("8::height", fields)
        self.assertEqual(
            config["required_models"],
            [
                "diffusion_models/boogu_image_edit_fp8_scaled.safetensors",
                "text_encoders/qwen3vl_8b_fp8_scaled.safetensors",
                "vae/flux1_vae_bf16.safetensors",
            ],
        )

    def test_i2i_edit_auto_uses_reference_aspect_at_max_size(self):
        try:
            from PIL import Image
        except Exception as exc:
            self.skipTest(f"Pillow unavailable: {exc}")

        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_nvfp4.json").read_text())
        old_input = app.COMFYUI_INPUT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.COMFYUI_INPUT = tmp
                image_path = pathlib.Path(tmp) / "u1" / "portrait.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1200, 1800), "white").save(image_path)
                fields = {
                    "32::image": "u1/portrait.png",
                    "8::width": 1024,
                    "8::height": 1024,
                }

                size = app._sync_i2i_reference_dimensions(
                    "i2i_boogu_image_edit_nvfp4.json",
                    workflow,
                    fields,
                )
            finally:
                app.COMFYUI_INPUT = old_input

        self.assertEqual(size, (1200, 1800))
        self.assertNotIn("8::width", fields)
        self.assertNotIn("8::height", fields)
        self.assertEqual(fields["__boogu_i2i_source_size"], "1200x1800")
        self.assertEqual(fields["__boogu_i2i_auto_size"], "1200x1800")

    def test_i2i_edit_fp8_scaled_preserves_get_image_size_links(self):
        try:
            from PIL import Image
        except Exception as exc:
            self.skipTest(f"Pillow unavailable: {exc}")

        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_fp8_scaled.json").read_text())
        old_input = app.COMFYUI_INPUT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.COMFYUI_INPUT = tmp
                image_path = pathlib.Path(tmp) / "u1" / "portrait.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1200, 1800), "white").save(image_path)
                fields = {
                    "32::image": "u1/portrait.png",
                    "8::width": 1024,
                    "8::height": 1024,
                }

                size = app._sync_i2i_reference_dimensions(
                    "i2i_boogu_image_edit_fp8_scaled.json",
                    workflow,
                    fields,
                )
                tall_path = pathlib.Path(tmp) / "u1" / "tall.png"
                Image.new("RGB", (1536, 2720), "white").save(tall_path)
                tall_fields = {
                    "32::image": "u1/tall.png",
                    "8::width": 1024,
                    "8::height": 1024,
                }
                tall_size = app._sync_i2i_reference_dimensions(
                    "i2i_boogu_image_edit_fp8_scaled.json",
                    workflow,
                    tall_fields,
                )
            finally:
                app.COMFYUI_INPUT = old_input

        self.assertEqual(size, (1200, 1800))
        self.assertNotIn("8::width", fields)
        self.assertNotIn("8::height", fields)
        self.assertEqual(fields["__boogu_i2i_source_size"], "1200x1800")
        self.assertEqual(fields["__boogu_i2i_auto_size"], "1200x1800")
        self.assertEqual(tall_size, (1536, 2720))
        self.assertNotIn("8::width", tall_fields)
        self.assertNotIn("8::height", tall_fields)
        self.assertEqual(tall_fields["__boogu_i2i_source_size"], "1536x2720")
        self.assertEqual(tall_fields["__boogu_i2i_auto_size"], "1536x2720")

    def test_i2i_edit_prompt_defaults_to_user_instruction(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_nvfp4.json").read_text())
        fields = {"46::text": "修改上衣为白色小吊带"}

        normalized = app._normalize_workflow_field_values(
            workflow,
            fields,
            "i2i_boogu_image_edit_nvfp4.json",
        )

        self.assertEqual(normalized["__user_prompt"], "修改上衣为白色小吊带")
        self.assertEqual(normalized["46::text"], "修改上衣为白色小吊带")
        self.assertNotIn("36::prompt", normalized)
        self.assertEqual(normalized["__boogu_instruction_used"], "修改上衣为白色小吊带")

    def test_i2i_edit_fp8_scaled_prompt_uses_linked_text_node(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_fp8_scaled.json").read_text())
        fields = {"46::text": "修改上衣为白色小吊带"}

        normalized = app._normalize_workflow_field_values(
            workflow,
            fields,
            "i2i_boogu_image_edit_fp8_scaled.json",
        )

        self.assertEqual(normalized["__user_prompt"], "修改上衣为白色小吊带")
        self.assertEqual(normalized["46::text"], "修改上衣为白色小吊带")
        self.assertNotIn("36::prompt", normalized)
        self.assertEqual(normalized["__boogu_instruction_used"], "修改上衣为白色小吊带")

    def test_i2i_edit_enable_thinking_uses_instruction_rewrite(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_boogu_image_edit_nvfp4.json").read_text())
        fields = {
            "46::text": "修改上衣为白色小吊带",
            "36::__boogu_enable_thinking": True,
        }
        old_rewrite = app._llm_boogu_i2i_instruction_rewrite
        try:
            app._llm_boogu_i2i_instruction_rewrite = lambda prompt: f"重写：{prompt}"
            normalized = app._normalize_workflow_field_values(
                workflow,
                fields,
                "i2i_boogu_image_edit_nvfp4.json",
                allow_llm=True,
            )
        finally:
            app._llm_boogu_i2i_instruction_rewrite = old_rewrite

        self.assertEqual(normalized["__user_prompt"], "修改上衣为白色小吊带")
        self.assertEqual(normalized["46::text"], "重写：修改上衣为白色小吊带")
        self.assertEqual(normalized["__boogu_instruction_used"], "重写：修改上衣为白色小吊带")

    def test_t2i_turbo_nvfp4_uses_fast_boogu_defaults(self):
        workflow = json.loads((WORKFLOW_DIR / "t2i_boogu_image_turbo_nvfp4.json").read_text())
        config = json.loads((CONFIG_DIR / "t2i_boogu_image_turbo_nvfp4.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["37"]["inputs"]["unet_name"], "boogu_image_turbo_nvfp4.safetensors")
        self.assertEqual(workflow["38"]["inputs"]["clip_name"], "qwen3vl_8b_fp8_scaled.safetensors")
        self.assertEqual(workflow["38"]["inputs"]["type"], "boogu")
        self.assertEqual(workflow["39"]["inputs"]["vae_name"], "flux1_vae_bf16.safetensors")
        self.assertEqual(workflow["66"]["class_type"], "ModelSamplingAuraFlow")
        self.assertEqual(workflow["66"]["inputs"]["shift"], 3.16)
        self.assertEqual(workflow["3"]["inputs"]["steps"], 4)
        self.assertEqual(workflow["3"]["inputs"]["cfg"], 1)
        self.assertEqual(workflow["7"]["inputs"]["text"], "")
        self.assertEqual(fields["3::steps"]["max"], 8)
        self.assertEqual(fields["3::cfg"]["max"], 4)
        self.assertEqual(fields["7::text"]["value"], "")
        self.assertEqual(
            config["required_models"],
            [
                "diffusion_models/boogu_image_turbo_nvfp4.safetensors",
                "text_encoders/qwen3vl_8b_fp8_scaled.safetensors",
                "vae/flux1_vae_bf16.safetensors",
            ],
        )

    def test_boogu_workflows_are_registered_with_expected_metadata(self):
        meta = json.loads(META.read_text())
        t2i = meta["t2i_boogu_image_base_nvfp4.json"]
        i2i = meta["i2i_boogu_image_edit_nvfp4.json"]
        i2i_fp8 = meta["i2i_boogu_image_edit_fp8_scaled.json"]
        turbo = meta["t2i_boogu_image_turbo_nvfp4.json"]

        self.assertEqual(t2i["name"], "[测试] Boogu-Image Base NVFP4 文生图")
        self.assertEqual(i2i["name"], "[测试] Boogu-Image Edit NVFP4 图生图")
        self.assertEqual(i2i_fp8["name"], "[测试] Boogu-Image Edit FP8 Scaled 图生图")
        self.assertEqual(turbo["name"], "Boogu-Image Turbo 快速")
        self.assertIn("NVFP4", t2i["tags"])
        self.assertIn("NVFP4", i2i["tags"])
        self.assertIn("FP8", i2i_fp8["tags"])
        self.assertIn("Native", i2i["tags"])
        self.assertIn("Boogu", turbo["tags"])
        self.assertFalse(t2i["shared"])
        self.assertFalse(i2i["shared"])
        self.assertFalse(i2i_fp8["shared"])
        self.assertTrue(turbo["shared"])
        self.assertEqual(t2i["source"], "Comfy-Org Boogu-Image repackaged model files")
        self.assertIn("User-tested", i2i["source"])
        self.assertIn("User-tested", i2i_fp8["source"])
        self.assertIn("Comfy-Org Boogu-Image", turbo["source"])


if __name__ == "__main__":
    unittest.main()
