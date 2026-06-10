# UI/UX 优化 — 基于 UI UX Pro Max 设计建议

## 项目类型分析
- **产品类型**: 图像生成工具 / 创意仪表盘 / 画廊
- **推荐风格**: Dark Mode (OLED) + 创意工具暗色主题
- **推荐字体**: Fira Code + Fira Sans（仪表盘/数据/技术类最优搭配）
- **推荐配色**: 深色背景 + 品红/蓝紫强调色（创意平台风格）

## 修改清单

### 1. 字体系统 — 引入 Fira Code + Fira Sans
在 index.html 中加载 Google Fonts：
```html
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```
在 style.css 中设置：
```css
:root {
  --font-sans: 'Fira Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'Fira Code', 'Monaco', 'Cascadia Code', monospace;
}
body { font-family: var(--font-sans); }
code, pre, .mono { font-family: var(--font-mono); }
```

### 2. 色彩系统 — CSS 变量统一
当前 style.css 中已有部分 CSS 变量。统一调整为：

```css
:root {
  /* 背景层级 */
  --bg-deep: #0a0a0f;
  --bg-base: #12121a;
  --bg-elevated: #1a1a26;
  --bg-card: #1e1e2e;

  /* 文字 */
  --text: #e4e4ef;
  --text-secondary: #8a8f98;
  --dim: #6b7280;

  /* 强调色 - 紫蓝渐变系（适合创意工具） */
  --accent: #5e6ad2;
  --accent-glow: rgba(94, 106, 210, 0.3);
  --accent-hover: #4f5ab8;

  /* 语义色 */
  --green: #22c55e;
  --red: #ef4444;
  --orange: #f59e0b;
  --yellow: #eab308;
  --blue: #3b82f6;

  /* 边框 */
  --border: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(255, 255, 255, 0.15);

  /* 圆角 */
  --radius: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;

  /* 阴影 */
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.5);
}
```

### 3. 卡片样式优化
出图卡片、设备卡片、工作流卡片统一圆角和阴影：
```css
.card, .device-card, .gi, .wf-mgr-card {
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  transition: all 0.2s ease;
}
.card:hover, .device-card:hover, .gi:hover, .wf-mgr-card:hover {
  border-color: var(--border-hover);
  box-shadow: var(--shadow-md);
}
```

### 4. 操作按钮视觉优化
按钮增加过渡动画和悬停效果：
```css
.wf-mgr-btn {
  transition: all 0.15s ease;
  border-radius: 6px;
}
.wf-mgr-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
.wf-mgr-btn:active {
  transform: translateY(0);
}
```

### 5. 间距统一
替换各处零散的 padding/margin 为统一的间距变量：
```css
:root {
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
}
```

### 6. 加载/过渡动画
为出图卡片和工作流列表增加入场动画：
```css
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
.gi, .wf-mgr-card {
  animation: fadeInUp 0.3s ease both;
}
.gi:nth-child(2) { animation-delay: 0.05s; }
.gi:nth-child(3) { animation-delay: 0.1s; }
/* etc */
```

## 涉及文件
- `static/index.html` — Google Fonts 加载
- `static/css/style.css` — 主题变量、卡片、按钮、动画

## 约束
- 不要改变现有的 HTML 结构和功能逻辑
- 只修改 CSS 和 index.html 的 font 加载
- 保持暗色主题基调不变
- 优化后检查所有页面元素正常显示
- 更新 index.html 中 style.css 缓存版本号
