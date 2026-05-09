/**
 * ComfyUI Web v3.9 — 上图下文卡片，点击图片放大，点击文字还原参数
 */
(function () {
  'use strict';

  // ── Mobile viewport height fix (100vh includes address bar on iOS) ──
  function setVH() {
    document.documentElement.style.setProperty('--vh', `${window.innerHeight * 0.01}px`);
  }
  window.addEventListener('resize', setVH);
  window.addEventListener('orientationchange', setVH);
  setVH();

  const BASE = location.pathname.replace(/\/+$/, '');
  const API = BASE;

  let ws = null;
  let currentWF = null;
  let advOpen = false;
  let jobs = {};
  let jobFields = {};
  // job_id → fields snapshot
  let historyItems = [];
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
  window.__APP__ = { $, $$, escH, escA, API, jobs, historyItems };

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
    var othersBtn = document.querySelector('#svcOthers');
    var othersState = document.querySelector('#othersState');
    if (othersBtn) othersBtn.className = 'svc-btn ' + (d.vllm ? 'on' : 'off');
    if (othersState) othersState.textContent = d.vllm ? 'vLLM' : '-';
  }

  function updateGPU(g) {
    if (!g) return;
    const fill = $('#vramFill');
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
    $('#vramText').textContent =
      `${(g.vram_used_mb / 1024).toFixed(1)} / ${(g.vram_total_mb / 1024).toFixed(0)} GB (${pct}%)`;
    $('#gpuTemp').textContent = `${temp} °C`;
    $('#gpuUtil').textContent = `GPU ${g.util_pct}%`;
    if (!$('#vramSegments').dataset.done) {
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
    var othersBtn = $('#svcOthers');
    if (othersBtn)
      othersBtn.addEventListener('click', function () {
        openInstPopup('others');
      });
  }
  // ══════════════════════════════════════════════════════════════════════════
  //  Workflows
  // ══════════════════════════════════════════════════════════════════════════

  

  

  
  
  

  

  

  
 // zone-aware field metadata for current workflow

  

  

  

  // initDropZone removed — upload card is built into loadWorkflows

  

  

  // ══════════════════════════════════════════════════════════════════════════
  //  Generate + Restore
  // ══════════════════════════════════════════════════════════════════════════

  

  

  

  

  

  

  // ══════════════════════════════════════════════════════════════════════════
  //  Jobs + Gallery
  // ══════════════════════════════════════════════════════════════════════════

  async function pollJobs() {
    try {
      const r = await fetch(`${API}/api/jobs`);
      const arr = await r.json();
      const prevCount = Object.keys(jobs).length;
      // Client-side safety: cancel jobs stuck in generating for >700s
      const now = Date.now() / 1000;
      for (const j of arr) {
        if (j.status === 'generating' && j.generating_at && now - j.generating_at > 700) {
          fetch(`${API}/api/jobs/${j.id}`, { method: 'DELETE' });
        }
      }
      for (const j of arr) {
        jobs[j.id] = j;
      }
      // Remove stale jobs no longer on server (keep error jobs even if server cleaned them up)
      const serverIds = new Set(arr.map((j) => j.id));
      for (const id of Object.keys(jobs)) {
        if (!serverIds.has(id) && jobs[id]?.status !== 'error') delete jobs[id];
      }
      const newCount = Object.keys(jobs).length;
      // Rebuild if count changed OR any status changed (e.g. error from instance stop)
      var statusChanged = false;
      if (newCount === prevCount) {
        for (var j of arr) {
          var old = jobs[j.id];
          if (old && old.status !== j.status) { statusChanged = true; break; }
        }
      }
      if (newCount !== prevCount || statusChanged) { if (window.CW.renderGallery) window.CW.renderGallery(); }
    } catch {}
  }

  function onJobUpdate(job) {
    const prev = jobs[job.id];
    // Show toast on status transitions (ignoring initial load)
    if (prev && prev.status !== job.status) {
      var wf = (job.workflow || '').replace('.json', '');
      var shortId = job.id.slice(-6);
      var wfTag = getWFType(job.workflow);
      var typeLabel = wfTag ? wfTag.text : '';
      if (job.status === 'queued') showToast(shortId + ' ' + typeLabel + '任务 排队中', 'queued');
      else if (job.status === 'generating') showToast(shortId + ' ' + typeLabel + '任务 出图开始', 'generating');
      else if (job.status === 'done') showToast(shortId + ' ' + typeLabel + '任务 出图完成', 'done');
      else if (job.status === 'error') showToast(shortId + ' ' + typeLabel + '任务 出图失败', 'error');
    }
    jobs[job.id] = job;
    if (job.status === 'done' && (!prev || prev.status !== 'done')) {
      if (prev && prev.status === 'error') return;
      delete jobs[job.id];
      window.CW.loadHistory();
      return;
    }
    if (prev && prev.status === job.status && updateJobCardInPlace(job)) return;
    window.CW.renderGallery();
  }

  /** Targeted DOM update for a single job card (progress/message/timer only). */
  function updateJobCardInPlace(job) {
    const card = document.querySelector(`[data-job-id="${job.id}"]`);
    if (!card) return false;

    // Update CSS class
    card.className = `gi job-card ${job.status}`;

    // Status text
    const st = card.querySelector('.job-status-text');
    if (st && job.status === 'queued') {
      st.textContent = '等待前序任务中';
      st.className = 'job-status-text queued';
    } else if (st && job.status !== 'queued') {
      st.textContent = job.message || job.status;
      st.className = `job-status-text ${job.status}`;
    }

    // Detail message
    const det = card.querySelector('.gi-detail');
    if (det && job.message) {
      det.textContent = job.message;
      det.title = job.message;
    }

    // Progress bar — always update for generating jobs
    if (job.status === 'generating') {
      const pct = job.progress?.pct || 0;
      let bar = card.querySelector('.gi-progress-fill');
      if (bar) bar.style.width = pct + '%';
    }

    // Meta status label (first span in .gi-meta)
    const metaSpan = card.querySelector('.gi-meta span:first-child');
    if (metaSpan) {
      if (job.status === 'generating') {
        const phaseMsg = escH(job.message || '出图中');
        const genTs = job.generating_at || 0;
        let timer = metaSpan.querySelector('.gi-timer');
        if (timer) {
          // Update phase text before timer
          const prev = timer.previousSibling;
          if (prev && prev.nodeType === 3) prev.textContent = phaseMsg + ' ';
          else metaSpan.insertBefore(document.createTextNode(phaseMsg + ' '), timer);
        } else {
          metaSpan.innerHTML = phaseMsg;
        }
      } else {
        metaSpan.textContent = job.status === 'error' ? '失败' : '排队中';
      }
    }

    // If image just appeared (was placeholder → now has image), swap in the image
    if (job.image) {
      const imgDiv = card.querySelector('.gi-img');
      if (imgDiv && imgDiv.classList.contains('job-placeholder')) {
        const label = job.prompt_preview || job.workflow?.replace('.json', '') || '...';
        imgDiv.className = 'gi-img';
        imgDiv.setAttribute('onclick', `event.stopPropagation();CW.openJobLB('${escA(job.image)}','${escA(label)}')`);
        imgDiv.innerHTML = `<img src="${API}/api/images/${job.image}" loading="lazy" alt="">`;
      }
    }
    return true;
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


  // ══════════════════════════════════════════════════════════════════════════
  //  Gallery Filters
  // ══════════════════════════════════════════════════════════════════════════


  

  

  

  

  

  /** Build a single history card HTML string */
  

  /** Append newly visible history cards without rebuilding the DOM (no flicker) */
  

  
  

  

  // ══════════════════════════════════════════════════════════════════════════
  //  History
  // ══════════════════════════════════════════════════════════════════════════

  

  

  async function cancelJob(jobId) {
    try {
      await fetch(`${API}/api/jobs/${jobId}`, { method: 'DELETE' });
      delete jobs[jobId];
      window.CW.renderGallery();
    } catch (e) {
      console.error('cancelJob:', e);
    }
  }

  async function retryJob(jobId) {
    try {
      const r = await fetch(`${API}/api/jobs/${jobId}/retry`, { method: 'POST' });
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
    pollStatus();
    setInterval(pollStatus, 5000);
    setInterval(() => {
      if (ws && ws.readyState === 1) ws.send('ping');
    }, 30000);
    window.CW.loadHistory && window.CW.loadHistory();
    pollJobs();
    setInterval(pollJobs, 5000);
    connectWS();
    initServiceToggles();
    window.CW.initAdvToggle && window.CW.initAdvToggle();
    window.CW.initRatioGrid && window.CW.initRatioGrid();
    window.CW.initOverlayUpload && window.CW.initOverlayUpload();
    window.CW.initResizeHandle && window.CW.initResizeHandle();
    setInterval(tickTimers, 1000);
    initDragScroll('.wf-grid');
  // Show/hide clear button on prompt input
  var pi = $('#promptInput');
  var cb = $('#clearPromptBtn');
  if (pi && cb) {
    pi.addEventListener('input', function() { cb.style.display = pi.value ? '' : 'none'; });
    cb.style.display = pi.value ? '' : 'none';
  }
  $('#btnGenerate').addEventListener('click', function() { if (window.CW.doGenerate) window.CW.doGenerate(); });
    $('#lightbox').addEventListener('click', (e) => {
      if (e.target === $('#lightbox') || e.target === $('#lbImg')) { if (window.CW.closeLB) window.CW.closeLB(); }
    });
    // Workflow management overlay
    $('#tbWfMgrBtn').addEventListener('click', function() { if (window.CW.openWfMgr) window.CW.openWfMgr(); });
    $('#wfOverlayClose').addEventListener('click', function() { if (window.CW.closeWfMgr) window.CW.closeWfMgr(); });
    $('#wfEditClose').addEventListener('click', function() { if (window.CW.closeWfEdit) window.CW.closeWfEdit(); });
    $('#wfEditCancel').addEventListener('click', function() { if (window.CW.closeWfEdit) window.CW.closeWfEdit(); });
    $('#wfEditSave').addEventListener('click', function() { if (window.CW.saveWfEdit) window.CW.saveWfEdit(); });
    $('#wfEditThumb').addEventListener('click', function() { var el = $('#wfEditThumbInput'); if (el) el.click(); });
    $('#wfEditThumbInput').addEventListener('change', function() { if (window.CW.onWfThumbUpload) window.CW.onWfThumbUpload(); });
    $('#wfEditTagSelect').addEventListener('change', function() { if (window.CW.onAddWfTag) window.CW.onAddWfTag(); });
    $('#wfDelCancel').addEventListener('click', function() { if (window.CW.closeWfDel) window.CW.closeWfDel(); });
    $('#wfDelConfirm').addEventListener('click', function() { if (window.CW.confirmWfDel) window.CW.confirmWfDel(); });
    $('#nodeEditorClose').addEventListener('click', function() { if (window.CW.closeNodeEditor) window.CW.closeNodeEditor(); });
    $('#nodeEditorCancel').addEventListener('click', function() { if (window.CW.closeNodeEditor) window.CW.closeNodeEditor(); });
    $('#nodeEditorSave').addEventListener('click', function() { if (window.CW.saveNodeConfig) window.CW.saveNodeConfig(); });
    $('#nodeEditorReset').addEventListener('click', function() { if (window.CW.resetNodeConfig) window.CW.resetNodeConfig(); });
  }

  // ── Workflow Management ──
  let _wfMeta = {};
  let _currentTab = '文生图';
  let _wfEditFilename = '';
  let _wfDelFilename = '';

  
  

  // ── Workflow Directory Management ──

  

  
  

  

  

  

  

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

  if (!window.CW) window.CW = {};
  Object.assign(window.CW, {
    cancelJob,
    retryJob,
    rndSeed,
    wfUploadOverlay,
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
