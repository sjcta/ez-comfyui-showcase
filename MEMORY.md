# ez-comfyui-showcase Memory

## 2026-06-18

- 初始化项目本地 `AGENTS.md` / `MEMORY.md`，因为根目录缺失且 `~/.codex/templates/` 不存在。
- 前端缓存版本需要同时维护 `static/index.html` 与 `static/js/module_loader.js`，否则浏览器可能继续加载旧模块。
- 快速出图尺寸控件按当前工作流读取 `multiple/maxSide/maxPixels/inputMax`；用户点击比例按钮后，手动改宽或高都要同步另一侧，并保持比例、像素倍数和模型上限。
- Vision Lab 按完全独立子项目落在 `vision-lab/`，规划文档统一放 `docs/vision_lab/`；本地验证端口为 API `19100`、Web `19101`，默认 UI 按手机端标准，专业设置只放进专业模式面板。
- Vision Lab 本地部署包应只包含 `vision-lab/` 与 `docs/vision_lab/`，通过 `vision-lab/start_local.py` 一键启动 Web/API，不依赖 Node.js、ComfyUI 或 ez-comfyui-showcase。
- Vision Lab 已接入 Mac mini nginx 1313：`https://imdjj.cn:1313/visionlab/` → `127.0.0.1:19101`，`/visionlab/api/v1/` → `127.0.0.1:19100/api/v1/`；LaunchAgent 标签为 `cn.imdjj.visionlab`，配置在 `vision-lab/deploy/cn.imdjj.visionlab.plist`。
- Vision Lab UI 设计稿中的手机外壳、圆角设备边框、时间、Wi-Fi、信号、电量等属于 mockup 展示背景，不进入页面实现；Web 应按真实手机浏览器页面渲染，只保留应用自身 header/content/bottom nav。
- Vision Lab 前端已按功能拆分为 `apps/web/src/js/core`、`ui`、`features`，样式按 `apps/web/src/styles/base`、`layout`、`modules`、`pages` 分层；页面入口为 `apps/web/src/js/main.js`，不再使用单体 `src/app.js`。
- Vision Lab 设置页已加入模型/API 管理：后端 `/api/v1/providers` 暴露 Mock、DGX Qwen OpenAI-compatible、自定义 Provider，`/api/v1/workflows` 暴露图片反推、提示词优化、Seedance 2.0 视频脚本三条本地工作流。
- Vision Lab 后端新增 OpenAI-compatible Provider runtime：`/api/v1/runs` 会按当前 Provider 分流，非 mock Provider 失败会返回真实错误而不是静默降级；`/api/v1/provider-test` 测试当前 Base URL/Model/API Key，DGX Qwen 当前状态为 `needs_key`（无有效 key 时 chat 返回 401）。
- Vision Lab 上传图片会写入独立目录 `vision-lab/.local/assets/images` 并返回 image_id；API Key 只存 `sessionStorage`，不写入持久化 localStorage。
- Vision Lab Provider 判定只允许 `provider.id == "mock"` 走 mock；custom/DGX 即使 model 为空也必须返回 `provider_not_configured`，不能按空 model 降级到 `vision-lab-mock`。
- Vision Lab “继续优化”必须调用后端 `/api/v1/runs`，通过当前 Provider runtime 生成新版；前端不得直接拼接“新版优化”来制造假结果。
- Vision Lab 手机端自适应默认应全宽铺满真实移动浏览器；只有桌面鼠标环境才把 `.app-frame` 收成 430px 预览，避免手机内置浏览器出现左右黑边或二次套壳。
- Vision Lab 默认 Provider 已切换为 `EZ ComfyUI VLM Adapter`：这是 Vision Lab 自己的独立 Provider 预设，只通过 HTTP Adapter 调用 ez-comfyui `/api/upload-image`、`/api/prompt/interrogate`、`/api/prompt/optimize`；它不读取、不同步、不覆盖 ez-comfyui 内部 Provider 配置。同域时只转发 `ez_comfyui_token`/`ez_comfyui_csrf` cookie；真实反推验证返回 `provider_mode=ez-comfyui-api`、`ez_provider=llm-qwen36-gguf-q4-mtp-vision`。
- Vision Lab 转发 ez-comfyui 登录态时必须白名单化 Cookie，只允许 `ez_comfyui_token` 与 `ez_comfyui_csrf` 进入下游 Provider；不能把同域其它业务 Cookie 原样转发。

## 2026-06-19

- 用户明确纠正：Vision Lab 必须完全独立，不能把 ez-comfyui 的会员系统、反推系统、Cookie、HTTP API 或数据库作为运行时依赖；上一版 `EZ ComfyUI VLM Adapter` 方向废弃。Vision Lab 可以复用 ez-comfyui 已验证的提示词策略、模型入口参数和结果归一化经验，但默认运行时改为自己的注册/登录、SQLite 用户/会话、独立资产目录和直接 OpenAI-compatible VLM Provider。
- Vision Lab 默认 VLM 使用从 ez-comfyui 活跃 LLM 配置迁移出的独立 `.env.local`：`VISIONLAB_LLM_BASE_URL=https://imdjj.cn:8000/v1`、`VISIONLAB_VLM_MODEL=qwen36-gguf-q4-mtp`；密钥只在 `.env.local` 中，不提交。Qwen3/3.6 调用必须加 `/no_think` 与 `chat_template_kwargs.enable_thinking=false`，否则响应容易只有 `reasoning_content`、`content` 为空或完整生成超时。
- Vision Lab 复查后修正：前端不得在 `/api/v1/runs` 失败时本地伪造生成结果；mock 只能由 `provider.id == "mock"` 触发；有图片预览但上传失败时必须阻止图片反推并提示重传；个人中心不得展示未接入的项目/额度假入口，账号状态来自 Vision Lab 自己的 users 表 `plan` 字段。
- Vision Lab 图片上传状态必须以后端返回的 `image_id` 为准，不能因为本地 `FileReader` 预览图已出现就显示“已上传”。上传中 badge 显示“上传中”、反推按钮禁用；拿到 `imageAsset.image_id` 后才显示“已上传”并允许反推；上传失败时显示“上传失败/重新上传图片”。
- Vision Lab 上传预览必须完整显示用户原图，`#previewImage` 使用 `object-fit: contain` 而不是 `cover`；不要为了填满预览框裁切图片。
- Vision Lab 点击图片反推/提示词优化/视频脚本后，结果区必须立刻进入 pending 状态并清掉旧结果；真实 `/api/v1/runs` 成功后再切换为 V2 结果，失败时在同一结果区显示错误，避免用户误以为输出没有刷新。
- Vision Lab 上传预览里的“换图”按钮没有独立功能，已移除；需要换图时点击预览区域重新选择图片，左上角 `×` 只负责清除当前图片。
- Vision Lab 专业模式面板必须按当前创作模式动态渲染：图片反推不显示 Seedance 等视频模型，不显示手动比例；图片比例跟随上传图片本身，目标只保留通用图像/GPT Image/Qwen Image/Flux 等图像适配项。
- Vision Lab 提示词/脚本语言是高频选项，必须放在 Studio 主界面随时切换；专业模式里不再放英文提示词和质量信息，只保留 JSON 这类结构化输出开关。
- Vision Lab Mock 技术上可正常工作，但只作为内部开发/接口验证 Provider；用户侧模型/API 管理只展示“系统内置”和“自定义 OpenAI-compatible”，历史选中过 mock/dgx-qwen 时应自动迁移回系统内置。

