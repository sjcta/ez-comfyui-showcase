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
  var _pinnedHistoryIds = [];
  var _optimisticHistoryById = {};
  var _galleryBatchItems = {};
  var _loadHistoryPromise = null;
  var lbIdx = -1;
  var lbItems = [];
  var _galleryFilters = { owner: 'all', type: '', style: '' };
  var _renderTimer = null;
  var _lbLoadToken = 0;
  var _lbCurrentItem = null;
  var _lbFavorites = {};
  var HISTORY_FETCH_LIMIT = 300;

  function _lightboxImageUrl(filename) {
    return `${API}/api/images/${filename}`;
  }

  function _mediaType(itemOrType, filename) {
    var explicit = typeof itemOrType === 'string'
      ? itemOrType
      : (itemOrType && itemOrType.media_type);
    explicit = String(explicit || '').toLowerCase();
    if (explicit === 'video') return 'video';
    var name = String(filename || (itemOrType && itemOrType.filename) || '');
    return /\.(mp4|webm|mov|m4v)(\?|$)/i.test(name) ? 'video' : 'image';
  }

  function _isVideoItem(item) {
    return _mediaType(item) === 'video';
  }

  function _lightboxDownloadName(filename) {
    if (!filename) return 'image.png';
    var parts = String(filename).split('/');
    return parts[parts.length - 1] || 'image.png';
  }

  async function _historyJsonOrThrow(response, label) {
    if (!response.ok) {
      throw new Error(`${label}失败（${response.status}）`);
    }
    var data = await response.json();
    if (!data || !data.ok) {
      throw new Error(`${label}失败`);
    }
    return data;
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
    var actionState = _historyActionState(item);
    var isFav = !!(actionState && actionState.isFavorited);
    if (favBtn) {
      favBtn.style.display = actionState.canFavorite ? '' : 'none';
      favBtn.classList.toggle('is-active', isFav);
      favBtn.disabled = !actionState.canFavorite;
      favBtn.classList.toggle('is-disabled', !actionState.canFavorite);
      favBtn.title = isFav ? '取消收藏' : '收藏';
    }
    if (shareBtn) {
      shareBtn.style.display = actionState.canShare ? '' : 'none';
      shareBtn.classList.toggle('is-shared', !!(item && item.is_public));
      shareBtn.disabled = !actionState.canShare;
      shareBtn.classList.toggle('is-disabled', !actionState.canShare);
      shareBtn.title = item && item.is_public ? '取消分享' : '快速分享';
    }
  }

  function _historyFavoriteKey(item) {
    if (!item) return '';
    return String(item.id || item.filename || item.original || item.prompt || '');
  }

  function _isHistoryFavorited(item) {
    if (!item) return false;
    if (window.CW && CW.auth && typeof CW.auth.getHistoryActionState === 'function') {
      return !!CW.auth.getHistoryActionState(item).isFavorited;
    }
    var key = _historyFavoriteKey(item);
    return !!(key && _lbFavorites[key]);
  }

  function _historyActionState(item) {
    if (window.CW && CW.auth && typeof CW.auth.getHistoryActionState === 'function') {
      return CW.auth.getHistoryActionState(item);
    }
    return {
      hasUser: false,
      canFavorite: false,
      canShare: false,
      canDelete: false,
      isFavorited: false
    };
  }

  function _favoriteBadgeHtml(item) {
    var actionState = _historyActionState(item);
    var isFav = !!actionState.isFavorited;
    var id = item && item.id ? String(item.id) : '';
    if (!actionState.canFavorite) return '';
    if (!id || !(window.CW && CW.auth && typeof CW.auth.toggleHistoryFavorite === 'function')) return '';
    return '<button class="gi-fav-btn' + (isFav ? ' is-active' : '') + '" type="button" title="' + (isFav ? '取消收藏' : '收藏') + '" aria-label="' + (isFav ? '取消收藏' : '收藏') + '" onclick="event.stopPropagation();CW.auth.toggleHistoryFavorite(\'' + escA(id) + '\')"><svg class="cw-icon" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21.2 10.7 20C5.8 15.6 2.5 12.6 2.5 8.8 2.5 5.8 4.8 3.5 7.8 3.5c1.7 0 3.3.8 4.2 2.1.9-1.3 2.5-2.1 4.2-2.1 3 0 5.3 2.3 5.3 5.3 0 3.8-3.3 6.8-8.2 11.2L12 21.2Z"/></svg></button>';
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
  function _jobTimerTs(j) {
    return j && (j.generating_at || 0);
  }

  function _jobShowsTimer(j) {
    var status = j && j.status;
    return status === 'generating' || status === 'downloading' || status === 'checking';
  }

  function _jobTimerHtml(j) {
    if (!_jobShowsTimer(j)) return '';
    var ts = _jobTimerTs(j);
    if (!ts) return '';
    var estimateLabel = j.estimated_duration_label || '';
    var timerText = window.CW.formatJobElapsedWithEstimate
      ? window.CW.formatJobElapsedWithEstimate(ts, estimateLabel)
      : window.CW.formatElapsed(ts);
    return `<div class="gi-timer-row"><span class="gi-timer" data-ts="${escA(ts)}" data-estimate-label="${escA(estimateLabel)}">${escH(timerText)}</span></div>`;
  }

  function _renderJobCard(j) {
    const label = j.prompt_preview || j.workflow?.replace('.json', '') || '...';
    const statusMsg = j.message || j.status;
    const hasImage = !!j.image;
    const isVideo = _mediaType(j.media_type, j.image) === 'video';
    const checkingPreview = j.status === 'checking' && (j.pending_thumb || j.pending_image);
    const imgSrc = hasImage && !isVideo ? `${API}/api/images/${j.image}` : '';
    const checkingImgSrc = checkingPreview
      ? (j.pending_thumb ? `${API}/api/thumbs/${j.pending_thumb}` : `${API}/api/images/${j.pending_image}`)
      : '';
    const checkingSensitiveCls = j.status === 'checking' ? ' gi-sensitive' : '';

    // ── Image area ──
    let imgHtml = '';
    if (hasImage) {
      imgHtml = imgSrc ? `<img src="${imgSrc}" loading="lazy" alt="">` : _videoPreviewHtml(j.image, j.thumb);
    } else {
      if (checkingPreview) {
        imgHtml = `<img class="job-checking-preview" src="${checkingImgSrc}" loading="lazy" alt="">`;
      }
      if (j.status === 'generating' || j.status === 'preparing' || j.status === 'starting_comfyui' || j.status === 'submitting' || j.status === 'downloading' || j.status === 'checking') {
        imgHtml += `<div class="job-spinner"></div>`;
      }
      // Status text ABOVE timer (always shown for non-image states)
      if (j.status === 'queued') {
        imgHtml += `<div class="job-status-text queued">排队中</div>`;
      } else if (j.status === 'generating') {
        imgHtml += `<div class="job-status-text generating">${escH(statusMsg)}</div>`;
      } else if (j.status === 'downloading') {
        imgHtml += `<div class="job-status-text downloading">${escH(statusMsg || '正在拉取图片...')}</div>`;
      } else if (j.status === 'checking') {
        imgHtml += `<div class="job-status-text checking">${escH(statusMsg || '图片校验中')}</div>`;
      } else {
        imgHtml += `<div class="job-status-text ${escH(j.status)}">${escH(statusMsg)}</div>`;
      }
      imgHtml += _jobTimerHtml(j);
    }

    // ── Badge ──
    const wfMeta = A._wfMeta[j.workflow] || {};
    const wfLabel = window.CW && CW.workflowDisplayName
      ? CW.workflowDisplayName(j.workflow || '', wfMeta)
      : (String(wfMeta.name || '').trim() || (j.workflow || '').replace(/\.json$/i, ''));
    const wfTag = window.CW.wfTag ? window.CW.wfTag(j.workflow || '', wfMeta.tags) : '';
    const tagHtml = wfTag ? `<div class="gi-type-badge ${wfTag.cls}">${wfTag.text}</div>` : '';
    const instBadge = j.instance ? `<div class="gi-inst-badge">#${escH(j.instance)}</div>` : '';

    // ── Info area ──
    // Type class for border color
    const _jTag1 = window.CW.wfTag ? window.CW.wfTag(j.workflow || '', wfMeta.tags) : '';
    const _jCls1 = _jTag1 ? _jTag1.cls : '';
    const jTypeCls = _jCls1 ? 'gi-type-' + _jCls1.replace('wf-tag-', '') : '';
    return `<div class="gi job-card ${escH(j.status)} ${jTypeCls}" data-job-id="${escA(j.id)}">
      <div class="gi-img ${hasImage ? '' : 'job-placeholder'}${checkingSensitiveCls}">
        ${imgHtml}
        ${j.status === "error" ? `<div class="gi-retry-row"><button class="btn-retry" onclick="event.stopPropagation();CW.retryJob('${escA(j.id)}')">重新尝试</button></div>` : ""}
        <button class="gi-del" onclick="event.stopPropagation();CW.cancelJob('${escA(j.id)}')" title="${j.status === 'generating' ? '取消' : '删除'}"><svg class="cw-icon" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-trash-2"/></svg></button>
        ${tagHtml || instBadge ? `<div class="gi-tags-row">${tagHtml}${instBadge}</div>` : ''}
      </div>
      <div class="gi-info" onclick="event.stopPropagation();CW.restoreJob('${escA(j.id)}')">
        ${j.status === 'generating' || j.status === 'submitting' ? `<div class="gi-progress-top"><div class="gi-progress-fill" style="width:${j.progress?.pct || 0}%"></div></div>` : ''}
        ${wfLabel ? `<div class="gi-wf-label" title="${escA(wfLabel)}">${escH(wfLabel)}</div>` : ''}
        <div class="gi-prompt" title="${escA(j.prompt_preview || label)}">${escH(j.prompt_preview || label)}</div>
        ${j.status !== 'generating' && j.status !== 'submitting' ? `<div class="gi-meta">
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
    const timerEl = card.querySelector('.gi-timer');
    if (_jobShowsTimer(job)) {
      if (timerEl) {
        const timerTs = _jobTimerTs(job);
        timerEl.dataset.ts = timerTs;
        timerEl.dataset.estimateLabel = job.estimated_duration_label || timerEl.dataset.estimateLabel || '';
        timerEl.textContent = window.CW.formatJobElapsedWithEstimate
          ? window.CW.formatJobElapsedWithEstimate(timerTs, timerEl.dataset.estimateLabel)
          : window.CW.formatElapsed(timerTs);
      }
    } else if (timerEl) {
      const timerRow = timerEl.closest ? timerEl.closest('.gi-timer-row') : null;
      if (timerRow && timerRow.parentNode) timerRow.parentNode.removeChild(timerRow);
    }
    _ensureJobCardOrder();
  }

  function _refreshWorkflowPreviewFromJob(job) {
    if (window.CW && typeof CW.refreshWorkflowPreviewFromJob === 'function') {
      CW.refreshWorkflowPreviewFromJob(job);
    }
  }

  function _refreshWorkflowCardsAfterJobDone(job) {
    _refreshWorkflowPreviewFromJob(job);
    if (window.CW && typeof CW.loadWorkflows === 'function') {
      Promise.resolve(CW.loadWorkflows()).catch(function(e) {
        console.warn('refresh workflow previews failed:', e && e.message ? e.message : e);
      });
    }
  }

  function _onJobDone(job) {
    if (!job.image) return; // Wait for image to arrive
    _refreshWorkflowPreviewFromJob(job);
    // Immediate visual: blur the progress card away while the finished image card fades in.
    const card = document.querySelector(`[data-job-id="${job.id}"]`);
    var cleanupDelay = 980;
    if (card) {
      const frontHtml = card.innerHTML;
      const wfMeta = (A._wfMeta || {})[job.workflow] || {};
      const wfTag = window.CW.wfTag ? window.CW.wfTag(job.workflow || '', wfMeta.tags) : '';
      const tagBadge = wfTag ? `<div class="gi-type-badge ${wfTag.cls}">${wfTag.text}</div>` : '';
      const displayPrompt = job.prompt_preview || (job.workflow ? job.workflow.replace('.json', '') : '出图完成');
      const jobBatchCount = Number(job.batch_count || (Array.isArray(job.images) ? job.images.length : 1) || 1);
      const jobBatchBadge = jobBatchCount > 1 ? `<div class="gi-batch-badge">×${jobBatchCount}</div>` : '';
      const protectionStatus = String(job.protection_status || '').toLowerCase();
      const sensitiveCls = (protectionStatus === 'protected' || protectionStatus === 'error') ? ' gi-sensitive' : '';
      const isVideo = _mediaType(job.media_type, job.image) === 'video';
      const mediaHtml = isVideo
        ? _videoPreviewHtml(job.image, job.thumb)
        : `<img src="${API}/api/images/${job.image}" loading="lazy" alt="">`;
      const completeHtml =
        `<div class="gi-img${sensitiveCls}" onclick="event.stopPropagation();CW.openJobLB('${escA(job.image)}','${escA(job.prompt_preview || '')}', this, '${escA(job.media_type || '')}')">` +
          mediaHtml +
          tagBadge +
          jobBatchBadge +
        `</div>` +
        `<div class="gi-info">` +
          `<div class="gi-prompt" title="${escA(displayPrompt)}">${escH(displayPrompt)}</div>` +
          `<div class="gi-meta"><span>${CW.icon("clock")} 刚刚</span>` +
            `<div class="gi-meta-row">` +
              `<span>${CW.icon("timer")} ${_fmtElapsed(job.elapsed || 0)}</span>` +
              `<span>${CW.icon("ruler")} ${job.width && job.height ? job.width + '×' + job.height : '—'}</span>` +
            `</div></div>` +
          (job.seed ? `<div class="gi-seed">${CW.icon("sprout")} ${escH(String(job.seed))}</div>` : '') +
        `</div>`;
      card.className = 'gi job-card done completing job-card-complete-blurfade';
      card.innerHTML =
        `<div class="job-card-complete-transition">` +
          `<div class="job-card-complete-old">${frontHtml}</div>` +
          `<div class="job-card-complete-new">${completeHtml}</div>` +
        `</div>`;
      setTimeout(function() {
        if (!card.parentNode) return;
        card.classList.remove('completing', 'job-card-complete-blurfade');
        card.innerHTML = completeHtml;
      }, cleanupDelay);
    }
    setTimeout(function() {
      _promoteCompletedJobToHistory(job);
      delete jobs[job.id];
      renderGallery();
      var historyPromise = window.CW.loadHistory ? window.CW.loadHistory() : null;
      Promise.resolve(historyPromise).then(function() {
        _refreshWorkflowCardsAfterJobDone(job);
      });
    }, cleanupDelay);
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

function _histKey(h) {
    return String((h && (h.id || h.filename || h.thumb)) || '');
  }

function _galleryChildKey(el) {
    if (!el || !el.getAttribute) return '';
    if (el.hasAttribute('data-job-id')) return 'job:' + el.getAttribute('data-job-id');
    if (el.hasAttribute('data-hist-id')) return 'hist:' + el.getAttribute('data-hist-id');
    if (el.id === 'masonrySentinel') return 'sentinel';
    if (el.classList && el.classList.contains('empty-hint')) return 'empty';
    return '';
  }

  function _stableGalleryHTML(html) {
    return String(html || '')
      .replace(/\sstyle="[^"]*--gi-info-height:[^"]*"/g, '')
      .replace(/\sdata-video-mask-bound="[^"]*"/g, '')
      .replace(/\sdata-hist-idx="[^"]*"/g, '')
      .replace(/CW\.fillFormFromHistory\(\d+(?:,\s*'[^']*')?\)/g, 'CW.fillFormFromHistory(#)')
      .replace(/CW\.openLB\(\d+(?:,\s*this)?\)/g, 'CW.openLB(#)');
  }

function _placeGalleryChild(gallery, child, cursor) {
    if (!gallery || !child) return cursor;
    if (child === cursor) return child.nextSibling;
    gallery.insertBefore(child, cursor);
    return child.nextSibling;
  }

function _patchHistoryCardIndex(oldChild, newChild) {
    if (!oldChild || !newChild || !oldChild.hasAttribute('data-hist-id')) return false;
    if (_stableGalleryHTML(oldChild.outerHTML) !== _stableGalleryHTML(newChild.outerHTML)) return false;
    var nextIdx = newChild.getAttribute('data-hist-idx') || '0';
    oldChild.setAttribute('data-hist-idx', nextIdx);
    oldChild.setAttribute('onclick', newChild.getAttribute('onclick') || '');
    var oldImg = oldChild.querySelector('.gi-img');
    var newImg = newChild.querySelector('.gi-img');
    if (oldImg && newImg) oldImg.setAttribute('onclick', newImg.getAttribute('onclick') || '');
    var oldReuse = oldChild.querySelector('.gi-reuse');
    var newReuse = newChild.querySelector('.gi-reuse');
    if (oldReuse && newReuse) oldReuse.setAttribute('onclick', newReuse.getAttribute('onclick') || '');
    return true;
  }

function _jobCardStatusClass(card) {
    if (!card || !card.classList) return '';
    var statuses = ['queued', 'preparing', 'dispatching', 'starting_comfyui', 'submitting', 'generating', 'downloading', 'checking'];
    for (var i = 0; i < statuses.length; i++) {
      if (card.classList.contains(statuses[i])) return statuses[i];
    }
    return '';
  }

function _patchStableJobCard(oldChild, newChild) {
    if (!oldChild || !newChild || !oldChild.hasAttribute('data-job-id') || !newChild.hasAttribute('data-job-id')) return false;
    var id = oldChild.getAttribute('data-job-id') || '';
    if (!id || id !== (newChild.getAttribute('data-job-id') || '')) return false;
    if (_jobCardStatusClass(oldChild) !== _jobCardStatusClass(newChild)) return false;
    var job = jobs && jobs[id];
    if (!job || job.status === 'done' || job.status === 'error') return false;
    _patchJobCard(job);
    return true;
  }

function _patchGalleryHTML(gallery, html) {
    var tpl = document.createElement('template');
    tpl.innerHTML = html;
    var next = Array.prototype.slice.call(tpl.content.children);
    var oldByKey = {};
    Array.prototype.slice.call(gallery.children).forEach(function(child) {
      var key = _galleryChildKey(child);
      if (key) oldByKey[key] = child;
    });
    var cursor = gallery.firstChild;
    next.forEach(function(newChild) {
      var key = _galleryChildKey(newChild);
      var oldChild = key ? oldByKey[key] : null;
      var childToPlace = newChild;
      if (oldChild) {
        delete oldByKey[key];
        if (oldChild.outerHTML !== newChild.outerHTML && !_patchStableJobCard(oldChild, newChild) && !_patchHistoryCardIndex(oldChild, newChild)) {
          var replacingCursor = oldChild === cursor;
          var afterOldChild = oldChild.nextSibling;
          oldChild.replaceWith(newChild);
          if (replacingCursor) cursor = newChild;
          else if (cursor && cursor.parentNode !== gallery) cursor = afterOldChild;
        } else {
          childToPlace = oldChild;
        }
      } else {
        if (newChild.hasAttribute('data-job-id') && newChild.classList.contains('queued')) {
          newChild.classList.add('queue-entering');
          setTimeout(function() { newChild.classList.remove('queue-entering'); }, 360);
        }
      }
      cursor = _placeGalleryChild(gallery, childToPlace, cursor);
    });
    Object.keys(oldByKey).forEach(function(key) {
      var oldChild = oldByKey[key];
      if (oldChild.parentNode) oldChild.remove();
    });
    _scheduleVideoPreviewMaskSync(gallery);
  }

  var _videoMaskObserver = null;

  function _setVideoPreviewMaskHeight(card) {
    if (!card) return;
    var info = card.querySelector('.gi-info');
    if (!info) return;
    var height = Math.ceil(info.getBoundingClientRect().height || info.offsetHeight || 0);
    if (height > 0) card.style.setProperty('--gi-info-height', height + 'px');
  }

  function _syncVideoPreviewMasks(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var cards = scope.querySelectorAll('.gi:not(.job-card)');
    if (!_videoMaskObserver && 'ResizeObserver' in window) {
      _videoMaskObserver = new ResizeObserver(function(entries) {
        entries.forEach(function(entry) {
          _setVideoPreviewMaskHeight(entry.target && entry.target.closest ? entry.target.closest('.gi:not(.job-card)') : null);
        });
      });
    }
    Array.prototype.forEach.call(cards, function(card) {
      if (!card.querySelector('.gi-video-poster')) return;
      _setVideoPreviewMaskHeight(card);
      if (card.dataset.videoMaskBound === '1') return;
      card.dataset.videoMaskBound = '1';
      card.addEventListener('mouseenter', function() {
        requestAnimationFrame(function() { _setVideoPreviewMaskHeight(card); });
      });
      card.addEventListener('mouseleave', function() {
        requestAnimationFrame(function() { _setVideoPreviewMaskHeight(card); });
      });
      if (_videoMaskObserver) {
        var info = card.querySelector('.gi-info');
        if (info) _videoMaskObserver.observe(info);
      }
    });
  }

  function _scheduleVideoPreviewMaskSync(root) {
    requestAnimationFrame(function() { _syncVideoPreviewMasks(root); });
  }

function _renderHistCard(h, i) {
    const entry = h;
    h = _batchCover(entry);
    const isBatch = !!(entry && entry.__isBatch);
    const batchCount = isBatch ? Number(entry.batch_count || (entry.items && entry.items.length) || 1) : 1;
    const canDelete = _batchCanDelete(entry, h);
    const deleteTargetId = _batchDeleteTargetId(entry, h);
    const deleteTitle = isBatch ? '删除本批次' : '删除';
    const batchStackImages = _batchStackImages(entry, h);
    const mainText1 = _historyItemType(h);
    const mainCls1 = _typeClass(mainText1, h.workflow);
    const displayPrompt = _historyDisplayPrompt(h);
    const sensitiveCls = _isSensitivePreview(h, displayPrompt) ? ' gi-sensitive' : '';
    const tagBadge = mainText1 ? `<div class="gi-type-badge ${mainCls1}">${mainText1}</div>` : '';
    const typeCls1 = mainCls1 ? 'gi-type-' + mainCls1.replace('wf-tag-', '') : '';
    const histKey = _histKey(h);
    const entryKey = _galleryEntryKey(entry);
    const openAction = isBatch
      ? `CW.openBatchLB('${escA(entry.batch_id)}', this)`
      : `CW.openLB(${i}, this)`;
    const batchBadge = isBatch ? `<div class="gi-batch-badge">×${batchCount}</div>` : '';
    const videoTag = _infoVideoTagHtml(h);

	    return `<div class="gi ${typeCls1}${isBatch ? ' gi-batch-stack' : ''}" data-wf="${escA(h.workflow || '')}" data-hist-id="${escA(entryKey || histKey)}" data-hist-idx="${i}" data-favorited="${_isHistoryFavorited(h) ? '1' : '0'}" onclick="CW.fillFormFromHistory(${i}, '${escA(histKey)}')">
	      <div class="gi-img${sensitiveCls}" onclick="event.stopPropagation();${openAction}">
	        ${batchStackImages}
	        ${_mediaPreviewHtml(h)}
	        ${_favoriteBadgeHtml(h)}
	        ${tagBadge}
        ${canDelete && deleteTargetId ? `<button class="gi-del" onclick="event.stopPropagation();CW.delHist('${escA(deleteTargetId)}')" title="${deleteTitle}"><svg class="cw-icon" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-trash-2"/></svg></button>` : ''}
      </div>
      <div class="gi-info">
	        <div class="gi-info-actions">
	          ${videoTag}
	          ${batchBadge}
	        <button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(${i}, '${escA(histKey)}')" title="复刻出图" aria-label="复刻出图">${CW.icon("copy")}</button>
	        </div>
        <div class="gi-prompt" title="${escA(displayPrompt)}">${escH(displayPrompt)}</div>
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
    return !!_historyActionState(h).canDelete;
  }

function _clearHistoryDeleteFocus() {
    var active = document.activeElement;
    if (active && active.blur && active.classList && active.classList.contains('gi-del')) {
      active.blur();
    }
    requestAnimationFrame(function() {
      var current = document.activeElement;
      if (current && current.blur && current.classList && current.classList.contains('gi-del')) {
        current.blur();
      }
    });
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

function _typeClass(typeText, workflowName) {
    var fallback = window.CW && CW.getWFType ? CW.getWFType(workflowName || '') : null;
    if (fallback && fallback.text === typeText) return fallback.cls;
    if (typeText === '文生图') return 'wf-tag-t2i';
    if (typeText === '图生图') return 'wf-tag-i2i';
    if (typeText === '文生视频') return 'wf-tag-t2v';
    if (typeText === '图生视频') return 'wf-tag-i2v';
    if (/视频/.test(typeText || '')) return 'wf-tag-video';
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

function _historyDisplayPrompt(item) {
    if (!item) return '—';
    var text = item.prompt || item.prompt_preview || '';
    if (text) return text;
    if (_historyItemType(item) === '放大') {
      var fields = item.field_values || {};
      var resolution = 0;
      Object.keys(fields).some(function(key) {
        var field = String(key).split('::').pop();
        if (field !== 'resolution' && field !== 'max_resolution') return false;
        resolution = parseInt(fields[key], 10) || 0;
        return true;
      });
      if (resolution >= 3840) return '4K 放大';
      if (resolution >= 1920) return '2K 放大';
      return resolution > 0 ? (resolution + 'P 放大') : '放大';
    }
    return '—';
  }

  function _isSensitivePreview(item, displayPrompt) {
    var protectionStatus = String(item && item.protection_status || '').toLowerCase();
    if (protectionStatus === 'protected' || protectionStatus === 'error' || protectionStatus === 'pending') return true;
    if (protectionStatus === 'safe') return false;
    var text = [
      displayPrompt,
      item && item.prompt,
      item && item.prompt_preview
    ].filter(Boolean).join(' ').toLowerCase();
    if (!text) return false;
    return /18\s*\+|18禁|r18|r-18|nsfw|nfsw|成人|成年|裸体|全裸|私处|乳头|生殖器|色情|情色|露点|\bsex\b|\bsexual\b|\bnude\b|\bnudity\b|\bporn\b|\berotic\b/.test(text);
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
      var mainTag = tags[0] || (typeTag ? typeTag.text : '');
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
      !!_galleryFilters.style;
  }

  function _jobSortPriority(status) {
    if (status === 'queued') return 0;
    if (status === 'preparing' || status === 'starting_comfyui' || status === 'submitting') return 1;
    if (status === 'generating' || status === 'downloading' || status === 'checking') return 2;
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

  function _ensureJobCardOrder() {
    var gallery = $('#gallery');
    if (!gallery) return;
    var cards = Array.prototype.slice.call(gallery.children).filter(function(el) {
      return el && el.hasAttribute && el.hasAttribute('data-job-id');
    });
    if (cards.length < 1) return;
    var sorted = cards.slice().sort(function(a, b) {
      var ja = jobs[a.getAttribute('data-job-id')] || {};
      var jb = jobs[b.getAttribute('data-job-id')] || {};
      return _sortJobCards([ja, jb])[0] === ja ? -1 : 1;
    });
    var firstNonJob = Array.prototype.slice.call(gallery.children).find(function(el) {
      return !(el && el.hasAttribute && el.hasAttribute('data-job-id'));
    }) || null;
    var changed = sorted.some(function(card, idx) { return card !== cards[idx]; }) ||
      (firstNonJob && cards.some(function(card) {
        return !!(card.compareDocumentPosition(firstNonJob) & Node.DOCUMENT_POSITION_PRECEDING);
      }));
    if (!changed) return;
    sorted.forEach(function(card) {
      gallery.insertBefore(card, firstNonJob);
    });
  }

  function _historySortTimestamp(item) {
    if (!item) return 0;
    var raw = item.time || item.created_at || item.completed_at || '';
    if (!raw) return 0;
    if (typeof raw === 'number') return raw;
    var parsed = Date.parse(raw);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  function _sortHistoryItems(items) {
    return (items || []).slice().sort(function(a, b) {
      var tsDiff = _historySortTimestamp(b) - _historySortTimestamp(a);
      if (tsDiff !== 0) return tsDiff;
      var sortDiff = Number(b && b.sort_index || 0) - Number(a && a.sort_index || 0);
      if (sortDiff !== 0) return sortDiff;
      return String(b && b.id || '').localeCompare(String(a && a.id || ''));
    });
  }

  function _pinHistoryId(id) {
    id = String(id || '');
    if (!id) return;
    _pinnedHistoryIds = _pinnedHistoryIds.filter(function(x) { return x !== id; });
    _pinnedHistoryIds.unshift(id);
    _pinnedHistoryIds = _pinnedHistoryIds.slice(0, 8);
  }

  function _applyPinnedHistoryOrder(items) {
    var arr = (items || []).slice();
    if (!_pinnedHistoryIds.length) return arr;
    var found = new Set(arr.map(function(item) { return String(item && item.id || ''); }));
    _pinnedHistoryIds = _pinnedHistoryIds.filter(function(id) { return found.has(id); });
    if (!_pinnedHistoryIds.length) return arr;
    var pinRank = {};
    _pinnedHistoryIds.forEach(function(id, idx) { pinRank[id] = idx; });
    return arr.sort(function(a, b) {
      var aid = String(a && a.id || '');
      var bid = String(b && b.id || '');
      var ap = Object.prototype.hasOwnProperty.call(pinRank, aid);
      var bp = Object.prototype.hasOwnProperty.call(pinRank, bid);
      if (ap || bp) {
        if (ap && bp) return pinRank[aid] - pinRank[bid];
        return ap ? -1 : 1;
      }
      return 0;
    });
  }

  function _batchKey(item) {
    if (!item) return '';
    var count = Number(item.batch_count || 1);
    var batchId = String(item.batch_id || '');
    return count > 1 && batchId ? batchId : '';
  }

  function _batchIndex(item) {
    var n = Number(item && item.batch_index);
    return Number.isFinite(n) ? n : 0;
  }

  function _batchCover(entry) {
    return entry && entry.__isBatch ? entry.cover : entry;
  }

  function _historyImageSrc(item) {
    if (!item) return '';
    if (_isVideoItem(item)) return '';
    if (item.thumb) return `${API}/api/thumbs/${item.thumb}`;
    return item.filename ? `${API}/api/images/${item.filename}` : '';
  }

  function _videoPosterHtml() {
    return `<div class="gi-video-poster" aria-hidden="true">${CW.icon ? CW.icon("play") : '▶'}</div>`;
  }

  function _infoVideoTagHtml(item) {
    if (!_isVideoItem(item)) return '';
    return `<span class="gi-video-chip" title="视频" aria-label="视频">${CW.icon ? CW.icon("video", 16) : '▣'}</span>`;
  }

  function _videoPreviewSrc(filename) {
    return filename ? `${API}/api/images/${filename}#t=0.1` : '';
  }

  function _videoPreviewHtml(filename, thumb) {
    if (thumb) return `<img class="gi-video-thumb" src="${API}/api/thumbs/${thumb}" loading="lazy" alt="">${_videoPosterHtml()}`;
    var src = _videoPreviewSrc(filename);
    if (!src) return _videoPosterHtml();
    return `<video class="gi-video-preview" src="${escA(src)}" muted playsinline preload="metadata"></video>${_videoPosterHtml()}`;
  }

  function _mediaPreviewHtml(item) {
    if (_isVideoItem(item)) return _videoPreviewHtml(item.filename, item.thumb);
    var src = _historyImageSrc(item);
    if (src) return `<img src="${escA(src)}" loading="lazy" alt="">`;
    return '';
  }

  function _batchStackImages(entry, cover) {
    if (!(entry && entry.__isBatch && Array.isArray(entry.items))) return '';
    return entry.items
      .filter(function(item) { return item && item !== cover && (item.thumb || item.filename); })
      .slice(0, 2)
      .map(function(item, idx) {
        var src = _historyImageSrc(item);
        return src ? `<img class="gi-batch-layer gi-batch-layer-${idx + 1}" src="${escA(src)}" loading="lazy" alt="">` : '';
      })
      .join('');
  }

  function _batchCanDelete(entry, cover) {
    if (entry && entry.__isBatch && Array.isArray(entry.items)) {
      return entry.items.some(function(item) { return _canDeleteHistoryItem(item); });
    }
    return _canDeleteHistoryItem(cover);
  }

  function _batchDeleteTargetId(entry, cover) {
    var target = entry && entry.__isBatch && entry.cover ? entry.cover : cover;
    return String(target && target.id || '');
  }

  function _galleryEntryKey(entry) {
    if (entry && entry.__isBatch) return 'batch:' + entry.batch_id;
    return String(entry && (entry.id || entry.filename || entry.original || '') || '');
  }

  function _groupHistoryForGallery(items) {
    var out = [];
    var map = {};
    _galleryBatchItems = {};
    (items || []).forEach(function(item) {
      var key = _batchKey(item);
      if (!key) {
        out.push(item);
        return;
      }
      if (!map[key]) {
        map[key] = {
          __isBatch: true,
          id: 'batch:' + key,
          batch_id: key,
          batch_count: Number(item.batch_count || 1),
          cover: item,
          items: [],
        };
        out.push(map[key]);
      }
      map[key].items.push(item);
    });
    Object.keys(map).forEach(function(key) {
      var entry = map[key];
      entry.items.sort(function(a, b) { return _batchIndex(a) - _batchIndex(b); });
      entry.cover = entry.items[0] || entry.cover;
      entry.batch_count = Math.max(entry.items.length, Number(entry.cover && entry.cover.batch_count || entry.batch_count || 1));
      _galleryBatchItems[key] = entry.items;
    });
    if (window.__APP__) window.__APP__._galleryBatchItems = _galleryBatchItems;
    return out;
  }

  function _historyRecordFromJob(job) {
    return {
      id: job.id,
      filename: job.image || '',
      thumb: job.thumb || '',
      workflow: job.workflow || '',
      workflow_type: job.workflow_type || _historyItemType(job),
      prompt: job.prompt_preview || '',
      prompt_preview: job.prompt_preview || '',
      seed: job.seed || '',
      width: job.width || 0,
      height: job.height || 0,
      elapsed: job.elapsed || 0,
      time: new Date().toISOString(),
      user_id: job.user_id || '',
      is_public: false,
      batch_id: job.batch_id || '',
      batch_index: Number(job.batch_index || 0),
      batch_count: Number(job.batch_count || 1),
      protection_status: job.protection_status || 'safe',
      protection_score: job.protection_score || 0,
      protection_source: job.protection_source || '',
      protection_reason: job.protection_reason || '',
      field_values: job.fields || {}
    };
  }

  function _promoteCompletedJobToHistory(job) {
    if (!job || !job.id || !job.image) return;
    var jobRecords = Array.isArray(job.batch_items) && job.batch_items.length
      ? job.batch_items.map(function(item, idx) {
          return Object.assign({}, _historyRecordFromJob(job), item, {
            batch_id: item.batch_id || job.batch_id || (job.batch_items.length > 1 ? job.id : ''),
            batch_index: Number(item.batch_index != null ? item.batch_index : idx),
            batch_count: Number(item.batch_count || job.batch_count || job.batch_items.length || 1),
          });
        })
      : [_historyRecordFromJob(job)];
    var ids = new Set(jobRecords.map(function(item) { return String(item && item.id || ''); }));
    for (var i = historyItems.length - 1; i >= 0; i--) {
      if (ids.has(String(historyItems[i] && historyItems[i].id || ''))) historyItems.splice(i, 1);
    }
    jobRecords.forEach(function(item) {
      _optimisticHistoryById[item.id] = item;
    });
    _pinHistoryId(jobRecords[0].id);
    for (var r = jobRecords.length - 1; r >= 0; r--) {
      historyItems.unshift(jobRecords[r]);
    }
    historyItems.splice(0, historyItems.length, ..._applyPinnedHistoryOrder(_sortHistoryItems(historyItems)));
    _filteredHistory = _applyPinnedHistoryOrder(_filterHistory(historyItems));
    if (_histVisibleCount <= 0) _histVisibleCount = Math.min(_batchSize(), historyItems.length);
    else _histVisibleCount = Math.min(Math.max(_histVisibleCount, 1), historyItems.length);
    _lastGalleryHash = '';
  }

function _renderGalleryImpl() {
    const gallery = $('#gallery');

    // Ensure we have an initial batch size on first render
    _ensureInitialBatch();

    // Active jobs (queued, preparing, starting_comfyui, submitting, generating)
    const activeJobs = Object.values(jobs).filter(_isJobVisibleToCurrentUser).filter((j) => j.status !== 'done' && j.status !== 'error');
    // Error jobs (kept briefly for visibility)
    const errorJobs = Object.values(jobs).filter(_isJobVisibleToCurrentUser).filter((j) => j.status === 'error');

    const jobCards = _sortJobCards([...activeJobs, ...errorJobs]);

    // ── Hash check: skip rebuild if nothing changed ──
    const hash = _galleryHash(jobs, historyItems);
    if (hash === _lastGalleryHash) return;
    _lastGalleryHash = hash;

    var html = '';

    // ── Job cards always stay before history cards, even after history deletes/rebuilds.
    for (const j of jobCards) {
      html += _renderJobCard(j);
    }

    // ── History items ──
    const filteredArr = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
    const displayArr = _groupHistoryForGallery(filteredArr);
    var histCountEl = $('#histCount');
    if (histCountEl) histCountEl.textContent = String(filteredArr.length) + ' / ' + String(historyItems.length);
    lbItems = displayArr;
    if (window.__APP__) window.__APP__._lbItems = displayArr;
    _histVisibleCount = Math.min(Math.max(_histVisibleCount, _batchSize()), displayArr.length);
    const visibleItems = displayArr.slice(0, _histVisibleCount);
    for (let i = 0; i < visibleItems.length; i++) {
      html += _renderHistCard(visibleItems[i], i);
    }

    if (displayArr.length > _histVisibleCount) {
      html += `<div class="masonry-sentinel" id="masonrySentinel"></div>`;
    }

    if (!jobCards.length && !displayArr.length) {
      html = `<div class="empty-hint"><div class="eh-icon">${CW.icon("image", 32)}</div><p>暂无历史</p><p class="hint-sub">出图后自动出现在这里</p></div>`;
    }

    try { _patchGalleryHTML(gallery, html); } catch(e) { console.error("[GALLERY ERROR]", e); var ediv = document.getElementById("gallery"); if(ediv) ediv.innerHTML = "<div style=color:red;padding:20px>Render error: " + e.message + "</div>"; }

    _lastRenderedHistCount = visibleItems.length;
    lbItems = displayArr;
    if (window.__APP__) window.__APP__._lbItems = displayArr;
    _attachSentinel();
  }
function _galleryHash(jobsObj, histArr) {
    // Only structural changes trigger full rebuild: job added/removed, status transitions, history items added/removed
    var s = '';
    for (const j of Object.values(jobsObj).filter(_isJobVisibleToCurrentUser)) {
      s += j.id + j.status + '|';
    }
    var histSig = (histArr || []).slice(0, Math.max(_histVisibleCount || 0, 24)).map(function(item) {
      return String(item && item.id || '');
    }).join('|');
    return s + '::' + histArr.length + '::' + histSig + '::pin:' + _pinnedHistoryIds.join(',');
  }
function _appendNewHistoryCards() {
    const gallery = $('#gallery');
    if (!gallery) return;
    const sentinel = gallery.querySelector('.masonry-sentinel');
    const prevCount = _lastRenderedHistCount;
    const filteredArr2 = _groupHistoryForGallery(_hasActiveGalleryFilters() ? _filteredHistory : historyItems);
    const newCount = Math.min(_histVisibleCount, filteredArr2.length);
    if (newCount <= prevCount) {
      if (sentinel) _attachSentinel();
      return;
    }

    var fragment = '';
    for (let i = prevCount; i < newCount; i++) {
      fragment += _histCardHTML(filteredArr2[i], i);
    }

    if (sentinel) sentinel.insertAdjacentHTML('beforebegin', fragment);
    else gallery.insertAdjacentHTML('beforeend', fragment);
    _scheduleVideoPreviewMaskSync(gallery);

    _lastRenderedHistCount = newCount;

    if (newCount >= filteredArr2.length && sentinel) {
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
    var entry = h;
    h = _batchCover(entry);
    var isBatch = !!(entry && entry.__isBatch);
    var batchCount = isBatch ? Number(entry.batch_count || (entry.items && entry.items.length) || 1) : 1;
    const user = window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser();
    const canEdit = !!user;
    const canDelete = _batchCanDelete(entry, h);
    const deleteTargetId = _batchDeleteTargetId(entry, h);
    const deleteTitle = isBatch ? '删除本批次' : '删除';
    const batchStackImages = _batchStackImages(entry, h);
    const mainText2 = _historyItemType(h);
    const mainCls2 = _typeClass(mainText2, h.workflow);
    const displayPrompt = _historyDisplayPrompt(h);
    const sensitiveCls = _isSensitivePreview(h, displayPrompt) ? ' gi-sensitive' : '';
    const tagBadge = mainText2 ? `<div class="gi-type-badge ${mainCls2}">${mainText2}</div>` : '';
    const typeCls2 = mainCls2 ? 'gi-type-' + mainCls2.replace('wf-tag-', '') : '';
    const histKey = _histKey(h);
    var entryKey = _galleryEntryKey(entry);
    var openAction = isBatch ? `CW.openBatchLB('${escA(entry.batch_id)}', this)` : `CW.openLB(${i}, this)`;
    var batchBadge = isBatch ? `<div class="gi-batch-badge">×${batchCount}</div>` : '';
    var videoTag = _infoVideoTagHtml(h);
    return `<div class="gi ${typeCls2}${isBatch ? ' gi-batch-stack' : ''}" data-wf="${escA(h.workflow || '')}" data-hist-id="${escA(entryKey || histKey)}" data-hist-idx="${i}" data-favorited="${_isHistoryFavorited(h) ? '1' : '0'}" onclick="CW.fillFormFromHistory(${i}, '${escA(histKey)}')">
    <div class="gi-img lazy-img${sensitiveCls}" onclick="event.stopPropagation();${openAction}">
      ${batchStackImages}
      ${_mediaPreviewHtml(h)}
      ${_favoriteBadgeHtml(h)}
      ${tagBadge}
      ${canDelete && deleteTargetId ? `<button class="gi-del" onclick="event.stopPropagation();CW.delHist('${escA(deleteTargetId)}')" title="${deleteTitle}"><svg class="cw-icon" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-trash-2"/></svg></button>` : ''}
    </div>
    <div class="gi-info">
      <div class="gi-info-actions">
        ${videoTag}
        ${batchBadge}
      ${canEdit ? `<button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(${i}, '${escA(histKey)}')" title="复刻出图" aria-label="复刻出图">${CW.icon("copy")}</button>` : ''}
      </div>
      <div class="gi-prompt" title="${escA(displayPrompt)}">${escH(displayPrompt)}</div>
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
        if (_galleryFilters.owner === 'favorite' && !_isHistoryFavorited(j)) return false;
        if (_galleryFilters.owner === 'other' && uid && owner === uid) return false;
      }
      if(_galleryFilters.type) {
        if(_historyItemType(j) !== _galleryFilters.type) return false;
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

  _galleryFilters = { owner: 'all', type: '', style: '' };
function _ensureInitialBatch() {
    if (_histVisibleCount > 0) return;
    var initialItems = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
    _histVisibleCount = Math.min(_batchSize(), initialItems.length);
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

  function _resetLightboxVideo() {
    var video = $('#lbVideo');
    var stage = $('#lbStage');
    if (!video) return;
    try { video.pause(); } catch (e) {}
    if (stage) stage.classList.remove('lb-video-playing');
    video.classList.remove('lb-video-visible');
    video.onloadedmetadata = null;
    video.onloadeddata = null;
    video.onplay = null;
    video.onpause = null;
    video.onended = null;
    video.onclick = null;
    video.onerror = null;
    video.controls = false;
    video.removeAttribute('src');
    video.removeAttribute('poster');
    try { video.load(); } catch (e) {}
  }

  function _syncLightboxVideoPlayingState() {
    var video = $('#lbVideo');
    var stage = $('#lbStage');
    if (!video || !stage) return;
    stage.classList.toggle('lb-video-playing', !!(!video.paused && !video.ended));
  }

  function _lockLightboxVideoSize(video) {
    if (!video) return null;
    var width = Number(video.videoWidth || 0);
    var height = Number(video.videoHeight || 0);
    if (!width || !height) return null;
    return _lockLightboxDisplaySize({ width: width, height: height });
  }

  function _lockLightboxDisplaySize(size) {
    var lbImg = $('#lbImg');
    var fullImg = $('#lbFullImg');
    var video = $('#lbVideo');
    var stage = $('#lbStage');
    var rect = _finalLightboxImageRectForAspect(size);
    if (!lbImg || !rect) return null;
    lbImg.style.width = rect.width + 'px';
    lbImg.style.height = rect.height + 'px';
    if (fullImg) {
      fullImg.style.width = rect.width + 'px';
      fullImg.style.height = rect.height + 'px';
    }
    if (video) {
      video.style.width = rect.width + 'px';
      video.style.height = rect.height + 'px';
    }
    if (stage) {
      stage.style.width = rect.width + 'px';
      stage.style.height = rect.height + 'px';
    }
    return rect;
  }

  function _clearLightboxDisplaySize() {
    var lbImg = $('#lbImg');
    var fullImg = $('#lbFullImg');
    var video = $('#lbVideo');
    var stage = $('#lbStage');
    if (lbImg) {
      lbImg.style.width = '';
      lbImg.style.height = '';
    }
    if (fullImg) {
      fullImg.style.width = '';
      fullImg.style.height = '';
    }
    if (video) {
      video.style.width = '';
      video.style.height = '';
    }
    if (stage) {
      stage.style.width = '';
      stage.style.height = '';
    }
  }

  function _resetLightboxFullLayer() {
    var fullImg = $('#lbFullImg');
    if (!fullImg) return;
    fullImg.classList.remove('lb-full-visible');
    fullImg.removeAttribute('src');
    fullImg.style.width = '';
    fullImg.style.height = '';
  }

  function _fadeInLightboxFullImage(fullSrc, token, size, onVisible) {
    var lbImg = $('#lbImg');
    var fullImg = $('#lbFullImg');
    if (!fullImg) {
      if (lbImg && fullSrc) {
        lbImg.src = fullSrc;
        lbImg.classList.remove('lb-preview');
        lbImg.classList.add('lb-ready');
      }
      if (typeof onVisible === 'function') onVisible();
      return;
    }
    if (size && size.width && size.height) _lockLightboxDisplaySize(size);
    fullImg.classList.remove('lb-full-visible');
    fullImg.src = fullSrc;
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        if (token !== _lbLoadToken) return;
        fullImg.classList.add('lb-full-visible');
        if (typeof onVisible === 'function') onVisible();
        setTimeout(function() {
          if (token !== _lbLoadToken || !lbImg) return;
          lbImg.src = '';
          lbImg.classList.remove('lb-visible', 'lb-preview', 'lb-ready');
        }, 280);
      });
    });
  }

  function _primeLightboxImage(fullSrc, previewSrc, revealWhenReady, loadFullNow, expectedSize) {
    revealWhenReady = revealWhenReady !== false;
    loadFullNow = loadFullNow !== false;
    var lbImg = $('#lbImg');
    var stage = $('#lbStage');
    if (!lbImg || !stage) return Promise.resolve(null);
    _lbLoadToken += 1;
    var token = _lbLoadToken;
    stage.classList.remove('is-live');
    _resetLightboxFullLayer();
    lbImg.classList.remove('lb-ready');
    lbImg.classList.add('lb-visible', 'lb-preview');
    if (expectedSize) _lockLightboxDisplaySize(expectedSize);
    lbImg.src = previewSrc || fullSrc;
    return new Promise(function(resolve) {
      if (!loadFullNow) {
        requestAnimationFrame(function () {
          if (token !== _lbLoadToken) return resolve(null);
          if (revealWhenReady) stage.classList.add('is-live');
          resolve({
            width: lbImg.naturalWidth || 0,
            height: lbImg.naturalHeight || 0,
          });
        });
        return;
      }
      if (!fullSrc || fullSrc === previewSrc) {
        requestAnimationFrame(function () {
          if (token !== _lbLoadToken) return resolve(null);
          if (revealWhenReady) stage.classList.add('is-live');
          _fadeInLightboxFullImage(fullSrc || previewSrc, token, {
            width: lbImg.naturalWidth || 0,
            height: lbImg.naturalHeight || 0,
          });
          resolve({
            width: lbImg.naturalWidth || 0,
            height: lbImg.naturalHeight || 0,
          });
        });
        return;
      }
      var loader = new Image();
      loader.onload = function () {
        if (token !== _lbLoadToken) return resolve(null);
        var size = {
          width: loader.naturalWidth || loader.width || 0,
          height: loader.naturalHeight || loader.height || 0,
        };
        _fadeInLightboxFullImage(fullSrc, token, size, function () {
          if (revealWhenReady) stage.classList.add('is-live');
          resolve(size);
        });
      };
      loader.onerror = function () {
        if (revealWhenReady) stage.classList.add('is-live');
        resolve(null);
      };
      loader.src = fullSrc;
    });
  }

  function _loadLightboxFullImage(fullSrc, previewSrc) {
    var lbImg = $('#lbImg');
    var stage = $('#lbStage');
    if (!lbImg || !stage || !fullSrc || fullSrc === previewSrc) {
      if (lbImg) {
        _fadeInLightboxFullImage(fullSrc || previewSrc, _lbLoadToken, {
          width: lbImg.naturalWidth || 0,
          height: lbImg.naturalHeight || 0,
        });
      }
      return Promise.resolve(null);
    }
    var token = _lbLoadToken;
    return new Promise(function(resolve) {
      var loader = new Image();
      loader.onload = function() {
        if (token !== _lbLoadToken) return resolve(null);
        var size = {
          width: loader.naturalWidth || loader.width || 0,
          height: loader.naturalHeight || loader.height || 0,
        };
        _fadeInLightboxFullImage(fullSrc, token, size, function() {
          resolve(size);
        });
      };
      loader.onerror = function() { resolve(null); };
      loader.src = fullSrc;
    });
  }

  function _finalLightboxImageRect(size) {
    var w = Number(size && size.width || 0);
    var h = Number(size && size.height || 0);
    if (!w || !h) return null;
    var maxW = window.innerWidth * 0.95;
    var maxH = window.innerHeight * 0.90;
    var scale = Math.min(1, maxW / w, maxH / h);
    var finalW = w * scale;
    var finalH = h * scale;
    return {
      left: (window.innerWidth - finalW) / 2,
      top: (window.innerHeight - finalH) / 2,
      width: finalW,
      height: finalH,
      right: (window.innerWidth + finalW) / 2,
      bottom: (window.innerHeight + finalH) / 2,
    };
  }

  function _finalLightboxImageRectForAspect(size) {
    var w = Number(size && size.width || 0);
    var h = Number(size && size.height || 0);
    if (!w || !h) return null;
    var maxW = window.innerWidth * 0.95;
    var maxH = window.innerHeight * 0.90;
    var scale = Math.min(maxW / w, maxH / h);
    var finalW = w * scale;
    var finalH = h * scale;
    return {
      left: (window.innerWidth - finalW) / 2,
      top: (window.innerHeight - finalH) / 2,
      width: finalW,
      height: finalH,
      right: (window.innerWidth + finalW) / 2,
      bottom: (window.innerHeight + finalH) / 2,
    };
  }

  function _sourceImageSize(sourceEl) {
    var img = sourceEl && sourceEl.querySelector ? (sourceEl.querySelector('img') || sourceEl) : sourceEl;
    if (!img) return null;
    var width = Number(img.naturalWidth || img.width || 0);
    var height = Number(img.naturalHeight || img.height || 0);
    if (!width || !height) return null;
    return { width: width, height: height };
  }

  function _revealLightboxStage() {
    var overlay = $('#lightbox');
    var stage = $('#lbStage');
    if (stage) {
      stage.classList.add('is-live');
      stage.style.borderRadius = '';
    }
    _positionLightboxActions();
    if (overlay) overlay.classList.remove('lb-has-flight');
    document.querySelectorAll('.lb-flight').forEach(function(el) { el.remove(); });
  }

  function _positionLightboxActions() {
    var overlay = $('#lightbox');
    if (!overlay) return;
    overlay.style.removeProperty('--lb-action-right');
    overlay.style.removeProperty('--lb-action-bottom');
  }

  function _imageContentRect(img) {
    if (!img || !img.getBoundingClientRect) return null;
    var rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return rect;
    var naturalW = img.naturalWidth || 0;
    var naturalH = img.naturalHeight || 0;
    if (!naturalW || !naturalH) return rect;
    var fit = getComputedStyle(img).objectFit || 'fill';
    if (fit !== 'contain' && fit !== 'scale-down') return rect;
    var scale = Math.min(rect.width / naturalW, rect.height / naturalH);
    var contentW = naturalW * scale;
    var contentH = naturalH * scale;
    return {
      left: rect.left + (rect.width - contentW) / 2,
      top: rect.top + (rect.height - contentH) / 2,
      width: contentW,
      height: contentH,
      right: rect.left + (rect.width + contentW) / 2,
      bottom: rect.top + (rect.height + contentH) / 2,
    };
  }

  function _animateLightboxFromSource(sourceEl, previewSrc, targetRect, flightSrc, onArrived) {
    var overlay = $('#lightbox');
    var stage = $('#lbStage');
    if (!overlay || !stage || !sourceEl || !sourceEl.getBoundingClientRect) {
      if (overlay) overlay.classList.remove('lb-has-flight');
      if (stage) stage.classList.add('is-live');
      if (typeof onArrived === 'function') onArrived();
      return;
    }
    document.querySelectorAll('.lb-flight').forEach(function(el) { el.remove(); });
    overlay.classList.add('lb-has-flight');
    stage.classList.remove('is-live');
    var thumb = sourceEl.querySelector ? (sourceEl.querySelector('img') || sourceEl) : sourceEl;
    var thumbRadius = getComputedStyle(thumb).borderRadius || '18px';
    var fromRect = _imageContentRect(thumb) || thumb.getBoundingClientRect();
    if (!fromRect.width || !fromRect.height) {
      overlay.classList.remove('lb-has-flight');
      stage.classList.add('is-live');
      if (typeof onArrived === 'function') onArrived();
      return;
    }
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var lbImg = $('#lbImg');
        var toRect = targetRect || _imageContentRect(lbImg) || stage.getBoundingClientRect();
        if (!toRect.width || !toRect.height) {
          overlay.classList.remove('lb-has-flight');
          stage.classList.add('is-live');
          if (typeof onArrived === 'function') onArrived();
          return;
        }
        var flight = document.createElement('img');
        flight.className = 'lb-flight';
        flight.src = flightSrc || previewSrc || thumb.currentSrc || thumb.src || '';
        flight.alt = '';
        flight.style.left = fromRect.left + 'px';
        flight.style.top = fromRect.top + 'px';
        flight.style.width = fromRect.width + 'px';
        flight.style.height = fromRect.height + 'px';
        flight.style.borderRadius = thumbRadius;
        overlay.appendChild(flight);
        requestAnimationFrame(function () {
          flight.style.left = toRect.left + 'px';
          flight.style.top = toRect.top + 'px';
          flight.style.width = toRect.width + 'px';
          flight.style.height = toRect.height + 'px';
          flight.style.borderRadius = getComputedStyle(stage).borderRadius || '28px';
          flight.style.opacity = '1';
          flight.style.filter = 'blur(5px)';
        });
        setTimeout(function () {
          stage.classList.add('is-live');
          _positionLightboxActions();
          if (typeof onArrived === 'function') onArrived();
          requestAnimationFrame(function () {
            flight.style.opacity = '0';
            flight.style.filter = 'blur(5px)';
            setTimeout(function () {
              overlay.classList.remove('lb-has-flight');
              flight.remove();
            }, 180);
          });
        }, 380);
      });
    });
  }

  function _openLightbox(opts) {
    opts = opts || {};
    var overlay = $('#lightbox');
    if (!overlay) return;
    var fullSrc = opts.fullSrc || '';
    var previewSrc = opts.previewSrc || fullSrc;
    var expectedSize = opts.expectedSize || null;
    var mediaType = _mediaType(opts.mediaType, fullSrc);
    if (mediaType === 'video') {
      var video = $('#lbVideo');
      var stageVideo = $('#lbStage');
      _lbLoadToken += 1;
      _resetLightboxFullLayer();
      var lbImgVideo = $('#lbImg');
      if (lbImgVideo) {
        lbImgVideo.classList.remove('lb-visible', 'lb-preview', 'lb-ready');
        lbImgVideo.removeAttribute('src');
      }
      if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
      else overlay.classList.add('open');
      overlay.classList.remove('lb-has-flight');
      if (stageVideo) {
        stageVideo.classList.add('is-live', 'is-video');
        stageVideo.classList.remove('lb-video-playing');
        if (expectedSize) _lockLightboxDisplaySize(expectedSize);
      }
      if (video) {
        video.controls = false;
        video.playsInline = true;
        video.onloadedmetadata = function () {
          _lockLightboxVideoSize(video);
          _positionLightboxActions();
        };
        video.onloadeddata = function () {
          _syncLightboxVideoPlayingState();
        };
        video.onplay = _syncLightboxVideoPlayingState;
        video.onpause = _syncLightboxVideoPlayingState;
        video.onended = _syncLightboxVideoPlayingState;
        video.onclick = function () {
          if (video.paused || video.ended) {
            var clickPlay = video.play();
            if (clickPlay && clickPlay.catch) clickPlay.catch(function() { video.controls = true; });
          } else {
            video.pause();
          }
        };
        video.onerror = function () {
          if (stageVideo) stageVideo.classList.remove('lb-video-playing');
          _clearLightboxDisplaySize();
        };
        video.poster = previewSrc || '';
        video.src = fullSrc;
        video.classList.add('lb-video-visible');
        if (video.readyState >= 1) _lockLightboxVideoSize(video);
        var playPromise = video.play();
        if (playPromise && playPromise.catch) {
          playPromise.catch(function () {
            video.controls = true;
            _syncLightboxVideoPlayingState();
          });
        }
      }
      document.body.style.overflow = 'hidden';
      _positionLightboxActions();
      return;
    }
    _resetLightboxVideo();
    var stageImage = $('#lbStage');
    if (stageImage) stageImage.classList.remove('is-video');
    var hasSourceAnimation = !!(opts.sourceEl && opts.sourceEl.getBoundingClientRect);
    if (hasSourceAnimation) {
      var stage = $('#lbStage');
      overlay.classList.add('lb-has-flight');
      if (stage) stage.classList.remove('is-live');
    }
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
    else overlay.classList.add('open');
    var ready = _primeLightboxImage(fullSrc, previewSrc, !hasSourceAnimation, !hasSourceAnimation, expectedSize);
    if (hasSourceAnimation) {
      ready.then(function(size) {
        if (!$('#lightbox') || !$('#lightbox').classList.contains('open')) return;
        var targetRect = _lockLightboxDisplaySize(expectedSize) || _finalLightboxImageRectForAspect(_sourceImageSize(opts.sourceEl) || size) || _imageContentRect($('#lbImg'));
        _positionLightboxActions();
        _animateLightboxFromSource(opts.sourceEl, previewSrc, targetRect, null, function() {
          _loadLightboxFullImage(fullSrc, previewSrc);
        });
      }).catch(function() {
        _animateLightboxFromSource(opts.sourceEl, previewSrc, null, null, function() {
          _loadLightboxFullImage(fullSrc, previewSrc);
        });
      });
    } else {
      ready.then(function() {
        if ($('#lightbox') && $('#lightbox').classList.contains('open')) {
          _positionLightboxActions();
        }
      }).catch(function() {});
    }
    document.body.style.overflow = 'hidden';
  }

function renderLB(sourceEl) {
    if (window.__APP__ && Array.isArray(window.__APP__._lbItems)) lbItems = window.__APP__._lbItems;
    if (lbIdx < 0 || lbIdx >= lbItems.length) return;
    const h = _batchCover(lbItems[lbIdx]);
    _syncLightboxDownload(h.filename);
    _syncLightboxActions(h);
    $('#lbInfo').textContent = h.prompt || '—';
    $('#lbPrev').style.display = lbIdx > 0 ? '' : 'none';
    $('#lbNext').style.display = lbIdx < lbItems.length - 1 ? '' : 'none';
    _openLightbox({
      fullSrc: _lightboxImageUrl(h.filename),
      previewSrc: _lightboxPreviewUrl(h),
      mediaType: h.media_type || _mediaType(h),
      sourceEl: sourceEl,
      expectedSize: { width: h.width || 0, height: h.height || 0 },
    });
  }

  function _cleanupClosedLightbox() {
    var overlay = $('#lightbox');
    var stage = $('#lbStage');
    var lbImg = $('#lbImg');
    if (stage) stage.classList.remove('is-live');
    if (stage) stage.classList.remove('is-video');
    if (lbImg) {
      lbImg.classList.remove('lb-visible', 'lb-preview', 'lb-ready');
      lbImg.removeAttribute('src');
    }
    _resetLightboxVideo();
    _resetLightboxFullLayer();
    _clearLightboxDisplaySize();
    if (overlay) {
      overlay.classList.remove('lb-has-flight');
      overlay.style.removeProperty('--lb-action-right');
      overlay.style.removeProperty('--lb-action-bottom');
    }
    document.querySelectorAll('.lb-flight').forEach(function(el) { el.remove(); });
    _syncLightboxDownload('');
    _syncLightboxActions(null);
    lbIdx = -1;
  }

function closeLB() {
    var overlay = $('#lightbox');
    _lbLoadToken += 1;
    if (overlay) overlay.classList.remove('lb-has-flight');
    document.querySelectorAll('.lb-flight').forEach(function(el) { el.remove(); });
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, false, { afterClose: _cleanupClosedLightbox });
    else if (overlay) {
      overlay.classList.remove('open');
      setTimeout(_cleanupClosedLightbox, 280);
    } else {
      _cleanupClosedLightbox();
    }
    document.body.style.overflow = '';
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

function openJobLB(filename, label, sourceEl, mediaType) {
    // Show a single-item lightbox for a job image
    _syncLightboxDownload(filename);
    _syncLightboxActions(null);
    $('#lbInfo').textContent = label || '';
    $('#lbPrev').style.display = 'none';
    $('#lbNext').style.display = 'none';
    _openLightbox({
      fullSrc: _lightboxImageUrl(filename),
      previewSrc: sourceEl && sourceEl.querySelector ? ((sourceEl.querySelector('img') || {}).currentSrc || '') : '',
      mediaType: mediaType || _mediaType('', filename),
      sourceEl: sourceEl,
    });
  }

function openLB(idx, sourceEl) {
    if (window.__APP__ && Array.isArray(window.__APP__._lbItems)) lbItems = window.__APP__._lbItems;
    lbIdx = idx;
    renderLB(sourceEl);
  }

function openBatchLB(batchId, sourceEl) {
    var shared = window.__APP__ && window.__APP__._galleryBatchItems ? window.__APP__._galleryBatchItems : {};
    var items = _galleryBatchItems[String(batchId || '')] || shared[String(batchId || '')] || [];
    if (!items.length) return;
    lbItems = items;
    if (window.__APP__) window.__APP__._lbItems = items;
    lbIdx = 0;
    renderLB(sourceEl);
  }

	  function toggleLBFavorite() {
	    if (!_historyActionState(_lbCurrentItem).canFavorite) return;
	    if (!_lbCurrentItem) return;
	    var key = _lbCurrentItem.id || _lbCurrentItem.filename || _lbCurrentItem.original || _lbCurrentItem.prompt;
	    if (!key) return;
	    if (window.CW && CW.auth && typeof CW.auth.toggleHistoryFavorite === 'function' && _lbCurrentItem.id) {
	      var next = CW.auth.toggleHistoryFavorite(_lbCurrentItem.id, _lbCurrentItem);
	      _lbFavorites[key] = !!next;
	      _syncLightboxActions(_lbCurrentItem);
	      return;
	    }
	    _lbFavorites[key] = !_lbFavorites[key];
	    _syncLightboxActions(_lbCurrentItem);
	    if (window.CW && typeof window.CW.renderGallery === 'function') window.CW.renderGallery();
	    if (window.CW && CW.toast) CW.toast(_lbFavorites[key] ? '已收藏' : '已取消收藏', 'done');
	  }

  function toggleLBShare() {
    if (!_historyActionState(_lbCurrentItem).canShare) return;
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
    _clearHistoryDeleteFocus();
    id = String(id || '');
    var item = historyItems.find(function(h) { return String(h && h.id || '') === id; });
    var batchKey = _batchKey(item);
    var items = batchKey
      ? historyItems.filter(function(h) { return _batchKey(h) === batchKey; })
      : (item ? [item] : []);
    var deleteIds = items
      .filter(function(h) { return _canDeleteHistoryItem(h); })
      .map(function(h) { return String(h && h.id || ''); })
      .filter(Boolean);
    if (!deleteIds.length) {
      if (window.CW && CW.toast) CW.toast('只能删除自己生成的内容，管理员可删除全部历史', 'info');
      return;
    }
    var isBatchDelete = deleteIds.length > 1;
    if (!confirm(isBatchDelete ? `确认将这个批次的 ${deleteIds.length} 张图片移入回收站？` : '确认将这张图片移入回收站？')) return;
    // Mark card as deleting immediately
    var card = document.querySelector('[data-hist-idx][onclick*="' + id.slice(-6) + '"]') || document.querySelector('[onclick*="' + id.slice(-6) + '"]');
    if (card) { card.classList.add('deleting'); card.style.opacity = '0.4'; card.style.pointerEvents = 'none'; }
    try {
      var authHeaders = window.CW.auth.getAuthHeaders();
      var r = isBatchDelete
        ? await fetch(`${API}/api/history/batch-delete`, {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders),
          body: JSON.stringify({ ids: deleteIds }),
        })
        : await fetch(`${API}/api/history/${deleteIds[0]}`, { method: 'DELETE', headers: Object.assign({}, authHeaders) });
      if (!r.ok) throw new Error('删除失败');
      var deleted = new Set(deleteIds);
      for (var idx = historyItems.length - 1; idx >= 0; idx -= 1) {
        if (deleted.has(String(historyItems[idx] && historyItems[idx].id || ''))) historyItems.splice(idx, 1);
      }
      _pinnedHistoryIds = _pinnedHistoryIds.filter(function(pinId) { return !deleted.has(String(pinId)); });
      _filteredHistory = _filterHistory(historyItems);
      renderGallery();
      if (window.CW && typeof CW.loadWorkflows === 'function') {
        Promise.resolve(CW.loadWorkflows()).catch(function(err) {
          console.warn('refresh workflow previews after delete failed:', err && err.message ? err.message : err);
        });
      }
      _clearHistoryDeleteFocus();
      if (window.CW && CW.toast) CW.toast(isBatchDelete ? `已将 ${deleteIds.length} 张图片移入回收站` : '已移入回收站', 'done');
    } catch (e) {
      console.error('delHist:', e);
      if (card) { card.classList.remove('deleting'); card.style.opacity = ''; card.style.pointerEvents = ''; }
    }
  }

async function loadHistory() {
    if (_loadHistoryPromise) return _loadHistoryPromise;
    _loadHistoryPromise = (async function() {
    try {
      var prevVisibleCount = _histVisibleCount || _lastRenderedHistCount || 0;
      var authHeaders = window.CW.auth.getAuthHeaders();
      const user = window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser();
      const scope = user && user.role === 'admin' ? 'all' : 'gallery';
      const r = await fetch(`${API}/api/history?scope=${scope}&limit=${HISTORY_FETCH_LIMIT}`, { headers: Object.assign({}, authHeaders) });
      const d = await _historyJsonOrThrow(r, '加载历史');
      var nextItems = _sortHistoryItems(d.data || []);
      var serverIds = new Set(nextItems.map(function(item) { return String(item && item.id || ''); }));
      _pinnedHistoryIds = _pinnedHistoryIds.filter(function(id) {
        if (serverIds.has(String(id))) return false;
        if (_optimisticHistoryById[id]) {
          nextItems.unshift(_optimisticHistoryById[id]);
          return true;
        }
        return false;
      });
      historyItems.length = 0;
      Array.prototype.push.apply(historyItems, _applyPinnedHistoryOrder(nextItems));
      _lastGalleryHash = '';
      _populateFilterOptions();
      _syncOwnerFilterButtons();
      _syncTypeFilterButtons();
      var el;
      el = document.getElementById("gfStyle");
      _galleryFilters.style = el ? el.value.toLowerCase() : "";
      _filteredHistory = _applyPinnedHistoryOrder(_filterHistory(historyItems));
      var filteredArr = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
      _histVisibleCount = prevVisibleCount > 0
        ? Math.min(Math.max(prevVisibleCount, _lastRenderedHistCount || 0), filteredArr.length)
        : 0;
      renderGallery();
    } catch (e) {
      console.error('loadHistory:', e);
    }
    })();
    return _loadHistoryPromise.finally(function() {
      _loadHistoryPromise = null;
    });
  }


function applyFilters() {
    _syncOwnerFilterButtons();
    _syncTypeFilterButtons();
    var el;
    el = document.getElementById("gfStyle");
    _galleryFilters.style = el ? el.value.toLowerCase() : "";
    _filteredHistory = _filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = "";
    renderGallery();
  }

function clearFilters() {
    _galleryFilters = { owner: "all", type: "", style: "" };
    _syncOwnerFilterButtons();
    _syncTypeFilterButtons();
    var el;
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
  window.CW.openBatchLB = openBatchLB;
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
      const r = await fetch(`${API}/api/history?scope=${scope}&limit=${HISTORY_FETCH_LIMIT}`, { headers: Object.assign({}, authHeaders) });
      const d = await _historyJsonOrThrow(r, '加载历史');
      var nextItems = _sortHistoryItems(d.data || []);
      var serverIds = new Set(nextItems.map(function(item) { return String(item && item.id || ''); }));
      _pinnedHistoryIds = _pinnedHistoryIds.filter(function(id) { return !serverIds.has(String(id)); });
      historyItems.length = 0;
      Array.prototype.push.apply(historyItems, _applyPinnedHistoryOrder(nextItems));
    } catch (e) { console.error("loadHistoryNoRender:", e); }
  }
	  window.CW.loadHistoryNoRender = loadHistoryNoRender;
	  window.CW.renderGallery = renderGallery;
	  window.CW.forceGalleryRerender = function() {
	    _lastGalleryHash = '';
	    renderGallery();
  };
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
