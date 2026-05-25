# Ez ComfyUI Showcase — 项目开发规范

> 所有新开发的功能、修改、重构，必须遵守以下规范。
> 违反规范的代码在验收时将被打回重做。

---

## 1. 局部刷新（Partial DOM Update）

### 原则
任何用户操作触发的 UI 更新，**不得全量刷新整个列表/页面**。

### ❌ 禁止
```javascript
// 操作成功后全量刷新，导致闪烁
function doSomething() {
  await fetch(...);
  loadNodes();  // ← 禁止：全量刷新整个设备列表
}
```

### ✅ 允许
```javascript
function doSomething(id) {
  await fetch(...);
  updateRow(id);  // ← 允许：只更新受影响的行
}

function updateRow(id) {
  // 通过 API 获取最新单条数据
  var data = await fetch('/api/items/' + id);
  // DOM 定位 + 局部更新
  var row = document.querySelector('[data-id="' + id + '"]');
  row.querySelector('.status').textContent = data.status;
  row.querySelector('.btn-group').innerHTML = buildButtons(data);
}
```

### 实现模式
1. 每个可操作的元素上设置 `data-xxx` 属性用于 DOM 定位（如 `data-nid`, `data-iid`）
2. 操作成功后调用专门的局部更新函数，不调用全量刷新函数
3. 局部更新函数只更新：状态文字、状态灯颜色、操作按钮组
4. 仅在以下情况允许全量刷新：页面初始化加载、用户点击"刷新"按钮、局部更新失败时的异常降级

---

## 2. 模块化设计（Modular Design）

### 原则
所有功能按模块拆分，每个 JS 文件一个模块，模块间通过 `window.CW` 或 `window.__APP__` 共享接口。

### 模块结构
```javascript
// static/js/modules/xxx.js
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API;

  // ── 私有函数 ──
  function _privateHelper() { ... }

  // ── 公开函数 ──
  function publicFunction() { ... }

  // ── 导出 ──
  if (!window.CW) window.CW = {};
  window.CW.publicFunction = publicFunction;
})();
```

### 规则
- 每个模块使用 IIFE（Immediately Invoked Function Expression）包裹
- 严格模式 `'use strict'`
- 从 `window.__APP__` 获取共享工具（`$`, `$$`, `escH`, `escA`, `API`）
- 公开接口通过 `window.CW` 导出
- 私有函数以下划线 `_` 开头
- 禁止模块间直接引用对方的私有变量

### 现有模块清单
| 文件 | 职责 |
|------|------|
| app.js | 主入口，__APP__ 初始化，WebSocket，全局状态 |
| icons.js | SVG 图标助手 CW.icon() |
| status.js | 状态栏 GPU/服务状态 |
| node-editor.js | 工作流 ComfyUI 节点编辑器 |
| ui.js | UI 工具函数 |
| workflows.js | 工作流管理（列表/同步/上传/编辑） |
| history.js | 出图历史/图片画廊 |
| generate.js | 出图表单/参数设置 |
| nodes.js | 设备管理 |

---

## 3. 禁止行内样式（No Inline Styles）

### 原则
所有样式定义在 `static/css/style.css` 中，不得在 HTML/JS 中使用行内 `style` 属性。

### ❌ 禁止
```html
<div style="display:flex;align-items:center;padding:8px">...</div>
```
```javascript
element.style.color = 'red';
element.style.display = 'none';
```
```javascript
html += '<span style="font-weight:bold;color:var(--accent)">text</span>';
```

### ✅ 允许
```html
<div class="flex-row">...</div>
```
```javascript
element.classList.add('error-text');
element.classList.remove('hidden');
```
```javascript
html += '<span class="accent-bold">text</span>';
```

### 例外
仅允许极少数动态样式必须通过 JS 控制的情况：
- 元素显隐：使用预定义的 `.hidden` 类，而非 `element.style.display = 'none'`
- 动态宽度/位置：使用 CSS 变量或 data 属性控制，而非直接设置像素值

---

## 4. SVG 图标系统（Icon System）

### 原则
所有图标使用项目内置的 SVG 图标系统 `CW.icon(name)`，**不得使用 emoji/unicode 字符**作为图标。

### 可用图标列表
```
alert-triangle, camera, check, check-circle, clock, copy, dice-1,
download, eye, eye-off, file-text, folder, folder-open, image, loader,
palette, pencil, play, refresh-cw, ruler, search, send, settings,
settings-2, sliders, sprout, timer, trash-2, upload, x, x-circle, zap
```

### ❌ 禁止
```javascript
html += '<button>🖥️ 设备</button>';
html += '<button>🔗 打开</button>';
```

### ✅ 允许
```javascript
html += '<button>' + CW.icon('settings-2') + ' 设备</button>';
html += '<button>' + CW.icon('send') + ' 打开</button>';
```

### 注意事项
- `CW.icon(name)` 返回一个 SVG HTML 字符串，默认 16px
- 可传第二个参数指定尺寸：`CW.icon('trash-2', 20)`
- 可传第三个参数指定颜色：`CW.icon('check', 14, 'var(--green)')`
- 在 HTML 中直接使用时，通过 JS 动态渲染，不写死在 HTML 里
