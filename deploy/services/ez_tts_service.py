#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import random
import time
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf


DEFAULT_REF_URL = "https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-TTS-Repo/clone.wav"
DEFAULT_REF_TEXT = "Okay. Yeah. I resent you. I love you. I respect you. But you know what? You blew it! And thanks to you."
DEFAULT_ZH_REF_TEXT = "甚至出现交易几乎停滞的情况"
QWEN_CUSTOM_VOICE_OPTIONS = {
    "Vivian / 明亮年轻女声（中文）": "Vivian",
    "Serena / 温暖温柔女声（中文）": "Serena",
    "Uncle_Fu / 低沉成熟男声（中文）": "Uncle_Fu",
    "Dylan / 北京青年男声（中文北京话）": "Dylan",
    "Eric / 成都男声（四川话）": "Eric",
    "Ryan / 节奏感男声（英文）": "Ryan",
    "Aiden / 美式阳光男声（英文）": "Aiden",
    "Ono_Anna / 轻快日语女声（日语）": "Ono_Anna",
    "Sohee / 温暖韩语女声（韩语）": "Sohee",
}
QWEN_CUSTOM_VOICE_DEFAULT = "Serena"
QWEN_CUSTOM_VOICE_LEGACY_ALIASES = {
    "cherry": "Serena",
    "芊悦": "Serena",
    "ono anna": "Ono_Anna",
    "ono_anna": "Ono_Anna",
}
for _speaker in QWEN_CUSTOM_VOICE_OPTIONS.values():
    QWEN_CUSTOM_VOICE_LEGACY_ALIASES[_speaker.lower()] = _speaker
QWEN_CUSTOM_VOICE_NO_STYLE_VALUES = {
    "",
    "default",
    "none",
    "no style",
    "natural",
    "默认",
    "无风格指令",
    "默认自然朗读",
    "默认自然朗读（无额外风格）",
}
VOICE_PRESETS = {
    "auto": {"label": "自动按语言选择"},
    "qwen_reference_zh": {"label": "Qwen参考音频克隆（中文样本）", "alias_of": "zh_aishell"},
    "qwen_reference_en": {"label": "Qwen参考音频克隆（英文样本）", "alias_of": "en_qwen_clone"},
    "voxcpm2_native": {"label": "VoxCPM2无参考原生生成", "mode": "native"},
    "voxcpm2_voice_design": {"label": "VoxCPM2文字描述音色（0样本）", "mode": "voice_design"},
    "voxcpm2_reference_zh": {"label": "VoxCPM2参考音频克隆（中文样本）", "alias_of": "zh_aishell"},
    "voxcpm2_reference_en": {"label": "VoxCPM2参考音频克隆（英文样本）", "alias_of": "en_qwen_clone"},
    "indextts2_reference_zh": {"label": "IndexTTS2参考音频克隆（中文样本）", "alias_of": "zh_aishell"},
    "indextts2_reference_en": {"label": "IndexTTS2参考音频克隆（英文样本）", "alias_of": "en_qwen_clone"},
    "higgs_native": {"label": "Higgs Zero-shot原生生成", "mode": "native"},
    "higgs_reference_zh": {"label": "Higgs参考音频克隆（中文样本）", "alias_of": "zh_aishell"},
    "higgs_reference_en": {"label": "Higgs参考音频克隆（英文样本）", "alias_of": "en_qwen_clone"},
    "zh_aishell": {
        "label": "中文默认音色",
        "path_env": "EZ_TTS_ZH_REF_AUDIO",
        "path": "/workspace/tts/reference/aishell_zh.wav",
        "text": DEFAULT_ZH_REF_TEXT,
    },
    "en_qwen_clone": {
        "label": "英文默认音色",
        "path_env": "EZ_TTS_EN_REF_AUDIO",
        "path": "/workspace/tts/reference/qwen_clone.wav",
        "url": DEFAULT_REF_URL,
        "text": DEFAULT_REF_TEXT,
    },
    "custom_reference": {"label": "使用上传参考音频"},
}
SERVICE_MODEL_CACHE: dict[str, object] = {}