## 2026-06-22

- Vision Lab Studio 交互已改为图片优先：默认必须先上传一张参考图，再选择反推提示词、提示词优化或故事脚本；三种任务都必须携带 Vision Lab 自己的 `image_id`，后端会把图片作为 OpenAI-compatible 多模态 `image_url` 一并发送。
- Vision Lab 详细程度从旧“专业模式”弹窗提升为主界面全局控件：标准=自然语言，高级=JSON 语义结构，专家=JSON 专业维度且内容不重复；切换任务时详细程度不能丢失。
- Vision Lab 高级/专家结果主卡必须直接展示 JSON；后端不能把模型 JSON 拆回自然语言字段作为主结果。
- Vision Lab 默认 Studio 不再显示目标模型、手动比例、动作强度、英文/JSON/质量复选框、提示词语言或专业模式入口；提示词优化只显示文案风格，故事脚本只显示镜头语言和视频长度。
- Vision Lab 三种主任务的图片必需校验必须早于 Provider 分流；即使 provider 是 mock，也不能无 `image_id` 跑通。
- Vision Lab 继续优化应沿用原结果的 `source_image_id`，用户清空当前图片预览后也不能丢失该结果的原始图片上下文。
- Vision Lab 结果解析要容忍模型返回 Markdown 标题，例如 `视频脚本：标题`；短标题后面的镜头正文必须作为主结果展示，不能只截取标题。
- Vision Lab 当前系统内置 Provider 仍是独立 OpenAI-compatible 入口 `https://imdjj.cn:8000/v1` + `qwen36-gguf-q4-mtp`，不调用 ez-comfyui API/会员/Cookie/数据库；真实 API 验证已跑通 reverse/optimize/video 三类 operation。
- Vision Lab 默认 Studio 要用最少选项完成首次生成：用户上传图片并选择任务后固定产出标准自然语言结果；高级/专家不再是生成前选项，而是结果卡片后的加强动作，并沿用原图、原任务和当前结果生成新版本。
- Vision Lab 图片反推高级/专家 JSON 现在对齐 ez-comfyui 已验证的图片反推模板，但运行时仍完全独立：高级固定输出 `visual_spec`、`visual_evidence`、`keyword_prompt`、`negative_prompt`；专家固定输出 `visual_spec`、`visual_evidence`、`expert_plan`、`fact_cards`、`expert_observations`、`expert_review`、`keyword_prompt`、`negative_prompt`。不要再使用 `图片概述`、`反推提示词`、`画面判断`、`复刻结构`、`专业视角`、`专家补充`、`professional_angles`、`angle`、`content`、`prompt_zh`、`prompt_en`、`semantic_structure` 等旧字段。
- Vision Lab 结果卡住可能是前端历史写入失败而非模型未返回：localStorage 保存 base64 原图会触发 quota exceeded，阻断 UI 从 pending 切到结果。历史记录只能保存资产 URL 和压缩文本，`/runs` 前端要有硬超时兜底。
- Vision Lab 图片反推的语言选择应放在生成前轻量选项中，只保留 `中文 / 英文` 单选；不要在一次反推结果里同时输出中英双语提示词。
- WhatDreamsCost LTX Director 2.0 升级后，`LTXDirector` 的 `motion_guide_data` 是输出 5，`frame_rate` 是输出 6；`LTXDirectorGuide` 要接 `motion_guide_data` 和 `model`，采样后需要用 `LTXDirectorCropGuides` 裁掉 appended guide latent，再进 upsampler/最终 decode。
- LTX Director 快速出图可真实稳定暴露的输入是全局提示词、宽高、时长、帧率、种子、负面提示词、阶段步数/denoise、`epsilon`、图像缩放和参考图压缩；视频轨、音频轨、IC-LoRA、retake、timeline save/load 依赖 ComfyUI Director 时间线 UI 和上传文件契约，当前应隐藏，等 quick form 有 timeline/媒体上传控件后再放开。
- LTX Director 的“导演模式”入口不要放在 prompt actions 里，避免和“图片反推/提示词优化/中英切换/清除”挤压手机端按钮；应作为 `详细参数` 折叠区里的 Director 参数块打开浮层面板。
- Boogu NVFP4 走 Comfy-Org 单文件模型路线时，CLIPLoader type 必须是 `boogu`，Edit 使用 `TextEncodeBooguEdit` 的 `images.image_1`，Turbo 是单独 T2I 工作流；`boogu-project/ComfyUI-Boogu` 的 GitHub workflow 可作为参数参考，但它本身要求完整 `models/boogu` 目录和官方 `boogu` Python 包。

## 2026-06-23

