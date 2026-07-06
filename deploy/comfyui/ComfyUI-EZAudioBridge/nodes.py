from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
import wave

import numpy as np
import torch


DEFAULT_TTS_URL = os.environ.get("EZ_TTS_SERVICE_URL", "http://127.0.0.1:18210/tts")
LANGUAGE_OPTIONS = [
    "auto",
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Spanish",
    "Italian",
    "Arabic",
    "Burmese",
    "Danish",
    "Dutch",
    "Finnish",
    "Greek",
    "Hebrew",
    "Hindi",
    "Indonesian",
    "Khmer",
    "Lao",
    "Malay",
    "Norwegian",
    "Polish",
    "Swahili",
    "Swedish",
    "Tagalog",
    "Thai",
    "Turkish",
    "Vietnamese",
    "四川话",
    "粤语",
    "吴语",
    "东北话",
    "河南话",
    "陕西话",
    "山东话",
    "天津话",
    "闽南话",
]
VOICE_INPUT_MODE_OPTIONS = [
    "自动",
    "本地预设 Speaker（CustomVoice）",
    "本地参考音频克隆（Base）",
    "原生默认",
    "上传参考音频克隆",
    "上传参考音频克隆（本地）",
    "文字描述音色（0样本）",
    "声音设计（无参考音频）",
    "可控克隆（参考音频+控制指令）",
    "极致克隆（参考音频+逐字稿）",
    "官方发音人（DashScope）",
]
QWEN_CUSTOM_VOICE_OPTIONS = [
    "Vivian / 明亮年轻女声（中文）",
    "Serena / 温暖温柔女声（中文）",
    "Uncle_Fu / 低沉成熟男声（中文）",
    "Dylan / 北京青年男声（中文北京话）",
    "Eric / 成都男声（四川话）",
    "Ryan / 节奏感男声（英文）",
    "Aiden / 美式阳光男声（英文）",
    "Ono_Anna / 轻快日语女声（日语）",
    "Sohee / 温暖韩语女声（韩语）",
]
LEGACY_QWEN_DASHSCOPE_VOICE_OPTIONS = [
    "Cherry / 芊悦",
    "Serena / 苏瑶",
    "Ethan / 晨煦",
    "Chelsie / 千雪",
    "Momo / 茉兔",
    "Vivian / 十三",
    "Moon / 月白",
    "Maia / 四月",
    "Kai / 凯",
    "Nofish / 不吃鱼",
    "Bella / 萌宝",
    "Jennifer / 詹妮弗",
    "Ryan / 甜茶",
    "Katerina / 卡捷琳娜",
    "Aiden / 艾登",
    "Bodega / 西班牙语-博德加",
    "Alek / 俄语-阿列克",
    "Dolce / 意大利语-多尔切",
    "Sohee / 韩语-素熙",
    "Ono Anna / 日语-小野杏",
    "Lenn / 德语-莱恩",
    "Sonrisa / 西班牙语拉美-索尼莎",
    "Emilien / 法语-埃米尔安",
    "Andre / 葡萄牙语欧-安德雷",
    "Radio Gol / 葡萄牙语巴-拉迪奥·戈尔",
    "Eldric Sage / 精品百人-沧明子",
    "Mia / 精品百人-乖小妹",
    "Mochi / 精品百人-沙小弥",
    "Bellona / 精品百人-燕铮莺",
    "Vincent / 精品百人-田叔",
    "Bunny / 精品百人-萌小姬",
    "Neil / 精品百人-阿闻",
    "Elias / 墨讲师",
    "Arthur / 精品百人-徐大爷",
    "Nini / 精品百人-邻家妹妹",
    "Ebona / 精品百人-诡婆婆",
    "Seren / 精品百人-小婉",
    "Pip / 精品百人-调皮小新",
    "Stella / 精品百人-美少女阿月",
    "Li / 南京-老李",
    "Marcus / 陕西-秦川",
    "Roy / 闽南-阿杰",
    "Peter / 天津-李彼得",
    "Eric / 四川-程川",
    "Rocky / 粤语-阿强",
    "Kiki / 粤语-阿清",
    "Sunny / 四川-晴儿",
    "Jada / 上海-阿珍",
    "Dylan / 北京-晓东",
]
VOICE_PRESET_OPTIONS = [
    *QWEN_CUSTOM_VOICE_OPTIONS,
    "自动按语言选择参考样本",
    "Auto / 自动按语言选择参考样本",
    "Qwen参考音频克隆（中文样本）",
    "Qwen参考音频克隆（英文样本）",
    "Chinese Reference / 中文默认参考样本",
    "English Reference / 英文默认参考样本",
    "VoxCPM2无参考原生生成",
    "VoxCPM2文字描述音色（0样本）",
    "VoxCPM2参考音频克隆（中文样本）",
    "VoxCPM2参考音频克隆（英文样本）",
    "IndexTTS2参考音频克隆（中文样本）",
    "IndexTTS2参考音频克隆（英文样本）",
    "Higgs Zero-shot原生生成",
    "Higgs参考音频克隆（中文样本）",
    "Higgs参考音频克隆（英文样本）",
    "自定义参考音频",
    "Custom Reference Audio / 自定义参考音频",
    "auto",
    "zh_aishell",
    "en_qwen_clone",
    "custom_reference",
    *LEGACY_QWEN_DASHSCOPE_VOICE_OPTIONS,
]


