# Ez ComfyUI Showcase — 功能规格文档

> 版本：v4.6.25 | 最后更新：2026-06-03

本文档按功能域详细说明 Ez ComfyUI Showcase 的系统能力、行为规则和数据接口。

---

## 目录

1. [工作流管理系统](#1-工作流管理系统)
2. [生成任务系统](#2-生成任务系统)
3. [实时进度追踪](#3-实时进度追踪)
4. [历史画廊](#4-历史画廊)
5. [提示词工具](#5-提示词工具)
6. [图片内容保护](#6-图片内容保护)
7. [用户与权限](#7-用户与权限)
8. [设备与节点管理](#8-设备与节点管理)
9. [系统设置](#9-系统设置)
10. [API 端点参考](#10-api-端点参考)

---

## 1. 工作流管理系统

### 1.1 工作流类型

系统支持以下四类 ComfyUI 工作流，每类对应不同的生成实例偏好：

| 类型 | 命名规范 | 优先实例 | 代表模型 |
|------|----------|----------|----------|
| **文生图 (T2I)** | `t2i-{model}.json` | A (8190) | FLUX.2 Dev, FLUX.2 Klein, Z-Image Turbo |
| **图生图 (I2I)** | `i2i-{model}.json` | B (8189) | Qwen Edit, FireRed Edit |
| **视频生成 (I2V)** | `i2v-{model}.json` | B (8189) | LTX 2.3 Sulphur, LTX 2.3 10Eros |
| **超分放大** | `SeedVR2_*.json` | A (8190) | SeedVR2 (2K/4K) |

### 1.2 工作流存储格式

工作流以 **ComfyUI API Prompt 格式**的 JSON 文件存储，结构为节点 ID 到节点定义的字典：

```json
{
  "1": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 42,
      "steps": 20,
      "cfg": 7.0,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1.0,
      "model": ["3", 0],
      "positive": ["4", 0],
      "negative": ["5", 0],
      "latent_image": ["6", 0]
    },
    "_meta": { "title": "KSampler 采样器" }
  }
}
```

节点间通过 `[source_node_id, output_index]` 数组建立连接。

### 1.3 工作流配置（四区模型）

每个工作流对应一个字段配置文件，控制前端节点编辑器中参数的展示方式。配置采用四区模型：

| 区域 | 用途 | 用户可见性 |
|------|------|-----------|
| **user_input** | 用户主要操作区 | 首屏直接显示（提示词、图片上传、尺寸） |
| **advanced** | 高级参数区 | 折叠在"详细参数"中（seed、采样器、CFG、降噪） |
| **output** | 输出控制 | 文件名前缀等 |
| **hidden** | 隐藏字段 | 不在快速出图中显示，但可通过节点编辑器修改 |

字段配置结构：

```json
{
  "key": "1::seed",
  "zone": "advanced",
  "visible": true,
  "label": "随机种子",
  "order": 10,
  "type": "seed",
  "min": 0,
  "max": 9999999999
}
```

支持的字段类型：`number`、`textarea`、`text`、`image`、`seed`、`select`、`toggle`。

### 1.4 工作流版本管理

- 每个工作流支持多版本存储，可上传新版本并切换激活版本
- 版本文件存储在 `data/workflows/{name}/versions/` 目录
- 激活版本通过 `workflow_meta` 表中的 `active_version` 字段管理
- 支持版本回退和历史对比

### 1.5 工作流操作

| 操作 | 说明 |
|------|------|
| **同步** | 从远程 ComfyUI 实例拉取工作流 JSON 到本地 |
| **上传** | 上传本地工作流 JSON 文件（支持拖拽） |
| **下载** | 下载工作流 JSON 到本地 |
| **编辑** | 修改名称、标签、缩略图、版本 |
| **节点编辑** | 可视化调整字段分区、可见性和标签 |
| **重命名** | 修改工作流文件名 |
| **删除** | 删除工作流及其所有版本 |
| **缩略图** | 上传或自动生成工作流预览图 |

---

## 2. 生成任务系统

### 2.1 任务提交流程

```
用户提交 → 参数校验 → 选择实例 → 停止 vLLM(遗留) → 冷启动检查
    → 获取实例信号量 → 注入字段/种子 → 上传输入媒体
    → WebSocket 连接 → POST /prompt → 实时进度追踪
    → 下载输出 → 保存历史 → 图片保护校验 → 恢复 vLLM(遗留)
```

### 2.2 智能实例选择

实例选择算法综合考虑以下因素：

| 因素 | 规则 |
|------|------|
| **任务类型偏好** | T2I/放大 → 优先 A；I2I/视频 → 优先 B |
| **模型组亲和性** | 相同模型组的工作流优先分配到同一实例，减少模型切换 |
| **远程队列深度** | 优先选择 ComfyUI 远端队列较浅的实例 |
| **本地等待队列** | 优先选择本地等待任务较少的实例 |
| **忙碌惩罚** | 正在执行任务的实例会被降权，避免任务过度集中 |

### 2.3 串行队列机制

- **全局生成队列**：所有生成任务串行执行，A/B 实例不会同时出图
- **实例信号量**：每个实例最多 1 个并发任务（`max_concurrent: 1`）
- **排队显示**：后提交的任务显示排队状态和前方任务信息

### 2.4 冷启动与自愈

| 场景 | 行为 |
|------|------|
| **实例未运行** | 自动通过 `systemctl --user start` 启动，等待 300s 超时 |
| **启动超时** | 先强制重启一次，再等待一轮 |
| **健康检查失败** | 15s 缓存，连续失败后标记为离线 |
| **死实例检测** | 60s 间隔后台循环，服务 active 但 health 失败时自动重启 |
| **防御期** | 启动后 90s 内不做死实例误判 |
| **空闲回收** | 实例空闲 15 分钟后自动停止 |

### 2.5 任务状态生命周期

```
queued → preparing → submitting → generating → saving → protecting → completed
                                                              ↘ failed
                                          cancelled (用户主动取消)
                                          retrying → (新任务)
```

| 状态 | 说明 |
|------|------|
| `queued` | 在本地队列中等待 |
| `preparing` | 正在准备环境和上传媒体 |
| `submitting` | 正在向 ComfyUI 提交 prompt |
| `generating` | ComfyUI 正在生成中 |
| `saving` | 正在下载和保存输出文件 |
| `protecting` | 正在进行图片内容保护校验 |
| `completed` | 生成完成 |
| `failed` | 生成失败 |
| `cancelled` | 用户主动取消 |
| `retrying` | 正在重试 |

### 2.6 任务操作

| 操作 | 说明 |
|------|------|
| **取消** | 取消正在执行或排队的任务，立即从列表移除 |
| **重试** | 对失败任务创建新任务，旧错误卡自动清除 |
| **清除** | 移除已完成/失败的任务卡片 |
| **复用** | 从历史记录复用参数重新生成 |

### 2.7 提交卡死自动纠错

- 提交 prompt 后 45s 内无响应视为卡死
- 自动清理 ComfyUI 队列 + 重启实例
- 最多重试 3 次，每次尝试可能切换实例
- 采用循环重试（非递归），避免资源泄漏

---

## 3. 实时进度追踪

### 3.1 WebSocket 事件驱动

通过 WebSocket 连接 ComfyUI 实例，实时接收以下事件：

| 事件类型 | 说明 |
|----------|------|
| `executing` | 节点开始执行 |
| `progress` | 节点执行进度（当前步/总步数） |
| `executed` | 节点执行完成 |
| `execution_error` | 执行出错 |
| `execution_start` | 整个 prompt 开始执行 |

### 3.2 进度权重算法

进度计算引擎基于工作流节点拓扑：

1. **拓扑排序**：Kahn 算法解析节点执行顺序
2. **权重分配**：
   - 采样器 (KSampler) / 超分器：占 90% 进度预算
   - 其他节点：共享剩余 10%
3. **有效步数计算**：考虑 `denoise` 系数和 `steps` 参数
4. **递归链路解析**：支持 PrimitiveInt / ComfySwitchNode / 多层链路

### 3.3 时长估算

- 使用历史完成耗时的**中位数**进行估算（每类节点最多 20 条记录）
- 无历史数据时按分辨率使用默认值（如 4K 超分默认 120s）
- 线程安全（类级别锁保护）

### 3.4 断线退化

- WebSocket 连接支持 3 次重试
- 断线后自动退化为 HTTP polling 兜底
- 兜底请求的超时时间按已消耗时间扣减，避免额外阻塞

---

## 4. 历史画廊

### 4.1 数据模型

每条历史记录包含以下核心字段：

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识 |
| `workflow` / `workflow_name` | 使用的工作流 |
| `device` / `instance` | 生成设备和实例 |
| `status` | 状态 |
| `media_type` | 媒体类型 (image/video) |
| `image_path` / `thumb_path` | 媒体文件路径 |
| `params` | 生成参数 (JSON) |
| `prompt` | 使用的提示词 |
| `width` / `height` | 输出分辨率 |
| `seed` | 随机种子 |
| `duration_sec` | 生成耗时 |
| `user_id` | 所属用户 |
| `batch_id` / `batch_index` / `batch_count` | 批次信息 |
| `is_public` / `is_hidden` / `deleted_at` | 可见性控制 |
| `protection_*` | 内容保护状态 |

### 4.2 浏览与筛选

| 功能 | 说明 |
|------|------|
| **分页加载** | 初始加载 9 张卡片，滚动到底部自动加载更多 |
| **搜索** | 按提示词内容搜索 |
| **归属筛选** | 所有图片 / 我的图片 / 我的收藏 / 其他 |
| **类型筛选** | 全部类型 / 图片 / 视频（动态生成可用类型） |
| **懒加载** | 仅加载可见区域数据，减少首次加载时间 |

### 4.3 回收站与删除

| 操作 | 说明 |
|------|------|
| **软删除** | 标记 `deleted_at`，从常规列表隐藏 |
| **恢复** | 取消软删除标记 |
| **永久删除** | 物理删除记录和文件 |
| **清空回收站** | 批量永久删除所有已软删除的记录 |
| **批量操作** | 支持批量恢复、批量删除、批量下载 |

### 4.4 社交功能

| 功能 | 说明 |
|------|------|
| **公开分享** | 设置 `is_public`，匿名用户可查看 |
| **收藏** | 标记为收藏，可在筛选中快速定位 |
| **隐藏** | 设置 `is_hidden`，仅管理员可见 |
| **导出** | 导出到图生图 / 视频制作 / 放大工作流 |

### 4.5 Lightbox 查看

- 支持图片大图查看和视频播放
- 键盘左右箭头导航上一张/下一张
- 图片对比功能（图生图历史可切换原图/新图）
- 视频逐帧预览、封面设置
- 视频编辑器：时间轴拖拽、帧刻度显示
- 下载原图

---

## 5. 提示词工具

### 5.1 提示词优化

- 将用户简单描述扩展为专业级生成提示词
- 支持模型感知：针对 FLUX.2 / Z-Image Turbo / Qwen 不同模型调整策略
- 支持视频脚本优化：LTX / Seedance 风格的视频生成脚本
- 字符上限：10000 字符

### 5.2 中英互译

- 中文提示词翻译为英文（适配主流 AI 模型）
- 英文提示词翻译为中文（方便用户理解）

### 5.3 图片反推

上传截图或照片，由本地视觉 LLM 分析后输出可复用的提示词。

#### 反推模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **标准反推** | 基础画面描述，输出正向提示词 | 快速获取大致描述 |
| **专家反推** | 按维度拆解（构图/颜色/肢体/材质等），结构化 JSON 输出 | 高精度复刻 |
| **专家团反推** | 9 位专家席位协同分析，一次视觉读取完成分工+复核 | 最精细的反推 |

#### 专家团席位

| 席位 | 职责 |
|------|------|
| 构图专家 | 画面构图、镜头焦段、光圈 |
| 摄影专家 | 摄影参数、光线、色温 |
| 色彩专家 | 颜色分析、HEX 色值 |
| 风格专家 | 画面风格、氛围 |
| 体态专家 | 人物姿态、关节角度 |
| 表情专家 | 面部表情、妆容 |
| 边界专家 | NSFW 内容边界判定 |
| 服装专家 | 服装、材质、纹理 |
| 材质专家 | 表面材质、肌理颗粒 |

#### 质量验证

反推结果经过质量评分系统（满分 100，目标 95 分），检测维度包括：

- 画幅比例冲突
- 负面提示词嵌套
- 稀疏回退检测
- 姿态分类漂移
- 支撑点矛盾
- NSFW 标签滥用
- 手部端点错误
- 裁切可见性冲突
- 等 15+ 种问题

---

## 6. 图片内容保护

### 6.1 三层检测机制

| 层级 | 检测器 | 说明 |
|------|--------|------|
| **第一层** | ifnude ONNX 检测器 | 基于 ONNX Runtime 的轻量裸露检测 |
| **第二层** | HuggingFace 分类器 | ML 分类器进行内容安全判定 |
| **第三层** | 本地启发式规则 | 肤色比例分析 + 视觉亲密标记 + 提示词 NSFW 正则 |

### 6.2 检测流程

```
生成完成 → 保存输出 → 标记为"保护中"
    → 第一层检测 → 通过? → 第二层检测 → 通过? → 第三层检测
    → 写入保护状态 (safe/warning/blocked)
    → 前端按状态展示（safe 清晰显示，其他模糊或隐藏）
```

### 6.3 可配置项

管理员可在系统设置中调整：
- 保护功能开关
- 各层检测阈值
- NSFW 关键词规则（中英文）
- 肤色比例阈值

---

## 7. 用户与权限

### 7.1 认证机制

| 项目 | 说明 |
|------|------|
| **认证方式** | httpOnly Cookie 会话 |
| **密码存储** | bcrypt 哈希 |
| **会话保持** | 正常情况至少一个月 |
| **CSRF 保护** | Cookie + Header 双重校验（写请求） |
| **登录限流** | 内存级 IP + 用户名限流 |

### 7.2 角色权限

| 功能 | 普通用户 (user) | 管理员 (admin) |
|------|:---:|:---:|
| 生成图片/视频 | ✓ | ✓ |
| 查看自己的历史 | ✓ | ✓ |
| 查看公开历史 | ✓ | ✓ |
| 查看所有历史 | — | ✓ |
| 工作流管理 | — | ✓ |
| 设备管理 | — | ✓ |
| 用户管理 | — | ✓ |
| 系统设置 | — | ✓ |
| 网站通知管理 | — | ✓ |
| GPU 进程管理 | — | ✓ |

### 7.3 用户操作

| 操作 | 说明 |
|------|------|
| **注册** | 用户名 + 密码（至少 6 位） |
| **登录** | 用户名 + 密码 |
| **修改密码** | 需验证旧密码 |
| **管理员创建用户** | 管理员可创建/编辑/禁用用户 |

---

## 8. 设备与节点管理

### 8.1 数据模型

```
Node (设备)
  ├── id, name, host, connection (remote-ssh/remote-http/local)
  ├── ssh_config (user, port, auth, password/key)
  ├── scan_ports (range, extra)
  ├── workflow_dirs (远程工作流目录列表)
  ├── access (url 模板, type)
  ├── labels, enabled, shared, sort_order
  └── Instances[]
       ├── id, name, port, service (systemd 服务名)
       ├── enabled, max_concurrent, sort_order
       ├── output_dir, shared
       └── 状态: running / idle / stopped / error
```

### 8.2 设备操作

| 操作 | 说明 |
|------|------|
| **添加设备** | 填写名称、主机、SSH 信息、端口列表 |
| **编辑设备** | 修改设备配置 |
| **删除设备** | 移除设备及其所有实例 |
| **连接测试** | 检测 HTTP/SSH/systemd 连通性 |
| **端口扫描** | 扫描指定端口范围，发现可用实例 |
| **排序** | 调整设备显示顺序 |

### 8.3 实例操作

| 操作 | 说明 |
|------|------|
| **启动** | `systemctl --user start {service}` |
| **停止** | `systemctl --user stop {service}` |
| **重启** | 先 stop 再 start |
| **强制重启** | 强制终止进程后重启 |
| **发现实例** | 扫描端口发现新的 ComfyUI 实例 |

### 8.4 GPU 监控

| 指标 | 说明 |
|------|------|
| **显存** | 已用/总量，进度条可视化 |
| **GPU 利用率** | 百分比 |
| **温度** | 摄氏度 |
| **功耗** | 瓦特 |
| **进程列表** | 当前 GPU 上的进程，支持终止操作 |

---

## 9. 系统设置

### 9.1 LLM 配置

| 配置项 | 说明 |
|--------|------|
| **API 地址** | LLM 服务的 OpenAI 兼容 API 地址 |
| **模型名称** | 使用的模型标识 |
| **API Key** | 认证密钥（显示时脱敏） |
| **连接测试** | 一键测试 LLM 服务连通性 |
| **快速切换** | 多套配置快速切换 |

### 9.2 网站通知

| 功能 | 说明 |
|------|------|
| **发布通知** | 管理员填写标题和内容，全站推送 |
| **通知记录** | 自动保存所有已发送通知 |
| **用户行为** | 浮窗查看，"不再通知"后不再弹出，新通知重新提醒 |
| **编辑/删除** | 管理员可二次编辑和删除通知 |

### 9.3 内容保护设置

- 保护功能总开关
- 各检测层阈值调整
- NSFW 关键词规则编辑

---

## 10. API 端点参考

### 10.1 基础

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | SPA 首页 |
| GET | `/api/version` | 应用版本号 |
| GET | `/api/logs` | 运行日志 |
| WS | `/ws` | WebSocket 实时通信 |

### 10.2 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 用户登录 |
| POST | `/auth/logout` | 退出登录 |
| GET | `/auth/me` | 当前用户信息 |
| POST | `/auth/change-password` | 修改密码 |

### 10.3 用户管理 (Admin)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/users` | 用户列表 |
| POST | `/api/users` | 创建用户 |
| PUT | `/api/users/{user_id}` | 更新用户 |
| DELETE | `/api/users/{user_id}` | 删除用户 |

### 10.4 GPU 与服务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 实例健康 + GPU 状态总览 |
| GET | `/api/gpu` | GPU 显存/功耗/温度 |
| GET | `/api/gpu-processes` | GPU 进程列表 |
| POST | `/api/gpu-processes/kill` | 终止 GPU 进程 |
| POST | `/api/comfyui/{action}` | 全局 ComfyUI 控制 (start/stop/restart) |
| GET | `/api/comfyui/status` | 所有实例详细状态 |
| POST | `/api/comfyui/{instance}/{action}` | 单实例控制 |
| POST | `/api/vllm/{action}` | vLLM 服务管理（已弃用） |

### 10.5 工作流管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workflows` | 工作流列表 |
| POST | `/api/workflows/sync` | 从远程同步工作流 |
| POST | `/api/workflows/upload` | 上传工作流 JSON |
| GET | `/api/workflows/find-closest` | 按名称/标签匹配最佳工作流 |
| GET | `/api/workflows/meta` | 工作流元数据 |
| POST | `/api/workflows/meta/sort` | 排序工作流 |
| PUT | `/api/workflows/meta/{filename}` | 更新元数据 |
| DELETE | `/api/workflows/meta/{filename}` | 删除元数据 |
| POST | `/api/workflows/meta/thumbnail` | 生成缩略图 |
| GET | `/api/workflows/thumbnail/{name}` | 获取缩略图 |
| PUT | `/api/workflows/{filename}/rename` | 重命名工作流 |
| DELETE | `/api/workflows/{name}` | 删除工作流 |
| GET | `/api/workflows/{name}/fields` | 解析可编辑字段 |
| GET | `/api/workflows/{name}/analyze` | 分析工作流结构 |
| GET | `/api/workflows/{name}/download` | 下载工作流 JSON |
| GET/PUT/DELETE | `/api/workflows/{name}/config` | 工作流配置 CRUD |
| GET | `/api/workflows/previews` | 工作流预览图 |
| GET/POST/DELETE | `/api/workflows/{name}/versions*` | 版本管理 |

### 10.6 生成任务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generate` | 提交生成任务 |
| GET | `/api/jobs` | 活跃任务列表 |
| GET | `/api/jobs/{job_id}` | 查询任务状态 |
| DELETE | `/api/jobs/{job_id}` | 取消任务 |
| DELETE | `/api/jobs/{job_id}/dismiss` | 清除已完成任务 |
| POST | `/api/jobs/{job_id}/retry` | 重试失败任务 |

### 10.7 提示词工具

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/prompt/optimize` | 提示词优化/润色 |
| POST | `/api/prompt/translate` | 中英提示词互译 |
| POST | `/api/prompt/interrogate` | 图片反推提示词 |

### 10.8 历史画廊

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history` | 历史列表（分页/筛选） |
| POST | `/api/history` | 手动添加历史 |
| GET | `/api/history/summary` | 历史统计摘要 |
| GET | `/api/history/user-counts` | 按用户统计 |
| GET | `/api/history/{item_id}` | 单条详情 |
| DELETE | `/api/history/{item_id}` | 软删除 |
| POST | `/api/history/{item_id}/restore` | 恢复 |
| POST | `/api/history/{item_id}/permanent-delete` | 永久删除 |
| POST | `/api/history/{item_id}/share` | 公开/取消公开 |
| POST | `/api/history/{item_id}/hide` | 隐藏 |
| POST | `/api/history/{item_id}/video-frame` | 提取视频帧 |
| POST | `/api/history/batch-*` | 批量操作 |
| POST | `/api/history/trash/clear` | 清空回收站 |
| DELETE | `/api/history` | 清空全部历史 |

### 10.9 媒体文件

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload-image` | 上传参考图片 |
| POST | `/api/upload-video` | 上传参考视频 |
| GET | `/api/input-image/{filename}` | 获取输入图片 |
| GET | `/api/input-video/{filename}` | 获取输入视频 |
| GET | `/api/images/{filename}` | 获取输出图片/视频 |
| GET | `/api/thumbs/{filename}` | 获取缩略图 |

### 10.10 设备/节点管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/nodes` | 节点列表 |
| GET | `/api/nodes/{nid}` | 单节点详情 |
| POST | `/api/nodes` | 添加节点 |
| PUT | `/api/nodes/reorder` | 排序 |
| PUT | `/api/nodes/{nid}` | 更新节点 |
| DELETE | `/api/nodes/{nid}` | 删除节点 |
| POST | `/api/nodes/{nid}/connect` | 连接 |
| POST | `/api/nodes/{nid}/disconnect` | 断开 |
| POST | `/api/nodes/{nid}/instances/{iid}/start` | 启动实例 |
| POST | `/api/nodes/{nid}/instances/{iid}/stop` | 停止实例 |
| POST | `/api/nodes/{nid}/instances/{iid}/restart` | 重启实例 |
| POST | `/api/nodes/{nid}/instances/{iid}/force-restart` | 强制重启 |
| POST | `/api/nodes/{nid}/discover` | 发现实例 |
| POST | `/api/nodes/{nid}/test` | 测试连接 |
| POST | `/api/nodes/{nid}/apply-scan` | 应用扫描结果 |
| GET | `/api/workflow-dirs` | 工作流目录列表 |
| POST/DELETE | `/api/workflow-dirs` | 目录管理 |

### 10.11 系统设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system-settings` | 获取系统设置 |
| PUT | `/api/system-settings` | 更新系统设置 |
| POST | `/api/system-settings/llm/test` | 测试 LLM 连接 |
| GET/POST/PUT/DELETE | `/api/site-notifications*` | 网站通知管理 |
