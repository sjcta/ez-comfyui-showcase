# 首批规范化整改

> 基于 `PROJECT_STANDARDS.md` 对现有代码进行整改，使其符合项目规范。
> 所有修改须同时遵守 PROJECT_STANDARDS.md 中的四条规范。

## 整改项

### A. 连接/断开全屏刷新 → 局部更新
**违反规范**：1. 局部刷新
**文件**：`static/js/modules/nodes.js`
**修复**：`toggleDeviceConnection()` 中把 `loadNodes()` 改为局部 DOM 更新
- 成功后只更新该设备卡片中的连接状态文字、按钮文字
- 不刷新整个设备列表

### B. 启动实例后设备变离线
**违反规范**：无（纯 bug）
**文件**：`static/js/modules/nodes.js`
**修复**：在 `updateInstanceRow()` 中找到更新设备状态标签的代码并删除
- 约第 400 行：`var statusTag = card.querySelector('.device-status-tag')` 到 `})` 之间的代码
- 实例行更新函数不应修改设备级别状态

### C. Emoji 替换为 SVG 图标
**违反规范**：4. SVG 图标系统
**文件**：`static/index.html` + `static/js/modules/nodes.js`

**替换表**：

| 位置 | 当前 Emoji | 替换为 |
|------|-----------|--------|
| index.html toolbar: 设备按钮 | `🖥️ 设备` | `CW.icon('settings-2') + ' 设备'` |
| index.html overlay 标题 | `🖥️ 设备管理` | `CW.icon('settings-2') + ' 设备管理'` |
| nodes.js: SSH 按钮 | `🔑 SSH` | `CW.icon('settings') + ' SSH'` |
| nodes.js: 打开按钮 | `🔗 打开` | `CW.icon('send') + ' 打开'` |
| nodes.js: 测连通按钮 | `🔍 测连通` | `CW.icon('search') + ' 测连通'` |
| nodes.js: 扫端口按钮 | `🔎 扫端口` | `CW.icon('sliders') + ' 扫端口'` |
| nodes.js: 编辑按钮 | `✏️ 编辑` | `CW.icon('pencil') + ' 编辑'` |

**注意**：
- `CW.icon()` 在 JS 字符串模板中用 `' + CW.icon('name') + '` 拼接
- HTML 中所有用到 emoji 图标的地方都要替换
- 仅替换作为图标的 emoji，正文中的 emoji 不受影响

## 验证清单
- [ ] 连接/断开操作不触发全屏刷新
- [ ] 启动实例后设备状态不被覆盖
- [ ] 所有操作按钮使用 SVG 图标，无 emoji 图标残留
- [ ] 修改后前端无 JS 报错

## 提交
```bash
cd /Users/ai/.openclaw/workspace/ez-comfyui-showcase
git add -A
git commit -m "fix: comply with project standards - local DOM updates, SVG icons, fix instance start bug"
git push origin 4.0-beta
```