VOICE_INPUT_MODE_ALIASES = {
    "": "auto",
    "auto": "auto",
    "自动": "auto",
    "default": "auto",
    "默认": "auto",
    "native": "native",
    "原生默认": "native",
    "无参考原生生成": "native",
    "zero-shot": "native",
    "zeroshot": "native",
    "zero-shot原生生成": "native",
    "本地预设 speaker": "custom_voice",
    "本地预设 speaker（customvoice）": "custom_voice",
    "本地预设发音人": "custom_voice",
    "预设 speaker": "custom_voice",
    "预设发音人": "custom_voice",
    "customvoice": "custom_voice",
    "custom voice": "custom_voice",
    "speaker": "custom_voice",
    "voice": "custom_voice",
    "官方发音人": "custom_voice",
    "官方发音人（dashscope）": "custom_voice",
    "dashscope": "custom_voice",
    "select voice": "custom_voice",
    "声音设计": "voice_description",
    "声音设计（无参考音频）": "voice_description",
    "voice design": "voice_description",
    "参考音频": "reference_audio",
    "参考音频克隆": "reference_audio",
    "上传参考音频": "reference_audio",
    "上传参考音频克隆": "reference_audio",
    "上传参考音频克隆（本地）": "reference_audio",
    "本地参考音频克隆": "reference_audio",
    "本地参考音频克隆（base）": "reference_audio",
    "可控克隆": "reference_audio",
    "可控克隆（参考音频+控制指令）": "reference_audio",
    "controllable cloning": "reference_audio",
    "reference": "reference_audio",
    "reference_audio": "reference_audio",
    "upload": "reference_audio",
    "极致克隆": "ultimate_cloning",
    "极致克隆模式": "ultimate_cloning",
    "极致克隆（参考音频+逐字稿）": "ultimate_cloning",
    "ultimate": "ultimate_cloning",
    "ultimate cloning": "ultimate_cloning",
    "prompt_text": "ultimate_cloning",
    "hifi": "ultimate_cloning",
    "hi-fi": "ultimate_cloning",
    "voice_description": "voice_description",
    "description": "voice_description",
    "文字描述": "voice_description",
    "文字描述音色": "voice_description",
    "文字描述音色（0样本）": "voice_description",
}

VOXCPM2_CHINESE_DIALECT_CONTROLS = {
    "四川话": "四川话",
    "粤语": "广东话",
    "吴语": "吴语",
    "东北话": "东北话",
    "河南话": "河南话",
    "陕西话": "陕西话",
    "山东话": "山东话",
    "天津话": "天津话",
    "闽南话": "闽南话",
}


def _coerce_seed(value) -> int | None:
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return None
    if seed < 0:
        seed = 0
    return seed % 2147483648


def _apply_seed(seed: int | None) -> None:
    if seed is None:
        return
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _wav_response(handler: BaseHTTPRequestHandler, wav_bytes: bytes, extra_headers: dict | None = None) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "audio/wav")
    handler.send_header("Content-Length", str(len(wav_bytes)))
    for key, value in (extra_headers or {}).items():
        handler.send_header(key, _header_safe_value(value))
    handler.end_headers()
    handler.wfile.write(wav_bytes)


def _header_safe_value(value) -> str:
    raw = str(value)
    try:
        raw.encode("latin-1")
        return raw
    except UnicodeEncodeError:
        return urllib.parse.quote(raw, safe=" -_./")


def _ensure_default_reference() -> Path:
    ref_path = Path(os.environ.get("EZ_TTS_DEFAULT_REF_AUDIO", VOICE_PRESETS["en_qwen_clone"]["path"]))
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    if not ref_path.exists() or ref_path.stat().st_size < 1024:
        urllib.request.urlretrieve(DEFAULT_REF_URL, ref_path)
    return ref_path


def _resolve_uploaded_reference_audio(value: str) -> Path | None:
    value = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_file():
        return candidate
    input_root = Path(os.environ.get("EZ_COMFYUI_INPUT_DIR", "/home/sjcta/software/ComfyUI-Project/ComfyUI/input"))
    resolved = (input_root / value).resolve()
    try:
        resolved.relative_to(input_root.resolve())
    except ValueError:
        return None
    if resolved.is_file():
        return resolved
    return None


def _preset_entry(preset_key: str) -> dict:
    preset = VOICE_PRESETS.get(preset_key) or VOICE_PRESETS["zh_aishell"]
    seen = {preset_key}
    while preset.get("alias_of") and str(preset["alias_of"]) not in seen:
        alias = str(preset["alias_of"])
        seen.add(alias)
        preset = VOICE_PRESETS.get(alias) or preset
    return preset