- 本机 Codex CLI 通过全局 npm 包 `@openai/codex` 安装，更新命令是 `npm install -g @openai/codex@latest` 或 `codex update`；更新后若 `codex app-server daemon version` 显示 `cliVersion` 新而 `appServerVersion` 旧，需要完全重启 Codex/远程会话让 app-server 换到新版本。
- Boogu Image Edit 不能只靠工作流默认 `ImageScaleToMaxDimension.largest_size=1024`；用户期望参考上传图比例并自动使用允许最高长边。现在 `i2i_boogu_image_edit_nvfp4.json` 默认改为 2048，后端 `_sync_i2i_reference_dimensions` 会把旧提交里的 `41::largest_size=1024` 覆盖到配置上限，并记录 `__boogu_i2i_source_size` / `__boogu_i2i_auto_size`。
- Boogu Image Edit 当前 NVFP4 工作流不是官方 `BOOGULoadEditPipeline -> BOOGUGenerate(input_image)` 路径，而是 Comfy-Org 单文件模型 + `TextEncodeBooguEdit` + VAEEncode + `KSampler`；`3::denoise=1` 会让参考 latent 接近全重绘，2K 尺寸修正只解决分辨率/比例，不解决参考图一致性。要官方级跟图，需要另注册官方 Boogu Edit workflow 并部署 `models/boogu/Boogu-Image-0.1-Edit` 与官方 `boogu` 包。
- 按用户纠正，`i2i_boogu_image_edit_nvfp4.json` 最终应走官方 README 推荐的 Native ComfyUI 路线，而不是 legacy `BOOGULoadEditPipeline` 原始模型目录：保留已部署的 `boogu_image_edit_nvfp4.safetensors`、`qwen3vl_8b_fp8_scaled.safetensors`、`flux1_vae_bf16.safetensors`，图结构为 `UNETLoader + CLIPLoader(type=boogu) + VAELoader + TextEncodeBooguEdit + EmptySD3LatentImage + KSampler + VAEDecode + SaveImage`。参考图直接进入 `TextEncodeBooguEdit.images.image_1`，不再用 VAEEncode 参考图当 img2img latent；后端 `_sync_boogu_i2i_reference_dimensions` 应按官方 demo 推荐分辨率档选择输出尺寸。
- 已清理 DGX 上误下载的 legacy 原始模型目录 `/home/sjcta/software/ComfyUI-Project/ComfyUI/models/boogu/Boogu-Image-0.1-Edit`，释放约 15G；Native NVFP4 workflow 仍使用 `/ComfyUI/models/diffusion_models/boogu_image_edit_nvfp4.safetensors`。
- 用户在官方 `https://demo-edit.boogu.org/` 验证同提示词 2K 输出正常，说明 Boogu Edit 的主要差异不是“2K 过大”或“prompt 约束不够硬”。官方 demo 暴露 `Enable Thinking(enable_pe)`、`text_guidance_scale=4.0`、`image_guidance_scale=1.0`、`num_inference_steps=50` 和 1K/1.5K/2K 推荐分辨率；ComfyUI `TextEncodeBooguEdit` 节点 schema 不直接暴露 `enable_pe`，参考 latent 目前按官方上限 `1024^2` 处理，早先试过的 DGX `2048^2` reference latent 实验值已撤回。
- Boogu Image Edit 的 `image_guidance_scale` 不能只作为 UI 数字或 KSampler 参数处理；官方双 guidance 需要额外的 no-reference/drop-all 模型预测分支。本地工作流已新增 `BooguImageGuidance` 节点接在 `ModelSamplingAuraFlow` 与 `KSampler` 之间，DGX `nodes_boogu.py` 用 sampler CFG patch 实现 `image_guidance_scale > 1.0` 时的 no-reference 分支，默认值保持官方 `1.0`。
- Boogu Image Edit 的 `Enable Thinking` 是 true/false 布尔参数，配置类型应使用现有 `toggle`，这样 quick form 会渲染为“开启/关闭”开关；不要用普通 `checkbox`。
- 用户提供并测试通过的 Boogu Image Edit FP8 Scaled API workflow 已作为本地基准新增 `i2i_boogu_image_edit_fp8_scaled.json`：模型用 `diffusion_models/boogu_image_edit_fp8_scaled.safetensors`，VAE 按当前系统替换为 `vae/flux1_vae_bf16.safetensors`，CLIP 保持 `text_encoders/qwen3vl_8b_fp8_scaled.safetensors` 且 `CLIPLoader.type=boogu`。DGX 原本未下载 FP8 edit 模型，已从 `Comfy-Org/Boogu-Image` 下载到 diffusion_models，文件大小 `10313835784`；DGX 缺 `DF_Get_image_size`，本地 workflow 移除此节点并继续由后端 Boogu 自动尺寸逻辑写入 latent 宽高。
- Boogu FP8 Scaled Edit 的附件 API workflow 里 flat `TextEncodeBooguEdit.inputs["images.image_1"]` 才是正确的 `COMFY_AUTOGROW_V3` 输入形态；之前 nested `images: {"image_1": ["32", 0]}` 只是绕过了 DGX Qwen3VL 崩溃，但 ComfyUI 裸 API prompt 不会把它注入 `TextEncodeBooguEdit.images`，结果是成功出图却完全不带参考图。EZ FP8/NVFP4 edit workflow 必须使用 flat `images.image_1`，并确保 config 不暴露 `36::images`/`111::images` 这类错误字段。
- Boogu FP8 Scaled Edit 生成结果和参考图差异过大时，优先检查 `SamplerCustom.model` 是否还直连 `UNETLoader`。旧 FP8 workflow 只把 `ModelSamplingAuraFlow` 接给 `BasicScheduler`，采样器实际使用裸 UNET，且没有 `BooguImageGuidance`；这会削弱 Boogu edit 的参考图约束。修复后应是 `UNETLoader -> ModelSamplingAuraFlow -> BooguImageGuidance -> SamplerCustom.model`，并在 config 暴露 `45::image_guidance_scale`。1-step DGX smoke `3730d7bd-de61-4c92-a62a-70d325a31051` 已验证该结构可执行。
- Flux2 Dev 图生图最近两条失败任务都是 `i2i_flux2_dev_turbo_q4km.json` 提交到 DGX B `/prompt` 时 400：远端 `ImageScaleToTotalPixels` 已把 `resolution_steps` 变成 required，旧 workflow 节点 41 只传 `image/upscale_method/megapixels`。修复方式是在 Flux2 Dev i2i 三个变体 `i2i_flux2_dev_turbo_q4km/q5km/q6k` 的节点 41 固定补 `resolution_steps: 1`；Qwen Edit v2511 同一时间任务成功，不属于这次失败根因。

## 2026-06-24

