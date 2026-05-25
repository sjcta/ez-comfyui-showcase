# Icon Migration — 统一使用 SVG 图标系统

## 背景
项目中已有 SVG 图标系统 `CW.icon(name)`，图标定义在 index.html 的 `<svg>` sprite 中。
但设备管理页面等新功能使用了 emoji/unicode 字符代替图标，导致视觉不一致。

## 需要修改的文件
- `static/index.html`
- `static/js/modules/nodes.js`

## 图标映射表

| 当前 Emoji | 位置 | 应替换为 |
|-----------|------|---------|
| `🖥️ 设备` | toolbar 按钮 (line 194) | `CW.icon('settings-2') + ' 设备'` |
| `🔗 打开` | 实例行操作按钮 | `CW.icon('send') + ' 打开'` |
| `🔑 SSH` | SSH 信息按钮 | `CW.icon('settings') + ' SSH'` |
| `🔍 测连通` | 底部操作 | `CW.icon('search') + ' 测连通'` |
| `🔎 扫端口` | 底部操作 | `CW.icon('sliders') + ' 扫端口'` |
| `✏️ 编辑` | 设备编辑按钮 | `CW.icon('pencil') + ' 编辑'` |
| `🗑 删除` | 设备删除按钮 | `CW.icon('trash-2') + ' 删除'` |
| `⟳ 同步` | 远程同步按钮 | `CW.icon('refresh-cw') + ' 同步'` |
| `🖥️ 设备管理` | overlay 标题 | `CW.icon('settings-2') + ' 设备管理'` |
| `📋 基础信息` | 表单 section 标题 | `CW.icon('file-text') + ' 基础信息'` |
| `🔑 SSH 连接配置` | 表单 section 标题 | `CW.icon('settings') + ' SSH 连接配置'` |
| `⚙️ 实例预设` | 表单 section 标题 | `CW.icon('settings') + ' 实例预设'` |
| `📡 已登记实例` | 表单 section 标题 | `CW.icon('sliders') + ' 已登记实例'` |

## 代码替换示例

**HTML 中（index.html）：**
```html
<!-- 旧 -->
<button ...>🖥️ 设备</button>
<!-- 新 -->
<button ...>${CW.icon('settings-2')} 设备</button>
```

注意 HTML 中直接写 `CW.icon()` 需要通过 `onclick` 或动态生成。对于静态 HTML，使用 `<svg>` inline 或通过 JS 动态设置 innerHTML。

**JS 中（nodes.js）：**
```javascript
// 旧
html += '<button ...>🔗 打开</button>';
// 新
html += '<button ...>' + CW.icon('send') + ' 打开</button>';
```

## 完成条件
- [ ] toolbar 设备按钮改为 SVG 图标
- [ ] 所有设备卡片操作按钮使用 SVG 图标
- [ ] 设备管理 overlay 标题使用 SVG 图标
- [ ] 设备编辑表单 section 标题使用 SVG 图标
- [ ] 不要破坏按钮功能
