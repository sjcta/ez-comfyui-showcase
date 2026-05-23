"""
modules/config.py — 常量定义 + 节点分类表。

Ez ComfyUI v4.0 重构。
集中管理所有常量、分类表、状态映射。
"""

from typing import ClassVar


class NodeCategory:
    """节点分类表 — 在此处添加新节点即可自动适配进度计算。"""

    SAMPLER: ClassVar[set[str]] = {
        "KSampler",
        "KSamplerAdvanced",
        "SamplerCustom",
        "SamplerCustomAdvanced",
        "FluxSampler",
    }

    UPSCALE: ClassVar[set[str]] = {
        "ImageUpscaleWithModel",
        "SeedVR2VideoUpscaler",
    }

    FREE: ClassVar[set[str]] = {
        "SaveImage",
        "PreviewImage",
        "PrimitiveBoolean",
        "PrimitiveFloat",
        "PrimitiveInt",
        "PrimitiveString",
    }

    WEIGHT_1: ClassVar[set[str]] = {
        "CLIPTextEncode",
        "CLIPTextEncodeFlux",
        "TextEncodeQwenImageEditPlus",
        "VAEEncode",
        "VAEDecode",
        "EmptyLatentImage",
        "EmptySD3LatentImage",
        "EmptyFlux2LatentImage",
        "ConditioningZeroOut",
        "ConditioningSetTimestepRange",
        "FluxGuidance",
        "ImageScaleBy",
        "ImageScale",
        "ImageCompositeMasked",
        "LoadImage",
        "LoadVideo",
        "GetVideoComponents",
        "CreateVideo",
        "JoinImageWithAlpha",
    }

    LOADER: ClassVar[set[str]] = {
        "UNETLoader",
        "UNETLoaderGGUF",
        "CLIPLoader",
        "DualCLIPLoader",
        "CLIPVisionLoader",
        "VAELoader",
        "UpscaleModelLoader",
        "LoraLoader",
        "LoraLoaderModelOnly",
        "NunchakuZImageDiTLoader",
        "SeedVR2LoadDiTModel",
        "SeedVR2LoadVAEModel",
    }

    FREE_RUNTIME: ClassVar[set[str]] = {
        "BasicGuider",
        "KSamplerSelect",
        "RandomNoise",
        "Flux2Scheduler",
    }


class ModelGroup:
    """工作流模型分组 — 控制实例亲和性路由。"""

    GROUPS: ClassVar[list[tuple[str, list[str]]]] = [
        ("flux2-klein", ["flux2_klein", "flux2-klein", "flux-2-klein"]),
        ("flux2-dev", ["flux2_dev", "flux2-dev", "flux.2-dev"]),
        ("nunchaku", ["nunchaku"]),
        ("z-image-turbo", ["z-image-turbo", "z_image_turbo", "z-image", "z-xxx", "z_xxx"]),
        ("seedvr", ["seedvr"]),
        ("i2i-firered", ["firered", "fire-red"]),
        ("i2i-qwen", ["i2i_qwen", "i2i-qwen"]),
    ]

    @staticmethod
    def extract_model_group(workflow_name: str) -> str:
        """从工作流文件名中提取模型组名。

        Args:
            workflow_name: 工作流文件名（含路径或纯文件名）。

        Returns:
            匹配的模型组名，若无匹配则返回原文件名（降级为精确匹配）。
        """
        lower = workflow_name.lower()
        for group, keywords in ModelGroup.GROUPS:
            for kw in keywords:
                if kw in lower:
                    return group
        return workflow_name  # unknown → exact match fallback


# ── ComfyUI 节点 → 可读状态映射 ────────────────────────────────────────

NODE_STATUS_MAP: dict[str, str] = {
    "NunchakuZImageDiTLoader": "加载 DiT 模型...",
    "UNETLoader": "加载 UNet 模型...",
    "SeedVR2LoadDiTModel": "加载 SeedVR2 模型...",
    "DualCLIPLoader": "加载双 CLIP...",
    "CLIPLoader": "加载 CLIP...",
    "CLIPVisionLoader": "加载 CLIP Vision...",
    "VAELoader": "加载 VAE...",
    "UpscaleModelLoader": "加载超分模型...",
    "UNETLoaderGGUF": "加载 GGUF 模型...",
    "LoraLoader": "加载 LoRA...",
    "ModelSamplingAuraFlow": "配置采样策略...",
    "ModelSamplingFlux": "配置 Flux 采样...",
    "CLIPTextEncode": "编码提示词...",
    "TextEncodeQwenImageEditPlus": "编码提示词...",
    "CLIPTextEncodeFlux": "编码 Flux 提示词...",
    "ConditioningZeroOut": "处理条件...",
    "ConditioningSetTimestepRange": "设置时间步范围...",
    "EmptySD3LatentImage": "准备潜空间...",
    "EmptyLatentImage": "准备潜空间...",
    "KSampler": "采样中...",
    "KSamplerAdvanced": "高级采样中...",
    "SamplerCustom": "自定义采样中...",
    "SamplerCustomAdvanced": "高级采样中...",
    "VAEDecode": "解码图像...",
    "VAEEncode": "编码图像...",
    "ImageUpscaleWithModel": "超分辨率放大...",
    "SeedVR2VideoUpscaler": "超分辨率放大...",
    "ImageScaleBy": "图像缩放...",
    "ImageScale": "图像缩放...",
    "ImageCompositeMasked": "合成图像...",
    "LoadVideo": "加载视频...",
    "GetVideoComponents": "解析视频...",
    "CreateVideo": "创建视频...",
    "SaveVideo": "保存视频...",
    "SaveImage": "保存图像...",
}