- PC lightbox 图片缩放要和移动端 pinch 分流：移动端继续用 `.lb-stage.lb-image-zoomed` fullscreen stage；PC 控制条使用 `.lb-stage.lb-image-control-zoomed`，只缩放/平移 `#lbImg` 与 `#lbFullImg`，stage 尺寸和位置保持不变。前端静态改动仍要同步 `static/index.html`、`static/js/module_loader.js` 和 `tests/test_css_loading.py` 的 cache 版本。
- Boogu FP8 Scaled Edit 如果结构已是 `UNETLoader -> ModelSamplingAuraFlow -> BooguImageGuidance -> SamplerCustom.model` 但输出仍明显偏离参考图，要先查 `generations.params` 里的实际提交值；2026-06-24 最新失败样例仍使用 `steps=25`、`cfg=3.5`、`negative_prompt=""`，和官方 demo 默认 `steps=50`、`text guidance=4.0`、官方 negative instruction 不一致。修复时 workflow JSON、`data/wf_configs`、SQLite `workflow_editor_config` 必须一起同步。
- Boogu 官方 demo 的 2K 推荐分辨率不是按原图精确尺寸贴 `2048^2` 上限，而是固定 bucket：例如 9:16 是 `1458x2592`，2:3 是 `1664x2496`。FP8 Scaled Edit 不能继续走 `BOOGU_I2I_SOURCE_SIZE_WORKFLOWS`，否则 1536x2720 参考图会提交 1536x2720 而不是官方 bucket，容易在 50 steps 下重写背景和构图。
- DGX `comfy_extras/nodes_boogu.py` 的 `BooguImageGuidance` 去 reference 分支必须支持 ComfyUI raw conditioning 的 `[tensor, metadata]` 结构，并移除 metadata 里的 `reference_latents`；只检查 dict / `model_conds.ref_latents` 会让 `image_guidance_scale > 1` 的 no-reference/drop-all 分支基本无效。远端原文件备份在 `nodes_boogu.py.codex-bak-20260624-image-guidance-conditioning`。
- 用户再次提供并验证过的 Boogu FP8 Scaled API workflow 表明：EZ 不应继续把 `BooguImageGuidance`、官方 bucket、50 steps/CFG 4 强套到 `i2i_boogu_image_edit_fp8_scaled`。按附件最小兼容到 DGX 时只应改运行时不支持的节点：`JjkText -> Text`、`Get Image Size -> GetImageSize`，并把 VAE 映射到现有 `flux1_vae_bf16.safetensors`；`TextEncodeBooguEdit` 参考图输入必须保留附件的 flat `images.image_1`。附件拓扑保持 `SamplerCustom.model` 直连 `UNETLoader`、`BasicScheduler.model` 接 `ModelSamplingAuraFlow`、25 steps、CFG 3.5、空 negative、latent 宽高链接原图尺寸。`ae.sft` 与 `flux1_vae_bf16.safetensors` 结果像素相同，VAE 不是主因。
- Comfy-Org/Boogu-Image 的官方 ComfyUI VAE 目录只有 `vae/flux1_vae_bf16.safetensors`，HF LFS oid 为 `0c0c8ac49850d6bd174107d4001685f4f6c876768a1c84dde751f2aed69f46ce`、大小 `167664710`。DGX `/ComfyUI/models/vae/flux1_vae_bf16.safetensors` 的 sha256 与该 oid 完全一致；用同 seed/同 latent 分别跑 `flux1_vae_bf16.safetensors` 和 `ae.sft`，输出像素完全相同，因此 Boogu FP8 跟图问题不是 VAE 文件缺失或 VAE 版本错误。
- Boogu FP8/NVFP4 Edit 跟图失败的根因已查明：DGX `comfy/text_encoders/qwen35.py` 缺少 Qwen3VL DeepStack 返回值支持，正确 flat `images.image_1` 会在 `qwen3vl.py` 里报 `too many values to unpack`；改成 nested `images` 虽能跑通，但参考图没有进入 `TextEncodeBooguEdit`，带参考图和无参考图同 seed 输出曾像素完全相同。已在 DGX 修复 `qwen35.py` DeepStack，恢复 FP8/NVFP4 edit workflow 的 flat `images.image_1`，重启 `comfyui-a.service`/`comfyui-b.service`，并用 25-step smoke 验证参考图 latent 确实进入模型。
- Comfy-Org/Boogu-Image 官方 `loras/` 目录目前只有 `boogu_image_turbo_lora_rank_128_bf16.safetensors`，用于 Turbo 路线；Edit 是独立的 `boogu_image_edit_bf16/fp8_scaled/nvfp4.safetensors` diffusion model。当前 Boogu Image Edit workflow 不加载 Turbo LoRA 是正常的，不是 edit 偏离参考图的原因。
- 修复参考图链路后，NVFP4 实测能基本还原原图内容但仍会过度修改部分背景；FP8 最新任务 `job_1782295149290_5791` 也已正常使用参考图，但和本地 ComfyUI 仍有轻微差异。当前两个 edit workflow 参数并不等价：FP8 是 `SamplerCustom + dpmpp_2m/simple + 25 steps + cfg 3.5 + enable_thinking=true + 空 negative + 1536x2720 原尺寸`；NVFP4 是 `KSampler + euler/simple + 50 steps + cfg 4 + image_guidance_scale=1 + enable_thinking=false + 官方 negative + 1458x2592 bucket`。后续校准应先做同 prompt/同 seed/同尺寸/同采样参数的 A/B，而不是继续猜 LoRA/VAE。
- 按用户提供并验证过的 Boogu Image Edit API workflow，`i2i_boogu_image_edit_fp8_scaled.json` 与 `i2i_boogu_image_edit_nvfp4.json` 已统一为同构参数：`SamplerCustom + dpmpp_2m/simple + 25 steps + cfg 3.5 + denoise=1 + shift=3.16 + 空 negative + GetImageSize 原图尺寸 + TextEncodeBooguEdit.images.image_1`，两者只差 `UNETLoader.unet_name`。用户可见参数也统一为参考图、编辑提示词、种子、步数、Text guidance scale、denoise、shift、文件名前缀；不再暴露 synthetic `Enable Thinking` 或 `Image guidance scale`，避免偏离用户本地 ComfyUI workflow。
- 回收站清空当前只覆盖 `generations.deleted_at` 对应的历史正式产物：会删 `data/outputs` 下的 `image_path`、`thumb_path`/推测缩略图、简单 `params` 字符串里的未复用 `image*`/`upload` 输入引用，并删除 SQLite 行与 `data/history/history.json` 记录；不会全量清理 `data/outputs/.remote_downloads` 中转缓存、`data/input` 里未被简单字段识别的上传/反推预处理文件、音频字段、JSON 数组引用如 `__bernini_refs`、远端 ComfyUI 原始输出或空目录。
- Krea 2 官方 `Comfy-Org/Krea-2` 当前没有 Base/Raw MXFP8；Base 文生图使用 `diffusion_models/krea2_raw_fp8_scaled.safetensors`，Turbo 文生图使用 `diffusion_models/krea2_turbo_mxfp8.safetensors`，共同依赖 `text_encoders/qwen3vl_4b_fp8_scaled.safetensors`、`vae/qwen_image_vae.safetensors` 和 `CLIPLoader.type=krea2`。DGX ComfyUI 已补最小 Krea2 runtime 支持，`comfy/model_base.py` 的 Krea2 `extra_conds` 必须写 `out["c_crossattn"]`；Krea2 官方 `cfg=0` 表示禁用 CFG/只走正向条件，但 ComfyUI `KSampler.cfg=0` 会偏向 uncond/negative 并生成彩色乱码，Turbo workflow 应固定 `cfg=1` 且隐藏该字段，采样器用 `euler/simple` 对齐官方 flow ODE。Base/Raw 使用 CFG 时 negative 分支必须是空 `CLIPTextEncode`，不能用 `ConditioningZeroOut`，否则会出现噪点/花图；A/B 已验证 `euler_cfg1` 和 `er_sde_cfg1` 能正常出狐狸图，`euler_cfg0` 仍乱码，Base 空 negative 后 512 图正常。

## 2026-06-25

