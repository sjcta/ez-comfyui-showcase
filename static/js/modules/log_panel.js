/**
 * log_panel.js — 日志面板状态管理
 * 纯 class 切换，零内联样式
 * 独立于 app.js 加载，避免 IIFE 作用域冲突
 */
(function() {
  'use strict';

  var ICON_DOCK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>';
  var ICON_UNDOCK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ><polyline points="15 18 9 12 15 6"/></svg>';
  var _logPanelPos = null;
  var _expandedLogGroups = {};

  function _isMobileLogViewport() {
    return window.matchMedia('(max-width: 900px)').matches;
  }

  function _logLoad() {
    var API = window.CW_API_BASE || location.pathname.replace(/\/+$/, '');
    fetch(API + '/api/logs').then(function(r) {
      return r.json().then(function(data) {
        if (!r.ok) throw new Error((data && data.detail) || '日志加载失败');
        if (!Array.isArray(data)) throw new Error('日志格式异常');
        return data;
      });
    }).then(function(entries) {
      window.CW._logEntries = entries;
      var body = document.getElementById('logBody');
      if (body) {
        _renderLogEntries(entries);
        requestAnimationFrame(function() { body.scrollTop = body.scrollHeight; });
      }
      var countEl = document.getElementById('logCount');
      if (countEl) countEl.textContent = entries.length;
    }).catch(function(err) {
      window.CW._logEntries = [];
      var body = document.getElementById('logBody');
      if (body) {
        body.innerHTML = '';
        var el = document.createElement('div');
        el.className = 'log-entry';
        el.textContent = err && err.message ? err.message : '日志加载失败';
        body.appendChild(el);
      }
      var countEl = document.getElementById('logCount');
      if (countEl) countEl.textContent = '0';
    });
  }

  function _logWorkflowClass(workflowType, jobId) {
    if (!jobId) return 'log-system';
    if (workflowType === '文生图') return 'log-flow log-flow-t2i';
    if (workflowType === '图生图') return 'log-flow log-flow-i2i';
    if (workflowType === '文生视频') return 'log-flow log-flow-t2v';
    if (workflowType === '图生视频') return 'log-flow log-flow-i2v';
    if (workflowType === '放大') return 'log-flow log-flow-cat';
    if (workflowType) return 'log-flow log-flow-other';
    var str = String(jobId);
    var hash = 0;
    for (var i = 0; i < str.length; i++) hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    return 'log-flow log-flow-' + (Math.abs(hash) % 8);
  }

  function _logEntryKey(e) {
    return [
      e && e.ts ? Number(e.ts).toFixed(3) : '',
      e && e.job_id ? e.job_id : '',
      e && e.level ? e.level : '',
      e && e.phase ? e.phase : '',
      e && e.msg ? e.msg : ''
    ].join('|');
  }

  function _escLogText(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function _logWorkflowName(entries) {
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].workflow) return entries[i].workflow;
      var msg = String(entries[i].msg || '');
      var m = msg.match(/Job queued:\s*(.+)$/);
      if (m && m[1]) return m[1];
    }
    return entries.length && entries[0].job_id ? 'Job ' + entries[0].job_id : '工作流任务';
  }

  function _isCompletionLog(e) {
    var msg = String((e && e.msg) || '');
    return msg.indexOf('工作流完成') >= 0 || msg.indexOf('Workflow finished') >= 0;
  }

  function _logGroupKey(jobId) {
    return 'group|' + String(jobId || '');
  }

  function _appendLogEntry(body, e, extraClass) {
    var el = document.createElement('div');
    el.className = 'log-entry ' + _logWorkflowClass(e.workflow_type || '', e.job_id || '') + (extraClass ? ' ' + extraClass : '');
    el.dataset.logKey = _logEntryKey(e);
    if (e.workflow) el.title = e.workflow;
    var ts = new Date(e.ts * 1000).toLocaleTimeString();
    var levelCls = e.level === 'info' ? 'info dim' : e.level;
    var msgHtml = _escLogText(e.msg || '');
    var pctMatch = msgHtml.match(/采样 (\d+)\/(\d+)|Sampling (\d+)\/(\d+)/);
    if (pctMatch) {
      var cur = parseInt(pctMatch[1] || pctMatch[3], 10);
      var total = parseInt(pctMatch[2] || pctMatch[4], 10);
      var pct = total ? Math.round(cur / total * 100) : 0;
      msgHtml = msgHtml + ' <span class="log-pct">(' + pct + '%)</span>';
    }
    var phaseCls = ['节点','采样','步进','开始','完成','node','sampler','step','start','complete','done'].includes(e.phase) ? 'workflow-phase' : '';
    var msgCls = msgHtml.includes('采样') || msgHtml.includes('Sampl') ? 'sampling' : (msgHtml.includes('VAE') ? 'vae' : '');
    el.innerHTML = '<span class="log-time">' + ts + '</span>'
      + '<span class="log-level ' + levelCls + '">' + e.level.toUpperCase() + '</span>'
      + '<span class="log-phase ' + phaseCls + '">[' + e.phase + ']</span>'
      + '<span class="log-msg ' + msgCls + '">' + msgHtml + '</span>'
      + (e.details ? '<div class="log-details">' + _escLogText(e.details) + '</div>' : '');
    body.appendChild(el);
  }

  function _appendLogGroup(body, group) {
    var entries = group.entries || [];
    if (!entries.length) return;
    var first = entries[0];
    var last = entries[entries.length - 1];
    var key = _logGroupKey(group.jobId);
    var expanded = !!_expandedLogGroups[group.jobId];
    var el = document.createElement('div');
    el.className = 'log-group ' + _logWorkflowClass(first.workflow_type || '', first.job_id || '') + (expanded ? ' expanded' : '');
    el.dataset.logKey = key;
    el.dataset.jobId = group.jobId;
    var startTs = new Date(first.ts * 1000).toLocaleTimeString();
    var endTs = new Date(last.ts * 1000).toLocaleTimeString();
    var workflow = _logWorkflowName(entries).replace(/\.json$/, '');
    el.innerHTML =
      '<button class="log-group-head" type="button" onclick="CW.toggleLogGroup(\'' + _escLogText(group.jobId) + '\')" title="展开/收起日志">' +
        '<span class="log-group-caret">' + (expanded ? '⌄' : '›') + '</span>' +
        '<span class="log-time">' + startTs + ' - ' + endTs + '</span>' +
        '<span class="log-level info dim">DONE</span>' +
        '<span class="log-phase workflow-phase">[完成]</span>' +
        '<span class="log-msg"><strong>' + _escLogText(workflow) + '</strong><span class="log-group-meta"> · ' + entries.length + ' 条日志 · #' + _escLogText(group.jobId) + '</span></span>' +
      '</button>';
    if (expanded) {
      var detail = document.createElement('div');
      detail.className = 'log-group-detail';
      entries.forEach(function(e) { _appendLogEntry(detail, e, 'log-entry-nested'); });
      el.appendChild(detail);
    }
    body.appendChild(el);
  }

  function _buildLogRenderItems(entries, levelFilter) {
    var byJob = {};
    entries.forEach(function(e) {
      var jobId = e && e.job_id ? String(e.job_id) : '';
      if (!jobId) return;
      if (!byJob[jobId]) byJob[jobId] = { jobId: jobId, entries: [], completed: false };
      byJob[jobId].entries.push(e);
      if (_isCompletionLog(e)) byJob[jobId].completed = true;
    });
    var emittedGroups = {};
    var items = [];
    entries.forEach(function(e) {
      if (levelFilter && e.level !== levelFilter) return;
      var jobId = e && e.job_id ? String(e.job_id) : '';
      var group = jobId ? byJob[jobId] : null;
      if (group && group.completed) {
        if (emittedGroups[jobId]) return;
        emittedGroups[jobId] = true;
        var visibleEntries = levelFilter ? group.entries.filter(function(ge) { return ge.level === levelFilter; }) : group.entries;
        if (visibleEntries.length) items.push({ type: 'group', jobId: jobId, entries: visibleEntries });
        return;
      }
      items.push({ type: 'entry', entry: e });
    });
    return items;
  }

  function _renderLogEntries(entries) {
    var body = document.getElementById('logBody');
    if (!body) return;
    var sel = document.getElementById('logLevelFilter');
    var val = sel ? sel.value : '';
    var oldByKey = {};
    Array.prototype.slice.call(body.children).forEach(function(child) {
      var key = child.dataset ? child.dataset.logKey : '';
      if (key) oldByKey[key] = child;
    });
    var seen = {};
    var items = _buildLogRenderItems(entries, val);
    items.forEach(function(item) {
      var key = item.type === 'group' ? _logGroupKey(item.jobId) : _logEntryKey(item.entry);
      seen[key] = true;
      if (oldByKey[key]) {
        oldByKey[key].remove();
      }
      if (item.type === 'group') {
        _appendLogGroup(body, item);
      } else if (oldByKey[key]) {
        body.appendChild(oldByKey[key]);
      } else {
        _appendLogEntry(body, item.entry);
      }
    });
    Object.keys(oldByKey).forEach(function(key) {
      if (!seen[key] && oldByKey[key].parentNode) oldByKey[key].remove();
    });
  }

  function _logSetState(state) {
    var panel = document.getElementById('logPanel');
    var colRight = document.getElementById('colRight');
    var tbBtn = document.getElementById('tbLogBtn');
    var dockBtn = document.getElementById('logDockBtn');
    if (!panel || !colRight) return;
    panel.classList.remove('log-panel--floating', 'log-panel--docked', 'log-panel--mobile-docked', 'log-panel--hidden');

    if (state === 'hidden') {
      if (panel.parentNode && panel.parentNode.id === 'colRight') {
        colRight.classList.remove('log-open');
        document.body.appendChild(panel);
      } else if (panel.parentNode !== document.body) {
        document.body.appendChild(panel);
      }
      panel.classList.add('log-panel--hidden');
      if (tbBtn) tbBtn.classList.remove('active');
      if (dockBtn) { dockBtn.innerHTML = ICON_DOCK; dockBtn.title = '\u5438\u9644\u5230\u53f3\u4fa7'; }
      return;
    }
    if (state === 'docked') {
      if (panel.parentNode && panel.parentNode.id === 'colRight') return;
      colRight.appendChild(panel);
      colRight.classList.add('log-open');
      panel.classList.add('log-panel--docked');
      if (tbBtn) tbBtn.classList.add('active');
      if (dockBtn) { dockBtn.innerHTML = ICON_UNDOCK; dockBtn.title = '\u53d6\u6d88\u5438\u9644'; }
      return;
    }
    if (state === 'mobile-docked') {
      colRight.classList.remove('log-open');
      if (panel.parentNode !== document.body) document.body.appendChild(panel);
      panel.classList.add('log-panel--mobile-docked');
      panel.style.removeProperty('--log-top');
      panel.style.removeProperty('--log-left');
      panel.style.removeProperty('--log-right');
      if (tbBtn) tbBtn.classList.add('active');
      if (dockBtn) { dockBtn.innerHTML = ICON_UNDOCK; dockBtn.title = '\u53d6\u6d88\u5438\u9644'; }
      return;
    }
    if (state === 'floating') {
      if (panel.parentNode && panel.parentNode.id === 'colRight') {
        colRight.classList.remove('log-open');
        document.body.appendChild(panel);
      } else if (panel.parentNode !== document.body) {
        document.body.appendChild(panel);
      }
      panel.classList.add('log-panel--floating');
      panel.style.removeProperty('--log-top');
      panel.style.removeProperty('--log-left');
      panel.style.removeProperty('--log-right');
      if (tbBtn) tbBtn.classList.add('active');
      if (dockBtn) { dockBtn.innerHTML = ICON_DOCK; dockBtn.title = '\u5438\u9644\u5230\u53f3\u4fa7'; }
    }
  }

  window.CW.toggleLog = function() {
    var panel = document.getElementById('logPanel');
    if (!panel) return;
    var inCol = panel.parentNode && panel.parentNode.id === 'colRight';
    if (inCol) { _logSetState('hidden'); return; }
    if (panel.classList.contains('log-panel--hidden')) {
      _logSetState('floating');
      _logLoad();
    } else {
      _logSetState('hidden');
    }
  };

  window.CW.closeLog = function() { _logSetState('hidden'); };

  window.CW.toggleLogDock = function() {
    var panel = document.getElementById('logPanel');
    if (!panel) return;
    var inCol = panel.parentNode && panel.parentNode.id === 'colRight';
    var isMobileDocked = panel.classList.contains('log-panel--mobile-docked');
    if (_isMobileLogViewport()) {
      _logSetState(isMobileDocked ? 'floating' : 'mobile-docked');
      if (!isMobileDocked) _logLoad();
      return;
    }
    _logSetState(inCol ? 'floating' : 'docked');
    if (!inCol) _logLoad();
  };

  window.CW._onLog = function(entry) {
    window.CW._logEntries = window.CW._logEntries || [];
    var key = _logEntryKey(entry);
    for (var i = 0; i < window.CW._logEntries.length; i++) {
      if (_logEntryKey(window.CW._logEntries[i]) === key) return;
    }
    window.CW._logEntries.push(entry);
    var countEl = document.getElementById('logCount');
    if (countEl) countEl.textContent = String(window.CW._logEntries.length);
    var body = document.getElementById('logBody');
    if (!body) return;
    _renderLogEntries(window.CW._logEntries);
    body.scrollTop = body.scrollHeight;
  };

  window.CW.toggleLogGroup = function(jobId) {
    _expandedLogGroups[jobId] = !_expandedLogGroups[jobId];
    _renderLogEntries(window.CW._logEntries || []);
  };

  window.CW.applyLogFilter = function() {
    var sel = document.getElementById('logLevelFilter');
    if (!sel) return;
    var entries = window.CW._logEntries || [];
    var body = document.getElementById('logBody');
    _renderLogEntries(entries);
    if (body) requestAnimationFrame(function() { body.scrollTop = body.scrollHeight; });
  };

  window.CW.clearLog = function() {
    window.CW._logEntries = [];
    var body = document.getElementById('logBody');
    if (body) body.innerHTML = '';
    var countEl = document.getElementById('logCount');
    if (countEl) countEl.textContent = '0';
  };

  // ── 拖拽 ──
  function _initDrag() {
    var panel = document.getElementById('logPanel');
    var header = panel && panel.querySelector('.log-header');
    if (!panel || !header) { setTimeout(_initDrag, 100); return; }
    header.addEventListener('mousedown', function(e) {
      if (panel.parentNode && panel.parentNode.id === 'colRight') return;
      if (!panel.classList.contains('log-panel--floating')) return;
      if (e.target.closest('button, input, select, textarea')) return;
      e.preventDefault();
      var rect = panel.getBoundingClientRect();
      var dx = e.clientX - rect.left;
      var dy = e.clientY - rect.top;
      function onMove(ev) {
        var left = ev.clientX - dx;
        var top = ev.clientY - dy;
        panel.style.setProperty('--log-top', top + 'px');
        panel.style.setProperty('--log-left', left + 'px');
        panel.style.removeProperty('--log-right');
        _logPanelPos = { top: top, right: null, left: left };
      }
      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initDrag);
  } else {
    _initDrag();
  }

  window.addEventListener('resize', function() {
    var panel = document.getElementById('logPanel');
    if (!panel) return;
    if (_isMobileLogViewport()) {
      if (panel.parentNode && panel.parentNode.id === 'colRight') {
        _logSetState('mobile-docked');
      }
      return;
    }
    if (panel.classList.contains('log-panel--mobile-docked')) {
      _logSetState('floating');
    }
  });

})();
