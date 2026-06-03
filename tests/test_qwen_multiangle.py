from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _node_reaches_save_image(workflow, start_node_id):
    consumers = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, list) and value:
                consumers.setdefault(str(value[0]), set()).add(str(node_id))

    seen = {str(start_node_id)}
    queue = [str(start_node_id)]
    while queue:
        node_id = queue.pop(0)
        node = workflow.get(node_id)
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            return True
        for next_node in consumers.get(node_id, ()):
            if next_node in seen:
                continue
            seen.add(next_node)
            queue.append(next_node)
    return False


RAPID_V23_PARAMS = {
    "steps": 4,
    "cfg": 1,
    "sampler_name": "euler_ancestral",
    "scheduler": "beta",
    "denoise": 1,
}


class QwenMultiangleWorkflowTests(unittest.TestCase):
    def test_qwen_i2i_workflows_include_multiangle_node(self):
        workflow_files = [
            "data/workflows/i2i-Qwen-Edit-v2511.json",
            "data/workflows/DGX Spark/i2i-Qwen-Edit-v2511.json",
            "data/workflows/i2i-Qwen-Rapid-seedVR2-4k.json",
            "data/workflows/DGX Spark/i2i-Qwen-Rapid-seedVR2-4k.json",
            "data/workflows/i2i-Qwen-SeedVR2.json",
            "data/workflows/DGX Spark/i2i-Qwen-SeedVR2.json",
            "data/workflows/DGX Spark/i2i-Qwen-Rapid.json",
            "data/workflows/DGX Spark/i2i-Qwen-Rapid-Q2.json",
        ]
        for rel in workflow_files:
            with self.subTest(workflow=rel):
                wf = json.loads((ROOT / rel).read_text())
                node = wf.get("910")
                self.assertIsNotNone(node)
                self.assertEqual(node["class_type"], "QwenMultiangleCameraNode")
                self.assertIn("horizontal_angle", node["inputs"])
                self.assertIn("vertical_angle", node["inputs"])
                self.assertIn("zoom", node["inputs"])
                self.assertIsInstance(node["inputs"].get("image"), list)

    def test_qwen_rapid_adjustable_fields_are_valid_for_output_graph(self):
        workflow_pairs = [
            (
                "data/workflows/DGX Spark/i2i-Qwen-Rapid.json",
                "data/wf_configs/i2i-Qwen-Rapid.json",
            ),
            (
                "data/workflows/DGX Spark/i2i-Qwen-Rapid-Q2.json",
                "data/wf_configs/i2i-Qwen-Rapid-Q2.json",
            ),
        ]
        for wf_rel, cfg_rel in workflow_pairs:
            with self.subTest(workflow=wf_rel):
                wf = json.loads((ROOT / wf_rel).read_text())
                cfg = json.loads((ROOT / cfg_rel).read_text())

                self.assertEqual(wf["115:111"]["inputs"]["image1"], ["78", 0])
                self.assertEqual(wf["88"]["inputs"]["image"], ["78", 0])

                for node in wf.values():
                    if not isinstance(node, dict):
                        continue
                    for input_name, value in (node.get("inputs") or {}).items():
                        if input_name in ("image", "image1", "pixels"):
                            self.assertNotEqual(value, ["910", 0])

                for field in cfg["fields"]:
                    if field.get("zone") not in ("user_input", "advanced"):
                        continue
                    node_id, field_name = field["key"].split("::", 1)
                    node = wf.get(node_id)
                    self.assertIsNotNone(node, field["key"])
                    self.assertIn(field_name, node.get("inputs", {}), field["key"])
                    if node_id != "910":
                        self.assertTrue(_node_reaches_save_image(wf, node_id), field["key"])

    def test_qwen_rapid_workflows_use_v23_model_and_recommended_sampler(self):
        workflow_specs = [
            (
                "data/workflows/DGX Spark/i2i-Qwen-Rapid.json",
                "UNETLoader",
                "Qwen-Rapid-AIO-NSFW-v23.safetensors",
            ),
            (
                "data/workflows/i2i-Qwen-Rapid-seedVR2-4k.json",
                "UNETLoader",
                "Qwen-Rapid-AIO-NSFW-v23.safetensors",
            ),
            (
                "data/workflows/DGX Spark/i2i-Qwen-Rapid-seedVR2-4k.json",
                "UNETLoader",
                "Qwen-Rapid-AIO-NSFW-v23.safetensors",
            ),
            (
                "data/workflows/DGX Spark/i2i-Qwen-Rapid-Q2.json",
                "UnetLoaderGGUF",
                "gguf/Qwen-Rapid-NSFW-v23_Q2_K.gguf",
            ),
        ]
        for wf_rel, loader_class, model_name in workflow_specs:
            with self.subTest(workflow=wf_rel):
                wf = json.loads((ROOT / wf_rel).read_text())

                self.assertEqual(wf["89"]["class_type"], loader_class)
                self.assertEqual(wf["89"]["inputs"]["unet_name"], model_name)
                if loader_class == "UNETLoader":
                    self.assertEqual(wf["89"]["inputs"]["weight_dtype"], "default")

                sampler_inputs = wf["115:3"]["inputs"]
                for key, expected in RAPID_V23_PARAMS.items():
                    self.assertEqual(sampler_inputs[key], expected, key)

                self.assertEqual(wf["88"]["inputs"]["image"], ["78", 0])
                self.assertEqual(wf["115:111"]["inputs"]["image1"], ["78", 0])
                for node in wf.values():
                    if not isinstance(node, dict):
                        continue
                    for input_name, value in (node.get("inputs") or {}).items():
                        if input_name in ("image", "image1", "pixels"):
                            self.assertNotEqual(value, ["910", 0])

    def test_qwen_multiangle_fields_are_user_input_when_enabled(self):
        config_files = [
            "i2i-Qwen-Edit-v2511.json",
            "i2i_Qwen_Edit.json",
            "i2i-Qwen-Rapid-seedVR2-4k.json",
            "i2i-Qwen-SeedVR2.json",
            "i2i-Qwen-Rapid.json",
            "i2i-Qwen-Rapid-Q2.json",
        ]
        for filename in config_files:
            with self.subTest(config=filename):
                cfg = json.loads((ROOT / "data/wf_configs" / filename).read_text())
                by_key = {item["key"]: item for item in cfg["fields"]}
                for key in ("910::horizontal_angle", "910::vertical_angle", "910::zoom"):
                    self.assertEqual(by_key[key]["zone"], "user_input")
                    self.assertTrue(by_key[key]["visible"])
                self.assertEqual(by_key["910::camera_view"]["zone"], "hidden")

    def test_qwen_rapid_high_quality_hides_seedvr2_internal_batch_size(self):
        cfg = json.loads((ROOT / "data/wf_configs/i2i-Qwen-Rapid-seedVR2-4k.json").read_text())
        by_key = {item["key"]: item for item in cfg["fields"]}

        field = by_key["92::batch_size"]
        self.assertEqual(field["zone"], "hidden")
        self.assertFalse(field["visible"])
        self.assertEqual(field["label"], "SeedVR2 内部批量")

    def test_quick_form_renders_3d_angle_control_and_appends_prompt(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()
        app_py = (ROOT / "app.py").read_text()

        self.assertIn("QwenMultiangleCameraNode", app_py)
        self.assertIn("function _qwenAngleControlHtml", generate_js)
        self.assertIn("qwen-angle-stage", generate_js)
        self.assertIn("data-angle-plane", generate_js)
        self.assertIn("data-angle-reset", generate_js)
        self.assertIn("data-angle-enable", generate_js)
        self.assertIn("data-angle-collapse", generate_js)
        self.assertIn("data-angle-enabled=\"0\"", generate_js)
        self.assertIn("data-angle-mode=\"camera\"", generate_js)
        self.assertIn("只控制主体", generate_js)
        self.assertIn("控制相机", generate_js)
        self.assertIn("data-angle-slider=\"zoom\"", generate_js)
        self.assertIn("data-angle-slider=\"roll\"", generate_js)
        self.assertIn("Z/Roll 图片旋转", generate_js)
        self.assertIn("aria-label=\"图片旋转角度\"", generate_js)
        self.assertIn("qwen-angle-slider-ticks", generate_js)
        self.assertIn("qwen-angle-camera-frame", generate_js)
        self.assertIn("var sliderValue = slider.value", generate_js)
        self.assertIn("_setQwenAngleValue(root, 'zoom', sliderValue)", generate_js)
        self.assertIn("qwenZoomTicks", generate_js)
        self.assertIn("qwenRollTicks", generate_js)
        self.assertIn("min=\"-45\" max=\"45\"", generate_js)
        self.assertNotIn("右上45", generate_js)
        self.assertNotIn("左上45", generate_js)
        self.assertNotIn('data-angle-preset="h:45,v:30,z:5"', generate_js)
        self.assertNotIn('data-angle-preset="h:315,v:30,z:5"', generate_js)
        self.assertNotIn("data-angle-step=\"zoom", generate_js)
        self.assertNotIn("data-angle-step=\"roll", generate_js)
        self.assertIn("qwen-angle-camera-ray", generate_js)
        self.assertIn("__qwen_frame_roll", generate_js)
        self.assertNotIn("fields.__qwen_frame_roll", generate_js)
        self.assertNotIn("Z-axis roll", generate_js)
        self.assertIn("function _qwenNativeHorizontalText", generate_js)
        self.assertIn("function _qwenNativeVerticalText", generate_js)
        self.assertIn("function _qwenNativeDistanceText", generate_js)
        self.assertIn("front-right quarter view", generate_js)
        self.assertIn("right side view", generate_js)
        self.assertIn("back-left quarter view", generate_js)
        self.assertIn("eye-level shot", generate_js)
        self.assertIn("elevated shot", generate_js)
        self.assertIn("medium shot", generate_js)
        self.assertIn("function _qwenRollCompositionText", generate_js)
        self.assertIn("return '调整画面构图，用' + direction + '约' + degrees + '度 对角线构图'", generate_js)
        self.assertNotIn("采用对角线构图", generate_js)
        self.assertIn("var rollDirectionZh = r > 0 ? '顺时针' : '逆时针'", generate_js)
        self.assertNotIn("轻微画面倾斜构图", generate_js)
        self.assertNotIn("让最终画面水平线", generate_js)
        self.assertNotIn("最终构图倾斜角必须接近", generate_js)
        self.assertNotIn("构图倾斜角控制在", generate_js)
        self.assertNotIn("这是小角度画面roll", generate_js)
        self.assertNotIn("对角线构图角度必须约等于", generate_js)
        self.assertNotIn("只控制主体姿态，让主体整体姿态", generate_js)
        self.assertNotIn("这里描述的是最终画面构图方向", generate_js)
        self.assertNotIn("保持原始画布方向和画面比例不变", generate_js)
        self.assertNotIn("画布方向保持原始横竖版", generate_js)
        self.assertNotIn("主体头部和身体姿态保持自然", generate_js)
        self.assertNotIn("整张画布方向保持不变", generate_js)
        self.assertNotIn("场景透视保持不变", generate_js)
        self.assertNotIn("保持主体一致性", generate_js)
        self.assertNotIn("调整镜头位置到", generate_js)
        self.assertNotIn("将主体调整为", generate_js)
        self.assertNotIn("camera XY offset yaw", generate_js)
        self.assertNotIn("C-axis depth", generate_js)
        self.assertNotIn("control target: ", generate_js)
        self.assertNotIn("不要", generate_js)
        self.assertNotIn("不是", generate_js)
        self.assertNotIn("Dutch angle camera roll", generate_js)
        self.assertNotIn("do not rotate the entire image or canvas", generate_js)
        self.assertNotIn("do not swap portrait and landscape orientation", generate_js)
        self.assertNotIn("do not tilt only", generate_js)
        self.assertNotIn("rotate the entire composition and horizon line", generate_js)
        self.assertNotIn("pre-expanded non-mirrored", generate_js)
        self.assertIn("rollDirectionZh", generate_js)
        self.assertNotIn("wide-angle close camera perspective", generate_js)
        self.assertNotIn("telephoto compression", generate_js)
        self.assertIn("function _resetQwenAngleControl", generate_js)
        self.assertIn("function _setQwenAngleEnabled", generate_js)
        self.assertIn("function _setQwenAngleCollapsed", generate_js)
        self.assertIn("function _qwenAngleMode", generate_js)
        self.assertIn("function _setQwenAngleMode", generate_js)
        self.assertIn("__qwen_angle_mode", generate_js)
        self.assertIn("function _isQwenAngleNeutral", generate_js)
        self.assertIn("function _isQwenAngleControlActive", generate_js)
        self.assertIn("function _isCurrentQwenAngleActive", generate_js)
        self.assertIn("function _qwenPitchToMarkerY", generate_js)
        self.assertIn("function _qwenMarkerYToPitch", generate_js)
        self.assertIn("function _qwenOrbitRadius", generate_js)
        self.assertIn("function _qwenOrbitVector", generate_js)
        self.assertIn("_qwenSignedYaw(horizontal) / 90", generate_js)
        self.assertIn("var radiusPx = Math.min(rect.width, rect.height) * (_qwenOrbitRadius() / 100)", generate_js)
        self.assertIn("if (len > 1)", generate_js)
        self.assertIn("var signedYaw = x * 90", generate_js)
        self.assertIn("horizontal_angle: signedYaw < 0 ? 360 + signedYaw : signedYaw", generate_js)
        self.assertIn("vertical_angle: _qwenNormToPitch(y)", generate_js)
        reset_body = generate_js.split("function _resetQwenAngleControl", 1)[1].split("function _initQwenAngleControls", 1)[0]
        self.assertNotIn("_setQwenAngleEnabled(root, false", reset_body)
        self.assertNotIn("_setQwenAngleCollapsed(root, true", reset_body)
        self.assertIn("!qwenAngleEnabled", generate_js)
        self.assertIn("qwenAngleEnabled = _isCurrentQwenAngleActive()", generate_js)
        self.assertIn("!_isQwenAngleControlActive(angleRoot)", generate_js)
        self.assertIn("function _applyQwenAngleSpherePoint", generate_js)
        self.assertIn("function _promptWithQwenAngle", generate_js)
        self.assertIn("function _qwenAnglePromptFromFieldValues", generate_js)
        self.assertIn("function _sanitizePromptForQwenAngle", generate_js)
        self.assertIn("function _stripExistingQwenAngleMarkers", generate_js)
        self.assertIn("function _isConflictingQwenCameraClause", generate_js)
        self.assertIn("window.CW.preparePromptForQwenAngle", generate_js)
        self.assertIn("anglePrompt + '\\n' + base", generate_js)
        self.assertNotIn("base.indexOf('<sks>') >= 0) return base", generate_js)
        self.assertIn("<sks> ", generate_js)
        self.assertIn("低角度|高角度|俯视|俯拍|仰视|仰拍|平视", generate_js)
        self.assertIn("QwenMultiangleCameraNode", generate_js)
        self.assertIn(".qwen-angle-stage", css)
        self.assertIn("white-space: pre-wrap", css)
        self.assertIn("text-overflow: clip", css)
        self.assertIn("word-break: break-word", css)
        self.assertIn("aria-label=\"当前坐标参数\"", generate_js)
        self.assertIn('<div class="qwen-angle-readout" aria-label="当前坐标参数">', generate_js)
        self.assertIn("qwen-angle-reference-frame", generate_js)
        self.assertIn(".qwen-angle-mode", css)
        self.assertIn(".qwen-angle-mode button.active", css)
        self.assertIn(".qwen-angle-plane", css)
        self.assertIn(".qwen-angle-plane::before", css)
        self.assertIn("qwen-angle-orbit-ring", generate_js)
        self.assertIn("--qwen-orbit-size:12.666%", generate_js)
        self.assertIn("--qwen-orbit-size:50.666%", generate_js)
        self.assertIn(".qwen-angle-orbit-ring", css)
        self.assertIn("width: 76%", css)
        self.assertIn("aspect-ratio: 1 / 1", css)
        self.assertIn(".qwen-angle-card-side", css)
        self.assertIn(".qwen-angle-reference-frame", css)
        self.assertIn(".qwen-angle-camera-ray", css)
        self.assertIn(".qwen-angle-roll", css)
        self.assertIn(".qwen-angle-range", css)
        self.assertIn(".qwen-angle-slider-ticks", css)
        self.assertIn(".qwen-angle-control.is-collapsed", css)
        self.assertIn("--qwen-image-roll", css)
        self.assertIn("z-index: 36", css)
        self.assertIn(".qwen-angle-camera-frame", css)
        self.assertIn("background: #92400e", css)
        self.assertIn(".qwen-angle-readout", css)
        self.assertIn("position: absolute", css)
        self.assertIn("pointer-events: none", css)
        self.assertIn("rotateZ(var(--qwen-image-roll))", css)
        self.assertIn("translate3d(0, 0, 96px) scale(var(--qwen-camera-scale))", css)
        self.assertIn("transform: none", css)
        self.assertIn("translateZ(72px) rotate(var(--qwen-camera-ray-angle))", css)
        self.assertIn("transform: translateZ(0)", css)
        self.assertNotIn("rotateZ(var(--qwen-camera-roll))", css)
        self.assertNotIn("rotate(var(--qwen-camera-angle))", css)
        self.assertIn("touch-action: none", css)
        self.assertIn("perspective: 760px", css)


if __name__ == "__main__":
    unittest.main()
