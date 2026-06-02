# Ez ComfyUI Showcase -- 全模块代码审查报告

**审查日期:** 2026-06-02
**项目版本:** v4.6.0
**审查范围:** app.py (9138行) + 12个前端模块 (15119行) + 8个后端模块 + 图片保护与LLM模块

---

## 统计总览

| 严重等级 | 后端API | 实例管理 | 前端JS | 图片保护/LLM | **合计** |
|---------|---------|---------|--------|-------------|---------|
| 严重     | 4       | 8       | 6      | 2           | **20**  |
| 中等     | 10      | 9       | 10     | 12          | **41**  |
| 低风险   | 7       | 8       | 6      | 6           | **27**  |
| **合计** | **21**  | **25**  | **22** | **20**      | **88**  |

---

## 第一部分: 严重问题 (需立即修复)

### 1.1 安全类严重问题

#### S-1 JWT 硬编码默认密钥
- **文件:** `app.py` 第 86-88 行
- **问题:** `SECRET_KEY` 回退到硬编码字符串 `"ez-comfyui-showcase-local-jwt-secret-v1"`。生产环境若未设置环境变量，攻击者可直接伪造任意 JWT，获取管理员权限。
- **修复:** 生产环境启动时检测不到 `JWT_SECRET_KEY` 则拒绝启动 (`sys.exit(1)`)。

#### S-2 自动创建 admin/admin 账户
- **文件:** `app.py` 第 1667-1673 行
- **问题:** 初始化时自动创建用户名和密码均为 `admin` 的管理员账户，且密码仅 5 字符，不满足注册时 min 6 的要求。
- **修复:** 改为首次启动引导流程，强制设置强密码。

#### S-3 大量敏感端点无需认证
- **文件:** `app.py` 多处
- **问题:** 12+ 个端点缺少认证依赖，包括 `/api/gpu`、`/api/gpu-processes`、`/api/images/{filename}`、`/api/input-image/{filename}`、`/api/workflow-dirs` 等。未登录用户可遍历文件、获取 GPU 信息、服务器进程信息。
- **修复:** 为所有涉及用户数据的端点添加 `Depends(get_current_user)`。

#### S-4 管理员创建用户默认密码 "admin"
- **文件:** `app.py` 第 8180 行、第 8345 行
- **问题:** `AdminUserCreateRequest` 默认密码 `"admin"`，管理员不传密码时自动使用弱密码。
- **修复:** 移除默认值，强制要求密码字段。

#### S-5 前端 innerHTML 未转义导致 XSS
- **文件:** `history.js` 第 1681 行、`card_manager.js` 第 811 行
- **问题:** `e.message` 未使用 `escH()` 转义直接拼入 innerHTML。若服务端返回含 HTML 的错误详情，可触发 DOM XSS。
- **修复:** 统一使用 `escH(e.message || 'unknown')`。

#### S-6 img src URL 未转义
- **文件:** `history.js` 第 505-508 行、`card_manager.js` 第 464-473 行
- **问题:** `j.image` 来自服务端的文件名直接用于 `src` 属性拼接，若含双引号可注入 HTML。
- **修复:** 所有拼接进 HTML 属性的字符串使用 `escA()` 转义。

#### S-7 Token 存储在 localStorage
- **文件:** `auth.js` 第 68-70 行
- **问题:** localStorage 对所有同源 JS 可见。任何 XSS 漏洞直接导致 token 泄漏 = 完整账户接管。
- **修复:** 迁移到 httpOnly Cookie + CSRF token，或实施严格 CSP。

#### S-8 Token 通过 WebSocket URL 查询参数传输
- **文件:** `poll_manager.js` 第 176 行
- **问题:** Token 出现在 URL 中，会被服务器日志、代理日志、浏览器历史、Referer 头捕获。
- **修复:** WS 连接建立后通过第一条消息或子协议头传输 token。

#### S-9 用户 prompt 无长度限制
- **文件:** `prompt_optimizer.py` 第 1210-1244 行
- **问题:** 所有 prompt 入口函数无长度限制，可提交百万字符 prompt 导致 LLM 服务 DoS。
- **修复:** 增加上限 10000 字符。

