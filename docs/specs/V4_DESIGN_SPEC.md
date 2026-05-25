# V4 视觉改版设计规范 — Crypto-Wallet · Dark OLED · Bento Box

> 项目：Ez ComfyUI Showcase
> 分支：4.0-beta
> 状态：✅ 已实施

---

## 1. 设计语言

### 品牌定位
金融级精密感 × 创意工具 × Dark OLED

### 关键词
- 精密、金融、深色、毛玻璃
- 非对称网格（Bento Box）
- 金紫双色系统

---

## 2. 色彩系统

### 背景层级（OLED 优先）
```css
--bg-deep:     #000000;   /* 真黑 OLED — 主体背景 */
--bg-base:     #0A0A0F;   /* 略升 — 次要背景 */
--bg-elevated: #111118;   /* 卡片/面板 */
--bg-card:     #1A1A28;   /* 卡片内部 */
--bg-glass:    rgba(255,255,255,0.03); /* 毛玻璃底色 */
```

### 强调色（Crypto Gold + Purple）
```css
--accent:       #F59E0B;   /* 金 — 主强调色 */
--accent-dim:   #D97706;   /* 暗金 — hover */
--accent-glow:  rgba(245,158,11,0.25); /* 发光 */
--purple:       #8B5CF6;   /* 紫 — 次强调 */
--purple-dim:   #7C3AED;   /* 暗紫 */
--purple-glow:  rgba(139,92,246,0.25);
```

### 文字
```css
--text:           #F1F5F9;   /* 主文字 */
--text-secondary: #94A3B8;   /* 次要文字 */
--dim:            #64748B;   /* 弱化文字 */
```

### 语义色
```css
--green:  #22C55E;
--red:    #EF4444;
--orange: #F59E0B;   /* 复用 gold */
--yellow: #EAB308;
--blue:   #3B82F6;
```

### 边框
```css
--border:        rgba(255,255,255,0.06);
--border-hover:  rgba(255,255,255,0.12);
--border-accent: rgba(245,158,11,0.3);
--border-purple: rgba(139,92,246,0.3);
```

---

## 3. 字体系统

```css
--font-sans: 'Fira Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: 'Fira Code', 'SF Mono', 'Monaco', 'Cascadia Code', monospace;
```

### 加载方式
HTML `<head>` 中通过 Google Fonts 预加载：
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

---

## 4. 布局：Bento Box Grid

### 目标
将传统三栏布局改为**非对称 Bento Grid**，提升视觉层次感和信息密度。

### 布局方案
```
┌──────────────────────────────────────────────┐
│ Titlebar (glassmorphism, gold accent)         │
├──────────────────────────────────────────────┤
│ Statusbar (compact, gold glow)               │
├──────────────┬───────────────────────────────┤
│              │                               │
│  BENTO LEFT  │   BENTO RIGHT (Gallery)       │
│              │                               │
│ ┌──┬──┐     │  ┌──────┬──────┬──────┐      │
│ │WF│WF│     │  │ Tile  │ Tile  │ Tile  │      │
│ │  │  │     │  ├──────┼──────┼──────┤      │
│ ├──┴──┤     │  │ Tile  │ Tile  │ Tile  │      │
│ │Gen  │     │  ├──────┴──────┴──────┤      │
│ │Form │     │  │  Bottom controls    │      │
│ └─────┘     │  └─────────────────────┘      │
└──────────────┴───────────────────────────────┘
```

### 实现要点
- CSS Grid `grid-template-areas` 实现非对称
- 画廊区部分卡片 2×2，大部分 1×1
- 工作流卡片区：水平滚动 + 毛玻璃小卡片
- Gen Form：可折叠

---

## 5. 毛玻璃效果（Glassmorphism）

### 标准 Glass Card
```css
.glass-card {
  background: var(--bg-glass);
  backdrop-filter: blur(12px) saturate(1.1);
  -webkit-backdrop-filter: blur(12px) saturate(1.1);
  border: 1px solid var(--border);
  border-radius: var(--radius-glass, 14px);
  box-shadow: var(--shadow-glass, 0 4px 20px rgba(0,0,0,0.4));
}
```

### 应用范围
| 组件 | 状态 |
|------|------|
| 工作流卡片 (.wf-card) | ✅ |
| 出图历史卡片 (.gi) | ✅ |
| 工作流管理弹窗 (.wf-mgr-card) | ✅ |
| 设备卡片 (.device-card) | ✅ |
| 实例管理弹窗 (.inst-card, .inst-popup) | ✅ |
| 节点编辑弹窗 (.ne-card, .de-card) | ✅ |

---

## 6. 动画系统

### 卡片入场
```css
@keyframes cardIn {
  from { opacity: 0; transform: translateY(12px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
```

### 生成中动画
```css
@keyframes cryptoGlow {
  0%, 100% { box-shadow: 0 0 18px rgba(245,158,11,0.2); }
  50% { box-shadow: 0 0 28px rgba(139,92,246,0.25); }
}
```

