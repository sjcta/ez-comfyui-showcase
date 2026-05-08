/**
 * Status & Service Management Module
 * Extracted from app.js — handles pollStatus, GPU display, service toggles
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$;
  var $$ = A.$$;
  var escH = A.escH;
  var escA = A.escA;
  var jobs = A.jobs;
  var API = A.API;

  // ══════════════════════════════════════════════════════════════════════════
  //  Status
  // ══════════════════════════════════════════════════════════════════════════

  async function pollStatus() {
    try {
      var r = await fetch(API + '/api/status');
      var d = await r.json();
      updateServices(d);
      updateGPU(d.gpu);
    } catch (e) {}
  }

  function updateServices(d) {
    var insts = d.instances || [];
    var anyUp = insts.some(function (i) { return i.up; });
    var comfyBtn = $('#svcComfyUI');
    var comfyState = $('#comfyState');
    if (comfyBtn) comfyBtn.className = 'svc-btn ' + (anyUp ? 'on' : 'off');
    if (comfyState) {
      var upCount = insts.filter(function (i) { return i.up; }).length;
      var busyCount = insts.filter(function (i) { return i.up && i.queue_running > 0; }).length;
      var pendCount = insts.filter(function (i) { return i.up && i.queue_pending > 0; }).length;
      if (!anyUp) comfyState.textContent = '全部关闭';
      else if (busyCount > 0) comfyState.textContent = '出图中(' + busyCount + '/' + upCount + ')';
      else if (pendCount > 0) comfyState.textContent = '排队中(' + pendCount + ')';
      else comfyState.textContent = '待机(' + upCount + ')';
    }
    var othersBtn = document.querySelector('#svcOthers');
    var othersState = document.querySelector('#othersState');
    if (othersBtn) othersBtn.className = 'svc-btn ' + (d.vllm ? 'on' : 'off');
    if (othersState) othersState.textContent = d.vllm ? 'vLLM' : '-';
  }

  function updateGPU(g) {
    if (!g) return;
    var fill = $('#vramFill');
    var pct = g.vram_pct || 0;
    var temp = g.temp_c || 0;
    fill.style.width = pct + '%';
    var isOverload = pct > 70 || temp > 65;
    var isBusy = pct > 30 || temp > 50;
    fill.className = 'sb-vram-fill' + (isOverload ? ' overload' : isBusy ? ' busy' : '');
    var bar = $('#statusbar');
    if (bar) bar.dataset.state = isOverload ? 'overload' : isBusy ? 'busy' : 'idle';
    $('#vramText').textContent =
      (g.vram_used_mb / 1024).toFixed(1) + ' / ' + (g.vram_total_mb / 1024).toFixed(0) + ' GB (' + pct + '%)';
    $('#gpuTemp').textContent = temp + ' °C';
    $('#gpuUtil').textContent = 'GPU ' + g.util_pct + '%';
    if (!$('#vramSegments').dataset.done) {
      [25, 50, 75].forEach(function (pct) {
        var seg = document.createElement('div');
        seg.className = 'sb-vram-seg';
        seg.style.left = pct + '%';
        $('#vramSegments').appendChild(seg);
      });
      $('#vramSegments').dataset.done = '1';
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  Service toggles
  // ══════════════════════════════════════════════════════════════════════════

  function openInstPopup(mode) {
    var overlay = $('#instPopup');
    var title = $('#instPopupTitle');
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
    if (total === 0) return '<span style="color:var(--dim);font-size:11px">\u65e0</span>';
    var html = '';
    for (var i = 0; i < running; i++) {
      html += '<div style="flex:1;height:8px;background:var(--green);border-radius:2px;min-width:4px"></div>';
    }
    for (var i = 0; i < pending; i++) {
      html += '<div style="flex:1;height:8px;background:#f59e0b;border-radius:2px;opacity:0.6;min-width:4px"></div>';
    }
    if (!html) html = '<div style="flex:1;height:8px;background:var(--border);border-radius:2px"></div>';
    return html;
  }

  async function _refreshInstCards() {
    var box = $('#instCards');
    if (!box) return;
    box.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:8px">\u52a0\u8f7d\u4e2d...</div>';
    try {
      var r = await fetch(API + '/api/comfyui/status');
      var d = await r.json();
      var html = '<div class="popup-section-title">ComfyUI \u5b9e\u4f8b</div>';
      var groupMap = { nunchaku: 'Nunchaku', 'z-image-turbo': 'Z-Image Turbo', seedvr: 'SeedVR' };
      for (var idx = 0; idx < (d.instances || []).length; idx++) {
        var inst = d.instances[idx];
        var statusCls = inst.up ? 'on' : 'off';
        var btnLabel = inst.up
          ? '<svg width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:3px"><rect x="4" y="4" width="16" height="16" rx="2" fill="currentColor"/></svg>\u505c\u6b62'
          : '<svg width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:3px"><polygon points="5,3 22,12 5,21" fill="currentColor"/></svg>\u542f\u52a8';
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
          '<div class="inst-card ' + statusCls + '">' +
          '<div class="inst-card-header">' +
          '<div class="inst-card-name"><span class="inst-led ' +
          statusCls +
          '"></span> \u5b9e\u4f8b ' +
          inst.name +
          ' <span style="color:var(--dim);font-size:11px">:' +
          inst.port +
          '</span></div>' +
          '<button class="inst-card-btn ' +
          btnCls +
          '" onclick="CW.toggleInst(\'' +
          inst.name +
          '\',' +
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
          '</span></div>' +
          '<div class="inst-card-row"><span>\u8fd0\u884c\u4e2d</span><span class="val ' +
          (inst.queue_running ? 'active' : '') +
          '">' +
          inst.queue_running +
          ' \u4efb\u52a1' +
          (inst.queue_running > 0 && inst.current_workflow ? '(\u2009' + inst.current_workflow + ' - ' + inst.progress + '%)' : '') +
          '</span></div>' +
          '<div class="inst-card-row"><span>\u6392\u961f</span><span class="val ' +
          (inst.queue_pending ? 'pending' : '') +
          '">' +
          inst.queue_pending +
          ' \u4efb\u52a1' +
          (inst.pending_workflows && inst.pending_workflows.length > 0 ? '(\u2009' + inst.pending_workflows.join(' ') + ')' : '') +
          '</span></div>';
        if (inst.loaded_group) html += '<span class="inst-card-group">' + escH(inst.loaded_group) + '</span>';
        html += '</div>';
      }
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML =
        '<div style="color:#ef4444;font-size:12px;padding:8px">\u52a0\u8f7d\u5931\u8d25: ' + escH(e.message) + '</div>';
    }
  }

  async function _refreshGpuCards() {
    var box = $('#instCards');
    if (!box) return;
    box.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:8px">\u52a0\u8f7d\u4e2d...</div>';
    try {
      var r = await fetch(API + '/api/gpu-processes');
      var d = await r.json();
      var procs = d.processes || [];
      var html = '<div class="popup-section-title">\u5360\u7528 GPU \u663e\u5b58\u7684\u8fdb\u7a0b</div>';
      if (procs.length === 0)
        html += '<div style="color:var(--dim);font-size:12px;padding:8px">\u65e0\u5176\u4ed6\u663e\u5b58\u5360\u7528\u8fdb\u7a0b</div>';
      for (var i = 0; i < procs.length; i++) {
        var p = procs[i];
        html +=
          '<div class="gpu-card">' +
          '<div class="gpu-card-info">' +
          '<div class="gpu-card-name" title="' + escH(p.process) + '">' + escH(p.name) + '</div>' +
          '<div class="gpu-card-detail">PID ' + p.pid + ' \u00b7 ' + escH(p.process) + '</div>' +
          '</div>' +
          '<span class="gpu-card-mem">' + p.mem_mb + ' MB</span>' +
          '<button class="gpu-card-kill" onclick="CW.killGpuProc(' + p.pid + ')" id="gpuKill' + p.pid + '">\u7ec8\u6b62</button>' +
          '</div>';
      }
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML =
        '<div style="color:#ef4444;font-size:12px;padding:8px">\u52a0\u8f7d\u5931\u8d25: ' + escH(e.message) + '</div>';
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
    var othersBtn = $('#svcOthers');
    if (othersBtn)
      othersBtn.addEventListener('click', function () {
        openInstPopup('others');
      });
  }

  // ── Expose on window._statusMod for app.js to merge into window.CW ──
  window._statusMod = {
    openInstPopup: openInstPopup,
    closeInstPopup: closeInstPopup,
    toggleInst: toggleInst,
    killGpuProc: killGpuProc,
  };

  // ── Expose init for main app.js ──
  window._initStatusModule = initServiceToggles;

  // ── Expose functions back to __APP__ for main app.js to call ──
  A.pollStatus = pollStatus;
})();
