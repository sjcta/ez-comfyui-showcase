import json
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / "data/workflows"
CONFIG_ROOT = ROOT / "data/wf_configs"

CORE_NEGATIVE_TERMS = (
    "low quality",
    "bad anatomy",
    "watermark",
    "incorrect lettering",
)
VIDEO_NEGATIVE_TERMS = (
    "flicker",
    "temporal artifacts",
    "low frequency hum",
    "sub-bass rumble",
    "noisy room tone",
)
STYLE_TERM_RE = re.compile(
    r"\b("
    r"anime|manga|cartoon|toon|comic|game|gamer|cinematic|film grain|"
    r"photorealistic|photo realistic|hyperrealistic|ultra realistic|realistic|"
    r"3d|cg|cgi|render|rendered|painting|painted|oil brushstrokes|"
    r"van gogh|illustration|illustrative|newscast|podcast|comedy|horror"
    r")\b",
    re.IGNORECASE,
)


def _workflow_nodes(workflow):
    if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list):
        return {
            str(node.get("id")): node
            for node in workflow["nodes"]
            if isinstance(node, dict) and "id" in node
        }
    if isinstance(workflow, dict):
        return {
            str(node_id): node
            for node_id, node in workflow.items()
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict)
        }
    return {}


def _reference_id(value):
    if isinstance(value, list) and value and isinstance(value[0], (str, int)):
        return str(value[0])
    return None


def _negative_texts_for_workflow(path):
    workflow = json.loads(path.read_text())
    nodes = _workflow_nodes(workflow)
    results = []

    def visit(node_id, origin, visited):
        if node_id in visited:
            return
        visited.add(node_id)
        node = nodes.get(node_id)
        if not node:
            return
        if node.get("class_type") == "ConditioningZeroOut":
            return

        inputs = node.get("inputs", {})
        for text_key in ("text", "prompt"):
            value = inputs.get(text_key)
            if isinstance(value, str) and value.strip():
                results.append((origin, node_id, text_key, value))
                return

        for key, value in inputs.items():
            if not re.search(r"(negative|conditioning|cond|guide)", str(key), re.IGNORECASE):
                continue
            ref = _reference_id(value)
            if ref:
                visit(ref, origin, visited)

    for node_id, node in nodes.items():
        inputs = node.get("inputs", {})
        ref = _reference_id(inputs.get("negative"))
        if ref:
            visit(ref, node_id, set())

    return results


def _visible_negative_config_values():
    values = []
    for path in sorted(CONFIG_ROOT.glob("*.json")):
        config = json.loads(path.read_text())
        for field in config.get("fields", []):
            label = str(field.get("label", ""))
            key = str(field.get("key", ""))
            if "负面" not in label and "negative" not in key.lower():
                continue
            values.append((path, field))
    return values


class WorkflowNegativePromptTests(unittest.TestCase):
    def test_negative_prompt_texts_are_generic_error_controls(self):
        found = []
        for path in sorted(WORKFLOW_ROOT.rglob("*.json")):
            for origin, node_id, text_key, text in _negative_texts_for_workflow(path):
                found.append((path, origin, node_id, text_key, text))
                lowered = text.lower()
                for term in CORE_NEGATIVE_TERMS:
                    self.assertIn(term, lowered, f"{path}:{node_id} missing {term}")
                self.assertIsNone(
                    STYLE_TERM_RE.search(text),
                    f"{path}:{node_id} contains style-specific negative text",
                )

        self.assertGreaterEqual(len(found), 20)

    def test_video_negative_prompt_texts_keep_temporal_and_audio_errors(self):
        for path in sorted(WORKFLOW_ROOT.rglob("*.json")):
            if not re.search(r"(?:^|[_\-/])i2v|ltx", str(path), re.IGNORECASE):
                continue
            for _origin, node_id, _text_key, text in _negative_texts_for_workflow(path):
                lowered = text.lower()
                for term in VIDEO_NEGATIVE_TERMS:
                    self.assertIn(term, lowered, f"{path}:{node_id} missing {term}")

    def test_visible_negative_config_defaults_are_prefilled(self):
        values = _visible_negative_config_values()

        self.assertGreaterEqual(len(values), 5)
        for path, field in values:
            self.assertIn("value", field, f"{path}:{field.get('key')} should expose a default")
            text = str(field.get("value", ""))
            lowered = text.lower()
            for term in CORE_NEGATIVE_TERMS:
                self.assertIn(term, lowered, f"{path}:{field.get('key')} missing {term}")
            self.assertIsNone(
                STYLE_TERM_RE.search(text),
                f"{path}:{field.get('key')} contains style-specific negative text",
            )

    def test_image_only_ernie_negative_prompt_excludes_audio_controls(self):
        path = WORKFLOW_ROOT / "DGX Spark/t2i_ernie_image.json"
        texts = _negative_texts_for_workflow(path)

        self.assertTrue(texts)
        for _origin, node_id, _text_key, text in texts:
            lowered = text.lower()
            self.assertNotIn("low frequency hum", lowered, f"{path}:{node_id}")
            self.assertNotIn("sub-bass rumble", lowered, f"{path}:{node_id}")
            self.assertNotIn("noisy room tone", lowered, f"{path}:{node_id}")


if __name__ == "__main__":
    unittest.main()
