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

  function _logLoad() {
    var API = window.CW_API_BASE || location.pathname.replace(/\/+$/, '');
    fetch(API + '/api/logs').then(function(r) { return r.json(); }).then(function(entries) {
      window.CW._logEntries = entries;
      var body = document.getElementById('logBody');
      if (body) { body.innerHTML = ''; entries.forEach(function(e) { if (window.CW._onLog) window.CW._onLog(e); }); }
      var countEl = document.getElementById('logCount');
      if (countEl) countEl.textContent = entries.length;
    }).catch(function() {});
  }

  function _logSetState(state) {
    var panel = document.getElementById('logPanel');
    var colRight = document.getElementById('colRight');
    var tbBtn = document.getElementById('tbLogBtn');
    var dockBtn = document.getElementById('logDockBtn');
    if (!panel || !colRight) return;
    panel.classList.remove('log-panel--floating', 'log-panel--docked', 'log-panel--hidden');

    if (state === 'hidden') {
      if (panel.parentNode && panel.parentNode.id === 'colRight') {
        colRight.classList.remove('log-open');
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
    if (state === 'floating') {
      if (panel.parentNode && panel.parentNode.id === 'colRight') {
        colRight.classList.remove('log-open');
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
    _logSetState(inCol ? 'floating' : 'docked');
    if (!inCol) _logLoad();
  };

  window.CW.applyLogFilter = function() {
    var sel = document.getElementById('logLevelFilter');
    if (!sel) return;
    var val = sel.value;
    var entries = window.CW._logEntries || [];
    var body = document.getElementById('logBody');
    if (!body) return;
    body.innerHTML = '';
    entries.forEach(function(e) {
      if (val && e.level !== val) return;
      var el = document.createElement('div');
      el.className = 'log-entry';
      var ts = new Date(e.ts * 1000).toLocaleTimeString();
      var levelCls = e.level === 'info' ? 'info dim' : e.level;
      var msgHtml = (e.msg || '');
      // Extract percentage from progress messages
      var pctMatch = msgHtml.match(/Sampling (\d+)\/(\d+)/);
      if (pctMatch) {
        var pct = Math.round(parseInt(pctMatch[1]) / parseInt(pctMatch[2]) * 100);
        msgHtml = msgHtml + ' <span class="log-pct">(' + pct + '%)</span>';
      }
      var phaseCls = ['node','sampler','step','start','complete','done'].includes(e.phase) ? e.phase : '';
      var msgCls = msgHtml.includes('Sampl') ? 'sampling' : (msgHtml.includes('VAE') ? 'vae' : '');
      el.innerHTML = '<span class="log-time">' + ts + '</span>'
        + '<span class="log-level ' + levelCls + '">' + e.level.toUpperCase() + '</span>'
        + '<span class="log-phase ' + phaseCls + '">[' + e.phase + ']</span>'
        + '<span class="log-msg ' + msgCls + '">' + msgHtml + '</span>'
        + (e.details ? '<div class="log-details">' + e.details + '</div>' : '');
      body.appendChild(el);
    });
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

})();
