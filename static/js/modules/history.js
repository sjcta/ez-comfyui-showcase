/**
 * History Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs, historyItems = A.historyItems;
  var _sentinelObs = null;
  var _histVisibleCount = 0;
  var _lastRenderedHistCount = 0;
  var _lastGalleryHash = '';
  var _filteredHistory = [];
  var lbIdx = -1;
  var lbItems = [];
  var _galleryFilters = { owner: 'all', type: '', size: '', style: '' };
  var _renderTimer = null;
  var _lbLoadToken = 0;
  var _lbCurrentItem = null;
  var _lbFavorites = {};

  function _lightboxImageUrl(filename) {
    return `${API}/api/images/${filename}`;
  }

  function _lightboxDownloadName(filename) {
    if (!filename) return 'image.png';
    var parts = String(filename).split('/');
    return parts[parts.length - 1] || 'image.png';
  }

  function _syncLightboxDownload(filename) {
    var link = $('#lbDownload');
    if (!link) return;
    var url = _lightboxImageUrl(filename || '');
    var downloadName = _lightboxDownloadName(filename || '');
    link.href = url;
    link.setAttribute('download', downloadName);
    link.dataset.url = url;
    link.dataset.filename = downloadName;
  }

  function _syncLightboxActions(item) {
    _lbCurrentItem = item || null;
    var favBtn = $('#lbFavoriteBtn');
    var shareBtn = $('#lbShareBtn');
    var canShare = !!(item && item.id);
    var favKey = item && (item.id || item.filename || item.original || item.prompt);
    var isFav = !!(favKey && _lbFavorites[favKey]);
    if (favBtn) {
      favBtn.classList.toggle('is-active', isFav);
      favBtn.disabled = !item;
      favBtn.classList.toggle('is-disabled', !item);
      favBtn.title = isFav ? '取消收藏' : '收藏';
    }
    if (shareBtn) {
      shareBtn.classList.toggle('is-shared', !!(item && item.is_public));
      shareBtn.disabled = !canShare;
      shareBtn.classList.toggle('is-disabled', !canShare);
      shareBtn.title = item && item.is_public ? '取消分享' : '快速分享';
    }
  }
function _attachSentinel() {
    const sentinel = document.getElementById('masonrySentinel');
    if (!sentinel) return;
    if (_sentinelObs) _sentinelObs.disconnect();
    _sentinelObs = new IntersectionObserver(
      (entries) => {
        var activeItems = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
        if (entries[0].isIntersecting && _histVisibleCount < activeItems.length) {
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), activeItems.length);
          _appendNewHistoryCards();
        }
      },
      { root: null, rootMargin: '300px', threshold: 0 },
    );
    _sentinelObs.observe(sentinel);
  }

  _sentinelObs = null;
  // ═══ Unified card rendering ═══
  function _renderJobCard(j) {
    const label = j.prompt_preview || j.workflow?.replace('.json', '') || '...';
    const statusMsg = j.message || j.status;
    const hasImage = !!j.image;
    const imgSrc = hasImage ? `${API}/api/images/${j.image}` : '';

    // ── Image area ──
    let imgHtml = '';
    if (hasImage) {
      imgHtml = `<img src="${imgSrc}" loading="lazy" alt="">`;
    } else {
      if (j.status === 'generating' || j.status === 'preparing' || j.status === 'downloading') {
        imgHtml = `<div class="job-spinner"></div>`;
      }
      // Status text ABOVE timer (always shown for non-image states)
      if (j.status === 'queued') {
        imgHtml += `<div class="job-status-text queued">排队中</div>`;
      } else if (j.status === 'generating') {
        imgHtml += `<div class="job-status-text generating">${escH(statusMsg)}</div>`;
        if (j.generating_at) {
          imgHtml += `<div class="gi-timer-row"><span class="gi-timer" data-ts="${j.generating_at}">${window.CW.formatElapsed(j.generating_at)}</span></div>`;
        }
      } else if (j.status === 'downloading') {
        imgHtml += `<div class="job-status-text downloading">${escH(statusMsg || '正在拉取图片...')}</div>`;
      } else {
        imgHtml += `<div class="job-status-text ${escH(j.status)}">${escH(statusMsg)}</div>`;
      }
    }

    // ── Badge ──
    const wfMeta = A._wfMeta[j.workflow] || {};
    const wfLabel = wfMeta.name || (j.workflow || '').replace('.json', '');
    const wfTag = window.CW.getWFType(j.workflow || '');
    const tagHtml = wfTag ? `<div class="gi-type-badge ${wfTag.cls}">${wfTag.text}</div>` : '';
    const instBadge = j.instance ? `<div class="gi-inst-badge">#${escH(j.instance)}</div>` : '';

    // ── Info area ──
    // Type class for border color
    const _jMeta1 = A._wfMeta[j.workflow] || {};
    const _jTag1 = window.CW.getWFType(j.workflow || '');
    const _jMain1 = _jTag1 ? _jTag1.text : ((_jMeta1.tags || [])[0] || '');
    const _jCls1 = _jTag1 ? _jTag1.cls : (_jMain1 ? (_jMain1 === '放大' ? 'wf-tag-cat' : 'wf-tag-res') : '');
    const jTypeCls = _jCls1 ? 'gi-type-' + _jCls1.replace('wf-tag-', '') : '';
    return `<div class="gi job-card ${escH(j.status)} ${jTypeCls}" data-job-id="${escA(j.id)}">
      <div class="gi-img ${hasImage ? '' : 'job-placeholder'}">
        ${imgHtml}
        ${j.status === "error" ? `<div class="gi-retry-row"><button class="btn-retry" onclick="event.stopPropagation();CW.retryJob('${escA(j.id)}')">重新尝试</button></div>` : ""}
        <button class="gi-del" onclick="event.stopPropagation();CW.cancelJob('${escA(j.id)}')" title="${j.status === 'generating' ? '取消' : '删除'}"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>
        ${tagHtml || instBadge ? `<div class="gi-tags-row">${tagHtml}${instBadge}</div>` : ''}
      </div>
      <div class="gi-info" onclick="event.stopPropagation();CW.restoreJob('${escA(j.id)}')">
        ${j.status === 'generating' ? `<div class="gi-progress-top"><div class="gi-progress-fill" style="width:${j.progress?.pct || 0}%"></div></div>` : ''}
        ${wfLabel ? `<div class="gi-wf-label" title="${escA(wfLabel)}">${escH(wfLabel)}</div>` : ''}
        <div class="gi-prompt" title="${escA(j.prompt_preview || label)}">${escH(j.prompt_preview || label)}</div>
        ${j.status !== 'generating' ? `<div class="gi-meta">
          ${j.queued_at ? `<span>${CW.icon("clock")} ${j.queued_at}</span>` : ''}
          <div class="gi-meta-row">
            ${j.width && j.height ? `<span>${CW.icon("ruler")} ${j.width}×${j.height}</span>` : ''}
          </div>
        </div>` : ''}
        ${j.seed ? `<div class="gi-seed">${CW.icon("sprout")} ${j.seed}</div>` : ''}
      </div>
    </div>`;
  }

  // ═══ In-place DOM patching (no full rebuild) ═══
  function _patchJobCard(job) {
    const card = document.querySelector(`[data-job-id="${job.id}"]`);
    if (!card) return;
    // CSS class
    var _tag2 = window.CW.wfTag(job.workflow || '', (A._wfMeta[job.workflow] || {}).tags);
    var _typeCls = _tag2 ? 'gi-type-' + _tag2.cls.replace('wf-tag-', '') : '';
    card.className = `gi job-card ${job.status}` + (_typeCls ? ' ' + _typeCls : '');
    // Status text — update in image area
    const st = card.querySelector('.job-status-text');
    if (st) {
      const label = job.message || (job.status === 'generating' ? '出图中' : job.status);
      st.textContent = label;
      st.className = `job-status-text ${job.status}`;
    }
    // For downloading state, show specific message without progress bar
    if (job.status === 'downloading') {
      const bar = card.querySelector('.gi-progress-top');
      if (bar) bar.style.display = 'none';
    } else {
      const bar = card.querySelector('.gi-progress-top');
      if (bar) bar.style.display = '';
    }
    // Progress bar
    const bar = card.querySelector('.gi-progress-fill');
    if (bar) bar.style.width = (job.progress?.pct || 0) + '%';
    // Timer
    if (job.generating_at) {
      const timerEl = card.querySelector('.gi-timer');
      if (timerEl) {
        timerEl.dataset.ts = job.generating_at;
        timerEl.textContent = window.CW.formatElapsed(job.generating_at);
      }
    }
  }

  function _onJobDone(job) {
    if (!job.image) return; // Wait for image to arrive
    // Immediate visual: swap spinner → image
    const card = document.querySelector(`[data-job-id="${job.id}"]`);
    if (card) {
      const imgDiv = card.querySelector('.gi-img');
      if (imgDiv) {
        imgDiv.className = 'gi-img';
        imgDiv.setAttribute('onclick', `event.stopPropagation();CW.openJobLB('${escA(job.image)}','${escA(job.prompt_preview || '')}')`);
        imgDiv.innerHTML = `<img src="${API}/api/images/${job.image}" loading="lazy" alt="">`;
        card.className = 'gi job-card done';
      }
    }
    // Remove from active jobs
    delete jobs[job.id];
    // Refresh history to show completed image card
    window.CW.loadHistory();
  }

  function _onJobError(job) {
    // Remove from active jobs
    delete jobs[job.id];
    // Re-render to show error state
    window.CW.forceGalleryRerender();
  }

    
  // ── Format helpers for meta display ──
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
    // t = "2026-05-06 22:18:47"
    return t;
  }

function _renderHistCard(h, i) {
    const canDelete = _canDeleteHistoryItem(h);
    const imgSrc = h.thumb ? `${API}/api/thumbs/${h.thumb}` : `${API}/api/images/${h.filename}`;
    const mainText1 = _historyItemType(h);
    const mainCls1 = _typeClass(mainText1, h.workflow);
    const tagBadge = mainText1 ? `<div class="gi-type-badge ${mainCls1}">${mainText1}</div>` : '';
    const typeCls1 = mainCls1 ? 'gi-type-' + mainCls1.replace('wf-tag-', '') : '';

    return `<div class="gi ${typeCls1}" data-wf="${escA(h.workflow || '')}" data-hist-idx="${i}" onclick="CW.fillFormFromHistory(${i})">
      <div class="gi-img" onclick="event.stopPropagation();CW.openLB(${i})">
        <img src="${imgSrc}" loading="lazy" alt="">
        ${tagBadge}
        ${canDelete ? `<button class="gi-del" onclick="event.stopPropagation();CW.delHist('${h.id}')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>` : ''}
        <button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(${i})" title="复刻出图">${CW.icon("copy")} 复刻</button>
      </div>
      <div class="gi-info">
        <div class="gi-prompt" title="${escA(h.prompt || '')}">${escH(h.prompt || '—')}</div>
        <div class="gi-meta">
          <span>${CW.icon("clock")} ${_fmtTime(h.time)}</span>
          <div class="gi-meta-row">
            <span>${CW.icon("timer")} ${_fmtElapsed(h.elapsed)}</span>
            <span>${CW.icon("ruler")} ${h.width && h.height ? h.width + '×' + h.height : '—'}</span>
          </div>
        </div>
        ${h.seed ? `<div class="gi-seed">${CW.icon("sprout")} ${h.seed}</div>` : ''}
      </div>
    </div>`;
  }

function _isAdminHistoryView() {
    var user = window.CW && window.CW.auth && window.CW.auth.getCurrentUser
      ? window.CW.auth.getCurrentUser()
      : null;
    return !!(user && user.role === 'admin');
  }

function _canDeleteHistoryItem(h) {
    var user = window.CW && window.CW.auth && window.CW.auth.getCurrentUser
      ? window.CW.auth.getCurrentUser()
      : null;
    if (user && user.role === 'admin') return true;
    var uid = user && (user.sub || user.id);
    var owner = h && h.user_id;
    return !!(uid && owner && String(uid) === String(owner));
  }

function _currentUserId() {
    var user = window.CW && window.CW.auth && window.CW.auth.getCurrentUser
      ? window.CW.auth.getCurrentUser()
      : null;
    return user && (user.sub || user.id) ? String(user.sub || user.id) : '';
  }

function _typeClass(typeText, workflowName) {
    var fallback = window.CW && CW.getWFType ? CW.getWFType(workflowName || '') : null;
    if (fallback && fallback.text === typeText) return fallback.cls;
    if (typeText === '文生图') return 'wf-tag-t2i';
    if (typeText === '图生图') return 'wf-tag-i2i';
    if (typeText === '文生视频') return 'wf-tag-t2v';
    if (typeText === '图生视频') return 'wf-tag-i2v';
    if (typeText === '放大') return 'wf-tag-cat';
    return typeText ? 'wf-tag-res' : '';
  }

function _historyItemType(item) {
    if (item && item.workflow_type) return item.workflow_type;
    var workflow = item && item.workflow ? item.workflow : '';
    var meta = (A._wfMeta || {})[workflow] || {};
    var tag = window.CW && CW.wfTag ? CW.wfTag(workflow, meta.tags) : null;
    return tag && tag.text ? tag.text : '';
  }

function _syncOwnerFilterButtons() {
    var val = _galleryFilters.owner || 'all';
    var buttons = document.querySelectorAll('[data-owner-filter]');
    buttons.forEach(function(btn) {
      var active = btn.getAttribute('data-owner-filter') === val;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

function setHistoryOwnerFilter(value) {
    _galleryFilters.owner = value || 'all';
    _syncOwnerFilterButtons();
    applyFilters();
  }

function _syncTypeFilterButtons() {
    _renderTypeFilterButtons();
    var val = _galleryFilters.type || '';
    var buttons = document.querySelectorAll('[data-type-filter]');
    buttons.forEach(function(btn) {
      var active = btn.getAttribute('data-type-filter') === val;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

function _historyTypeOptions() {
    var fromHistory = new Set();
    historyItems.forEach(function(item) {
      var type = _historyItemType(item);
      if (type) fromHistory.add(type);
    });
    if (fromHistory.size > 0) {
      return _sortTypeOptions(Array.from(fromHistory));
    }
    var set = new Set();
    Object.keys(A._wfMeta || {}).forEach(function(fname) {
      var meta = A._wfMeta[fname] || {};
      var tags = meta.tags || [];
      var typeTag = window.CW && CW.getWFType ? CW.getWFType(fname) : null;
      var mainTag = typeTag ? typeTag.text : (tags[0] || '');
      if (mainTag) set.add(mainTag);
    });
    return _sortTypeOptions(Array.from(set));
  }

function _sortTypeOptions(items) {
    var priority = ['文生图', '图生图', '放大', '文生视频', '图生视频', '其他'];
    return items.sort(function(a, b) {
      var ai = priority.indexOf(a), bi = priority.indexOf(b);
      if (ai >= 0 && bi >= 0) return ai - bi;
      if (ai >= 0) return -1;
      if (bi >= 0) return 1;
      return a.localeCompare(b, 'zh');
    });
  }

function _renderTypeFilterButtons() {
    var wrap = document.querySelector('.gf-type-segment');
    if (!wrap) return;
    var options = _historyTypeOptions();
    if (_galleryFilters.type && options.indexOf(_galleryFilters.type) < 0) {
      _galleryFilters.type = '';
    }
    var html = '<button class="gf-segment-btn" type="button" data-type-filter="" onclick="CW.setHistoryTypeFilter(this.dataset.typeFilter)">全部类型</button>';
    options.forEach(function(t) {
      html += '<button class="gf-segment-btn" type="button" data-type-filter="' + escA(t) + '" onclick="CW.setHistoryTypeFilter(this.dataset.typeFilter)">' + escH(t) + '</button>';
    });
    wrap.innerHTML = html;
  }

function setHistoryTypeFilter(value) {
    _galleryFilters.type = value || '';
    _syncTypeFilterButtons();
    applyFilters();
  }

  function _hasActiveGalleryFilters() {
    return (_galleryFilters.owner && _galleryFilters.owner !== 'all') ||
      !!_galleryFilters.type ||
      !!_galleryFilters.size ||
      !!_galleryFilters.style;
  }

  function _jobSortPriority(status) {
    if (status === 'queued') return 0;
    if (status === 'preparing' || status === 'starting_comfyui') return 1;
    if (status === 'generating' || status === 'downloading') return 2;
    if (status === 'error') return 3;
    return 4;
  }

  function _jobSortTimestamp(job) {
    if (!job) return 0;
    var raw = job.queued_at || job.generating_at || job.created_at || job.submitted_at || job.time || '';
    if (!raw) return 0;
    if (typeof raw === 'number') return raw;
    var parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) return parsed;
    if (typeof raw === 'string') {
      var timeMatch = raw.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
      if (timeMatch) {
        return (parseInt(timeMatch[1], 10) * 3600) +
          (parseInt(timeMatch[2], 10) * 60) +
          parseInt(timeMatch[3] || '0', 10);
      }
    }
    return 0;
  }

  function _sortJobCards(items) {
    return items.slice().sort(function(a, b) {
      var prioDiff = _jobSortPriority(a.status) - _jobSortPriority(b.status);
      if (prioDiff !== 0) return prioDiff;
      var tsDiff = _jobSortTimestamp(b) - _jobSortTimestamp(a);
      if (tsDiff !== 0) return tsDiff;
      return String(b.id || '').localeCompare(String(a.id || ''));
    });
  }

function _renderGalleryImpl() { console.log("[DEBUG] hist=" + historyItems.length + " filtered=" + _filteredHistory.length + " count=" + _histVisibleCount + " batch=" + _batchSize());
    const gallery = $('#gallery');

    // Ensure we have an initial batch size on first render
    _ensureInitialBatch();

    // Active jobs (queued, preparing, starting_comfyui, generating)
    const activeJobs = Object.values(jobs).filter((j) => j.status !== 'done' && j.status !== 'error');
    // Error jobs (kept briefly for visibility)
    const errorJobs = Object.values(jobs).filter((j) => j.status === 'error');

    const jobCards = _sortJobCards([...activeJobs, ...errorJobs]);

    // ── Hash check: skip rebuild if nothing changed ──
    const hash = _galleryHash(jobs, historyItems);
    if (hash === _lastGalleryHash) return;
    _lastGalleryHash = hash;

    // Count: active jobs + history
    $('#histCount').textContent = String(activeJobs.length + historyItems.length);

    var html = '';

    // ── Render all cards via unified functions ──
    for (const j of jobCards) {
      html += _renderJobCard(j);
    }

    // ── History items (lazy loaded) ──
    const filteredArr = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
    lbItems = filteredArr;
    if (_isAdminHistoryView()) _histVisibleCount = filteredArr.length;
    const visibleItems = filteredArr.slice(0, _histVisibleCount);
    for (let i = 0; i < visibleItems.length; i++) {
      html += _renderHistCard(visibleItems[i], i);
    }

    if (filteredArr.length > _histVisibleCount) {
      html += `<div class="masonry-sentinel" id="masonrySentinel"></div>`;
    }

    if (!jobCards.length && !filteredArr.length) {
      html = `<div class="empty-hint"><div class="eh-icon">${CW.icon("image", 32)}</div><p>暂无历史</p><p class="hint-sub">出图后自动出现在这里</p></div>`;
    }

    try { gallery.innerHTML = html; } catch(e) { console.error("[GALLERY ERROR]", e); var ediv = document.getElementById("gallery"); if(ediv) ediv.innerHTML = "<div style=color:red;padding:20px>Render error: " + e.message + "</div>"; }

    _lastRenderedHistCount = visibleItems.length;
    _lastGalleryHash = '';  // force next renderGallery to rebuild
    lbItems = filteredArr;
    _attachSentinel();
  }
function _galleryHash(jobsObj, histArr) {
    // Only structural changes trigger full rebuild: job added/removed, status transitions, history items added/removed
    var s = '';
    for (const j of Object.values(jobsObj)) {
      s += j.id + j.status + '|';
    }
    return s + '::' + histArr.length;
  }
function _appendNewHistoryCards() {
    const gallery = $('#gallery');
    if (!gallery) return;
    const sentinel = gallery.querySelector('.masonry-sentinel');
    const prevCount = _lastRenderedHistCount;
    const filteredArr2 = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
    const newCount = Math.min(_histVisibleCount, filteredArr2.length);
    if (newCount <= prevCount) {
      if (sentinel) _attachSentinel();
      return;
    }

    var fragment = '';
    for (let i = prevCount; i < newCount; i++) {
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

    // Re-check: if sentinel is still visible after appending, load more immediately
    if (sentinel && _histVisibleCount < filteredArr2.length) {
      requestAnimationFrame(() => {
        const rect = sentinel.getBoundingClientRect();
        if (rect.top < window.innerHeight + 200) {
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), filteredArr2.length);
          _appendNewHistoryCards();
        } else {
          _attachSentinel();
        }
      });
    }
  }
function _histCardHTML(h, i) {
    const user = window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser();
    const canEdit = !!user;
    const canDelete = _canDeleteHistoryItem(h);
    const imgSrc = h.thumb ? `${API}/api/thumbs/${h.thumb}` : `${API}/api/images/${h.filename}`;
    const mainText2 = _historyItemType(h);
    const mainCls2 = _typeClass(mainText2, h.workflow);
    const tagBadge = mainText2 ? `<div class="gi-type-badge ${mainCls2}">${mainText2}</div>` : '';
    const typeCls2 = mainCls2 ? 'gi-type-' + mainCls2.replace('wf-tag-', '') : '';
    return `<div class="gi ${typeCls2}" data-wf="${escA(h.workflow || '')}" data-hist-idx="${i}" onclick="CW.fillFormFromHistory(${i})">
    <div class="gi-img lazy-img" onclick="event.stopPropagation();CW.openLB(${i})">
      <img src="${imgSrc}" loading="lazy" alt="">
      ${tagBadge}
      ${canDelete ? `<button class="gi-del" onclick="event.stopPropagation();CW.delHist('${h.id}')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>` : ''}
      ${canEdit ? `<button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(${i})" title="复刻出图">${CW.icon("copy")} 复刻</button>` : ''}
    </div>
    <div class="gi-info">
      <div class="gi-prompt" title="${escA(h.prompt || '')}">${escH(h.prompt || '—')}</div>
      <div class="gi-meta">
        <span>${CW.icon("clock")} ${_fmtTime(h.time)}</span>
        <div class="gi-meta-row">
          <span>${CW.icon("timer")} ${_fmtElapsed(h.elapsed)}</span>
          <span>${CW.icon("ruler")} ${h.width && h.height ? h.width + '×' + h.height : '—'}</span>
        </div>
      </div>
      ${h.seed ? `<div class="gi-seed">${CW.icon("sprout")} ${h.seed}</div>` : ''}
    </div>
  </div>`;
  }

  _lastGalleryHash = '';

  _renderTimer = null;
function _populateFilterOptions() {
    var styles = new Set();
    for(var k = 0; k < historyItems.length; k++) {
      var j = historyItems[k];
      try {
        var pObj = JSON.parse(j.prompt || '{}');
        if(pObj.style && typeof pObj.style === 'string') {
          var s = pObj.style.trim();
          if(s.length > 0) styles.add(s);
        }
      } catch(e) {}
    }
    _syncTypeFilterButtons();
    var sizeSel = document.getElementById("gfSize");
    if(sizeSel) {
      sizeSel.innerHTML = '<option value="">全部尺寸</option>' +
        '<option value="1K">1K (≤1024)</option>' +
        '<option value="2K">2K (≤2048)</option>' +
        '<option value="4K">4K (≤3840)</option>' +
        '<option value="4K+">4K+ (>3840)</option>';
    }
    var styleInput = document.getElementById("gfStyle");
    if(styleInput && styles.size > 0) {
      var dlId = 'styleDatalist';
      var dl = document.getElementById(dlId);
      if(!dl) {
        dl = document.createElement('datalist');
        dl.id = dlId;
        document.body.appendChild(dl);
        styleInput.setAttribute('list', dlId);
      }
      var sorted = Array.from(styles).sort();
      dl.innerHTML = sorted.map(function(s) { return '<option value="' + escH(s) + '">'; }).join('');
    }
  }
function _filterHistory(arr) {
    return arr.filter(function(j) {
      if (_galleryFilters.owner && _galleryFilters.owner !== 'all') {
        var uid = _currentUserId();
        var owner = j && j.user_id ? String(j.user_id) : '';
        if (_galleryFilters.owner === 'mine' && (!uid || owner !== uid)) return false;
        if (_galleryFilters.owner === 'other' && uid && owner === uid) return false;
      }
      if(_galleryFilters.type) {
        if(_historyItemType(j) !== _galleryFilters.type) return false;
      }
      if(_galleryFilters.size) {
        var maxDim = Math.max(j.width || 0, j.height || 0);
        var sizeLevel = '';
        if(maxDim <= 1024) sizeLevel = '1K';
        else if(maxDim <= 2048) sizeLevel = '2K';
        else if(maxDim <= 3840) sizeLevel = '4K';
        else sizeLevel = '4K+';
        if(sizeLevel !== _galleryFilters.size) return false;
      }
      if(_galleryFilters.style) {
        var searchText = '';
        searchText += (j.prompt_preview || '').toLowerCase() + ' ';
        try {
          var pObj = JSON.parse(j.prompt || '{}');
          function _extractText(obj) {
            var t = '';
            if(typeof obj === 'string') return obj + ' ';
            if(typeof obj === 'object' && obj !== null) {
              for(var key in obj) { t += _extractText(obj[key]); }
            }
            return t;
          }
          searchText += _extractText(pObj).toLowerCase();
        } catch(e) {
          searchText += (j.prompt || '').toLowerCase();
        }
        if(searchText.indexOf(_galleryFilters.style) === -1) return false;
      }
      return true;
    });
  }

  _filteredHistory = [];

  _galleryFilters = { owner: 'all', type: '', size: '', style: '' };
function _ensureInitialBatch() {
    if (_histVisibleCount > 0) return;
    var initialItems = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
    _histVisibleCount = Math.min(_batchSize(), initialItems.length); console.log("[GALLERY DEBUG] _ensureInitialBatch: batch=" + _batchSize() + " filtered=" + _filteredHistory.length + " hist=" + historyItems.length + " => count=" + _histVisibleCount);
  }
function _batchSize() {
    return _getColumnCount() * 2;
  }
function _getColumnCount() {
    const gallery = $('#gallery');
    if (!gallery) return 3;
    const w = gallery.clientWidth;
    const gap = 10;
    const minCol = 140;
    return Math.max(1, Math.floor((w + gap) / (minCol + gap)));
  }

function lbNav(dir) {
    if (window.__APP__ && Array.isArray(window.__APP__._lbItems)) lbItems = window.__APP__._lbItems;
    lbIdx = Math.max(0, Math.min(lbIdx + dir, lbItems.length - 1));
    renderLB();
  }

  function _lightboxPreviewUrl(item) {
    if (!item) return '';
    return item.thumb ? `${API}/api/thumbs/${item.thumb}` : _lightboxImageUrl(item.filename);
  }

  function _primeLightboxImage(fullSrc, previewSrc) {
    var lbImg = $('#lbImg');
    var stage = $('#lbStage');
    if (!lbImg || !stage) return;
    _lbLoadToken += 1;
    var token = _lbLoadToken;
    stage.classList.remove('is-live');
    lbImg.classList.remove('lb-ready');
    lbImg.classList.add('lb-visible', 'lb-preview');
    lbImg.src = previewSrc || fullSrc;
    if (!fullSrc || fullSrc === previewSrc) {
      requestAnimationFrame(function () {
        if (token !== _lbLoadToken) return;
        stage.classList.add('is-live');
        lbImg.classList.remove('lb-preview');
        lbImg.classList.add('lb-ready');
      });
      return;
    }
    var loader = new Image();
    loader.onload = function () {
      if (token !== _lbLoadToken) return;
      lbImg.src = fullSrc;
      requestAnimationFrame(function () {
        if (token !== _lbLoadToken) return;
        stage.classList.add('is-live');
        lbImg.classList.remove('lb-preview');
        lbImg.classList.add('lb-ready');
      });
    };
    loader.src = fullSrc;
  }

  function _animateLightboxFromSource(sourceEl, previewSrc) {
    var overlay = $('#lightbox');
    var stage = $('#lbStage');
    if (!overlay || !stage || !sourceEl || !sourceEl.getBoundingClientRect) {
      if (stage) stage.classList.add('is-live');
      return;
    }
    var thumb = sourceEl.querySelector ? (sourceEl.querySelector('img') || sourceEl) : sourceEl;
    var fromRect = thumb.getBoundingClientRect();
    if (!fromRect.width || !fromRect.height) {
      stage.classList.add('is-live');
      return;
    }
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var toRect = stage.getBoundingClientRect();
        if (!toRect.width || !toRect.height) {
          stage.classList.add('is-live');
          return;
        }
        var flight = document.createElement('img');
        flight.className = 'lb-flight';
        flight.src = previewSrc || thumb.currentSrc || thumb.src || '';
        flight.alt = '';
        flight.style.left = fromRect.left + 'px';
        flight.style.top = fromRect.top + 'px';
        flight.style.width = fromRect.width + 'px';
        flight.style.height = fromRect.height + 'px';
        flight.style.borderRadius = getComputedStyle(thumb).borderRadius || '18px';
        document.body.appendChild(flight);
        overlay.classList.add('lb-has-flight');
        requestAnimationFrame(function () {
          flight.style.left = toRect.left + 'px';
          flight.style.top = toRect.top + 'px';
          flight.style.width = toRect.width + 'px';
          flight.style.height = toRect.height + 'px';
          flight.style.borderRadius = getComputedStyle(stage).borderRadius || '28px';
          flight.style.opacity = '0.9';
          flight.style.filter = 'blur(0px)';
        });
        setTimeout(function () {
          overlay.classList.remove('lb-has-flight');
          stage.classList.add('is-live');
          flight.remove();
        }, 320);
      });
    });
  }

  function _openLightbox(opts) {
    opts = opts || {};
    var overlay = $('#lightbox');
    if (!overlay) return;
    var fullSrc = opts.fullSrc || '';
    var previewSrc = opts.previewSrc || fullSrc;
    _primeLightboxImage(fullSrc, previewSrc);
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
    else overlay.classList.add('open');
    _animateLightboxFromSource(opts.sourceEl, previewSrc);
    document.body.style.overflow = 'hidden';
  }

function renderLB(sourceEl) {
    if (window.__APP__ && Array.isArray(window.__APP__._lbItems)) lbItems = window.__APP__._lbItems;
    if (lbIdx < 0 || lbIdx >= lbItems.length) return;
    const h = lbItems[lbIdx];
    _syncLightboxDownload(h.filename);
    _syncLightboxActions(h);
    $('#lbInfo').textContent = h.prompt || '—';
    $('#lbPrev').style.display = lbIdx > 0 ? '' : 'none';
    $('#lbNext').style.display = lbIdx < lbItems.length - 1 ? '' : 'none';
    _openLightbox({
      fullSrc: _lightboxImageUrl(h.filename),
      previewSrc: _lightboxPreviewUrl(h),
      sourceEl: sourceEl,
    });
  }

function closeLB() {
    var overlay = $('#lightbox');
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, false);
    else if (overlay) overlay.classList.remove('open');
    _lbLoadToken += 1;
    var stage = $('#lbStage');
    var lbImg = $('#lbImg');
    if (stage) stage.classList.remove('is-live');
    if (lbImg) lbImg.classList.remove('lb-visible', 'lb-preview', 'lb-ready');
    if (overlay) overlay.classList.remove('lb-has-flight');
    document.body.style.overflow = '';
    _syncLightboxDownload('');
    _syncLightboxActions(null);
    lbIdx = -1;
  }

async function downloadLB(e) {
    var link = $('#lbDownload');
    if (!link) return;
    var url = link.dataset.url || link.href;
    var filename = link.dataset.filename || 'image.png';
    var isMobileModal = window.matchMedia && window.matchMedia('(max-width: 765px)').matches;
    if (!isMobileModal) return;
    if (e) e.preventDefault();
    try {
      var resp = await fetch(url, { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('download failed');
      var blob = await resp.blob();
      var blobUrl = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      setTimeout(function() {
        a.remove();
        URL.revokeObjectURL(blobUrl);
      }, 1200);
    } catch (err) {
      window.open(url, '_blank', 'noopener');
    }
  }

function openJobLB(filename, label, sourceEl) {
    // Show a single-item lightbox for a job image
    _syncLightboxDownload(filename);
    _syncLightboxActions(null);
    $('#lbInfo').textContent = label || '';
    $('#lbPrev').style.display = 'none';
    $('#lbNext').style.display = 'none';
    _openLightbox({
      fullSrc: _lightboxImageUrl(filename),
      previewSrc: sourceEl && sourceEl.querySelector ? ((sourceEl.querySelector('img') || {}).currentSrc || '') : '',
      sourceEl: sourceEl,
    });
  }

function openLB(idx, sourceEl) {
    if (window.__APP__ && Array.isArray(window.__APP__._lbItems)) lbItems = window.__APP__._lbItems;
    lbIdx = idx;
    renderLB(sourceEl);
  }

  function toggleLBFavorite() {
    if (!_lbCurrentItem) return;
    var key = _lbCurrentItem.id || _lbCurrentItem.filename || _lbCurrentItem.original || _lbCurrentItem.prompt;
    if (!key) return;
    _lbFavorites[key] = !_lbFavorites[key];
    _syncLightboxActions(_lbCurrentItem);
    if (window.CW && CW.toast) CW.toast(_lbFavorites[key] ? '已收藏' : '已取消收藏', 'done');
  }

  function toggleLBShare() {
    if (!_lbCurrentItem || !_lbCurrentItem.id) {
      if (window.CW && CW.toast) CW.toast('当前图片暂不支持快速分享', 'info');
      return;
    }
    var auth = window.CW && CW.auth;
    if (!(auth && typeof auth.toggleShare === 'function')) {
      if (window.CW && CW.toast) CW.toast('分享功能暂不可用', 'error');
      return;
    }
    var next = !_lbCurrentItem.is_public;
    var currentId = _lbCurrentItem.id;
    auth.toggleShare(currentId, next).then(function(result) {
      if (!_lbCurrentItem || _lbCurrentItem.id !== currentId) return;
      _lbCurrentItem = Object.assign({}, _lbCurrentItem, { is_public: !!(result && result.is_public) });
      _syncLightboxActions(_lbCurrentItem);
    }).catch(function() {});
  }

async function delHist(id) {
    var item = historyItems.find(function(h) { return h.id === id; });
    if (!_canDeleteHistoryItem(item)) {
      if (window.CW && CW.toast) CW.toast('只能删除自己生成的内容，管理员可删除全部历史', 'info');
      return;
    }
    if (!confirm('确认删除这张图片？')) return;
    // Mark card as deleting immediately
    var card = document.querySelector('[data-hist-idx][onclick*="' + id.slice(-6) + '"]') || document.querySelector('[onclick*="' + id.slice(-6) + '"]');
    if (card) { card.classList.add('deleting'); card.style.opacity = '0.4'; card.style.pointerEvents = 'none'; }
    try {
      var authHeaders = window.CW.auth.getAuthHeaders();
      var r = await fetch(`${API}/api/history/${id}`, { method: 'DELETE', headers: Object.assign({}, authHeaders) });
      if (!r.ok) throw new Error('删除失败');
      var idx = historyItems.findIndex(function(h) { return h.id === id; });
      if (idx >= 0) historyItems.splice(idx, 1);
      _filteredHistory = _filterHistory(historyItems);
      renderGallery();
    } catch (e) {
      console.error('delHist:', e);
      if (card) { card.classList.remove('deleting'); card.style.opacity = ''; card.style.pointerEvents = ''; }
    }
  }

async function loadHistory() {
    try {
      console.log('[HIST] loadHistory start');
      var authHeaders = window.CW.auth.getAuthHeaders();
      const user = window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser();
      const scope = user && user.role === 'admin' ? 'all' : 'gallery';
      const r = await fetch(`${API}/api/history?scope=${scope}&limit=200`, { headers: Object.assign({}, authHeaders) });
      const d = await r.json();
      console.log('[HIST] loadHistory resp', r.status, d && d.total, d && d.data && d.data.length);
      if (d.ok) {
        historyItems.length = 0;
        Array.prototype.push.apply(historyItems, d.data);
        _lastGalleryHash = '';
        _populateFilterOptions();
        applyFilters();
        window.CW.loadWorkflows();
      }
    } catch (e) {
      console.error('loadHistory:', e);
    }
  }


function applyFilters() {
    _syncOwnerFilterButtons();
    _syncTypeFilterButtons();
    var el;
    el = document.getElementById("gfSize");
    _galleryFilters.size = el ? el.value : "";
    el = document.getElementById("gfStyle");
    _galleryFilters.style = el ? el.value.toLowerCase() : "";
    _filteredHistory = _filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = "";
    renderGallery();
  }

function clearFilters() {
    _galleryFilters = { owner: "all", type: "", size: "", style: "" };
    _syncOwnerFilterButtons();
    _syncTypeFilterButtons();
    var el;
    el = document.getElementById("gfSize");
    if (el) el.value = "";
    el = document.getElementById("gfStyle");
    if (el) el.value = "";
    _filteredHistory = _filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = "";
    renderGallery();
  }

function renderGallery() {
    if (_renderTimer) return;
    _renderTimer = requestAnimationFrame(function() {
      _renderTimer = null;
      _renderGalleryImpl();
    });
  }

  if (!window.CW) window.CW = {};
  window.CW.applyFilters = applyFilters;
  window.CW.clearFilters = clearFilters;
  window.CW.setHistoryOwnerFilter = setHistoryOwnerFilter;
  window.CW.setHistoryTypeFilter = setHistoryTypeFilter;
  window.CW.refreshHistoryTypeFilters = function() {
    _syncTypeFilterButtons();
    applyFilters();
  };
  window.CW.delHist = delHist;
  window.CW.openLB = openLB;
  window.CW.openJobLB = openJobLB;
  window.CW.closeLB = closeLB;
  window.CW.downloadLB = downloadLB;
  window.CW.lbNav = lbNav;
  window.CW.toggleLBFavorite = toggleLBFavorite;
  window.CW.toggleLBShare = toggleLBShare;
  window.CW.loadHistory = loadHistory;
  // Data-only refresh (no gallery re-render)
  async function loadHistoryNoRender() {
    try {
      var authHeaders = window.CW.auth.getAuthHeaders();
      const user = window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser();
      const scope = user && user.role === 'admin' ? 'all' : 'gallery';
      const r = await fetch(`${API}/api/history?scope=${scope}&limit=200`, { headers: Object.assign({}, authHeaders) });
      const d = await r.json();
      if (d.ok) {
        historyItems.length = 0;
        Array.prototype.push.apply(historyItems, d.data);
      }
    } catch (e) { console.error("loadHistoryNoRender:", e); }
  }
  window.CW.loadHistoryNoRender = loadHistoryNoRender;
  window.CW.renderGallery = renderGallery;
  window.CW.forceGalleryRerender = renderGallery;
  window.CW._renderJobCard = _renderJobCard;
  window.CW._patchJobCard = _patchJobCard;
  window.CW._onJobDone = _onJobDone;
  window.CW._onJobError = _onJobError;

  // 如果页面已登录但历史还没进来，兜底再拉一次
  setTimeout(function() {
    if (window.CW.auth && window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser() && historyItems.length === 0) {
      loadHistory();
    }
  }, 1500);

})();
