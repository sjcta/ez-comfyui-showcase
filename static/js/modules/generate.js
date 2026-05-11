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

async function fillFormFromHistory(idx) {
    const h = historyItems[idx];
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
      }
    } else {
      console.warn('[fillFormFromHistory] no match for workflow:', h.workflow, '— restoring common fields only');
    }
    if (h.prompt) {
      var pi = $('#promptInput');
      if (pi) pi.value = h.prompt;
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
          if (preview) { preview.src = API + '/api/input-image/' + v; preview.style.display = ''; }
          if (ph) ph.style.display = 'none';
          break;
        }
      }
    }
    // Restore seed (covers old items without field_values, and ensures actual seed is used)
    if (h.seed) {
      const seedInput = document.querySelector('.seed-group input');
      if (seedInput) seedInput.value = h.seed;
    }
    document.querySelector('.col-left').scrollTop = 0;
  }

async function restoreJob(jobId) {
    // Try local snapshot first (submitted this session)
    const snap = jobFields[jobId];
    if (snap) {
      if (snap.prompt) { var pi = $('#promptInput'); if (pi) pi.value = snap.prompt; }
      if (snap.width) { var wi = $('#widthInput'); if (wi) wi.value = snap.width; }
      if (snap.height) { var hi = $('#heightInput'); if (hi) hi.value = snap.height; }
      for (const [k, v] of Object.entries(snap.adv || {})) {
        const el = $(`#advFields [data-key="${k}"]`);
        if (el) el.value = v;
      }
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
      var pi = $('#promptInput');
      if (pi) pi.value = j.prompt_preview;
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

async function doGenerate() {
    if (!A.currentWF) {
      alert('请先选择 workflow');
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
      const r = await fetch(`${API}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow: A.currentWF,
          fields,
          width: parseInt(($('#widthInput') || {}).value) || 0,
          height: parseInt(($('#heightInput') || {}).value) || 0,
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
        workflow: A.currentWF,
        seed: String(d.seed),
        prompt_preview: ($('#promptInput') || {}).value ? $('#promptInput').value.slice(0, 300) : '',
        width: parseInt(($('#widthInput') || {}).value) || 0,
        height: parseInt(($('#heightInput') || {}).value) || 0,
        queued_at: new Date().toLocaleTimeString('en-GB'),
      };
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
    var html = '', hasTextEncode = false, hasLoadImage = false;
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
        html += '<div class="fg"><label>' + escH(labelText + nodeInfo) + '</label><div style="position:relative"><textarea id="promptInput" placeholder="' + escA(labelText) + '..."></textarea><button id="clearPromptBtn" class="clear-btn" onclick="CW.clearPrompt()">X Clear</button></div></div>';
      } else if (f.class_type === 'LoadImage' && f.field === 'image') {
        hasLoadImage = true;
        html += '<div class="ref-image-section"><label>' + escH(f.label || 'Reference Image') + '</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*" class="hidden"></div></div>';
      } else if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'width') { hasLatentW = true; latentW = f.value || 1024; }
      else if (f.class_type && f.class_type.includes('LatentImage') && f.field === 'height') { hasLatentH = true; latentH = f.value || 1024; }
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadImage) {
      html += '<div class="ref-image-section"><label>Reference Image</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*" class="hidden"></div></div>';
    }
    // Restore saved prompt text after DOM rebuild
    if (_savedPrompt) {
      var pi = $('#promptInput');
      if (pi && !pi.value) pi.value = _savedPrompt;
    }
    if (hasLatentW || hasLatentH) {
      var sw = hasLatentW ? latentW : 1024, sh = hasLatentH ? latentH : 1024;
      html += '<div class="fg" id="sizeSection"><label>Size</label><div class="ratio-grid" id="ratioGrid">';
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
          html += `<label class="toggle-label"><input type="checkbox" data-key="${key}" ${val === true || val === 'True' || val === true ? 'checked' : ''} onchange="this.value=this.checked"><span class="toggle-slider"></span></label>`;
          break;
        case 'seed':
          html += `<div class="seed-group"><input type="number" data-key="${key}" data-type="number" value="${val}"><button type="button" class="btn-dice" onclick="CW.rndSeed(this)">${CW.icon('dice-1')}</button></div>`;
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
    const btn = $('#genToggleMobile');
    const open = form.classList.toggle('mobile-open');
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
      var fd = new FormData();
      fd.append('file', file);
      try {
        var r = await fetch(API + '/api/upload-image', { method: 'POST', body: fd });
        var d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.detail || 'upload fail');
        valueInput.value = d.filename;
        if (preview) {
          preview.src = API + '/api/input-image/' + d.filename;
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
      var fd = new FormData();
      fd.append('file', file);
      try {
        var r = await fetch(API + '/api/upload-image', { method: 'POST', body: fd });
        var d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.detail || 'upload fail');
        valueInput.value = d.filename;
        if (preview) {
          preview.src = API + '/api/input-image/' + d.filename;
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
  window.CW.renderAdvFields = renderAdvFields;
  window.CW.renderQuickGen = renderQuickGen;
  window.CW.renderQuickForm = renderQuickForm;
  window.CW.initRatioGrid = initRatioGrid;
  window.CW.highlightRatio = highlightRatio;
})();