def _wav_bytes_to_audio(data: bytes) -> dict:
    with wave.open(io.BytesIO(data), "rb") as wav:
        channels = int(wav.getnchannels() or 1)
        sample_rate = int(wav.getframerate() or 24000)
        sample_width = int(wav.getsampwidth() or 2)
        frames = wav.readframes(wav.getnframes())
    if sample_width == 2:
        arr = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        arr = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        arr = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV sample width: {sample_width}")
    if channels > 1:
        arr = arr.reshape(-1, channels).T
    else:
        arr = arr.reshape(1, -1)
    waveform = torch.from_numpy(arr).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": sample_rate}


def _decode_tts_response(content: bytes, content_type: str) -> bytes:
    if "application/json" not in str(content_type or "").lower():
        return content
    payload = json.loads(content.decode("utf-8"))
    if payload.get("ok") is False:
        raise RuntimeError(payload.get("detail") or payload.get("error") or "TTS service failed")
    audio_b64 = payload.get("audio_base64") or payload.get("wav_base64")
    if not audio_b64:
        raise RuntimeError("TTS service JSON did not include audio_base64")
    return base64.b64decode(audio_b64)


class EZ_TTS_Service:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "service_url": ("STRING", {"default": DEFAULT_TTS_URL}),
                "engine": (["qwen_tts", "voxcpm2", "indextts2", "higgs_audio_v3"], {"default": "qwen_tts"}),
                "text": ("STRING", {"multiline": True, "default": "今天我们测试本地语音合成服务。"}),
                "language": ("STRING", {"default": "Auto / 自动"}),
                "voice_input_mode": (VOICE_INPUT_MODE_OPTIONS, {"default": "自动"}),
                "voice_preset": (VOICE_PRESET_OPTIONS, {"default": "Serena / 温暖温柔女声（中文）"}),
                "voice_description": ("STRING", {"multiline": True, "default": ""}),
                "reference_audio": ("STRING", {"default": ""}),
                "reference_text": ("STRING", {"multiline": True, "default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.95, "min": 0.05, "max": 1.0, "step": 0.01}),
                "speed": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.05}),
            },
            "optional": {
                "voice_style_custom": ("STRING", {"multiline": True, "default": ""}),
                "cfg_value": ("FLOAT", {"default": 2.0, "min": 1.0, "max": 3.0, "step": 0.1}),
                "inference_timesteps": ("INT", {"default": 10, "min": 4, "max": 30, "step": 1}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "synthesize"
    CATEGORY = "语音TTS"

    def synthesize(
        self,
        service_url: str,
        engine: str,
        text: str,
        language: str,
        voice_input_mode: str,
        voice_preset: str,
        voice_description: str,
        reference_audio: str,
        reference_text: str,
        seed: int,
        temperature: float,
        top_p: float,
        speed: float,
        voice_style_custom: str = "",
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
    ):
        service_url = str(service_url or DEFAULT_TTS_URL).strip()
        text = str(text or "").strip()
        if not service_url:
            raise RuntimeError("service_url is empty")
        if not text:
            raise RuntimeError("text is empty")
        body = json.dumps(
            {
                "engine": engine,
                "text": text,
                "language": language,
                "voice_input_mode": voice_input_mode,
                "voice_preset": voice_preset,
                "voice_description": voice_description,
                "voice_style_custom": voice_style_custom,
                "reference_audio": reference_audio,
                "reference_text": reference_text,
                "seed": int(seed),
                "temperature": float(temperature),
                "top_p": float(top_p),
                "speed": float(speed),
                "cfg_value": float(cfg_value),
                "inference_timesteps": int(inference_timesteps),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            service_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                content_type = response.headers.get("Content-Type", "")
                wav_bytes = _decode_tts_response(response.read(), content_type)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", "ignore").strip()
            raise RuntimeError(detail or f"TTS service HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"TTS service request failed: {exc}") from exc
        return (_wav_bytes_to_audio(wav_bytes),)


NODE_CLASS_MAPPINGS = {
    "EZ_TTS_Service": EZ_TTS_Service,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "EZ_TTS_Service": "EZ TTS Service",
}