- 两个放大 workflow 已部署为 `FlashVSR_SeedVR2_8K.json` 与 `i2i_z_image_tile_seedvr2_upscale_v2.json`：本地要同步 `data/workflows/DGX Spark/`、`data/wf_configs/`、`data/wf_meta.json` 和 SQLite `workflow_meta`/`workflow_editor_config`；远端文件放在 `/home/sjcta/software/ComfyUI-Project/workflow/api/upscale/`。FlashVSR 依赖远端 custom node `ComfyUI-FlashVSR_Ultra_Fast`，且 `models/FlashVSR` 与 `models/FlashVSR-v1.1` 都需要完整下载；Z-Image 附件里的隐藏 `KSampler.ddim/ddim_uniform` 和 `CLIPLoader.type=flux` 在 DGX 上应改为 `euler/simple/lumina2`。
- DGX `comfyui_ttp_toolset/TTP_toolsets.py` 的 `TTP_Image_Tile_Batch` no-tile 分支曾返回 Python list，导致 `easy imageBatchToImageList` 报 `'list' object has no attribute 'shape'`；已在远端补丁为直接返回 IMAGE tensor，备份为 `TTP_toolsets.py.codex-bak-20260625-tile-batch-single-image`。FlashVSR 最小 smoke 不要用单边小于 64 的图，`scale=2` 时 48x64 会触发内部 latent 尺寸不匹配；64x64 square smoke 可通过。
- `FlashVSR_SeedVR2_8K.json` 随机生成失败时先查 `node_errors["59"]`：2026-06-25 实例失败是 `FlashVSRNode.seed` 收到全局随机 seed `192115955086502232`，超过远端节点 max `1125899906842624`，不是模型或远端服务故障。后端应按 `FlashVSRNode` / `FlashVSRNodeAdv` 的 seed 上限归一化随机 seed，并在提交前对旧 job 字段再做一次保险归一化。
- `FlashVSR_SeedVR2_8K.json` 第二次真实失败 `prompt_id=80378a6a-b1b5-4b23-96ba-fb517724efc1` 不是 FlashVSR/SeedVR2 失败，而是 `TTP_Image_Assy` 拼接失败：输入图 `1206x2622` 经 workflow 变成 `3840x8192`，`TTP_Image_Tile_Batch(tile_width=1024)` 产生 4 列且横向 overlap 为 85，旧 `70::padding=64` 导致 blend crop 为 `(65, 1024)` vs `(64, 1024)`。将 `70::padding` 改为 `1024` 后，同图远端重跑 `prompt_id=0c9c0695-89db-4330-90e2-1efdd5ad527b` 成功输出 1 张图。
- `FlashVSR_SeedVR2_8K.json` 继续失败时检查是否是旧失败卡片重试：`job_1782374325738_9753` 仍提交了 `fields["70::padding"]=64`，说明 retry 继承了旧 job 的隐藏字段，覆盖了当前 `/fields` 里的 `1024`。后端已改为提交/重试时刷新 hidden fields 为当前 workflow 默认值；隐藏字段是实现细节，不应作为用户意图从旧 job 继承。
- `FlashVSR_SeedVR2_8K.json` 出图完成但比例严重错误时，优先查是否仍用了旧 workaround `70::padding=1024`：真实 job `job_1782374887963_1201` 输入 `1206x2622`，输出变成 `3840x1024`，本质是远端 `TTP_Image_Assy` no-overlap 分支 `paste()` 不扩展画布，只保留第一行；同时旧 odd-overlap blend 会裁出 `65px` vs `64px`。最终修复不是保留 `1024` padding，而是把 workflow 恢复 `70::padding=64`，并在远端 `/home/sjcta/software/ComfyUI-Project/ComfyUI/custom_nodes/comfyui_ttp_toolset/TTP_toolsets.py` 修 `blend_tiles()` 奇数 overlap 裁剪和 `assemble_image()` 无 overlap 画布增长；备份为 `TTP_toolsets.py.codex-bak-20260625-odd-overlap-blend`、`TTP_toolsets.py.codex-bak-20260625-no-overlap-grow`。验证：TTP-only `prompt_id=8ec8b693-d08b-4780-b043-34e3b22c5384` 可把 `1963x2048` 拼回 `1963x2048`；完整 FlashVSR `prompt_id=6af3a90f-905a-4b8e-b72d-bd55afe9b752` 输出 `3840x8192`，比例轻微差异来自 `round_to_multiple=16`。
- `FlashVSR_SeedVR2_8K.json` 输出出现规则拼接线时优先查 `184::tile_width/tile_height` 是否仍为 `1024`：2026-06-26 真实 job `job_1782456179659_3588` 输出 `8192x5120`，正好是 `1024` 整数倍，远端 TTP tiler 计算 overlap 为 0，导致 `70::padding=64` 完全不参与融合，SeedVR2 独立处理的 8x5 个 tile 被硬拼回去。修复为 `184::tile_width=1152`、`184::tile_height=1152`、`70::padding=128`，让常见 8K 输出产生正 overlap：`8192x5120` 约横向 146px、纵向 160px；中尺寸 smoke `prompt_id=60abcfed-65e2-48ab-9847-278b524a62ed` 成功输出 `4096x2560`，规则网格消失。
- 放大 workflow 的出图卡片主标题不能让 `2K 放大` / `4K 放大` 这类分辨率推导覆盖 `workflow_meta.name`：例如 `i2i_z_image_tile_seedvr2_upscale_v2.json` 应显示 `Z-Image 分块重绘放大`。修复点包括后端 `infer_generation_label(..., fallback_label)` 接入 `_workflow_custom_display_name()`，以及前端 `history.js` 对旧 `prompt_preview` 的通用放大标签做兼容替换；有真实用户提示词时仍优先显示提示词。
- `i2i_klein_ttp_4k_upscale.json` 已从用户附件 `Klein+TTP 4K_api.json` 追加部署为 `Klein + TTP 4K 放大`：附件不能原样上 DGX，孤立 UI/清理节点 `MemoryCleaner`、`PreviewImage`、`Image Comparer (rgthree)`、`GetImageSize`、数学节点不在最终 SaveImage 输出链上，且远端缺 `Flux2-Klein-9B-True-v2-bf16.safetensors` 与 `f2k_9B_lcs_consist_20260415.safetensors`。部署版保留 24 个输出链节点，模型使用远端已有 `Flux2-Klein-9B-True-v2-fp8mixed.safetensors`、`qwen_3_8b.safetensors`、`flux2-vae.safetensors`、`f2k_9B_小志一致性（0.5-0.7）lcs_consist_0412预览版preview.safetensors`；本地同步 workflow/config/meta/SQLite，远端文件在 `/home/sjcta/software/ComfyUI-Project/workflow/api/upscale/i2i_klein_ttp_4k_upscale.json`。`/api/workflows/i2i_klein_ttp_4k_upscale.json/fields` 已验证，远端小图 smoke `prompt_id=6d0dd425-327d-47a5-a496-344b8a007e1b` 成功输出 `/home/sjcta/software/ComfyUI-Project/outputs/smoke/Klein_TTP_4K_smoke_00001_.png`，尺寸 `512x512`。
- `i2i_klein_ttp_4k_upscale.json` 颗粒感排查：用户实测 job `job_1782382372012_6808` 用输入 `3309x2535` 输出 `3840x2944`，实际字段为 `steps=4`、`cfg=1`、`denoise=1`、`target=3840`、提示词空；这些采样/TTP/缩放参数与原附件一致，颗粒感主要来自模型资产偏差。已将可恢复的 CLIP 从 `qwen_3_8b_fp8mixed.safetensors` 切回原附件的 `qwen_3_8b.safetensors`，并同步本地 workflow 与远端 `/workflow/api/upscale/`；full CLIP smoke `prompt_id=02881dba-c2c3-41e9-8cd0-5bb372bcee0d` 成功输出 `512x512`。当前仍与原附件不同的有效出图资产只有 `Flux2-Klein-9B-True-v2-bf16.safetensors` -> `Flux2-Klein-9B-True-v2-fp8mixed.safetensors`，以及 `f2k_9B_lcs_consist_20260415.safetensors` -> `f2k_9B_小志一致性（0.5-0.7）lcs_consist_0412预览版preview.safetensors`；远端目前缺这两个原始文件。

## 2026-06-26

