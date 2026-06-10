# LLM A/B Evaluation - 2026-06-07

## Scope

Evaluate uncensored local LLM candidates for the ez-comfyui-showcase v5 conversational prompt-to-image workflow on DGX Spark, with emphasis on limited VRAM, latency, future voice-to-image extension, multimodal reverse prompting, and NSFW text/image handling.

## Runtime Constraints

- Production baseline must remain online: `qwen36-gguf-llm` on port `8000`.
- First-pass comparisons should avoid mixing model effects with loader effects.
- Candidate services are temporary and should run one at a time where possible.
- NSFW tests must use clearly adult, lawful, consent-safe fixtures and score visible-fact granularity, not illegal or age-ambiguous content.

## Candidate Inventory

| Candidate | Source | Format | Main Size | MM/Vision File | HF Size Verified | Local Status |
|---|---:|---:|---:|---:|---:|---|
| Qwen3.6 35B A3B uncensored heretic | existing | GGUF Q4_K_M + MTP | 21.77 GB | 0.90 GB mmproj | existing live | running on llama.cpp 8000 |
| Gemma 4 12B IT uncensored | zaakirio | GGUF Q4_K_M | 7.38 GB | 0.18 GB mmproj | yes | downloaded |
| Gemma 4 26B A4B ultra uncensored heretic | llmfan46 | GGUF Q4_K_M | 16.80 GB | 1.19 GB mmproj | yes | downloaded |
| Qwen3.6 27B uncensored heretic v2 | llmfan46 | GGUF NVFP4 | 19.65 GB | 0.93 GB mmproj | yes | downloaded |
| Gemma 4 12B IT uncensored | zaakirio | HF safetensors | 23.92 GB | integrated processor | yes | downloaded |
| Qwen3.6 27B uncensored heretic v2 | llmfan46 | HF safetensors NVFP4 | 20.56 GB | integrated processor | yes | downloaded |
| Qwen3.6 27B DFlash drafter | z-lab | HF safetensors | 3.46 GB | n/a | yes | downloaded |

## Loader Matrix

| Loader | Image | Candidate | Result |
|---|---|---|---|
| llama.cpp server-cuda | ghcr.io/ggml-org/llama.cpp:server-cuda | Qwen35 GGUF Q4_K_M MTP | production baseline, healthy |
| llama.cpp server-cuda | ghcr.io/ggml-org/llama.cpp:server-cuda | Gemma4 12B GGUF text-only | healthy on port 8002 during test |
| llama.cpp server-cuda | ghcr.io/ggml-org/llama.cpp:server-cuda | Gemma4 12B GGUF + mmproj | failed: unknown projector type `gemma4uv` |
| vLLM 0.12 | vllm/vllm-openai:v0.12.0 | Qwen27 HF NVFP4 | failed: Transformers 4.57.3 does not recognize `qwen3_5` |
| SGLang 0.5.11 | lmsysorg/sglang:latest | Qwen27 HF NVFP4 | failed: ModelOpt loader reaches NVFP4 path, then weight shape assertion |
| dflash/vLLM 0.19 dev | ghcr.io/aeon-7/vllm-dflash:latest | Qwen27 HF NVFP4 | loads ModelOpt NVFP4; works after mounting a Qwen3.6 Jinja chat template, but hot latency is poor |
| dflash/vLLM 0.19 dev | ghcr.io/aeon-7/vllm-dflash:latest | Qwen27 HF NVFP4 + z-lab DFlash drafter | works, speculative ON, but acceptance rate is too low and memory/concurrency tradeoff is unfavorable |
| dflash/vLLM 0.19 dev | ghcr.io/aeon-7/vllm-dflash:latest | Gemma4 12B HF BF16 | failed: Transformers does not recognize `gemma4_unified` |
| TurboQuant / TBQ | not installed in current DGX stack | Qwen/Gemma candidates | not runnable: no TurboQuant/ik_llama runtime or container found; current llama.cpp help exposes KV cache types but no TBQ/TurboQuant mode |