#### S-10 LLM API Key 泄露路径
- **文件:** `llm_client.py` 第 70-71 行
- **问题:** `get_llm_client_settings()` 返回包含 `api_key` 的完整字典，若通过 API/日志暴露将泄露密钥。
- **修复:** 返回前脱敏 api_key。

### 1.2 并发/稳定性严重问题

#### S-11 信号量 double-release
- **文件:** `job_runner.py` 第 770-778 行 + 第 667-670 行
- **问题:** `cancel()` 和 `run()` 的 finally 块都会释放信号量，导致计数溢出，破坏"每实例一次一任务"互斥语义，可能并发出图引发 GPU OOM。
- **修复:** 设置 `job["cancelled"]` 标记，信号量释放逻辑集中到一处。

#### S-12 递归调用 `run()` 重试导致状态泄漏
- **文件:** `job_runner.py` 第 566-572 行
- **问题:** `PromptStartTimeout` 时递归调用自身重试，内层/外层 finally 都会执行释放和恢复操作。
- **修复:** 改为 while 循环重试。

#### S-13 cancel() 可能释放错误的信号量
- **文件:** `job_runner.py` 第 770-778 行
- **问题:** `cancel()` 按 `job.get("instance")` 释放，但 `run()` 中信号量有 fallback 逻辑，实际获取的可能不是同一对象，导致实例永久死锁。
- **修复:** 在 job 字典中记录实际信号量对象。

#### S-14 cancel() 删除 job 后 run() 中 KeyError
- **文件:** `job_runner.py` 第 779 行
- **问题:** `cancel()` 直接 `del self._jobs[job_id]`，`run()` 仍在执行中，后续访问触发 KeyError。
- **修复:** 改为设置 `job["status"] = "cancelled"` 标记而非删除。

#### S-15 `_has_active_jobs` 始终返回 False
- **文件:** `instance_manager.py` 第 521-531 行
- **问题:** 硬编码返回 `False` (TODO)，空闲回收循环无法感知运行中的任务，可能在长任务执行期间误杀实例。
- **修复:** 注入 JobRunner 查询函数或查询 ComfyUI `/queue` 端点。

#### S-16 同步阻塞调用在 async 上下文中
- **文件:** `instance_manager.py` 第 276-458 行
- **问题:** `urllib.request.urlopen()`、`subprocess.run()`、`time.sleep(2)` 直接在事件循环中执行，健康检查循环可阻塞事件循环 20+ 秒。
- **修复:** 使用 `asyncio.to_thread()` 包装，并行化健康检查。

#### S-17 WebSocket 无 ping/pong 心跳配置
- **文件:** `ws_tracker.py` 第 308 行
- **问题:** 长时间生成任务中 WS 连接可能被 Nginx 反代静默断开，前端 5 分钟无进度更新。
- **修复:** 显式配置 `ping_interval=20, ping_timeout=10`。

#### S-18 WS 断线后不尝试重连
- **文件:** `ws_tracker.py` 第 500-502 行
- **问题:** 连接断开直接退化 HTTP polling，无重连尝试。网络抖动后用户完全失去实时进度。
- **修复:** 断线前尝试 1-2 次 WS 重连。

#### S-19 gallery 卡片事件监听器累积泄漏
- **文件:** `card_manager.js` 第 394-398 行、`history.js` 第 851-855 行
- **问题:** 每张视频卡片绑定 mouseenter/mouseleave，DOM 重建后闭包引用延迟回收，长时间浏览可导致内存膨胀。
- **修复:** 改用事件委托。

#### S-20 `_last_active` 双字典不一致
- **文件:** `instance_manager.py` 第 77 行 + `job_runner.py` 第 672 行
- **问题:** InstanceManager 和 JobRunner 各自维护独立的 `last_active` 记录，若非同一引用，空闲回收无法感知 JobRunner 的活跃时间，可能误停所有实例。
- **修复:** 统一为 InstanceManager 暴露 `mark_active` API。

---

## 第二部分: 中等风险问题

### 2.1 认证与权限 (6个)

