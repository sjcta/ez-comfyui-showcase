#!/usr/bin/env python3
"""
Generate wf_configs for 6 newly converted ComfyUI API prompt workflows.
"""
import json
import os
import sys

WORKFLOWS_DIR = "/Users/ai/projects/ez-comfyui-showcase/data/workflows"
CONFIGS_DIR = "/Users/ai/projects/ez-comfyui-showcase/data/wf_configs"

# Files to process (must match exactly what's in data/workflows/)
TARGETS = [
    "i2i-FireRed-Edit-1.1.json",
    "i2i_Qwen_Edit.json",
    "nunchaku-z-image-turbo-high.json",
    "nunchaku_T2I_4k.json",
    "image_ernie_image.json",
    "nunchaku-z-image-turbo-highSD.json",
]

ZONE_RULES = {
    "CLIPTextEncode": {"text": "user_input"},
    "TextEncodeQwenImageEditPlus": {"prompt": "user_input"},
    "LoadImage": {"image": "user_input"},
    # EmptyLatentImage/EmptySD3LatentImage: all exposed fields -> user_input
    "EmptyLatentImage": "__all_user_input__",
    "EmptySD3LatentImage": "__all_user_input__",
    # Samplers: all exposed fields -> advanced
    "KSampler": "__all_advanced__",
    "KSamplerAdvanced": "__all_advanced__",
    "SamplerCustom": "__all_advanced__",
    # VAE decode/encode: all exposed fields -> output
    "VAEDecode": "__all_output__",
    "VAEEncode": "__all_output__",
    # SaveImage: all exposed fields -> output
    "SaveImage": "__all_output__",
}


def is_exposed(key, val):
    """Check if a node input is an exposed field (user-editable)."""
    return isinstance(val, list) and len(val) == 2 and isinstance(val[1], dict) and "name" in val[1]


def get_zone(class_type, field_name):
    """Determine zone for a given node class_type and field_name."""
    rule = ZONE_RULES.get(class_type)
    if rule == "__all_user_input__":
        return "user_input"
    elif rule == "__all_advanced__":
        return "advanced"
    elif rule == "__all_output__":
        return "output"
    elif isinstance(rule, dict):
        return rule.get(field_name, "hidden")
    return "hidden"


def gen_config(workflow_name):
    """Generate a wf_config for one workflow."""
    wf_path = os.path.join(WORKFLOWS_DIR, workflow_name)
    if not os.path.exists(wf_path):
        print(f"  [SKIP] {workflow_name}: file not found at {wf_path}")
        return None

    with open(wf_path, "r") as f:
        wf = json.load(f)

    fields = []
    order = 0

    for node_id, node in wf.items():
        class_type = node.get("class_type", "")
        title = node.get("_meta", {}).get("title", class_type)
        inputs = node.get("inputs", {})

        for field_name, field_val in inputs.items():
            if not is_exposed(field_name, field_val):
                continue

            zone = get_zone(class_type, field_name)
            visible = zone != "hidden"
            label_name = field_val[1]["name"] if isinstance(field_val[1], dict) else field_name

            field_entry = {
                "key": f"{node_id}::{field_name}",
                "zone": zone,
                "visible": visible,
                "label": label_name,
                "order": order,
                "type": "text",
            }

            # Smart type detection based on field name
            fname_lower = field_name.lower()
            if "image" in fname_lower or fname_lower == "upload":
                field_entry["type"] = "image"
            elif "prompt" in fname_lower or "text" in fname_lower:
                field_entry["type"] = "textarea"
            elif "seed" in fname_lower:
                field_entry["type"] = "seed"
            elif "width" in fname_lower or "height" in fname_lower or "resolution" in fname_lower:
                field_entry["type"] = "number"
                if "resolution" in fname_lower or "width" in fname_lower or "height" in fname_lower:
                    field_entry["step"] = 64
                    field_entry["min"] = 256
                    field_entry["max"] = 8192
            elif "batch_size" in fname_lower or "steps" in fname_lower or "cfg" == fname_lower:
                field_entry["type"] = "number"
            elif fname_lower in ("denoise", "scale_by", "strength", "shift"):
                field_entry["type"] = "number"
                if "denoise" in fname_lower or "strength" in fname_lower:
                    field_entry["step"] = 0.05
                    field_entry["min"] = 0
                    field_entry["max"] = 1
            elif "sampler_name" in fname_lower:
                field_entry["type"] = "select"
                field_entry["options"] = [
                    "euler", "euler_ancestral", "heun", "dpm_2",
                    "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive",
                    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_2m",
                    "dpmpp_2m_sde", "ddim", "uni_pc", "uni_pc_bh2", "res_multistep"
                ]
            elif "scheduler" in fname_lower:
                field_entry["type"] = "select"
                field_entry["options"] = [
                    "normal", "karras", "exponential", "sgm_uniform",
                    "simple", "ddim_uniform", "beta"
                ]
            elif "upscale_method" in fname_lower:
                field_entry["type"] = "select"
                field_entry["options"] = ["nearest-exact", "bilinear", "bicubic", "lanczos", "area"]
            elif "enable" in fname_lower or fname_lower in ("value", "switch", "uniform_batch_size", "encode_tiled", "decode_tiled", "tile_debug", "cache_model", "swap_io_components"):
                field_entry["type"] = "toggle"
            elif "filename_prefix" in fname_lower:
                field_entry["type"] = "text"

            fields.append(field_entry)
            order += 1

    config = {
        "version": 1,
        "workflow": workflow_name,
        "fields": fields,
    }

    return config


def main():
    os.makedirs(CONFIGS_DIR, exist_ok=True)
    generated = []

    for wf_name in TARGETS:
        print(f"\nProcessing: {wf_name}")
        config = gen_config(wf_name)
        if config is None:
            continue

        config_path = os.path.join(CONFIGS_DIR, wf_name)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"  -> Saved: {config_path}")
        print(f"  -> {len(config['fields'])} fields generated")
        generated.append(wf_name)

    print(f"\n{'='*60}")
    print(f"Generated configs for {len(generated)}/{len(TARGETS)} workflows:")
    for g in generated:
        print(f"  - {g}")

if __name__ == "__main__":
    main()