- Ideogram4 uncen 两个失败任务 `job_1782407048951_8865`、`job_1782407100921_4071` 的根因是 DGX A 远端 `/home/sjcta/software/ComfyUI-Project/ComfyUI/comfy/text_encoders/ideogram4.py` 缺少 `te_qwen3vl` 与 `Ideogram4Qwen3VLTokenizer`，而当前 `comfy/sd.py` 的 `TEModel.QWEN3VL_8B` 分支会调用这两个导出；已追加兼容别名并备份为 `ideogram4.py.codex-bak-20260626-te-qwen3vl`，重启 `comfyui-a.service` 后通过 CLIPLoader。
- Ideogram4 画布模式重试时，如果旧 job 的 `24::text` 已是官方 JSON 且 `__user_prompt` 为空，后端不能再把整段 JSON 当普通 prompt 嵌进新 JSON；`_ideogram4_canvas_caption_from_shapes()` 已改为先识别并提取现有官方 caption，避免重复包裹导致画面描述膨胀。
- Ideogram4 uncen test 已真实跑通两种提交：提示词模式 `job_1782407516786_7688` 输出 `data/outputs/7ac22882/2026-06-26/ideogram4_uncen_test_0001.png`，画布模式 `job_1782407662252_4719` 输出 `data/outputs/7ac22882/2026-06-26/ideogram4_uncen_test_0002.png`；两张图均包含乡村树林/小路、河流、都市高楼、天空/太阳，画布模式未出现多余框线、分割线或辅助线。
- 用户实测 Ideogram 两张图“画面被分割得很碎”后确认：自然照片/写实场景不能给 object 元素保留 bbox，哪怕说明 bbox 只是 metadata 也会诱导 Ideogram 分区/拼贴；修复为只有 `layout/poster/graphic design` 和文字元素才保留 bbox，普通照片画布把对象合并成一个无 bbox 的连续场景描述。
- Ideogram 提示词里大量负向措辞如 `hidden`、`not visible frames`、`Do not draw rectangles/split-screen` 会增加安全占位图或反向诱导风险；照片画布 caption 改为正向表达 `seamless single-view realistic image`、`composition guidance`、`single continuous camera view`。修复后真实 smoke：提示词模式 `job_1782410151745_5098` 输出 `ideogram4_uncen_test_0007.png`，画布模式 `job_1782410180419_9199` 输出 `ideogram4_uncen_test_0008.png`，两张均为连续景观且无框线/分割。
- Vision Lab 图片反推专家模板中的姿态、风格和多视角信息应放入 ez-comfyui 专家团结构：`visual_spec.主体` 负责主体细节和人物骨架链，`expert_observations` 负责一维中文观点，`fact_cards` 负责可见证据来源，`expert_review` 负责内部复核。VLM-only 阶段仍不得编造精确关键点角度；如需真实坐标/角度，后续应接 OpenPose、MediaPipe Pose Landmarker 或 MMPose detector 后再让 VLM 转写。
- Vision Lab 图片反推高级模板不再使用旧的高信号复刻结构 `画面判断/复刻结构/生成控制`；用户最新要求是参考 ez-comfyui 中图片反推高级/专家的格式和内容模板，但高级用户结果也不能输出 `易错点与禁止项`、`不确定项`、`无/不可见/不适用` 这类会和正向识别内容混淆的信息。高级 `visual_spec` 可按 `画面总体概述、构图与镜头、主体拆解、空间关系与层次、重要物体细节、人物高精度分析（如有）、服装与材质（如有）、光线、颜色与色调、风格与质感、关键保留点、复刻注意点` 自适应组织；`negative_prompt` 只保留通用品质/结构瑕疵短语，不写 `睁眼/微笑/明亮暖光/清晰背景/现代数码感/高饱和度` 这类与 `keyword_prompt` 对立的图像语义。
- Vision Lab 如果用户上传 WebP/GIF 等非 JPEG/PNG 图片，Qwen OpenAI-compatible VLM 可能返回 `Failed to load image or audio file`；资产可保留原格式，但 `load_image_data_url()` 发给模型前应使用 macOS `sips` 转成 PNG data URL，避免下游解码失败。

## 2026-06-28

- Cowart Codex 插件已从 `https://github.com/zhongerxin/cowart.git` clone 到 `~/plugins/cowart`，personal marketplace 清单位于 `~/.agents/plugins/marketplace.json`，已通过 `codex plugin marketplace add ~` 与 `codex plugin add cowart@personal` 安装为 `cowart@personal` v0.1.3；新技能和 MCP 工具需要开启新对话后加载。
- Cowart 画布已按当前项目启动，默认 URL 为 `http://127.0.0.1:43217/`；画布数据写入项目内 `canvas/pages/<page-id>/cowart-canvas.json`，页面资产写入 `canvas/pages/<page-id>/assets`。
- Cowart 图标空白的根因是 tldraw 默认从 `https://cdn.tldraw.com/5.1.1/` 加载 icons/translations/fonts，当前内置浏览器无法加载该 CDN；修复为在 `~/plugins/cowart/public/tldraw-assets/5.1.1/` 放置官方 `@tldraw/assets@5.1.1` 资源，并在 `src/App.jsx` 给 `<Tldraw />` 传本地 `assetUrls`。

## 2026-06-29

- Vision Lab Studio 操作流已从旧单页工具面板重构为 `首页 → 输入页 → 结果页`：首页只保留 `图像反推` 与 `提示词优化` 两个主入口，视频提示词作为提示词优化内的 `optimize_video` pipeline；结果页默认只显示纯提示词，`标准/高级/专家` 与 `中文/英文` 切换会沿用原始输入重新调用模型，JSON 只作为结果页展示开关。
- Vision Lab 游客模式允许未登录调用 `/api/v1/runs` 与上传图片，前端本地每日 3 次试用计数并保存游客历史；登录用户生成后由 Vision Lab 独立 SQLite `history_items` 表自动保存，`GET/PATCH/DELETE /api/v1/history` 用于历史同步、收藏和删除。
- Vision Lab 后端反推结果统一以结构化 JSON 作为中间结果，`cards[0].content` 始终返回默认展示用纯提示词，完整结构放入 `metadata.structured_prompt_json`；图片反推仍强制图片，图片/视频提示词优化可纯文本或可选参考图。
- Vision Lab 真实浏览器验收覆盖注册、登录、上传、反推标准/高级/专家/英文/JSON、图片优化、视频优化、History、Templates、Settings/API、Profile、游客额度和 `https://imdjj.cn:1313/visionlab` 代理；验收中发现前端 `/runs` 90 秒超时早于后端 Provider 120 秒，已改为 130 秒，避免模型略慢时前端先 abort。
- Vision Lab 图片反推的默认纯提示词展示不能直接复用同一个 `keyword_prompt` 压平标准/高级/专家差异；标准保留短自然提示词，高级从 `visual_spec/visual_evidence` 提炼多维复刻提示词，专家从 `visual_spec/fact_cards/expert_observations/expert_review` 提炼控制型提示词，JSON 仍只保留在 `metadata.structured_prompt_json` 和结果页 JSON 开关中。
- Vision Lab 图片反推高级/专家默认纯提示词的首行必须直接是可复制 prompt，不能带 `复刻主提示词:`、`复刻目标:` 这类说明性标签；标签会污染用户复制到生图模型的提示词效果。
- Vision Lab 顶部 Logo 和底部 Studio 图标是“回到 Studio 首页”的全局导航，不只是切换到 studio panel；即使当前在图片反推/提示词结果页，也必须把 `currentStep` 重置为 `home` 并显示 `studioHome`。
- Vision Lab 图像反推/提示词优化的输入页应使用移动端 Composer 模式：文字输入框与参考图融合为一个输入框，左下 `+` 负责上传图片；无图时不显示大上传面板，上传后在输入框内展开完整预览并继续使用 `object-fit: contain`。
- OpenMontage 主线仓库是 `https://github.com/calesthio/OpenMontage`：它是 AGPL-3.0 的 agent-first 本地视频制作系统，核心可借鉴点是 `pipeline_defs` + Markdown skills + Python tools + Remotion/FFmpeg + 质量门禁；不建议直接并入 ez-comfyui，若评估应先独立 sandbox 试跑并注意 AGPL 与本地代码执行风险。

## 2026-06-30

