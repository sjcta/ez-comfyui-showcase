"""Image-to-prompt helpers backed by the local ComfyUI interrogation workflow."""

from __future__ import annotations

import copy
import difflib
import os
import re
import time
import uuid
from typing import Any, Callable


INTERROGATE_MAX_IMAGE_SIDE = 1280
INTERROGATE_MAX_IMAGE_PIXELS = 1_600_000


def build_image_interrogate_workflow(image_filename: str) -> dict[str, dict[str, Any]]:
    """Build the fast WD14 + Florence PromptGen ComfyUI API prompt."""
    image_name = str(image_filename or "").replace("\\", "/").lstrip("/")
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "2": {
            "class_type": "WD14Tagger|pysssss",
            "inputs": {
                "image": ["1", 0],
                "model": "wd-v1-4-moat-tagger-v2",
                "threshold": 0.35,
                "character_threshold": 0.85,
                "replace_underscore": True,
                "trailing_comma": False,
                "exclude_tags": "",
            },
        },
        "3": {
            "class_type": "ShowText|pysssss",
            "inputs": {"text": ["2", 0]},
        },
        "4": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "lanczos",
                "width": 768,
                "height": 768,
                "crop": "center",
            },
        },
        "5": {
            "class_type": "DownloadAndLoadFlorence2Model",
            "inputs": {
                "model": "MiaoshouAI/Florence-2-base-PromptGen-v2.0",
                "precision": "fp16",
                "attention": "sdpa",
            },
        },
        "6": {
            "class_type": "Florence2Run",
            "inputs": {
                "image": ["4", 0],
                "florence2_model": ["5", 0],
                "text_input": "",
                "task": "prompt_gen_mixed_caption",
                "fill_mask": True,
                "keep_model_loaded": False,
                "max_new_tokens": 512,
                "num_beams": 3,
                "do_sample": False,
                "seed": 1,
            },
        },
        "7": {
            "class_type": "ShowText|pysssss",
            "inputs": {"text": ["6", 2]},
        },
    }


def _safe_input_path(input_dir: str, image_filename: str) -> tuple[str, str]:
    safe = str(image_filename or "").replace("\\", "/").lstrip("/")
    input_root = os.path.abspath(input_dir)
    path = os.path.abspath(os.path.join(input_root, safe))
    if os.path.commonpath([input_root, path]) != input_root:
        raise RuntimeError(f"非法反推图片路径: {image_filename}")
    return safe, path


