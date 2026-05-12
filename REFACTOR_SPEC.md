# nodes.js 代码重构 — 消除重复、统一数据源

## 目标
将 nodes.js 中重复的渲染逻辑、状态映射、数据获取统一为共享函数，减少重复代码。

## 当前问题

### 1. 状态映射重复定义
```javascript
// renderNodes (line ~69)
var dotColors = { running: 'dot-orange', idle: 'dot-green', dead: 'dot-red', offline: 'dot-gray' };
var statusLabel = { running: '忙碌中', idle: '待机中', dead: '宕机', offline: '未启动' }[inst.status] || inst.status;

// updateInstanceRow (line ~430)
var dotColors = { running: 'dot-orange', idle: 'dot-green', dead: 'dot-red', offline: 'dot-gray' };
var statusLabels = { running: '忙碌中', idle: '待机中', dead: '宕机', offline: '未启动' };
```
→ 应提取为模块级常量，两处共用。

### 2. 实例操作按钮 HTML 重复
renderNodes 和 updateInstanceRow 各自有一份几乎相同的代码来生成「🔗 打开」「■ 停止」「▶ 启动」「🔄 强制重启」按钮 HTML
→ 应提取为 `_buildInstanceActions(inst, nid, iid, instUrl)` 函数。

### 3. 数据来源不统一
- `updateInstanceRow` 之前用详情接口，刚改为列表接口
- `_instAction` 轮询循环也请求列表接口
→ 应提取为 `_fetchNodeStatus(nid)` 返回带实时状态的节点数据。

### 4. 状态灯 class 拼接重复
```javascript
row.querySelector('.node-status-dot').className = 'node-status-dot ' + (dotColors[inst.status] || 'dot-gray');
```
多处出现 → 提取 `_updateStatusDot(row, status)` 函数。

## 重构方案

### 模块顶部新增常量

```javascript
var STATUS_LABELS = { running: '忙碌中', idle: '待机中', dead: '宕机', offline: '未启动' };
var DOT_COLORS = { running: 'dot-orange', idle: 'dot-green', dead: 'dot-red', offline: 'dot-gray' };
var QUEUE_VAL = function(inst) { return (inst.status === 'offline' || inst.status === 'dead') ? '-' : (inst.queue || 0); };
```

### 新增共享函数

```javascript
// 获取带实时状态的节点数据（列表接口）
async function _fetchNodeStatus(nid) {
  var r = await fetch(API + '/api/nodes');
  var d = await r.json();
  if (!d.ok) return null;
  for (var ni = 0; ni < (d.data || []).length; ni++) {
    if (d.data[ni].id === nid) return d.data[ni];
  }
  return null;
}

// 构建实例操作栏 HTML
function _buildInstanceActions(inst, nid, iid, instUrl) {
  var html = '';
  if (inst.status !== 'offline' && inst.http_up) {
    html += '<a class="wf-mgr-btn btn-open" href="' + escA(instUrl) + '" target="_blank">' + CW.icon('send') + ' 打开</a>';
  }
  if (inst.status === 'running' || inst.status === 'idle') {
    html += '<button class="wf-mgr-btn btn-stop" onclick="CW.stopInstance(\'' + escA(nid) + '\',\'' + escA(iid) + '\')">■ 停止</button>';
  } else {
    var isDead = inst.status === 'dead';
    var fnName = isDead ? 'forceRestartInstance' : 'startInstance';
    var btnText = isDead ? '🔄 强制重启' : '▶ 启动';
    html += '<button class="wf-mgr-btn btn-start" onclick="CW.' + fnName + '(\'' + escA(nid) + '\',\'' + escA(iid) + '\')">' + btnText + '</button>';
  }
  return html;
}

// 构建实例行完整 HTML（renderNodes 用）
function _buildInstanceRow(inst, nid, instUrl, dotColor, statusLabel) {
  var qVal = QUEUE_VAL(inst);
  return '<div class="device-instance-row" data-iid="' + escA(inst.id) + '">'
    + '<span class="dih-col dih-name"><span class="node-status-dot ' + DOT_COLORS[inst.status] + '"></span>' + escH(inst.name || inst.id) + '</span>'
    + '<span class="dih-col dih-port">' + inst.port + '</span>'
    + '<span class="dih-col dih-status">' + STATUS_LABELS[inst.status] + '</span>'
    + '<span class="dih-col dih-queue">' + qVal + '</span>'
    + '<span class="dih-col dih-actions">' + _buildInstanceActions(inst, nid, inst.id, instUrl) + '</span></div>';
}
```

### renderNodes 中简化
用 `_buildInstanceRow` 替代大段 HTML 拼接。

### updateInstanceRow 中简化
用 `_fetchNodeStatus(nid)` 替代 fetch 调用，用模块常量替代局部变量，用 `_buildInstanceActions` 替代按钮 HTML 拼接。

### _instAction 轮询中简化
用 `_fetchNodeStatus(nid)` 替代 fetch 调用。

## 涉及文件
- `static/js/modules/nodes.js`

## 约束
- 功能不变，仅重构代码结构
- 不要修改 index.html 或 app.py
- 重构后测试：渲染设备列表、启停实例、局部更新
- 更新 index.html 中 nodes.js 缓存版本号