def _language_is_english_like(language: str) -> bool:
    value = str(language or "").strip().lower()
    return value.startswith("en") or value in {"english", "english / 英文"}


def _language_is_chinese_like(language: str) -> bool:
    value = str(language or "").strip().lower()
    return value.startswith("zh") or value in {
        "auto",
        "auto / 自动",
        "chinese",
        "chinese / 中文",
        "mandarin",
        "中文",
        "中国话",
        "普通话",
        "四川话",
        "粤语",
        "吴语",
        "东北话",
        "河南话",
        "陕西话",
        "山东话",
        "天津话",
        "闽南话",
    }


def _default_reference_preset(engine: str, language: str) -> str:
    suffix = "zh" if _language_is_chinese_like(language) else "en"
    if engine == "voxcpm2":
        return f"voxcpm2_reference_{suffix}"
    if engine == "indextts2":
        return f"indextts2_reference_{suffix}"
    if engine == "higgs_audio_v3":
        return f"higgs_reference_{suffix}"
    return f"qwen_reference_{suffix}"


def _voice_input_mode_for_payload(payload: dict) -> str:
    raw = str(payload.get("voice_input_mode") or "").strip().lower()
    return VOICE_INPUT_MODE_ALIASES.get(raw, raw or "auto")


def _voice_preset_for_payload(payload: dict, engine: str) -> str:
    value = str(payload.get("voice_preset") or "auto").strip().lower()
    aliases = {
        "": "auto",
        "自动": "auto",
        "default": "auto",
        "zh": "zh_aishell",
        "chinese": "zh_aishell",
        "中文默认音色": "zh_aishell",
        "en": "en_qwen_clone",
        "english": "en_qwen_clone",
        "英文默认音色": "en_qwen_clone",
        "qwen中文克隆音色": "qwen_reference_zh",
        "qwen英文官方音色": "qwen_reference_en",
        "qwen参考音频克隆（中文样本）": "qwen_reference_zh",
        "qwen参考音频克隆（英文样本）": "qwen_reference_en",
        "自动按语言选择参考样本": "auto",
        "auto / 自动按语言选择参考样本": "auto",
        "chinese reference / 中文默认参考样本": "qwen_reference_zh",
        "english reference / 英文默认参考样本": "qwen_reference_en",
        "voxcpm2原生默认": "voxcpm2_native",
        "voxcpm2无参考原生生成": "voxcpm2_native",
        "voxcpm2温柔女声": "voxcpm2_voice_design",
        "voxcpm2沉稳男声": "voxcpm2_voice_design",
        "voxcpm2新闻主播": "voxcpm2_voice_design",
        "voxcpm2文字描述音色（0样本）": "voxcpm2_voice_design",
        "voxcpm2参考音频克隆（中文样本）": "voxcpm2_reference_zh",
        "voxcpm2参考音频克隆（英文样本）": "voxcpm2_reference_en",
        "indextts2中文参考音色": "indextts2_reference_zh",
        "indextts2英文参考音色": "indextts2_reference_en",
        "indextts2参考音频克隆（中文样本）": "indextts2_reference_zh",
        "indextts2参考音频克隆（英文样本）": "indextts2_reference_en",
        "higgs原生默认": "higgs_native",
        "higgs zero-shot原生生成": "higgs_native",
        "higgs中文克隆音色": "higgs_reference_zh",
        "higgs英文克隆音色": "higgs_reference_en",
        "higgs参考音频克隆（中文样本）": "higgs_reference_zh",
        "higgs参考音频克隆（英文样本）": "higgs_reference_en",
        "自定义参考音频": "custom_reference",
        "custom reference audio / 自定义参考音频": "custom_reference",
        "custom": "custom_reference",
        "upload": "custom_reference",
        "custom_audio": "custom_reference",
    }
    value = aliases.get(value, value)
    if value == "auto":
        if engine == "voxcpm2":
            mode = _voice_input_mode_for_payload(payload)
            if mode == "voice_description":
                return "voxcpm2_voice_design"
            if mode in {"reference_audio", "ultimate_cloning"}:
                return _default_reference_preset(engine, payload.get("language", "zh"))
            return "voxcpm2_native"
        if engine == "indextts2":
            return _default_reference_preset(engine, payload.get("language", "zh"))
        if engine == "higgs_audio_v3":
            mode = _voice_input_mode_for_payload(payload)
            if mode == "reference_audio":
                return _default_reference_preset(engine, payload.get("language", "zh"))
            return "higgs_native"
        return _default_reference_preset(engine, payload.get("language", "zh"))
    return value if value in VOICE_PRESETS else "zh_aishell"


