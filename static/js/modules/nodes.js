// nodes.js — 节点管理模块
// 用于管理 ComfyUI 运行节点（本地/SSH/HTTP）

(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API;

  // ─── 加载节点列表 ───
  async function loadNodes() {
    var cont = $('#deviceListContainer');
    if (!cont) return;
    cont.innerHTML = '<div class="dim-tag">加载中...</div>';
    try {
      var r = await fetch(API + '/api/nodes');
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '加载失败');
      renderNodes(d.data);
    } catch (e) {
      cont.innerHTML = '<span class="wf-err-tag">加载失败: ' + escH(e.message) + '</span>';
    }
  }

  function renderNodes(nodes) {
    var cont = $('#deviceListContainer');
    if (!cont) return;
    if (!nodes || !nodes.length) {
      cont.innerHTML = '<div class="dim-tag">暂无设备，点击上方 "+ 添加设备" 开始</div>';
      return;
    }
    var html = '';
    for (var n of nodes) {
      if (!n.enabled) continue;
      var sshOk = n.ssh_ok || n.http_up;
      var statusIcon = sshOk ? '🟢' : '🔴';
      var statusText = sshOk ? '在线' : '离线';
      var connLabel = { local: '本地', 'remote-ssh': 'SSH', 'remote-http': 'HTTP' }[n.connection] || n.connection;
      var connColor = { local: 'conn-local', 'remote-ssh': 'conn-ssh', 'remote-http': 'conn-http' }[n.connection] || '';
      html += '<div class="device-card">';
      // Header
      html += '<div class="device-card-header">';
      html += '<span class="device-card-title">🖥 ' + escH(n.name) + '</span>';
      html += '<span class="node-conn-tag ' + connColor + '">' + escH(connLabel) + '</span>';
      html += '<span class="device-status-tag">' + statusIcon + ' ' + statusText + '</span>';
      html += '</div>';
      // Address + SSH info
      html += '<div class="device-card-meta">';
      html += '<span class="device-card-addr">' + escH(n.host || '') + (n.instances ? ' · ' + n.instances.length + ' 个实例' : '') + '</span>';
      if (n.connection === 'remote-ssh') {
        html += '<button class="wf-mgr-btn" onclick="CW.showSshInfo(\'' + n.id + '\')" title="SSH 连接信息">🔑 SSH</button>';
      }
      html += '</div>';
      // Instances table
      if (n.instances && n.instances.length) {
        html += '<div class="device-instance-header">';
        html += '<span class="dih-col dih-name">实例</span>';
        html += '<span class="dih-col dih-port">端口</span>';
        html += '<span class="dih-col dih-status">状态</span>';
        html += '<span class="dih-col dih-queue">队列</span>';
        html += '<span class="dih-col dih-actions">操作</span>';
        html += '</div>';
        for (var inst of n.instances) {
          if (!inst.enabled && inst.enabled !== undefined) continue;
          var dotColor = { running: 'dot-green', idle: 'dot-yellow', dead: 'dot-red', offline: 'dot-gray' }[inst.status] || 'dot-gray';
          var statusLabel = { running: '运行中', idle: '空闲', dead: '已死', offline: '已停止' }[inst.status] || inst.status;
          var instUrl = (n.access && n.access.url || 'http://' + n.host + ':{port}').replace('{port}', inst.port);
          html += '<div class="device-instance-row">';
          html += '<span class="dih-col dih-name"><span class="node-status-dot ' + dotColor + '"></span>' + escH(inst.name || inst.id) + '</span>';
          html += '<span class="dih-col dih-port">' + inst.port + '</span>';
          html += '<span class="dih-col dih-status">' + escH(statusLabel) + '</span>';
          html += '<span class="dih-col dih-queue">' + (inst.queue || 0) + '</span>';
          html += '<span class="dih-col dih-actions">';
          html += '<a class="wf-mgr-btn" href="' + escA(instUrl) + '" target="_blank" title="打开 ComfyUI">🔗 打开</a>';
          if (inst.status === 'running' || inst.status === 'idle') {
            html += '<button class="wf-mgr-btn" onclick="CW.stopInstance(\'' + n.id + '\',\'' + inst.id + '\')">■ 停止</button>';
          } else {
            html += '<button class="wf-mgr-btn" onclick="CW.startInstance(\'' + n.id + '\',\'' + inst.id + '\')">▶ 启动</button>';
          }
          html += '</span></div>';
        }
      }
      // Footer actions
      html += '<div class="device-card-footer">';
      html += '<button class="wf-mgr-btn" onclick="CW.testNode(\'' + n.id + '\')">🔍 测连通</button>';
      html += '<button class="wf-mgr-btn" onclick="CW.scanNode(\'' + n.id + '\')">🔎 扫端口</button>';
      html += '<button class="wf-mgr-btn" onclick="CW.openDeviceEditor(\'' + n.id + '\')">✏️ 编辑</button>';
      html += '<button class="wf-mgr-btn danger" onclick="CW.deleteNode(\'' + n.id + '\')">🗑 删除</button>';
      html += '</div></div>';
    }
    cont.innerHTML = html;
  }

  // ─── 设备编辑器 ───
  function openDeviceEditor(nid) {
    var modal = $('#deviceEditModal');
    var title = $('#deviceEditTitle');
    var form = $('#deviceEditForm');
    if (!modal || !form) return;
    title.textContent = nid ? '编辑设备' : '添加设备';
    form.dataset.nid = nid || '';
    form.reset();
    if (nid) {
      fetch(API + '/api/nodes/' + encodeURIComponent(nid))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) throw new Error(d.error);
          fillDeviceForm(d.data);
        })
        .catch(function (e) { alert('加载设备失败: ' + e.message); });
    }
    onDevConnChange();
    modal.classList.add('open');
  }

  function fillDeviceForm(data) {
    var f = $('#deviceEditForm');
    if (!f) return;
    setFormVal(f, 'name', data.name || '');
    setFormVal(f, 'host', data.host || '');
    setFormVal(f, 'connection', data.connection || 'remote-ssh');
    setFormVal(f, 'labels', (data.labels || []).join(','));
    setFormVal(f, 'access_url', (data.access && data.access.url) || 'http://{host}:{port}');
    var ssh = data.ssh_config || {};
    setFormVal(f, 'ssh_user', ssh.user || 'root');
    setFormVal(f, 'ssh_port', ssh.port || 22);
    setFormVal(f, 'ssh_auth', ssh.auth || 'password');
    setFormVal(f, 'ssh_password', ssh.password || '');
    setFormVal(f, 'ssh_key_path', ssh.key_path || '');
    var scanRange = data.scan_ports && data.scan_ports.range;
    setFormVal(f, 'preset_ports', scanRange || '8190,8189');
    var instList = $('#deviceEditInstances');
    var instSection = $('#devInstSection');
    if (instSection && data.instances && data.instances.length) {
      instSection.style.display = '';
      if (instList) {
        instList.innerHTML = '';
        for (var inst of data.instances) {
          var tag = document.createElement('span');
          tag.className = 'de-inst-tag';
          tag.textContent = (inst.name || inst.id) + ':' + inst.port + ' [' + (inst.status || '?') + ']';
          instList.appendChild(tag);
        }
      }
    } else if (instSection) {
      instSection.style.display = 'none';
    }
    onDevConnChange();
    onDevSshAuthChange();
  }

  function setFormVal(form, name, val) {
    var el = form.elements[name];
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!val;
    else el.value = val != null ? val : '';
  }

  function onDevConnChange() {
    var f = $('#deviceEditForm');
    if (!f) return;
    var conn = f.elements['connection'] && f.elements['connection'].value;
    var sshSec = $('#devSshSection');
    if (sshSec) sshSec.style.display = (conn === 'remote-ssh') ? '' : 'none';
  }

  function onDevSshAuthChange() {
    var f = $('#deviceEditForm');
    if (!f) return;
    var auth = f.elements['ssh_auth'] && f.elements['ssh_auth'].value;
    var pwRow = $('#devSshPwRow');
    var keyRow = $('#devSshKeyRow');
    if (pwRow) pwRow.style.display = (auth === 'password') ? '' : 'none';
    if (keyRow) keyRow.style.display = (auth === 'key') ? '' : 'none';
  }

  async function saveDevice() {
    var modal = $('#deviceEditModal');
    var form = $('#deviceEditForm');
    if (!form) return;
    var nid = form.dataset.nid || '';
    var data = {};
    for (var el of form.elements) {
      if (!el.name || el.disabled) continue;
      if (el.type === 'checkbox') data[el.name] = el.checked;
      else if (el.type === 'number') data[el.name] = parseFloat(el.value) || 0;
      else data[el.name] = el.value;
    }
    if (typeof data.labels === 'string') data.labels = data.labels.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (data.preset_ports) {
      var ports = data.preset_ports.split(',').map(function(s) { return parseInt(s.trim()); }).filter(Number);
      if (ports.length >= 2) {
        var min = Math.min.apply(null, ports), max = Math.max.apply(null, ports);
        data.scan_ports = { range: min + '-' + max, extra: [] };
      } else if (ports.length === 1) {
        data.scan_ports = { range: ports[0] + '-' + (ports[0] + 10), extra: [] };
      }
    }
    delete data.preset_ports;
    if (data.connection === 'remote-ssh') {
      data.ssh_config = {
        user: data.ssh_user || '',
        port: parseInt(data.ssh_port) || 22,
        auth: data.ssh_auth || 'password',
      };
      if (data.ssh_auth === 'password') data.ssh_config.password = data.ssh_password || '';
      else data.ssh_config.key_path = data.ssh_key_path || '';
    }
    data.access = { url: data.access_url || 'http://{host}:{port}', type: 'direct' };
    for (var k of ['ssh_user','ssh_port','ssh_auth','ssh_password','ssh_key_path','access_url']) delete data[k];
    if (!data.labels || !data.labels.length) delete data.labels;
    if (!data.instances) data.instances = [];
    if (!data.sort_order) data.sort_order = 99;
    try {
      var url = API + '/api/nodes' + (nid ? '/' + encodeURIComponent(nid) : '');
      r = await fetch(url, { method: nid ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '保存失败');
      modal.classList.remove('open');
      loadNodes();
    } catch (e) { alert('保存失败: ' + e.message); }
  }

  function closeDeviceEditor() {
    var modal = $('#deviceEditModal');
    if (modal) modal.classList.remove('open');
  }

  // ─── 操作 ───
  async function testNode(nid) {
    try {
      var r = await fetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/test', { method: 'POST' });
      var d = await r.json();
      var msg = d.data ? [
        'HTTP: ' + (d.data.http ? '✅' : '❌'),
        'SSH: ' + (d.data.ssh ? '✅' : '❌'),
        'systemd: ' + (d.data.systemd ? '✅' : '❌'),
      ].join('\n') : '测试完成';
      alert(msg);
    } catch (e) { alert('测试失败: ' + e.message); }
  }

  async function deleteNode(nid) {
    if (!confirm('确定删除此节点吗？')) return;
    try {
      var r = await fetch(API + '/api/nodes/' + encodeURIComponent(nid), { method: 'DELETE' });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '删除失败');
      loadNodes();
    } catch (e) { alert('删除失败: ' + e.message); }
  }

  async function scanNode(nid) {
    try {
      var r = await fetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/discover', { method: 'POST' });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '扫描失败');
      // Show scan results
      var list = d.data && d.data.detected;
      if (!list || !list.length) {
        alert('未发现 ComfyUI 实例');
        return;
      }
      var modal = $('#scanResultModal');
      var cont = $('#scanResultList');
      if (!modal || !cont) return;
      cont.innerHTML = '';
      for (var item of list) {
        var row = document.createElement('div');
        row.className = 'scan-result-row';
        row.innerHTML = '<label><input type="checkbox" data-port="' + item.port + '" checked> ' +
          '端口 ' + item.port + (item.comfyui ? ' ✅ ComfyUI' : ' ❌ 非ComfyUI') +
          (item.queue > 0 ? ' (队列' + item.queue + ')' : '') + '</label>';
        cont.appendChild(row);
      }
      modal.dataset.nid = nid;
      modal.classList.add('open');
    } catch (e) { alert('扫描失败: ' + e.message); }
  }

  async function applyScanResults() {
    var modal = $('#scanResultModal');
    var nid = modal.dataset.nid;
    var rows = $$('#scanResultList input[type=checkbox]:checked');
    var ports = [];
    for (var cb of rows) ports.push(parseInt(cb.dataset.port));
    try {
      var r = await fetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/apply-scan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected: ports.map(function(p) { return {port: p}; }) })
      });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '应用失败');
      modal.classList.remove('open');
      loadNodes();
    } catch (e) { alert('应用失败: ' + e.message); }
  }

  function closeScanModal() {
    $('#scanResultModal').classList.remove('open');
  }

  async function _instAction(nid, iid, action) {
    try {
      var r = await fetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/instances/' + encodeURIComponent(iid) + '/' + action, { method: 'POST' });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || action + '失败');
      setTimeout(loadNodes, 3000); // wait for state change
    } catch (e) { alert(action + '失败: ' + e.message); }
  }

  function startInstance(nid, iid) { return _instAction(nid, iid, 'start'); }
  function stopInstance(nid, iid) { return _instAction(nid, iid, 'stop'); }
  function restartInstance(nid, iid) { return _instAction(nid, iid, 'restart'); }

  // ─── Tab切换 ───
  function openDeviceMgr() {
    var overlay = $('#deviceOverlay');
    if (overlay) overlay.classList.add('open');
    loadNodes();
  }

  function closeDeviceMgr() {
    var overlay = $('#deviceOverlay');
    if (overlay) overlay.classList.remove('open');
  }

  function showSshInfo(nid) {
    var cont = $('#deviceListContainer');
    if (!cont) return;
    var nodesEl = cont.querySelectorAll('.device-card');
    // We don't have the raw data easily, so fetch from API
    fetch(API + '/api/nodes/' + encodeURIComponent(nid))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok) { alert(d.error); return; }
        var n = d.data;
        var ssh = n.ssh_config || {};
        var cmd = 'ssh ' + (ssh.user || 'root') + '@' + n.host + ' -p ' + (ssh.port || 22);
        if (ssh.auth === 'password' && ssh.password) {
          cmd = 'sshpass -p \"***\" ' + cmd;
        }
        var info = '主机: ' + n.host + ':' + (ssh.port || 22) + '\\n用户: ' + (ssh.user || 'root') + '\\n认证: ' + (ssh.auth || 'password') + '\\n\\n登录命令:\\n' + cmd;
        prompt('SSH 连接信息 (复制即可)', cmd);
      })
      .catch(function(e) { alert('获取失败: ' + e.message); });
  }

  function showNodeTab() {
    var nodePane = $('#nodePane');
    var wfPane = $('#wfOverlay');
    if (nodePane) nodePane.style.display = '';
    if (wfPane) wfPane.style.display = 'none';
    var tabs = $$('.wf-overlay-header .tab-btn');
    for (var t of tabs) t.classList.remove('active');
    var btn = $('#nodeOverlayTabBtn');
    if (btn) btn.classList.add('active');
    var tbBtn = $('#nodeTabBtn');
    if (tbBtn) tbBtn.classList.add('active');
    loadNodes();
  }

  function showWfTab() {
    var nodePane = $('#nodePane');
    var wfPane = $('#wfOverlay');
    if (nodePane) nodePane.style.display = 'none';
    if (wfPane) wfPane.style.display = '';
    var tabs = $$('.wf-overlay-header .tab-btn');
    for (var t of tabs) t.classList.remove('active');
    var btn = $('#wfTabBtn');
    if (btn) btn.classList.add('active');
    if (window.CW && CW.loadWfMeta) CW.loadWfMeta();
    if (window.CW && CW.loadWfDirs) CW.loadWfDirs();
    var sel = $('#wfMgrSortBy');
    var sortBy = (window.CW && CW.getMgrSortBy) ? CW.getMgrSortBy() : 'manual';
    if (sel) sel.value = sortBy;
    if (sel) sel.onchange = function() { if (window.CW && CW.setMgrSortBy) CW.setMgrSortBy(this.value); if (window.CW && CW.renderWfGrid) CW.renderWfGrid(); };
    if (window.CW && CW.loadWorkflows) CW.loadWorkflows();
  }

  // ─── 导出 ───
  if (!window.CW) window.CW = {};
  var exports = {
    loadNodes: loadNodes,
    openDeviceEditor: openDeviceEditor,

    saveDevice: saveDevice,
    closeDeviceEditor: closeDeviceEditor,
    testNode: testNode,
    deleteNode: deleteNode,
    scanNode: scanNode,
    applyScanResults: applyScanResults,
    closeScanModal: closeScanModal,
    startInstance: startInstance,
    stopInstance: stopInstance,
    restartInstance: restartInstance,
    openDeviceMgr: openDeviceMgr,
    closeDeviceMgr: closeDeviceMgr,
    showSshInfo: showSshInfo,
    showNodeTab: showNodeTab,
    showWfTab: showWfTab,
    onDevConnChange: onDevConnChange,
    onDevSshAuthChange: onDevSshAuthChange,
  };
  for (var k in exports) window.CW[k] = exports[k];
})();