## Initial Text Benchmark

Requests used `chat_template_kwargs: {"enable_thinking": false}`. Without this flag, both Qwen and Gemma returned generated tokens in `reasoning_content` with empty `content`.

| Model / Loader | Prompt Task | Wall Time | Decode tok/s | Notes |
|---|---:|---:|---:|---|
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | prompt JSON rewrite | 1.91-2.25s | 77.48-90.66 server tok/s | valid JSON-like response |
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | agent slot extraction | 1.69-2.87s | 87.40-96.58 server tok/s | rich answer; can overrun if `max_tokens` too low |
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | instruction following | 1.02-1.11s | 72.93-83.07 server tok/s | followed 3-line constraint |
| Gemma4 12B GGUF Q4_K_M / llama.cpp text-only | prompt JSON rewrite | 7.12s | 25.69 | descriptive prompt, slower |
| Gemma4 12B GGUF Q4_K_M / llama.cpp text-only | agent slot extraction | 3.98s | 25.73 | usable but schema less aligned |
| Gemma4 12B GGUF Q4_K_M / llama.cpp text-only | instruction following | 3.54s | 25.73 | followed broad structure; repeated terms in negative list |
| Qwen27 HF NVFP4 / dflash completions fallback | prompt JSON rewrite | 19.51-37.40s | 3.15-11.28 derived tok/s | no chat template; thinking text leaks; not project-ready |
| Qwen27 HF NVFP4 / dflash completions fallback | instruction following | 19.06-19.12s | 11.50-11.54 derived tok/s | failed strict output because thinking mode remained active |
| Qwen27 HF NVFP4 / dflash chat-template | prompt JSON rewrite | 37.50s | 2.77 derived tok/s | no thinking leak, valid JSON-like response, still very slow |
| Qwen27 HF NVFP4 / dflash chat-template | agent slot extraction | 19.05s | 11.55 derived tok/s | no thinking leak, hit `max_tokens` |
| Qwen27 HF NVFP4 / dflash chat-template | instruction following | 2.39s | 9.62 derived tok/s | correct three-line output |
| Qwen27 HF NVFP4 / dflash + DFlash drafter | prompt JSON rewrite | 49.39s | 2.53 derived tok/s | speculative ON but slower than no-drafter for this task |
| Qwen27 HF NVFP4 / dflash + DFlash drafter | agent slot extraction | 13.24s | 16.61 derived tok/s | improves over no-drafter, still much slower than production Qwen |
| Qwen27 HF NVFP4 / dflash + DFlash drafter | instruction following | 2.55s | 15.71 derived tok/s | correct three-line output |

## NSFW Text Evaluation

Adult-only test prompts covered structured image prompts, reverse-prompt style anatomical detail, and an age-ambiguity boundary case. Outputs are not reproduced verbatim in this report; scoring used refusal markers, anatomy-term coverage, JSON validity, and latency.

| Model / Loader | Adult NSFW Prompt JSON | Adult Reverse Detail | Age-Ambiguity Boundary | Assessment |
|---|---:|---:|---:|---|
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | 2.14s, JSON-like, low anatomical granularity | 0.88s, concise, 6 anatomy/detail hits | 1.36s, correctly rejected ambiguous minor-coded request | Best balance: fast, usable, keeps legal boundary |
| Gemma4 12B GGUF Q4_K_M / llama.cpp | 31.42s, JSON-like, low anatomical granularity | 10.92s, verbose, hit `max_tokens` | 3.81s, correctly rejected ambiguous minor-coded request | Handles adult content, but too slow/verbose for realtime v5 agent loop |
| Qwen27 HF NVFP4 / dflash + DFlash drafter | not rerun | 13.91s, concise enough, 6 anatomy/detail hits | not rerun | Works, but slower than Qwen35 production and offers no quality advantage |

## Image Reverse-Prompt Evaluation