- Lingzao skill 已从 `https://github.com/atian-create/lingzao-skill` 安装到 `/Users/ai/.agents/skills/lingzao`，当前版本 `0.1.65`；安装器初次 `--path .` 只拉了根文件，需在该 repo 中执行 `git sparse-checkout disable` 才能补齐 `scripts/`、`playbooks/`、`agents/`。当前本机尚无 `/Users/ai/.lingzao/config.json` 和 `/Users/ai/.lingzao/bin/lingzao`，因为 `scripts/setup.sh` 无 `lgz_` API Key 会交互式等待；拿到 Lingzao API Key 后再运行 `bash /Users/ai/.agents/skills/lingzao/scripts/setup.sh --base-url "https://lingzao.atian.vip" --api-key "lgz_xxx"`，并重启 Codex/开启新对话加载新 skill。
- 各类作图 skill 引入 ez-comfyui 时，不应把 Codex/Agent skill 直接塞进 ComfyUI workflow 或 custom node；更稳的架构是作为 EZ 的 `Prompt/Workflow Intelligence` 层：把用户意图转成结构化画面 brief、模型/工作流选择、参数预设、negative prompt 和生成后 VLM 复盘建议，再交给现有 `/api/prompt/optimize`、`/api/prompt/interrogate` 与 `/api/generate` 执行。
- 快速出图的第一版作图 skill 落地为“出图策略”控件：前端 `static/js/modules/generate.js` 传 `prompt_strategy`，后端 `app.py` 的 `_apply_prompt_strategy_to_fields()` 在 workflow 专用 normalizer 之前 deterministic 增强正向 prompt/negative prompt，并写入 `__user_prompt_original`、`__prompt_strategy_id`、`__prompt_strategy_enhanced_prompt` 等历史字段；默认 `none` 保持旧行为，`auto` 遇到参考图/i2i/edit 自动走 `reference_edit`，遇到 upscale 不改 prompt。

## 2026-07-01

- 用户反馈选择“出图策略”后体感内容和质量没变化时，优先查三点：前端是否随 `/api/generate` 传 `prompt_strategy`、后端最终 `node::field` 是否真的被增强写入 ComfyUI graph、策略控件是否在快速出图面板里被 footer/按钮遮挡。修复方向是把策略从尾部弱追加改成前置“成片任务”编译，并在 `tests/test_prompt_strategy.py` 覆盖最终 workflow 字段；前端把“出图策略”移到提示词框上方，`#quickFormFields` 留底部安全区，避免 720px 高度下和“开始生成”按钮重叠。
- 用 `mmx video generate --first-frame` 做 MiniMax Hailuo 图生视频时，本机默认产物约 5.875 秒且无音轨；要交付 10 秒左右带台词成片，可用 `mmx speech synthesize` 生成中文语音，再用 `ffmpeg` 的 `tpad` 补时长、`adelay` 对齐音频。不要让 Hailuo 直接生成中文字幕，容易出现乱码；本机 ffmpeg 缺 `subtitles`/`drawtext` 滤镜，烧字幕应先用 PIL 生成透明字幕 PNG，再用 `overlay` 按时间叠加。
- 用户要“照片中的角色开口说话”时，不要默认改成技巧教学或让角色看站牌/物体；若主题是“等到了我的到来（镜头）”，prompt 要明确写 `camera represents the person she is waiting for`、角色正面看镜头、自然开合嘴说短句，并禁止模型生成 on-screen text。验收时抽 1fps contact sheet，确认人物朝向、口型动作和字幕位置，再封最终片。
- 严格嘴型同步不要继续用 Hailuo 图生视频猜口型，应走 `longcat_avatar15_q4_smoke.json` 的 LongCat Avatar 1.5 音频驱动 workflow：先生成/上传台词音频和近景半身参考图，字段用 `1::image`、`3::audio`、`4::duration=0`，后端会按音频同步 `__longcat_target_duration_sec`/`num_frames`。参考图最好裁成接近 `480x832` 的半身近景，让嘴部足够大；本次真实任务 `job_1782842860294_5726` 输出 `5.64s` 带 AAC 音轨，比强行补到 10s 更适合检验口型。

## 2026-07-02

- 快速出图「出图策略」已升级为 Lingzao-style LLM visual-director layer：`/api/generate` 在 workflow normalizer 之前调用 `_apply_prompt_strategy_to_fields(..., allow_llm=True)`，先按所选策略生成 `visual_brief`、`final_prompt`、`negative_prompt`，再把最终 prompt 写回正向提示词字段并把 negative 合并到反向字段；历史字段会保存 `__prompt_strategy_engine`、`__prompt_strategy_brief`、`__prompt_strategy_analysis_version` 和 `__prompt_strategy_enhanced_prompt`。`EZ_PROMPT_STRATEGY_LLM=0` 可禁用 LLM，`EZ_PROMPT_STRATEGY_LLM_TIMEOUT` 控制超时；LLM 失败时必须回落到 deterministic 策略，不能阻塞出图。
- 用户纠正“提示词优化”和“出图优化”功能重复后，快速出图只保留一个 `optimizePromptBtn`：点击后打开 `promptOptimizeMenu`，菜单含“标准优化”（现有 `/api/prompt/optimize`）和“智能优化/小红书封面/产品海报”等策略项（`/api/prompt/strategy-optimize`）。选择任一项后直接把优化结果写回 `#promptInput`，不再保留独立 `strategyOptimizeBtn`、出图优化弹窗或提交时隐藏 `prompt_strategy`；中文输入应保持中文输出。
- `promptOptimizeMenu` 应保持轻量：只显示选项标题，不显示说明小字，菜单层不拦截全页点击；点击任一优化项后菜单立即关闭，`optimizePromptBtn` 显示“优化中”等 API 完成。策略 LLM 输出需要一轮就足够硬，但不能依赖“成片硬约束”这类标题前缀；后端应把质量门槛改写成可直接生图的画面内容。
- 用户纠正：策略优化返回给生图的正向 prompt 不能带 `专业人物写真成片硬约束：`、`小红书封面：`、`最终提示词：` 这类标题/前缀；约束必须以真实画面内容表达。真人写真/写实摄影策略必须以所选策略为准清理冲突风格词，例如原 prompt 里有 `二次元`、`漫画`、`日漫`、`动漫`、`卡通`、`anime`、`manga`、`comic` 时，返回的正向 prompt 不应继续保留这些词。
- `promptOptimizeMenu` 的出现位置应始终锚定在 `optimizePromptBtn` 下方悬浮，并以按钮中心对齐；不要因为下方空间判断而翻到按钮上方，左右只做视口边界夹取。
- Qwen Rapid 图生图输出比参考图少外围一圈时，优先查 `QwenMultiangleCameraNode` 的 `910::zoom` 默认值，而不是 prompt；Rapid 三个 workflow 默认应为 `zoom=0`，前端相机调整的中性状态应按当前 workflow 初始值判断，避免未主动调整时提交隐性裁边。
- Qwen Rapid 仍出现“缩小一圈”时，继续查 `88::largest_size`：真实任务 `job_1782930908152_6063` 参考图 `832x1248` 被默认 `largest_size=1024` 缩成输出 `680x1024`。修复应在 `_sync_i2i_reference_dimensions()` 中为 Rapid 按上传参考图长边动态覆盖默认 `88::largest_size`，只在用户手动改成非默认值时尊重手动值。
- 新增 `GET /api/interfaces` 作为提交/列表/详情/上传接口目录，支持 `kind` 与 `auth` 过滤；外部调用方应先读该目录，再按 `/api/workflows/{name}/fields` 组装 `/api/generate` payload。

