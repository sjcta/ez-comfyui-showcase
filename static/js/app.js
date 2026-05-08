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
  let lbItems = [];
  let lbIdx = -1;
  let _histVisibleCount = 0;
  let _lastRenderedHistCount = 0;

  /** Calculate how many columns the masonry grid currently has */
  function _getColumnCount() {
    const gallery = $('#gallery');
    if (!gallery) return 3;
    const w = gallery.clientWidth;
    const gap = 10;
    const minCol = 140;
    return Math.max(1, Math.floor((w + gap) / (minCol + gap)));
  }

  /** Load 2 rows worth of items */
  function _batchSize() {
    return _getColumnCount() * 2;
  }

  /** Initialize first batch (called once after first history load) */
  function _ensureInitialBatch() {
    if (_histVisibleCount > 0) return;
    _histVisibleCount = Math.min(_batchSize(), (_filteredHistory.length ? _filteredHistory.length : historyItems.length)); console.log("[GALLERY DEBUG] _ensureInitialBatch: batch=" + _batchSize() + " filtered=" + _filteredHistory.length + " hist=" + historyItems.length + " => count=" + _histVisibleCount);
  }

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
  //  Shared state (window.__APP__)
  // ══════════════════════════════════════════════════════════════════════════
  window.__APP__ = {
    $: $, $$: $$, escH: escH, escA: escA, shortSeed: shortSeed, getWFType: getWFType,
    jobs: jobs, API: API,
    currentWF: null, set currentWF(v) { currentWF = v; },
  };


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
  //  Workflows
  // ══════════════════════════════════════════════════════════════════════════

  async function loadWorkflows() {
    try {
      const [r, metaR] = await Promise.all([fetch(`${API}/api/workflows`), fetch(`${API}/api/workflows/meta`)]);
      const wfs = await r.json();
      try {
        _wfMeta = await metaR.json();
      } catch (e) {
        _wfMeta = {};
      }
      var wfCountEl = $('#wfCount');
      if (wfCountEl) wfCountEl.textContent = `(${wfs.length})`;
      const grid = $('#wfGrid');
      if (!wfs.length) {
        grid.innerHTML =
          '<div style="padding:12px;color:var(--dim);text-align:center;font-size:12px">无 workflow</div>';
        return;
      }
      // Count history items per workflow + find latest thumb per workflow
      const wfCounts = {};
      const wfThumbs = {};
      for (const h of historyItems) {
        const wf = h.workflow || '';
        wfCounts[wf] = (wfCounts[wf] || 0) + 1;
        if (!wfThumbs[wf] && h.thumb) wfThumbs[wf] = h.thumb;
      }
      let cards = wfs
        .map((w) => {
          const meta = _wfMeta[w.name] || {};
          const displayName = meta.name || w.name.replace('.json', '');
          const count = wfCounts[w.name] || 0;
          const thumb = wfThumbs[w.name];
          const previewSrc = thumb ? `${API}/api/thumbs/${thumb}` : '';
          const previewImg = previewSrc
            ? `<img src="${previewSrc}" loading="lazy" alt="">`
            : `<div class="wf-card-icon">⚙</div>`;
          const typeTag = getWFType(w.name);
          const catText = typeTag ? typeTag.text : '其他';
          const typeClass = typeTag ? `wf-card-type-${typeTag.cls.replace('wf-tag-', '')}` : '';
          return `<div class="wf-card ${typeClass}" data-name="${escA(w.name)}" data-cat="${escH(catText)}" onclick="CW.selectWF('${escA(w.name)}')">
        <div class="wf-card-preview">${previewImg}</div>
        <div class="wf-card-body">
          <div class="wf-card-name" title="${escA(w.name)}">
            <span class="wf-card-name-text">${escH(displayName)}</span>
            
          </div>
        </div>
      </div>`;
        })
        .join('');
      grid.innerHTML = cards;
      // Build category tabs
      const TAB_ORDER = ['文生图', '图生图', '文生视频', '图生视频', '其他'];
      const cats = new Set(
        wfs.map((w) => {
          const t = getWFType(w.name);
          return t ? t.text : '其他';
        }),
      );
      const tabsEl = $('#wfTabs');
      if (tabsEl) {
        let tabHtml = '';
        for (const t of TAB_ORDER) {
          if (cats.has(t)) {
            const catWfs = wfs.filter(w => { const tag = getWFType(w.name); return tag ? tag.text === t : t === '其他'; });
            tabHtml += `<button class="wf-tab ${_currentTab === t ? 'active' : ''}" data-tab="${t}" onclick="CW.switchTab('${t}')"><span>${t}</span> (${catWfs.length})</button>`;
          }
        }
        tabsEl.innerHTML = tabHtml;
      }
      // Apply current tab filter
      _applyTabFilter();
      // Restore last-used workflow from localStorage, fallback to first
      let saved = '';
      try {
        saved = localStorage.getItem('cw:lastWF') || '';
      } catch {}
      const target =
        currentWF && wfs.find((w) => w.name === currentWF)
          ? currentWF
          : saved && wfs.find((w) => w.name === saved)
            ? saved
            : wfs[0].name;
      if (!currentWF || currentWF !== target) selectWF(target);
      else highlightWF();
    } catch (e) {
      console.error('loadWorkflows:', e);
    }
  }

  async function selectWF(name) {
    currentWF = name;
    try {
      localStorage.setItem('cw:lastWF', name);
    } catch {}
    highlightWF();
    // Scroll active card into view
    var ac = $$('.wf-card.active')[0];
    if (ac) ac.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    // Show gen section when workflow is selected
    var genTitle = $('#genTitle');
    var genForm = $('#genForm');
    var genFooter = $('.gen-footer');
    if (genTitle) {
      genTitle.style.display = '';
      genTitle.textContent = name.replace('.json', '') + ' 快速出图';
    }
    if (genForm) {
      genForm.style.display = '';
      genForm.classList.add('mobile-open');
    }
    if (genFooter) {
      genFooter.style.display = '';
      genFooter.classList.add('mobile-open');
    }
    const ws = $('#wfSummary');
    if (ws) ws.textContent = name.replace('.json', '');
    try {
      const r = await fetch(`${API}/api/workflows/${encodeURIComponent(name)}/fields`);
      const d = await r.json();
      const fields = d.fields || [];
      _wfFieldMeta = fields.map((f) => ({
        key: f.node_id + '::' + f.field,
        node_id: f.node_id,
        class_type: f.class_type,
        field: f.field,
        zone: f.zone || 'advanced',
        visible: f.visible !== false,
        type: f.type,
        label: f.label,
        value: f.value,
        options: f.options,
        step: f.step,
        min: f.min,
        max: f.max,
      }));
      renderAdvFields(fields);
      // Detect if workflow has width/height (LatentImage nodes)
      const hasSize = fields.some((f) => f.field === 'width' && f.class_type.includes('LatentImage'));
      const sizeSection = $('#sizeSection');
      if (sizeSection) sizeSection.style.display = hasSize ? '' : 'none';
      for (const f of fields) {
        if (f.field === 'width' && f.class_type.includes('LatentImage')) $('#widthInput').value = f.value;
        if (f.field === 'height' && f.class_type.includes('LatentImage')) $('#heightInput').value = f.value;
      }
      // Set prompt placeholder based on detected text-encode fields
      const promptField = fields.find(
        (f) => f.zone === 'user_input' && (f.type === 'textarea' || f.class_type.includes('TextEncode')),
      );
      const promptEl = $('#promptInput');
      const promptLabel = $('#promptLabel');
      if (promptEl) {
        if (promptField) {
          const labelText = promptField.label || '提示词';
          const nodeInfo = promptField.node_title ? ' [' + promptField.node_title.split('(')[0].trim() + ']' : '';
          promptEl.placeholder = labelText + '...';
          if (promptLabel) promptLabel.textContent = labelText + nodeInfo;
        } else {
          promptEl.placeholder = '输入提示词...';
          if (promptLabel) promptLabel.textContent = '提示词';
        }
      }
    } catch (e) {
      console.error('selectWF:', e);
    }
  }

  function highlightWF() {
    $$('.wf-card').forEach((el) => el.classList.toggle('active', el.dataset.name === currentWF));
  }
  function clearWF() {
    currentWF = '';
    highlightWF();
    var genTitle = $('#genTitle');
    var genForm = $('#genForm');
    var genFooter = $('.gen-footer');
    if (genTitle) genTitle.style.display = 'none';
    if (genForm) {
      genForm.style.display = 'none';
      genForm.classList.remove('mobile-open');
    }
    if (genFooter) {
      genFooter.style.display = 'none';
      genFooter.classList.remove('mobile-open');
    }
  }
  function switchTab(tab) {
    _currentTab = tab;
    // Update active tab button
    $$('.wf-tab').forEach((el) => el.classList.toggle('active', el.dataset.tab === tab));
    _applyTabFilter();
    // Scroll workflow grid back to start
    var wfGrid = $('#wfGrid');
    if (wfGrid) wfGrid.scrollLeft = 0;
  }

  function _applyTabFilter() {
    $$('.wf-card').forEach((el) => {
      const cat = el.dataset.cat || '其他';
      el.style.display = cat === _currentTab ? '' : 'none';
    });
  }

  function toggleGenForm() {
    const form = $('#genForm');
    const btn = $('#genToggleMobile');
    const open = form.classList.toggle('mobile-open');
    if (btn) btn.textContent = open ? '⚡ 收起 ▴' : '⚡ 快速出图 ▾';
  }

  function renderAdvFields(fields) {
    const box = $('#advFields');

    // ── Zone-aware field routing ──
    // user_input text-encode fields → main prompt textarea (handled in doGenerate)
    // user_input LoadImage → ref image section
    // user_input LatentImage size → size section
    // advanced → advanced params
    // hidden → not shown

    // Detect LoadImage in user_input zone
    _loadImageFields = fields.filter((f) => {
      if (f.class_type !== 'LoadImage' || f.field !== 'image') return false;
      const zone = f.zone || 'advanced';
      return zone === 'user_input';
    });
    // Fallback: if no zone info, use old logic
    if (!_loadImageFields.length && !fields.some((f) => f.zone)) {
      _loadImageFields = fields.filter((f) => f.class_type === 'LoadImage' && f.field === 'image');
    }
    const hasLoadImage = _loadImageFields.length > 0;
    const section = $('#refImageSection');
    if (section) section.style.display = hasLoadImage ? '' : 'none';
    if (hasLoadImage) _initRefImageZone();
    else _resetRefImage();

    // Build advanced fields: only 'advanced' zone (or fallback for unzoned)
    const hasZones = fields.some((f) => f.zone);
    const advFields = fields.filter((f) => {
      const zone = f.zone || 'advanced';
      // Skip hidden zone OR explicitly invisible fields
      if (zone === 'hidden') return false;
      if (f.visible === false) return false;
      // Skip user_input fields that are handled by dedicated sections
      if (zone === 'user_input') {
        // Text-encode → main prompt
        if (f.type === 'textarea' || (f.class_type && f.class_type.includes('TextEncode'))) return false;
        // LoadImage → ref image section
        if (f.class_type === 'LoadImage' && f.field === 'image') return false;
        // LatentImage size → size section
        if (f.class_type && f.class_type.includes('LatentImage') && (f.field === 'width' || f.field === 'height'))
          return false;
      }
      // For unzoned workflows, use old filtering
      if (!hasZones) {
        if (f.class_type === 'CLIPTextEncode' && f.field === 'text') return false;
        if (f.class_type && f.class_type.includes('LatentImage') && (f.field === 'width' || f.field === 'height'))
          return false;
        if (f.class_type === 'LoadImage' && f.field === 'image') return false;
      }
      // Skip output zone (read-only, handled by SaveImage)
      if (zone === 'output') return false;
      return true;
    });

    if (!advFields.length) {
      box.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:6px 0">无可编辑参数</div>';
      return;
    }
    let html = '';
    for (const f of advFields) {
      const key = `${f.node_id}::${f.field}`;
      const val = f.value ?? '';
      html += `<div class="fg"><label>${escH(f.label)} <span class="node-tag">[${escH(f.node_title)}]</span></label>`;
      switch (f.type) {
        case 'select': {
          const opts = (f.options || [])
            .map((o) => `<option value="${escA(o)}" ${o === val ? 'selected' : ''}>${escH(o)}</option>`)
            .join('');
          html += `<select data-key="${key}">${opts}</select>`;
          break;
        }
        case 'seed':
          html += `<div class="seed-group"><input type="number" data-key="${key}" data-type="number" value="${val}"><button type="button" class="btn-dice" onclick="CW.rndSeed(this)">🎲</button></div>`;
          break;
        case 'number': {
          const step = f.step || 1,
            mn = f.min ?? '',
            mx = f.max ?? '';
          html += `<input type="number" data-key="${key}" value="${val}" step="${step}" ${mn !== '' ? `min="${mn}"` : ''} ${mx !== '' ? `max="${mx}"` : ''}>`;
          break;
        }
        default:
          html += `<input type="text" data-key="${key}" value="${escH(String(val))}">`;
      }
      html += `</div>`;
    }
    box.innerHTML = html;
  }

  let _loadImageFields = [];
  let _wfFieldMeta = []; // zone-aware field metadata for current workflow

  function _initRefImageZone() {
    const zone = $('#refImageZone');
    if (!zone || zone._bound) return;
    zone._bound = true;
    zone.addEventListener('click', () => $('#refImageFile').click());
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      const file = e.dataTransfer?.files?.[0];
      if (file && file.type.startsWith('image/')) _uploadRefImage(file);
    });
    $('#refImageFile').addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (file) _uploadRefImage(file);
    });
  }

  async function _uploadRefImage(file) {
    if (!file) {
      alert('未选择文件');
      return;
    }
    const fd = new FormData();
    try {
      fd.append('file', file, file.name || 'upload.png');
    } catch (e) {
      fd.append('file', file);
    }
    try {
      const r = await fetch(`${API}/api/upload-image`, { method: 'POST', body: fd });
      if (!r.ok) {
        let msg = '上传失败 (' + r.status + ')';
        try {
          const d = await r.json();
          msg = d.detail || msg;
        } catch (e) {}
        throw new Error(msg);
      }
      const d = await r.json();
      if (!d.filename) throw new Error('服务端未返回文件名');
      $('#refImageValue').value = d.filename;
      const preview = $('#refImagePreview');
      const placeholder = $('#refImagePlaceholder');
      if (preview) {
        preview.src = `${API}/api/input-image/${encodeURIComponent(d.filename)}`;
        preview.style.display = '';
      }
      if (placeholder) placeholder.style.display = 'none';
    } catch (e) {
      console.error('Upload error:', e);
      alert('图片上传失败: ' + (e.message || e));
    }
  }

  function _resetRefImage() {
    const v = $('#refImageValue');
    if (v) v.value = '';
    const p = $('#refImagePreview');
    if (p) {
      p.src = '';
      p.style.display = 'none';
    }
    const ph = $('#refImagePlaceholder');
    if (ph) ph.style.display = '';
    const f = $('#refImageFile');
    if (f) f.value = '';
  }

  // initDropZone removed — upload card is built into loadWorkflows

  async function uploadWF(file) {
    if (!file.name.endsWith('.json')) {
      alert('需要 .json 文件');
      return;
    }
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(`${API}/api/workflows/upload`, { method: 'POST', body: fd });
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.detail || '上传失败');
      }
      loadWorkflows();
    } catch (e) {
      alert('上传失败: ' + e.message);
    }
  }

  async function delWF(name) {
    if (!confirm(`删除 ${name}？`)) return;
    await fetch(`${API}/api/workflows/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (currentWF === name) currentWF = null;
    loadWorkflows();
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  Generate + Restore
  // ══════════════════════════════════════════════════════════════════════════

  async function doGenerate() {
    if (!currentWF) {
      alert('请先选择 workflow');
      return;
    }
    const btn = $('#btnGenerate');
    btn.disabled = true;
    btn.textContent = '提交中...';

    const fields = {};
    const prompt = $('#promptInput').value;
    const snapshot = { prompt, width: $('#widthInput').value, height: $('#heightInput').value, adv: {} };

    try {
      const fr = await fetch(`${API}/api/workflows/${encodeURIComponent(currentWF)}/fields`);
      const fd = await fr.json();
      for (const f of fd.fields || []) {
        const zone = f.zone || 'advanced';
        const key = `${f.node_id}::${f.field}`;
        // Text-encode in user_input zone → main prompt
        if (zone === 'user_input' && (f.type === 'textarea' || (f.class_type && f.class_type.includes('TextEncode')))) {
          fields[key] = prompt;
          continue;
        }
        // Unzoned fallback
        if (!f.zone && f.class_type === 'CLIPTextEncode' && f.field === 'text') {
          fields[key] = prompt;
          continue;
        }
        // LatentImage size
        if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'width') {
          fields[key] = parseInt($('#widthInput').value) || 1024;
          continue;
        }
        if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'height') {
          fields[key] = parseInt($('#heightInput').value) || 1920;
          continue;
        }
        // LoadImage ref
        if (f.class_type === 'LoadImage' && f.field === 'image' && (zone === 'user_input' || !f.zone)) {
          const refVal = $('#refImageValue')?.value || '';
          if (refVal) fields[key] = refVal;
          continue;
        }
      }
    } catch (e) {
      console.error(e);
    }

    $$('#advFields [data-key]').forEach((el) => {
      fields[el.dataset.key] = el.type === 'number' ? parseFloat(el.value) || 0 : el.value;
      snapshot.adv[el.dataset.key] = el.value;
    });

    try {
      const r = await fetch(`${API}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow: currentWF,
          fields,
          width: parseInt($('#widthInput').value) || 0,
          height: parseInt($('#heightInput').value) || 0,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '提交失败');
      jobFields[d.job_id] = snapshot;
      // Add job to local store immediately so the card appears without waiting for poll
      jobs[d.job_id] = {
        id: d.job_id,
        status: 'queued',
        message: '排队中...',
        workflow: currentWF,
        seed: String(d.seed),
        prompt_preview: $('#promptInput').value.slice(0, 300),
        width: parseInt($('#widthInput').value) || 0,
        height: parseInt($('#heightInput').value) || 0,
        queued_at: new Date().toLocaleTimeString('en-GB'),
      };
      renderGallery();
    } catch (e) {
      alert('出图失败: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '🚀 出图';
    }
  }

  async function restoreJob(jobId) {
    // Try local snapshot first (submitted this session)
    const snap = jobFields[jobId];
    if (snap) {
      if (snap.prompt) $('#promptInput').value = snap.prompt;
      if (snap.width) $('#widthInput').value = snap.width;
      if (snap.height) $('#heightInput').value = snap.height;
      for (const [k, v] of Object.entries(snap.adv || {})) {
        const el = $(`#advFields [data-key="${k}"]`);
        if (el) el.value = v;
      }
      return;
    }
    // Fallback: restore from server job data
    const j = jobs[jobId];
    if (!j) return;
    // Switch to correct workflow first
    if (j.workflow && (!currentWF || j.workflow.replace('.json','') !== currentWF.replace('.json',''))) {
      const tag = getWFType(j.workflow);
      if (tag) switchTab(tag.text);
      await selectWF(j.workflow);
    }
    // Restore prompt
    if (j.prompt_preview) $('#promptInput').value = j.prompt_preview;
    // Restore dimensions
    if (j.width && j.height) {
      $('#widthInput').value = j.width;
      $('#heightInput').value = j.height;
      if (typeof highlightRatio === 'function') highlightRatio(j.width, j.height);
    }
    // Restore seed
    if (j.seed) {
      const seedEl = document.querySelector('[data-field="seed"]') || document.querySelector('input[placeholder*="seed"]');
      if (seedEl) seedEl.value = j.seed;
    }
    // Restore advanced fields from server fields data
    if (j.fields && typeof j.fields === 'object') {
      for (const [k, v] of Object.entries(j.fields)) {
        if (k === 'prompt_preview') continue;
        const el = $(`#advFields [data-key="${k}"]`);
        if (el) el.value = v;
      }
    }
  }

  async function fillFormFromHistory(idx) {
    const h = historyItems[idx];
    if (!h) return;
    // Switch to correct workflow first (so advanced fields exist in DOM)
    if (h.workflow && h.workflow.replace('.json', '') !== currentWF.replace('.json', '')) {
      // Auto-switch tab to match this workflow's category
      const tag = getWFType(h.workflow);
      switchTab(tag ? tag.text : '其他');
      await selectWF(h.workflow);
    }
    if (h.prompt) $('#promptInput').value = h.prompt;
    // Scale dimensions to fit within 1920, proportional, divisible by 64
    if (h.width && h.height) {
      const [w, h2] = scaleDim(h.width, h.height);
      $('#widthInput').value = w;
      $('#heightInput').value = h2;
      highlightRatio(w, h2);
    }
    // Restore advanced fields if available
    if (h.field_values) {
      for (const [k, v] of Object.entries(h.field_values)) {
        const el = $(`#advFields [data-key="${k}"]`);
        if (el) el.value = v;
      }
    }
    // Restore seed (covers old items without field_values, and ensures actual seed is used)
    if (h.seed) {
      const seedInput = document.querySelector('.seed-group input');
      if (seedInput) seedInput.value = h.seed;
    }
    document.querySelector('.col-left').scrollTop = 0;
  }

  function scaleDim(w, h, maxSide = 1920) {
    const longest = Math.max(w, h);
    if (longest <= maxSide && w % 64 === 0 && h % 64 === 0) return [w, h];
    const scale = maxSide / longest;
    const sw = Math.round((w * scale) / 64) * 64;
    const sh = Math.round((h * scale) / 64) * 64;
    return [Math.max(sw, 256), Math.max(sh, 256)];
  }

  function highlightRatio(w, h) {
    $$('.ratio-btn').forEach((b) => {
      const bw = parseInt(b.dataset.w),
        bh = parseInt(b.dataset.h);
      b.classList.toggle('active', bw === w && bh === h);
    });
  }

  function initRatioGrid() {
    $$('.ratio-btn').forEach((b) => {
      b.addEventListener('click', () => {
        $$('.ratio-btn').forEach((x) => x.classList.remove('active'));
        b.classList.add('active');
        $('#widthInput').value = b.dataset.w;
        $('#heightInput').value = b.dataset.h;
      });
    });
    // Sync: if user manually changes inputs, clear active highlight
    ['#widthInput', '#heightInput'].forEach((sel) => {
      $(sel).addEventListener('input', () => {
        const w = parseInt($('#widthInput').value) || 0,
          h = parseInt($('#heightInput').value) || 0;
        highlightRatio(w, h);
      });
    });
  }

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
      if (newCount !== prevCount || statusChanged) renderGallery();
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
      loadHistory();
      return;
    }
    if (prev && prev.status === job.status && updateJobCardInPlace(job)) return;
    renderGallery();
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

  let _galleryFilters = { type: '', size: '', style: '', workflow: '' };
  let _filteredHistory = [];

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

  function applyFilters() {
    var el;
    el = document.getElementById("gfType");
    _galleryFilters.type = el ? el.value : "";
    el = document.getElementById("gfSize");
    _galleryFilters.size = el ? el.value : "";
    el = document.getElementById("gfStyle"); _galleryFilters.style = el ? el.value.toLowerCase() : "";
    el = document.getElementById("gfWF");    _galleryFilters.workflow = el ? el.value : "";
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
    if(el) el.value = "";
    el = document.getElementById("gfSize");
    if(el) el.value = "";
    el = document.getElementById("gfStyle"); if(el) el.value = "";
    el = document.getElementById("gfWF");    if(el) el.value = "";
    _filteredHistory = _filterHistory(historyItems);
    _histVisibleCount = 0;
    _lastRenderedHistCount = 0;
    _lastGalleryHash = "";
    renderGallery();
  }

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

  let _renderTimer = null;
  let _lastGalleryHash = '';
  function renderGallery() {
    if (_renderTimer) return; // debounce: coalesce rapid updates
    _renderTimer = requestAnimationFrame(() => {
      _renderTimer = null;
      _renderGalleryImpl();
    });
  }

  /** Build a single history card HTML string */
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

  /** Append newly visible history cards without rebuilding the DOM (no flicker) */
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

    let fragment = '';
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

  function _galleryHash(jobsObj, histArr) {
    // Only structural changes trigger full rebuild: job added/removed, status transitions, history items added/removed
    let s = '';
    for (const j of Object.values(jobsObj)) {
      s += j.id + j.status + '|';
    }
    return s + '::' + histArr.length;
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

    let html = '';

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

  let _sentinelObs = null;
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

  // ══════════════════════════════════════════════════════════════════════════
  //  History
  // ══════════════════════════════════════════════════════════════════════════

  async function loadHistory() {
    try {
      const r = await fetch(`${API}/api/history`);
      historyItems = await r.json();
      _lastGalleryHash = '';
      _populateFilterOptions();
      applyFilters();
      loadWorkflows();
    } catch (e) {
      console.error('loadHistory:', e);
    }
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

  async function cancelJob(jobId) {
    try {
      await fetch(`${API}/api/jobs/${jobId}`, { method: 'DELETE' });
      delete jobs[jobId];
      renderGallery();
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

  function openLB(idx) {
    lbIdx = idx;
    renderLB();
    $('#lightbox').classList.add('open');
    document.body.style.overflow = 'hidden';
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

  function closeLB() {
    $('#lightbox').classList.remove('open');
    document.body.style.overflow = '';
    lbIdx = -1;
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

  function lbNav(dir) {
    lbIdx = Math.max(0, Math.min(lbIdx + dir, lbItems.length - 1));
    renderLB();
  }

  document.addEventListener('keydown', (e) => {
    if (!$('#lightbox').classList.contains('open')) return;
    if (e.key === 'Escape') closeLB();
    if (e.key === 'ArrowLeft') lbNav(-1);
    if (e.key === 'ArrowRight') lbNav(1);
  });

  // ══════════════════════════════════════════════════════════════════════════
  //  Advanced toggle / Seed / Init
  // ══════════════════════════════════════════════════════════════════════════

  function initAdvToggle() {
    $('#advToggle').addEventListener('click', () => {
      advOpen = !advOpen;
      $('#advToggle').classList.toggle('open', advOpen);
      $('#advBody').classList.toggle('open', advOpen);
    });
  }

  function initOverlayUpload() {
    const zone = $('#wfUploadZone');
    const input = $('#wfUploadInput');
    if (!zone || !input) return;
    zone.addEventListener('click', (e) => {
      if (e.target.tagName === 'LABEL') return; // let label click through
      input.click();
    });
    input.addEventListener('change', () => {
      if (input.files.length) wfUploadOverlay(Array.from(input.files));
      input.value = '';
    });
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      const files = Array.from(e.dataTransfer.files).filter((f) => f.name.endsWith('.json'));
      if (files.length) wfUploadOverlay(files);
    });
  }

  async function wfUploadOverlay(files) {
    const zone = $('#wfUploadZone');
    let ok = 0,
      fail = 0;
    for (const file of files) {
      if (!file.name.endsWith('.json')) {
        fail++;
        continue;
      }
      const fd = new FormData();
      fd.append('file', file);
      try {
        const r = await fetch(`${API}/api/workflows/upload`, { method: 'POST', body: fd });
        if (!r.ok) throw new Error('upload');
        ok++;
      } catch (e) {
        fail++;
      }
    }
    // Show result briefly
    const msg = document.createElement('div');
    msg.className = 'wf-upload-progress ' + (fail ? 'wf-upload-err' : 'wf-upload-ok');
    msg.textContent = fail ? `完成：${ok} 成功，${fail} 失败` : `成功上传 ${ok} 个工作流`;
    zone.parentElement.appendChild(msg);
    setTimeout(() => msg.remove(), 3000);
    loadWorkflows();
    loadWfMeta();
  }

  function rndSeed(btnEl) {
    const input = btnEl ? btnEl.parentElement.querySelector('input') : null;
    if (input) input.value = Math.floor(Math.random() * 2 ** 53);
  }

  /** Enable drag-to-scroll on horizontal scroll containers */
  function initDragScroll(selector) {
    var el = document.querySelector(selector);
    if (!el) return;
    var isDown = false, startX, scrollLeft;
    el.addEventListener("mousedown", function(e) {
      isDown = true;
      startX = e.pageX - el.offsetLeft;
      scrollLeft = el.scrollLeft;
      el.style.scrollSnapType = "none";
      el.classList.add("dragging");
    });
    el.addEventListener("mouseleave", function() {
      if (!isDown) return;
      isDown = false;
      el.style.scrollSnapType = "";
      el.classList.remove("dragging");
    });
    el.addEventListener("mouseup", function() {
      if (!isDown) return;
      isDown = false;
      el.style.scrollSnapType = "";
      el.classList.remove("dragging");
    });
    el.addEventListener("mousemove", function(e) {
      if (!isDown) return;
      e.preventDefault();
      var x = e.pageX - el.offsetLeft;
      var walk = (x - startX);
      el.scrollLeft = scrollLeft - walk;
    });
  }

  /** Show a floating toast notification */
function showToast(message, type) {
  var container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  var icons = { queued: '🕐', generating: '🎨', done: '✅', error: '❌' };
  // Dedup: remove existing toast with same message
  var existing = container.querySelectorAll('.toast');
  for (var ei = 0; ei < existing.length; ei++) {
    if (existing[ei].textContent.indexOf(message) >= 0) {
      existing[ei].parentNode.removeChild(existing[ei]);
      break;
    }
  }
  var t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.innerHTML = '<span class="toast-icon">' + (icons[type] || 'ℹ️') + '</span>' + escH(message);
  container.appendChild(t);
  setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 4000);
}

/** Clear the prompt textarea and hide the clear button */
function clearPrompt() {
  var inp = $('#promptInput');
  if (inp) { inp.value = ''; inp.dispatchEvent(new Event('input')); inp.focus(); }
}

function init() {
    if (A.pollStatus) A.pollStatus();
    setInterval(function() { if (A.pollStatus) A.pollStatus(); }, 5000);
    setInterval(() => {
      if (ws && ws.readyState === 1) ws.send('ping');
    }, 30000);
    loadHistory();
    pollJobs();
    setInterval(pollJobs, 5000);
    connectWS();
    if (window._initStatusModule) window._initStatusModule();
    initAdvToggle();
    initRatioGrid();
    initOverlayUpload();
    initResizeHandle();
    setInterval(tickTimers, 1000);
    initDragScroll('.wf-grid');
  // Show/hide clear button on prompt input
  var pi = $('#promptInput');
  var cb = $('#clearPromptBtn');
  if (pi && cb) {
    pi.addEventListener('input', function() { cb.style.display = pi.value ? '' : 'none'; });
    cb.style.display = pi.value ? '' : 'none';
  }
  $('#btnGenerate').addEventListener('click', doGenerate);
    $('#lightbox').addEventListener('click', (e) => {
      if (e.target === $('#lightbox') || e.target === $('#lbImg')) closeLB();
    });
    // Workflow management overlay
    $('#tbWfMgrBtn').addEventListener('click', openWfMgr);
    $('#wfOverlayClose').addEventListener('click', closeWfMgr);
    $('#wfEditClose').addEventListener('click', closeWfEdit);
    $('#wfEditCancel').addEventListener('click', closeWfEdit);
    $('#wfEditSave').addEventListener('click', saveWfEdit);
    $('#wfEditThumb').addEventListener('click', () => $('#wfEditThumbInput').click());
    $('#wfEditThumbInput').addEventListener('change', onWfThumbUpload);
    $('#wfEditTagSelect').addEventListener('change', onAddWfTag);
    $('#wfDelCancel').addEventListener('click', closeWfDel);
    $('#wfDelConfirm').addEventListener('click', confirmWfDel);
    $('#nodeEditorClose').addEventListener('click', closeNodeEditor);
    $('#nodeEditorCancel').addEventListener('click', closeNodeEditor);
    $('#nodeEditorSave').addEventListener('click', saveNodeConfig);
    $('#nodeEditorReset').addEventListener('click', resetNodeConfig);
  }

  // ── Workflow Management ──
  let _wfMeta = {};
  let _currentTab = '文生图';
  let _wfEditFilename = '';
  let _wfDelFilename = '';

  function openWfMgr() {
    $('#wfOverlay').classList.add('open');
    loadWfMeta();
    loadWfDirs();
  }
  function closeWfMgr() {
    $('#wfOverlay').classList.remove('open');
  }

  // ── Workflow Directory Management ──

  async function loadWfDirs() {
    try {
      const r = await fetch(API + '/api/workflow-dirs');
      const dirs = await r.json();
      const list = $('#wfDirsList');
      if (!list) return;
      list.innerHTML = dirs
        .map((d) => {
          const escPath = escA(d.path);
          const status = d.exists
            ? `<span class="wf-dir-count">${d.count} workflows</span>`
            : `<span class="wf-dir-missing">⚠ 不存在</span>`;
          const delBtn =
            dirs.length > 1
              ? `<button class="wf-dir-del" onclick="CW.removeWfDir('${escPath}')" title="移除">✕</button>`
              : '';
          return `<div class="wf-dir-item">
        <span class="wf-dir-path" title="${escPath}">${escH(d.path)}</span>
        ${status}
        ${delBtn}
      </div>`;
        })
        .join('');
    } catch (e) {
      console.error('loadWfDirs:', e);
    }
  }

  function showAddDir() {
    const el = $('#wfDirsAdd');
    if (el) {
      el.style.display = 'flex';
      $('#wfDirInput').focus();
    }
  }
  function hideAddDir() {
    const el = $('#wfDirsAdd');
    if (el) {
      el.style.display = 'none';
      $('#wfDirInput').value = '';
    }
  }

  async function addWfDir() {
    const input = $('#wfDirInput');
    if (!input) return;
    const path = input.value.trim();
    if (!path) return;
    try {
      const r = await fetch(API + '/api/workflow-dirs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.detail || '添加失败');
      }
      hideAddDir();
      loadWfDirs();
      loadWorkflows();
    } catch (e) {
      alert('添加失败: ' + e.message);
    }
  }

  async function removeWfDir(path) {
    if (!confirm(`移除目录？\n${path}\n\n（不会删除目录中的文件）`)) return;
    try {
      const r = await fetch(API + `/api/workflow-dirs?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.detail || '移除失败');
      }
      loadWfDirs();
      loadWorkflows();
    } catch (e) {
      alert('移除失败: ' + e.message);
    }
  }

  async function loadWfMeta() {
    try {
      const r = await fetch(API + '/api/workflows/meta');
      _wfMeta = await r.json();
    } catch (e) {
      _wfMeta = {};
    }
    renderWfGrid();
  }

  function renderWfGrid() {
    const grid = $('#wfOverlayGrid');
    const empty = $('#wfOverlayEmpty');
    const entries = Object.entries(_wfMeta);
    const wfFiles = new Set();
    try {
      for (const f of Object.values(jobs || {})) {
        if (f.workflow) wfFiles.add(f.workflow);
      }
    } catch (e) {}
    $('#wfOverlayCount').textContent = `(${entries.length})`;
    if (!entries.length) {
      grid.innerHTML = '';
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';

    let html = '';
    for (const [fname, meta] of entries) {
      const displayName = meta.name || fname.replace('.json', '');
      const tags = meta.tags || [];
      const thumbUrl = meta.thumbnail ? `${API}/api/workflows/thumbnail/${meta.thumbnail}` : '';
      const tagHtml = tags
        .map((t) => {
          const cls = t === '图生图' ? 'i2i' : t === '文生图' ? 't2i' : 'res';
          return `<span class="wf-mgr-tag ${cls}">${escH(t)}</span>`;
        })
        .join('');
      html += `<div class="wf-mgr-card" data-fname="${escA(fname)}">
      <div class="wf-mgr-thumb" onclick="CW.onWfThumbClick('${escA(fname)}')">
        ${thumbUrl ? `<img src="${thumbUrl}" alt="">` : `<div class="wf-mgr-thumb-placeholder">📷</div>`}
      </div>
      <div class="wf-mgr-body">
        <div class="wf-mgr-name" title="${escA(displayName)}">${escH(displayName)}</div>
        <div class="wf-mgr-filename" title="${escA(fname)}">${escH(fname)}</div>
        <div class="wf-mgr-tags">${tagHtml || '<span style="color:var(--dim);font-size:10px">无标签</span>'}</div>
        <div class="wf-mgr-actions">
          <button class="wf-mgr-btn" onclick="CW.openWfEdit('${escA(fname)}')">✏️ 编辑</button>
          <button class="wf-mgr-btn" onclick="CW.openNodeEditor('${escA(fname)}')">🔧 节点</button>
          <button class="wf-mgr-btn danger" onclick="CW.openWfDel('${escA(fname)}')">🗑️ 删除</button>
        </div>
      </div>
    </div>`;
    }
    grid.innerHTML = html;
  }

  // ── Edit Modal ──
  function openWfEdit(fname) {
    _wfEditFilename = fname;
    const meta = _wfMeta[fname] || {};
    $('#wfEditTitle').textContent = '编辑 ' + (meta.name || fname.replace('.json', ''));
    $('#wfEditName').value = meta.name || fname.replace('.json', '');
    // Render tags
    const tagsDiv = $('#wfEditTags');
    tagsDiv.innerHTML = '';
    (meta.tags || []).forEach((t) => {
      const span = document.createElement('span');
      span.className = 'wf-edit-tag';
      span.innerHTML = `${escH(t)} <span class="wf-edit-tag-remove" data-tag="${escA(t)}">✕</span>`;
      span.querySelector('.wf-edit-tag-remove').addEventListener('click', () => {
        span.remove();
      });
      tagsDiv.appendChild(span);
    });
    // Thumbnail
    const thumbUrl = meta.thumbnail ? `${API}/api/workflows/thumbnail/${meta.thumbnail}` : '';
    const img = $('#wfEditThumbImg');
    const ph = $('#wfEditThumbPlaceholder');
    if (thumbUrl) {
      img.src = thumbUrl;
      img.style.display = '';
      ph.style.display = 'none';
    } else {
      img.src = '';
      img.style.display = 'none';
      ph.style.display = '';
    }
    // Reset tag select
    $('#wfEditTagSelect').value = '';
    $('#wfEditModal').classList.add('open');
  }
  function closeWfEdit() {
    $('#wfEditModal').classList.remove('open');
  }

  function onAddWfTag(e) {
    const val = e.target.value;
    if (!val) return;
    const tagsDiv = $('#wfEditTags');
    // Prevent duplicates
    const existing = [...tagsDiv.querySelectorAll('.wf-edit-tag-remove')].map((el) => el.dataset.tag);
    if (existing.includes(val)) {
      e.target.value = '';
      return;
    }
    const span = document.createElement('span');
    span.className = 'wf-edit-tag';
    span.innerHTML = `${escH(val)} <span class="wf-edit-tag-remove" data-tag="${escA(val)}">✕</span>`;
    span.querySelector('.wf-edit-tag-remove').addEventListener('click', () => {
      span.remove();
    });
    tagsDiv.appendChild(span);
    e.target.value = '';
  }

  async function onWfThumbUpload(e) {
    const file = e.target.files[0];
    if (!file || !_wfEditFilename) return;
    const fd = new FormData();
    fd.append('filename', _wfEditFilename);
    fd.append('file', file);
    try {
      await fetch(API + '/api/workflows/meta/thumbnail', { method: 'POST', body: fd });
      // Show preview
      const reader = new FileReader();
      reader.onload = (ev) => {
        $('#wfEditThumbImg').src = ev.target.result;
        $('#wfEditThumbImg').style.display = '';
        $('#wfEditThumbPlaceholder').style.display = 'none';
      };
      reader.readAsDataURL(file);
    } catch (e) {}
    e.target.value = '';
  }

  async function saveWfEdit() {
    if (!_wfEditFilename) return;
    const name = $('#wfEditName').value.trim() || _wfEditFilename.replace('.json', '');
    const tags = [...$('#wfEditTags').querySelectorAll('.wf-edit-tag-remove')].map((el) => el.dataset.tag);
    try {
      await fetch(API + '/api/workflows/meta/' + encodeURIComponent(_wfEditFilename), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, tags }),
      });
      _wfMeta[_wfEditFilename] = { ...(_wfMeta[_wfEditFilename] || {}), name, tags };
    } catch (e) {}
    closeWfEdit();
    renderWfGrid();
    // Also refresh main workflow grid if it shows names
    loadWorkflows();
  }

  function onWfThumbClick(fname) {
    _wfEditFilename = fname;
    $('#wfEditThumbInput').click();
  }

  // ── Delete Modal ──
  function openWfDel(fname) {
    _wfDelFilename = fname;
    const meta = _wfMeta[fname] || {};
    const displayName = meta.name || fname.replace('.json', '');
    $('#wfDelMsg').textContent = `确定要删除工作流「${displayName}」吗？此操作不可撤销。`;
    $('#wfDelModal').classList.add('open');
  }
  function closeWfDel() {
    $('#wfDelModal').classList.remove('open');
  }
  async function confirmWfDel() {
    if (!_wfDelFilename) return;
    try {
      await fetch(API + '/api/workflows/' + encodeURIComponent(_wfDelFilename), { method: 'DELETE' });
      delete _wfMeta[_wfDelFilename];
    } catch (e) {}
    closeWfDel();
    renderWfGrid();
    loadWorkflows();
  }

  function initResizeHandle() {
    const handle = $('#resizeHandle');
    const colLeft = $('#colLeft');
    if (!handle || !colLeft) return;
    let startX, startW;
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      startX = e.clientX;
      startW = colLeft.offsetWidth;
      handle.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      const onMove = (e2) => {
        const dx = e2.clientX - startX;
        const nw = Math.max(280, Math.min(startW + dx, window.innerWidth * 0.5));
        colLeft.style.width = nw + 'px';
        colLeft.style.flex = 'none';
      };
      const onUp = () => {
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    // Clear inline width on mobile so CSS media query takes effect
    window.addEventListener('resize', () => {
      if (window.innerWidth <= 900) {
        colLeft.style.width = '';
        colLeft.style.flex = '';
      }
    });
  }

  // ═══ Node Editor ══════════════════════════════════════════════════════
  let _nodeEditorFname = '';
  let _nodeEditorData = null;
  let _nodeEditorConfig = null;

  function openNodeEditor(fname) {
    _nodeEditorFname = fname;
    $('#nodeEditorTitle').textContent = '节点编辑: ' + fname.replace('.json', '');
    Promise.all([
      fetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/analyze').then(function (r) {
        return r.json();
      }),
      fetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/config')
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .catch(function () {
          return null;
        }),
    ]).then(function (results) {
      _nodeEditorData = results[0];
      _nodeEditorConfig = results[1];
      renderNodeEditor(results[0], results[1]);
      $('#nodeEditorModal').classList.add('open');
    });
  }

  function closeNodeEditor() {
    $('#nodeEditorModal').classList.remove('open');
    _nodeEditorData = null;
    _nodeEditorConfig = null;
  }

  function renderNodeEditor(analyze, config) {
    var allFields = [];
    for (var ni = 0; ni < analyze.nodes.length; ni++) {
      var node = analyze.nodes[ni];
      for (var fi = 0; fi < node.fields.length; fi++) {
        var field = node.fields[fi];
        allFields.push({
          key: field.key,
          node_id: node.node_id,
          node_title: node.title,
          class_type: node.class_type,
          field: field.field,
          type: field.type,
          label: field.label,
          value: field.value,
          zone: field.zone,
          visible: field.visible,
        });
      }
    }
    if (config && config.fields) {
      for (var ci = 0; ci < config.fields.length; ci++) {
        var cfg = config.fields[ci];
        for (var ai = 0; ai < allFields.length; ai++) {
          if (allFields[ai].key === cfg.key) {
            allFields[ai].zone = cfg.zone || allFields[ai].zone;
            if (cfg.visible !== undefined) allFields[ai].visible = cfg.visible;
            allFields[ai].label = cfg.label || allFields[ai].label;
            break;
          }
        }
      }
    }
    var zoneMap = {
      user_input: 'neZoneUserInput',
      advanced: 'neZoneAdvanced',
      output: 'neZoneOutput',
      hidden: 'neZoneHidden',
    };
    for (var zKey in zoneMap) {
      var el = document.getElementById(zoneMap[zKey]);
      if (el) el.innerHTML = '';
    }
    for (var i = 0; i < allFields.length; i++) {
      var f = allFields[i];
      var container = document.getElementById(zoneMap[f.zone] || 'neZoneHidden');
      if (!container) continue;
      var card = document.createElement('div');
      card.className = 'ne-field' + (f.visible ? '' : ' hidden-field');
      card.draggable = true;
      card.dataset.key = f.key;
      var valPreview = f.value !== undefined && f.value !== null ? String(f.value).substring(0, 80) : '';
      var visIcon = f.visible ? '👁️' : '🚫';
      card.innerHTML =
        '<div class="ne-field-top">' +
        '<span class="ne-field-node" title="' +
        escA(f.node_title) +
        '">[' +
        escH(f.node_id) +
        '] ' +
        escH(f.class_type) +
        '</span>' +
        '<button class="ne-field-vis" title="切换可见性">' +
        visIcon +
        '</button>' +
        '</div>' +
        '<div class="ne-field-name">' +
        escH(f.field) +
        '</div>' +
        '<input class="ne-field-label-input" value="' +
        escA(f.label) +
        '" placeholder="显示名称" data-key="' +
        escA(f.key) +
        '">' +
        (valPreview
          ? '<div class="ne-field-value" title="' + escA(valPreview) + '">' + escH(valPreview) + '</div>'
          : '');
      (function (card, f) {
        card.addEventListener('dragstart', function (ev) {
          ev.dataTransfer.setData('text/plain', f.key);
          ev.dataTransfer.effectAllowed = 'move';
          card.style.opacity = '.4';
        });
        card.addEventListener('dragend', function () {
          card.style.opacity = '';
        });
        card.querySelector('.ne-field-vis').addEventListener('click', function () {
          var isHidden = card.classList.toggle('hidden-field');
          this.textContent = isHidden ? '🚫' : '👁️';
        });
      })(card, f);
      container.appendChild(card);
    }
    for (var zone in zoneMap) {
      (function (zone, id) {
        var el = document.getElementById(id);
        if (!el) return;
        var parent = el.parentElement;
        parent.addEventListener('dragover', function (ev) {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
          parent.classList.add('drag-over');
        });
        parent.addEventListener('dragleave', function () {
          parent.classList.remove('drag-over');
        });
        parent.addEventListener('drop', function (ev) {
          ev.preventDefault();
          parent.classList.remove('drag-over');
          var key = ev.dataTransfer.getData('text/plain');
          if (!key) return;
          var card = document.querySelector('.ne-field[data-key="' + CSS.escape(key) + '"]');
          if (card) el.appendChild(card);
        });
      })(zone, zoneMap[zone]);
    }
  }

  function saveNodeConfig() {
    if (!_nodeEditorFname) return;
    // Build type lookup from analyze data
    var typeMap = {};
    if (_nodeEditorData && _nodeEditorData.nodes) {
      for (var ni = 0; ni < _nodeEditorData.nodes.length; ni++) {
        var node = _nodeEditorData.nodes[ni];
        for (var fi = 0; fi < node.fields.length; fi++) {
          var f = node.fields[fi];
          typeMap[f.key] = { type: f.type, options: f.options, step: f.step, min: f.min, max: f.max };
        }
      }
    }
    var fields = [];
    var zoneMap = {
      neZoneUserInput: 'user_input',
      neZoneAdvanced: 'advanced',
      neZoneOutput: 'output',
      neZoneHidden: 'hidden',
    };
    for (var id in zoneMap) {
      var container = document.getElementById(id);
      if (!container) continue;
      var cards = container.querySelectorAll('.ne-field');
      for (var i = 0; i < cards.length; i++) {
        var card = cards[i];
        var key = card.dataset.key;
        var visible = !card.classList.contains('hidden-field');
        var labelInput = card.querySelector('.ne-field-label-input');
        var label = labelInput ? labelInput.value : '';
        var entry = { key: key, zone: zoneMap[id], visible: visible, label: label, order: i };
        // Copy type + extra props from analyze data
        var meta = typeMap[key];
        if (meta) {
          entry.type = meta.type || 'text';
          if (meta.options) entry.options = meta.options;
          if (meta.step !== undefined) entry.step = meta.step;
          if (meta.min !== undefined) entry.min = meta.min;
          if (meta.max !== undefined) entry.max = meta.max;
        }
        fields.push(entry);
      }
    }
    var config = { version: 1, workflow: _nodeEditorFname, fields: fields };
    fetch(API + '/api/workflows/' + encodeURIComponent(_nodeEditorFname) + '/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(function (r) {
      if (r.ok) {
        closeNodeEditor();
      }
    });
  }

  function resetNodeConfig() {
    if (!_nodeEditorFname) return;
    if (!confirm('恢复为自动分类？已保存的配置将被删除。')) return;
    fetch(API + '/api/workflows/' + encodeURIComponent(_nodeEditorFname) + '/config', { method: 'DELETE' }).then(
      function () {
        openNodeEditor(_nodeEditorFname);
      },
    );
  }
  // ═══ End Node Editor ═════════════════════════════════════════════════

  // Merge status module functions into CW (status.js sets window._statusMod first)
  window.CW = Object.assign({}, window._statusMod, {
    selectWF,
    clearWF,
    clearPrompt,
    delWF,
    openLB,
    openJobLB,
    closeLB,
    lbNav,
    delHist,
    cancelJob,
    retryJob,
    rndSeed,
    restoreJob,
    fillFormFromHistory,
    uploadWF,
    wfUploadOverlay,
    openWfMgr,
    closeWfMgr,
    openWfEdit,
    closeWfEdit,
    saveWfEdit,
    onAddWfTag,
    onWfThumbUpload,
    onWfThumbClick,
    openWfDel,
    closeWfDel,
    confirmWfDel,
    loadWfDirs,
    showAddDir,
    hideAddDir,
    addWfDir,
    removeWfDir,
    switchTab,
    applyFilters,
    clearFilters,
    toggleGenForm,
    openNodeEditor,
    closeNodeEditor,
    saveNodeConfig,
    resetNodeConfig,
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