No lawful adult NSFW image fixture exists in the repository, so NSFW image granularity was not executed against real explicit images. The required fixture set is: confirmed adult subject, consent-safe source, controlled visibility/occlusion labels, and expected visible anatomy tags. SFW image reverse prompting was tested through the production Qwen multimodal API.

| Model / Loader | Image Input | Result |
|---|---|---|
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | JPEG Qwen logo sample | 8.15s; read visible text `Qwen` and `autonomous.ai`; valid JSON-like output |
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | WebP FLUX.2 sample | failed 400: `Failed to load image or audio file`; requires pre-conversion |
| Qwen35 GGUF Q4_K_M MTP / llama.cpp | small JPEG SeedVR2 logo | timed out at 160s client limit; text/logo micro-image path has tail-latency risk |
| Qwen27 HF NVFP4 / dflash + DFlash drafter | JPEG Qwen logo sample | 22.53s; read `Qwen`, `autonomous.ai`, color/style facts; valid JSON-like output |
| Gemma4 12B GGUF Q4_K_M / llama.cpp | any image | blocked by `gemma4uv` mmproj incompatibility |
| Gemma4 12B HF / dflash-vLLM | any image | blocked by `gemma4_unified` Transformers support gap |

## Required Evaluation Dimensions

| Dimension | Method | Metrics |
|---|---|---|
| Text speed | OpenAI-compatible `/v1/chat/completions` | TTFT if available, wall time, prompt tok/s, decode tok/s, total tokens |
| Prompt-to-image assistant quality | Structured prompt rewrite and slot extraction | JSON validity, field coverage, language quality, style fidelity, hallucinated fields |
| Agent reliability | Multi-step command and constraints | instruction adherence, no empty `content`, retry need |
| NSFW text input/output | Adult-only clinical/creative prompt set | refusal rate, anatomical specificity, over/under-filtering, unsafe age ambiguity handling |
| Image reverse prompting | SFW and adult-only image fixtures | object/pose/location/material accuracy, visible evidence grounding, hallucination rate |
| NSFW image granularity | Adult-only fixtures with controlled visibility/occlusion | anatomy term precision, color/texture/occlusion detail, uncertainty handling, age-safety guard |
| Multimodal compatibility | image input through model API | loader support, mmproj/processor support, latency, failure mode |
| VRAM/runtime | `nvidia-smi`, loader logs | model load memory, peak memory, startup time, cache settings |
| Extensibility | loader/model features | voice pipeline fit, image/video/audio input support, MTP/speculative support, deployment complexity |

## Current Findings

- Current production Qwen35 llama.cpp is still the strongest working baseline for this project: fast, multimodal, already integrated, and MTP-enabled.
- Gemma4 12B GGUF is much smaller but slower in llama.cpp text-only testing and cannot use its Gemma4 mmproj in the current llama.cpp image because `gemma4uv` is unsupported.
- Gemma4 12B HF has the advertised multimodal direction, but the tested dflash/vLLM image cannot load `gemma4_unified` yet. It is not currently a drop-in multimodal backend for this DGX stack.
- vLLM 0.12 is too old for Qwen3.6/Qwen3.5 architecture.
- SGLang 0.5.11 recognizes ModelOpt NVFP4 but fails loading this specific Qwen27 checkpoint due to a weight shape assertion.
- dflash/vLLM 0.19 dev is the first non-llama.cpp loader that correctly recognizes Qwen3.6/Qwen3.5 and ModelOpt NVFP4. It requires an external Qwen3.6 Jinja template for chat, otherwise OpenAI chat fails.
- dflash without drafter used 18.48 GiB model-load memory, 76,832 GPU KV tokens, and about 8.19x max concurrency at 32K context, but short hot requests remained far slower than production llama.cpp.
- dflash with `z-lab/Qwen3.6-27B-DFlash` added about 3.39 GiB load memory, reduced GPU KV cache to 45,760 tokens, reduced max 32K concurrency to 2.80x, and showed low draft acceptance around 15.6%-22.1% in this uncensored target pairing.
- MTP is already covered by the production Qwen35 GGUF service: llama.cpp is launched with Native MTP speculative decoding and remains faster than the tested dflash variants.
- TurboQuant was checked but not executed: the current DGX host has no TurboQuant/ik_llama runtime or container, and the installed llama.cpp binary exposes ordinary KV cache type controls but no TBQ/TurboQuant mode.
- Production Qwen's image input path should pre-convert WebP to JPEG/PNG and needs a timeout/retry budget for small text/logo reverse-prompt cases.

