# Phase 2 Bugfix — 两个问题

## Bug A: 连接/断开依然全屏刷新

### 问题
`toggleDeviceConnection()` 调用后执行 `loadNodes()` 全量刷新设备列表。

### 修复要求
- 改为局部 DOM 更新
- 连接/断开切换后只更新：设备卡片上的连接状态文字和按钮文字（「断开」↔「连接」）
- 参考已有的 `updateInstanceRow` 模式

### 涉及文件
- `static/js/modules/nodes.js`

---

## Bug B: 启动实例后设备状态被覆盖为离线

### 根因
`updateInstanceRow()` 函数末尾（约第 400 行）有一行代码：
```javascript
var statusTag = card.querySelector('.device-status-tag');
if (statusTag) {
  var sshOk = nodeData.ssh_ok || nodeData.http_up;
  statusTag.innerHTML = (sshOk ? '🟢' : '🔴') + ' ' + (sshOk ? '在线' : '离线');
}
```
它错误地**更新了设备级别的状态标签**。启动实例时，SSH/HTTP 检测还没完成，`ssh_ok` 为 false，导致设备状态被覆盖为「离线」。

### 修复要求
- 删除 `updateInstanceRow()` 中更新设备状态标签的代码
- `updateInstanceRow()` 只更新实例行的状态，不应触碰设备级别的显示
- 设备级别状态（在线/离线/已断开）只在 `loadNodes()` 或 `toggleDeviceConnection()` 中控制
