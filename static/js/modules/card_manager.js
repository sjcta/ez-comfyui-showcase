/**
 * CardManager — 统一卡片渲染 + in-place DOM patch + 状态机。
 *
 * 职责：
 *   所有卡片渲染的唯一入口。合并旧的 _renderJobCard 和 _renderHistCard。
 *   状态变更 → debounce renderGallery() 全量重建
 *   progress 更新 → patchJobCard() in-place, 零闪烁
 *
 * 数据源：
 *   jobs {} — 通过 __APP__.jobs 桥接
 *   historyItems [] — 通过 __APP__.historyItems 桥接
 *
 * API 参见设计文档 §3.8
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs, historyItems = A.historyItems;

  // ── Internal state (moved from history.js) ──
  var _sentinelObs = null;
  var _histVisibleCount = 0;
  var _lastRenderedHistCount = 0;
  var _lastGalleryHash = '';
  var _filteredHistory = [];
  var _galleryFilters = { type: '', size: '', style: '', workflow: '' };
  var _renderTimer = null;
  var _cleanupTimer = null;

  /**
   * CardManager class
   * @param {Element} galleryEl - The gallery container element
   */
  function CardManager(galleryEl) {
    this.galleryEl = galleryEl;
  }

  /**
   * 统一渲染函数 — 合并 _renderJobCard + _renderHistCard
   * @param {Object} data - { id, status, image, prompt_preview, workflow, width, height, seed, progress, generating_at, queued_at, elapsed, time, instance, message }
   * @param {number} [histIdx] - index in filtered history, if history card
   * @returns {string} HTML string
   */
  CardManager.prototype.renderCard = function (data, histIdx) {
    if (data.status === 'history') {
      return this._renderHistCard(data, histIdx);
    }
    return this._renderJobCard(data);
  };

  /**
   * Render a job card (queued/preparing/generating/downloading/done/error)
   */
  CardManager.prototype._renderJobCard = function (j) {
    var label = j.prompt_preview || (j.workflow ? j.workflow.replace('.json', '') : '') || '...';
    var statusMsg = j.message || j.status;
    var hasImage = !!j.image;
    var imgSrc = hasImage ? API + '/api/images/' + j.image : '';

    // ── Image area ──
    var imgHtml = '';
    if (hasImage) {
      imgHtml = '<img src="' + imgSrc + '" loading="lazy" alt="">';
    } else {
      if (j.status === 'generating' || j.status === 'preparing' || j.status === 'starting_comfyui' || j.status === 'downloading') {
        imgHtml = '<div class="job-spinner"></div>';
      }
      if (j.status === 'queued') {
        imgHtml += '<div class="job-status-text queued">排队中</div>';
      } else if (j.status === 'generating') {
        imgHtml += '<div class="job-status-text generating">' + escH(statusMsg) + '</div>';
        if (j.generating_at) {
          imgHtml += '<div class="gi-timer-row"><span class="gi-timer" data-ts="' + j.generating_at + '">' + (window.CW.formatElapsed ? window.CW.formatElapsed(j.generating_at) : '') + '</span></div>';
        }
      } else if (j.status === 'downloading') {
        imgHtml += '<div class="job-status-text downloading">' + escH(statusMsg || '正在拉取图片...') + '</div>';
      } else {
        imgHtml += '<div class="job-status-text ' + escH(j.status) + '">' + escH(statusMsg) + '</div>';
      }
    }

    // ── Badge ──
    var wfMeta = (A._wfMeta || {})[j.workflow] || {};
    var wfLabel = wfMeta.name || (j.workflow ? j.workflow.replace('.json', '') : '');
    var wfTag = window.CW.getWFType ? window.CW.getWFType(j.workflow || '') : '';
    var tagHtml = wfTag ? ' <span class="' + wfTag.cls + '">' + wfTag.text + '</span>' : '';
    var instBadge = j.instance ? ' <span>#' + escH(j.instance) + '</span>' : '';

    // ── Type class for border color ──
    var _jMeta1 = (A._wfMeta || {})[j.workflow] || {};
    var _jTag1 = window.CW.getWFType ? window.CW.getWFType(j.workflow || '') : '';
    var _jMain1 = _jTag1 ? _jTag1.text : ((_jMeta1.tags || [])[0] || '');
    var _jCls1 = _jTag1 ? _jTag1.cls : (_jMain1 ? (_jMain1 === '放大' ? 'wf-tag-cat' : 'wf-tag-res') : '');
    var jTypeCls = _jCls1 ? 'gi-type-' + _jCls1.replace('wf-tag-', '') : '';

    return '<div class="gi job-card ' + escH(j.status) + ' ' + jTypeCls + '" data-job-id="' + escA(j.id) + '">' +
      '<div class="gi-img ' + (hasImage ? '' : 'job-placeholder') + '">' +
      imgHtml +
      (j.status === 'error' ? '<div class="gi-retry-row"><button class="btn-retry" onclick="event.stopPropagation();CW.retryJob(\'' + escA(j.id) + '\')">重新尝试</button></div>' : '') +
      '<button class="gi-del" onclick="event.stopPropagation();CW.cancelJob(\'' + escA(j.id) + '\')" title="' + (j.status === 'generating' ? '取消' : '删除') + '"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>' +
      (tagHtml || instBadge ? '<div class="gi-wf-badge">' + tagHtml + instBadge + '</div>' : '') +
      '</div>' +
      '<div class="gi-info" onclick="event.stopPropagation();CW.restoreJob(\'' + escA(j.id) + '\')">' +
      (j.status === 'generating' ? '<div class="gi-progress-top"><div class="gi-progress-fill" style="width:' + (j.progress ? j.progress.pct : 0) + '%"></div></div>' : '') +
      (wfLabel ? '<div class="gi-wf-label" title="' + escA(wfLabel) + '">' + escH(wfLabel) + '</div>' : '') +
      '<div class="gi-prompt" title="' + escA(j.prompt_preview || label) + '">' + escH(j.prompt_preview || label) + '</div>' +
      (j.status !== 'generating' ? '<div class="gi-meta">' +
        (j.queued_at ? '<span>' + (window.CW.icon ? CW.icon('clock') : '') + ' ' + j.queued_at + '</span>' : '') +
        '<div class="gi-meta-row">' +
        (j.elapsed ? '<span>' + (window.CW.icon ? CW.icon('timer') : '') + ' ' + Math.round(j.elapsed) + '秒</span>' : '') +
        (j.width && j.height ? '<span>' + (window.CW.icon ? CW.icon('ruler') : '') + ' ' + j.width + '×' + j.height + '</span>' : '') +
        '</div></div>' : '') +
      (j.seed ? '<div class="gi-seed">' + (window.CW.icon ? CW.icon('sprout') : '') + ' ' + j.seed + '</div>' : '') +
      '</div></div>';
  };

  /**
   * Render a history card
   */
  CardManager.prototype._renderHistCard = function (h, i) {
    var user = window.CW.auth && window.CW.auth.getCurrentUser ? window.CW.auth.getCurrentUser() : null;
    var canEdit = !!user;
    var imgSrc = h.thumb ? API + '/api/thumbs/' + h.thumb : API + '/api/images/' + h.filename;
    var wfTag = window.CW.getWFType ? window.CW.getWFType(h.workflow || '') : '';
    var meta1 = (A._wfMeta || {})[h.workflow] || {};
    var mainText1 = wfTag ? wfTag.text : ((meta1.tags || [])[0] || '');
    var mainCls1 = wfTag ? wfTag.cls : (mainText1 ? (mainText1 === '放大' ? 'wf-tag-cat' : 'wf-tag-res') : '');
    var tagBadge = mainText1 ? '<div class="gi-type-badge ' + mainCls1 + '">' + mainText1 + '</div>' : '';
    var typeCls1 = mainCls1 ? 'gi-type-' + mainCls1.replace('wf-tag-', '') : '';

    return '<div class="gi ' + typeCls1 + '" data-wf="' + escA(h.workflow || '') + '" data-hist-idx="' + i + '" onclick="CW.fillFormFromHistory(' + i + ')">' +
      '<div class="gi-img" onclick="event.stopPropagation();CW.openLB(' + i + ')">' +
      '<img src="' + imgSrc + '" loading="lazy" alt="">' +
      tagBadge +
      (canEdit ? '<button class="gi-del" onclick="event.stopPropagation();CW.delHist(\'' + h.id + '\')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>' : '') +
      (canEdit ? '<button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(' + i + ')" title="复刻出图">' + (window.CW.icon ? CW.icon('copy') : '') + ' 复刻</button>' : '') +
      '</div>' +
      '<div class="gi-info">' +
      '<div class="gi-prompt" title="' + escA(h.prompt || '') + '">' + escH(h.prompt || '—') + '</div>' +
      '<div class="gi-meta">' +
      '<span>' + (window.CW.icon ? CW.icon('clock') : '') + ' ' + _fmtTime(h.time) + '</span>' +
      '<div class="gi-meta-row">' +
      '<span>' + (window.CW.icon ? CW.icon('timer') : '') + ' ' + _fmtElapsed(h.elapsed) + '</span>' +
      '<span>' + (window.CW.icon ? CW.icon('ruler') : '') + ' ' + (h.width && h.height ? h.width + '×' + h.height : '—') + '</span>' +
      '</div></div>' +
      (h.seed ? '<div class="gi-seed">' + (window.CW.icon ? CW.icon('sprout') : '') + ' ' + h.seed + '</div>' : '') +
      '</div></div>';
  };

  // ── Format helpers ──
  function _fmtElapsed(sec) {
    if (!sec && sec !== 0) return '—';
    sec = Math.round(sec);
    if (sec < 60) return sec + '秒';
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + '分' + (s > 0 ? s + '秒' : '');
  }

  function _fmtTime(t) {
    if (!t) return '—';
    return t;
  }

  /**
   * In-place DOM patching — 更新进度条/状态文字/计时器, 零闪烁
   * @param {Object} job - 同 renderCard data 格式
   */
  CardManager.prototype.patchJobCard = function (job) {
    var card = document.querySelector('[data-job-id="' + job.id + '"]');
    if (!card) return;

    // ── Update CSS class ──
    var _tag2 = window.CW.wfTag ? window.CW.wfTag(job.workflow || '', ((A._wfMeta || {})[job.workflow] || {}).tags) : '';
    var _typeCls = _tag2 ? 'gi-type-' + _tag2.cls.replace('wf-tag-', '') : '';
    card.className = 'gi job-card ' + job.status + (_typeCls ? ' ' + _typeCls : '');

    // ── Status text ──
    var st = card.querySelector('.job-status-text');
    if (st) {
      var label = job.message || (job.status === 'generating' ? '出图中' : job.status === 'history' ? '' : job.status);
      st.textContent = label;
      st.className = 'job-status-text ' + job.status;
    }

    // ── Downloading state: hide progress bar ──
    if (job.status === 'downloading') {
      var bar = card.querySelector('.gi-progress-top');
      if (bar) bar.style.display = 'none';
    } else {
      var bar2 = card.querySelector('.gi-progress-top');
      if (bar2) bar2.style.display = '';
    }

    // ── Progress bar ──
    var bar3 = card.querySelector('.gi-progress-fill');
    if (bar3) bar3.style.width = (job.progress ? job.progress.pct : 0) + '%';

    // ── Timer ──
    if (job.generating_at) {
      var timerEl = card.querySelector('.gi-timer');
      if (timerEl) {
        timerEl.dataset.ts = job.generating_at;
        if (window.CW.formatElapsed) {
          timerEl.textContent = window.CW.formatElapsed(job.generating_at);
        }
      }
    }
  };

  /**
   * Handle job done: swap spinner to image, trigger auto-cleanup
   */
  CardManager.prototype.onJobDone = function (job) {
    if (!job.image) return;
    var card = document.querySelector('[data-job-id="' + job.id + '"]');
    if (card) {
      var imgDiv = card.querySelector('.gi-img');
      if (imgDiv) {
        imgDiv.className = 'gi-img';
        imgDiv.setAttribute('onclick', "event.stopPropagation();CW.openJobLB('" + escA(job.image) + "','" + escA(job.prompt_preview || '') + "')");
        imgDiv.innerHTML = '<img src="' + API + '/api/images/' + job.image + '" loading="lazy" alt="">';
        card.className = 'gi job-card done';
      }
    }
    // Remove from active jobs
    delete jobs[job.id];
    // Refresh history
    if (window.CW.loadHistory) window.CW.loadHistory();
  };

  /**
   * Handle job error: mark card as error, trigger auto-cleanup
   */
  CardManager.prototype.onJobError = function (job) {
    // 保留 error 卡片（60s 后由 _autoCleanup 清理）
    this.forceRender();
  };

  /**
   * 全量 render: active jobs + history（通过防抖）
   */
  CardManager.prototype.renderGallery = function () {
    if (_renderTimer) return;
    var self = this;
    _renderTimer = requestAnimationFrame(function () {
      _renderTimer = null;
      self._renderGalleryImpl();
    });
  };

  /**
   * 强制重建 — 清除 hash 缓存
   */
  CardManager.prototype.forceRender = function () {
    _lastGalleryHash = '';
    this.renderGallery();
  };

  /**
   * 内部渲染实现
   */
  CardManager.prototype._renderGalleryImpl = function () {
    var gallery = this.galleryEl || $('#gallery');
    if (!gallery) return;

    // ── Ensure initial batch ──
    if (_histVisibleCount === 0) {
      _histVisibleCount = Math.min(_batchSize(), (_filteredHistory.length ? _filteredHistory.length : historyItems.length));
    }

    // Active jobs (queued, preparing, starting_comfyui, generating, downloading)
    var activeJobs = Object.values(jobs).filter(function (j) { return j.status !== 'done' && j.status !== 'error'; });
    // Error jobs (kept briefly for visibility)
    var errorJobs = Object.values(jobs).filter(function (j) { return j.status === 'error'; });
    var jobCards = activeJobs.concat(errorJobs);

    // ── Hash check ──
    var hash = _galleryHash(jobs, historyItems);
    if (hash === _lastGalleryHash) return;
    _lastGalleryHash = hash;

    // Update count badge
    var histCountEl = $('#histCount');
    if (histCountEl) histCountEl.textContent = '(' + (activeJobs.length + historyItems.length) + ')';

    var html = '';

    // ── Render job cards ──
    for (var ci = 0; ci < jobCards.length; ci++) {
      html += this._renderJobCard(jobCards[ci]);
    }

    // ── History items (lazy loaded) ──
    var filteredArr = _filteredHistory.length ? _filteredHistory : historyItems;
    // Update lbItems for lightbox (used by history.js)
    if (window.__APP__) window.__APP__._lbItems = filteredArr;
    var visibleItems = filteredArr.slice(0, _histVisibleCount);
    for (var hi = 0; hi < visibleItems.length; hi++) {
      html += this._renderHistCard(visibleItems[hi], hi);
    }

    if (historyItems.length > _histVisibleCount) {
      html += '<div class="masonry-sentinel" id="masonrySentinel"></div>';
    }

    if (jobCards.length === 0 && historyItems.length === 0) {
      html = '<div class="empty-hint"><div class="eh-icon">' + (window.CW.icon ? CW.icon('image', 32) : '') + '</div><p>暂无历史</p><p class="hint-sub">出图后自动出现在这里</p></div>';
    }

    try {
      gallery.innerHTML = html;
    } catch (e) {
      console.error('[GALLERY ERROR]', e);
      var ediv = document.getElementById('gallery');
      if (ediv) ediv.innerHTML = '<div style=color:red;padding:20px>Render error: ' + e.message + '</div>';
    }

    _lastRenderedHistCount = visibleItems.length;
    _attachSentinel();
    _scheduleCleanup();
  };

  /**
   * Hash: structural changes only (job added/removed/status transition, history length change)
   */
  function _galleryHash(jobsObj, histArr) {
    var s = '';
    for (var key in jobsObj) {
      if (jobsObj.hasOwnProperty(key)) {
        var j = jobsObj[key];
        s += j.id + j.status + '|';
      }
    }
    return s + '::' + histArr.length;
  }

  function _batchSize() {
    return _getColumnCount() * 2;
  }

  function _getColumnCount() {
    var gallery = $('#gallery');
    if (!gallery) return 3;
    var w = gallery.clientWidth;
    var gap = 10;
    var minCol = 140;
    return Math.max(1, Math.floor((w + gap) / (minCol + gap)));
  }

  function _attachSentinel() {
    var sentinel = document.getElementById('masonrySentinel');
    if (!sentinel) return;
    if (_sentinelObs) _sentinelObs.disconnect();
    _sentinelObs = new IntersectionObserver(
      function (entries) {
        if (entries[0].isIntersecting && _histVisibleCount < historyItems.length) {
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), historyItems.length);
          _appendNewHistoryCards();
        }
      },
      { root: null, rootMargin: '300px', threshold: 0 }
    );
    _sentinelObs.observe(sentinel);
  }

  function _appendNewHistoryCards() {
    var gallery = $('#gallery');
    if (!gallery) return;
    var sentinel = gallery.querySelector('.masonry-sentinel');
    var prevCount = _lastRenderedHistCount;
    var filteredArr2 = _filteredHistory.length ? _filteredHistory : historyItems;
    var newCount = Math.min(_histVisibleCount, filteredArr2.length);
    if (newCount <= prevCount) {
      if (sentinel) _attachSentinel();
      return;
    }

    var fragment = '';
    for (var i = prevCount; i < newCount; i++) {
      fragment += _histCardHTML(historyItems[i], i);
    }

    if (sentinel) sentinel.insertAdjacentHTML('beforebegin', fragment);
    else gallery.insertAdjacentHTML('beforeend', fragment);

    _lastRenderedHistCount = newCount;

    if (newCount >= historyItems.length && sentinel) {
      sentinel.remove();
      if (_sentinelObs) _sentinelObs.disconnect();
      return;
    }

    if (sentinel && _histVisibleCount < filteredArr2.length) {
      requestAnimationFrame(function () {
        var rect = sentinel.getBoundingClientRect();
        if (rect.top < window.innerHeight + 200) {
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), historyItems.length);
          _appendNewHistoryCards();
        } else {
          _attachSentinel();
        }
      });
    }
  }

  function _histCardHTML(h, i) {
    var imgSrc = h.thumb ? API + '/api/thumbs/' + h.thumb : API + '/api/images/' + h.filename;
    var wfTag = window.CW.getWFType ? window.CW.getWFType(h.workflow || '') : '';
    var meta2 = (A._wfMeta || {})[h.workflow] || {};
    var mainText2 = wfTag ? wfTag.text : ((meta2.tags || [])[0] || '');
    var mainCls2 = wfTag ? wfTag.cls : (mainText2 ? (mainText2 === '放大' ? 'wf-tag-cat' : 'wf-tag-res') : '');
    var tagBadge = mainText2 ? '<div class="gi-type-badge ' + mainCls2 + '">' + mainText2 + '</div>' : '';
    var typeCls2 = mainCls2 ? 'gi-type-' + mainCls2.replace('wf-tag-', '') : '';
    return '<div class="gi ' + typeCls2 + '" data-wf="' + escA(h.workflow || '') + '" data-hist-idx="' + i + '" onclick="CW.fillFormFromHistory(' + i + ')">' +
      '<div class="gi-img lazy-img" onclick="event.stopPropagation();CW.openLB(' + i + ')">' +
      '<img src="' + imgSrc + '" loading="lazy" alt="">' +
      tagBadge +
      (canEdit ? '<button class="gi-del" onclick="event.stopPropagation();CW.delHist(\'' + h.id + '\')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>' : '') +
      (canEdit ? '<button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(' + i + ')" title="复刻出图">' + (window.CW.icon ? CW.icon('copy') : '') + ' 复刻</button>' : '') +
      '</div>' +
      '<div class="gi-info">' +
      '<div class="gi-prompt" title="' + escA(h.prompt || '') + '">' + escH(h.prompt || '—') + '</div>' +
      '<div class="gi-meta">' +
      '<span>' + (window.CW.icon ? CW.icon('clock') : '') + ' ' + _fmtTime(h.time) + '</span>' +
      '<div class="gi-meta-row">' +
      '<span>' + (window.CW.icon ? CW.icon('timer') : '') + ' ' + _fmtElapsed(h.elapsed) + '</span>' +
      '<span>' + (window.CW.icon ? CW.icon('ruler') : '') + ' ' + (h.width && h.height ? h.width + '×' + h.height : '—') + '</span>' +
      '</div></div>' +
      (h.seed ? '<div class="gi-seed">' + (window.CW.icon ? CW.icon('sprout') : '') + ' ' + h.seed + '</div>' : '') +
      '</div></div>';
  }

  /**
   * 自动清理 — done 保留 5s, error 保留 60s 后自动移入历史
   */
  function _scheduleCleanup() {
    var self = this;
    if (_cleanupTimer) clearTimeout(_cleanupTimer);
    _cleanupTimer = setTimeout(function () {
      _cleanupTimer = null;
      self._autoCleanup();
    }, 6000);
  }

  CardManager.prototype._autoCleanup = function (keepDone, keepError) {
    keepDone = keepDone || 5000;
    keepError = keepError || 60000;
    var now = Date.now();
    var changed = false;
    var keys = Object.keys(jobs);

    for (var ki = 0; ki < keys.length; ki++) {
      var id = keys[ki];
      var job = jobs[id];
      if (!job) continue;

      // Done: remove from active jobs after keepDone ms
      if (job.status === 'done' && job._doneAt && (now - job._doneAt > keepDone)) {
        delete jobs[id];
        changed = true;
      }

      // Error: remove from active jobs after keepError ms
      if (job.status === 'error' && job._errAt && (now - job._errAt > keepError)) {
        delete jobs[id];
        changed = true;
      }
    }

    if (changed) {
      _lastGalleryHash = '';
      if (window.CW.renderGallery) window.CW.renderGallery();
    }
  };

  // ── Filter helpers (moved from history.js) ──
  CardManager.prototype.populateFilterOptions = function () {
    var wfs = new Set();
    var styles = new Set();
    var typeOpts = new Set();
    for (var k = 0; k < historyItems.length; k++) {
      var j = historyItems[k];
      if (j && j.workflow) wfs.add(j.workflow.replace('.json', ''));
      var _tag = window.CW.wfTag ? window.CW.wfTag(j.workflow || '', ((A._wfMeta || {})[j.workflow || ''] || {}).tags) : '';
      if (_tag && _tag.text) typeOpts.add(_tag.text);
      try {
        var pObj = JSON.parse(j.prompt || '{}');
        if (pObj.style && typeof pObj.style === 'string') {
          var s = pObj.style.trim();
          if (s.length > 0) styles.add(s);
        }
      } catch (e) {}
    }
    var typeSel = document.getElementById('gfType');
    if (typeSel) {
      var curType = typeSel.value;
      var sortedTypes = Array.from(typeOpts).sort();
      var ht = '<option value="">全部类型</option>';
      for (var ti = 0; ti < sortedTypes.length; ti++) {
        ht += '<option value="' + sortedTypes[ti] + '">' + sortedTypes[ti] + '</option>';
      }
      typeSel.innerHTML = ht;
      if (curType && typeOpts.has(curType)) typeSel.value = curType;
    }
    var sizeSel = document.getElementById('gfSize');
    if (sizeSel) {
      sizeSel.innerHTML = '<option value="">全部尺寸</option>' +
        '<option value="1K">1K (≤1024)</option>' +
        '<option value="2K">2K (≤2048)</option>' +
        '<option value="4K">4K (≤3840)</option>' +
        '<option value="4K+">4K+ (>3840)</option>';
    }
    var wfSel = document.getElementById('gfWF');
    if (wfSel) {
      var cur2 = wfSel.value;
      var arr2 = Array.from(wfs).sort();
      var h2 = '<option value="">全部工作流</option>';
      for (var m = 0; m < arr2.length; m++) {
        h2 += '<option value="' + arr2[m] + '">' + arr2[m] + '</option>';
      }
      wfSel.innerHTML = h2;
      if (cur2 && wfs.has(cur2)) wfSel.value = cur2;
    }
    var styleInput = document.getElementById('gfStyle');
    if (styleInput && styles.size > 0) {
      var dlId = 'styleDatalist';
      var dl = document.getElementById(dlId);
      if (!dl) {
        dl = document.createElement('datalist');
        dl.id = dlId;
        document.body.appendChild(dl);
        styleInput.setAttribute('list', dlId);
      }
      var sorted = Array.from(styles).sort();
      dl.innerHTML = sorted.map(function (s) { return '<option value="' + escH(s) + '">'; }).join('');
    }
  };

  CardManager.prototype.filterHistory = function (arr) {
    return arr.filter(function (j) {
      if (_galleryFilters.type) {
        var t = window.CW.wfTag ? window.CW.wfTag(j.workflow || '', ((A._wfMeta || {})[j.workflow || ''] || {}).tags) : '';
        if (!t || t.text !== _galleryFilters.type) return false;
      }
      if (_galleryFilters.size) {
        var maxDim = Math.max(j.width || 0, j.height || 0);
        var sizeLevel = '';
        if (maxDim <= 1024) sizeLevel = '1K';
        else if (maxDim <= 2048) sizeLevel = '2K';
        else if (maxDim <= 3840) sizeLevel = '4K';
        else sizeLevel = '4K+';
        if (sizeLevel !== _galleryFilters.size) return false;
      }
      if (_galleryFilters.style) {
        var searchText = '';
        searchText += (j.prompt_preview || '').toLowerCase() + ' ';
        try {
          var pObj = JSON.parse(j.prompt || '{}');
          (function _extractText(obj) {
            var t = '';
            if (typeof obj === 'string') return obj + ' ';
            if (typeof obj === 'object' && obj !== null) {
              for (var key in obj) { t += _extractText(obj[key]); }
            }
            return t;
          })(pObj);
          searchText += _extractText(pObj).toLowerCase();
        } catch (e) {
          searchText += (j.prompt || '').toLowerCase();
        }
        if (searchText.indexOf(_galleryFilters.style) === -1) return false;
      }
      if (_galleryFilters.workflow) {
        if ((j.workflow || '').replace('.json', '') !== _galleryFilters.workflow) return false;
      }
      return true;
    });
  };

  CardManager.prototype.applyFilters = function () {
    var el;
    el = document.getElementById('gfType');
    _galleryFilters.type = el ? el.value : '';
    el = document.getElementById('gfSize');
    _galleryFilters.size = el ? el.value : '';
    el = document.getElementById('gfStyle');
    _galleryFilters.style = el ? el.value.toLowerCase() : '';
    el = document.getElementById('gfWF');
    _galleryFilters.workflow = el ? el.value : '';
    _filteredHistory = this.filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = '';
    this.renderGallery();
  };

  CardManager.prototype.clearFilters = function () {
    _galleryFilters = { type: '', size: '', style: '', workflow: '' };
    var el;
    el = document.getElementById('gfType');
    if (el) el.value = '';
    el = document.getElementById('gfSize');
    if (el) el.value = '';
    el = document.getElementById('gfStyle');
    if (el) el.value = '';
    el = document.getElementById('gfWF');
    if (el) el.value = '';
    _filteredHistory = this.filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = '';
    this.renderGallery();
  };

  // ── Expose class + instance ──
  if (!window.CW) window.CW = {};
  window.CW.CardManager = CardManager;

  // Auto-initialize once the gallery element exists
  function _initCardManager() {
    if (window.CW.cardManager) return;
    var gallery = $('#gallery');
    if (gallery) {
      window.CW.cardManager = new CardManager(gallery);
    }
  }

  window.CW.initCardManager = _initCardManager;

})();
