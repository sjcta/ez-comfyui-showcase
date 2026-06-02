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
  var _galleryFilters = { owner: 'all', type: '', style: '' };
  var _renderTimer = null;
  var _cleanupTimer = null;
  var _galleryBatchItems = {};

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
    if (item.thumb) return API + '/api/thumbs/' + item.thumb;
    return item.filename ? API + '/api/images/' + item.filename : '';
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

  function _videoPosterHtml() {
    return '<div class="gi-video-poster" aria-hidden="true">' + (window.CW.icon ? CW.icon('play') : '▶') + '</div>';
  }

  function _infoVideoTagHtml(item) {
    if (!_isVideoItem(item)) return '';
    return '<span class="gi-video-chip" title="视频" aria-label="视频">' + (window.CW.icon ? CW.icon('video', 16) : '▣') + '</span>';
  }

  function _videoPreviewSrc(filename) {
    return filename ? API + '/api/images/' + filename + '#t=0.1' : '';
  }

  function _videoPreviewHtml(filename, thumb) {
    if (thumb) return '<img class="gi-video-thumb" src="' + API + '/api/thumbs/' + thumb + '" loading="lazy" alt="">' + _videoPosterHtml();
    var src = _videoPreviewSrc(filename);
    if (!src) return _videoPosterHtml();
    return '<video class="gi-video-preview" src="' + escA(src) + '" muted playsinline preload="metadata"></video>' + _videoPosterHtml();
  }

  function _neutralJobStatusMessage(value) {
    var text = String(value || '');
    var image = '图' + '片';
    var picture = '图' + '像';
    return text
      .replace(new RegExp('正在拉取' + image, 'g'), '正在保存结果')
      .replace(new RegExp('拉取' + image + '超时', 'g'), '保存结果超时')
      .replace(new RegExp(image + '校验中', 'g'), '内容校验中')
      .replace(new RegExp(image + '保存中', 'g'), '结果保存中')
      .replace(new RegExp('保存' + image, 'g'), '保存结果')
      .replace(new RegExp('解码' + picture, 'g'), '解码内容')
      .replace(new RegExp('编码' + picture, 'g'), '编码内容')
      .replace(new RegExp(picture + '缩放', 'g'), '缩放内容')
      .replace(new RegExp('合成' + picture, 'g'), '合成内容')
      .replace(new RegExp('保存' + picture, 'g'), '保存结果');
  }

  function _mediaPreviewHtml(item) {
    if (_isVideoItem(item)) return _videoPreviewHtml(item.filename, item.thumb);
    var src = _historyImageSrc(item);
    if (src) return '<img src="' + escA(src) + '" loading="lazy" alt="">';
    return '';
  }

  function _batchStackImages(entry, cover) {
    if (!(entry && entry.__isBatch && Array.isArray(entry.items))) return '';
    var extras = entry.items.filter(function(item) {
      return item && item !== cover && (item.thumb || item.filename);
    }).slice(0, 2);
    return extras.map(function(item, idx) {
      var src = _historyImageSrc(item);
      return src ? '<img class="gi-batch-layer gi-batch-layer-' + (idx + 1) + '" src="' + escA(src) + '" loading="lazy" alt="">' : '';
    }).join('');
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
        map[key] = { __isBatch: true, id: 'batch:' + key, batch_id: key, batch_count: Number(item.batch_count || 1), cover: item, items: [] };
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

  /**
   * CardManager class
   * @param {Element} galleryEl - The gallery container element
   */
  function CardManager(galleryEl) {
    this.galleryEl = galleryEl;
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

  function _histKey(h) {
    return String((h && (h.id || h.filename || h.thumb)) || '');
  }

  function _historyActionState(item) {
    if (window.CW && CW.auth && typeof CW.auth.getHistoryActionState === 'function') {
      return CW.auth.getHistoryActionState(item);
    }
    return {
      hasUser: false,
      canFavorite: false,
      canShare: false,
      canHide: false,
      canDelete: false,
      isFavorited: false
    };
  }

  function _isHistoryFavorited(item) {
    return !!_historyActionState(item).isFavorited;
  }

  function _favoriteBadgeHtml(item) {
    var actionState = _historyActionState(item);
    var isFav = !!actionState.isFavorited;
    var id = item && item.id ? String(item.id) : '';
    if (!actionState.canFavorite) return '';
    if (!id || !(window.CW && CW.auth && typeof CW.auth.toggleHistoryFavorite === 'function')) return '';
    return '<button class="gi-fav-btn' + (isFav ? ' is-active' : '') + '" type="button" title="' + (isFav ? '取消收藏' : '收藏') + '" aria-label="' + (isFav ? '取消收藏' : '收藏') + '" onclick="event.stopPropagation();CW.auth.toggleHistoryFavorite(\'' + escA(id) + '\')"><svg class="cw-icon" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21.2 10.7 20C5.8 15.6 2.5 12.6 2.5 8.8 2.5 5.8 4.8 3.5 7.8 3.5c1.7 0 3.3.8 4.2 2.1.9-1.3 2.5-2.1 4.2-2.1 3 0 5.3 2.3 5.3 5.3 0 3.8-3.3 6.8-8.2 11.2L12 21.2Z"/></svg></button>';
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
      .replace(/CW\.openLB\(\d+(, this)?\)/g, 'CW.openLB(#)');
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
    var cm = window.CW && window.CW.cardManager;
    if (cm && typeof cm.patchJobCard === 'function') cm.patchJobCard(job);
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
  function _jobTimerTs(j) {
    return j && (j.generating_at || 0);
  }

  function _jobShowsTimer(j) {
    var status = j && j.status;
    return status === 'generating' || status === 'downloading' || status === 'checking';
  }

  function _jobProgressPct(j) {
    var pct = Number(j && j.progress ? j.progress.pct : 0);
    if (!isFinite(pct)) pct = 0;
    return Math.max(0, Math.min(100, pct));
  }

  function _jobProgressClass(j) {
    var status = j && j.status;
    return _jobProgressPct(j) <= 0 && (status === 'generating' || status === 'submitting') ? ' progress-unknown' : '';
  }

  function _jobTimerHtml(j) {
    if (!_jobShowsTimer(j)) return '';
    var ts = _jobTimerTs(j);
    if (!ts) return '';
    var estimateLabel = j.estimated_duration_label || '';
    var timerText = window.CW.formatJobElapsedWithEstimate
      ? window.CW.formatJobElapsedWithEstimate(ts, estimateLabel)
      : (window.CW.formatElapsed ? window.CW.formatElapsed(ts) : '');
    return '<div class="gi-timer-row"><span class="gi-timer" data-ts="' + escA(ts) + '" data-estimate-label="' + escA(estimateLabel) + '">' + escH(timerText) + '</span></div>';
  }

  CardManager.prototype._renderJobCard = function (j) {
    var label = j.prompt_preview || (j.workflow ? j.workflow.replace('.json', '') : '') || '...';
    var statusMsg = _neutralJobStatusMessage(j.message || j.status);
    var hasImage = !!j.image;
    var isVideo = _mediaType(j.media_type, j.image) === 'video';
    var checkingPreview = j.status === 'checking' && (j.pending_thumb || j.pending_image);
    var imgSrc = hasImage && !isVideo ? API + '/api/images/' + j.image : '';
    var checkingImgSrc = checkingPreview
      ? (j.pending_thumb ? API + '/api/thumbs/' + j.pending_thumb : API + '/api/images/' + j.pending_image)
      : '';
    var checkingSensitiveCls = j.status === 'checking' ? ' gi-sensitive' : '';

    // ── Image area ──
    var imgHtml = '';
    if (hasImage) {
      imgHtml = imgSrc ? '<img src="' + imgSrc + '" loading="lazy" alt="">' : _videoPreviewHtml(j.image, j.thumb);
    } else {
      if (checkingPreview) {
        imgHtml = '<img class="job-checking-preview" src="' + checkingImgSrc + '" loading="lazy" alt="">';
      }
      if (j.status === 'generating' || j.status === 'preparing' || j.status === 'starting_comfyui' || j.status === 'submitting' || j.status === 'downloading' || j.status === 'checking') {
        imgHtml += '<div class="job-spinner"></div>';
      }
      if (j.status === 'queued') {
        imgHtml += '<div class="job-status-text queued">排队中</div>';
      } else if (j.status === 'generating') {
        imgHtml += '<div class="job-status-text generating">' + escH(statusMsg) + '</div>';
      } else if (j.status === 'downloading') {
        imgHtml += '<div class="job-status-text downloading">' + escH(statusMsg || '正在保存结果...') + '</div>';
      } else if (j.status === 'checking') {
        imgHtml += '<div class="job-status-text checking">' + escH(statusMsg || '内容校验中') + '</div>';
      } else {
        imgHtml += '<div class="job-status-text ' + escH(j.status) + '">' + escH(statusMsg) + '</div>';
      }
      imgHtml += _jobTimerHtml(j);
    }

    // ── Badge ──
    var wfMeta = (A._wfMeta || {})[j.workflow] || {};
    var wfLabel = window.CW && CW.workflowDisplayName
      ? CW.workflowDisplayName(j.workflow || '', wfMeta)
      : (String(wfMeta.name || '').trim() || (j.workflow ? j.workflow.replace(/\.json$/i, '') : ''));
    var wfTag = window.CW.wfTag ? window.CW.wfTag(j.workflow || '', wfMeta.tags) : '';
    var tagHtml = wfTag ? '<div class="gi-type-badge ' + wfTag.cls + '">' + wfTag.text + '</div>' : '';
    var instBadge = j.instance ? '<div class="gi-inst-badge">#' + escH(j.instance) + '</div>' : '';

    // ── Type class for border color ──
    var _jTag1 = window.CW.wfTag ? window.CW.wfTag(j.workflow || '', wfMeta.tags) : '';
    var _jCls1 = _jTag1 ? _jTag1.cls : '';
    var jTypeCls = _jCls1 ? 'gi-type-' + _jCls1.replace('wf-tag-', '') : '';

    return '<div class="gi job-card ' + escH(j.status) + ' ' + jTypeCls + '" data-job-id="' + escA(j.id) + '">' +
      '<div class="gi-img ' + (hasImage ? '' : 'job-placeholder') + checkingSensitiveCls + '">' +
      imgHtml +
      (j.status === 'error' ? '<div class="gi-retry-row"><button class="btn-retry" onclick="event.stopPropagation();CW.retryJob(\'' + escA(j.id) + '\')">重新尝试</button></div>' : '') +
      '<button class="gi-del" onclick="event.stopPropagation();CW.cancelJob(\'' + escA(j.id) + '\')" title="' + (j.status === 'generating' ? '取消' : '删除') + '"><svg class="cw-icon" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-trash-2"/></svg></button>' +
      (tagHtml || instBadge ? '<div class="gi-tags-row">' + tagHtml + instBadge + '</div>' : '') +
      '</div>' +
      '<div class="gi-info" onclick="event.stopPropagation();CW.restoreJob(\'' + escA(j.id) + '\')">' +
      (j.status === 'generating' || j.status === 'submitting' ? '<div class="gi-progress-top' + _jobProgressClass(j) + '"><div class="gi-progress-fill" style="width:' + _jobProgressPct(j) + '%"></div></div>' : '') +
      (wfLabel ? '<div class="gi-wf-label" title="' + escA(wfLabel) + '">' + escH(wfLabel) + '</div>' : '') +
      '<div class="gi-prompt" title="' + escA(j.prompt_preview || label) + '">' + escH(j.prompt_preview || label) + '</div>' +
      (j.status !== 'generating' && j.status !== 'submitting' ? '<div class="gi-meta">' +
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
    var entry = h;
    h = _batchCover(entry);
    var isBatch = !!(entry && entry.__isBatch);
    var batchCount = isBatch ? Number(entry.batch_count || (entry.items && entry.items.length) || 1) : 1;
    var user = window.CW.auth && window.CW.auth.getCurrentUser ? window.CW.auth.getCurrentUser() : null;
    var canEdit = !!user;
    var canDelete = _batchCanDelete(entry, h);
    var deleteTargetId = _batchDeleteTargetId(entry, h);
    var deleteTitle = isBatch ? '删除本批次' : '删除';
    var batchStackImages = _batchStackImages(entry, h);
    var mainText1 = _historyItemType(h);
    var mainCls1 = _typeClass(mainText1, h.workflow);
    var displayPrompt = _historyDisplayPrompt(h);
    var sensitiveCls = _isSensitivePreview(h, displayPrompt) ? ' gi-sensitive' : '';
    var tagBadge = mainText1 ? '<div class="gi-type-badge ' + mainCls1 + '">' + mainText1 + '</div>' : '';
    var typeCls1 = mainCls1 ? 'gi-type-' + mainCls1.replace('wf-tag-', '') : '';
    var histKey = _histKey(h);
    var entryKey = _galleryEntryKey(entry);
    var openAction = isBatch ? "CW.openBatchLB('" + escA(entry.batch_id) + "', this)" : 'CW.openLB(' + i + ', this)';
    var batchBadge = isBatch ? '<div class="gi-batch-badge">×' + batchCount + '</div>' : '';
    var videoTag = _infoVideoTagHtml(h);

		    return '<div class="gi ' + typeCls1 + (isBatch ? ' gi-batch-stack' : '') + '" data-wf="' + escA(h.workflow || '') + '" data-hist-id="' + escA(entryKey || histKey) + '" data-hist-idx="' + i + '" data-favorited="' + (_isHistoryFavorited(h) ? '1' : '0') + '" onclick="CW.fillFormFromHistory(' + i + ', \'' + escA(histKey) + '\')">' +
	      '<div class="gi-img' + sensitiveCls + '" onclick="event.stopPropagation();' + openAction + '">' +
	      batchStackImages +
	      _mediaPreviewHtml(h) +
	      _favoriteBadgeHtml(h) +
	      tagBadge +
	      (canDelete && deleteTargetId ? '<button class="gi-del" onclick="event.stopPropagation();CW.delHist(\'' + escA(deleteTargetId) + '\')" title="' + deleteTitle + '"><svg class="cw-icon" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-trash-2"/></svg></button>' : '') +
	      '</div>' +
	      '<div class="gi-info">' +
	      '<div class="gi-info-actions">' + videoTag + batchBadge +
		      (canEdit ? '<button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(' + i + ', \'' + escA(histKey) + '\')" title="复刻出图" aria-label="复刻出图">' + (window.CW.icon ? CW.icon('copy') : '') + '</button>' : '') +
	      '</div>' +
	      '<div class="gi-prompt" title="' + escA(displayPrompt) + '">' + escH(displayPrompt) + '</div>' +
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
      var label = _neutralJobStatusMessage(job.message || (job.status === 'generating' ? '出图中' : job.status === 'history' ? '' : job.status));
      st.textContent = label;
      st.className = 'job-status-text ' + job.status;
    }

    // ── Downloading state: hide progress bar ──
    if (job.status === 'downloading') {
      var bar = card.querySelector('.gi-progress-top');
      if (bar) bar.style.display = 'none';
    } else {
      var bar2 = card.querySelector('.gi-progress-top');
      if (bar2) {
        bar2.style.display = '';
        bar2.classList.toggle('progress-unknown', _jobProgressPct(job) <= 0 && (job.status === 'generating' || job.status === 'submitting'));
      }
    }

    // ── Progress bar ──
    var bar3 = card.querySelector('.gi-progress-fill');
    if (bar3) bar3.style.width = _jobProgressPct(job) + '%';

    // ── Timer ──
    var timerEl = card.querySelector('.gi-timer');
    if (_jobShowsTimer(job)) {
      var timerTs = _jobTimerTs(job);
      if (timerTs) {
        if (!timerEl) {
          var imgBox = card.querySelector('.gi-img');
          if (imgBox) {
            var wrap = document.createElement('template');
            wrap.innerHTML = _jobTimerHtml(job);
            var timerRowNew = wrap.content.firstElementChild;
            var statusText = imgBox.querySelector('.job-status-text');
            if (timerRowNew) {
              if (statusText && statusText.nextSibling) imgBox.insertBefore(timerRowNew, statusText.nextSibling);
              else if (statusText) imgBox.appendChild(timerRowNew);
              else imgBox.insertBefore(timerRowNew, imgBox.querySelector('.gi-del'));
              timerEl = card.querySelector('.gi-timer');
            }
          }
        }
        if (timerEl) {
          timerEl.dataset.ts = timerTs;
          timerEl.dataset.estimateLabel = job.estimated_duration_label || timerEl.dataset.estimateLabel || '';
          if (window.CW.formatJobElapsedWithEstimate) {
            timerEl.textContent = window.CW.formatJobElapsedWithEstimate(timerTs, timerEl.dataset.estimateLabel);
          } else if (window.CW.formatElapsed) {
            timerEl.textContent = window.CW.formatElapsed(timerTs);
          }
        }
      }
    } else if (timerEl) {
      var timerRow = timerEl.closest ? timerEl.closest('.gi-timer-row') : null;
      if (timerRow && timerRow.parentNode) timerRow.parentNode.removeChild(timerRow);
    }
    _ensureJobCardOrder();
  };

  /**
   * Handle job done: swap spinner to image, trigger auto-cleanup
   */
  CardManager.prototype.onJobDone = function (job) {
    if (!job.image) return;
    if (window.CW.refreshWorkflowPreviewFromJob) window.CW.refreshWorkflowPreviewFromJob(job);
    var card = document.querySelector('[data-job-id="' + job.id + '"]');
    var cleanupDelay = 980;
    if (card) {
      var frontHtml = card.innerHTML;
      var wfMeta = ((A._wfMeta || {})[job.workflow] || {});
      var wfTag = window.CW.wfTag ? window.CW.wfTag(job.workflow || '', wfMeta.tags) : '';
      var tagBadge = wfTag ? '<div class="gi-type-badge ' + wfTag.cls + '">' + wfTag.text + '</div>' : '';
      var displayPrompt = job.prompt_preview || (job.workflow ? job.workflow.replace('.json', '') : '出图完成');
      var protectionStatus = String(job.protection_status || '').toLowerCase();
      var sensitiveCls = (protectionStatus === 'protected' || protectionStatus === 'error') ? ' gi-sensitive' : '';
      var isVideo = _mediaType(job.media_type, job.image) === 'video';
      var mediaHtml = isVideo
        ? _videoPreviewHtml(job.image, job.thumb)
        : '<img src="' + API + '/api/images/' + job.image + '" loading="lazy" alt="">';
      var completeHtml =
        '<div class="gi-img' + sensitiveCls + '" onclick="event.stopPropagation();CW.openJobLB(\'' + escA(job.image) + '\',\'' + escA(job.prompt_preview || '') + '\', this, \'' + escA(job.media_type || '') + '\')">' +
          mediaHtml +
          tagBadge +
        '</div>' +
        '<div class="gi-info">' +
          '<div class="gi-prompt" title="' + escA(displayPrompt) + '">' + escH(displayPrompt) + '</div>' +
          '<div class="gi-meta"><span>' + (window.CW.icon ? CW.icon('clock') : '') + ' 刚刚</span>' +
            '<div class="gi-meta-row">' +
              '<span>' + (window.CW.icon ? CW.icon('timer') : '') + ' ' + _fmtElapsed(job.elapsed || 0) + '</span>' +
              '<span>' + (window.CW.icon ? CW.icon('ruler') : '') + ' ' + (job.width && job.height ? job.width + '×' + job.height : '—') + '</span>' +
            '</div></div>' +
          (job.seed ? '<div class="gi-seed">' + (window.CW.icon ? CW.icon('sprout') : '') + ' ' + escH(String(job.seed)) + '</div>' : '') +
        '</div>';
      card.className = 'gi job-card done completing job-card-complete-blurfade';
      card.innerHTML =
        '<div class="job-card-complete-transition">' +
          '<div class="job-card-complete-old">' + frontHtml + '</div>' +
          '<div class="job-card-complete-new">' + completeHtml + '</div>' +
        '</div>';
      setTimeout(function() {
        if (!card.parentNode) return;
        card.classList.remove('completing', 'job-card-complete-blurfade');
        card.innerHTML = completeHtml;
      }, cleanupDelay);
    }
    setTimeout(function() {
      delete jobs[job.id];
      var historyPromise = window.CW.loadHistory ? window.CW.loadHistory() : null;
      Promise.resolve(historyPromise).then(function() {
        if (window.CW.loadWorkflows) return window.CW.loadWorkflows();
        return null;
      }).catch(function(e) {
        console.warn('refresh workflow previews failed:', e && e.message ? e.message : e);
      });
    }, cleanupDelay);
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
      var initialItems = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
      _histVisibleCount = Math.min(_batchSize(), initialItems.length);
    }

    // Active jobs (queued, preparing, starting_comfyui, submitting, generating, downloading)
    var activeJobs = Object.values(jobs).filter(_isJobVisibleToCurrentUser).filter(function (j) { return j.status !== 'done' && j.status !== 'error'; });
    // Error jobs (kept briefly for visibility)
    var errorJobs = Object.values(jobs).filter(_isJobVisibleToCurrentUser).filter(function (j) { return j.status === 'error'; });
    var jobCards = _sortJobCards(activeJobs.concat(errorJobs));

    // ── Hash check ──
    var hash = _galleryHash(jobs, historyItems);
    if (hash === _lastGalleryHash) return;
    _lastGalleryHash = hash;

    var html = '';

    // ── Render job cards ──
    for (var ci = 0; ci < jobCards.length; ci++) {
      html += this._renderJobCard(jobCards[ci]);
    }

    // ── History items ──
    var filteredArr = _hasActiveGalleryFilters() ? _filteredHistory : historyItems;
    var displayArr = _groupHistoryForGallery(filteredArr);
    var histCountEl = $('#histCount');
    if (histCountEl) histCountEl.textContent = String(filteredArr.length) + ' / ' + String(historyItems.length);
    // Update lbItems for lightbox (used by history.js)
    if (window.__APP__) window.__APP__._lbItems = displayArr;
    _histVisibleCount = Math.min(Math.max(_histVisibleCount, _batchSize()), displayArr.length);
    var visibleItems = displayArr.slice(0, _histVisibleCount);
    for (var hi = 0; hi < visibleItems.length; hi++) {
      html += this._renderHistCard(visibleItems[hi], hi);
    }

    if (displayArr.length > _histVisibleCount) {
      html += '<div class="masonry-sentinel" id="masonrySentinel"></div>';
    }

    if (jobCards.length === 0 && displayArr.length === 0) {
      html = '<div class="empty-hint"><div class="eh-icon">' + (window.CW.icon ? CW.icon('image', 32) : '') + '</div><p>暂无历史</p><p class="hint-sub">出图后自动出现在这里</p></div>';
    }

    try {
      _patchGalleryHTML(gallery, html);
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
        if (!_isJobVisibleToCurrentUser(j)) continue;
        s += j.id + j.status + '|';
      }
    }
    return s + '::' + histArr.length;
  }

  function _canDeleteHistoryItem(h) {
    return !!_historyActionState(h).canDelete;
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

  function _setHistoryOwnerFilter(value) {
    _galleryFilters.owner = value || 'all';
    _syncOwnerFilterButtons();
    if (window.CW.cardManager) window.CW.cardManager.applyFilters();
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
    var current = document.querySelector('.gf-type-current');
    if (current) current.textContent = val || '全部类型';
  }

  function _closeHistoryTypeMenus() {
    document.querySelectorAll('.gf-type-segment.open').forEach(function(menu) {
      menu.classList.remove('open');
      var trigger = menu.querySelector('.gf-type-trigger');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  }

  function _toggleHistoryTypeMenu(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    var trigger = e && e.currentTarget ? e.currentTarget : null;
    var wrap = trigger && trigger.closest ? trigger.closest('.gf-type-segment') : null;
    if (!wrap) return;
    var open = wrap.classList.contains('open');
    _closeHistoryTypeMenus();
    wrap.classList.toggle('open', !open);
    trigger.setAttribute('aria-expanded', !open ? 'true' : 'false');
  }

  function _ensureHistoryTypeMenuCloseBound() {
    var root = document.documentElement;
    if (!root || root.dataset.historyTypeMenuBound === '1') return;
    root.dataset.historyTypeMenuBound = '1';
    document.addEventListener('click', function(e) {
      if (e.target && e.target.closest && e.target.closest('.gf-type-segment')) return;
      if (window.CW && CW.closeHistoryTypeMenus) CW.closeHistoryTypeMenus();
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && window.CW && CW.closeHistoryTypeMenus) {
        CW.closeHistoryTypeMenus();
      }
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
    _ensureHistoryTypeMenuCloseBound();
    var options = _historyTypeOptions();
    if (_galleryFilters.type && options.indexOf(_galleryFilters.type) < 0) {
      _galleryFilters.type = '';
    }
    var currentLabel = _galleryFilters.type || '全部类型';
    var caret = window.CW && CW.icon ? CW.icon('chevron-right', 12) : '';
    var html = '<button class="gf-type-trigger" type="button" aria-haspopup="menu" aria-expanded="false" onclick="CW.toggleHistoryTypeMenu(event)"><span class="gf-type-current">' + escH(currentLabel) + '</span><span class="gf-type-caret">' + caret + '</span></button>';
    html += '<div class="gf-type-menu" role="menu">';
    html += '<button class="gf-segment-btn" type="button" role="menuitemradio" data-type-filter="" onclick="CW.setHistoryTypeFilter(this.dataset.typeFilter)">全部类型</button>';
    options.forEach(function(t) {
      html += '<button class="gf-segment-btn" type="button" role="menuitemradio" data-type-filter="' + escA(t) + '" onclick="CW.setHistoryTypeFilter(this.dataset.typeFilter)">' + escH(t) + '</button>';
    });
    html += '</div>';
    wrap.innerHTML = html;
  }

  function _setHistoryTypeFilter(value) {
    _galleryFilters.type = value || '';
    _syncTypeFilterButtons();
    _closeHistoryTypeMenus();
    if (window.CW.cardManager) window.CW.cardManager.applyFilters();
  }

  function _hasActiveGalleryFilters() {
    return (_galleryFilters.owner && _galleryFilters.owner !== 'all') ||
      !!_galleryFilters.type ||
      !!_galleryFilters.style;
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
        var activeItems = _groupHistoryForGallery(_hasActiveGalleryFilters() ? _filteredHistory : historyItems);
        if (entries[0].isIntersecting && _histVisibleCount < activeItems.length) {
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), activeItems.length);
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
    var filteredArr2 = _groupHistoryForGallery(_hasActiveGalleryFilters() ? _filteredHistory : historyItems);
    var newCount = Math.min(_histVisibleCount, filteredArr2.length);
    if (newCount <= prevCount) {
      if (sentinel) _attachSentinel();
      return;
    }

    var fragment = '';
    for (var i = prevCount; i < newCount; i++) {
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

    if (sentinel && _histVisibleCount < filteredArr2.length) {
      requestAnimationFrame(function () {
        var rect = sentinel.getBoundingClientRect();
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
    var canEdit = !!(window.CW && window.CW.auth && window.CW.auth.getCurrentUser && window.CW.auth.getCurrentUser());
    var canDelete = _batchCanDelete(entry, h);
    var deleteTargetId = _batchDeleteTargetId(entry, h);
    var deleteTitle = isBatch ? '删除本批次' : '删除';
    var batchStackImages = _batchStackImages(entry, h);
    var mainText2 = _historyItemType(h);
    var mainCls2 = _typeClass(mainText2, h.workflow);
    var displayPrompt = _historyDisplayPrompt(h);
    var sensitiveCls = _isSensitivePreview(h, displayPrompt) ? ' gi-sensitive' : '';
    var tagBadge = mainText2 ? '<div class="gi-type-badge ' + mainCls2 + '">' + mainText2 + '</div>' : '';
    var typeCls2 = mainCls2 ? 'gi-type-' + mainCls2.replace('wf-tag-', '') : '';
    var histKey = _histKey(h);
    var entryKey = _galleryEntryKey(entry);
    var openAction = isBatch ? "CW.openBatchLB('" + escA(entry.batch_id) + "', this)" : 'CW.openLB(' + i + ', this)';
    var batchBadge = isBatch ? '<div class="gi-batch-badge">×' + batchCount + '</div>' : '';
    var videoTag = _infoVideoTagHtml(h);
    return '<div class="gi ' + typeCls2 + (isBatch ? ' gi-batch-stack' : '') + '" data-wf="' + escA(h.workflow || '') + '" data-hist-id="' + escA(entryKey || histKey) + '" data-hist-idx="' + i + '" data-favorited="' + (_isHistoryFavorited(h) ? '1' : '0') + '" onclick="CW.fillFormFromHistory(' + i + ', \'' + escA(histKey) + '\')">' +
	      '<div class="gi-img lazy-img' + sensitiveCls + '" onclick="event.stopPropagation();' + openAction + '">' +
	      batchStackImages +
      _mediaPreviewHtml(h) +
      _favoriteBadgeHtml(h) +
      tagBadge +
	      (canDelete && deleteTargetId ? '<button class="gi-del" onclick="event.stopPropagation();CW.delHist(\'' + escA(deleteTargetId) + '\')" title="' + deleteTitle + '"><svg class="cw-icon" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-trash-2"/></svg></button>' : '') +
	      '</div>' +
	      '<div class="gi-info">' +
	      '<div class="gi-info-actions">' + videoTag + batchBadge +
	      (canEdit ? '<button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(' + i + ', \'' + escA(histKey) + '\')" title="复刻出图" aria-label="复刻出图">' + (window.CW.icon ? CW.icon('copy') : '') + '</button>' : '') +
	      '</div>' +
	      '<div class="gi-prompt" title="' + escA(displayPrompt) + '">' + escH(displayPrompt) + '</div>' +
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
    var styles = new Set();
    for (var k = 0; k < historyItems.length; k++) {
      var j = historyItems[k];
      try {
        var pObj = JSON.parse(j.prompt || '{}');
        if (pObj.style && typeof pObj.style === 'string') {
          var s = pObj.style.trim();
          if (s.length > 0) styles.add(s);
        }
      } catch (e) {}
    }
    _syncTypeFilterButtons();
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
      if (_galleryFilters.owner && _galleryFilters.owner !== 'all') {
        var uid = _currentUserId();
        var owner = j && j.user_id ? String(j.user_id) : '';
        if (_galleryFilters.owner === 'mine' && (!uid || owner !== uid)) return false;
        if (_galleryFilters.owner === 'favorite' && !_isHistoryFavorited(j)) return false;
        if (_galleryFilters.owner === 'other' && uid && owner === uid) return false;
      }
      if (_galleryFilters.type) {
        if (_historyItemType(j) !== _galleryFilters.type) return false;
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
      return true;
    });
  };

  CardManager.prototype.applyFilters = function () {
    _syncOwnerFilterButtons();
    _syncTypeFilterButtons();
    var el;
    el = document.getElementById('gfStyle');
    _galleryFilters.style = el ? el.value.toLowerCase() : '';
    _filteredHistory = this.filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = '';
    this.renderGallery();
  };

  CardManager.prototype.clearFilters = function () {
    _galleryFilters = { owner: 'all', type: '', style: '' };
    _syncOwnerFilterButtons();
    _syncTypeFilterButtons();
    var el;
    el = document.getElementById('gfStyle');
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
  if (!window.CW.setHistoryOwnerFilter) window.CW.setHistoryOwnerFilter = _setHistoryOwnerFilter;
  if (!window.CW.setHistoryTypeFilter) window.CW.setHistoryTypeFilter = _setHistoryTypeFilter;
  if (!window.CW.closeHistoryTypeMenus) window.CW.closeHistoryTypeMenus = _closeHistoryTypeMenus;
  if (!window.CW.toggleHistoryTypeMenu) window.CW.toggleHistoryTypeMenu = _toggleHistoryTypeMenu;
  if (!window.CW.refreshHistoryTypeFilters) {
    window.CW.refreshHistoryTypeFilters = function() {
      _syncTypeFilterButtons();
      if (window.CW.cardManager) window.CW.cardManager.applyFilters();
    };
  }

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
