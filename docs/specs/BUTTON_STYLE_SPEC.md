# 设备管理按钮颜色规范

## 需求
设备管理页面中，各类操作按钮需要用醒目的颜色区分，让用户一眼能识别操作类型。

## 颜色映射

| 操作 | 颜色 | 色值 | 语义 |
|------|------|------|------|
| ▶ 启动 / 连接 | 绿色 | `#22c55e` | 正向操作 |
| ■ 停止 / 断开 | 红色 | `#ef4444` | 危险/停止 |
| 🔗 打开 | 蓝色 | `#3b82f6` | 导航/跳转 |
| 🔍 测连通 / 🔎 扫端口 | 灰色/次要 | 保持现有 | 辅助操作 |
| ✏️ 编辑 | 灰色/次要 | 保持现有 | 辅助操作 |
| 🗑 删除 | 红色 | `#ef4444` | 危险操作 |

## 实现方式

在 style.css 中新增按钮变体类，不修改现有 `.wf-mgr-btn` 基础样式：

```css
.wf-mgr-btn.btn-start { 
  background: rgba(34,197,94,.15); 
  color: #22c55e; 
  border-color: rgba(34,197,94,.3); 
}
.wf-mgr-btn.btn-start:hover { 
  background: rgba(34,197,94,.25); 
}

.wf-mgr-btn.btn-stop { 
  background: rgba(239,68,68,.15); 
  color: #ef4444; 
  border-color: rgba(239,68,68,.3); 
}
.wf-mgr-btn.btn-stop:hover { 
  background: rgba(239,68,68,.25); 
}

.wf-mgr-btn.btn-open { 
  background: rgba(59,130,246,.15); 
  color: #3b82f6; 
  border-color: rgba(59,130,246,.3); 
}
.wf-mgr-btn.btn-open:hover { 
  background: rgba(59,130,246,.25); 
}
```

## 修改文件
- `static/css/style.css` — 新增按钮变体类
- `static/js/modules/nodes.js` — 为按钮添加 CSS 类

## nodes.js 中需要添加 class 的位置

| 当前 | 改为 |
|------|------|
| `▶ 启动` 按钮 | 添加 `btn-start` class |
| `■ 停止` 按钮 | 添加 `btn-stop` class |
| `🔗 打开` 按钮 | 添加 `btn-open` class |
| 连接按钮 | 添加 `btn-start` class |
| 断开按钮 | 添加 `btn-stop` class |

**注意**：在 JS 中拼接 HTML 时，class 要写成 `class="wf-mgr-btn btn-start"` 而不是覆盖原有 class。

## 完成
- git commit -m "style: add color-coded button variants (start/stop/open)"
- 更新 index.html 中 style.css 缓存版本号