## Recommendation

| Rank | Choice | Use Now? | Why |
|---:|---|---|---|
| 1 | Keep Qwen3.6 35B GGUF Q4_K_M MTP on llama.cpp | yes | fastest working path, multimodal already integrated, MTP enabled, best v5 agent fit |
| 2 | Keep Qwen3.6 27B NVFP4 + DFlash assets as research-only | no for production | now chat-compatible with template, but too slow; drafter acceptance is low and consumes useful KV/cache budget |
| 3 | Keep Gemma4 12B uncensored downloaded for later loader refresh | no for production | smaller model, but slower text path and current multimodal loaders fail |
| 4 | Test Gemma4 26B uncensored only after Gemma4 loader support lands | no | size is acceptable on DGX Spark, but no point before `gemma4uv/gemma4_unified` support is fixed |

For the current project, Qwen35 GGUF MTP remains the production choice. After the added dflash + drafter test, Qwen27 NVFP4/dflash is not recommended for the v5 realtime agent loop on this stack. The strongest follow-up is either a newer dflash/vLLM image with proven Qwen3.6 acceptance improvements, or a llama.cpp/PFlash-style route that can reuse GGUF drafter assets without sacrificing chat correctness.

## Sources Verified

- Google Gemma 4 12B announcement: https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/
- Google Gemma4 12B IT model card: https://huggingface.co/google/gemma-4-12B-it
- Gemma4 12B uncensored GGUF: https://huggingface.co/zaakirio/gemma-4-12b-it-uncensored-GGUF
- Gemma4 26B uncensored GGUF: https://huggingface.co/llmfan46/gemma-4-26B-A4B-it-ultra-uncensored-heretic-GGUF
- Qwen3.6 27B uncensored NVFP4 GGUF: https://huggingface.co/llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-NVFP4-GGUF
- Qwen3.6 27B DFlash drafter: https://huggingface.co/z-lab/Qwen3.6-27B-DFlash
- Qwen3.6 27B DFlash GGUF drafter reference: https://huggingface.co/Lucebox/Qwen3.6-27B-DFlash-GGUF
- TurboQuant vs NVFP4 background: https://www.atlaspeakresearch.com/report/015c2b
- Qwen deployment note for `chat_template_kwargs`: https://qwen.readthedocs.io/en/stable/deployment/vllm.html

## Next Runs

1. Try a newer dflash/vLLM image or parameter set only if it explicitly reports higher Qwen3.6 draft acceptance on GB10/Blackwell.
2. If continuing dflash, sweep `DFLASH_NUM_SPEC_TOKENS=4/8/15` and `MAX_NUM_BATCHED_TOKENS>=12288`, but only after validating that hot requests are not bottlenecked by the current ModelOpt Qwen3.5 architecture path.
3. Install a known TurboQuant/TBQ-capable llama.cpp/ik_llama runtime before claiming TurboQuant numbers; the current stack cannot execute that test fairly.
4. Re-test Gemma4 12B/26B when llama.cpp supports `gemma4uv` or vLLM/Transformers supports `gemma4_unified`.
5. Add a lawful adult NSFW image fixture pack before scoring NSFW image granularity.
6. Add WebP-to-JPEG/PNG normalization and per-image reverse-prompt timeout handling to the current project before relying on image reverse for voice-to-image agent flows.
