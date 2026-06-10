# Ez ComfyUI Showcase — 项目说明

> 当前版本：**v4.6.25** | 许可证：MIT | 作者：[Jeson Sun](https://github.com/sjcta)

---

## 项目简介

Ez ComfyUI Showcase 是一个运行在 **NVIDIA DGX Spark (GB10)** 上的多实例 ComfyUI Web 管理与 AI 内容生成平台。它在两台 ComfyUI 生成实例之上构建了智能调度层，通过浏览器提供一站式的工作流管理、AI 图片/视频生成、历史画廊和提示词工具。

**核心定位**：为拥有高端 GPU 设备的个人创作者或小团队，提供远程可视化操作界面，降低 ComfyUI 命令行操作的门槛，实现"打开浏览器即可出图"的体验。

---

## 核心能力

### AI 内容生成

| 能力 | 说明 |
|------|------|
| **文生图 (T2I)** | 输入文字描述，AI 生成对应图片，支持 FLUX.2、Z-Image Turbo 等模型 |
| **图生图 (I2I)** | 上传参考图 + 文字指令进行图片编辑，支持 Qwen Edit、FireRed Edit |
| **视频生成 (I2V)** | 从静态图片生成短视频，支持 LTX 2.3 系列模型 |
| **超分辨率放大** | 将低分辨率图片放大至 2K/4K，基于 SeedVR2 模型 |
| **批量生成** | 一次提交多张生成任务，自动排队执行 |

### 智能提示词工具

| 工具 | 说明 |
|------|------|
| **提示词优化** | 将简单描述扩展为专业级生成提示词（由本地 LLM 驱动） |
| **中英互译** | 提示词中英文语言切换 |
| **图片反推** | 上传截图或照片，AI 自动分析并输出可复用的提示词 |

图片反推支持四种模式：标准反推、专家反推、专家团反推（9 位专家席位协同分析）。

### 多实例智能调度

- **A/B 双实例串行调度**：文生图/放大优先走 A 实例 (8190)，图生图/视频优先走 B 实例 (8189)
- **冷启动自愈**：无可用实例时自动拉起 ComfyUI 服务
- **死实例自动恢复**：检测到实例无响应时自动重启
- **空闲回收**：实例空闲 15 分钟后自动停止，释放 GPU 资源
- **全局串行队列**：A/B 不会同时出图，避免 GPU 资源争抢

### 历史画廊

- 瀑布流卡片布局，无限滚动懒加载
- 按归属（所有/我的/收藏/其他）和类型筛选
- 软删除 + 回收站 + 永久删除
- 公开分享、收藏、隐藏
- 视频帧提取与导出
- Lightbox 大图/视频查看，支持键盘导航

### 图片内容保护

生成完成后自动进行内容安全检测：
1. **第一层**：ifnude ONNX 检测器
2. **第二层**：HuggingFace 分类器
3. **第三层**：本地启发式规则 fallback

---

## 系统架构

```
浏览器 (Vanilla JS SPA)
    │
    ├── HTTP REST API ──→ FastAPI 后端 (app.py)
    │                         │
    │                         ├── 实例管理器 (instance_manager)
    │                         ├── 实例选择器 (instance_picker)
    │                         ├── 任务编排器 (job_runner)
    │                         ├── WS 追踪器 (ws_tracker)
    │                         ├── 进度计算器 (step_calculator)
    │                         ├── 时长估算器 (time_estimator)
    │                         ├── 提示词工具 (prompt_optimizer / interrogator)
    │                         ├── 图片保护 (image_protection)
    │                         └── LLM 客户端 (llm_client)
    │
    ├── WebSocket ─────→ 实时进度推送
    │
    └── ComfyUI 实例 A (:8190) ←── HTTP + WS ──→ DGX Spark GPU
        ComfyUI 实例 B (:8189) ←── HTTP + WS ──→ DGX Spark GPU
        本地 LLM 服务 (:18080) ←── OpenAI API ──→ llama.cpp (Mac)
```

### 三段式界面布局

| 区域 | 位置 | 功能 |
|------|------|------|
| **工作流选择 + 快速出图** | 左列 | 选择工作流、输入提示词、设置参数、提交生成 |
| **出图历史画廊** | 中列 | 浏览生成结果、筛选/搜索、Lightbox 查看 |
| **日志面板** | 右列（可吸附） | 实时查看运行日志 |

顶部标题栏提供：设备管理、工作流管理、日志、用户认证入口。
底部状态栏显示：GPU 显存/温度/利用率、ComfyUI 实例状态。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | Python 3 + FastAPI + asyncio + uvicorn |
| **前端** | Vanilla JS (ES6 Modules) + CSS3，无框架依赖 |
| **认证** | JWT + bcrypt，httpOnly Cookie 会话 |
| **数据库** | SQLite (auth.db / generation.db / nodes.db) + JSON 文件持久化 |
| **AI 生成** | ComfyUI HTTP + WebSocket API |
| **LLM 服务** | llama.cpp server (OpenAI 兼容 API)，支持 Gemma-4 / Qwen 视觉模型 |
| **图片处理** | Pillow, OpenCV (人脸检测), ifnude (内容检测) |
| **部署** | macOS launchd 服务，Nginx SSL 反向代理 |

---

## 硬件要求

| 组件 | 要求 |
|------|------|
| **GPU 设备** | NVIDIA DGX Spark (GB10)，128GB 统一内存 |
| **ComfyUI 实例** | 2 个生成实例，各需独立端口 (默认 8190/8189) |
| **LLM 服务** | 可运行在 Mac 本地或远程服务器，需支持 OpenAI 兼容 API |
| **网络** | Mac 与 DGX Spark 在同一局域网，或通过 Nginx 代理访问 |

---

## 快速部署

### 1. 启动主服务

```bash
# 克隆仓库
git clone https://github.com/sjcta/ez-comfyui-showcase.git
cd ez-comfyui-showcase

# 安装 Python 依赖
pip install fastapi uvicorn aiofiles pillow python-jose bcrypt

# 直接启动（默认端口 18000）
python3 app.py

# 或指定端口
python3 app.py --port 9091
```

### 2. 注册为系统服务（macOS）

```bash
# 启动为 launchd 服务（开机自启 + 崩溃自动重启）
./quick-start.sh start

# 其他操作
./quick-start.sh stop      # 停止
./quick-start.sh restart   # 重启
./quick-start.sh status    # 查看状态
./quick-start.sh logs      # 查看日志
```

服务启动后访问 `http://127.0.0.1:18000/`。

### 3. 启动 LLM 服务（可选，用于提示词工具）

```bash
# 需要先安装 llama.cpp
brew install llama.cpp

# 启动 LLM 服务
./scripts/mac-llm.sh start

# 默认配置
#   模型: Gemma-4-E4B (视觉)
#   地址: http://127.0.0.1:18080
#   上下文: 8192 tokens
```

LLM 服务的环境变量配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EZ_MAC_LLM_PORT` | 18080 | LLM 服务端口 |
| `EZ_MAC_LLM_MODEL_PATH` | models/llm/gemma-4-.../ | GGUF 模型文件路径 |
| `EZ_MAC_LLM_MMPROJ_PATH` | models/llm/gemma-4-.../mmproj-... | 视觉投影器路径 |
| `EZ_MAC_LLM_CTX_SIZE` | 8192 | 上下文窗口大小 |

### 4. 配置节点/设备

首次使用需在界面中配置 DGX Spark 设备：

1. 点击右上角 **设备管理** 按钮
2. 点击 **添加设备**，填写设备名称、主机地址、SSH 连接信息
3. 设置实例端口（默认 8190、8189）和工作流目录
4. 保存后系统会自动扫描并登记 ComfyUI 实例

### 5. 创建管理员账号

首次启动不会自动创建默认账号。需要通过注册页面创建第一个用户，然后在数据库中将其提升为管理员角色。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EZ_COMFYUI_PORT` | 18000 | 主服务端口 |
| `COMFYUI_A_PORT` | 8190 | 实例 A 端口 |
| `COMFYUI_B_PORT` | 8189 | 实例 B 端口 |
| `WORKFLOW_DIR` | ./workflows | 工作流目录 |
| `OUTPUT_DIR` | ./output | 输出目录 |
| `EZ_LLM_BASE_URL` | http://127.0.0.1:18080 | LLM API 地址 |
| `EZ_LLM_MODEL` | — | LLM 模型名称 |
| `EZ_LLM_TIMEOUT` | — | LLM 请求超时 (秒) |
| `EZ_LLM_API_KEY` | — | LLM API Key |

---

## 版本里程碑

| 版本 | 亮点 |
|------|------|
| **v4.6.x** | 安全加固（CSRF/Cookie 会话/上传限额）、任务生命周期完善、前端稳定性修复 |
| **v4.4.x** | 图片对比、GPU 卡住自愈、专家团反推、内容保护、LLM 提示词链路 |
| **v4.3.0** | 登录保持一个月、网站通知、登录前首页、新增多种工作流 |
| **v4.2.x** | 图片保护校验、Safari 兼容、提示词助手优化 |
| **v4.0.0** | 出图 Pipeline 模块化重构，app.py 拆分为 18 个独立模块 |
| **v3.16** | 三段式 UI + 双实例调度 + GPU 监控（稳定版） |
| **v3.10-v3.15** | 模块化重构、画廊系统重写、ES6 模块拆分 |

完整更新日志请参阅 [CHANGELOG.md](../CHANGELOG.md)。

---

## 项目结构

```
ez-comfyui-showcase/
├── app.py                  # FastAPI 后端主入口
├── modules/                # 后端业务模块
│   ├── config.py           # 常量定义、节点分类、模型组
│   ├── instance_manager.py # 实例生命周期管理
│   ├── instance_picker.py  # 智能实例选择路由
│   ├── job_runner.py       # 出图全流程编排
│   ├── ws_tracker.py       # WebSocket 实时进度追踪
│   ├── step_calculator.py  # 进度权重计算
│   ├── time_estimator.py   # 时长估算
│   ├── comfyui_upload.py   # 媒体上传到 ComfyUI
│   ├── media_outputs.py    # 输出媒体类型检测
│   ├── image_protection.py # 图片内容安全
│   ├── llm_client.py       # LLM API 客户端
│   ├── prompt_optimizer.py # 提示词优化/翻译
│   ├── prompt_interrogator.py # 图片反推
│   ├── prompt_labels.py    # 标签推断
│   ├── workflow_validation.py # 工作流校验
│   └── image_reverse/      # 图片反推子模块
├── static/                 # 前端静态资源
│   ├── index.html          # SPA 入口页
│   ├── css/style.css       # 主题样式
│   └── js/
│       ├── app.js          # 核心加载器
│       ├── module_loader.js # 模块注册与加载
│       └── modules/        # 前端功能模块
│           ├── generate.js # 生成面板
│           ├── history.js  # 历史画廊
│           ├── workflows.js # 工作流管理
│           ├── nodes.js    # 设备管理
│           ├── status.js   # GPU 监控
│           └── ...
├── config/nodes.json       # 节点/设备配置
├── data/                   # 数据目录
│   ├── workflows/          # 工作流 JSON 文件
│   ├── wf_configs/         # 工作流字段配置
│   ├── outputs/            # 生成的图片/视频
│   └── *.db                # SQLite 数据库
├── models/llm/             # 本地 LLM 模型文件
├── scripts/                # 工具脚本
├── tests/                  # 测试用例 (68 个)
├── quick-start.sh          # macOS 服务管理脚本
└── VERSION                 # 当前版本号
```

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [功能规格文档](SPECIFICATION.md) | 各功能域的详细规格说明和 API 参考 |
| [用户使用指南](USER_GUIDE.md) | 界面操作指南和常见问题解答 |
| [更新日志](../CHANGELOG.md) | 完整的版本更新记录 |
| [开发规范](../PROJECT_STANDARDS.md) | 项目开发规范与约束 |
| [分支策略](../BRANCHING.md) | Git 分支管理与部署流程 |
