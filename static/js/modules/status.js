/**
 * Status Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var jobs = A.jobs, API = A.API;
  var _lastRunningSummaries = [];
  var _lastStatusInstances = [];

  function _setCurrentTarget(inst, manual) {
    if (!inst) return;
    A.currentTargetInstance = inst.name || '';
    A.currentTargetNodeId = inst.node_id || '';
    A.manualTargetInstance = !!manual;
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
      _setCurrentTarget(selected, false);
    }
    return selected;
  }

  function _instanceDisplayRank(inst) {
    inst = inst || {};
    var name = String(inst.name || inst.id || '').trim();
    var upper = name.toUpperCase();
    if (inst.prompt_aux || inst.role === 'prompt_aux' || upper === 'PROMPT') return [3, name.toLowerCase()];
    if (upper === 'A') return [0, 0];
    if (upper === 'B') return [0, 1];
    if (/^[A-Z]$/.test(upper)) return [0, upper.charCodeAt(0) - 65];
    var match = name.match(/\d+/);
    if (match) return [1, Number(match[0]), name.toLowerCase()];
    return [2, name.toLowerCase()];
  }

  function _compareRank(a, b) {
    var len = Math.max(a.length, b.length);
    for (var i = 0; i < len; i++) {
      var av = a[i] == null ? '' : a[i];
      var bv = b[i] == null ? '' : b[i];
      if (av < bv) return -1;
      if (av > bv) return 1;
    }
    return 0;
  }

  function _statusNodeKey(inst) {
    inst = inst || {};
    return inst.node_id || inst.node_name || 'default';
  }

  function _sortInstancesForDisplay(instances) {
    var nodeOrder = {};
    var nextNode = 0;
    return (instances || []).map(function(inst, idx) {
      var nodeKey = _statusNodeKey(inst);
      if (nodeOrder[nodeKey] == null) nodeOrder[nodeKey] = nextNode++;
      return { inst: inst, idx: idx, nodeRank: nodeOrder[nodeKey], rank: _instanceDisplayRank(inst) };
    }).sort(function(a, b) {
      if (a.nodeRank !== b.nodeRank) return a.nodeRank - b.nodeRank;
      var byRank = _compareRank(a.rank, b.rank);
      return byRank || (a.idx - b.idx);
    }).map(function(item) {
      return item.inst;
    });
  }

  function _displayStatusInstances(instances) {
    return _sortInstancesForDisplay(instances || []);
  }

  function _isTerminalJobStatus(status) {
    return status === 'done' || status === 'error' || status === 'history';
  }

  function _jobProgressPct(job) {
    var status = (job && job.status) || '';
    var pct = job && job.progress ? Number(job.progress.pct) : 0;
    if (!isFinite(pct)) pct = 0;
    if (status === 'downloading') pct = Math.max(pct, 98);
    return _clampPct(pct);
  }

  function _activeJobState() {
    var vals = Object.values(jobs || {});
    var best = null;
    for (var i = 0; i < vals.length; i++) {
      var job = vals[i] || {};
      var status = job.status || '';
      if (_isTerminalJobStatus(status)) continue;
      var pct = _jobProgressPct(job);
      if (!best || pct >= best.pct) {
        best = {
          pct: pct,
          instance: job.instance || '',
          node_id: job.target_node_id || job.node_id || '',
          status: status,
        };
      }
    }
    if (!best) return null;
    best.pct = Math.max(0, Math.min(100, Math.round(best.pct)));
    return best;
  }

  function _activeJobStatesByInstance() {
    var vals = Object.values(jobs || {});
    var byKey = {};
    for (var i = 0; i < vals.length; i++) {
      var job = vals[i] || {};
      var status = job.status || '';
      if (_isTerminalJobStatus(status)) continue;
      var instance = job.instance || '';
      if (!instance) continue;
      var nodeId = job.target_node_id || job.node_id || '';
      var key = instance + '|' + nodeId;
      var pct = _jobProgressPct(job);
      if (!byKey[key] || pct >= byKey[key].pct) {
        byKey[key] = {
          label: instance,
          instance: instance,
          node_id: nodeId,
          pct: pct,
        };
      }
    }
    return Object.keys(byKey).map(function(key) { return byKey[key]; });
  }

  function _activeJobProgress() {
    var state = _activeJobState();
    return state ? state.pct : null;
  }

  function _findInstanceForJob(instances, jobState) {
    if (!jobState || !jobState.instance) return null;
    return (instances || []).find(function(inst) {
      return inst.name === jobState.instance &&
        (!jobState.node_id || inst.node_id === jobState.node_id);
    }) || (instances || []).find(function(inst) {
      return inst.name === jobState.instance;
    }) || null;
  }

  function _clampPct(value) {
    var pct = Number(value || 0);
    if (!isFinite(pct)) pct = 0;
    return Math.max(0, Math.min(100, Math.round(pct)));
  }

  function _runningInstanceSummaries(instances, activeJob) {
    var out = [];
    for (var i = 0; i < (instances || []).length; i++) {
      var inst = instances[i] || {};
      if ((inst.queue_running || 0) <= 0) continue;
      var pct = _clampPct(inst.progress || 0);
      if (activeJob && activeJob.instance === inst.name) {
        pct = Math.max(pct, _clampPct(activeJob.pct));
      }
      var unknownRemote = !!inst.remote_untracked_running && inst.progress_known === false;
      out.push({
        label: inst.name || inst.node_name || '实例',
        instance: inst.name || '',
        node_id: inst.node_id || '',
        pct: pct,
        text: unknownRemote ? '未追踪任务中' : '',
      });
    }
    return out;
  }

  function _copyRunningSummary(item) {
    item = item || {};
    return {
      label: item.label || item.instance || '实例',
      instance: item.instance || item.label || '',
      node_id: item.node_id || '',
      pct: _clampPct(item.pct),
      text: item.text || '',
    };
  }

  function _findRunningSummaryIndex(out, item) {
    var instance = item && item.instance;
    var nodeId = item && item.node_id;
    for (var i = 0; i < out.length; i++) {
      if (out[i].instance === instance && (!nodeId || !out[i].node_id || out[i].node_id === nodeId)) return i;
    }
    return -1;
  }

  function _mergeRunningSummaries(baseSummaries, jobStates) {
    var out = (baseSummaries || []).map(_copyRunningSummary);
    for (var i = 0; i < (jobStates || []).length; i++) {
      var state = _copyRunningSummary(jobStates[i]);
      var idx = _findRunningSummaryIndex(out, state);
      if (idx >= 0) out[idx] = Object.assign({}, out[idx], state);
      else out.push(state);
    }
    return out;
  }

  function _rememberRunningSummaries(summaries, keep) {
    if ((summaries || []).length || keep) {
      _lastRunningSummaries = (summaries || []).map(_copyRunningSummary);
    } else {
      _lastRunningSummaries = [];
    }
  }

  function _runningStateText(summaries, fallbackPct) {
    if ((summaries || []).length > 1) {
      return summaries.map(function(item) {
        return item.label + ': ' + (item.text || (item.pct + '%'));
      }).join(' | ');
    }
    if ((summaries || []).length === 1 && summaries[0].text) return summaries[0].text;
    return '运行中 ' + _clampPct(fallbackPct) + '%';
  }

  function _instanceStateMeta(inst, activeByKey) {
    inst = inst || {};
    var rawName = inst.name || inst.node_name || '实例';
    var name = String(rawName).toUpperCase() === 'PROMPT' ? 'P' : rawName;
    var nodeId = inst.node_id || '';
    var key = (inst.name || '') + '|' + nodeId;
    var localActive = activeByKey && (activeByKey[key] || activeByKey[(inst.name || '') + '|']);
    var unknownRemote = !!inst.remote_untracked_running && inst.progress_known === false;
    if (!inst.up && !localActive) return { text: name + ': off', cls: 'off' };
    if (unknownRemote) return { text: name + ': 未追踪任务中', cls: 'running unknown' };
    if ((inst.queue_running || 0) > 0 || localActive) {
      var pct = _clampPct(inst.progress || 0);
      if (localActive) pct = Math.max(pct, _clampPct(localActive.pct));
      return { text: name + ': ' + pct + '%', cls: 'running' };
    }
    if ((inst.queue_pending || 0) > 0) return { text: name + ': pending', cls: 'pending' };
    return { text: name + ': idle', cls: 'idle' };
  }

  function _instanceSummaryItems(instances) {
    var display = _displayStatusInstances(instances);
    var activeStates = _activeJobStatesByInstance();
    var activeByKey = {};
    for (var i = 0; i < activeStates.length; i++) {
      var state = activeStates[i] || {};
      activeByKey[(state.instance || '') + '|' + (state.node_id || '')] = state;
    }
    return display.map(function(inst) {
      return _instanceStateMeta(inst, activeByKey);
    });
  }

  function _instanceSummaryText(instances) {
    return _instanceSummaryItems(instances).map(function(item) {
      return item.text;
    }).join(' | ');
  }

  function _instanceSummaryHtml(items) {
    return (items || []).map(function(item) {
      return '<span class="svc-inst ' + escA(item.cls || 'idle') + '">' + escH(item.text || '') + '</span>';
    }).join('<span class="svc-inst-sep"> | </span>');
  }

  function _setComfyStateText(el, text, html) {
    if (!el) return;
    el.textContent = text || '';
    el.innerHTML = html || escH(text || '');
  }

  function _safeVramMessage(gpu) {
    var msg = String((gpu && gpu.message) || '').trim();
    if (!msg) return 'VRAM 未上报';
    var rawError = /(connection\s+closed|permission\s+denied|connection\s+refused|timed?\s*out|no\s+route|host\s+key|known_hosts|port\s+\d+|ssh:|sshpass|stderr)/i;
    if (rawError.test(msg)) return 'VRAM 暂不可用';
    return msg.length > 24 ? 'VRAM 暂不可用' : msg;
  }

  function syncComfyServiceButton() {
    var activeJob = _activeJobState();
    var activePct = activeJob ? activeJob.pct : null;
    var runningSummaries = _mergeRunningSummaries(_lastRunningSummaries, _activeJobStatesByInstance());
    var comfyBtn = $('#svcComfyUI');
    var comfyState = $('#comfyState');
    var bar = $('#statusbar');
    var statusInstances = _lastStatusInstances || [];
    if (activePct == null && !runningSummaries.length) {
      if (comfyBtn) comfyBtn.classList.remove('running');
      if (bar && bar.dataset.instanceState === 'running') bar.dataset.instanceState = 'idle';
      if (statusInstances.length && comfyState) {
        var idleItems = _instanceSummaryItems(statusInstances);
        _setComfyStateText(
          comfyState,
          idleItems.map(function(item) { return item.text; }).join(' | '),
          _instanceSummaryHtml(idleItems)
        );
      }
      return;
    }
    if (bar) bar.dataset.instanceState = 'running';
    if (comfyBtn) {
      comfyBtn.classList.remove('pending', 'off');
      comfyBtn.classList.add('on', 'running');
    }
    if (comfyState) {
      if (statusInstances.length) {
        var items = _instanceSummaryItems(statusInstances);
        _setComfyStateText(
          comfyState,
          items.map(function(item) { return item.text; }).join(' | '),
          _instanceSummaryHtml(items)
        );
      } else {
        _setComfyStateText(comfyState, _runningStateText(runningSummaries, activePct));
      }
    }
  }

async function pollStatus() {
    try {
      var qs = new URLSearchParams();
      var activeJob = _activeJobState();
      if (activeJob && activeJob.node_id) qs.set('target_node_id', activeJob.node_id);
      else if (A.currentTargetNodeId) qs.set('target_node_id', A.currentTargetNodeId);
      if (activeJob && activeJob.instance) qs.set('target_instance', activeJob.instance);
      else if (A.currentTargetInstance) qs.set('target_instance', A.currentTargetInstance);
      const r = await fetch(`${API}/api/status${qs.toString() ? '?' + qs.toString() : ''}`);
      const d = await r.json();
      updateServices(d);
      updateGPU(d.gpu, d.instances || []);
    } catch {}
  }

function updateServices(d) {
    const insts = _sortInstancesForDisplay(d.instances || []);
    _lastStatusInstances = insts.slice();
    const target = _getCurrentTarget(insts);
    const comfyBtn = $('#svcComfyUI');
    const comfyState = $('#comfyState');
    const bar = $('#statusbar');
    const anyRunning = insts.some(function(inst) { return (inst.queue_running || 0) > 0; });
    const anyPending = insts.some(function(inst) { return (inst.queue_pending || 0) > 0; });
    var activeJob = _activeJobState();
    const runningInst = (target && (target.queue_running || 0) > 0)
      ? target
      : insts.find(function(inst) { return inst.up && (inst.queue_running || 0) > 0; });
    const pendingInst = (target && (target.queue_pending || 0) > 0)
      ? target
      : insts.find(function(inst) { return inst.up && (inst.queue_pending || 0) > 0; });
    var activeInst = _findInstanceForJob(insts, activeJob) || runningInst || pendingInst;
    var displayTarget = activeInst || target;
    var jobPct = activeJob ? activeJob.pct : null;
    var activeJobsByInstance = _activeJobStatesByInstance();
    var runningSummaries = _mergeRunningSummaries(_runningInstanceSummaries(insts, activeJob), activeJobsByInstance);
    var instPct = runningInst ? _clampPct(runningInst.progress || 0) : 0;
    var runningPct = jobPct == null ? instPct : Math.max(instPct, jobPct);
    var localRunning = jobPct != null;
    _rememberRunningSummaries(runningSummaries, anyRunning || localRunning);
    if (bar) bar.dataset.instanceState = (anyRunning || localRunning) ? 'running' : anyPending ? 'pending' : 'idle';
    if (comfyBtn) comfyBtn.className = 'svc-btn ' + (displayTarget && (displayTarget.up || localRunning || anyRunning) ? 'on' : 'off') + ((anyRunning || localRunning) ? ' running' : anyPending ? ' pending' : '');
    if (comfyBtn) comfyBtn.title = displayTarget ? ((displayTarget.node_name || '') + (displayTarget.name ? ' ' + displayTarget.name : '')).trim() : 'ComfyUI';
    if (comfyState) {
      var stateText = '';
      var stateHtml = '';
      var summaryItems = _instanceSummaryItems(insts);
      var summaryText = summaryItems.map(function(item) { return item.text; }).join(' | ');
      if (summaryText) stateText = summaryText;
      else if (anyRunning || localRunning) stateText = _runningStateText(runningSummaries, runningPct);
      else if (!displayTarget) stateText = '无可用实例';
      else if (!displayTarget.up) stateText = '已关闭';
      else if ((displayTarget.queue_pending || 0) > 0) stateText = '排队中';
      else stateText = '待机';
      if (summaryItems.length) stateHtml = _instanceSummaryHtml(summaryItems);
      _setComfyStateText(comfyState, stateText, stateHtml);
    }
  }

function updateGPU(g, instances) {
    const active = _findInstanceForJob(instances || [], _activeJobState());
    const target = active || _getCurrentTarget(instances || []);
    const gpu = target && target.gpu ? target.gpu : g;
    const fill = $('#vramFill');
    if (!fill) return;
    const pct = gpu && target ? (gpu.vram_pct || 0) : 0;
    const temp = gpu && target ? (gpu.temp_c || 0) : 0;
    const util = gpu && target ? Math.max(0, Math.min(100, Number(gpu.util_pct || 0))) : 0;
    fill.style.width = pct + '%';
    // State: green=idle, yellow=busy, red=overloaded.
    // Keep "red" for clearly high pressure so low VRAM usage does not look alarming.
    const isOverload = pct >= 80 || temp >= 85 || util >= 95;
    const isBusy = !isOverload && (pct >= 50 || temp >= 70 || util >= 70);
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
        ? `${(used / 1024).toFixed(1)} / ${(total / 1024).toFixed(1)} GB${compactVram ? '' : ` (${pct}%)`} · GPU ${util}% · ${temp} °C`
        : (target ? `${target.node_name || target.name} ${_safeVramMessage(gpu)}` : '无可用设备');
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
      var sortedInstances = _sortInstancesForDisplay(d.instances || []);
      for (var gi = 0; gi < sortedInstances.length; gi++) {
        var item = sortedInstances[gi];
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
        var isAux = !!inst.prompt_aux || inst.role === 'prompt_aux';
        var statusCls = inst.up ? 'on' : 'off';
        var btnLabel = inst.up ? '<svg width="12" height="12" viewBox="0 0 24 24" class="btn-svg"><rect x="4" y="4" width="16" height="16" rx="2" fill="currentColor"/></svg>\u505c\u6b62' : '<svg width="12" height="12" viewBox="0 0 24 24" class="btn-svg"><polygon points="5,3 22,12 5,21" fill="currentColor"/></svg>\u542f\u52a8';
        var btnCls = inst.up ? 'stop' : 'start';
        var groupLabel = groupMap[inst.loaded_group] || inst.loaded_group || '';
        var instBusy = (inst.queue_running || 0) > 0 || (inst.queue_pending || 0) > 0;
        var unknownRemote = !!inst.remote_untracked_running && inst.progress_known === false;
        var stateText = !inst.up
          ? '\u5173\u95ed'
          : unknownRemote
            ? '\u672a\u8ffd\u8e2a\u4efb\u52a1\u4e2d'
          : isAux && instBusy
            ? '\u8f85\u52a9\u4efb\u52a1\u4e2d'
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
          ' <span class="dim-tag">:' +
          inst.port +
          '</span>' +
          (isAux ? ' <span class="dim-tag">\u63d0\u793a\u8bcd\u8f85\u52a9</span>' : '') +
          '</div>' +
          (isAux
            ? '<button class="inst-card-btn" disabled>\u8f85\u52a9\u5b9e\u4f8b</button>'
            : '') +
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
          (inst.queue_running > 0 && inst.current_workflow
            ? `(\u2009${inst.current_workflow} - ${inst.progress}%)`
            : inst.queue_running > 0 && unknownRemote
              ? `(\u2009\u672a\u8ffd\u8e2a\u4efb\u52a1)`
              : ``) +
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
  window.CW.pollStatus = pollStatus;
  window.CW.syncComfyServiceButton = syncComfyServiceButton;
})();