def prepare_interrogate_image(
    image_filename: str,
    input_dir: str,
    max_side: int = INTERROGATE_MAX_IMAGE_SIDE,
    max_pixels: int = INTERROGATE_MAX_IMAGE_PIXELS,
) -> dict[str, Any]:
    """Create a smaller image for interrogation when the uploaded image is large."""
    safe, src = _safe_input_path(input_dir, image_filename)
    if not os.path.isfile(src):
        raise RuntimeError(f"反推图片不存在: {image_filename}")

    try:
        from PIL import Image, ImageOps
    except Exception as e:
        return {
            "filename": safe,
            "optimized": False,
            "reason": f"pillow_unavailable: {e}",
        }

    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        pixel_count = width * height
        side_limit = max(256, int(max_side or INTERROGATE_MAX_IMAGE_SIDE))
        pixel_limit = max(256 * 256, int(max_pixels or INTERROGATE_MAX_IMAGE_PIXELS))
        needs_resize = width > side_limit or height > side_limit or pixel_count > pixel_limit
        if not needs_resize:
            return {
                "filename": safe,
                "optimized": False,
                "width": width,
                "height": height,
                "pixels": pixel_count,
            }

        img.thumbnail((side_limit, side_limit), Image.Resampling.LANCZOS)
        if img.width * img.height > pixel_limit:
            scale = (pixel_limit / float(img.width * img.height)) ** 0.5
            resized = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(resized, Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if "A" in img.getbands():
                background.paste(img, mask=img.getchannel("A"))
            else:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        base_dir = os.path.dirname(safe)
        stem = os.path.splitext(os.path.basename(safe))[0]
        optimized_rel = "/".join(part for part in (base_dir, "_interrogate", f"{stem}_max{side_limit}.jpg") if part)
        _, dest = _safe_input_path(input_dir, optimized_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        img.save(dest, "JPEG", quality=88, optimize=True)
        final_width, final_height = img.size

    return {
        "filename": optimized_rel,
        "optimized": True,
        "original_filename": safe,
        "original_width": width,
        "original_height": height,
        "original_pixels": pixel_count,
        "width": final_width,
        "height": final_height,
        "pixels": final_width * final_height,
        "max_side": side_limit,
    }


def _text_output(outputs: dict[str, Any], node_id: str) -> str:
    node_out = outputs.get(str(node_id), {})
    text = node_out.get("text") if isinstance(node_out, dict) else None
    if isinstance(text, list) and text:
        return str(text[0]).strip()
    if isinstance(text, str):
        return text.strip()
    return ""


def _tag_output(outputs: dict[str, Any], node_id: str) -> str:
    node_out = outputs.get(str(node_id), {})
    tags = node_out.get("tags") if isinstance(node_out, dict) else None
    if isinstance(tags, list) and tags:
        return str(tags[0]).strip()
    if isinstance(tags, str):
        return tags.strip()
    return ""


def _is_tag_like_prompt_line(text: str) -> bool:
    """Detect WD14/booru-style comma tag lines that should not become final prompts."""
    line = str(text or "").strip().strip(".。")
    if not line:
        return False
    parts = [part.strip() for part in re.split(r"[,，]", line) if part.strip()]
    if len(parts) < 4:
        return False
    if re.search(r"[.。!?！？]", line):
        return False
    short_parts = 0
    for part in parts:
        words = [word for word in re.split(r"\s+", part) if word]
        if len(words) <= 3 and len(part) <= 36:
            short_parts += 1
    return short_parts / max(1, len(parts)) >= 0.75


def _paragraph_similarity(a: str, b: str) -> float:
    a_norm = re.sub(r"\s+", " ", str(a or "").strip().lower())
    b_norm = re.sub(r"\s+", " ", str(b or "").strip().lower())
    if not a_norm or not b_norm:
        return 0.0
    return max(
        difflib.SequenceMatcher(None, a_norm, b_norm).ratio(),
        difflib.SequenceMatcher(None, b_norm, a_norm).ratio(),
    )


def _paragraph_token_overlap(a: str, b: str) -> float:
    words_a = {
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", str(a or "").lower())
        if word not in {"the", "and", "with", "this", "that", "image", "itself", "even", "more"}
    }
    words_b = {
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", str(b or "").lower())
        if word not in {"the", "and", "with", "this", "that", "image", "itself", "even", "more"}
    }
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(1, min(len(words_a), len(words_b)))


def _clean_promptgen_text(text: str) -> str:
    """Keep Florence's natural caption and remove duplicate/tagger fragments."""
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
    if not blocks:
        blocks = [normalized]
    cleaned_blocks: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        prose_lines = [line for line in lines if not _is_tag_like_prompt_line(line)]
        prose = " ".join(prose_lines).strip()
        if not prose:
            continue
        if any(
            _paragraph_similarity(prose, previous) >= 0.58
            or _paragraph_token_overlap(prose, previous) >= 0.55
            for previous in cleaned_blocks
        ):
            continue
        cleaned_blocks.append(prose)
    return "\n\n".join(cleaned_blocks).strip()


def extract_interrogate_result(history_entry: dict[str, Any]) -> dict[str, str]:
    """Extract prompt candidates from a ComfyUI interrogation history entry."""
    outputs = history_entry.get("outputs", {}) if isinstance(history_entry, dict) else {}
    wd14 = _text_output(outputs, "3") or _tag_output(outputs, "2")
    promptgen = _clean_promptgen_text(_text_output(outputs, "7"))
    wd14_as_prompt = "" if _is_tag_like_prompt_line(wd14) else wd14
    prompt = promptgen or wd14_as_prompt
    return {"prompt": prompt, "promptgen": promptgen, "wd14_tags": wd14}


def run_image_interrogator(
    image_filename: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 180.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    """Submit the interrogation workflow to ComfyUI and return prompt text."""
    workflow = build_image_interrogate_workflow(image_filename)
    response = comfyui_post(
        "/prompt",
        {"prompt": copy.deepcopy(workflow), "client_id": f"ez-img-prompt-{uuid.uuid4().hex}"},
        base_url,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id for image interrogation")

    deadline = time.time() + float(timeout or 180.0)
    while time.time() < deadline:
        history = comfyui_get(f"/history/{prompt_id}", base_url)
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if status.get("completed", False):
                result = extract_interrogate_result(entry)
                if result["prompt"]:
                    return {"ok": True, "provider": "comfyui-wd14-florence", "prompt_id": prompt_id, **result}
                raise RuntimeError("ComfyUI image interrogation completed without text output")
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError(str(messages)[:300] if messages else "ComfyUI image interrogation failed")
        time.sleep(max(0.1, float(poll_interval or 1.0)))
    raise TimeoutError("Image interrogation timed out")
