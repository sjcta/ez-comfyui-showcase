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
    this._wsPingInterval = null;
    this._httpPolling = false;
    this._httpPollInFlight = false;
    this._resumeHandler = null;
    this._stopped = false;
    this._seenTerminalJobs = {};
    this._timerRaf = null;
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
    self._bindResumeEvents();

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
    if (self._wsPingInterval) {
      clearInterval(self._wsPingInterval);
      self._wsPingInterval = null;
    }
    if (self._timerRaf) {
      cancelAnimationFrame(self._timerRaf);
      self._timerRaf = null;
    }
    if (self._resumeHandler) {
      if (typeof document !== 'undefined' && document.removeEventListener) {
        document.removeEventListener('visibilitychange', self._resumeHandler);
      }
      if (typeof window !== 'undefined' && window.removeEventListener) {
        window.removeEventListener('focus', self._resumeHandler);
      }
      self._resumeHandler = null;
    }
    self._httpPolling = false;
    self._httpPollInFlight = false;
  };

  PollManager.prototype._bindResumeEvents = function () {
    var self = this;
    if (self._resumeHandler) return;
    self._resumeHandler = function () {
      if (self._stopped) return;
      if (typeof document !== 'undefined' && document.hidden) return;
      self._connectWS();
      self._doHTTPPoll(true);
    };
    if (typeof document !== 'undefined' && document.addEventListener) {
      document.addEventListener('visibilitychange', self._resumeHandler);
    }
    if (typeof window !== 'undefined' && window.addEventListener) {
      window.addEventListener('focus', self._resumeHandler);
    }
  };

  function _jobNeedsHistoryRefresh(job) {
    if (!job) return false;
    var status = job.status || '';
    return status !== 'done' && status !== 'error' && status !== 'cancelled' && status !== 'retrying' && status !== 'history';
  }

  function _isProtectedLocalSubmit(job) {
    if (!job) return false;
    var ts = Number(job._local_submitted_at || 0);
    if (!ts || Date.now() - ts > 15000) return false;
    var status = String(job.status || '');
    return status === 'queued' ||
      status === 'dispatching' ||
      status === 'preparing' ||
      status === 'starting_comfyui' ||
      status === 'submitting';
  }

  function _isTerminalJob(job) {
    var status = job && job.status || '';
    return status === 'done' || status === 'history';
  }

  function _currentUserId() {
    var user = window.CW && window.CW.auth && window.CW.auth.getCurrentUser
      ? window.CW.auth.getCurrentUser()
      : null;
    return user && (user.sub || user.id || user.user_id) ? String(user.sub || user.id || user.user_id) : '';
  }

  function _isJobVisibleToCurrentUser(job) {
    if (!job) return false;
    var user = window.CW && window.CW.auth && window.CW.auth.getCurrentUser
      ? window.CW.auth.getCurrentUser()
      : null;
    if (user && user.role === 'admin') return true;
    var owner = String(job.user_id || '');
    if (!owner) return true;
    var uid = _currentUserId();
    return !!uid && owner === uid;
  }

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
        } else if (d.type === 'history_update') {
          self.onHistoryUpdate(d);
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
    if (self._wsPingInterval) clearInterval(self._wsPingInterval);
    self._wsPingInterval = setInterval(function () {
      if (self.ws && self.ws.readyState === WebSocket.OPEN) {
        try { self.ws.send('ping'); } catch (e) {}
      }
    }, 30000);
  };

  PollManager.prototype.reconnect = function () {
    var old = this.ws;
    this.ws = null;
    if (old) {
      old.onclose = null;
      try { old.close(); } catch (e) {}
    }
    this._connectWS();
    this._doHTTPPoll(true);
  };

  /**
   * WS 推送回调 / HTTP fallback 统一入口
   * 处理 job 状态变更 → 触发 Toast / Gallery render / patch
   */
  PollManager.prototype.onJobUpdate = function (job) {
    if (!job || !job.id) return;
    if (!_isJobVisibleToCurrentUser(job)) {
      if (jobs[job.id]) {
        delete jobs[job.id];
        if (window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
      }
      return;
    }
    var prev = jobs[job.id];
    if (job.deleted || job.status === 'cancelled') {
      delete jobs[job.id];
      if (window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
      if (window.CW.syncComfyServiceButton) window.CW.syncComfyServiceButton();
      return;
    }

    if (!prev && _isTerminalJob(job)) {
      this._rememberTerminalJob(job.id);
      if (window.CW.loadHistoryNoRender) {
        Promise.resolve(window.CW.loadHistoryNoRender()).catch(function() {});
      }
      return;
    }

    // ── Toast on status change ──
    if (prev && prev.status !== job.status) {
      var shortId = job.id ? job.id.slice(-6) : '';
      var wfMeta = (A._wfMeta || {})[job.workflow] || {};
      var wfTag = window.CW.wfTag ? window.CW.wfTag(job.workflow, wfMeta.tags) : '';
      var typeLabel = wfTag ? wfTag.text : '';
      var toastByStatus = {
        queued: ['排队中', 'queued'],
        paused: ['已暂停', 'queued'],
        generating: ['出图中', 'generating'],
        checking: ['内容校验中', 'generating'],
        done: ['结束出图', 'done'],
        error: ['失败', 'error']
      };
      try {
        if (window.CW.toast && toastByStatus[job.status]) {
          window.CW.toast(shortId + ' ' + typeLabel + ' ' + toastByStatus[job.status][0], toastByStatus[job.status][1]);
        }
      } catch (e) {}
    }

    // Update job store
    jobs[job.id] = job;
    if (window.CW.syncComfyServiceButton) window.CW.syncComfyServiceButton();

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

  PollManager.prototype.onHistoryUpdate = function (update) {
    if (!update || !update.action) return;
    if (window.CW && typeof window.CW.onHistoryUpdate === 'function') {
      window.CW.onHistoryUpdate(update);
      return;
    }
    if (window.CW && typeof window.CW.loadHistory === 'function') {
      Promise.resolve(window.CW.loadHistory()).catch(function(e) {
        console.warn('[PollManager] loadHistory after history update failed:', e && e.message ? e.message : e);
      });
    }
    if (window.CW && typeof window.CW.loadWorkflows === 'function') {
      Promise.resolve(window.CW.loadWorkflows()).catch(function(e) {
        console.warn('[PollManager] loadWorkflows after history update failed:', e && e.message ? e.message : e);
      });
    }
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

  PollManager.prototype._doHTTPPoll = function (immediate) {
    var self = this;
    if (self._stopped) {
      self._httpPolling = false;
      return;
    }
    if (self._httpPollInFlight) return;
    if (immediate && self._pollTimer) {
      clearTimeout(self._pollTimer);
      self._pollTimer = null;
    }

    if (!window.CW.auth || !window.CW.auth.isLoggedIn || !window.CW.auth.isLoggedIn()) {
      self._pollTimer = setTimeout(function () { self._doHTTPPoll(); }, 3000);
      return;
    }

    self._httpPollInFlight = true;
    window.CW.auth.apiFetch(API + '/api/jobs')
      .then(function (r) { return r.json(); })
      .then(function (serverJobs) {
        if (self._stopped) return;

        // Build lookup
        var serverMap = {};
        for (var i = 0; i < serverJobs.length; i++) {
          if (!_isJobVisibleToCurrentUser(serverJobs[i])) continue;
          serverMap[serverJobs[i].id] = serverJobs[i];
        }

        var needRerender = false;
        var doneOrErrorProcessed = false;
        var historyRefresh = false;
        var historyRefreshNeedsRender = false;

        for (var id in serverMap) {
          if (!serverMap.hasOwnProperty(id)) continue;
          var sj = serverMap[id];
          var prev = jobs[id];

          if (!prev) {
            if (_isTerminalJob(sj)) {
              if (!self._seenTerminalJobs[id]) {
                self._rememberTerminalJob(id);
                historyRefresh = true;
              }
              continue;
            }
            // New job appeared
            self.onJobUpdate(sj);
            needRerender = true;
          } else if (prev.status !== sj.status) {
            // Status changed
            self.onJobUpdate(sj);
            // onJobUpdate handles loadHistory for done/error itself
            if (sj.status === 'done' && sj.image) {
              doneOrErrorProcessed = true;
            } else if (sj.status === 'error' || sj.status === 'retrying') {
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
              if (window.CW.syncComfyServiceButton) window.CW.syncComfyServiceButton();
            }
          } else if ((sj.status === 'queued' || sj.status === 'paused') && prev.message !== sj.message) {
            jobs[id] = sj;
            var cmQueued = window.CW.cardManager;
            if (cmQueued) cmQueued.patchJobCard(sj);
            if (window.CW.syncComfyServiceButton) window.CW.syncComfyServiceButton();
          } else if (sj.status === 'generating') {
            // First progress info
            if (sj.progress && !prev.progress) {
              jobs[id] = sj;
              var cm2 = window.CW.cardManager;
              if (cm2) cm2.patchJobCard(sj);
              if (window.CW.syncComfyServiceButton) window.CW.syncComfyServiceButton();
            }
          }
        }

        // Cleanup stale jobs (server no longer tracks them)
        for (var cleanId in jobs) {
          if (jobs.hasOwnProperty(cleanId) && !serverMap[cleanId]) {
            if (_isProtectedLocalSubmit(jobs[cleanId])) continue;
            if (_jobNeedsHistoryRefresh(jobs[cleanId])) historyRefresh = true;
            if (_jobNeedsHistoryRefresh(jobs[cleanId])) historyRefreshNeedsRender = true;
            delete jobs[cleanId];
            needRerender = true;
          }
        }

        if (doneOrErrorProcessed) {
          if (needRerender && window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
        } else if (historyRefresh) {
          if (historyRefreshNeedsRender && window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
          var historyLoader = historyRefreshNeedsRender ? window.CW.loadHistory : (window.CW.loadHistoryNoRender || window.CW.loadHistory);
          if (historyLoader) {
            Promise.resolve(historyLoader()).catch(function(e) {
              console.warn('[PollManager] loadHistory after stale job failed:', e && e.message ? e.message : e);
            });
          }
        } else if (needRerender) {
          if (window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
        }
      })
      .catch(function (err) {
        // Silently fail — WS should be the primary channel
      })
      .then(function () {
        self._httpPollInFlight = false;
        self._pruneSeenTerminalJobs();
        if (!self._stopped) {
          self._pollTimer = setTimeout(function () { self._doHTTPPoll(); }, 3000);
        }
      });
  };

  PollManager.prototype._rememberTerminalJob = function (jobId) {
    if (!jobId) return;
    this._seenTerminalJobs[jobId] = Date.now();
  };

  PollManager.prototype._pruneSeenTerminalJobs = function () {
    var cutoff = Date.now() - 10 * 60 * 1000;
    for (var id in this._seenTerminalJobs) {
      if (this._seenTerminalJobs.hasOwnProperty(id) && this._seenTerminalJobs[id] < cutoff) {
        delete this._seenTerminalJobs[id];
      }
    }
  };

  /**
   * 检查是否有活跃任务 (queued/preparing/generating/downloading)
   */
  PollManager.prototype._hasActiveJobs = function () {
    var vals = Object.values(jobs);
    for (var i = 0; i < vals.length; i++) {
      if (!_isJobVisibleToCurrentUser(vals[i])) continue;
      var s = vals[i].status;
      if (s !== 'done' && s !== 'error' && s !== 'cancelled' && s !== 'retrying' && s !== 'history') return true;
    }
    return false;
  };

  /**
   * 计时器 — 更新所有可用的 gi-timer
   */
  PollManager.prototype._tickTimers = function () {
    var self = this;
    if (!this._hasActiveJobs()) return;
    if (self._timerRaf) return;
    self._timerRaf = requestAnimationFrame(function () {
      self._timerRaf = null;
      var els = document.querySelectorAll('.gi-timer');
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.closest && el.closest('.job-card.queued')) continue;
        var ts = parseFloat(el.dataset.ts);
        if (ts > 0) {
          var estimateLabel = el.dataset.estimateLabel || '';
          if (window.CW.formatJobElapsedWithEstimate) {
            el.textContent = window.CW.formatJobElapsedWithEstimate(ts, estimateLabel);
          } else {
            var sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
            var m = Math.floor(sec / 60);
            var s = sec % 60;
            el.textContent = m > 0 ? m + 'm' + String(s).padStart(2, '0') + 's' : s + 's';
          }
        }
      }
    });
  };

  // ── Expose ──
  if (!window.CW) window.CW = {};
  window.CW.PollManager = PollManager;

  // Auto-initialize after DOM ready
  function _initPollManager() {
    if (window.CW.pollManager) return;
    window.CW.pollManager = new PollManager();
    window.CW.onJobUpdate = function(job) {
      window.CW.pollManager.onJobUpdate(job);
    };
  }

  window.CW.initPollManager = _initPollManager;

})();
