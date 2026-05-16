/**
 * PollManager — WS 优先, HTTP polling 兜底。
 *
 * 职责:
 *   统一管理 WS + HTTP fallback 两个数据源。
 *   WS 推送优先, HTTP 3s polling 仅做未收到 WS 推送时的保底。
 *   合并旧的两套轮询 (pollJobs 5s + _pollActiveJobs 3s) 为单一源。
 *   删除客户端 700s timeout 安全逻辑（信任服务端 stuck watcher）。
 *
 * 使用:
 *   1. new PollManager() 创建
 *   2. start() 启动 WS + HTTP polling
 *   3. onJobUpdate(job) 由 WS 回调
 *   4. stop() 停止所有轮询
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs;

  /**
   * PollManager — 统一 WS + HTTP fallback
   */
  function PollManager() {
    this.ws = null;
    this._pollTimer = null;
    this._timerTick = null;
    this._httpPolling = false;
    this._stopped = false;
  }

  /**
   * 启动 WS 连接 + HTTP polling (3s) + 计时器
   */
  PollManager.prototype.start = function () {
    var self = this;
    self._stopped = false;

    // ── WS connection ──
    self._connectWS();

    // ── HTTP polling (3s) — fallback when WS is missing ──
    self._startHTTPPoll();

    // ── Timer ticker (1s) — live elapsed timers ──
    if (!self._timerTick) {
      self._timerTick = setInterval(function () {
        self._tickTimers();
      }, 1000);
    }
  };

  /**
   * 停止所有轮询
   */
  PollManager.prototype.stop = function () {
    var self = this;
    self._stopped = true;
    if (self.ws) {
      try { self.ws.close(); } catch (e) {}
      self.ws = null;
    }
    if (self._pollTimer) {
      clearTimeout(self._pollTimer);
      self._pollTimer = null;
    }
    if (self._timerTick) {
      clearInterval(self._timerTick);
      self._timerTick = null;
    }
    self._httpPolling = false;
  };

  /**
   * WebSocket 连接
   */
  PollManager.prototype._connectWS = function () {
    var self = this;
    if (self._stopped) return;
    if (self.ws && (self.ws.readyState === WebSocket.OPEN || self.ws.readyState === WebSocket.CONNECTING)) return;

    var apiBase = window.CW_API_BASE || '';
    var wsTarget;
    if (apiBase) {
      wsTarget = apiBase.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:') + '/ws';
    } else {
      var proto = location.protocol === 'https:' ? 'wss' : 'ws';
      var base = location.pathname.replace(/\/+$/, '');
      wsTarget = proto + '://' + location.host + base + '/ws';
    }
    try {
      self.ws = new WebSocket(wsTarget);
    } catch (e) {
      console.error('[PollManager] WS creation failed:', e);
      setTimeout(function () { self._connectWS(); }, 5000);
      return;
    }

    self.ws.onopen = function () {
      console.log('[PollManager] WS connected');
    };

    self.ws.onmessage = function (e) {
      try {
        var d = JSON.parse(e.data);
        if (d.type === 'job_update') {
          self.onJobUpdate(d.job);
        } else if (d.type === 'log' && d.entry) {
          if (window.CW._onLog) window.CW._onLog(d.entry);
        }
      } catch (err) {
        console.warn('[PollManager] WS parse error:', err);
      }
    };

    self.ws.onclose = function () {
      console.log('[PollManager] WS closed, will reconnect in 5s');
      if (!self._stopped) {
        setTimeout(function () { self._connectWS(); }, 5000);
      }
    };

    self.ws.onerror = function () {
      console.error('[PollManager] WS error');
    };

    // Keepalive: send ping every 30s
    self._wsPingInterval = setInterval(function () {
      if (self.ws && self.ws.readyState === WebSocket.OPEN) {
        try { self.ws.send('ping'); } catch (e) {}
      }
    }, 30000);
  };

  /**
   * WS 推送回调 / HTTP fallback 统一入口
   * 处理 job 状态变更 → 触发 Toast / Gallery render / patch
   */
  PollManager.prototype.onJobUpdate = function (job) {
    var prev = jobs[job.id];

    // ── Toast on status change ──
    if (prev && prev.status !== job.status) {
      var shortId = job.id ? job.id.slice(-6) : '';
      var wfTag = window.CW.getWFType ? window.CW.getWFType(job.workflow) : '';
      var typeLabel = wfTag ? wfTag.text : '';
      try {
        if (window.CW.toast) {
          var toastTypes = { queued: 'queued', generating: 'generating', downloading: 'queued', done: 'done', error: 'error' };
          var tType = toastTypes[job.status] || 'info';
          window.CW.toast(shortId + ' ' + typeLabel + ' ' + (job.status === 'downloading' ? '拉取图片' : (job.status === 'queued' ? '排队中' : (job.status === 'generating' ? '出图中' : (job.status === 'done' ? '完成' : (job.status === 'error' ? '失败' : job.status))))), tType);
        }
      } catch (e) {}
    }

    // Update job store
    jobs[job.id] = job;

    // ── Done: immediate image swap + background history refresh ──
    if (job.status === 'done' && job.image) {
      if (!prev || prev.status !== 'done' || !prev.image) {
        if (window.CW._onJobDone) window.CW._onJobDone(job);
      }
      return;
    }

    // ── Error: remove from active + re-render ──
    if (job.status === 'error' && (!prev || prev.status !== 'error')) {
      if (window.CW._onJobError) window.CW._onJobError(job);
      return;
    }

    // ── Status transition (queued→preparing→generating→downloading): full rebuild ──
    if (!prev || prev.status !== job.status) {
      if (window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
      return;
    }

    // ── Same status (progress update): in-place patch via CardManager, NO flicker ──
    var cm = window.CW.cardManager;
    if (cm) cm.patchJobCard(job);
  };

  /**
   * HTTP fallback — 3s polling when WS is unavailable
   */
  PollManager.prototype._startHTTPPoll = function () {
    var self = this;
    if (self._httpPolling) return;
    self._httpPolling = true;
    self._doHTTPPoll();
  };

  PollManager.prototype._doHTTPPoll = function () {
    var self = this;
    if (self._stopped) {
      self._httpPolling = false;
      return;
    }

    // Only poll if there are active jobs
    if (!self._hasActiveJobs()) {
      self._pollTimer = setTimeout(function () { self._doHTTPPoll(); }, 3000);
      return;
    }

    window.CW.auth.apiFetch(API + '/api/jobs')
      .then(function (r) { return r.json(); })
      .then(function (serverJobs) {
        if (self._stopped) return;

        // Build lookup
        var serverMap = {};
        for (var i = 0; i < serverJobs.length; i++) {
          serverMap[serverJobs[i].id] = serverJobs[i];
        }

        var needRerender = false;
        var doneOrErrorProcessed = false;

        for (var id in serverMap) {
          if (!serverMap.hasOwnProperty(id)) continue;
          var sj = serverMap[id];
          var prev = jobs[id];

          if (!prev) {
            // New job appeared
            jobs[id] = sj;
            self.onJobUpdate(sj);
            needRerender = true;
          } else if (prev.status !== sj.status) {
            // Status changed
            jobs[id] = sj;
            self.onJobUpdate(sj);
            // onJobUpdate handles loadHistory for done/error itself
            if (sj.status === 'done' && sj.image) {
              doneOrErrorProcessed = true;
            } else if (sj.status === 'error') {
              doneOrErrorProcessed = true;
            } else {
              needRerender = true;
            }
          } else if (sj.status === 'generating' && sj.progress && prev.progress) {
            if (prev.progress.pct !== sj.progress.pct) {
              jobs[id] = sj;
              // In-place patch via CardManager
              var cm = window.CW.cardManager;
              if (cm) cm.patchJobCard(sj);
            }
          } else if (sj.status === 'generating') {
            // First progress info
            if (sj.progress && !prev.progress) {
              jobs[id] = sj;
              var cm2 = window.CW.cardManager;
              if (cm2) cm2.patchJobCard(sj);
            }
          }
        }

        // Cleanup stale jobs (server no longer tracks them)
        for (var cleanId in jobs) {
          if (jobs.hasOwnProperty(cleanId) && !serverMap[cleanId]) {
            delete jobs[cleanId];
            needRerender = true;
          }
        }

        if (doneOrErrorProcessed) {
          if (needRerender && window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
        } else if (needRerender) {
          if (window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
        }
      })
      .catch(function (err) {
        // Silently fail — WS should be the primary channel
      })
      .then(function () {
        if (!self._stopped) {
          self._pollTimer = setTimeout(function () { self._doHTTPPoll(); }, 3000);
        }
      });
  };

  /**
   * 检查是否有活跃任务 (queued/preparing/generating/downloading)
   */
  PollManager.prototype._hasActiveJobs = function () {
    var vals = Object.values(jobs);
    for (var i = 0; i < vals.length; i++) {
      var s = vals[i].status;
      if (s !== 'done' && s !== 'error' && s !== 'history') return true;
    }
    return false;
  };

  /**
   * 计时器 — 更新所有可用的 gi-timer
   */
  PollManager.prototype._tickTimers = function () {
    if (!this._hasActiveJobs()) return;
    var els = document.querySelectorAll('.gi-timer');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var ts = parseFloat(el.dataset.ts);
      if (ts > 0) {
        var sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        el.textContent = m > 0 ? m + 'm' + String(s).padStart(2, '0') + 's' : s + 's';
      }
    }
  };

  // ── Expose ──
  if (!window.CW) window.CW = {};
  window.CW.PollManager = PollManager;

  // Auto-initialize after DOM ready
  function _initPollManager() {
    if (window.CW.pollManager) return;
    window.CW.pollManager = new PollManager();
  }

  window.CW.initPollManager = _initPollManager;

})();
