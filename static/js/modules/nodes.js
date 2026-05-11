// nodes.js — 节点管理模块
// 用于管理 ComfyUI 运行节点（本地/SSH/HTTP）

(function () {
  var API = window._API || '';

  // ─── 加载节点列表 ───
  async function loadNodes() {
    var cont = $('#nodeListContainer');
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
    var cont = $('#nodeListContainer');
    if (!cont) return;
    if (!nodes || !nodes.length) {
      cont.innerHTML = '<div class="dim-tag">暂无节点</div>';
      return;
    }
    var html = '';
    for (var n of nodes) {
      html += '<div class="node-card">';
      html += '<div class="node-card-header">';
      html += '<span class="node-card-title">🖥 ' + escH(n.name) + '</span>';
      var connLabel = { local: '本地', 'remote-ssh': 'SSH', 'remote-http': 'HTTP' }[n.connection] || n.connection;
      var connColor = { local: 'conn-local', 'remote-ssh': 'conn-ssh', 'remote-http': 'conn-http' }[n.connection] || '';
      html += '<span class="node-conn-tag ' + connColor + '">' + escH(connLabel) + '</span>';
      html += '<div class="node-card-actions">';
      html += '<button class="wf-mgr-btn" onclick="CW.testNode(\'' + n.id + '\')">测试</button>';
      html += '<button class="wf-mgr-btn" onclick="CW.openNodeEditor(\'' + n.id + '\')">编辑</button>';
      html += '<button class="wf-mgr-btn danger" onclick="CW.deleteNode(\'' + n.id + '\')">删除</button>';
      html += '</div></div>';
      html += '<div class="node-card-addr">' + escH(n.host) + (n.instances && n.instances.length ? ' · ' + n.instances.length + ' 个实例' : '') + '</div>';
      if (n.labels && n.labels.length) {
        html += '<div class="node-card-labels">';
        for (var lb of n.labels) html += '<span class="wf-mgr-tag">' + escH(lb) + '</span>';
        html += '</div>';
      }
      // Instances
      if (n.instances && n.instances.length) {
        for (var inst of n.instances) {
          var dotColor = { running: 'dot-green', idle: 'dot-yellow', dead: 'dot-red', offline: 'dot-gray', unreachable: 'dot-gray' }[inst.status] || 'dot-gray';
          var statusLabel = { running: '运行中', idle: '空闲', dead: '已死', offline: '已停止', unreachable: '不可达' }[inst.status] || inst.status;
          html += '<div class="node-instance-row">';
          html += '<span class="node-status-dot ' + dotColor + '"></span>';
          html += '<span class="node-instance-name">' + escH(inst.name || inst.id) + '</span>';
          html += '<span class="node-instance-port">:' + inst.port + '</span>';
          html += '<span class="node-instance-status">' + escH(statusLabel) + '</span>';
          if (inst.queue > 0) html += '<span class="node-instance-queue">队列' + inst.queue + '</span>';
          html += '<div class="node-instance-actions">';
          if (inst.status === 'running' || inst.status === 'idle') {
            html += '<button class="wf-mgr-btn" onclick="CW.restartInstance(\'' + n.id + '\',\'' + inst.id + '\')">重启</button>';
            html += '<button class="wf-mgr-btn" onclick="CW.stopInstance(\'' + n.id + '\',\'' + inst.id + '\')">停止</button>';
          } else if (inst.status === 'dead' || inst.status === 'offline') {
            html += '<button class="wf-mgr-btn" onclick="CW.startInstance(\'' + n.id + '\',\'' + inst.id + '\')">启动</button>';
          }
          html += '</div></div>';
        }
      }
      // Scan
      html += '<div class="node-card-footer">';
      html += '<button class="wf-mgr-btn" onclick="CW.scanNode(\'' + n.id + '\')">🔄 扫描端口</button>';
      html += '</div></div>';
    }
    cont.innerHTML = html;
  }

  // ─── 节点编辑器 ───
  function openNodeEditor(nid) {
    var modal = $('#nodeEditorModal');
    var title = $('#nodeEditorTitle');
    var form = $('#nodeEditorForm');
    if (!modal || !form) return;
    title.textContent = nid ? '编辑节点' : '添加节点';
    form.dataset.nid = nid || '';
    form.reset();
    if (nid) {
      fetch(API + '/api/nodes/' + encodeURIComponent(nid))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) throw new Error(d.error);
          fillNodeForm(d.data);
        })
        .catch(function (e) { alert('加载节点失败: ' + e.message); });
    }
    modal.classList.add('open');
  }

  function fillNodeForm(data) {
    var f = $('#nodeEditorForm');
    if (!f) return;
    for (var key in data) {
      var el = f.elements[key];
      if (!el) continue;
      if (el.type === 'checkbox') el.checked = data[key];
      else el.value = data[key];
    }
    // Handle connection change
    onNodeConnChange();
    // Instances summary
    var instList = $('#nodeEditInstances');
    if (instList && data.instances) {
      instList.innerHTML = '';
      for (var inst of data.instances) {
        var tag = document.createElement('span');
        tag.className = 'dim-tag';
        tag.textContent = (inst.name || inst.id) + ':' + inst.port;
        instList.appendChild(tag);
      }
    }
  }

  function onNodeConnChange() {
    var f = $('#nodeEditorForm');
    if (!f) return;
    var conn = f.elements['connection'] && f.elements['connection'].value;
    var sshSec = $('#sshConfigSection');
    if (sshSec) sshSec.style.display = (conn === 'remote-ssh') ? '' : 'none';
  }

  async function saveNode() {
    var modal = $('#nodeEditorModal');
    var form = $('#nodeEditorForm');
    if (!form) return;
    var nid = form.dataset.nid || '';
    var data = {};
    for (var el of form.elements) {
      if (!el.name || el.disabled) continue;
      if (el.type === 'checkbox') data[el.name] = el.checked;
      else if (el.type === 'number') data[el.name] = parseFloat(el.value) || 0;
      else data[el.name] = el.value;
    }
    // Structure labels
    if (typeof data.labels === 'string') data.labels = data.labels.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (typeof data.scan_range === 'string') {
      data.scan_ports = { range: data.scan_range, extra: [] };
    }
    delete data.scan_range;
    // Build ssh_config
    if (data.connection === 'remote-ssh') {
      data.ssh_config = {
        user: data.ssh_user || '',
        port: parseInt(data.ssh_port) || 22,
        auth: data.ssh_auth || 'password',
      };
      if (data.ssh_auth === 'password') data.ssh_config.password = data.ssh_password;
      else data.ssh_config.key_path = data.ssh_key_path;
    }
    delete data.ssh_user; delete data.ssh_port; delete data.ssh_auth;
    delete data.ssh_password; delete data.ssh_key_path;
    // Clean up empty fields
    if (!data.labels || !data.labels.length) delete data.labels;
    if (!data.scan_ports) data.scan_ports = { range: '8188-8195', extra: [] };
    if (!data.instances) data.instances = [];
    if (!data.sort_order) data.sort_order = 99;

    try {
      var url = API + '/api/nodes' + (nid ? '/' + encodeURIComponent(nid) : '');
      var method = nid ? 'PUT' : 'POST';
      var r = await fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '保存失败');
      modal.classList.remove('open');
      loadNodes();
    } catch (e) { alert('保存失败: ' + e.message); }
  }

  function closeNodeEditor() {
    $('#nodeEditorModal').classList.remove('open');
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
  function showNodeTab() {
    var nodePane = $('#nodePane');
    var wfPane = $('#wfOverlay');
    if (nodePane) nodePane.style.display = '';
    if (wfPane) wfPane.style.display = 'none';
    var tabs = $$('.wf-overlay-header .tab-btn');
    for (var t of tabs) t.classList.remove('active');
    var btn = $('#nodeTabBtn');
    if (btn) btn.classList.add('active');
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
    loadWfMeta();
    loadWfDirs();
    var sel = $('#wfMgrSortBy');
    if (sel) sel.value = _mgrSortBy;
    if (sel) sel.onchange = function() { _mgrSortBy = this.value; renderWfGrid(); };
    if (window.CW && CW.loadWorkflows) CW.loadWorkflows();
  }

  // ─── 导出 ───
  if (!window.CW) window.CW = {};
  var exports = {
    loadNodes: loadNodes,
    openNodeEditor: openNodeEditor,
    saveNode: saveNode,
    closeNodeEditor: closeNodeEditor,
    testNode: testNode,
    deleteNode: deleteNode,
    scanNode: scanNode,
    applyScanResults: applyScanResults,
    closeScanModal: closeScanModal,
    startInstance: startInstance,
    stopInstance: stopInstance,
    restartInstance: restartInstance,
    showNodeTab: showNodeTab,
    showWfTab: showWfTab,
    onNodeConnChange: onNodeConnChange,
  };
  for (var k in exports) window.CW[k] = exports[k];
})();
