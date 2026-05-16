// nodes.js — 节点管理模块
// 用于管理 ComfyUI 运行节点（本地/SSH/HTTP）

(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API;

  function authFetch(url, opts) {
    if (window.CW && CW.auth && typeof CW.auth.apiFetch === 'function') {
      return CW.auth.apiFetch(url, opts);
    }
    return fetch(url, opts);
  }

  // ─── 模块级常量 ───
  var STATUS_LABELS = { running: '忙碌中', idle: '待机中', dead: '宕机', offline: '未启动' };
  var DOT_COLORS = { running: 'dot-orange', idle: 'dot-green', dead: 'dot-red', offline: 'dot-gray' };
  var QUEUE_VAL = function(inst) { return (inst.status === 'offline' || inst.status === 'dead') ? '-' : (inst.queue || 0); };

  // ─── 共享工具函数 ───
  async function _fetchNodeStatus(nid) {
    var r = await authFetch(API + '/api/nodes');
    var d = await r.json();
    if (!d.ok) return null;
    for (var ni = 0; ni < (d.data || []).length; ni++) {
      if (d.data[ni].id === nid) return d.data[ni];
    }
    return null;
  }

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
      var btnText = isDead ? '强制重启' : '启动';
      html += '<button class="wf-mgr-btn btn-start" onclick="CW.' + fnName + '(\'' + escA(nid) + '\',\'' + escA(iid) + '\')">' + btnText + '</button>';
    }
    return html;
  }

  function _buildInstanceRow(inst, nid, instUrl) {
    var qVal = QUEUE_VAL(inst);
    return '<div class="device-instance-row" data-iid="' + escA(inst.id) + '">'
      + '<span class="dih-col dih-name"><span class="node-status-dot ' + DOT_COLORS[inst.status] + '"></span>' + escH(inst.name || inst.id) + '</span>'
      + '<span class="dih-col dih-port">' + inst.port + '</span>'
      + '<span class="dih-col dih-status">' + STATUS_LABELS[inst.status] + '</span>'
      + '<span class="dih-col dih-queue">' + qVal + '</span>'
      + '<span class="dih-col dih-actions">' + _buildInstanceActions(inst, nid, inst.id, instUrl) + '</span></div>';
  }

  // ─── 加载节点列表 ───
  async function loadNodes() {
    var cont = $('#deviceListContainer');
    if (!cont) return;
    cont.innerHTML = '<div class="dim-tag">加载中...</div>';
    try {
      var r = await authFetch(API + '/api/nodes');
      if (r.status === 401) {
        cont.innerHTML = '<div class="dim-tag">请先登录后查看设备</div>';
        return;
      }
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
    var currentUser = window.CW && CW.auth && CW.auth.getCurrentUser ? CW.auth.getCurrentUser() : null;
    var isAdmin = !!(currentUser && currentUser.role === 'admin');
    if (!nodes || !nodes.length) {
      cont.innerHTML = '<div class="dim-tag">暂无设备，点击上方“添加设备”开始</div>';
      return;
    }
    var html = '';
    for (var n of nodes) {
      var connLabel = { local: '本机', 'remote-ssh': '本地网络', 'remote-http': '远端' }[n.connection] || n.connection;
      var connColor = { local: 'conn-local', 'remote-ssh': 'conn-ssh', 'remote-http': 'conn-http' }[n.connection] || '';
      html += '<div class="device-card" data-nid="' + escA(n.id) + '">';
      // Header
      var connected = (n.connected !== false);
      html += '<div class="device-card-header">';
      html += '<span class="device-card-title"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> ' + escH(n.name) + ' <span class="node-conn-tag ' + connColor + '">' + escH(connLabel) + '</span></span>';
      html += '<button class="wf-mgr-btn device-status-toggle' + (connected ? ' btn-start' : ' btn-stop') + '" onclick="CW.toggleDeviceConnection(\'' + n.id + '\',' + connected + ')">' + (connected ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> 已连接' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> 已断开') + '</button>';
      html += '</div>';
      // Address + SSH info
      html += '<div class="device-card-meta">';
      html += '<span class="device-card-addr">' + escH(n.host || '') + (n.instances ? ' · ' + n.instances.length + ' 个实例' : '') + '</span>';
      if (isAdmin || n.shared) {
        html += '<span class="device-card-addr">' + (n.shared ? '共享设备' : '私有设备') + '</span>';
      }
      if (n.connection === 'remote-ssh') {
      // SSH moved to footer
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
          var instUrl = (n.access && n.access.url || 'http://' + n.host + ':{port}').replace('{port}', inst.port);
          html += _buildInstanceRow(inst, n.id, instUrl);
        }
      }
      // Footer actions
      html += '<div class="device-card-footer">';
      if (n.connection === 'remote-ssh') {
        html += "<button class=\"wf-mgr-btn\" onclick='CW.showSshInfo(\"" + n.id + "\")' title=\"SSH 连接信息\">" + CW.icon('settings') + ' SSH</button>';
      }
      if (n.connection === 'remote-ssh') {
      // SSH moved to footer
      }
      html += '<button class="wf-mgr-btn" onclick="CW.testNode(\'' + n.id + '\')">' + CW.icon('search') + ' 连通测试</button>';

      if (n.can_manage) {
        html += '<button class="wf-mgr-btn" onclick="CW.openDeviceEditor(\'' + n.id + '\')">' + CW.icon('pencil') + ' 编辑</button>';
        html += '<button class="wf-mgr-btn danger" onclick="CW.deleteNode(\'' + n.id + '\')">' + CW.icon('trash-2') + ' 删除</button>';
      }
      html += '</div></div>';
    }
    cont.innerHTML = html;
  }

  // ─── 设备编辑器 ───
  function openDeviceEditor(nid) {
    var modal = $('#deviceEditModal');
    var title = document.getElementById('v4DeviceEditTitle');
    var form = document.getElementById('v4DeviceEditForm');
    if (!modal || !form) return;
    title.textContent = nid ? '编辑设备' : '添加设备';
    form.dataset.nid = nid || '';
    form.reset();
    if (nid) {
      authFetch(API + '/api/nodes/' + encodeURIComponent(nid))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) throw new Error(d.error);
          fillDeviceForm(d.data);
        })
        .catch(function (e) { alert('加载设备失败: ' + e.message); });
    }
    // Auto-fill access_url when host changes
    if (!nid) {
      var hostEl = form.elements['host'];
      var urlEl = form.elements['access_url'];
      if (hostEl && urlEl) {
        hostEl.oninput = function() {
          var h = hostEl.value.trim();
          urlEl.value = h ? 'http://' + h + ':{port}' : 'http://{host}:{port}';
        };
      }
    }
    onDevConnChange();
    modal.classList.add('open');
  }

  function fillDeviceForm(data) {
    var f = document.getElementById('v4DeviceEditForm');
    if (!f) return;
    var currentUser = window.CW && CW.auth && CW.auth.getCurrentUser ? CW.auth.getCurrentUser() : null;
    var isAdmin = !!(currentUser && currentUser.role === 'admin');
    setFormVal(f, 'name', data.name || '');
    setFormVal(f, 'host', data.host || '');
    setFormVal(f, 'connection', data.connection || 'remote-ssh');
    setFormVal(f, 'labels', (data.labels || []).join(','));
    setFormVal(f, 'access_url', (data.access && data.access.url) || ('http://' + (data.host || '{host}') + ':{port}'));
    var ssh = data.ssh_config || {};
    setFormVal(f, 'ssh_user', ssh.user || 'root');
    setFormVal(f, 'ssh_port', ssh.port || 22);
    setFormVal(f, 'ssh_auth', ssh.auth || 'password');
    setFormVal(f, 'ssh_password', ssh.password || '');
    setFormVal(f, 'ssh_key_path', ssh.key_path || '');
    var scanRange = data.scan_ports && data.scan_ports.range;
    setFormVal(f, 'preset_ports', scanRange || '8190,8189');
    setFormVal(f, 'preset_wf_dirs', (data.workflow_dirs || []).join(','));
    setFormVal(f, 'shared', !!data.shared);
    if (f.elements.shared) f.elements.shared.disabled = !isAdmin;
    var instList = document.getElementById('deviceEditInstances');
    var instSection = document.getElementById('devInstSection');
    if (instSection && data.instances && data.instances.length) {
      instSection.style.display = '';
      if (instList) {
        instList.innerHTML = '';
        for (var inst of data.instances) {
          var tag = document.createElement('span');
          tag.className = 'de-inst-tag';
          tag.textContent = (inst.name || inst.id) + ':' + inst.port;
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
    var f = document.getElementById('v4DeviceEditForm');
    if (!f) return;
    var conn = f.elements['connection'] && f.elements['connection'].value;
    var sshSec = $('#devSshSection');
    if (sshSec) sshSec.style.display = (conn === 'remote-ssh') ? '' : 'none';
  }

  function onDevSshAuthChange() {
    var f = document.getElementById('v4DeviceEditForm');
    if (!f) return;
    var auth = f.elements['ssh_auth'] && f.elements['ssh_auth'].value;
    var pwRow = $('#devSshPwRow');
    var keyRow = $('#devSshKeyRow');
    if (pwRow) pwRow.style.display = (auth === 'password') ? '' : 'none';
    if (keyRow) keyRow.style.display = (auth === 'key') ? '' : 'none';
  }

  async function saveDevice() {
    var modal = $('#deviceEditModal');
    var form = document.getElementById('v4DeviceEditForm');
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
      // Create instances from preset ports (only when adding new device)
      if (!data.instances || !data.instances.length) {
        data.instances = [];
        var names = ['A','B','C','D','E','F','G','H'];
        for (var pi = 0; pi < ports.length && pi < names.length; pi++) {
          data.instances.push({
            id: 'inst-' + names[pi].toLowerCase(),
            name: names[pi],
            port: ports[pi],
            service: 'comfyui-' + names[pi].toLowerCase(),
            enabled: true,
            max_concurrent: 1,
            sort_order: pi + 1
          });
        }
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
    var currentUser = window.CW && CW.auth && CW.auth.getCurrentUser ? CW.auth.getCurrentUser() : null;
    if (!(currentUser && currentUser.role === 'admin')) delete data.shared;
    // Parse workflow_dirs from comma-separated field
    if (data.preset_wf_dirs) {
      data.workflow_dirs = data.preset_wf_dirs.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
      if (data.workflow_dirs.length === 0) delete data.workflow_dirs;
    }
    data.access = { url: data.access_url || ('http://' + (data.host || '{host}') + ':{port}'), type: 'direct' };
    for (var k of ['ssh_user','ssh_port','ssh_auth','ssh_password','ssh_key_path','access_url','preset_wf_dirs']) delete data[k];
    if (!data.labels || !data.labels.length) delete data.labels;
    if (!data.instances) data.instances = [];
    if (!data.sort_order) data.sort_order = 99;
    try {
      var url = API + '/api/nodes' + (nid ? '/' + encodeURIComponent(nid) : '');
      var r = await authFetch(url, { method: nid ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
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
  function _showToast(msg, duration) {
    var el = $('#deviceToast');
    if (!el) { alert(msg); return; }
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function() { el.classList.remove('show'); }, duration || 10000);
  }


  async function testNode(nid) {
    try {
      var r = await authFetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/test', { method: 'POST' });
      var d = await r.json();
      // Build rich HTML for the test result modal
      var contentEl = $('#testResultContent');
      var modalEl = $('#testResultModal');
      if (!contentEl || !modalEl) {
        _showToast('测试结果弹窗未找到');
        return;
      }
      if (!d.ok) {
        contentEl.innerHTML = '<div style="color:var(--red);font-weight:600">测试失败: ' + escH(d.error || '未知错误') + '</div>';
        modalEl.style.display = ''; modalEl.classList.add('open');
        return;
      }
      var data = d.data || {};
      var html = '<div style="display:flex;flex-direction:column;gap:8px">';
      // Overall status row
      var allOk = data.http && data.ssh && data.systemd;
      html += '<div style="display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:8px;background:' + (allOk ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)') + ';border:1px solid ' + (allOk ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)') + '">';
      html += '<span style="font-weight:700;font-size:14px;color:' + (allOk ? 'var(--green)' : 'var(--red)') + '">' + (allOk ? '全部服务正常' : '部分服务异常') + '</span>';
      html += '</div>';
      // Detail checks
      html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">';
      var checks = [
        { label: 'HTTP 服务', ok: data.http, detail: data.http_detail || '' },
        { label: 'SSH 连接', ok: data.ssh, detail: data.ssh_detail || '' },
        { label: 'systemd', ok: data.systemd, detail: data.systemd_detail || '' },
      ];
      for (var ci = 0; ci < checks.length; ci++) {
        var c = checks[ci];
        html += '<div style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;background:var(--bg-deep);border:1px solid var(--border)">';
        html += '<div><div style="font-weight:600;font-size:12px;color:var(--text)">' + escH(c.label) + '</div>';
        if (c.detail) html += '<div style="font-size:10px;color:var(--dim);margin-top:2px">' + escH(c.detail) + '</div>';
        html += '</div></div>';
      }
      html += '</div>';
      // Instance statuses (if any)
      if (data.instances && data.instances.length) {
        html += '<div style="margin-top:4px;font-weight:600;font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px">实例状态</div>';
        for (var _ii = 0; _ii < data.instances.length; _ii++) {
          var inst = data.instances[_ii];
          var instOk = inst.status === 'running' || inst.status === 'idle';
          html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:4px;background:var(--bg-deep);border:1px solid var(--border);font-size:12px">';
          html += '<span style="flex:1">' + escH(inst.name || inst.id) + ' <span style="color:var(--dim)">:' + inst.port + '</span></span>';
          var statusColor = instOk ? 'var(--green)' : 'var(--red)';
          html += '<span style="color:' + statusColor + ';font-weight:600">' + escH(inst.status || '?') + '</span>';
          if (inst.queue != null) html += '<span style="color:var(--dim);font-size:11px">队列: ' + inst.queue + '</span>';
          html += '</div>';
        }
      }
      html += '</div>';
      contentEl.innerHTML = html;
      modalEl.style.display = ''; modalEl.classList.add('open');
    } catch (e) {
      var contentEl2 = $('#testResultContent');
      var modalEl2 = $('#testResultModal');
      if (contentEl2 && modalEl2) {
        contentEl2.innerHTML = '<div style="color:var(--red);font-weight:600">测试失败: ' + escH(e.message) + '</div>';
        modalEl2.classList.add('open');
      } else {
        alert('测试失败: ' + e.message);
      }
    }
  }

  function closeTestResult() {
    var modal = $('#testResultModal');
    if (modal) modal.classList.remove('open');
  }

  async function deleteNode(nid) {
    if (!confirm('确定删除此节点吗？')) return;
    try {
      var r = await authFetch(API + '/api/nodes/' + encodeURIComponent(nid), { method: 'DELETE' });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '删除失败');
      loadNodes();
    } catch (e) { alert('删除失败: ' + e.message); }
  }

  async function scanNode(nid) {
    try {
      var r = await authFetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/discover', { method: 'POST' });
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
          '端口 ' + item.port + (item.comfyui ? ' ComfyUI' : ' 非 ComfyUI') +
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
      var r = await authFetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/apply-scan', {
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
      var r = await authFetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/instances/' + encodeURIComponent(iid) + '/' + action, { method: 'POST' });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || action + '失败');

      // 乐观更新 DOM（按设备卡片 + 实例行定位）
      var row = document.querySelector('.device-card[data-nid="' + escA(nid) + '"] .device-instance-row[data-iid="' + escA(iid) + '"]');
      if (row) {
        var isStart = action === 'start';
        row.querySelector('.node-status-dot').className = 'node-status-dot' + (isStart ? ' dot-green dot-blink' : ' dot-red dot-blink');
        row.querySelector('.dih-status').textContent = isStart ? '启动中' : '停止中';
        var actionBtns = row.querySelector('.dih-actions');
        if (actionBtns) actionBtns.innerHTML = '<span class="dim-tag">处理中...</span>';
      }

      // 延迟后立即轮询真实状态（每5秒检测一次）
      var done = false;
      for (var retry = 0; retry < 12 && !done; retry++) {
        await new Promise(function(resolve) { setTimeout(resolve, 5000); });
        try {
          var foundNode = await _fetchNodeStatus(nid);
          if (foundNode) {
            var found = null;
            if (foundNode.instances) {
              for (var si = 0; si < foundNode.instances.length; si++) {
                if (foundNode.instances[si].id === iid) { found = foundNode.instances[si]; break; }
              }
            }
            if (found) {
              if (found.status === 'idle' || found.status === 'running') {
                await updateInstanceRow(nid, iid);
                done = true;
              } else if (action === 'stop' && (found.status === 'dead' || found.status === 'offline')) {
                // 停止时 dead 或 offline 都是预期结果
                await updateInstanceRow(nid, iid);
                done = true;
              }
            }
          }
        } catch (_) {}
      }
      // 如果轮询完仍未完成，保持乐观状态不变（不覆盖为灰色）
    } catch (e) { alert(action + '失败: ' + e.message); }
  }

  // ─── 局部更新实例行（避免全屏闪烁）───
  async function updateInstanceRow(nid, iid) {
    try {
      var nodeData = await _fetchNodeStatus(nid);
      if (!nodeData) { loadNodes(); return; }
      var inst = null;
      if (nodeData.instances) {
        for (var _i = 0; _i < nodeData.instances.length; _i++) {
          if (nodeData.instances[_i].id === iid) { inst = nodeData.instances[_i]; break; }
        }
      }
      if (!inst) { loadNodes(); return; }
      // Locate the device card by data-nid
      var card = document.querySelector('.device-card[data-nid="' + escA(nid) + '"]');
      if (!card) { loadNodes(); return; }
      // Locate the instance row by data-iid
      var row = card.querySelector('.device-instance-row[data-iid="' + escA(iid) + '"]');
      if (!row) { loadNodes(); return; }
      // Update status dot
      var dot = row.querySelector('.node-status-dot');
      if (dot) {
        dot.className = 'node-status-dot ' + (DOT_COLORS[inst.status] || 'dot-gray');
      }
      // Update status text (the dih-status span)
      var statusCell = row.querySelector('.dih-status');
      if (statusCell) {
        statusCell.textContent = STATUS_LABELS[inst.status] || inst.status;
      }
      // Update queue display
      var queueCell = row.querySelector('.dih-queue');
      if (queueCell) {
        queueCell.textContent = QUEUE_VAL(inst);
      }
      // Update action buttons: rebuild only the dih-actions span
      var actionsCell = row.querySelector('.dih-actions');
      if (actionsCell) {
        var instUrl = (nodeData.access && nodeData.access.url || 'http://' + nodeData.host + ':{port}').replace('{port}', inst.port);
        actionsCell.innerHTML = _buildInstanceActions(inst, nid, iid, instUrl);
      }
    } catch (e) {
      // Fall back to full refresh on error
      loadNodes();
    }
  }

  function startInstance(nid, iid) { return _instAction(nid, iid, 'start'); }
  function stopInstance(nid, iid) { return _instAction(nid, iid, 'stop'); }
  function restartInstance(nid, iid) { return _instAction(nid, iid, 'restart'); }
  function forceRestartInstance(nid, iid) { return _instAction(nid, iid, 'force-restart'); }

  // ─── Tab切换 ───
  function openDeviceMgr() {
    var overlay = $('#deviceMgr');
    if (overlay) overlay.classList.add('open');
    // Set SVG icon for toolbar button and overlay title
    var tbBtn = $('#tbDeviceBtn');
    if (tbBtn) tbBtn.innerHTML = CW.icon('settings-2') + ' 设备管理';
    var title = $('#deviceMgrTitle');
    if (title) title.innerHTML = CW.icon('settings-2') + ' 设备管理';
    loadNodes();
  }

  function closeDeviceMgr() {
    var overlay = $('#deviceMgr');
    if (overlay) overlay.classList.remove('open');
  }

  async function toggleDeviceConnection(nid, wasConnected) {
    var action = wasConnected ? 'disconnect' : 'connect';
    try {
      var r = await authFetch(API + '/api/nodes/' + encodeURIComponent(nid) + '/' + action, { method: 'POST' });
      var d = await r.json();
      if (!d.ok) throw new Error(d.error || '操作失败');
      // Local DOM update instead of full refresh
      var card = document.querySelector('.device-card[data-nid="' + escA(nid) + '"]');
      if (!card) { loadNodes(); return; }
      var statusTag = card.querySelector('.device-status-tag');
      if (statusTag) {
        statusTag.innerHTML = wasConnected ? '已断开' : '在线';
      }
      var toggleBtn = card.querySelector('.device-card-header button');
      if (toggleBtn) {
        var isNowConnected = !wasConnected;
        toggleBtn.innerHTML = isNowConnected
          ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> 已连接'
          : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> 已断开';
        toggleBtn.className = 'wf-mgr-btn device-status-toggle' + (isNowConnected ? ' btn-start' : ' btn-stop');
      }
    } catch (e) { alert('操作失败: ' + e.message); }
  }

  function refreshAllDevices() {
    loadNodes();
  }

  function showSshInfo(nid) {
    var contentEl = $('#sshInfoContent');
    var modalEl = $('#sshInfoModal');
    if (!contentEl || !modalEl) { _showToast('SSH 信息弹窗未找到'); return; }
    contentEl.innerHTML = '<div style="padding:16px 0;text-align:center;color:var(--text-muted)">加载中…</div>';
    modalEl.style.display = ''; modalEl.classList.add('open');
    authFetch(API + '/api/nodes/' + encodeURIComponent(nid))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok) { contentEl.innerHTML = '<div class="error-msg" style="padding:12px;color:var(--red)">获取失败: ' + escH(d.error || '未知错误') + '</div>'; return; }
        var n = d.data;
        var ssh = n.ssh_config || {};
        var user = ssh.user || 'root';
        var host = n.host || '?';
        var port = ssh.port || 22;
        var auth = ssh.auth || 'password';
        var cmd = 'ssh ' + user + '@' + host + ' -p ' + port;
        contentEl.innerHTML = '<div class="ssh-info" style="padding:8px 0">'
          + '<div class="info-row" style="display:flex;padding:4px 0;gap:12px"><span style="min-width:64px;color:var(--text-muted)">主机</span><span>' + escH(host + ':' + port) + '</span></div>'
          + '<div class="info-row" style="display:flex;padding:4px 0;gap:12px"><span style="min-width:64px;color:var(--text-muted)">用户</span><span>' + escH(user) + '</span></div>'
          + '<div class="info-row" style="display:flex;padding:4px 0;gap:12px"><span style="min-width:64px;color:var(--text-muted)">认证</span><span>' + escH(auth) + '</span></div>'
          + '<div class="info-row" style="display:flex;padding:4px 0;gap:12px"><span style="min-width:64px;color:var(--text-muted)">命令</span><code style="flex:1;background:var(--bg-subtle);padding:4px 8px;border-radius:4px;font-size:12px;word-break:break-all;cursor:pointer" onclick="var r=document.createRange();r.selectNode(this);getSelection().removeAllRanges();getSelection().addRange(r)">' + escH(cmd) + '</code></div>'
          + '</div>';
      })
      .catch(function(e) { contentEl.innerHTML = '<div class="error-msg" style="padding:12px;color:var(--red)">获取失败: ' + escH(e.message) + '</div>'; });
  }

  function closeSshInfo() {
    var modalEl = $('#sshInfoModal');
    if (modalEl) modalEl.classList.remove('open');
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
    closeTestResult: closeTestResult,
    deleteNode: deleteNode,
    scanNode: scanNode,
    applyScanResults: applyScanResults,
    closeScanModal: closeScanModal,
    startInstance: startInstance,
    stopInstance: stopInstance,
    restartInstance: restartInstance,
    forceRestartInstance: forceRestartInstance,
    updateInstanceRow: updateInstanceRow,
    openDeviceMgr: openDeviceMgr,
    closeDeviceMgr: closeDeviceMgr,
    refreshAllDevices: refreshAllDevices,
    showSshInfo: showSshInfo,
    closeSshInfo: closeSshInfo,
    toggleDeviceConnection: toggleDeviceConnection,
    showNodeTab: showNodeTab,
    showWfTab: showWfTab,
    onDevConnChange: onDevConnChange,
    onDevSshAuthChange: onDevSshAuthChange,
  };
  for (var k in exports) window.CW[k] = exports[k];
})();
