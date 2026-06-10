# Ez ComfyUI Showcase 🎨

Multi-instance ComfyUI Web Management & Generation Platform.

Current version: **v4.7.36**. The canonical project version is stored in [`VERSION`](VERSION) and exposed by `/api/version`.

Built for **DGX Spark (GB10)** with 128GB unified memory, running two serially dispatched generation ComfyUI instances (A:8190 / B:8189) behind an intelligent scheduler. Prompt optimization, translation, and image reverse prompting use the configured local LLM API instead of a separate ComfyUI Prompt instance.

---

## Features

- **多实例生成调度** — 出图走 A/B 生成实例，提示词优化、翻译和图片反推走本地 LLM API
- **三段式 UI** — 工作流管理、生成面板、历史画廊一站式操作
- **GPU 监控** — 实时显存/功耗/温度仪表盘
- **服务管理** — 浏览器内一键启动/停止 ComfyUI 实例
- **节点编辑器** — 可视化修改 workflow 参数（prompt、seed、尺寸）
- **画廊系统** — 按标签/日期/模型筛选，无限滚动懒加载
- **快速出图** — 一键复用历史配置重新生成
- **冷启动自愈** — 无可用实例时自动拉起 ComfyUI

## Screenshots

![主界面](screenshots/01_main_dashboard.png)
*主界面 — 左侧生成控制面板（工作流选择、Prompt 输入、尺寸预设、参数调节）+ 右侧出图历史画廊*

![工作流管理](screenshots/04_workflow_management.png)
*工作流管理页 — 管理 10 条预置工作流（文生图/图生图/放大），支持排序、编辑、节点查看、下载、删除和拖拽上传*

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 + asyncio + FastAPI |
| Frontend | Vanilla JS ES6 Modules, CSS3 |
| ComfyUI | 2× generation instances (A/B), --highvram |
| Nginx | SSL reverse proxy (`imdjj.cn:1213`) |
| Hardware | NVIDIA GB10, 128GB unified, CUDA 13 |

## Directory Structure

```
├── app.py                      # FastAPI backend (2084 lines)
├── static/
│   ├── index.html              # SPA 入口
│   ├── css/style.css           # 主题样式
│   └── js/
│       ├── app.js              # 核心加载器 + 模块注册
│       └── modules/
│           ├── workflows.js    # 工作流管理（CRUD + 缩略图）
│           ├── generate.js     # 生成面板 + 快速出图
│           ├── history.js      # 画廊 + 懒加载 + 筛选
│           ├── node-editor.js  # 节点参数编辑
│           ├── status.js       # GPU 实时监控
│           └── ui.js           # 通用 UI 组件
├── i2i-FireRed-Edit-1.1.json   # 图生图 workflow
├── i2i_Qwen_Edit.json          # Qwen 编辑 workflow
└── README.md
```

## Quick Start