### 悬浮微动
卡片 hover 时 `transform: translateY(-2px)`

### 占位渐变
生成中卡片背景：金→紫径向渐变，`gradShift` 动画 12s 循环

---

## 7. 品牌元素

### Favicon
金紫渐变钻石/六边形 SVG（已更新）

### Logo
`<span style="background:linear-gradient(135deg,#F59E0B,#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent">Ez ComfyUI</span>`

### 标题栏图标
金紫渐变钻石 SVG 代替原调色板 🎨 图标

---

## 8. 已改动文件

| 文件 | 改动内容 | 状态 |
|------|----------|------|
| `static/css/style.css` | CSS 设计系统全面替换（OLED + 金紫 + 毛玻璃 + 动画） | ✅ |
| `static/index.html` | Google Fonts + favicon + logo + data-theme + 缓存版本 | ✅ |
| `V4_DESIGN_SPEC.md` | 本文档 | ✅ |

## 9. 部署与运维

### 部署架构
```
外网用户 → imdjj.cn:1313 (RouterOS NAT) → Mac mini nginx:1313
                                       ├── /comfy/  → 127.0.0.1:18000 (FastAPI Python)
                                       └── /dgx/    → 10.10.10.75:xxxx (DGX ComfyUI 实例)

旧版（3.x）继续运行：imdjj.cn:1213/comfy/ → DGX:9091
```

### 后端服务

| 项目 | 值 |
|------|-----|
| 端口 | **18000** |
| 进程管理 | `nohup python3 app.py`（环境变量 `EZ_COMFYUI_PORT=18000`） |
| 日志 | `/tmp/ez_v4.log` |
| 4.0-beta 路径 | `/Users/ai/.openclaw/workspace/ez-comfyui-showcase/` |

### 启动命令
```bash
cd /Users/ai/.openclaw/workspace/ez-comfyui-showcase
EZ_COMFYUI_PORT=18000 nohup python3 app.py > /tmp/ez_v4.log 2>&1 &
```

### nginx 配置

**配置文件：** `/opt/homebrew/etc/nginx/servers/imdjj.cn.conf`

**关键路由：**
| 路径 | 目标 | 说明 |
|------|------|------|
| `/comfy/` | `127.0.0.1:18000` | V4 面板（Mac mini 本地） |
| `/dgx/8190/` | `10.10.10.75:8190` | DGX 实例 A（ComfyUI） |
| `/dgx/8189/` | `10.10.10.75:8189` | DGX 实例 B（ComfyUI） |

**重载命令：**
```bash
sudo cp /tmp/imdjj_1313.conf /opt/homebrew/etc/nginx/servers/imdjj.cn.conf
sudo nginx -s reload
```

### 当前进程状态
- Backend PID: 18243 (port 18000, 200 ✅)
- nginx master PID: 1389

---

## 10. V4 功能路线图（未完成）

**当前状态：视觉改版已完成，功能模块未动。**

### Phase 1 — 用户基础认证
- [ ] SQLite 用户表：id, username, phone, password_hash, avatar, created_at
- [ ] JWT token 认证（前端 localStorage，后端验证）
- [ ] API 加 `/auth/` 前缀：注册、登录、登出、修改密码
- [ ] 前端：登录/注册弹窗，未登录只看公共图

### Phase 2 — 手机验证码
- [ ] 短信 API（阿里云/腾讯云 SMS）
- [ ] 验证码存储（SQLite + 过期时间）
- [ ] 流程：输入手机号 → 发验证码 → 验证通过 → 自动创建账户

### Phase 3 — 微信扫码登录
- [ ] 微信开放平台 OAuth2.0
- [ ] 扫码 → 回调 → 绑定/创建账户
- [ ] 需要微信开放平台 AppID

### Phase 4 — 多用户数据隔离
- [ ] 每个用户的图片、工作流独立存储
- [ ] user_images 表：user_id, image_path, ...
- [ ] user_workflows 表：user_id, workflow_name, ...
- [ ] 公共图库：用户主动"分享"的图片

### Phase 5 — 设备管理
- [ ] 设备能力清单（已安装节点 + 已部署模型）
- [ ] 面板 → 设备兼容性校验
- [ ] 自动补全缺失节点/模型
- [ ] 多设备并行出图
- [ ] 设备状态监控（GPU/VRAM/温度）

### Phase 6 — 工作流管理增强
- [ ] workflow 文件埋 required_nodes / required_models 元数据
- [ ] 选工作流 + 选设备时自动校验兼容性
- [ ] 工作流版本管理
- [ ] 远程同步工作流

---

## 11. 遗留/待办

- [ ] 实际部署到生产环境测试视觉表现
- [ ] Bento Box 布局的 CSS grid 实现细节验证
- [ ] 移动端响应式检查
