/**
 * ComfyUI Web v3.9 — 上图下文卡片，点击图片放大，点击文字还原参数
 */
(function () {
  'use strict';
  try {
  console.log('[BOOT] app.js IIFE started');

  // ── Mobile viewport height fix (100vh includes address bar on iOS) ──
  function setVH() {
    document.documentElement.style.setProperty('--vh', `${window.innerHeight * 0.01}px`);
  }
  window.addEventListener('resize', setVH);
  window.addEventListener('orientationchange', setVH);
  setVH();

  const API = window.CW_API_BASE || (location.protocol === 'file:' ? 'http://localhost:18000' : location.pathname.replace(/\/+$/, ''));
  const BASE = API;

  let ws = null;
  let currentWF = null;
  let advOpen = false;
  let jobs = {};
  let jobFields = {};
  // job_id → fields snapshot
  let historyItems = [];
  let currentTargetInstance = '';
  let currentTargetNodeId = '';
  let _histVisibleCount = 0;
  let _lastRenderedHistCount = 0;

  /** Calculate how many columns the masonry grid currently has */
  

  /** Load 2 rows worth of items */
  

  /** Initialize first batch (called once after first history load) */
  

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  function escH(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
  function escA(s) {
    return s.replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }
  // ── Expose shared state for modules ──
  console.log('[BOOT] before __APP__');
  window.__APP__ = { $, $$, escH, escA, API, jobs, jobFields, historyItems };
  console.log('[BOOT] after __APP__');
  console.log('[BOOT] currentWF before def:', typeof currentWF);
  // Expose currentWF via getter/setter so other IIFE modules can read/write it
  Object.defineProperty(window.__APP__, 'currentWF', {
    get: () => currentWF,
    set: (v) => { currentWF = v; }
  });
  console.log('[BOOT] currentWF after def');
  // Expose advOpen via getter/setter (used by ui.js)
  Object.defineProperty(window.__APP__, 'advOpen', {
    get: () => advOpen,
    set: (v) => { advOpen = v; }
  });
  Object.defineProperty(window.__APP__, 'currentTargetInstance', {
    get: () => currentTargetInstance,
    set: (v) => { currentTargetInstance = v || ''; }
  });
  Object.defineProperty(window.__APP__, 'currentTargetNodeId', {
    get: () => currentTargetNodeId,
    set: (v) => { currentTargetNodeId = v || ''; }
  });
  console.log('[BOOT] defineProperties done');

  function shortSeed(s) {
    if (!s) return '—';
    s = String(s);
    return s.length > 10 ? s.slice(0, 4) + '…' + s.slice(-4) : s;
  }
  function getWFType(name) {
    if (!name) return '';
    const n = name.toLowerCase();
    if (n.startsWith('i2v') || n.includes('-i2v') || n.includes('_i2v')) return { text: '图生视频', cls: 'wf-tag-i2v' };
    if (n.startsWith('t2v') || n.includes('-t2v') || n.includes('_t2v')) return { text: '文生视频', cls: 'wf-tag-t2v' };
    if (n.startsWith('i2i') || n.includes('-i2i') || n.includes('_i2i')) return { text: '图生图', cls: 'wf-tag-i2i' };
    if (n.startsWith('t2i') || n.includes('-t2i') || n.includes('_t2i')) return { text: '文生图', cls: 'wf-tag-t2i' };
    return '';
  }
  /** Prefer metadata tags[0] over filename guess, keep CSS class from filename. */
  function wfTag(name, metaTags) {
    const fallback = getWFType(name);
    if (metaTags && metaTags.length > 0) {
      return { text: metaTags[0], cls: fallback ? fallback.cls : 'wf-tag-res' };
    }
    return fallback;
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  WebSocket
  // ══════════════════════════════════════════════════════════════════════════

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}${BASE}/ws`);
    ws.onopen = () => console.log('[WS] ok');
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.type === 'job_update') onJobUpdate(d.job);
      } catch {}
    };
    ws.onclose = () => setTimeout(connectWS, 5000);
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  Status
  // ══════════════════════════════════════════════════════════════════════════

  async function pollStatus() {
    try {
      const r = await fetch(`${API}/api/status`);
      const d = await r.json();
      updateServices(d);
      updateGPU(d.gpu);
    } catch {}
  }

  function updateServices(d) {
    const insts = d.instances || [];
    const anyUp = insts.some((i) => i.up);
    const totalRun = insts.reduce((s, i) => s + (i.queue_running || 0), 0);
    const totalPend = insts.reduce((s, i) => s + (i.queue_pending || 0), 0);
    const comfyBtn = $('#svcComfyUI');
    const comfyState = $('#comfyState');
    if (comfyBtn) comfyBtn.className = 'svc-btn ' + (anyUp ? 'on' : 'off');
    if (comfyState) {
      var upCount = insts.filter(function (i) {
        return i.up;
      }).length;
      var busyCount = insts.filter(function (i) {
        return i.up && i.queue_running > 0;
      }).length;
      var pendCount = insts.filter(function (i) {
        return i.up && i.queue_pending > 0;
      }).length;
      if (!anyUp) comfyState.textContent = '全部关闭';
      else if (busyCount > 0) comfyState.textContent = '出图中(' + busyCount + '/' + upCount + ')';
      else if (pendCount > 0) comfyState.textContent = '排队中(' + pendCount + ')';
      else comfyState.textContent = '待机(' + upCount + ')';
    }
  }

  function updateGPU(g) {
    if (!g) return;
    const fill = $('#vramFill');
    if (!fill) return;
    const pct = g.vram_pct || 0;
    const temp = g.temp_c || 0;
    fill.style.width = pct + '%';
    // State: green=idle, yellow=busy, orange=overloaded (vram>70% or temp>65)
    const isOverload = pct > 70 || temp > 65;
    const isBusy = pct > 30 || temp > 50;
    fill.className = 'sb-vram-fill' + (isOverload ? ' overload' : isBusy ? ' busy' : '');
    // Also tint the entire statusbar
    const bar = $('#statusbar');
    if (bar) bar.dataset.state = isOverload ? 'overload' : isBusy ? 'busy' : 'idle';
    var used = Number(g.vram_used_mb || 0);
    var total = Number(g.vram_total_mb || 0);
    if ($('#vramText')) {
      $('#vramText').textContent = total > 0
        ? `${(used / 1024).toFixed(1)} / ${(total / 1024).toFixed(1)} GB (${pct}%)`
        : '未获取到 VRAM';
    }
    if ($('#gpuTemp')) $('#gpuTemp').textContent = `${temp} °C`;
    if ($('#gpuUtil')) $('#gpuUtil').textContent = `GPU ${g.util_pct}%`;
    if ($('#vramSegments') && !$('#vramSegments').dataset.done) {
      [25, 50, 75].forEach((pct) => {
        const seg = document.createElement('div');
        seg.className = 'sb-vram-seg';
        seg.style.left = pct + '%';
        $('#vramSegments').appendChild(seg);
      });
      $('#vramSegments').dataset.done = '1';
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  Service toggles
  // ══════════════════════════════════════════════════════════════════════════

  function openInstPopup(mode) {
    var overlay = $('#instPopup');
    var title = $('#instPopupTitle');
    if (!overlay) return;
    overlay.classList.add('open');
    overlay._mode = mode || 'comfyui';
    if (title)
      title.textContent = mode === 'others' ? '\u5176\u4ed6 GPU \u8fdb\u7a0b' : 'ComfyUI \u5b9e\u4f8b\u7ba1\u7406';
    if (mode === 'others') _refreshGpuCards();
    else _refreshInstCards();
  }
  function closeInstPopup() {
    var overlay = $('#instPopup');
    if (overlay) overlay.classList.remove('open');
  }
  function _queueBarHtml(running, pending) {
    var total = running + pending;
    if (total === 0) return '<span style="color:var(--dim);font-size:11px">\u65e0</span>';
    var html = '';
    // Running segment(s) — green
    for (var i = 0; i < running; i++) {
      html += '<div style="flex:1;height:8px;background:var(--green);border-radius:2px;min-width:4px"></div>';
    }
    // Pending segment(s) — yellow dashed
    for (var i = 0; i < pending; i++) {
      html += '<div style="flex:1;height:8px;background:#f59e0b;border-radius:2px;opacity:0.6;min-width:4px"></div>';
    }
    if (!html) html = '<div style="flex:1;height:8px;background:var(--border);border-radius:2px"></div>';
    return html;
  }

  async function _refreshInstCards() {
    var box = $('#instCards');
    if (!box) return;
    box.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:8px">\u52a0\u8f7d\u4e2d...</div>';
    try {
      var r = await fetch(API + '/api/comfyui/status');
      var d = await r.json();
      var html = '<div class="popup-section-title">ComfyUI \u5b9e\u4f8b</div>';
      var groupMap = { nunchaku: 'Nunchaku', 'z-image-turbo': 'Z-Image Turbo', seedvr: 'SeedVR' };
      for (var idx = 0; idx < (d.instances || []).length; idx++) {
        var inst = d.instances[idx];
        var statusCls = inst.up ? 'on' : 'off';
        var btnLabel = inst.up ? '<svg width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:3px"><rect x="4" y="4" width="16" height="16" rx="2" fill="currentColor"/></svg>\u505c\u6b62' : '<svg width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:3px"><polygon points="5,3 22,12 5,21" fill="currentColor"/></svg>\u542f\u52a8';
        var btnCls = inst.up ? 'stop' : 'start';
        var groupLabel = groupMap[inst.loaded_group] || inst.loaded_group || '';
        var stateText = !inst.up
          ? '\u5173\u95ed'
          : inst.queue_running > 0
            ? '\u51fa\u56fe\u4e2d'
            : inst.queue_pending > 0
              ? '\u6392\u961f\u4e2d'
              : '\u5f85\u673a';
        html +=
          '<div class="inst-card ' + statusCls + '">' +
          '<div class="inst-card-header">' +
          '<div class="inst-card-name"><span class="inst-led ' +
          statusCls +
          '"></span> \u5b9e\u4f8b ' +
          inst.name +
          ' <span style="color:var(--dim);font-size:11px">:' +
          inst.port +
          '</span></div>' +
          '<button class="inst-card-btn ' +
          btnCls +
          '" onclick="CW.toggleInst(\'' +
          inst.name +
          "'," +
          !inst.up +
          ')" id="instBtn' +
          inst.name +
          '">' +
          btnLabel +
          '</button>' +
          '</div>' +
          '<div class="inst-card-row"><span>\u72b6\u6001</span><span class="val ' +
          (inst.up ? 'active' : '') +
          '">' +
          stateText +
          `</span></div>` +
          `<div class="inst-card-row"><span>\u8fd0\u884c\u4e2d</span><span class="val ` +
          (inst.queue_running ? `active` : ``) +
          `">` +
          inst.queue_running +
          ` \u4efb\u52a1` +
          (inst.queue_running > 0 && inst.current_workflow ? `(\u2009${inst.current_workflow} - ${inst.progress}%)` : ``) +
          `</span></div>` +
          `<div class="inst-card-row"><span>\u6392\u961f</span><span class="val ` +
          (inst.queue_pending ? `pending` : ``) +
          `">` +
          inst.queue_pending +
          ` \u4efb\u52a1` +
          (inst.pending_workflows && inst.pending_workflows.length > 0 ? `(\u2009${inst.pending_workflows.join(' ')}` + `)` : ``) +
          `</span></div>`;
        if (inst.loaded_group) html += '<span class="inst-card-group">' + escH(inst.loaded_group) + '</span>';
        html += '</div>';
      }
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML =
        '<div style="color:#ef4444;font-size:12px;padding:8px">\u52a0\u8f7d\u5931\u8d25: ' + escH(e.message) + '</div>';
    }
  }
  async function _refreshGpuCards() {
    var box = $('#instCards');
    if (!box) return;
    box.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:8px">\u52a0\u8f7d\u4e2d...</div>';
    try {
      var r = await fetch(API + '/api/gpu-processes');
      var d = await r.json();
      var procs = d.processes || [];
      var html = '<div class="popup-section-title">\u5360\u7528 GPU \u663e\u5b58\u7684\u8fdb\u7a0b</div>';
      if (procs.length === 0)
        html +=
          '<div style="color:var(--dim);font-size:12px;padding:8px">\u65e0\u5176\u4ed6\u663e\u5b58\u5360\u7528\u8fdb\u7a0b</div>';
      for (var i = 0; i < procs.length; i++) {
        var p = procs[i];
        html +=
          '<div class="gpu-card">' +
          '<div class="gpu-card-info">' +
          '<div class="gpu-card-name" title="' +
          escH(p.process) +
          '">' +
          escH(p.name) +
          '</div>' +
          '<div class="gpu-card-detail">PID ' +
          p.pid +
          ' \u00b7 ' +
          escH(p.process) +
          '</div>' +
          '</div>' +
          '<span class="gpu-card-mem">' +
          p.mem_mb +
          ' MB</span>' +
          '<button class="gpu-card-kill" onclick="CW.killGpuProc(' +
          p.pid +
          ')" id="gpuKill' +
          p.pid +
          '">\u7ec8\u6b62</button>' +
          '</div>';
      }
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML =
        '<div style="color:#ef4444;font-size:12px;padding:8px">\u52a0\u8f7d\u5931\u8d25: ' + escH(e.message) + '</div>';
    }
  }
  async function toggleInst(name, start) {
    var btn = document.getElementById('instBtn' + name);
    if (btn) {
      btn.disabled = true;
      btn.textContent = '...';
    }
    try {
      var r = await fetch(API + '/api/comfyui/' + name + '/' + (start ? 'start' : 'stop'), { method: 'POST' });
      var d = await r.json();
      if (!r.ok) throw new Error(d.detail || '\u64cd\u4f5c\u5931\u8d25');
    } catch (e) {
      alert('\u64cd\u4f5c\u5931\u8d25: ' + e.message);
    }
    setTimeout(_refreshInstCards, 1500);
    setTimeout(pollStatus, 2000);
  }
  async function killGpuProc(pid) {
    if (!confirm('\u786e\u5b9a\u7ec8\u6b62 PID ' + pid + ' \uff1f')) return;
    var btn = document.getElementById('gpuKill' + pid);
    if (btn) {
      btn.disabled = true;
      btn.textContent = '...';
    }
    try {
      var r = await fetch(API + '/api/gpu-processes/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid: pid }),
      });
      var d = await r.json();
      if (!r.ok) throw new Error(d.detail || '\u64cd\u4f5c\u5931\u8d25');
    } catch (e) {
      alert('\u64cd\u4f5c\u5931\u8d25: ' + e.message);
    }
    setTimeout(_refreshGpuCards, 1500);
  }
  function initServiceToggles() {
    var comfyBtn = $('#svcComfyUI');
    if (comfyBtn)
      comfyBtn.addEventListener('click', function () {
        openInstPopup('comfyui');
      });
  }
  // ══════════════════════════════════════════════════════════════════════════
  //  Workflows
  // ══════════════════════════════════════════════════════════════════════════

  

  

  
  
  

  

  

  
 // zone-aware field metadata for current workflow

  

  

  

  // initDropZone removed — upload card is built into loadWorkflows
  console.log("[BOOT] mid-1");

  

  

  // ══════════════════════════════════════════════════════════════════════════
  //  Generate + Restore
  // ══════════════════════════════════════════════════════════════════════════

  

  

  

  

  

  

  // ══════════════════════════════════════════════════════════════════════════
  //  Jobs + Gallery
  // ══════════════════════════════════════════════════════════════════════════

  async function pollJobs() {
  console.log("[BOOT] pollJobs");
    if (!(window.CW.auth && window.CW.auth.isLoggedIn && window.CW.auth.isLoggedIn())) return;
    try {
      const r = await window.CW.auth.apiFetch(`${API}/api/jobs`);
      if (!r.ok) return;
      const arr = await r.json();
      const prevCount = Object.keys(jobs).length;
      // Client-side safety: cancel jobs stuck in generating for >700s
      const now = Date.now() / 1000;
      for (const j of arr) {
        if (j.status === 'generating' && j.generating_at && now - j.generating_at > 700) {
          window.CW.auth.apiFetch(`${API}/api/jobs/${j.id}`, { method: 'DELETE' });
        }
      }
      let changed = false;
      for (const j of arr) {
        const prev = jobs[j.id];
        if (!prev || prev.status !== j.status || prev.message !== j.message || prev.progress?.pct !== j.progress?.pct) {
          changed = true;
        }
        jobs[j.id] = j;
      }
      // Remove stale jobs no longer on server (keep error jobs even if server cleaned them up)
      const serverIds = new Set(arr.map((j) => j.id));
      for (const id of Object.keys(jobs)) {
        if (!serverIds.has(id) && jobs[id]?.status !== 'error') {
          delete jobs[id];
          changed = true;
        }
      }
      if (changed && window.CW.renderGallery) window.CW.renderGallery();
    } catch {}
  }

  function onJobUpdate(job) {
    const prev = jobs[job.id];
    // Toast on status change
    if (prev && prev.status !== job.status) {
      var shortId = job.id.slice(-6);
      var wfTag = getWFType(job.workflow);
      var typeLabel = wfTag ? wfTag.text : '';
      try {
        if (job.status === 'queued') showToast(shortId + ' ' + typeLabel + ' 排队中', 'queued');
        else if (job.status === 'generating') showToast(shortId + ' ' + typeLabel + ' 出图中', 'generating');
        else if (job.status === 'downloading') showToast(shortId + ' ' + typeLabel + ' 拉取图片', 'queued');
        else if (job.status === 'done') showToast(shortId + ' ' + typeLabel + ' 完成', 'done');
        else if (job.status === 'error') showToast(shortId + ' ' + typeLabel + ' 失败', 'error');
      } catch(e) {}
    }
    jobs[job.id] = job;
    // ── Done: immediate image swap + background history refresh ──
    if (job.status === 'done' && job.image) {
      if (!prev || prev.status !== 'done' || !prev.image) {
        window.CW._onJobDone(job);
      }
      return;
    }
    // ── Error: remove from active + re-render ──
    if (job.status === 'error' && (!prev || prev.status !== 'error')) {
      window.CW._onJobError(job);
      return;
    }
    // ── Status transition (queued→preparing→generating): full rebuild ──
    if (!prev || prev.status !== job.status) {
      window.CW.forceGalleryRerender();
      return;
    }
    // ── Same status (progress update): in-place patch, NO flicker ──
    window.CW._patchJobCard(job);
  }

  // Live timer ticker — only runs when there are generating jobs
  function tickTimers() {
    const hasGenerating = Object.values(jobs).some((j) => j.status === 'generating');
    if (!hasGenerating) return;
    $$('.gi-timer').forEach((el) => {
      const ts = parseFloat(el.dataset.ts);
      if (ts > 0) el.textContent = formatElapsed(ts);
    });
  }

  function formatElapsed(startTime) {
    const sec = Math.max(0, Math.floor(Date.now() / 1000 - startTime));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}m${String(s).padStart(2, '0')}s` : `${s}s`;
  }


  // ── Polling fallback: sync active jobs via /api/jobs every 3s ──
  let _pollTimer = null;
  function _hasActiveJobs() {
    return Object.values(jobs).some(j => j.status !== 'done' && j.status !== 'error');
  }

  // Track timer for downloading state (rebroadcast download message)
  let _fetcherActive = false;
  async function _fetcherTick() {
    if (!_hasActiveJobs()) { _fetcherActive = false; return; }
    if (!(window.CW.auth && window.CW.auth.isLoggedIn && window.CW.auth.isLoggedIn())) { _fetcherActive = false; return; }
    // Check for downloading jobs that might need re-broadcast of download message
    const downloading = Object.values(jobs).filter(j => j.status === 'downloading');
    if (downloading.length > 0) {
      // Refresh from server to pick up status changes
      try {
        const r = await window.CW.auth.apiFetch(API + '/api/jobs');
        if (!r.ok) { _fetcherActive = false; return; }
        const serverJobs = await r.json();
        for (const sj of serverJobs) {
          const prev = jobs[sj.id];
          if (!prev) jobs[sj.id] = sj;
          else if (prev.status !== sj.status) {
            jobs[sj.id] = sj;
            onJobUpdate(sj);
          }
        }
      } catch {}
    }
    _fetcherActive = false;
  }
  async function _pollActiveJobs() {
    if (!_hasActiveJobs()) { _pollTimer = null; return; }
    if (!(window.CW.auth && window.CW.auth.isLoggedIn && window.CW.auth.isLoggedIn())) { _pollTimer = null; return; }
    try {
      const r = await window.CW.auth.apiFetch(API + '/api/jobs');
      if (!r.ok) { _pollTimer = null; return; }
      const serverJobList = await r.json(); const serverJobs = {}; for (const j of serverJobList) serverJobs[j.id] = j;
      // serverJobs is a dict {id: job_obj}
      let needRerender = false;
      let historyRefresh = false;
      let alreadyRefreshed = false;
      for (const [id, sj] of Object.entries(serverJobs)) {
        const prev = jobs[id];
        if (!prev) {
          jobs[id] = sj;
          needRerender = true;
        } else if (prev.status !== sj.status) {
          jobs[id] = sj;
          onJobUpdate(sj);
          // onJobUpdate handles loadHistory for done/error itself
          if (sj.status === 'done' && sj.image) { alreadyRefreshed = true; }
          else if (sj.status === 'error') { alreadyRefreshed = true; }
          else needRerender = true;
        } else if (sj.status === 'generating' && sj.progress && prev.progress?.pct !== sj.progress.pct) {
          jobs[id] = sj;
          window.CW._patchJobCard && window.CW._patchJobCard(sj);
        }
      }
      // Clean up jobs that server no longer tracks (completed while we weren't looking)
      for (const id of Object.keys(jobs)) {
        if (!serverJobs[id]) {
          delete jobs[id];
          historyRefresh = true;
        }
      }
      if (alreadyRefreshed) {
        // onJobUpdate already called loadHistory — only do forceGalleryRerender if there's still active jobs
        if (historyRefresh || needRerender) window.CW.forceGalleryRerender();
      } else if (historyRefresh) {
        window.CW.forceGalleryRerender();
        window.CW.loadHistory();
      } else if (needRerender) {
        window.CW.forceGalleryRerender();
      }
    } catch {}
    if (_hasActiveJobs()) _pollTimer = setTimeout(_pollActiveJobs, 3000);
    else _pollTimer = null;
  }
  function _startJobPoll() {
    if (_pollTimer) return;
    _pollTimer = setTimeout(_pollActiveJobs, 3000);
  }

  // Patch onJobUpdate to start polling when active jobs exist
  const _origOnJobUpdate = onJobUpdate;
  onJobUpdate = function(job) {
    var _prev = jobs[job.id];
    _origOnJobUpdate(job);
    // Status changed → re-render gallery immediately
    if (_prev && _prev.status !== job.status && job.status !== 'done' && job.status !== 'error') {
      if (window.CW.renderGallery) window.CW.renderGallery();
    }
    if (job.status !== 'done' && job.status !== 'error') _startJobPoll();
  };

  // Also: onJobUpdate needs to force re-render when downloading → done (image swap)
  if (!window.CW) window.CW = {};
  const _origOnJobUpdate2 = window.CW.onJobUpdate;
  // (already handled by the done + image branch in _origOnJobUpdate)

  // ══════════════════════════════════════════════════════════════════════════
  //  Gallery Filters
  // ══════════════════════════════════════════════════════════════════════════


  

  

  

  

  

  /** Build a single history card HTML string */
  

  /** Append newly visible history cards without rebuilding the DOM (no flicker) */
  

  
  

  

  // ══════════════════════════════════════════════════════════════════════════
  //  History
  // ══════════════════════════════════════════════════════════════════════════

  

  

  async function cancelJob(jobId) {
    var j = jobs[jobId];
    if (!j) return;
    var label = j.status === 'generating' ? '终止本次出图？' : '删除这张卡片？';
    if (!confirm(label)) return;
    try {
      await window.CW.auth.apiFetch(`${API}/api/jobs/${jobId}`, { method: 'DELETE' });
      delete jobs[jobId];
      window.CW.renderGallery();
    } catch (e) {
      console.error('cancelJob:', e);
    }
  }

  async function retryJob(jobId) {
    try {
      const r = await window.CW.auth.apiFetch(`${API}/api/jobs/${jobId}/retry`, { method: 'POST' });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert('重试失败: ' + (d.detail || r.status));
      }
    } catch (e) {
      alert('重试失败: ' + e.message);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  Lightbox
  // ══════════════════════════════════════════════════════════════════════════

  

  

  

  

  

  document.addEventListener('keydown', (e) => {
    if (!$('#lightbox').classList.contains('open')) return;
    if (e.key === 'Escape' && window.CW.closeLB) window.CW.closeLB();
    if (e.key === 'ArrowLeft' && window.CW.lbNav) window.CW.lbNav(-1);
    if (e.key === 'ArrowRight' && window.CW.lbNav) window.CW.lbNav(1);
  });

  // ══════════════════════════════════════════════════════════════════════════
  //  Advanced toggle / Seed / Init
  // ══════════════════════════════════════════════════════════════════════════

  

  

  

  

  /** Enable drag-to-scroll on horizontal scroll containers */
  

  /** Show a floating toast notification */


/** Clear the prompt textarea and hide the clear button */


function init() {
  console.log("[BOOT] init function");
    var statusPoller = (window.CW && window.CW.pollStatus && window.CW.pollStatus !== pollStatus)
      ? window.CW.pollStatus
      : pollStatus;
    statusPoller();
    setInterval(statusPoller, 5000);
    setInterval(() => {
      if (ws && ws.readyState === 1) ws.send('ping');
    }, 30000);
    window.CW.loadWfMeta && window.CW.loadWfMeta();
    window.CW.loadHistory && window.CW.loadHistory();
    if (window.CW.authReady && typeof window.CW.authReady.then === 'function') {
      window.CW.authReady.finally(function() {
        pollJobs();
      });
    } else {
      pollJobs();
    }
    setInterval(function() {
      pollJobs();
    }, 5000);
    connectWS();
    initServiceToggles();
    window.CW.initAdvToggle && window.CW.initAdvToggle();
    window.CW.initRatioGrid && window.CW.initRatioGrid();
    window.CW.initOverlayUpload && window.CW.initOverlayUpload();
    window.CW.initResizeHandle && window.CW.initResizeHandle();
    setInterval(tickTimers, 1000);
    if (window.CW.initDragScroll) window.CW.initDragScroll('.wf-grid');
  // Clear button clears prompt and focuses input
  // (always visible — toggled in HTML)
  (()=>{var el=$('#btnGenerate');if(el)el.addEventListener('click',function(){if(window.CW.doGenerate)window.CW.doGenerate();});})();
    ($('#lightbox')||{})['addEventListener']('click', (e) => {
      if (e.target === $('#lightbox') || e.target === $('#lbImg')) { if (window.CW.closeLB) window.CW.closeLB(); }
    });
    // Workflow management overlay
    try{$('#tbWfMgrBtn').addEventListener('click', function() { if (window.CW.openWfMgr) window.CW.openWfMgr(); });}catch(e){}
    try{$('#wfOverlayClose').addEventListener('click', function() { if (window.CW.closeWfMgr) window.CW.closeWfMgr(); });}catch(e){}
    try{$('#wfEditClose').addEventListener('click', function() { if (window.CW.closeWfEdit) window.CW.closeWfEdit(); });}catch(e){}
    try{$('#wfEditTagInput').addEventListener('keydown', function(e) { if (e.key === 'Enter' && window.CW.onAddWfTag) { window.CW.onAddWfTag(e.target.value); e.target.value = ''; } });}catch(e){}
    try{$('#wfEditCancel').addEventListener('click', function() { if (window.CW.closeWfEdit) window.CW.closeWfEdit(); });}catch(e){}
    try{$('#wfEditSave').addEventListener('click', function() { if (window.CW.saveWfEdit) window.CW.saveWfEdit(); });}catch(e){}
    try{$('#wfEditThumb').addEventListener('click', function() { var el = $('#wfEditThumbInput'); if (el) el.click(); });}catch(e){}
    try{$('#wfEditThumbInput').addEventListener('change', function() { if (window.CW.onWfThumbUpload) window.CW.onWfThumbUpload(); });}catch(e){}

    try{$('#wfDelCancel').addEventListener('click', function() { if (window.CW.closeWfDel) window.CW.closeWfDel(); });}catch(e){}
    try{$('#wfDelConfirm').addEventListener('click', function() { if (window.CW.confirmWfDel) window.CW.confirmWfDel(); });}catch(e){}
    try{$('#nodeEditorClose').addEventListener('click', function() { if (window.CW.closeNodeEditor) window.CW.closeNodeEditor(); });}catch(e){}
    try{$('#nodeEditorCancel').addEventListener('click', function() { if (window.CW.closeNodeEditor) window.CW.closeNodeEditor(); });}catch(e){}
    try{$('#nodeEditorSave').addEventListener('click', function() { if (window.CW.saveNodeConfig) window.CW.saveNodeConfig(); });}catch(e){}
    try{$('#nodeEditorReset').addEventListener('click', function() { if (window.CW.resetNodeConfig) window.CW.resetNodeConfig(); });}catch(e){}
  }

  // ── Workflow Management ──
  let _wfMeta = {};
  let _currentTab = '文生图';
  let _wfEditFilename = '';
  let _wfDelFilename = '';

  // Expose _wf* vars via getter/setter for cross-module access
  Object.defineProperty(window.__APP__, '_wfMeta', {
    get: () => _wfMeta,
    set: (v) => { _wfMeta = v; }
  });
  Object.defineProperty(window.__APP__, '_wfEditFilename', {
    get: () => _wfEditFilename,
    set: (v) => { _wfEditFilename = v; }
  });
  Object.defineProperty(window.__APP__, '_wfDelFilename', {
    get: () => _wfDelFilename,
    set: (v) => { _wfDelFilename = v; }
  });
  Object.defineProperty(window.__APP__, '_currentTab', {
    get: () => _currentTab,
    set: (v) => { _currentTab = v; }
  });

  

  
  

  

  

  

  

  // ── Edit Modal ──
  
  

  

  

  

  

  // ── Delete Modal ──
  
  
  

  

  // ═══ Node Editor ══════════════════════════════════════════════════════

  

  

  

  

  
  async function wfUploadOverlay(files) {
    var zone = $('#wfUploadZone');
    var ok = 0, fail = 0;
    for (var fi = 0; fi < files.length; fi++) {
      var file = files[fi];
      if (!file.name.endsWith('.json')) { fail++; continue; }
      var fd = new FormData();
      fd.append('file', file);
      try {
        var r = await fetch(API + '/api/workflows/upload', { method: 'POST', body: fd });
        if (!r.ok) throw new Error('upload');
        ok++;
      } catch (e) { fail++; }
    }
    var msg = document.createElement('div');
    msg.className = 'wf-upload-progress ' + (fail ? 'wf-upload-err' : 'wf-upload-ok');
    msg.textContent = fail ? '完成：' + ok + ' 成功，' + fail + ' 失败' : '成功上传 ' + ok + ' 个工作流';
    if (zone && zone.parentElement) zone.parentElement.appendChild(msg);
    setTimeout(function() { msg.remove(); }, 3000);
    if (window.CW.loadWfDirs) window.CW.loadWfDirs();
  }

  function rndSeed(btnEl) {
    var input = btnEl ? btnEl.parentElement.querySelector('input') : null;
    if (input) input.value = Math.floor(Math.random() * Math.pow(2, 53));
  }

  // ═══ End Node Editor ═════════════════════════════════════════════════

  console.log('[BOOT] before init, window.CW=', typeof window.CW);
  if (!window.CW) window.CW = {};
  console.log('[BOOT] after window.CW init');
  // DEBUG: verify function exists before Object.assign
  console.log('[DEBUG] getWFType exists:', typeof getWFType !== 'undefined');
  console.log('[DEBUG] cancelJob exists:', typeof cancelJob !== 'undefined');
  console.log('[DEBUG] window.CW keys:', Object.keys(window.CW).length);
  window.CW._logEntries = [];
  window.CW._onLog = function(entry) {
    window.CW._logEntries.push(entry);
    var body = document.getElementById('logBody');
    if (!body) return;
    var el = document.createElement('div');
    el.className = 'log-entry';
    var ts = new Date(entry.ts * 1000).toLocaleTimeString();
    el.innerHTML = '<span class="log-time">' + ts + '</span>'
      + '<span class="log-level ' + entry.level + '">' + entry.level.toUpperCase() + '</span>'
      + '<span class="log-phase">[' + entry.phase + ']</span>'
      + '<span class="log-msg">' + (entry.msg || '') + '</span>'
      + (entry.details ? '<div class="log-details">' + entry.details + '</div>' : '');
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
  };
  window.CW.toggleLog = function() {
    var panel = document.getElementById('logPanel');
    if (!panel) return;
    if (!panel.classList.contains('open')) {
      panel.classList.add('open');
      fetch(API + '/api/logs').then(function(r) { return r.json(); }).then(function(entries) {
        window.CW._logEntries = entries;
        var body = document.getElementById('logBody');
        if (body) {
          body.innerHTML = '';
          entries.forEach(function(e) { window.CW._onLog(e); });
        }
      }).catch(function(e) {});
    } else {
      panel.classList.remove('open');
    }
  };
  window.CW.closeLog = function() {
    var panel = document.getElementById('logPanel');
    if (panel) panel.classList.remove('open');
  };
  console.log('[BOOT] before Object.assign');
  Object.assign(window.CW, {
    cancelJob,
    retryJob,
    rndSeed,
    wfUploadOverlay,
    getWFType, wfTag,
    formatElapsed,
    shortSeed,
    onJobUpdate,
  });

  console.log('[BOOT] after Object.assign');
  console.log('[BOOT] getWFType=', typeof getWFType);
  window.CW = window.CW || {};
  window.CW.refreshForAuthChange = function() {
    window.__APP__.currentTargetInstance = '';
    window.__APP__.currentTargetNodeId = '';
    if (window.CW.loadWfMeta) window.CW.loadWfMeta();
    if (window.CW.loadWorkflows) window.CW.loadWorkflows();
    if (window.CW.loadHistory) window.CW.loadHistory();
    if (window.CW.pollStatus) window.CW.pollStatus();
  };
  window.CW._bootApp = function() {
    if (window.CW.__appBooted) return;
    window.CW.__appBooted = true;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
  };
  if (!window.CW.__skipAutoBoot) window.CW._bootApp();
  console.log('[BOOT] init queued');
} catch(e) {
  console.error('[FATAL] app.js IIFE error:', e.message, e.stack);
  throw e;
}
})();