## 2026-07-04

- 快速出图左侧 `#promptInput` 支持一键全屏编辑：入口放在提示词标题行右侧，`promptFullscreenEditor` 只做 UI 层编辑并实时回写原 `#promptInput`，不能新增独立提交字段或绕过现有 `/api/generate` 字段收集；静态改动仍需同步 `static/index.html`、`static/js/module_loader.js` 和缓存版本测试。
- 出图列表中 `queued` 与 `paused` 属于同一个排队队列组；暂停/恢复只应切换状态文案和按钮，不应改变 `_sortJobCards` 的队列相对顺序。
- 当前 `wf_meta` 里 59 个 workflow（36 个 shared）没有已暴露的“多参考图片生图片”入口；多参考真实入口主要是 `t2i_bernini_fp8.json` 的 `r2v/rv2v` 多参考视频模式和隐藏测试版 `i2v_ltx23_msr_test.json` 的 4 张参考图视频 workflow。Qwen/Flux 图生图虽有 `FluxKontextMultiReferenceLatentMethod` 节点、Boogu Edit 虽用 `TextEncodeBooguEdit.images.image_1` autogrow 形态，但当前配置/API 都只给单张参考图。
- 外部官方源核对后需修正边界：模型能力不等于当前 EZ 接入能力。`Qwen/Qwen-Image-Edit-2511` 官方 Diffusers 示例用 `QwenImageEditPlusPipeline` 传 `image: [image1, image2]` 并展示 two-person fusion；`FireRedTeam/FireRed-Image-Edit-1.1` 官方写明增强 multi-image conditioning / multi-element fusion；`black-forest-labs/FLUX.2-dev` 官方写明支持 single-reference editing 和 multi-reference editing。相反，`Boogu-Image-0.1-Edit` 官方仍注明当前只支持 1 张参考图；`ERNIE-Image`、`Krea-2`、`Ideogram-4` 官方 Comfy/HF 页主要是文生图/风格 LoRA/单模型部署，没有确认多参考图生图/修图能力。下一步若做多参考图片入口，优先改造 Qwen-Image-Edit-2511、FireRed-Image-Edit-1.1 或 FLUX.2，而不是 Boogu/ERNIE/Krea/Ideogram。
- 单/多参考图切换已落地在 `i2i-Qwen-Edit-v2511.json`、`i2i-FireRed-Edit-8step.json`、`i2i_flux2_dev_turbo_q4km.json`：config 通过主 `LoadImage` 节点挂 `__image_reference_mode` 与 `__multi_reference_images` 合成字段，前端 `generate.js` 渲染“单图/多图”按钮和最多 3 张多参考图上传区。后端共享 mutator 在 `modules/multi_reference_workflow.py`：Qwen/FireRed 只给已有 `image1` 的 `TextEncodeQwenImageEditPlus` 动态补 `image2/image3`；FLUX.2 通过链式 `ReferenceLatent` 把第 2/3 张参考图接到 `BasicGuider.conditioning`。配置变更需同步 `data/wf_configs` 与 SQLite `workflow_editor_config`。

## 2026-07-05

- 三个多参考图 workflow 已做真实远端 smoke：FireRed `prompt_id=45f1bf27-272f-441b-b7eb-c924dc94bcb1` 输出 `Firered_image_edit_1.0/codex_smoke_multi_ref_1783181654_00001_.png`；Qwen 2511 `prompt_id=8afb11b6-bf0b-4115-9f46-8825a3594918` 输出 `Qwen_Edit_2511/codex_smoke_multi_ref_1783181834_00001_.png`；Flux2 Dev Turbo Q4 retry `prompt_id=30a9cd69-1532-4d9e-aada-39c6434d5458` 输出 `i2i-flux2-dev-turbo-q4km/codex_smoke_multi_ref_retry_1783182472_00001_.png`。用户页面 FireRed 失败任务 `job_1783181346172_2046` 的 `prompt_id` 为空，失败在实例启动/状态阶段，不是 FireRed 多图 graph 被 ComfyUI 执行拒绝。
- 直接向远端 ComfyUI 提交长任务时，app 的 idle watcher 过去只看本地 active job，可能在发现“未追踪远端任务”后仍按空闲停掉实例；已改为停实例前检查远端 `/queue`，只要 `queue_running` 或 `queue_pending` 非空就刷新 `_instance_last_active` 并跳过 stop，避免正在运行的远端 prompt 被 idle 回收误杀。
- 使用上一组 FireRed 两张参考图临时注入 `TextEncodeQwenImageEditPlus.image2` 后，Qwen Rapid 主版和 Q2 版均真实跑通多图：`i2i-Qwen-Rapid.json` `prompt_id=f5fdce75-d4b9-4529-9239-2bd3d3154aee` 输出 `Qwen_Rapid/codex_smoke_multi_ref_1783183206_00001_.png`，`i2i-Qwen-Rapid-Q2.json` `prompt_id=367e0358-fa16-4228-b650-5866ad4e451a` 输出 `Qwen_Rapid_Q2/codex_smoke_multi_ref_1783183283_00001_.png`。当前只是验证模型/节点链路可跑，EZ 配置尚未给 Rapid 暴露 `__image_reference_mode` / `__multi_reference_images`。
- Qwen Rapid 三个图生图入口 `i2i-Qwen-Rapid.json`、`i2i-Qwen-Rapid-Q2.json`、`i2i-Qwen-Rapid-seedVR2-4k.json` 已补齐单/多参考图切换字段并同步 SQLite；Rapid mutator 走已实测的直连路径：第 2/3 张图动态创建 `LoadImage` 并接到 `TextEncodeQwenImageEditPlus.image2/image3`，不走 FireRed/Qwen 2511 的 `FluxKontextImageScale`。应用层 `/api/generate` 已用上一组 FireRed 两张参考图真实跑通 Rapid 主版：`job_1783184398057_8492`，`prompt_id=ff750c0d-0f6e-4115-8e02-66751fa0f9dc`，B 实例 28.3s 完成，输出 `data/outputs/1ec621fd/2026-07-05/i2i-Qwen-Rapid_0001.png`（832x1248）。
- 单/多参考图 UI 切换不能把单图和多图当成独立状态：从单图切到多图时，如果 `refImageValue` 已有图片，必须把它插为 `multiRefsValue[0]`；从多图切回单图时，必须把第一张多图写回 `refImageValue`，并把多图状态裁成只剩第一张。已在 `static/js/modules/generate.js` 用 `_ensureMultiRefsStartWithSingleReference()` 和 `_syncSingleReferenceFromFirstMultiRef(true)` 固化，并用 Chrome Playwright 验证 Rapid 标准版通过。
- v4.8.0 release 通知内容应聚焦多参考图生图/修图：Qwen Image Edit 2511、FireRed、Flux2 Dev Turbo Q4、Qwen Rapid 三入口支持单/多参考图切换，切换时首图同步，并说明已做远端 smoke 与 idle watcher 保护；通知写入 `site_notifications`，版本真源同步 `VERSION`、README、CHANGELOG 和 `tests/test_app_version.py`。