| ID | 问题 | 位置 |
|----|------|------|
| M-1 | JWT token 有效期 31 天，无撤销机制 | `app.py:90` |
| M-2 | 登录/注册无速率限制、无 CAPTCHA | `app.py:8236,8259` |
| M-3 | WebSocket 接受无效 token 连接 | `app.py:8577-8593` |
| M-4 | 登出仅清除客户端，不通知服务端 | `auth.js:211-219` |
| M-5 | 无 token 刷新/过期主动处理 | `auth.js:221-246` |
| M-6 | 新用户默认密码 'admin' (前端) | `auth.js:1173` |

### 2.2 输入校验与注入 (6个)

| ID | 问题 | 位置 |
|----|------|------|
| M-7 | `/api/history` POST 无输入验证，可注入伪造记录 | `app.py:7712-7717` |
| M-8 | 上传接口无文件大小限制，可 OOM | `app.py:6693-6731` |
| M-9 | 工作流上传文件名未过滤路径遍历 | `app.py:6542-6575` |
| M-10 | 节点发现接口 SSRF 风险 | `app.py:8889-8944` |
| M-11 | 用户 prompt 直接嵌入 LLM 请求，无注入防护 | `prompt_optimizer.py:1210-1244` |
| M-12 | `ast.literal_eval` 用于 LLM 输出解析 | `prompt_optimizer.py:451-457` |

### 2.3 NSFW 检测与图片保护 (6个)

| ID | 问题 | 位置 |
|----|------|------|
| M-13 | NSFW 正则可被 Unicode 变体绕过 | `image_protection.py:12-33` |
| M-14 | 皮肤检测启发式误判率高 | `image_protection.py:375-388` |
| M-15 | 保护可通过 API 完全禁用 | `image_protection.py:60-76` |
| M-16 | 检测阈值可通过 API 设为 1.0 使保护失效 | `image_protection.py:117-129` |
| M-17 | NSFW 正则模式可通过 API 替换为空串 | `image_protection.py:130-134` |
| M-18 | LLM 配置更新缺少审计日志 | `llm_client.py:44-67` |

### 2.4 错误处理与信息泄露 (4个)

| ID | 问题 | 位置 |
|----|------|------|
| M-19 | 错误响应暴露内部实现细节 | `app.py:6708,6730,8436` |
| M-20 | LLM 错误消息泄露原始响应 | `llm_client.py:185` |
| M-21 | SSH StrictHostKeyChecking=no | `app.py:1162,1171` |
| M-22 | LLM 图片反推失败无降级策略 | `prompt_interrogator.py:4197-4246` |

### 2.5 异步与资源管理 (7个)

| ID | 问题 | 位置 |
|----|------|------|
| M-23 | `_save_output` 中同步 `time.sleep(1)` 阻塞事件循环最长 30 秒 | `job_runner.py:908` |
| M-24 | HTTP polling 兜底循环缺取消检查，取消后仍等 5 分钟 | `job_runner.py:583-614` |
| M-25 | 后台循环异常被完全吞没 | `instance_manager.py:355-356` |
| M-26 | WS 进度回调异常被完全吞没 | `ws_tracker.py:892-908` |
| M-27 | LLM 客户端无请求频率限制 | `llm_client.py` 全文 |
| M-28 | LLM base_url 未做白名单校验 (SSRF) | `llm_client.py:95-96` |
| M-29 | `historyItems` 数组并发修改风险 | `history.js` 全局 |

### 2.6 路由与调度 (3个)

| ID | 问题 | 位置 |
|----|------|------|
| M-30 | `strict_preferred` 路由在实例忙碌时可能饿死 | `instance_picker.py:106-118` |
| M-31 | 评分函数 load 权重过大，负载分散失效 | `instance_picker.py:167` |
| M-32 | 拓扑排序 O(V*E) 性能问题 | `step_calculator.py:410-421` |

### 2.7 前端代码质量 (4个)

| ID | 问题 | 位置 |
|----|------|------|
| M-33 | onclick 内联处理器嵌入服务器数据 (XSS 风险) | `history.js:542-546` |
| M-34 | doGenerate 重入保护仅依赖按钮 disabled | `generate.js:1226-1399` |
| M-35 | window 级事件监听器未清理 | `generate.js:2087-2088` |
| M-36 | history.js 和 card_manager.js 大量重复代码 | 两个文件 ~200 行重复 |

---

