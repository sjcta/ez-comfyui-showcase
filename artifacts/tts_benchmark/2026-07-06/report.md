# DGX Spark TTS Benchmark - 2026-07-06

## 结论

当前四个已实际生成同一中文文案样本的候选里，优先级是：

1. Qwen3-TTS-0.6B-Base: 速度最快，热态 RTF 约 0.60，适合实时对话默认 TTS。
2. IndexTTS2: 速度第二，热态 RTF 约 0.92，适合需要情绪/配音控制的场景，但部署依赖更重。
3. VoxCPM2: 能力完整，48 kHz 输出、无样本 voice design、5-30 秒参考音频建议清晰；但当前普通 PyTorch 路线在 DGX Spark 上较慢，需另测 Nano-vLLM/vLLM-Omni 才可能成为高并发方案。
4. Higgs Audio TTS v3 BF16 transformers port: 质量潜力强，但冷启动和依赖成本最高，热态仍慢于 Qwen/Index，且本次 transformers port 加载出现 `audio_head.weight` missing warning，当前不适合作为默认生产 TTS。

`Reza2kn/Higgs-Audio-v3-TTS-4bit-NVFP4` 不纳入速度排名，因为它不是完整 drop-in runtime。模型卡明确说 current vanilla Transformers 不能实例化 Higgs 架构，需要 SGLang-Omni 或自定义 loader。本机实测 `AutoConfig.from_pretrained()` 也失败于 `model_type=higgs_multimodal_qwen3` 未识别。

## 测试条件

- 机器: DGX Spark / NVIDIA GB10
- 容器: `nvcr.io/nvidia/pytorch:25.04-py3`
- Python: 3.12
- Torch: `2.7.0a0+79aa17489c.nv25.04`
- 测试文本: `今天我们测试本地语音合成服务的速度、稳定性和自然度，看看哪一个更适合实时对话场景。`
- 文本长度: 41 个中文字符
- 参考音频: `reference/qwen_clone.wav`
- 参考文本: `Okay. Yeah. I resent you. I love you. I respect you. But you know what? You blew it! And thanks to you.`
- 每个引擎: 3 轮生成，记录平均值；同时记录去掉第 1 轮 warm-up 后的热态均值。

## 速度结果

| 引擎 | 冷加载 | 3 轮平均生成 | 热态平均生成 | 3 轮 RTF | 热态 RTF | 3 轮 chars/s | 采样率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3-TTS-0.6B-Base | 59.28s | 6.19s | 4.27s | 0.824 | 0.603 | 7.81 | 24 kHz |
| IndexTTS2 | 35.76s | 8.70s | 7.51s | 1.093 | 0.919 | 4.87 | 22.05 kHz |
| VoxCPM2 | 23.81s | 11.35s | 11.58s | 1.640 | 1.609 | 3.62 | 48 kHz |
| Higgs Audio TTS v3 BF16 | 411.66s | 22.86s | 10.64s | 2.996 | 1.297 | 2.86 | 24 kHz |

RTF 小于 1 表示快于实时。按热态速度排序: Qwen3-TTS > IndexTTS2 > Higgs BF16 > VoxCPM2。

## 客观音频健康指标

| 引擎 | 平均音频时长 | RMS | Peak | Clip | 静音比例 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3-TTS-0.6B-Base | 7.36s | 0.0468 | 0.4538 | 0.0000% | 8.42% |
| IndexTTS2 | 8.01s | 0.0953 | 0.9480 | 0.0002% | 12.05% |
| VoxCPM2 | 6.93s | 0.0985 | 0.8909 | 0.0000% | 9.86% |
| Higgs Audio TTS v3 BF16 | 7.93s | 0.0746 | 0.5603 | 0.0000% | 7.36% |

这些只是自动指标，不能替代人工听感。最终音质请以本目录下每个模型 3 个样本人工听后确认。

## 音色与克隆能力

