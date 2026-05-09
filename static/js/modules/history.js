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

    html = '';

    // ── Job cards ──
    for (const j of jobCards) {
      const label = j.prompt_preview || j.workflow?.replace('.json', '') || '...';
      const statusMsg = j.message || j.status;
      const hasImage = !!j.image;
      const imgSrc = hasImage ? `${API}/api/images/${j.image}` : '';

      html += `<div class="gi job-card ${j.status}" data-job-id="${j.id}">`;

      if (hasImage) {
        html += `<div class="gi-img" onclick="event.stopPropagation();CW.openJobLB('${escA(j.image)}','${escA(label)}')">
        <img src="${imgSrc}" loading="lazy" alt="">
      </div>`;
      } else if (j.status === 'queued') {
        html += `<div class="gi-img job-placeholder">
        <div class="job-status-text queued">等待前序任务中</div>
      </div>`;
      } else {
        const genTs = j.generating_at || 0;
        html += `<div class="gi-img job-placeholder">
        <div class="job-spinner"></div>
        <div class="job-status-text ${j.status}">${escH(statusMsg)}</div>
        ${j.status === 'generating' && genTs ? `<div class="gi-timer-row"><span class="gi-timer" data-ts="${genTs}">${formatElapsed(genTs)}</span></div>` : ''}
      </div>`;
      }

      // Cancel/delete button (top-right) for all job states
      const cancelLabel = j.status === 'generating' ? '取消' : '删除';
      html += `<button class="gi-del" onclick="event.stopPropagation();CW.cancelJob('${j.id}')" title="${cancelLabel}"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>`;

      // Workflow name badge (top-left) — use metadata edited name
      const wfMeta = _wfMeta[j.workflow] || {};
      const wfLabel = wfMeta.name || (j.workflow || '').replace('.json', '');
      if (wfLabel) {
        const wfTag = getWFType(j.workflow || '');
        const tagHtml = wfTag
          ? ` <span class="wf-tag ${wfTag.cls}" style="font-size:8px;padding:0 3px;vertical-align:middle;margin-left:4px">${wfTag.text}</span>`
          : '';
        const instBadge = j.instance
          ? ` <span class="wf-tag" style="font-size:8px;padding:0 3px;vertical-align:middle;margin-left:4px;background:#2d1b69;color:#a78bfa">#${escH(j.instance)}</span>`
          : '';
        html += `<div class="gi-wf-badge">${escH(wfLabel)}${tagHtml}${instBadge}</div>`;
      }

      const phaseMsg = j.message || (j.status === 'generating' ? '出图中' : j.status === 'error' ? '失败' : '排队中');
      const showPhase = j.status !== 'generating'; // hide phase in meta for generating (timer only)
      html += `<div class="gi-info" onclick="event.stopPropagation();CW.restoreJob('${j.id}')">
      <div class="gi-prompt" title="${escA(j.prompt_preview || label)}">${escH(j.prompt_preview || label)}</div>
      ${j.status !== 'generating' && j.message ? `<div class="gi-detail" title="${escA(j.message)}">${escH(j.message)}</div>` : ''}
      ${j.status === 'generating' ? `<div class="gi-progress-bar"><div class="gi-progress-fill" style="width:${j.progress?.pct || 0}%"></div></div>` : ''}
      ${j.status === 'error' ? `<div class="gi-retry-row"><button class="btn-retry" onclick="event.stopPropagation();CW.retryJob('${j.id}')">重新尝试</button></div>` : ''}
      <div class="gi-meta">
        <span>${j.status === 'generating' ? '' : phaseMsg}</span>
        ${j.width && j.height ? `<span>📐 ${j.width}×${j.height}</span>` : ''}
        ${j.queued_at ? `<span>🕐 ${j.queued_at}</span>` : ''}
      </div>
      ${j.seed ? `<div class="gi-seed">🌱 ${j.seed}</div>` : ''}
    </div>`;

      html += `</div>`;
    }

    // ── History items (lazy loaded) ──
    const filteredArr = _filteredHistory.length ? _filteredHistory : historyItems;
    lbItems = filteredArr;
    const visibleItems = filteredArr.slice(0, _histVisibleCount);
    for (let i = 0; i < visibleItems.length; i++) {
      const h = visibleItems[i];
      const imgSrc = h.thumb ? `${API}/api/thumbs/${h.thumb}` : `${API}/api/images/${h.filename}`;
      const wfTag = getWFType(h.workflow || '');
      const tagBadge = wfTag ? `<div class="gi-type-badge ${wfTag.cls}">${wfTag.text}</div>` : '';

      html += `<div class="gi" data-hist-idx="${i}" onclick="CW.fillFormFromHistory(${i})">
      <div class="gi-img" onclick="event.stopPropagation();CW.openLB(${i})">
        <img src="${imgSrc}" loading="lazy" alt="">
        ${tagBadge}
        <button class="gi-del" onclick="event.stopPropagation();CW.delHist('${h.id}')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>
        <button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(${i})" title="复刻出图">📋 复刻</button>
      </div>
      <div class="gi-info">
        <div class="gi-prompt" title="${escA(h.prompt || '')}">${escH(h.prompt || '—')}</div>
        <div class="gi-meta">
          <span>⏱ ${h.elapsed}s</span>
          <span>📐 ${h.width && h.height ? h.width + '×' + h.height : '—'}</span>
          <span>🕐 ${h.time || '—'}</span>
        </div>
        ${h.seed ? `<div class="gi-seed">🌱 ${h.seed}</div>` : ''}
      </div>
    </div>`;
    }

    if (historyItems.length > _histVisibleCount) {
      html += `<div class="masonry-sentinel" id="masonrySentinel"></div>`;
    }

    if (!jobCards.length && !historyItems.length) {
      html = `<div class="empty-hint"><div class="eh-icon">🖼️</div><p>暂无历史</p><p style="font-size:11px;margin-top:4px">出图后自动出现在这里</p></div>`;
    }

    try { gallery.innerHTML = html; } catch(e) { console.error("[GALLERY ERROR]", e); var ediv = document.getElementById("gallery"); if(ediv) ediv.innerHTML = "<div style=color:red;padding:20px>Render error: " + e.message + "</div>"; }

    _lastRenderedHistCount = visibleItems.length;
    lbItems = filteredArr;
    _attachSentinel();
  }
