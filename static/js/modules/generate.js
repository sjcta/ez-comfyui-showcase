/**
 * Generate Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs;

  _wfFieldMeta = [];

  _loadImageFields = [];

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

function highlightRatio(w, h) {
    $$('.ratio-btn').forEach((b) => {
      const bw = parseInt(b.dataset.w),
        bh = parseInt(b.dataset.h);
      b.classList.toggle('active', bw === w && bh === h);
    });
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
    // Switch to correct workflow first (so advanced fields exist in DOM)
    if (h.workflow && h.workflow.replace('.json', '') !== currentWF.replace('.json', '')) {
      // Auto-switch tab to match this workflow's category
      const tag = getWFType(h.workflow);
      window.CW.switchTab(tag ? tag.text : '其他');
      await window.CW.selectWF(h.workflow);
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
      if (tag) window.CW.switchTab(tag.text);
      await window.CW.selectWF(j.workflow);
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


  let _wfFieldMeta = [];


  let _loadImageFields = [];

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

function toggleGenForm() {
    const form = $('#genForm');
    const btn = $('#genToggleMobile');
    const open = form.classList.toggle('mobile-open');
    if (btn) btn.textContent = open ? '⚡ 收起 ▴' : '⚡ 快速出图 ▾';
  }

  if (!window.CW) window.CW = {};
  window.CW.toggleGenForm = toggleGenForm;
  window.CW.restoreJob = restoreJob;
  window.CW.fillFormFromHistory = fillFormFromHistory;
})();
