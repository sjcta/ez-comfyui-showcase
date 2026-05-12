# 实例状态指示灯规范

## 颜色映射

| 状态 | 颜色 | CSS class | 含义 |
|------|------|-----------|------|
| `offline` | 灰色 | `dot-gray` | 没启动 |
| `idle` | 绿色 | `dot-green` | 待机 |
| `running` | 橙色 | `dot-orange` | 忙碌（正在出图） |
| `dead` | 红色 | `dot-red` | 死机 |
| `starting` | 绿色闪烁 | `dot-green dot-blink` | 启动中 |
| `stopping` | 红色闪烁 | `dot-red dot-blink` | 停止中 |

## 修改文件
- `static/css/style.css` — 新增 dot-orange 和 dot-blink 动画
- `static/js/modules/nodes.js` — 更新状态映射

## CSS 新增

```css
/* 橙色 - 忙碌 */
.dot-orange { background: #f59e0b; box-shadow: 0 0 4px rgba(245,158,11,.5); }

/* 闪烁动画 */
.dot-blink { animation: dot-blink 1s ease-in-out infinite; }
@keyframes dot-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
```

## JS 修改

### 位置 1: renderNodes 中的状态颜色映射
```javascript
var dotColors = {
  running: 'dot-orange',
  idle: 'dot-green', 
  dead: 'dot-red',
  offline: 'dot-gray'
};
```

### 位置 2: 状态文字映射（updateInstanceRow 中同样）
```javascript
var statusLabels = {
  running: '忙碌',
  idle: '待机',
  dead: '死机',
  offline: '没启动'
};
```

### 位置 3: _instAction 乐观更新时
- 启动中 → `dot-green dot-blink` + 状态文字「启动中」
- 停止中 → `dot-red dot-blink` + 状态文字「停止中」

### 位置 4: updateInstanceRow 渲染时
- 如果 status 不在已知映射中（如「启动中」「停止中」），保持原文字不覆盖

## 现有 dot 样式参考
```css
.node-status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
```

## 完成条件
- [ ] dot-orange 样式正确显示橙色
- [ ] dot-blink 动画正常工作
- [ ] 渲染时 idle=绿色、running=橙色、dead=红色、offline=灰色
- [ ] 启动中绿色闪烁、停止中红色闪烁

提交：git commit -m "style: status indicator colors - gray(green) idle, orange busy, red dead, green/red blink for start/stop"