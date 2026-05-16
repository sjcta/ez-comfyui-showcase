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
  var _galleryFilters = { type: '', size: '', style: '', workflow: '' };
  var _renderTimer = null;
function _attachSentinel() {
    const sentinel = document.getElementById('masonrySentinel');
    if (!sentinel) return;
    if (_sentinelObs) _sentinelObs.disconnect();
    _sentinelObs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && _histVisibleCount < historyItems.length) {
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), historyItems.length);
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
    const tagHtml = wfTag ? ` <span class="${wfTag.cls}">${wfTag.text}</span>` : '';
    const instBadge = j.instance ? ` <span>#${escH(j.instance)}</span>` : '';

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
        ${tagHtml || instBadge ? `<div class="gi-wf-badge">${tagHtml}${instBadge}</div>` : ''}
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
    const imgSrc = h.thumb ? `${API}/api/thumbs/${h.thumb}` : `${API}/api/images/${h.filename}`;
    const wfTag = window.CW.getWFType(h.workflow || '');
    const meta1 = A._wfMeta[h.workflow] || {};
    const mainText1 = wfTag ? wfTag.text : ((meta1.tags || [])[0] || '');
    const mainCls1 = wfTag ? wfTag.cls : (mainText1 ? (mainText1 === '放大' ? 'wf-tag-cat' : 'wf-tag-res') : '');
    const tagBadge = mainText1 ? `<div class="gi-type-badge ${mainCls1}">${mainText1}</div>` : '';
    const typeCls1 = mainCls1 ? 'gi-type-' + mainCls1.replace('wf-tag-', '') : '';

    return `<div class="gi ${typeCls1}" data-wf="${escA(h.workflow || '')}" data-hist-idx="${i}" onclick="CW.fillFormFromHistory(${i})">
      <div class="gi-img" onclick="event.stopPropagation();CW.openLB(${i})">
        <img src="${imgSrc}" loading="lazy" alt="">
        ${tagBadge}
        <button class="gi-del" onclick="event.stopPropagation();CW.delHist('${h.id}')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>
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

function _renderGalleryImpl() { console.log("[DEBUG] hist=" + historyItems.length + " filtered=" + _filteredHistory.length + " count=" + _histVisibleCount + " batch=" + _batchSize());
    const gallery = $('#gallery');

    // Ensure we have an initial batch size on first render
    _ensureInitialBatch();

    // Active jobs (queued, preparing, starting_comfyui, generating)
    const activeJobs = Object.values(jobs).filter((j) => j.status !== 'done' && j.status !== 'error');
    // Error jobs (kept briefly for visibility)
    const errorJobs = Object.values(jobs).filter((j) => j.status === 'error');

    const jobCards = [...activeJobs, ...errorJobs];

    // ── Hash check: skip rebuild if nothing changed ──
    const hash = _galleryHash(jobs, historyItems);
    if (hash === _lastGalleryHash) return;
    _lastGalleryHash = hash;

    // Count: active jobs + history
    $('#histCount').textContent = `(${activeJobs.length + historyItems.length})`;

    var html = '';

    // ── Render all cards via unified functions ──
    for (const j of jobCards) {
      html += _renderJobCard(j);
    }

    // ── History items (lazy loaded) ──
    const filteredArr = _filteredHistory.length ? _filteredHistory : historyItems;
    lbItems = filteredArr;
    const visibleItems = filteredArr.slice(0, _histVisibleCount);
    for (let i = 0; i < visibleItems.length; i++) {
      html += _renderHistCard(visibleItems[i], i);
    }

    if (historyItems.length > _histVisibleCount) {
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
    const filteredArr2 = _filteredHistory.length ? _filteredHistory : historyItems;
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
          _histVisibleCount = Math.min(_histVisibleCount + _batchSize(), historyItems.length);
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
    const imgSrc = h.thumb ? `${API}/api/thumbs/${h.thumb}` : `${API}/api/images/${h.filename}`;
    const wfTag = window.CW.getWFType(h.workflow || '');
    const meta2 = A._wfMeta[h.workflow] || {};
    const mainText2 = wfTag ? wfTag.text : ((meta2.tags || [])[0] || '');
    const mainCls2 = wfTag ? wfTag.cls : (mainText2 ? (mainText2 === '放大' ? 'wf-tag-cat' : 'wf-tag-res') : '');
    const tagBadge = mainText2 ? `<div class="gi-type-badge ${mainCls2}">${mainText2}</div>` : '';
    const typeCls2 = mainCls2 ? 'gi-type-' + mainCls2.replace('wf-tag-', '') : '';
    return `<div class="gi ${typeCls2}" data-wf="${escA(h.workflow || '')}" data-hist-idx="${i}" onclick="CW.fillFormFromHistory(${i})">
    <div class="gi-img lazy-img" onclick="event.stopPropagation();CW.openLB(${i})">
      <img src="${imgSrc}" loading="lazy" alt="">
      ${tagBadge}
      ${canEdit ? `<button class="gi-del" onclick="event.stopPropagation();CW.delHist('${h.id}')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>` : ''}
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
    var wfs = new Set();
    var styles = new Set();
    var typeOpts = new Set();
    for(var k = 0; k < historyItems.length; k++) {
      var j = historyItems[k];
      if(j.workflow) wfs.add(j.workflow.replace(".json", ""));
      // Collect unique main tags for type filter
      var _tag = window.CW.wfTag(j.workflow || '', (A._wfMeta[j.workflow || ''] || {}).tags);
      if(_tag && _tag.text) typeOpts.add(_tag.text);
      try {
        var pObj = JSON.parse(j.prompt || '{}');
        if(pObj.style && typeof pObj.style === 'string') {
          var s = pObj.style.trim();
          if(s.length > 0) styles.add(s);
        }
      } catch(e) {}
    }
    var typeSel = document.getElementById("gfType");
    if(typeSel) {
      var curType = typeSel.value;
      var sortedTypes = Array.from(typeOpts).sort();
      var ht = '<option value="">全部类型</option>';
      for(var ti = 0; ti < sortedTypes.length; ti++) {
        ht += '<option value="' + sortedTypes[ti] + '">' + sortedTypes[ti] + '</option>';
      }
      typeSel.innerHTML = ht;
      if(curType && typeOpts.has(curType)) typeSel.value = curType;
    }
    var sizeSel = document.getElementById("gfSize");
    if(sizeSel) {
      sizeSel.innerHTML = '<option value="">全部尺寸</option>' +
        '<option value="1K">1K (≤1024)</option>' +
        '<option value="2K">2K (≤2048)</option>' +
        '<option value="4K">4K (≤3840)</option>' +
        '<option value="4K+">4K+ (>3840)</option>';
    }
    var wfSel = document.getElementById("gfWF");
    if(wfSel) {
      var cur2 = wfSel.value;
      var arr2 = Array.from(wfs).sort();
      var h2 = '<option value="">全部工作流</option>';
      for(var m = 0; m < arr2.length; m++) {
        h2 += '<option value="' + arr2[m] + '">' + arr2[m] + '</option>';
      }
      wfSel.innerHTML = h2;
      if(cur2 && wfs.has(cur2)) wfSel.value = cur2;
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
      if(_galleryFilters.type) {
        var t = window.CW.wfTag(j.workflow || '', (A._wfMeta[j.workflow || ''] || {}).tags);
        if(!t || t.text !== _galleryFilters.type) return false;
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
      if(_galleryFilters.workflow) {
        if((j.workflow || "").replace(".json", "") !== _galleryFilters.workflow) return false;
      }
      return true;
    });
  }

  _filteredHistory = [];

  _galleryFilters = { type: '', size: '', style: '', workflow: '' };