```bash
# 克隆仓库
git clone https://github.com/sjcta/ez-comfyui-showcase.git
cd ez-comfyui-showcase

# 安装依赖
pip install fastapi uvicorn aiofiles pillow

# 启动（默认 :9091）
python3 app.py

# 指定端口
python3 app.py --port 9091
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKFLOW_DIR` | `./workflows` | ComfyUI workflow JSON 目录 |
| `COMFYUI_A_PORT` | `8190` | 实例 A WebSocket 端口 |
| `COMFYUI_B_PORT` | `8189` | 实例 B WebSocket 端口 |
| `OUTPUT_DIR` | `./output` | 生成图片输出目录 |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/generate` | POST | 提交生成任务 |
| `/api/jobs/{id}` | GET | 查询任务状态 |
| `/api/workflows` | GET | 获取工作流列表 |
| `/api/status` | GET | 实例健康 + GPU 状态 |

## Version History

See [`CHANGELOG.md`](CHANGELOG.md) for the full user-facing update notes.

### Release Discipline

Every code, workflow, documentation, or configuration change must be recorded in [`CHANGELOG.md`](CHANGELOG.md) with a concise description of what changed, and the smallest applicable project version must be bumped at the same time. For ordinary fixes and documentation updates, increment the patch version in [`VERSION`](VERSION) and keep the README current-version line and version tests aligned.

| Version | Highlights |
|---------|-----------|
| v4.7.36 | 远端输出下载隔离 — 按 prompt_id 下载到独立目录，避免本地同名旧图污染新 i2i 卡片 |
| v4.7.35 | i2i 输出选择生效修正 — 兼容真实 ComfyUI history prompt tuple，确保 SaveImage/SaveVideo 优先规则真正命中 |
| v4.7.34 | i2i 输出卡片修正 — 优先保存 SaveImage/SaveVideo 节点输出，避免参考图或中间图抢占最终结果 |
| v4.7.33 | Flux2 Klein Realistic — 新增文生图和图生图 Realistic Detail LoRA 工作流，开放 LoRA 强度控制 |
| v4.7.32 | 图生图参考图保护 — Qwen Rapid 等 I2I 工作流不会再静默沿用默认占位参考图，缺图时直接提示上传 |
| v4.7.31 | LLM 审查矛盾纠偏 — `sexual_visible`/`violent_visible` 成为权威字段，避免 `protected=true` 误伤安全图片 |
| v4.7.30 | 手动保护广播不重载 — protection WebSocket 更新只局部 patch 卡片，不再重建懒加载历史窗口 |
| v4.7.29 | 手动保护不跳顶 — 管理员切换图片保护时只局部更新卡片敏感状态，不再强制刷新历史列表 |
| v4.7.28 | 三路图片保护 — 管理员人工审查最高优先级，LLM 视觉和提示词审查任一路命中即保护，二者都未命中才放行 |
| v4.7.27 | LLM 专家审查收口 — 开启后由视觉大模型最终判断漏点、性器官、半透明暴露和血腥程度，避免普通猫狗被旧 detector 误伤 |
| v4.7.26 | LLM 视觉审查开关 — 可用大模型只判断可见情色或暴力血腥内容，不按皮肤露出面积保护 |
| v4.7.25 | 删除边界懒加载 — 删除后边界进入一个卡片高度预加载范围时，自动继续局部加载下一批 |
| v4.7.18 | 删除无定位刷新 — 删除历史卡片时只做局部 DOM patch，不再滚动定位或全量刷新 |
| v4.7.17 | 删除滚动锚点修正 — 捕获锚点时跳过即将删除的卡片，避免恢复失败后回到上方 |
| v4.7.16 | 历史最小 DOM 更新 — 删除后只 patch 历史卡片，不再重建整块画廊 |
| v4.7.15 | 历史删除视觉锚点 — 删除卡片后保持当前可见卡片的屏幕位置，减少跳动 |
| v4.7.14 | 画廊数据驱动更新 — 增删改统一收口到 galleryStore 调度渲染入口 |
| v4.7.13 | 历史删除滚动修正 — 删除卡片后延迟恢复滚动位置，不再跳回页头 |
| v4.7.12 | 历史删除补位修正 — 删除卡片后改用统一画廊渲染，避免第 6 张起重复前面内容 |
| v4.7.11 | 历史懒加载删除修正 — 出图中删除其他卡片后，后续加载不再重复前面的历史卡片 |
| v4.7.10 | 快速输入默认状态修正 — 新打开或刷新页面后提示词为空，画风为无 |
| v4.7.9 | 风格选择融合优化 — 用单个分组选单一次选定大类和细化风格，并嵌入提示词输入框 |
| v4.7.8 | 两级风格选单 — 正向提示词下方先选画风大类，再选择细化预设，历史复刻自动回填 |
| v4.7.7 | ERNIE 风格直通 — 选中画风时自动绕过 ERNIE prompt enhancer，避免强风格被改写稀释 |
| v4.7.6 | 风格菜单重构 — 移除宽泛游戏/电影入口，拆成像素、低多边形、AAA资产、黑色电影等高差异预设 |
| v4.7.5 | 游戏风格锁定修正 — 游戏预设强化为非摄影概念图，并要求 ERNIE 保留非人/机械主体类别 |
| v4.7.4 | 风格卡片标题修正 — 出图卡片只显示风格标题加用户提示词，不暴露完整风格增强块 |
| v4.7.3 | 风格锁定增强 — 画风预设改为强约束 Style Lock，并加强 ERNIE 提示词增强链路的画风保留 |
| v4.7.2 | 负面提示词清理 — 所有已有负面提示词预置通用错误排除词，并移除画风相关负面约束 |
| v4.7.1 | 风格选单 — 正向提示词下方新增画风预设，提交时合成通用风格块和模型族增强块 |
| v4.7.0 | ERNIE 与皮肤测试工作流 — 新增 ERNIE/BERNINI 工作流配置、Qwen/SkinTest 变体、项目文档，并同步运行与测试修正 |
| v4.6.27 | 移动端放大手势修正 — lightbox 双指缩放时抑制左右切图按钮和横滑导航误触 |
| v4.6.26 | 登出刷新修正 — `_logout` 刷新标记消费后立即从地址栏移除，避免用户重新登录后刷新又被登出 |
| v4.6.25 | 发布流程规范 — README 明确要求每次修改都必须写入修正日志，并同步更新最小适用版本号 |
| v4.4.0 | 图片对比与运行恢复 — 图生图放大窗口可一键切换原图/新图，增强 GPU 卡住自愈、实例停止收敛、媒体中性状态文案，并新增 LTX2.3 10Eros 工作流 |
| v4.3.0 | 正式升级 — 登录保持一个月、管理员网站通知、登录前首页、更多工作流、设备管理布局优化、历史画廊载入和 admin 轮询闪烁修复 |
| v4.2.3 | 图片保护校验 — 出图后先进入“图片校验中”，由本地轻量 worker 写回保护状态后再显示 |
| v4.2.2 | Safari 修复 — 登录/注册等弹窗遮罩拆分为独立合成层，避免黑色遮罩抖动或失效 |
| v4.2.1 | 小版本修正 — JSON 提示词中英切换稳定化、启动脚本 restart 修复、提示词助手与历史/状态 UI 累积修正 |
| v3.16 | 当前稳定版 — 三段式 UI + 双实例调度 + GPU 监控 |
| v3.15 | 模块化重构，JS 拆分为 6 个 ES6 模块 |
| v3.14 | Strict Mode 兼容，跨模块共享状态修复 |
| v3.13 | 画廊系统重写，懒加载 + 筛选功能 |
| v3.12 | 完整模块拆分（app.js 751行→6模块） |
| v3.10 | 三段式布局初始版本 |

## License

MIT © [Jeson Sun](https://github.com/sjcta)
