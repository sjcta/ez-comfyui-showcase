/**
 * Status Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var jobs = A.jobs, API = A.API;

  function _setCurrentTarget(inst) {
    if (!inst) return;
    A.currentTargetInstance = inst.name || '';
    A.currentTargetNodeId = inst.node_id || '';
  }

  function _getCurrentTarget(instances) {
    instances = instances || [];
    var selected = null;
    if (A.currentTargetInstance) {
      selected = instances.find(function(inst) {
        return inst.name === A.currentTargetInstance &&
          (!A.currentTargetNodeId || inst.node_id === A.currentTargetNodeId);
      });
    }
    if (!selected && instances.length) {
      selected = instances[0];
      _setCurrentTarget(selected);
    }
    return selected;
  }

async function pollStatus() {
    try {
      const r = await fetch(`${API}/api/status`);
      const d = await r.json();
      updateServices(d);
      updateGPU(d.gpu, d.instances || []);
    } catch {}
  }

function updateServices(d) {
    const insts = d.instances || [];
    const target = _getCurrentTarget(insts);
    const comfyBtn = $('#svcComfyUI');
    const comfyState = $('#comfyState');
    const bar = $('#statusbar');
    const anyRunning = insts.some(function(inst) { return (inst.queue_running || 0) > 0; });
    const anyPending = insts.some(function(inst) { return (inst.queue_pending || 0) > 0; });
    if (bar) bar.dataset.instanceState = anyRunning ? 'running' : anyPending ? 'pending' : 'idle';
    if (comfyBtn) comfyBtn.className = 'svc-btn ' + (target && target.up ? 'on' : 'off');
    if (comfyState) {
      var compactState = window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
      var targetName = target ? (target.node_name || target.name || '目标实例') : '';
      var stateText = '';
      if (!target) stateText = '无可用实例';
      else if (!target.up) stateText = '已关闭';
      else if ((target.queue_running || 0) > 0) stateText = '出图中';
      else if ((target.queue_pending || 0) > 0) stateText = '排队中';
      else stateText = '待机';
      comfyState.textContent = compactState || !targetName ? stateText : targetName + ' ' + stateText;
    }
  }

function updateGPU(g, instances) {
    const target = _getCurrentTarget(instances || []);
    const gpu = target && target.gpu ? target.gpu : g;
    const fill = $('#vramFill');
    if (!fill) return;
    const pct = gpu && target ? (gpu.vram_pct || 0) : 0;
    const temp = gpu && target ? (gpu.temp_c || 0) : 0;
    fill.style.width = pct + '%';
    // State: green=idle, yellow=busy, red=overloaded.
    // Keep "red" for clearly high pressure so low VRAM usage does not look alarming.
    const isOverload = pct >= 80 || temp >= 85;
    const isBusy = !isOverload && (pct >= 50 || temp >= 70);
    fill.className = 'sb-vram-fill' + (isOverload ? ' overload' : isBusy ? ' busy' : '');
    // Also tint the entire statusbar
    const bar = $('#statusbar');
    if (bar) bar.dataset.state = isOverload ? 'overload' : isBusy ? 'busy' : 'idle';
    var used = Number(gpu && target ? (gpu.vram_used_mb || 0) : 0);
    var total = Number(gpu && target ? (gpu.vram_total_mb || 0) : 0);
    var vramText = $('#vramText');
    if (vramText) {
      var compactVram = window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
      vramText.textContent = total > 0
        ? `${(used / 1024).toFixed(1)} / ${(total / 1024).toFixed(1)} GB${compactVram ? '' : ` (${pct}%)`} · ${temp} °C`
        : (target ? `${target.node_name || target.name} ${gpu && gpu.message ? gpu.message : '未上报 VRAM'}` : '无可用设备');
    }
    if ($('#gpuTemp')) $('#gpuTemp').textContent = '';
    if ($('#gpuUtil')) $('#gpuUtil').textContent = '';
    if ($('#vramSegments') && !$('#vramSegments').dataset.done) {
      [25, 50, 75].forEach((pct) => {
        const seg = document.createElement('div');
        seg.className = 'sb-vram-seg';
        seg.style.left = pct + '%';
        $('#vramSegments').appendChild(seg);
      });
      $('#vramSegments').dataset.done = '1';
    }
  }

function openInstPopup(mode) {
    var overlay = $('#instPopup');
    var title = $('#v4InstPopupTitle') || $('#instPopupTitle');
    if (!overlay) return;
    overlay.classList.add('open');
    overlay._mode = mode || 'comfyui';
    if (title)
      title.textContent = mode === 'others' ? '\u5176\u4ed6 GPU \u8fdb\u7a0b' : 'ComfyUI \u5b9e\u4f8b\u7ba1\u7406';
    if (mode === 'others') _refreshGpuCards();
    else _refreshInstCards();
  }

function closeInstPopup() {
    var overlay = $('#instPopup');
    if (overlay) overlay.classList.remove('open');
  }

function _queueBarHtml(running, pending) {
    var total = running + pending;
    if (total === 0) return '<span class="dim-tag">\u65e0</span>';
    var html = '';
    // Running segment(s) — green
    for (var i = 0; i < running; i++) {
      html += '<div class="gpu-bar gpu-green"></div>';
    }
    // Pending segment(s) — yellow dashed
    for (var i = 0; i < pending; i++) {
      html += '<div class="gpu-bar gpu-yellow"></div>';
    }
    if (!html) html = '<div class="gpu-bar gpu-empty"></div>';
    return html;
  }

async function _refreshInstCards() {
    var box = $('#instCards');
    if (!box) return;
    box.innerHTML = '<div class="st-empty">\u52a0\u8f7d\u4e2d...</div>';
    try {
      var r = await fetch(API + '/api/comfyui/status');
      var d = await r.json();
      var grouped = {};
      var order = [];
      for (var gi = 0; gi < (d.instances || []).length; gi++) {
        var item = d.instances[gi];
        var nodeKey = item.node_id || item.node_name || 'default';
        if (!grouped[nodeKey]) {
          grouped[nodeKey] = { name: item.node_name || item.node_id || '默认设备', items: [] };
          order.push(nodeKey);
        }
        grouped[nodeKey].items.push(item);
      }
      var html = '';
      var groupMap = { nunchaku: 'Nunchaku', 'z-image-turbo': 'Z-Image Turbo', seedvr: 'SeedVR' };
      for (var oi = 0; oi < order.length; oi++) {
        var group = grouped[order[oi]];
        html += '<div class="popup-section-title">' + escH(group.name) + ' \u5b9e\u4f8b\u5217\u8868</div>';
        for (var idx = 0; idx < group.items.length; idx++) {
        var inst = group.items[idx];
        var isSelected = A.currentTargetInstance === inst.name && (!A.currentTargetNodeId || A.currentTargetNodeId === inst.node_id);
        var statusCls = inst.up ? 'on' : 'off';
        var btnLabel = inst.up ? '<svg width="12" height="12" viewBox="0 0 24 24" class="btn-svg"><rect x="4" y="4" width="16" height="16" rx="2" fill="currentColor"/></svg>\u505c\u6b62' : '<svg width="12" height="12" viewBox="0 0 24 24" class="btn-svg"><polygon points="5,3 22,12 5,21" fill="currentColor"/></svg>\u542f\u52a8';
        var btnCls = inst.up ? 'stop' : 'start';
        var groupLabel = groupMap[inst.loaded_group] || inst.loaded_group || '';
        var stateText = !inst.up
          ? '\u5173\u95ed'
          : inst.queue_running > 0
            ? '\u51fa\u56fe\u4e2d'
            : inst.queue_pending > 0
              ? '\u6392\u961f\u4e2d'
              : '\u5f85\u673a';
        html +=
          '<div class="inst-card ' + statusCls + (isSelected ? ' active-target' : '') + '">' +
          '<div class="inst-card-header">' +
          '<div class="inst-card-name"><span class="inst-led ' +
          statusCls +
          '"></span> \u5b9e\u4f8b ' +
          inst.name +
          ' <span class="dim-tag">:' +
          inst.port +
          '</span></div>' +
          '<button class="inst-card-btn" onclick="CW.setTargetInstance(\'' + escA(inst.name) + '\',\'' + escA(inst.node_id || '') + '\')">' + (isSelected ? '当前目标' : '设为目标') + '</button>' +
          '<button class="inst-card-btn ' +
          btnCls +
          '" onclick="CW.toggleInst(\'' +
          inst.name +
          "'," +
          !inst.up +
          ')" id="instBtn' +
          inst.name +
          '">' +
          btnLabel +
          '</button>' +
          '</div>' +
          '<div class="inst-card-row"><span>\u72b6\u6001</span><span class="val ' +
          (inst.up ? 'active' : '') +
          '">' +
          stateText +
          `</span></div>` +
          `<div class="inst-card-row"><span>\u8fd0\u884c\u4e2d</span><span class="val ` +
          (inst.queue_running ? `active` : ``) +
          `">` +
          inst.queue_running +
          ` \u4efb\u52a1` +
          (inst.queue_running > 0 && inst.current_workflow ? `(\u2009${inst.current_workflow} - ${inst.progress}%)` : ``) +
          `</span></div>` +
          `<div class="inst-card-row"><span>\u6392\u961f</span><span class="val ` +
          (inst.queue_pending ? `pending` : ``) +
          `">` +
          inst.queue_pending +
          ` \u4efb\u52a1` +
          (inst.pending_workflows && inst.pending_workflows.length > 0 ? `(\u2009${inst.pending_workflows.join(' ')}` + `)` : ``) +
          `</span></div>`;
        if (inst.loaded_group) html += '<span class="inst-card-group">' + escH(inst.loaded_group) + '</span>';
        html += '</div>';
        }
      }
      if (!html) html = '<div class="st-empty">\u6682\u65e0 ComfyUI \u5b9e\u4f8b</div>';
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML =
        '<div class="st-error">\u52a0\u8f7d\u5931\u8d25: ' + escH(e.message) + '</div>';
    }
  }

async function _refreshGpuCards() {
    var box = $('#instCards');
    if (!box) return;
    box.innerHTML = '<div class="st-empty">\u52a0\u8f7d\u4e2d...</div>';
    try {
      var r = await fetch(API + '/api/gpu-processes');
      var d = await r.json();
      var procs = d.processes || [];
      var html = '<div class="popup-section-title">\u5360\u7528 GPU \u663e\u5b58\u7684\u8fdb\u7a0b</div>';
      if (procs.length === 0)
        html +=
          '<div class="st-empty">\u65e0\u5176\u4ed6\u663e\u5b58\u5360\u7528\u8fdb\u7a0b</div>';
      for (var i = 0; i < procs.length; i++) {
        var p = procs[i];
        html +=
          '<div class="gpu-card">' +
          '<div class="gpu-card-info">' +
          '<div class="gpu-card-name" title="' +
          escH(p.process) +
          '">' +
          escH(p.name) +
          '</div>' +
          '<div class="gpu-card-detail">PID ' +
          p.pid +
          ' \u00b7 ' +
          escH(p.process) +
          '</div>' +
          '</div>' +
          '<span class="gpu-card-mem">' +
          p.mem_mb +
          ' MB</span>' +
          '<button class="gpu-card-kill" onclick="CW.killGpuProc(' +
          p.pid +
          ')" id="gpuKill' +
          p.pid +
          '">\u7ec8\u6b62</button>' +
          '</div>';
      }
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML =
        '<div class="st-error">\u52a0\u8f7d\u5931\u8d25: ' + escH(e.message) + '</div>';
    }
  }

async function toggleInst(name, start) {
    var btn = document.getElementById('instBtn' + name);
    if (btn) {
      btn.disabled = true;
      btn.textContent = '...';
    }
    try {
      var r = await fetch(API + '/api/comfyui/' + name + '/' + (start ? 'start' : 'stop'), { method: 'POST' });
      var d = await r.json();
      if (!r.ok) throw new Error(d.detail || '\u64cd\u4f5c\u5931\u8d25');
    } catch (e) {
      alert('\u64cd\u4f5c\u5931\u8d25: ' + e.message);
    }
    setTimeout(_refreshInstCards, 1500);
    setTimeout(pollStatus, 2000);
  }

async function killGpuProc(pid) {
    if (!confirm('\u786e\u5b9a\u7ec8\u6b62 PID ' + pid + ' \uff1f')) return;
    var btn = document.getElementById('gpuKill' + pid);
    if (btn) {
      btn.disabled = true;
      btn.textContent = '...';
    }
    try {
      var r = await fetch(API + '/api/gpu-processes/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid: pid }),
      });
      var d = await r.json();
      if (!r.ok) throw new Error(d.detail || '\u64cd\u4f5c\u5931\u8d25');
    } catch (e) {
      alert('\u64cd\u4f5c\u5931\u8d25: ' + e.message);
    }
    setTimeout(_refreshGpuCards, 1500);
  }

function initServiceToggles() {
    var comfyBtn = $('#svcComfyUI');
    if (comfyBtn)
      comfyBtn.addEventListener('click', function () {
        openInstPopup('comfyui');
      });
  }

  if (!window.CW) window.CW = {};
  window.CW.openInstPopup = openInstPopup;
  window.CW.closeInstPopup = closeInstPopup;
  window.CW.toggleInst = toggleInst;
  window.CW.killGpuProc = killGpuProc;
  window.CW.setTargetInstance = function(name, nodeId) {
    A.currentTargetInstance = name || '';
    A.currentTargetNodeId = nodeId || '';
    pollStatus();
    _refreshInstCards();
  };
  window.CW.pollStatus = pollStatus;
})();