| 引擎 | 音色克隆 | 推荐样本长度 | 是否支持无样本生成/设计 | 预设音色数量 | 备注 |
| --- | --- | --- | --- | ---: | --- |
| Qwen3-TTS-0.6B-Base | 支持 | 官方强调 3 秒快速克隆 | 当前 0.6B Base 不做无样本克隆；Qwen3-TTS 另有 VoiceDesign/CustomVoice 路线 | CustomVoice 官方 9 个 premium timbres，本次 Base 模型无固定预设 | Apache-2.0；速度最佳 |
| VoxCPM2 | 支持 reference-only cloning，也支持 reference+transcript Hi-Fi cloning | 官方建议 5-30 秒 | 支持 voice design，无参考音频可按描述生成新声音；这不是克隆某个真实人 | 理论上按描述生成，不是固定数量 | Apache-2.0；48 kHz；当前 PyTorch 路线慢 |
| IndexTTS2 | 支持 zero-shot voice cloning | 官方 README 未给固定秒数；建议先用 3-10 秒干净单人语音 | 不支持真正无样本克隆 | 无固定预设 | License 不是简单 Apache；部署依赖最麻烦 |
| Higgs Audio TTS v3 BF16 | 支持 reference clip + optional transcript | 官方未给固定秒数；建议先用 5-15 秒干净单人语音，提供转写会更稳 | 支持无参考普通 TTS/控制标签；克隆仍需参考音频 | 非固定数量，靠参考音频/控制标签 | Research/non-commercial；当前 BF16 port 冷启动很重 |
| Higgs Audio TTS v3 NVFP4 | 有量化权重，不是完整 runtime | 取决于 SGLang-Omni/custom loader | 取决于 runtime | 不适用 | 当前不可直接 Transformers 加载，需另做引擎集成 |

## 资源占用

DGX Spark / GB10 的 `nvidia-smi --query-gpu=memory.used,memory.total` 返回 `[N/A]`，本轮无法得到传统离散 GPU 的精确显存数字。因此这里报告可实测的模型磁盘 footprint 和部署资源判断。

| 引擎 | 本地模型/缓存占用 | 显存结论 |
| --- | ---: | --- |
| Qwen3-TTS-0.6B-Base | 2.4 GB | 最轻；适合默认常驻 |
| VoxCPM2 | 4.7 GB | 官方文档标注约 8 GB VRAM；当前可跑但速度慢 |
| IndexTTS2 | 11 GB | 中高；依赖和 checkpoint 最重之一 |
| Higgs Audio TTS v3 BF16 + tokenizer | 9.5 GB | 高；冷加载约 412 秒，不适合轻量实时默认 |
| Higgs Audio TTS v3 NVFP4 | HF 仓库约 2.06 GB | 理论更省资源，但当前不是完整 runtime，不能直接得出显存/速度收益 |

## 样本

- Reference: `reference/qwen_clone.wav`
- Qwen3-TTS: `results/qwen_tts/qwen_tts_round1.wav`, `round2.wav`, `round3.wav`
- VoxCPM2: `results/voxcpm2/voxcpm2_round1.wav`, `round2.wav`, `round3.wav`
- IndexTTS2: `results/indextts2/indextts2_round1.wav`, `round2.wav`, `round3.wav`
- Higgs Audio TTS v3 BF16: `results/higgs_audio_v3/higgs_audio_v3_round1.wav`, `round2.wav`, `round3.wav`

## 部署建议

默认实时语音助手先用 Qwen3-TTS-0.6B-Base。它不是所有维度最强，但在 DGX Spark 上速度优势明显，且 3 秒克隆能力足够快速试音色。

如果后续重点是“可描述音色、无需样本、更多中文方言”，单独测 VoxCPM2 的 Nano-vLLM 或 vLLM-Omni 路线；当前 PyTorch 路线不能代表它的最佳速度。

如果重点是“情绪配音、可控朗读”，保留 IndexTTS2 作为配音引擎候选，但不建议作为实时默认。

Higgs Audio TTS v3 先不要进默认生产。BF16 路线冷启动太重，NVFP4 路线目前缺完整 runtime。等 SGLang-Omni/custom loader 在 ARM64 DGX Spark 上可稳定跑通后，再补测 NVFP4 3 轮速度和样本。

## 主要来源

- Qwen3-TTS: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base and https://github.com/QwenLM/Qwen3-TTS
- VoxCPM2: https://huggingface.co/openbmb/VoxCPM2 and https://voxcpm.readthedocs.io/en/latest/usage_guide.html
- IndexTTS2: https://huggingface.co/IndexTeam/IndexTTS-2 and https://github.com/index-tts/index-tts
- Higgs Audio TTS v3 BF16 transformers port: https://huggingface.co/multimodalart/higgs-audio-v3-tts-4b-transformers
- Higgs Audio TTS v3 upstream/SGLang/vLLM notes: https://huggingface.co/bosonai/higgs-tts-3-4b
- Higgs Audio TTS v3 NVFP4 artifact: https://huggingface.co/Reza2kn/Higgs-Audio-v3-TTS-4bit-NVFP4
