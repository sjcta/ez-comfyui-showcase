/**
 * Workflows Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs, historyItems = A.historyItems;

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

function closeWfDel() {
    $('#wfDelModal').classList.remove('open');
  }

function openWfDel(fname) {
    _wfDelFilename = fname;
    const meta = _wfMeta[fname] || {};
    const displayName = meta.name || fname.replace('.json', '');
    $('#wfDelMsg').textContent = `确定要删除工作流「${displayName}」吗？此操作不可撤销。`;
    $('#wfDelModal').classList.add('open');
  }

function onWfThumbClick(fname) {
    _wfEditFilename = fname;
    $('#wfEditThumbInput').click();
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

function closeWfEdit() {
    $('#wfEditModal').classList.remove('open');
  }

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

async function loadWfMeta() {
    try {
      const r = await fetch(API + '/api/workflows/meta');
      _wfMeta = await r.json();
    } catch (e) {
      _wfMeta = {};
    }
    renderWfGrid();
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

function hideAddDir() {
    const el = $('#wfDirsAdd');
    if (el) {
      el.style.display = 'none';
      $('#wfDirInput').value = '';
    }
  }

function showAddDir() {
    const el = $('#wfDirsAdd');
    if (el) {
      el.style.display = 'flex';
      $('#wfDirInput').focus();
    }
  }

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

function closeWfMgr() {
    $('#wfOverlay').classList.remove('open');
  }

function openWfMgr() {
    $('#wfOverlay').classList.add('open');
    loadWfMeta();
    loadWfDirs();
  }

async function delWF(name) {
    if (!confirm(`删除 ${name}？`)) return;
    await fetch(`${API}/api/workflows/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (A.currentWF === name) A.currentWF = null;
    loadWorkflows();
  }

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

function _applyTabFilter() {
    $$('.wf-card').forEach((el) => {
      const cat = el.dataset.cat || '其他';
      el.style.display = cat === _currentTab ? '' : 'none';
    });
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

function clearWF() {
    A.currentWF = '';
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

function highlightWF() {
    $$('.wf-card').forEach((el) => el.classList.toggle('active', el.dataset.name === A.currentWF));
  }

async function selectWF(name) {
    A.currentWF = name;
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
      window.__APP__._wfFieldMeta = fields.map((f) => ({
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
      if (window.CW.renderAdvFields) window.CW.renderAdvFields(fields);
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
          const typeTag = window.CW.getWFType(w.name);
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
          const t = window.CW.getWFType(w.name);
          return t ? t.text : '其他';
        }),
      );
      const tabsEl = $('#wfTabs');
      if (tabsEl) {
        let tabHtml = '';
        for (const t of TAB_ORDER) {
          if (cats.has(t)) {
            const catWfs = wfs.filter(w => { const tag = window.CW.getWFType(w.name); return tag ? tag.text === t : t === '其他'; });
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
        A.currentWF && wfs.find((w) => w.name === A.currentWF)
          ? A.currentWF
          : saved && wfs.find((w) => w.name === saved)
            ? saved
            : wfs[0].name;
      if (!A.currentWF || A.currentWF !== target) selectWF(target);
      else highlightWF();
    } catch (e) {
      console.error('loadWorkflows:', e);
    }
  }

  if (!window.CW) window.CW = {};
  window.CW.selectWF = selectWF;
  window.CW.clearWF = clearWF;
  window.CW.delWF = delWF;
  window.CW.uploadWF = uploadWF;
  window.CW.openWfMgr = openWfMgr;
  window.CW.closeWfMgr = closeWfMgr;
  window.CW.openWfEdit = openWfEdit;
  window.CW.closeWfEdit = closeWfEdit;
  window.CW.saveWfEdit = saveWfEdit;
  window.CW.onAddWfTag = onAddWfTag;
  window.CW.onWfThumbUpload = onWfThumbUpload;
  window.CW.onWfThumbClick = onWfThumbClick;
  window.CW.openWfDel = openWfDel;
  window.CW.closeWfDel = closeWfDel;
  window.CW.confirmWfDel = confirmWfDel;
  window.CW.loadWfDirs = loadWfDirs;
  window.CW.showAddDir = showAddDir;
  window.CW.hideAddDir = hideAddDir;
  window.CW.addWfDir = addWfDir;
  window.CW.removeWfDir = removeWfDir;
  window.CW.switchTab = switchTab;
  window.CW.loadWorkflows = loadWorkflows;
  window.CW.loadWfMeta = loadWfMeta;
})();