function _galleryHash(jobsObj, histArr) {
    // Only structural changes trigger full rebuild: job added/removed, status transitions, history items added/removed
    s = '';
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

    fragment = '';
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
    const imgSrc = h.thumb ? `${API}/api/thumbs/${h.thumb}` : `${API}/api/images/${h.filename}`;
    const wfTag = getWFType(h.workflow || '');
    const tagBadge = wfTag ? `<div class="gi-type-badge ${wfTag.cls}">${wfTag.text}</div>` : '';
    return `<div class="gi" data-hist-idx="${i}" onclick="CW.fillFormFromHistory(${i})">
    <div class="gi-img lazy-img" onclick="event.stopPropagation();CW.openLB(${i})">
      <img src="${imgSrc}" loading="lazy" alt="">
      ${tagBadge}
      <button class="gi-del" onclick="event.stopPropagation();CW.delHist('${h.id}')" title="删除"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg></button>
      <button class="gi-reuse" onclick="event.stopPropagation();CW.fillFormFromHistory(${i})" title="复刻出图">📋 复刻</button>
    </div>
    <div class="gi-info">
      <div class="gi-prompt" title="${escA(h.prompt || '')}">${escH(h.prompt || '—')}</div>
      <div class="gi-meta">
        <span>⏱ ${h.elapsed}s</span>
        <span>📐 ${h.width && h.height ? h.width + '×' + h.height : '—'}</span>
        <span>🕐 ${h.time || '—'}</span>
      </div>
      ${h.seed ? `<div class="gi-seed">🌱 ${h.seed}</div>` : ''}
    </div>
  </div>`;
  }

  _lastGalleryHash = '';

  _renderTimer = null;
function _populateFilterOptions() {
    var wfs = new Set();
    var styles = new Set();
    for(var k = 0; k < historyItems.length; k++) {
      var j = historyItems[k];
      if(j.workflow) wfs.add(j.workflow.replace(".json", ""));
      try {
        var pObj = JSON.parse(j.prompt || '{}');
        if(pObj.style && typeof pObj.style === 'string') {
          var s = pObj.style.trim();
          if(s.length > 0) styles.add(s);
        }
      } catch(e) {}
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
        var t = getWFType(j.workflow || "");
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
    $('#lbImg').src = `${API}/api/images/${h.filename}`;
    $('#lbInfo').textContent =
      `${h.prompt || '—'} · ⏱ ${h.elapsed}s · 📐 ${h.width && h.height ? h.width + '×' + h.height : '—'} · 🌱 ${shortSeed(h.seed)} · 🕐 ${h.time || ''}`;
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
    $('#lbImg').src = imgSrc;
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
    // Mark card as deleting immediately
    var card = document.querySelector('[data-hist-idx][onclick*="' + id.slice(-6) + '"]') || document.querySelector('[onclick*="' + id.slice(-6) + '"]');
    if (card) { card.classList.add('deleting'); card.style.opacity = '0.4'; card.style.pointerEvents = 'none'; }
    try {
      var r = await fetch(`${API}/api/history/${id}`, { method: 'DELETE' });
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
      const r = await fetch(`${API}/api/history`);
      const newItems = await r.json();
      historyItems.length = 0;
      Array.prototype.push.apply(historyItems, newItems);
      _lastGalleryHash = '';
      _populateFilterOptions();
      applyFilters();
      loadWorkflows();
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
  window.CW.renderGallery = renderGallery;

})();