## 第三部分: 低风险问题 (27个)

### 后端 (7个)
- 用户名无字符白名单校验 (`app.py:8238`)
- 动态 SQL 构造模式需警惕 (`app.py:8390`)
- 文件名随机性仅 9000 值 (`app.py:6698`)
- SSH 密码通过命令行参数传递 (多处)
- 硬编码路径暴露目录结构 (`app.py:2706`)
- 路径遍历防护正确但 macOS 大小写不敏感风险 (`app.py:1298`)
- CORS 未显式配置 (`app.py` 全文)

### 实例管理 (8个)
- `_start_locks` 并发创建模式不安全 (`instance_manager.py:116`)
- `_get_node_by_id` 始终返回 None (`instance_manager.py:475`)
- WS timeout 可能为负值 (`ws_tracker.py:558`)
- `resume()` 只做单次 WS 连接尝试 (`ws_tracker.py:379`)
- 评分函数权重细节 (`instance_picker.py:167`)
- 使用 threading.Lock 而非无需锁 (`time_estimator.py:9`)
- 历史数据无持久化 (`time_estimator.py:21`)
- `total_units` 为 0 边界情况 (`step_calculator.py:143`)

### 前端 (6个)
- Job ID 直接用于 CSS 选择器拼接 (`history.js:566`)
- IntersectionObserver 实例可能累积 (`history.js:432`)
- 多处使用 `alert()` 而非 `CW.toast()` (多处)
- 错误响应直接展示服务端 detail 字段 (多处)
- `var`/`const`/`let` 混用 (`generate.js`, `history.js`)
- `javascript:` 协议 href (`auth.js:308`)

### 图片保护/LLM (6个)
- 模型加载失败时静默降级到启发式 (`image_protection.py:245`)
- PIL Image.open 未设置解压炸弹保护 (`image_protection.py:339`)
- `image_to_data_url` 无文件大小限制 (`llm_client.py:74`)
- MIME 类型通过扩展名猜测 (`llm_client.py:75`)
- 环境变量默认值使用 HTTP (`llm_client.py:14`)
- media_outputs 缺少 `.gif` 等格式 (`media_outputs.py:9`)

---

## 第四部分: 优先修复路线图

### 阶段一: 紧急安全修复 (1-2 天)

1. **JWT 密钥强制化** -- 启动时检测环境变量，缺失则拒绝启动
2. **移除默认 admin 密码** -- 改为首次启动引导设置
3. **敏感端点加认证** -- 至少覆盖 `/api/images/`、`/api/gpu`、`/api/gpu-processes`、`/api/input-*`
4. **修复信号量 double-release** -- 统一信号量释放逻辑到单一位置
5. **修复 `_has_active_jobs`** -- 注入 JobRunner 查询或调用 ComfyUI `/queue`
6. **前端 XSS 修复** -- 所有 innerHTML 拼接处统一 `escH()`/`escA()` 转义

### 阶段二: 稳定性修复 (3-5 天)

7. **async 阻塞调用改造** -- `asyncio.to_thread()` 包装所有同步 IO
8. **WS 心跳与重连** -- 配置 ping_interval，断线尝试重连
9. **cancel() 逻辑重写** -- 标记式取消 + 协程级别 task.cancel()
10. **prompt 长度限制** -- 所有入口增加 10000 字符上限
11. **API Key 脱敏** -- `get_llm_client_settings()` 返回前脱敏
12. **PIL 解压炸弹保护** -- 设置 `Image.MAX_IMAGE_PIXELS`

### 阶段三: 架构改进 (1-2 周)

13. **Token 机制升级** -- httpOnly Cookie + refresh token + 黑名单
14. **统一 last_active 管理** -- 消除 InstanceManager/JobRunner 双字典
15. **前端代码去重** -- card_manager.js 统一渲染逻辑
16. **事件委托改造** -- 替代逐卡片事件绑定
17. **LLM 频率限制与审计** -- 添加请求计数和配置变更日志
18. **NSFW Unicode 规范化** -- 匹配前 NFKD 规范化 + 零宽字符清除
19. **登录速率限制** -- 失败锁定 + IP 限流
20. **错误消息脱敏** -- 对外通用错误，详细信息仅记日志
