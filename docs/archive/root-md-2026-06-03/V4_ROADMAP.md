# Ez ComfyUI Showcase — V4 全量任务拆解

> 生成时间: 2026-05-13 03:00
> 负责人: 大总管（main agent）
> 原则: 每完成一项 → 严格审查（代码+视觉+交互）→ 通过才进入下一项

---

## Phase 1 — 用户认证系统（基础）

### P1-T1 后端：用户模型 + SQLite 表
- [ ] 创建 `users` 表（id, username, password_hash, avatar, created_at, updated_at）
- [ ] 密码加密存储（bcrypt/argon2）
- [ ] 用户注册 API：`POST /auth/register`
- [ ] 用户登录 API：`POST /auth/login` → 返回 JWT
- [ ] JWT token 生成与验证中间件
- [ ] Token 刷新 API：`POST /auth/refresh`
- [ ] 修改密码 API：`POST /auth/change-password`

### P1-T2 前端：登录/注册弹窗
- [ ] 登录弹窗（模态框）：用户名 + 密码 + 登录按钮
- [ ] 注册弹窗：用户名 + 密码 + 确认密码 + 注册按钮
- [ ] JWT token 存入 localStorage
- [ ] 请求拦截器自动带 Authorization header
- [ ] 登录状态持久化（页面刷新不丢失）
- [ ] 登录/注册成功/失败 toast 提示
- [ ] 弹窗动画（与 V4 风格一致的金紫主题）

### P1-T3 前端：登录态 UI 联动
- [ ] 未登录：右上角显示「登录」「注册」按钮
- [ ] 已登录：右上角显示用户名 + 头像 + 退出按钮
- [ ] 未登录：画廊仅显示公共图片，出图按钮禁用+提示登录
- [ ] 已登录：完整功能可用
- [ ] 退出登录：清除 token + 回到未登录视图

### P1-T4 严格审查项
- [ ] 密码传输是否 HTTPS（✅ 已有 nginx SSL）
- [ ] JWT 密钥安全性（环境变量，不硬编码）
- [ ] Token 过期机制（建议 7 天 + refresh）
- [ ] XSS 防护（所有用户输入转义）
- [ ] SQL 注入防护（参数化查询）
- [ ] 前端路由守卫（未登录不能访问受限页面）
- [ ] API 鉴权中间件覆盖所有受限接口
- [ ] 弹窗视觉符合 V4 Design Spec（金紫 + 毛玻璃 + 动画）
- [ ] 移动端适配

---

## Phase 2 — 手机验证码登录

### P2-T1 后端：验证码系统
- [ ] 短信 API 接入（阿里云/腾讯云 SMS）
- [ ] 验证码生成 + 存储（SQLite + 5分钟过期）
- [ ] 发送验证码 API：`POST /auth/send-code`
- [ ] 验证码登录 API：`POST /auth/login-with-code`
- [ ] 手机号绑定/修改

### P2-T2 前端：验证码登录流
- [ ] 输入手机号 → 发送验证码 → 输入验证码 → 自动登录
- [ ] 60秒倒计时重发
- [ ] 手机号格式校验
- [ ] 视觉一致

### P2-T3 审查
- [ ] 短信轰炸防护（同一手机号 1 分钟/次）
- [ ] 验证码暴力破解防护（5次错误锁定）
- [ ] 手机号隐私处理

---

## Phase 3 — 微信扫码登录

### P3-T1 微信 OAuth
- [ ] 微信开放平台 AppID/Secret 配置
- [ ] 生成扫码二维码 API
- [ ] 回调处理 + 绑定/创建账户

### P3-T2 前端
- [ ] 扫码弹窗（二维码展示）
- [ ] 扫码成功后自动跳转

---

## Phase 4 — 多用户数据隔离

### P4-T1 后端：数据分离
- [ ] `user_images` 表（user_id, path, prompt, params, created_at）
- [ ] `user_workflows` 表（user_id, name, json_data, version, created_at）
- [ ] 图片查询 API 增加 user_id 过滤
- [ ] 工作流 CRUD 增加 user_id 归属

### P4-T2 前端：个人空间
- [ ] "我的图片" 标签（仅自己的出图）
- [ ] "我的工作流" 标签
- [ ] 公共图库（用户主动分享）
- [ ] 图片分享/取消分享 toggle
- [ ] 用户主页/个人设置页面

---

## Phase 5 — 设备管理系统

### P5-T1 设备能力清单
- [ ] 设备注册时扫描已安装 ComfyUI 节点
- [ ] 设备注册时扫描已部署模型
- [ ] 能力数据可视化展示

### P5-T2 兼容性校验
- [ ] workflow 文件注入 `required_nodes` / `required_models` 元数据
- [ ] 选 workflow + 选设备 → 自动校验兼容性
- [ ] 不兼容时提示缺失项 + 建议操作

### P5-T3 自动补全
- [ ] ComfyUI Manager API 远程安装节点
- [ ] 自动下载缺失模型（HF/GitHub）
- [ ] 进度展示

### P5-T4 多设备并行
- [ ] 出图面板增加设备选择器
- [ ] 提交到远程设备 ComfyUI
- [ ] WebSocket 追踪进度
- [ ] 结果回传本地

---

## Phase 6 — 工作流增强

### P6-T1 元数据体系
- [ ] workflow JSON 注入 required_nodes/required_models
- [ ] 标签系统完善

### P6-T2 版本管理完善
- [ ] 已有版本管理功能打磨
- [ ] 版本对比 diff

### P6-T3 远程同步
- [ ] 已有同步功能打磨
- [ ] 多设备源同步

---

## 执行顺序与优先级

```
Phase 1 (认证) → Phase 4 (数据隔离) → Phase 5 (设备管理) → Phase 6 (工作流增强)
     ↘ Phase 2 (手机验证码) → Phase 3 (微信扫码)
```

**建议开工顺序：** P1-T1 → P1-T2 → P1-T3 → P1-T4（审查）→ P4-T1 → P4-T2 → ...

当前先做 Phase 1，因为认证是所有后续功能的基础。