def _ensure_preset_reference_audio(preset_key: str) -> Path:
    preset = _preset_entry(preset_key)
    if preset_key == "custom_reference":
        preset = VOICE_PRESETS["zh_aishell"]
    path = Path(os.environ.get(str(preset.get("path_env") or ""), str(preset.get("path") or "")))
    if preset.get("url"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size < 1024:
            urllib.request.urlretrieve(str(preset.get("url") or DEFAULT_REF_URL), path)
    if not path.is_file() or path.stat().st_size < 1024:
        raise FileNotFoundError(f"voice preset reference audio not found: {preset_key} -> {path}")
    return path


def _resolve_voice_reference(payload: dict, engine: str) -> tuple[Path | None, str | None, str, bool, str | None]:
    mode = _voice_input_mode_for_payload(payload)
    preset_key = _voice_preset_for_payload(payload, engine)
    if mode == "voice_description" and engine == "voxcpm2":
        description = str(payload.get("voice_description") or "").strip()
        return None, None, "voxcpm2_voice_design", False, description or None
    if mode == "native" and engine in {"voxcpm2", "higgs_audio_v3"}:
        native_key = "voxcpm2_native" if engine == "voxcpm2" else "higgs_native"
        return None, None, native_key, False, None
    requested_reference = str(payload.get("reference_audio") or "").strip()
    uploaded = _resolve_uploaded_reference_audio(requested_reference)
    if uploaded is not None and mode in {"auto", "reference_audio", "ultimate_cloning"}:
        ref_text = str(payload.get("reference_text") or "").strip() or None
        if engine == "qwen_tts":
            return uploaded, ref_text, "custom_reference", ref_text is None, None
        if mode == "ultimate_cloning" and not ref_text:
            raise ValueError("VoxCPM2 极致克隆需要填写参考音频逐字稿")
        if mode != "ultimate_cloning":
            ref_text = None
        return uploaded, ref_text, "custom_reference", ref_text is None, None
    if engine == "voxcpm2" and mode in {"reference_audio", "ultimate_cloning"} and not requested_reference:
        raise ValueError("VoxCPM2 可控克隆/极致克隆需要上传参考音频")
    if engine == "qwen_tts" and mode == "reference_audio" and preset_key == "custom_reference" and not requested_reference:
        raise ValueError("Qwen TTS 自定义参考音频需要上传参考音频")
    if mode == "reference_audio" and requested_reference:
        input_root = Path(os.environ.get("EZ_COMFYUI_INPUT_DIR", "/home/sjcta/software/ComfyUI-Project/ComfyUI/input"))
        raise FileNotFoundError(
            f"uploaded reference audio not found or not synced: {requested_reference} "
            f"(input_root={input_root})"
        )
    if mode == "ultimate_cloning" and requested_reference:
        input_root = Path(os.environ.get("EZ_COMFYUI_INPUT_DIR", "/home/sjcta/software/ComfyUI-Project/ComfyUI/input"))
        raise FileNotFoundError(
            f"uploaded reference audio not found or not synced: {requested_reference} "
            f"(input_root={input_root})"
        )
    if mode == "reference_audio" and preset_key in {"auto", "voxcpm2_native", "higgs_native", "voxcpm2_voice_design"}:
        preset_key = _default_reference_preset(engine, payload.get("language", "zh"))
    preset = VOICE_PRESETS.get(preset_key) or VOICE_PRESETS["zh_aishell"]
    mode = str(preset.get("mode") or "")
    if mode in {"native", "voice_design"}:
        description = str(payload.get("voice_description") or preset.get("description") or "").strip()
        return None, None, preset_key, False, description or None
    ref_audio = _ensure_preset_reference_audio(preset_key)
    effective_preset = _preset_entry(preset_key)
    ref_text = str(payload.get("reference_text") or effective_preset.get("text") or DEFAULT_REF_TEXT).strip()
    return ref_audio, ref_text, preset_key, False, None


def _wav_bytes(samples, sample_rate: int) -> bytes:
    arr = np.asarray(samples)
    if arr.ndim > 1 and arr.shape[0] < arr.shape[-1]:
        arr = arr.T
    buf = io.BytesIO()
    sf.write(buf, arr, int(sample_rate), format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _language_for_qwen(language: str) -> str:
    value = str(language or "").strip().lower()
    mapping = {
        "auto": "Chinese",
        "auto / 自动": "Chinese",
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "chinese": "Chinese",
        "chinese / 中文": "Chinese",
        "中文": "Chinese",
        "en": "English",
        "en-us": "English",
        "english": "English",
        "english / 英文": "English",
        "ja": "Japanese",
        "jp": "Japanese",
        "japanese": "Japanese",
        "japanese / 日语": "Japanese",
        "ko": "Korean",
        "kr": "Korean",
        "korean": "Korean",
        "korean / 韩语": "Korean",
        "de": "German",
        "german": "German",
        "german / 德语": "German",
        "fr": "French",
        "french": "French",
        "french / 法语": "French",
        "ru": "Russian",
        "russian": "Russian",
        "russian / 俄语": "Russian",
        "pt": "Portuguese",
        "portuguese": "Portuguese",
        "portuguese / 葡萄牙语": "Portuguese",
        "es": "Spanish",
        "spanish": "Spanish",
        "spanish / 西班牙语": "Spanish",
        "it": "Italian",
        "italian": "Italian",
        "italian / 意大利语": "Italian",
    }
    if value in mapping:
        return mapping[value]
    for prefix, qwen_name in (
        ("en", "English"),
        ("ja", "Japanese"),
        ("ko", "Korean"),
        ("de", "German"),
        ("fr", "French"),
        ("ru", "Russian"),
        ("pt", "Portuguese"),
        ("es", "Spanish"),
        ("it", "Italian"),
    ):
        if value.startswith(prefix):
            return qwen_name
    return "Chinese"


def _qwen_uses_custom_voice(payload: dict) -> bool:
    return _voice_input_mode_for_payload(payload) in {"auto", "custom_voice"}


def _qwen_model(cache_key: str, env_name: str, default_model: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    model = SERVICE_MODEL_CACHE.get(cache_key)
    if model is None:
        model = Qwen3TTSModel.from_pretrained(
            os.environ.get(env_name, default_model),
            device_map=os.environ.get("EZ_QWEN_TTS_DEVICE", "cuda:0"),
            dtype=torch.bfloat16,
            attn_implementation=os.environ.get("EZ_QWEN_TTS_ATTN", "sdpa"),
        )
        SERVICE_MODEL_CACHE[cache_key] = model
    return model


def _qwen_custom_voice_speaker_for_payload(payload: dict) -> tuple[str, str]:
    raw = str(payload.get("voice_preset") or "").strip()
    if not raw or raw.lower() in {"auto", "自动", "auto / 自动按语言选择参考样本"}:
        return QWEN_CUSTOM_VOICE_DEFAULT, QWEN_CUSTOM_VOICE_DEFAULT
    if raw in QWEN_CUSTOM_VOICE_OPTIONS:
        return raw, QWEN_CUSTOM_VOICE_OPTIONS[raw]
    first = raw.split("/", 1)[0].strip()
    normalized = first.replace(" ", "_") if first.lower() == "ono anna" else first
    by_speaker = {value.lower(): value for value in QWEN_CUSTOM_VOICE_OPTIONS.values()}
    direct = by_speaker.get(normalized.lower())
    if direct:
        return raw, direct
    legacy = QWEN_CUSTOM_VOICE_LEGACY_ALIASES.get(first.lower()) or QWEN_CUSTOM_VOICE_LEGACY_ALIASES.get(raw.lower())
    if legacy:
        return raw, legacy
    supported = ", ".join(QWEN_CUSTOM_VOICE_OPTIONS.values())
    raise ValueError(f"unknown Qwen3-TTS local speaker: {raw}; supported speakers: {supported}")


def _qwen_custom_voice_instruct(payload: dict) -> str | None:
    preset = str(payload.get("voice_description") or "").strip()
    custom = str(payload.get("voice_style_custom") or "").strip()
    parts: list[str] = []
    if preset and preset.lower() not in {value.lower() for value in QWEN_CUSTOM_VOICE_NO_STYLE_VALUES}:
        parts.append(preset)
    if custom:
        parts.append(custom)
    return " ".join(parts) or None


def _voxcpm2_language_control(language: str) -> str:
    value = str(language or "").strip()
    return VOXCPM2_CHINESE_DIALECT_CONTROLS.get(value, "")


def _voxcpm2_is_chinese_dialect(language: str) -> bool:
    return bool(_voxcpm2_language_control(language))


def _merge_voxcpm2_control_descriptions(*parts: str | None) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = str(part or "").strip().strip("()").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return ", ".join(merged)


def _voxcpm2_generation_text(payload: dict, voice_description: str | None, *, include_control: bool = True) -> str:
    text = str(payload.get("text") or "")
    if not include_control:
        return text
    language_control = _voxcpm2_language_control(payload.get("language", ""))
    control = _merge_voxcpm2_control_descriptions(language_control, voice_description)
    return f"({control}){text}" if control else text


def _voxcpm2_should_use_hifi_prompt(payload: dict, ref_text: str | None) -> bool:
    if not str(ref_text or "").strip():
        return False
    return _voice_input_mode_for_payload(payload) == "ultimate_cloning"


def _qwen_tts(payload: dict) -> tuple[bytes, dict]:
    if _qwen_uses_custom_voice(payload):
        model = _qwen_model(
            "qwen_tts_custom_voice",
            "EZ_QWEN_CUSTOM_VOICE_MODEL",
            "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        )
        speaker_display, speaker = _qwen_custom_voice_speaker_for_payload(payload)
        wavs, sample_rate = model.generate_custom_voice(
            text=str(payload.get("text") or ""),
            language=_language_for_qwen(payload.get("language", "zh")),
            speaker=speaker,
            instruct=_qwen_custom_voice_instruct(payload),
        )
        return _wav_bytes(wavs[0], sample_rate), {
            "sample_rate": sample_rate,
            "voice_preset": speaker_display,
            "qwen_speaker": speaker,
        }

    model = _qwen_model(
        "qwen_tts_base",
        "EZ_QWEN_TTS_BASE_MODEL",
        os.environ.get("EZ_QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
    )
    ref_audio, ref_text, voice_preset, x_vector_only, _ = _resolve_voice_reference(payload, "qwen_tts")
    if ref_audio is None:
        fallback_key = _default_reference_preset("qwen_tts", payload.get("language", "zh"))
        ref_audio = _ensure_preset_reference_audio(fallback_key)
        ref_text = ref_text or (_preset_entry(fallback_key).get("text") or DEFAULT_REF_TEXT)
    wavs, sample_rate = model.generate_voice_clone(
        text=str(payload.get("text") or ""),
        language=_language_for_qwen(payload.get("language", "zh")),
        ref_audio=str(ref_audio),
        ref_text=ref_text,
        x_vector_only_mode=x_vector_only,
    )
    return _wav_bytes(wavs[0], sample_rate), {
        "sample_rate": sample_rate,
        "reference_audio": str(ref_audio),
        "voice_preset": voice_preset,
    }


def _voxcpm2_model_path() -> str:
    model_id = os.environ.get("EZ_VOXCPM2_MODEL", "openbmb/VoxCPM2")
    if os.path.isdir(model_id):
        path = Path(model_id)
    else:
        from huggingface_hub import snapshot_download

        path = Path(
            snapshot_download(
                repo_id=model_id,
                local_files_only=os.environ.get("HF_HUB_OFFLINE", "0").lower() in {"1", "true", "yes"},
            )
        )
    max_length = int(os.environ.get("EZ_VOXCPM2_MAX_LENGTH", "2048") or 2048)
    config_path = path / "config.json"
    if max_length > 0 and config_path.is_file():
        config = json.loads(config_path.read_text())
        current = int(config.get("max_length") or max_length)
        if current > max_length:
            config.setdefault("_ez_original_max_length", current)
            config["max_length"] = max_length
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return str(path)


def _voxcpm2(payload: dict) -> tuple[bytes, dict]:
    from voxcpm import VoxCPM

    model = SERVICE_MODEL_CACHE.get("voxcpm2")
    if model is None:
        model = VoxCPM(_voxcpm2_model_path(), enable_denoiser=False)
        SERVICE_MODEL_CACHE["voxcpm2"] = model
    ref_audio, ref_text, voice_preset, _, voice_description = _resolve_voice_reference(payload, "voxcpm2")
    max_length = int(os.environ.get("EZ_VOXCPM2_MAX_LENGTH", "2048") or 2048)
    cfg_default = float(os.environ.get("EZ_VOXCPM2_CFG_VALUE", "2.0") or 2.0)
    timesteps_default = int(os.environ.get("EZ_VOXCPM2_INFERENCE_TIMESTEPS", "30") or 30)
    use_hifi_prompt = ref_audio is not None and _voxcpm2_should_use_hifi_prompt(payload, ref_text)
    kwargs = {
        "text": _voxcpm2_generation_text(payload, voice_description, include_control=not use_hifi_prompt),
        "cfg_value": float(payload.get("cfg_value") or cfg_default),
        "inference_timesteps": int(payload.get("inference_timesteps") or timesteps_default),
        "max_len": max_length,
    }
    if ref_audio is not None:
        kwargs["reference_wav_path"] = str(ref_audio)
        if use_hifi_prompt:
            kwargs["prompt_wav_path"] = str(ref_audio)
            kwargs["prompt_text"] = ref_text
    wav = model.generate(**kwargs)
    sample_rate = int(model.tts_model.sample_rate)
    return _wav_bytes(wav, sample_rate), {
        "sample_rate": sample_rate,
        "reference_audio": str(ref_audio or ""),
        "voice_preset": voice_preset,
        "language": str(payload.get("language") or ""),
    }


def _patch_indextts_normalizer() -> None:
    from indextts.utils import front

    def simple_load(self):
        self.zh_normalizer = True
        self.en_normalizer = True

    def simple_normalize(self, text: str) -> str:
        repl = getattr(self, "zh_char_rep_map", getattr(self, "char_rep_map", {}))
        for src, dst in repl.items():
            text = text.replace(src, dst)
        return text

    front.TextNormalizer.load = simple_load
    front.TextNormalizer.normalize = simple_normalize


def _indextts2(payload: dict) -> tuple[bytes, dict]:
    _patch_indextts_normalizer()
    from indextts.infer_v2 import IndexTTS2

    model = SERVICE_MODEL_CACHE.get("indextts2")
    model_dir = os.environ.get("EZ_INDEXTTS2_DIR", "/workspace/tts/index-tts/checkpoints")
    if model is None:
        model = IndexTTS2(
            cfg_path=os.path.join(model_dir, "config.yaml"),
            model_dir=model_dir,
            use_fp16=True,
            use_cuda_kernel=False,
            use_deepspeed=False,
        )
        SERVICE_MODEL_CACHE["indextts2"] = model
    ref_audio, _, voice_preset, _, _ = _resolve_voice_reference(payload, "indextts2")
    if ref_audio is None:
        ref_audio = _ensure_preset_reference_audio(_default_reference_preset("indextts2", payload.get("language", "zh")))
    out_path = Path(os.environ.get("EZ_TTS_TMP_DIR", "/tmp")) / f"ez_indextts2_{int(time.time() * 1000)}.wav"
    model.infer(spk_audio_prompt=str(ref_audio), text=str(payload.get("text") or ""), output_path=str(out_path), verbose=False)
    data = out_path.read_bytes()
    try:
        out_path.unlink()
    except Exception:
        pass
    return data, {"reference_audio": str(ref_audio), "voice_preset": voice_preset}


def _higgs_audio_v3(payload: dict) -> tuple[bytes, dict]:
    import torch
    import torchaudio
    from transformers import AutoModelForCausalLM, AutoTokenizer

    bundle = SERVICE_MODEL_CACHE.get("higgs_audio_v3")
    repo = os.environ.get("EZ_HIGGS_AUDIO_V3_MODEL", "multimodalart/higgs-audio-v3-tts-4b-transformers")
    if bundle is None:
        tokenizer = AutoTokenizer.from_pretrained(repo, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(repo, trust_remote_code=True, torch_dtype=torch.bfloat16).to("cuda").eval()
        bundle = {"tokenizer": tokenizer, "model": model}
        SERVICE_MODEL_CACHE["higgs_audio_v3"] = bundle
    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    ref_audio, ref_text, voice_preset, _, _ = _resolve_voice_reference(payload, "higgs_audio_v3")
    with torch.inference_mode():
        if ref_audio is None:
            wav = model.generate_speech(
                str(payload.get("text") or ""),
                tokenizer,
                temperature=float(payload.get("temperature") or 0.7),
                top_p=float(payload.get("top_p") or 0.95),
            )
        else:
            ref_wav, ref_sr = torchaudio.load(str(ref_audio))
            if ref_wav.ndim == 2 and ref_wav.shape[0] > 1:
                ref_wav = ref_wav.mean(dim=0, keepdim=True)
            wav = model.generate_speech(
                str(payload.get("text") or ""),
                tokenizer,
                reference_audio=ref_wav,
                reference_sample_rate=ref_sr,
                reference_text=ref_text or DEFAULT_REF_TEXT,
                temperature=float(payload.get("temperature") or 0.7),
                top_p=float(payload.get("top_p") or 0.95),
            )
    wav_arr = wav if isinstance(wav, np.ndarray) else wav.detach().cpu().float().numpy()
    sample_rate = int(model.config.sample_rate)
    return _wav_bytes(wav_arr, sample_rate), {"sample_rate": sample_rate, "reference_audio": str(ref_audio or ""), "voice_preset": voice_preset}


RUNNERS = {
    "qwen_tts": _qwen_tts,
    "voxcpm2": _voxcpm2,
    "indextts2": _indextts2,
    "higgs_audio_v3": _higgs_audio_v3,
}


def _enabled_engines() -> set[str]:
    raw = os.environ.get("EZ_TTS_ENABLED_ENGINES", "qwen_tts")
    enabled = {item.strip() for item in raw.split(",") if item.strip()}
    return enabled & set(RUNNERS)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class TTSHandler(BaseHTTPRequestHandler):
    server_version = "EZTTS/0.1"

    def do_GET(self):
        if self.path == "/health":
            enabled = _enabled_engines()
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "engines": sorted(enabled),
                    "disabled_engines": sorted(set(RUNNERS) - enabled),
                    "voice_presets": sorted(VOICE_PRESETS),
                    "loaded": sorted(SERVICE_MODEL_CACHE),
                },
            )
            return
        _json_response(self, 404, {"ok": False, "detail": "not found"})

    def do_POST(self):
        if self.path != "/tts":
            _json_response(self, 404, {"ok": False, "detail": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            engine = str(payload.get("engine") or "qwen_tts").strip()
            enabled = _enabled_engines()
            if engine not in RUNNERS:
                raise ValueError(f"unknown engine: {engine}")
            if engine not in enabled:
                raise ValueError(f"engine is not enabled in current service: {engine}")
            if not str(payload.get("text") or "").strip():
                raise ValueError("text is empty")
            seed = _coerce_seed(payload.get("seed"))
            _apply_seed(seed)
            started = time.perf_counter()
            wav_bytes, meta = RUNNERS[engine](payload)
            elapsed = time.perf_counter() - started
            headers = {
                "X-EZ-TTS-Engine": engine,
                "X-EZ-TTS-Elapsed": f"{elapsed:.4f}",
            }
            if meta.get("sample_rate"):
                headers["X-EZ-TTS-Sample-Rate"] = meta["sample_rate"]
            if seed is not None:
                headers["X-EZ-TTS-Seed"] = seed
            if meta.get("voice_preset"):
                headers["X-EZ-TTS-Voice-Preset"] = meta["voice_preset"]
            _wav_response(self, wav_bytes, headers)
        except ValueError as exc:
            _json_response(self, 400, {"ok": False, "detail": str(exc)})
        except FileNotFoundError as exc:
            _json_response(self, 400, {"ok": False, "detail": str(exc)})
        except Exception as exc:
            _json_response(
                self,
                500,
                {"ok": False, "detail": str(exc), "traceback": traceback.format_exc(limit=8)},
            )

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    host = os.environ.get("EZ_TTS_HOST", "0.0.0.0")
    port = int(os.environ.get("EZ_TTS_PORT", "18210"))
    print(f"EZ TTS service listening on {host}:{port}", flush=True)
    ReusableThreadingHTTPServer((host, port), TTSHandler).serve_forever()


if __name__ == "__main__":
    main()
