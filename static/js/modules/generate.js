/**
 * Generate Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs, jobFields = A.jobFields, historyItems = A.historyItems;

function initRatioGrid() {
    // Ratio buttons are created dynamically by renderQuickForm - guard
    var btns = $$('.ratio-btn');
    if (!btns || !btns.length) return;
    btns.forEach(function(b) {
      b.addEventListener('click', function() {
        var allBtns = $$('.ratio-btn');
        allBtns.forEach(function(x) { x.classList.remove('active'); });
        b.classList.add('active');
        $('#widthInput').value = b.dataset.w;
        $('#heightInput').value = b.dataset.h;
      });
    });
    // Sync: if user manually changes inputs, clear active highlight
    ['#widthInput', '#heightInput'].forEach(function(sel) {
      var el = $(sel);
      if (el) {
        el.addEventListener('input', function() {
          var w = parseInt($('#widthInput').value) || 0,
            h = parseInt($('#heightInput').value) || 0;
          highlightRatio(w, h);
        });
      }
    });
  }

function highlightRatio(w, h) {
    var target = w / h;
    var best = null, bestDiff = Infinity;
    $$('.ratio-btn').forEach((b) => {
      var bw = parseInt(b.dataset.w), bh = parseInt(b.dataset.h);
      var ratio = bw / bh;
      var diff = Math.abs(ratio - target);
      if (diff < bestDiff) { bestDiff = diff; best = b; }
    });
    $$('.ratio-btn').forEach((b) => b.classList.toggle('active', bestDiff < 0.01 && b === best));
  }

function scaleDim(w, h, maxSide = 1920) {
    const longest = Math.max(w, h);
    if (longest <= maxSide && w % 64 === 0 && h % 64 === 0) return [w, h];
    const scale = maxSide / longest;
    const sw = Math.round((w * scale) / 64) * 64;
    const sh = Math.round((h * scale) / 64) * 64;
    return [Math.max(sw, 256), Math.max(sh, 256)];
  }

function _setPromptInputValue(value) {
    var pi = $('#promptInput');
    if (!pi) return null;
    pi.value = value || '';
    pi.dispatchEvent(new Event('input', { bubbles: true }));
    if (window.CW && CW.syncClearPromptButton) CW.syncClearPromptButton();
    return pi;
  }

function _getSeedInput() {
    return document.querySelector('.seed-group input[type="number"]');
  }

function _setSeedRandomEnabled(enabled) {
    $$('.btn-dice[data-seed-random]').forEach(function(btn) {
      btn.classList.toggle('is-active', !!enabled);
      btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    });
  }

function _isSeedRandomEnabled() {
    var btn = document.querySelector('.btn-dice[data-seed-random]');
    return !!(btn && btn.classList.contains('is-active'));
  }

function _getManualSeedValue() {
    var input = _getSeedInput();
    if (!input) return null;
    var value = String(input.value || '').trim();
    if (!value) return null;
    var seed = parseInt(value, 10);
    return Number.isFinite(seed) ? seed : null;
  }

function toggleSeedRandom(btnEl) {
    var btn = btnEl || document.querySelector('.btn-dice[data-seed-random]');
    if (!btn) return;
    _setSeedRandomEnabled(!btn.classList.contains('is-active'));
  }

function _clearPromptOptimizationVariants() {
    var old = $('#promptOptimizeVariants');
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }

function _showPromptOptimizationVariants(data) {
    var optimized = String((data && (data.optimized_prompt || data.cleaned_prompt)) || '').trim();
    var structured = String((data && data.structured_prompt_json) || '').trim();
    if (!optimized || !structured) {
      _clearPromptOptimizationVariants();
      return;
    }
    var promptField = $('#promptInput');
    var promptGroup = promptField && promptField.closest ? promptField.closest('.prompt-fg') : null;
    var labelRow = promptGroup ? promptGroup.querySelector('.prompt-label-row') : null;
    if (!labelRow) return;
    _clearPromptOptimizationVariants();
    var panel = document.createElement('div');
    panel.id = 'promptOptimizeVariants';
    panel.className = 'prompt-variant-panel';
    panel.innerHTML = ''
      + '<button class="prompt-variant-btn active" type="button" data-kind="text">纯词汇</button>'
      + '<button class="prompt-variant-btn" type="button" data-kind="json">JSON格式</button>';
    var buttons = panel.querySelectorAll('.prompt-variant-btn');
    function activate(kind) {
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].classList.toggle('active', buttons[i].getAttribute('data-kind') === kind);
      }
      _setPromptInputValue(kind === 'json' ? structured : optimized);
    }
    for (var j = 0; j < buttons.length; j++) {
      buttons[j].addEventListener('click', function() {
        activate(this.getAttribute('data-kind') || 'text');
      });
    }
    labelRow.appendChild(panel);
  }

function _quickGenerationLabel() {
    var prompt = ($('#promptInput') || {}).value || '';
    if (prompt.trim()) return prompt.slice(0, 300);
    var meta = (A._wfMeta || {})[A.currentWF] || {};
    var tags = meta.tags || [];
    var typeTag = window.CW && CW.getWFType ? CW.getWFType(A.currentWF || '') : null;
    var isUpscale = (typeTag && typeTag.text === '放大') || tags.indexOf('放大') >= 0 || /upscale|seedvr/i.test(A.currentWF || '');
    if (!isUpscale) return '';
    var resolution = 0;
    var fields = A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if (f.field === 'resolution') {
        var el = document.querySelector('#advFields [data-key="' + f.key + '"]');
        resolution = parseInt((el && el.value) || f.value || 0, 10) || 0;
        break;
      }
    }
    if (resolution >= 3840) return '4K 放大';
    if (resolution >= 1920) return '2K 放大';
    return resolution > 0 ? (resolution + 'P 放大') : '放大';
  }

  function _historyKey(item) {
    return String((item && (item.id || item.filename || item.thumb)) || '');
  }

  function _historyItemByKey(key) {
    key = String(key || '');
    if (!key) return null;
    for (var i = 0; i < historyItems.length; i++) {
      if (_historyKey(historyItems[i]) === key) return historyItems[i];
    }
    return null;
  }

async function fillFormFromHistory(idx, key) {
    const h = _historyItemByKey(key) || historyItems[idx];
    if (!h) return;
    if (!h.workflow) return;
    // Always find and switch to the correct workflow + tab
    var targetWf = null;
    // 1. Direct match in current workflow cards
    var wfExists = [...$$('.wf-card')].some(el => el.dataset.name === h.workflow);
    if (wfExists) {
      targetWf = h.workflow;
    }
    // 2. Try server-side find-closest (by wf_id or tags)
    if (!targetWf) {
      try {
        var params = new URLSearchParams();
        if (h.wf_id) params.set('wf_id', h.wf_id);
        if (h.wf_tags) params.set('wf_tags', JSON.stringify(h.wf_tags));
        params.set('workflow', h.workflow);
        var r = await fetch(API + '/api/workflows/find-closest?' + params.toString());
        if (r.ok) {
          var d = await r.json();
          targetWf = d.filename;
          console.log('[fillFormFromHistory] fuzzy matched:', h.workflow, '→', targetWf, 'by', d.matched_by);
        }
      } catch(e) { console.warn('[fillFormFromHistory] find-closest failed:', e); }
    }
    if (targetWf) {
      var tag = window.CW.getWFType(targetWf);
      var tabName = tag ? tag.text : '';
      if (!tabName) {
        var meta = (A._wfMeta || {})[targetWf] || {};
        var tags = meta.tags || [];
        tabName = tags[0] || '全部';
      }
      // Always switch tab (even if same workflow — user may have switched tabs)
      window.CW.switchTab(tabName);
      // Only re-fetch fields if workflow actually changed
      if (targetWf !== A.currentWF) {
        await window.CW.selectWF(targetWf);
      } else if (window.CW.highlightWF) {
        window.CW.highlightWF();
      }
      requestAnimationFrame(function() {
        var card = Array.prototype.slice.call(document.querySelectorAll('.wf-card')).find(function(el) {
          return el.dataset && el.dataset.name === targetWf;
        });
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
      });
    } else {
      console.warn('[fillFormFromHistory] no match for workflow:', h.workflow, '— restoring common fields only');
    }
    if (h.prompt) {
      _setPromptInputValue(h.prompt);
    }
    // Scale dimensions to fit within 1920, proportional, divisible by 64
    if (h.width && h.height) {
      var wi = $('#widthInput'), hi = $('#heightInput');
      if (wi && hi) {
        const [w, h2] = scaleDim(h.width, h.height);
        wi.value = w;
        hi.value = h2;
        highlightRatio(w, h2);
      }
    }
    // Restore advanced fields if available
    if (h.field_values) {
      for (const [k, v] of Object.entries(h.field_values)) {
        const el = $(`#advFields [data-key="${k}"]`);
        if (el) el.value = v;
      }
      // Restore ref image from LoadImage field_values
      for (const [k, v] of Object.entries(h.field_values)) {
        if (k.endsWith('::image') && v) {
          var vInput = document.querySelector('#refImageValue');
          var preview = document.querySelector('#refImagePreview');
          var ph = document.querySelector('#refImagePlaceholder');
          if (vInput) vInput.value = v;
          if (preview) { preview.src = API + '/api/input-image/' + encodeURIComponent(v); preview.style.display = ''; }
          if (ph) ph.style.display = 'none';
          break;
        }
      }
    }
    // Restore seed (covers old items without field_values, and ensures actual seed is used)
    if (h.seed) {
      const seedInput = _getSeedInput();
      if (seedInput) seedInput.value = h.seed;
      _setSeedRandomEnabled(true);
    }
    document.querySelector('.col-left').scrollTop = 0;
  }

async function restoreJob(jobId) {
    // Try local snapshot first (submitted this session)
    const snap = jobFields[jobId];
    if (snap) {
      if (snap.prompt) { _setPromptInputValue(snap.prompt); }
      if (snap.width) { var wi = $('#widthInput'); if (wi) wi.value = snap.width; }
      if (snap.height) { var hi = $('#heightInput'); if (hi) hi.value = snap.height; }
      for (const [k, v] of Object.entries(snap.adv || {})) {
        const el = $(`#advFields [data-key="${k}"]`);
        if (el) el.value = v;
      }
      if (Object.keys(snap.adv || {}).some(function(k) { return k.endsWith('::seed'); })) _setSeedRandomEnabled(true);
      return;
    }
    // Fallback: restore from server job data
    const j = jobs[jobId];
    if (!j) return;
    // Switch to correct workflow: try direct → wf_id fuzzy match → skip
    if (j.workflow && (!A.currentWF || j.workflow.replace('.json','') !== A.currentWF.replace('.json',''))) {
      var targetWf = null;
      var wfExists = [...$$('.wf-card')].some(el => el.dataset.name === j.workflow);
      if (wfExists) {
        targetWf = j.workflow;
      }
      if (!targetWf) {
        try {
          var params = new URLSearchParams();
          if (j.wf_id) params.set('wf_id', j.wf_id);
          if (j.wf_tags) params.set('wf_tags', JSON.stringify(j.wf_tags));
          params.set('workflow', j.workflow);
          var r = await fetch(API + '/api/workflows/find-closest?' + params.toString());
          if (r.ok) {
            var d = await r.json();
            targetWf = d.filename;
            console.log('[restoreJob] fuzzy matched:', j.workflow, '→', targetWf, 'by', d.matched_by);
          }
        } catch(e) { console.warn('[restoreJob] find-closest failed:', e); }
      }
      if (targetWf) {
        var tag = window.CW.getWFType(targetWf);
        if (tag) window.CW.switchTab(tag.text);
        await window.CW.selectWF(targetWf);
      } else {
        console.warn('[restoreJob] no match for workflow:', j.workflow, '— skipping switch');
      }
    }
    // Restore prompt
    if (j.prompt_preview) {
      _setPromptInputValue(j.prompt_preview);
    }
    // Restore dimensions
    if (j.width && j.height) {
      var wi = $('#widthInput'), hi = $('#heightInput');
      if (wi && hi) {
        wi.value = j.width;
        hi.value = j.height;
      }
      if (typeof highlightRatio === 'function') highlightRatio(j.width, j.height);
    }
    // Restore seed
    if (j.seed) {
      const seedEl = _getSeedInput() || document.querySelector('[data-field="seed"]') || document.querySelector('input[placeholder*="seed"]');
      if (seedEl) seedEl.value = j.seed;
      _setSeedRandomEnabled(true);
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

async function doGenerate() {
    if (!A.currentWF) {
      alert('请先选择 workflow');
      return;
    }
    // 未登录可看可选，但提交前再要求登录
    if (!window.CW.auth.isLoggedIn()) {
      window.CW.auth.showLogin();
      return;
    }
    const btn = $('#btnGenerate');
    btn.disabled = true;
    btn.textContent = '提交中...';

    const fields = {};
    const prompt = ($('#promptInput') || {}).value || '';
    const snapshot = { prompt, width: ($('#widthInput') || {}).value || 0, height: ($('#heightInput') || {}).value || 0, adv: {} };

    try {
      const fr = await fetch(`${API}/api/workflows/${encodeURIComponent(A.currentWF)}/fields`);
      const fd = await fr.json();
      for (const f of fd.fields || []) {
        // Pre-set default value for this field (including hidden)
        fields[f.node_id + '::' + f.field] = f.value;
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
          fields[key] = parseInt(($('#widthInput') || {}).value) || 1024;
          continue;
        }
        if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'height') {
          fields[key] = parseInt(($('#heightInput') || {}).value) || 1920;
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
      fields[el.dataset.key] = el.type === 'number' ? parseFloat(el.value) || 0 : (el.type === 'checkbox' ? el.checked : el.value);
      snapshot.adv[el.dataset.key] = el.value;
    });

    try {
      const manualSeed = _getManualSeedValue();
      const requestBody = {
        workflow: A.currentWF,
        fields,
        width: parseInt(($('#widthInput') || {}).value) || 0,
        height: parseInt(($('#heightInput') || {}).value) || 0,
        preferred_instance: A.manualTargetInstance ? (A.currentTargetInstance || '') : '',
        preferred_node_id: A.manualTargetInstance ? (A.currentTargetNodeId || '') : '',
      };
      if (!_isSeedRandomEnabled() && manualSeed === null) throw new Error('请输入种子数字，或开启随机种子');
      if (!_isSeedRandomEnabled()) requestBody.seed = manualSeed;
      const authHeaders = window.CW.auth.getAuthHeaders();
      const r = await fetch(`${API}/api/generate`, {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders),
        body: JSON.stringify(requestBody),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '提交失败');
      jobFields[d.job_id] = snapshot;
      // Add job to local store immediately so the card appears without waiting for poll
      jobs[d.job_id] = {
        id: d.job_id,
        status: 'queued',
        message: '排队中...',
        workflow: A.currentWF,
        seed: String(d.seed),
        prompt_preview: _quickGenerationLabel(),
        width: parseInt(($('#widthInput') || {}).value) || 0,
        height: parseInt(($('#heightInput') || {}).value) || 0,
        preferred_instance: A.manualTargetInstance ? (A.currentTargetInstance || '') : '',
        preferred_node_id: A.manualTargetInstance ? (A.currentTargetNodeId || '') : '',
        queued_at: new Date().toLocaleTimeString('en-GB'),
      };
      try {
        if (window.CW && CW.toast) CW.toast('排队中', 'queued');
      } catch (e) {}
      // Trigger onJobUpdate to kick off active job polling
      window.CW.onJobUpdate(jobs[d.job_id]);
      window.CW.renderGallery();
    } catch (e) {
      alert('出图失败: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = CW.icon('play') + ' 出图';
    }
  }


async function optimizePrompt() {
    var input = $('#promptInput');
    var btn = $('#optimizePromptBtn');
    if (!input) return;
    var raw = (input.value || '').trim();
    if (!raw) {
      if (window.CW && CW.toast) CW.toast('先输入提示词', 'warn');
      input.focus();
      return;
    }
    var oldHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.classList.add('is-loading');
      btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 优化中';
    }
    try {
      var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
      var response = await fetcher(API + '/api/prompt/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: raw, max_new_tokens: 384 })
      });
      var data = await response.json().catch(function() { return {}; });
      if (!response.ok) throw new Error(data.detail || data.message || '提示词优化失败');
      var optimized = String(data.optimized_prompt || data.cleaned_prompt || '').trim();
      if (!optimized) throw new Error('优化结果为空');
      window.CW.lastPromptOptimization = data;
      _setPromptInputValue(optimized);
      _showPromptOptimizationVariants(data);
      if (window.CW && CW.toast) CW.toast(data.structured_prompt_json ? '提示词已优化，JSON 版本已生成' : '提示词已优化', 'ok');
    } catch (e) {
      console.warn('[optimizePrompt] failed:', e);
      if (window.CW && CW.toast) CW.toast(e.message || '提示词优化失败', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.innerHTML = oldHtml || ((window.CW && CW.icon ? CW.icon('zap') : '') + ' 优化');
      }
    }
  }


var _promptInterrogateRunning = false;

  function _setPromptInterrogateLoading(isLoading, label) {
    var buttons = [$('#interrogatePromptBtn'), $('#promptInterrogateRunBtn')];
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!btn) continue;
      btn.disabled = !!isLoading;
      btn.classList.toggle('is-loading', !!isLoading);
      if (isLoading) {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' ' + (label || '反推中');
      } else if (btn.id === 'interrogatePromptBtn') {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">用图片反推</span>';
      } else {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推';
      }
    }
  }

  function _startPromptInterrogateTask(refVal) {
    if (!refVal) return;
    if (_promptInterrogateRunning) {
      if (window.CW && CW.toast) CW.toast('图片反推正在后台运行', 'info');
      return;
    }
    _promptInterrogateRunning = true;
    _setPromptInterrogateLoading(true, '后台反推中');
    if (window.CW && CW.closePromptInterrogateModal) CW.closePromptInterrogateModal();
    if (window.CW && typeof CW.showPromptInterrogatePendingToast === 'function') {
      CW.showPromptInterrogatePendingToast();
    } else if (window.CW && CW.toast) {
      CW.toast('后台努力反推中，请稍后……', 'info');
    }
    _runPromptInterrogate(refVal).then(function(result) {
      var prompt = result && result.prompt ? result.prompt : '';
      if (window.CW && typeof CW.showPromptResultToast === 'function') {
        CW.showPromptResultToast(prompt, result && result.data ? result.data : {});
      } else if (window.CW && CW.toast) {
        CW.toast('反推完成', 'done');
      }
    }).catch(function(e) {
      console.warn('[interrogatePromptFromImage] failed:', e);
      if (window.CW && CW.toast) CW.toast(e.message || '图片反推失败', 'error');
    }).finally(function() {
      _promptInterrogateRunning = false;
      _setPromptInterrogateLoading(false);
    });
  }

async function interrogatePromptFromImage() {
    var refVal = ($('#refImageValue') || {}).value || '';
    openPromptInterrogateModal(refVal);
  }

  async function _runPromptInterrogate(refVal) {
    var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
    var response = await fetcher(API + '/api/prompt/interrogate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: refVal })
    });
    var data = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(data.detail || data.message || '图片反推失败');
    var prompt = String(data.prompt || data.promptgen || data.wd14_tags || '').trim();
    if (!prompt) throw new Error('反推结果为空');
    return { prompt: prompt, data: data };
  }

  function openPromptInterrogateModal(initialImage) {
    if (!window.CW || !CW.auth || !CW.auth.isLoggedIn || !CW.auth.isLoggedIn()) {
      if (window.CW && CW.auth && CW.auth.showLogin) CW.auth.showLogin();
      return;
    }
    var old = document.getElementById('promptInterrogateModal');
    if (old) old.remove();
    var html = '<div class="v4-overlay prompt-interrogate-modal" id="promptInterrogateModal" onclick="if(event.target===this)CW.closePromptInterrogateModal()">' +
      '<div class="v4-card narrow prompt-interrogate-card">' +
        '<div class="auth-modal-header"><span class="auth-modal-title">' + (window.CW && CW.icon ? CW.icon('image', 18) : '') + '图片反推提示词</span>' +
        '<button class="auth-modal-close" type="button" onclick="CW.closePromptInterrogateModal()">×</button></div>' +
        '<div class="auth-modal-body">' +
          '<div class="prompt-interrogate-upload" id="promptInterrogateZone">' +
            '<div class="img-upload-placeholder"><span>' + (window.CW && CW.icon ? CW.icon('upload', 26) : '') + '</span><span>点击或拖入图片</span></div>' +
            '<img id="promptInterrogatePreview" class="img-upload-preview hidden" alt="">' +
            '<input type="file" id="promptInterrogateFile" accept="image/*" class="hidden">' +
          '</div>' +
          '<div class="prompt-interrogate-actions">' +
            '<button class="prompt-tool-btn" type="button" id="promptInterrogateRunBtn" disabled>' + (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
    var modal = document.getElementById('promptInterrogateModal');
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        if (modal) modal.classList.add('open');
      });
    });
    _initPromptInterrogateModal(initialImage);
  }

  function closePromptInterrogateModal() {
    var modal = document.getElementById('promptInterrogateModal');
    if (!modal) return;
    modal.classList.remove('open');
    setTimeout(function() {
      if (modal.parentNode) modal.parentNode.removeChild(modal);
    }, 300);
  }

  function _initPromptInterrogateModal(initialImage) {
    var zone = $('#promptInterrogateZone');
    var fileInput = $('#promptInterrogateFile');
    var preview = $('#promptInterrogatePreview');
    var runBtn = $('#promptInterrogateRunBtn');
    var uploadedName = String(initialImage || '').trim();
    if (!zone || !fileInput || !runBtn) return;

    if (uploadedName) {
      if (preview) {
        preview.src = API + '/api/input-image/' + encodeURIComponent(uploadedName);
        preview.style.display = '';
        preview.classList.remove('hidden');
      }
      var ph = zone.querySelector('.img-upload-placeholder');
      if (ph) ph.style.display = 'none';
      runBtn.disabled = false;
    }

    async function useFile(file) {
      if (!file) return;
      runBtn.disabled = true;
      runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 上传中';
      runBtn.classList.add('is-loading');
      try {
        var d = await _uploadRefImage(file);
        uploadedName = d.filename;
        if (preview) {
          preview.src = API + '/api/input-image/' + encodeURIComponent(uploadedName);
          preview.style.display = '';
          preview.classList.remove('hidden');
        }
        var ph = zone.querySelector('.img-upload-placeholder');
        if (ph) ph.style.display = 'none';
        runBtn.disabled = false;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推';
      } catch (e) {
        if (window.CW && CW.toast) CW.toast(e.message || '图片上传失败', 'error');
        runBtn.disabled = true;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推';
      } finally {
        runBtn.classList.remove('is-loading');
        fileInput.value = '';
      }
    }

    zone.addEventListener('click', function(e) {
      if (e.target && e.target.tagName === 'IMG') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', function() {
      useFile(fileInput.files && fileInput.files[0]);
    });
    zone.addEventListener('dragover', function(e) {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
      zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', function(e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      useFile(e.dataTransfer.files && e.dataTransfer.files[0]);
    });
    runBtn.addEventListener('click', async function() {
      if (!uploadedName) return;
      _startPromptInterrogateTask(uploadedName);
    });
  }


  // Shared across modules via __APP__
  var _wfFieldMeta = window.__APP__._wfFieldMeta || [];
  window.__APP__._wfFieldMeta = _wfFieldMeta;

  var _loadImageFields = window.__APP__._loadImageFields || [];
  window.__APP__._loadImageFields = _loadImageFields;

function renderQuickForm(fields) {
    var container = $('#quickFormFields');
    if (!container) return;
    if (!fields || !fields.length) { container.innerHTML = ''; return; }
    // Preserve prompt text across workflow switches
    var _savedPrompt = ($('#promptInput') || {}).value || '';
    var hasZones = fields.some(function(f) { return f.zone; });
    var html = '', hasTextEncode = false, hasLoadImage = false, quickImageRendered = false;
    var hasLatentW = false, hasLatentH = false, latentW = 1024, latentH = 1024;
    for (var fi = 0; fi < fields.length; fi++) {
      var f = fields[fi], zone = f.zone || (hasZones ? 'hidden' : 'advanced');
      if (zone !== 'user_input') {
        if (hasZones) continue;
        if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'width') { hasLatentW = true; latentW = f.value || 1024; }
        else if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'height') { hasLatentH = true; latentH = f.value || 1024; }
        else if (f.class_type === 'LoadImage' && f.field === 'image') hasLoadImage = true;
        else if (f.class_type && (f.class_type.includes('TextEncode') || f.class_type === 'CLIPTextEncode') && f.field === 'text') hasTextEncode = true;
        continue;
      }
      if (f.type === 'textarea' || (f.class_type && f.class_type.includes('TextEncode'))) {
        hasTextEncode = true;
        var labelText = f.label || 'Prompt', nodeInfo = f.node_title ? ' [' + f.node_title.split('(')[0].trim() + ']' : '';
        html += '<div class="fg prompt-fg"><div class="prompt-label-row"><label>' + escH(labelText + nodeInfo) + '</label></div><div class="prompt-input-wrap"><textarea id="promptInput" placeholder="' + escA(labelText) + '..."></textarea></div><div class="prompt-actions"><button id="interrogatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-image" type="button" title="用图片反推" onclick="CW.interrogatePromptFromImage()">' + (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">用图片反推</span></button><button id="optimizePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant is-compact-disabled" type="button" title="提示词优化" onclick="CW.optimizePrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('zap') : '') + ' <span class="prompt-tool-label">提示词优化</span></button><button id="clearPromptBtn" class="prompt-tool-btn prompt-tool-btn-clear clear-btn is-compact-disabled" type="button" title="清除文字" onclick="CW.clearPrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' <span class="prompt-tool-label">清除文字</span></button></div></div>';
      } else if (f.class_type === 'LoadImage' && f.field === 'image') {
        hasLoadImage = true;
        quickImageRendered = true;
        html += '<div class="ref-image-section"><label>' + escH(f.label || 'Reference Image') + '</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*" class="hidden"></div></div>';
      } else if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'width') { hasLatentW = true; latentW = f.value || 1024; }
      else if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'height') { hasLatentH = true; latentH = f.value || 1024; }
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadImage && !quickImageRendered) {
      html += '<div class="ref-image-section"><label>Reference Image</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*" class="hidden"></div></div>';
    }
    // Restore saved prompt text after DOM rebuild
    if (_savedPrompt) {
      var pi = $('#promptInput');
      if (pi && !pi.value) pi.value = _savedPrompt;
    }
    if (hasLatentW || hasLatentH) {
      var sw = hasLatentW ? latentW : 1024, sh = hasLatentH ? latentH : 1024;
      html += '<div class="fg" id="sizeSection"><label>出图比例</label><div class="ratio-grid" id="ratioGrid">';
      var presets = [[1024,1024,'1:1','22px','22px'],[1536,1024,'3:2','26px','17px'],[1920,1080,'16:9','28px','16px'],[1536,1152,'4:3','24px','18px'],[1152,1536,'3:4','18px','24px'],[1024,1536,'2:3','16px','24px'],[1080,1920,'9:16','14px','24px']];
      for (var pi = 0; pi < presets.length; pi++) {
        var p = presets[pi];
        html += '<button class="ratio-btn' + (p[0]===sw&&p[1]===sh?' active':'') + '" data-w="' + p[0] + '" data-h="' + p[1] + '" title="' + p[0] + 'x' + p[1] + '"><span class="ratio-shape" style="width:' + p[3] + ';height:' + p[4] + '"></span><span class="ratio-label">' + p[2] + '</span></button>';
      }
      html += '</div><div class="ratio-custom"><input type="number" id="widthInput" value="' + sw + '" step="64" min="256" max="2048"><span class="sep-dim">x</span><input type="number" id="heightInput" value="' + sh + '" step="64" min="256" max="2048"></div></div>';
      container.innerHTML = html;
      window.CW.initRatioGrid && window.CW.initRatioGrid();
      window.CW.highlightRatio && CW.highlightRatio(sw, sh);
    } else { container.innerHTML = html; }
    // Restore saved prompt text after DOM rebuild (non-latent path)
    if (_savedPrompt) {
      var pi2 = $('#promptInput');
      if (pi2 && !pi2.value) pi2.value = _savedPrompt;
    }
    var promptInput = $('#promptInput');
    if (promptInput && window.CW.syncClearPromptButton) {
      promptInput.addEventListener('input', window.CW.syncClearPromptButton);
      window.CW.syncClearPromptButton();
    }
    if (hasLoadImage) { _refImageInited = false; setTimeout(function() { _initRefImageZone(); }, 50); }
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
      box.innerHTML = '<div class="gen-empty">无可编辑参数</div>';
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
        case 'toggle':
        case 'bool':
          html += `<label class="toggle-label bool-toggle"><input type="checkbox" data-key="${key}" ${val === true || val === 'True' || val === 'true' ? 'checked' : ''} onchange="this.value=this.checked"><span class="toggle-slider"></span><span class="toggle-state" data-on="开启" data-off="关闭"></span></label>`;
          break;
        case 'seed':
          html += `<div class="seed-group"><input type="number" data-key="${key}" data-type="number" value="${val}" oninput="CW.setSeedRandomEnabled(false)"><button type="button" class="btn-dice seed-random-toggle is-active" data-seed-random="1" aria-pressed="true" title="随机种子" aria-label="随机种子" onclick="CW.toggleSeedRandom(this)">${CW.icon('shuffle')}</button></div>`;
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

function toggleGenForm() {
    const form = $('#genForm');
    if (!form) return;
    const footer = $('.gen-footer');
    const btn = $('#genToggleMobile');
    const title = $('#genTitle');
    const arrow = $('#genArrow');
    const open = !form.classList.contains('mobile-open');
    form.classList.toggle('mobile-open', open);
    if (footer) footer.classList.toggle('mobile-open', open);
    if (title) title.classList.toggle('is-open', open);
    if (arrow) arrow.textContent = open ? '\u25B4' : '\u25BE';
    if (btn) btn.innerHTML = open ? CW.icon('zap') + ' 收起 \u25B4' : CW.icon('zap') + ' 快速出图 \u25BE';
  }

var _refImageInited = false;
function _resetRefImage() {
    _refImageInited = false;
    var preview = $('#refImagePreview');
    var placeholder = $('#refImagePlaceholder');
    var valueInput = $('#refImageValue');
    if (preview) { preview.src = ''; preview.style.display = 'none'; }
    if (placeholder) placeholder.style.display = '';
    if (valueInput) valueInput.value = '';
  }

var __curZone = null;
  async function _parseUploadResponse(resp) {
    var text = await resp.text();
    var data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        data = { detail: text };
      }
    }
    if (!resp.ok || !data.ok) {
      throw new Error((data && (data.detail || data.error || data.message)) || ('upload fail (' + resp.status + ')'));
    }
    return data;
  }

  function _uploadRefImage(file) {
    var fd = new FormData();
    fd.append('file', file);
    var upload = (window.CW && window.CW.auth && typeof window.CW.auth.apiFetch === 'function')
      ? window.CW.auth.apiFetch(API + '/api/upload-image', { method: 'POST', body: fd })
      : fetch(API + '/api/upload-image', { method: 'POST', body: fd });
    return upload.then(_parseUploadResponse);
  }

  function _initRefImageZone() {
    if (_refImageInited) return;
    _refImageInited = true;
    var zone = $('#refImageZone');
    var fileInput = $('#refImageFile');
    var preview = $('#refImagePreview');
    var valueInput = $('#refImageValue');
    var placeholder = $('#refImagePlaceholder');
    if (!zone || !fileInput) return;
    zone.addEventListener('click', function(e) {
      if (e.target.tagName === 'IMG') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', async function() {
      if (!fileInput.files.length) return;
      var file = fileInput.files[0];
      try {
        var d = await _uploadRefImage(file);
        valueInput.value = d.filename;
        if (preview) {
          preview.src = API + '/api/input-image/' + encodeURIComponent(d.filename);
          preview.style.display = '';
        }
        if (placeholder) placeholder.style.display = 'none';
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
      fileInput.value = '';
    });
    if (preview) {
      preview.addEventListener('click', function() {
        preview.src = '';
        preview.style.display = 'none';
        if (placeholder) placeholder.style.display = '';
        valueInput.value = '';
      });
    }
    zone.addEventListener('dragover', function(e) {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
      zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', async function(e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      var file = e.dataTransfer.files[0];
      if (!file) return;
      try {
        var d = await _uploadRefImage(file);
        valueInput.value = d.filename;
        if (preview) {
          preview.src = API + '/api/input-image/' + encodeURIComponent(d.filename);
          preview.style.display = '';
        }
        if (placeholder) placeholder.style.display = 'none';
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
  }

function renderQuickGen() {
    // No-op: quick gen is rendered inline
  }

  if (!window.CW) window.CW = {};
  window.CW.toggleGenForm = toggleGenForm;
  window.CW.restoreJob = restoreJob;
  window.CW.fillFormFromHistory = fillFormFromHistory;
  window.CW.doGenerate = doGenerate;
  window.CW.optimizePrompt = optimizePrompt;
  window.CW.clearPromptOptimizationVariants = _clearPromptOptimizationVariants;
  window.CW.interrogatePromptFromImage = interrogatePromptFromImage;
  window.CW.openPromptInterrogateModal = openPromptInterrogateModal;
  window.CW.closePromptInterrogateModal = closePromptInterrogateModal;
  window.CW.renderAdvFields = renderAdvFields;
  window.CW.renderQuickGen = renderQuickGen;
  window.CW.renderQuickForm = renderQuickForm;
  window.CW.toggleSeedRandom = toggleSeedRandom;
  window.CW.setSeedRandomEnabled = _setSeedRandomEnabled;
  window.CW.initRatioGrid = initRatioGrid;
  window.CW.highlightRatio = highlightRatio;
})();