function _ensureInitialBatch() {
    if (_histVisibleCount > 0) return;
    _histVisibleCount = Math.min(_batchSize(), (_filteredHistory.length ? _filteredHistory.length : historyItems.length)); console.log("[GALLERY DEBUG] _ensureInitialBatch: batch=" + _batchSize() + " filtered=" + _filteredHistory.length + " hist=" + historyItems.length + " => count=" + _histVisibleCount);
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
    lbIdx = Math.max(0, Math.min(lbIdx + dir, lbItems.length - 1));
    renderLB();
  }

function renderLB() {
    if (lbIdx < 0 || lbIdx >= lbItems.length) return;
    const h = lbItems[lbIdx];
    var lbImg = $('#lbImg'); lbImg.src = ''; lbImg.src = `${API}/api/images/${h.filename}`;
    $('#lbInfo').textContent = h.prompt || '—';
    $('#lbPrev').style.display = lbIdx > 0 ? '' : 'none';
    $('#lbNext').style.display = lbIdx < lbItems.length - 1 ? '' : 'none';
  }

function closeLB() {
    $('#lightbox').classList.remove('open');
    document.body.style.overflow = '';
    lbIdx = -1;
  }

function openJobLB(filename, label) {
    // Show a single-item lightbox for a job image
    const imgSrc = `${API}/api/images/${filename}`;
    var lbImg = $('#lbImg'); lbImg.src = ''; lbImg.src = imgSrc;
    $('#lbInfo').textContent = label || '';
    $('#lbPrev').style.display = 'none';
    $('#lbNext').style.display = 'none';
    $('#lightbox').classList.add('open');
    document.body.style.overflow = 'hidden';
  }

function openLB(idx) {
    lbIdx = idx;
    renderLB();
    $('#lightbox').classList.add('open');
    document.body.style.overflow = 'hidden';
  }

async function delHist(id) {
    if (!(window.CW.auth && window.CW.auth.isLoggedIn && window.CW.auth.isLoggedIn())) return;
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
    var el;
    el = document.getElementById("gfType");
    _galleryFilters.type = el ? el.value : "";
    el = document.getElementById("gfSize");
    _galleryFilters.size = el ? el.value : "";
    el = document.getElementById("gfStyle");
    _galleryFilters.style = el ? el.value.toLowerCase() : "";
    el = document.getElementById("gfWF");
    _galleryFilters.workflow = el ? el.value : "";
    _filteredHistory = _filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = "";
    renderGallery();
  }

function clearFilters() {
    _galleryFilters = { type: "", size: "", style: "", workflow: "" };
    var el;
    el = document.getElementById("gfType");
    if (el) el.value = "";
    el = document.getElementById("gfSize");
    if (el) el.value = "";
    el = document.getElementById("gfStyle");
    if (el) el.value = "";
    el = document.getElementById("gfWF");
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
  window.CW.delHist = delHist;
  window.CW.openLB = openLB;
  window.CW.openJobLB = openJobLB;
  window.CW.closeLB = closeLB;
  window.CW.lbNav = lbNav;
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
