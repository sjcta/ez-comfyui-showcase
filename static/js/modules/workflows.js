/**
 * Workflows Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs, historyItems = A.historyItems;

  function authFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {});
    if (window.CW && CW.auth && typeof CW.auth.apiFetch === 'function') {
      return CW.auth.apiFetch(url, opts);
    }
    try {
      var token = localStorage.getItem('v4_token');
      if (token && !opts.headers.Authorization) opts.headers.Authorization = 'Bearer ' + token;
    } catch (e) {}
    return fetch(url, opts);
  }

  // ── Manager toolbar state ──
  var _mgrFilter = '';  // '' = all
  var _mgrSortBy = 'manual';
  var _mgrDragIdx = -1;
  // Drag-detection for card clicks (prevent drag-to-scroll from triggering select)
  var _wfCardDownX = 0, _wfCardDownY = 0, _wfCardMoved = false;
  window.CW._wfCardDown = function(e) {
    _wfCardDownX = e.clientX;
    _wfCardDownY = e.clientY;
    _wfCardMoved = false;
  };
  window.CW._wfCheckMove = function(e) {
    if (!_wfCardMoved && _wfCardDownX && _wfCardDownY) {
      var dx = Math.abs(e.clientX - _wfCardDownX);
      var dy = Math.abs(e.clientY - _wfCardDownY);
      if (dx > 5 || dy > 5) _wfCardMoved = true;
    }
    return _wfCardMoved;
  };

async function confirmWfDel() {
    if (!A._wfDelFilename) return;
    try {
      await fetch(API + '/api/workflows/' + encodeURIComponent(A._wfDelFilename), { method: 'DELETE' });
      delete A._wfMeta[A._wfDelFilename];
    } catch (e) {}
    closeWfDel();
    renderMgrFilterTabs();
    renderWfGrid();
    loadWorkflows();
  }

function closeWfDel() {
    $('#wfDelModal').classList.remove('open');
  }

function downloadWf(fname) {
    window.open(API + "/api/workflows/" + encodeURIComponent(fname) + "/download", "_blank");
}

function openWfDel(fname) {
    A._wfDelFilename = fname;
    const meta = A._wfMeta[fname] || {};
    const displayName = meta.name || fname.replace('.json', '');
    $('#wfDelMsg').textContent = `确定要删除工作流「${displayName}」吗？此操作不可撤销。`;
    $('#wfDelModal').classList.add('open');
  }

function onWfThumbClick(fname) {
    A._wfEditFilename = fname;
    $('#wfEditThumbInput').click();
  }

async function saveWfEdit() {
    if (!A._wfEditFilename) return;
    const name = $('#wfEditName').value.trim() || A._wfEditFilename.replace('.json', '');
    const tags = [...$('#wfEditTags').querySelectorAll('.wf-edit-tag-remove')].map((el) => el.dataset.tag);
    try {
      await fetch(API + '/api/workflows/meta/' + encodeURIComponent(A._wfEditFilename), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, tags }),
      });
      A._wfMeta[A._wfEditFilename] = { ...(A._wfMeta[A._wfEditFilename] || {}), name, tags };
    } catch (e) {}
    closeWfEdit();
    renderWfGrid();
    // Also refresh main workflow grid if it shows names
    loadWorkflows();
  }

async function onWfThumbUpload(e) {
    const file = e.target.files[0];
    if (!file || !A._wfEditFilename) return;
    const fd = new FormData();
    fd.append('filename', A._wfEditFilename);
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

function onAddWfTag(val) {
    if (!val || !val.trim()) return;
    val = val.trim();
    const tagsDiv = $('#wfEditTags');
    // Prevent duplicates
    const existing = [...tagsDiv.querySelectorAll('.wf-edit-tag-remove')].map((el) => el.dataset.tag);
    if (existing.includes(val)) return;
    const span = document.createElement('span');
    span.className = 'wf-edit-tag';
    span.innerHTML = `${escH(val)} <span class="wf-edit-tag-remove" data-tag="${escA(val)}">${CW.icon('x')}</span>`;
    span.querySelector('.wf-edit-tag-remove').addEventListener('click', () => {
      span.remove();
    });
    tagsDiv.appendChild(span);
    // Add to datalist if not already there
    var dl = document.getElementById('wfEditTagSuggest');
    if (dl) {
      var exists = Array.from(dl.options).some(function(o) { return o.value === val; });
      if (!exists) {
        var opt = document.createElement('option');
        opt.value = val;
        dl.appendChild(opt);
      }
    }
  }

function closeWfEdit() {
    $('#wfEditModal').classList.remove('open');
    // Refresh management grid and filter tags after tag edit
    renderMgrFilterTabs();
    renderWfGrid();
  }

function openWfEdit(fname) {
    A._wfEditFilename = fname;
    const meta = A._wfMeta[fname] || {};
    $('#wfEditTitle').textContent = '编辑 ' + (meta.name || fname.replace('.json', ''));
    $('#wfEditName').value = meta.name || fname.replace('.json', '');
    // Render tags
    const tagsDiv = $('#wfEditTags');
    tagsDiv.innerHTML = '';
    (meta.tags || []).forEach((t) => {
      const span = document.createElement('span');
      span.className = 'wf-edit-tag';
      span.innerHTML = `${escH(t)} <span class="wf-edit-tag-remove" data-tag="${escA(t)}">${CW.icon('x')}</span>`;
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
    // Clear tag input
    var tagInput = $('#wfEditTagInput');
    if (tagInput) tagInput.value = '';
    // Load versions
    loadWfVersions(fname);
    // Setup version upload handler
    var vFileInput = $('#wfEditVersionFile');
    if (vFileInput && !vFileInput._bound) {
      vFileInput._bound = true;
      vFileInput.addEventListener('change', async function(e) {
        var file = e.target.files[0];
        if (!file || !A._wfEditFilename) return;
        var fd = new FormData();
        fd.append('file', file);
        try {
          var r = await fetch(API + '/api/workflows/' + encodeURIComponent(A._wfEditFilename) + '/upload-version', { method: 'POST', body: fd });
          if (!r.ok) { var d = await r.json(); throw new Error(d.detail || 'Upload failed'); }
          var d = await r.json();
          alert('版本 ' + d.version + ' 上传成功');
          loadWfVersions(A._wfEditFilename);
          loadWorkflows(); // refresh field cache
        } catch (e) { alert('上传失败: ' + e.message); }
        e.target.value = '';
      });
    }
    $('#wfEditModal').classList.add('open');
    // Focus tag input
    setTimeout(function() {
      var ti = $('#wfEditTagInput');
      if (ti) ti.focus();
    }, 100);
  }

function _tagCls(t) {
    if (t === '图生图') return 'i2i';
    if (t === '文生图') return 't2i';
    if (t === '放大') return 'cat';
    if (t === '文生视频') return 't2v';
    if (t === '图生视频') return 'i2v';
    return 'res';
  }

  function _mgrSortEntries(entries) {
    entries.sort(function(a, b) {
      var oa = (a[1].sort_order != null) ? a[1].sort_order : 9999;
      var ob = (b[1].sort_order != null) ? b[1].sort_order : 9999;
      if (oa !== ob) return oa - ob;
      return a[0].localeCompare(b[0]);
    });
    return entries;
  }

  function renderMgrFilterTabs() {
    var tabsEl = $('#wfMgrFilterTabs');
    if (!tabsEl) return;
    var entries = Object.entries(A._wfMeta);
    var tagCounts = {};
    tagCounts['全部'] = entries.length;
    for (var i = 0; i < entries.length; i++) {
      var fname = entries[i][0];
      var meta = entries[i][1];
      var mainTag = _getPrimaryTag(fname, meta);
      if (mainTag) tagCounts[mainTag] = (tagCounts[mainTag] || 0) + 1;
    }
    var tagOrder = ['全部', '文生图', '图生图', '放大', '文生视频', '图生视频', '其他'];
    var allTags = Object.keys(tagCounts);
    allTags.sort(function(a, b) {
      if (a === '全部') return -1;
      if (b === '全部') return 1;
      var ai = tagOrder.indexOf(a), bi = tagOrder.indexOf(b);
      if (ai >= 0 && bi >= 0) return ai - bi;
      if (ai >= 0) return -1;
      if (bi >= 0) return 1;
      return a.localeCompare(b, 'zh');
    });
    var html = '';
    for (var k = 0; k < allTags.length; k++) {
      var t = allTags[k];
      var active = _mgrFilter === t || (t === '全部' && !_mgrFilter);
      html += '<button class="wf-mgr-filter-tab' + (active ? ' active' : '') + '" data-mgr-tag="' + escA(t) + '" onclick="CW.mgrFilterTag(\'' + escA(t) + '\')">' + escH(t) + '<span class="count">' + tagCounts[t] + '</span></button>';
    }
    tabsEl.innerHTML = html;
  }

  function _getPrimaryTag(fname, meta) {
    var tags = meta.tags || [];
    var typeTag = window.CW.getWFType(fname);
    return typeTag ? typeTag.text : (tags[0] || '其他');
  }

  function mgrFilterTag(tag) {
    _mgrFilter = (tag === '全部') ? '' : tag;
    renderMgrFilterTabs();
    renderWfGrid();
  }

  function toggleMgrSortDir() {}

function renderWfGrid() {
    const grid = $('#wfOverlayGrid');
    const empty = $('#wfOverlayEmpty');
    var currentUser = window.CW && CW.auth && CW.auth.getCurrentUser ? CW.auth.getCurrentUser() : null;
    var isAdmin = !!(currentUser && currentUser.role === 'admin');
    var entries = Object.entries(A._wfMeta);
    // removed
    if (!entries.length) {
      grid.innerHTML = '';
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';

    // Filter by primary tag only
    if (_mgrFilter) {
      entries = entries.filter(function(e) {
        return _getPrimaryTag(e[0], e[1]) === _mgrFilter;
      });
    }
    // Sort
    _mgrSortEntries(entries);

    let html = '';
    for (var _mi = 0; _mi < entries.length; _mi++) {
      var fname = entries[_mi][0], meta = entries[_mi][1];
      const displayName = meta.name || fname.replace('.json', '');
      const tags = meta.tags || [];
      const thumbUrl = meta.thumbnail ? API + '/api/workflows/thumbnail/' + meta.thumbnail : '';
      const sharedTag = meta.shared ? '<span class="wf-mgr-tag res">共享</span>' : '';
      const tagHtml = tags.map(function(t) {
        return '<span class="wf-mgr-tag ' + _tagCls(t) + '">' + escH(t) + '</span>';
      }).join('');
      var _pcat = _getPrimaryTag(fname, meta);
      html += '<div class="wf-mgr-card" data-fname="' + escA(fname) + '" data-idx="' + _mi + '" data-cat="' + escA(_pcat) + '">' +
      '<div class="wf-mgr-drag" draggable="true" ondragstart="WF_MGR._mgrDragStart(event)" ondragover="WF_MGR._mgrDragOver(event)" ondrop="WF_MGR._mgrDrop(event)" ondragend="WF_MGR._mgrDragEnd(event)" ontouchstart="WF_MGR._touchDragStart(event)" ontouchmove="WF_MGR._touchDragMove(event)" ontouchend="WF_MGR._touchDragEnd(event)">⠿</div>' +
      '<div class="wf-mgr-card-thumb" onclick="CW.onWfThumbClick(\'' + escA(fname) + '\')">' +
        (thumbUrl ? '<img src="' + thumbUrl + '" alt="">' : '<div class="wf-mgr-card-thumb-placeholder">'+CW.icon('camera')+'</div>') +
      '</div>' +
      '<div class="wf-mgr-card-body">' +
        '<div class="wf-mgr-info">' +
          '<div class="wf-mgr-card-name" title="' + escA(displayName) + '">' + escH(displayName) + ' ' + ((tagHtml || sharedTag) ? '<span class="wf-mgr-tags">' + tagHtml + sharedTag + '</span>' : '') + '</div>' +
          '<div class="wf-mgr-card-filename" title="' + escA(fname) + '">' + escH(fname) + '</div>' +
        '</div>' +
        '<div class="wf-mgr-card-actions">' +
          '<button class="wf-mgr-btn" onclick="CW.openWfEdit(\'' + escA(fname) + '\')">'+CW.icon('pencil')+' 编辑</button>' +
          '<button class="wf-mgr-btn" onclick="CW.openNodeEditor(\'' + escA(fname) + '\')">'+CW.icon('settings')+' 节点</button>' +
          '<button class="wf-mgr-btn" onclick="CW.downloadWf(\'' + escA(fname) + '\')">'+CW.icon('download')+' 下载</button>' +
          (isAdmin ? '<button class="wf-mgr-btn wf-share-btn ' + (meta.shared ? 'is-shared' : 'is-private') + '" title="' + (meta.shared ? '点击取消共享' : '点击设为共享') + '" onclick="CW.toggleWfShare(\'' + escA(fname) + '\',' + (!meta.shared) + ')">' + CW.icon('share') + (meta.shared ? ' 已共享' : ' 未共享') + '</button>' : '') +
          '<button class="wf-mgr-btn danger" onclick="CW.openWfDel(\'' + escA(fname) + '\')">'+CW.icon('trash-2')+' 删除</button>' +
        '</div>' +
      '</div>' +
    '</div>';
    }
    grid.innerHTML = html;
  }

  function _updateWfShareCard(fname) {
    var card = document.querySelector('.wf-mgr-card[data-fname="' + fname.replace(/"/g, '\\"') + '"]');
    if (!card) return;
    var meta = (A._wfMeta && A._wfMeta[fname]) || {};
    var shared = !!meta.shared;
    var shareBtn = card.querySelector('.wf-share-btn');
    if (shareBtn) {
      shareBtn.classList.toggle('is-shared', shared);
      shareBtn.classList.toggle('is-private', !shared);
      shareBtn.title = shared ? '点击取消共享' : '点击设为共享';
      shareBtn.innerHTML = CW.icon('share') + (shared ? ' 已共享' : ' 未共享');
      shareBtn.setAttribute('onclick', "CW.toggleWfShare('" + escA(fname) + "'," + (!shared) + ")");
    }
    var nameRow = card.querySelector('.wf-mgr-card-name');
    var tagsWrap = nameRow ? nameRow.querySelector('.wf-mgr-tags') : null;
    if (!nameRow) return;
    var sharedTag = tagsWrap ? Array.from(tagsWrap.querySelectorAll('.wf-mgr-tag')).find(function(el) {
      return (el.textContent || '').trim() === '共享';
    }) : null;
    if (shared) {
      if (!tagsWrap) {
        tagsWrap = document.createElement('span');
        tagsWrap.className = 'wf-mgr-tags';
        nameRow.appendChild(document.createTextNode(' '));
        nameRow.appendChild(tagsWrap);
      }
      if (!sharedTag) {
        sharedTag = document.createElement('span');
        sharedTag.className = 'wf-mgr-tag res';
        sharedTag.textContent = '共享';
        tagsWrap.appendChild(sharedTag);
      }
    } else if (sharedTag) {
      sharedTag.remove();
      if (tagsWrap && !tagsWrap.children.length) tagsWrap.remove();
    }
  }

async function loadWfMeta() {
    try {
      const r = await authFetch(API + '/api/workflows/meta');
      A._wfMeta = await r.json();
    } catch (e) {
      A._wfMeta = {};
    }
    renderMgrFilterTabs();
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
      const r = await authFetch(API + '/api/workflow-dirs');
      const dirs = await r.json();
      const list = $('#wfDirsList');
      if (!list) return;
      list.innerHTML = dirs
        .map((d) => {
          const escPath = escA(d.path);
          const status = d.exists
            ? `<span class="wf-dir-count">${d.count} workflows</span>`
            : `<span class="wf-dir-missing">${CW.icon('alert-triangle')} 不存在</span>`;
          const delBtn =
            dirs.length > 1
              ? `<button class="wf-dir-del" onclick="CW.removeWfDir('${escPath}')" title="移除">${CW.icon('x')}</button>`
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
    // Sync selection bar tabs after management changes
    _syncSelectionBar();
  }

  function _syncSelectionBar() {
    // Reload meta and refresh the selection bar tabs
    if (window.CW.loadWorkflows) window.CW.loadWorkflows();
  }

function openWfMgr() {
    $('#wfOverlay').classList.add('open');
    if (window.CW && CW.showWfTab) CW.showWfTab();
    else { loadWfMeta(); }
    // Populate device select for sync
    _populateSyncDevice();
  }

  async function _populateSyncDevice() {
    var sel = $('#wfMgrDeviceSelect');
    if (!sel) return;
    try {
      var r = await authFetch(API + '/api/nodes');
      var d = await r.json();
      if (!d.ok) return;
      sel.innerHTML = '<option value="">选择设备...</option>';
      for (var n of d.data) {
        if (n.connection === 'local') continue;
        var opt = document.createElement('option');
        opt.value = n.id;
        opt.textContent = n.name + ' (' + n.connection + ')';
        sel.appendChild(opt);
      }
    } catch (e) { /* ignore */ }
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

  function toggleWfShare(fname, shared) {
    authFetch(API + '/api/workflows/meta/' + encodeURIComponent(fname), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shared: shared })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '操作失败'); });
      return r.json();
    }).then(function(saved) {
      if (!A._wfMeta[fname]) A._wfMeta[fname] = {};
      A._wfMeta[fname] = Object.assign({}, A._wfMeta[fname], saved || {});
      if (!!A._wfMeta[fname].shared !== !!shared) {
        throw new Error('共享状态未保存，请刷新后重试');
      }
      _updateWfShareCard(fname);
    }).then(function() {
      CW.toast(shared ? '工作流已共享' : '已取消共享', 'done');
    }).catch(function(e) {
      CW.toast(e.message || '共享状态保存失败，请确认当前账号是管理员', 'error');
    });
  }

function _applyTabFilter() {
    const tab = A._currentTab || '全部';
    [...$$('.wf-card')].forEach((el) => {
      if (tab === '全部') { el.style.display = ''; return; }
      const cat = el.dataset.cat || '';
      const wName = el.dataset.name;
      const meta = (A._wfMeta || {})[wName] || {};
      const tags = meta.tags || [];
      el.style.display = (cat === tab || tags.includes(tab)) ? '' : 'none';
    });
  }

function switchTab(tab) {
    A._currentTab = tab || '全部';
    // Update active tab button
    $$('.wf-tab').forEach((el) => el.classList.toggle('active', el.dataset.tab === tab));
    _applyTabFilter();
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

function _isInView(el, container) {
  var cr = el.getBoundingClientRect();
  var vr = container.getBoundingClientRect();
  return cr.right <= vr.right && cr.left >= vr.left;
}


async function selectWF(name) {
    A.currentWF = name;
    try {
      localStorage.setItem('cw:lastWF', name);
    } catch {}
    highlightWF();
    // Switch tab to match this workflow category
    var grid = $('#wfGrid');
    var snapType = grid ? grid.style.scrollSnapType : '';
    if (grid) grid.style.scrollSnapType = 'none';
    var _tag = window.CW.wfTag(name, (A._wfMeta[name] || {}).tags);
    if (_tag && window.CW.switchTab) window.CW.switchTab(_tag.text);
    // Scroll active card into view (wait for layout after tab switch)
    requestAnimationFrame(function() {
      var ac = $$('.wf-card.active')[0];
      if (ac) {
        if (grid && !_isInView(ac, grid)) {
          ac.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        }
      }
      if (grid) grid.style.scrollSnapType = snapType || '';
    });
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
      // Preserve uploaded reference image
      var _savedRefVal = $('#refImageValue')?.value || '';
      var _savedRefSrc = $('#refImagePreview')?.src || '';
      const r = await authFetch(`${API}/api/workflows/${encodeURIComponent(name)}/fields`);
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
      // Quick form is dynamically built from workflow fields
      if (window.CW.renderQuickForm) { try { window.CW.renderQuickForm(fields); } catch(e) { console.error('renderQuickForm error:', e); } }
      // Restore reference image if the new workflow has a LoadImage field
      var _newRefInput = $('#refImageValue');
      if (_newRefInput && _savedRefVal) {
        _newRefInput.value = _savedRefVal;
        var _preview = $('#refImagePreview');
        var _ph = $('#refImagePlaceholder');
        if (_preview) { _preview.src = _savedRefSrc || (API + '/api/input-image/' + encodeURIComponent(_savedRefVal)); _preview.style.display = ''; }
        if (_ph) _ph.style.display = 'none';
      }
    } catch (e) {
      console.error('selectWF:', e);
    }
  }

async function loadWorkflows() {
    try {
      const [r, metaR] = await Promise.all([authFetch(`${API}/api/workflows`), authFetch(`${API}/api/workflows/meta`)]);
      const wfs = await r.json();
      try {
        A._wfMeta = await metaR.json();
      } catch (e) {
        A._wfMeta = {};
      }
      // Sort wfs by manual sort_order from _wfMeta
      wfs.sort(function(a, b) {
        var oa = ((A._wfMeta[a.name] || {}).sort_order != null) ? A._wfMeta[a.name].sort_order : 9999;
        var ob = ((A._wfMeta[b.name] || {}).sort_order != null) ? A._wfMeta[b.name].sort_order : 9999;
        if (oa !== ob) return oa - ob;
        return a.name.localeCompare(b.name);
      });
      var wfCountEl = $('#wfCount');
      if (wfCountEl) wfCountEl.textContent = `(${wfs.length})`;
      const grid = $('#wfGrid');
      if (!wfs.length) {
        grid.innerHTML =
          '<div class="wf-empty">无 workflow</div>';
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
      // Build wfTagMap BEFORE card loop (first tag = primary category)
      const PRIORITY_TAGS = ['文生图', '图生图', '文生视频', '图生视频', '放大'];
      const wfTagMap = {};
      const wfAllTags = {};
      wfs.forEach(w => {
        const meta = A._wfMeta[w.name] || {};
        const tags = meta.tags || [];
        const typeTag = window.CW.getWFType(w.name);
        const mainTag = typeTag ? typeTag.text : (tags[0] || '其他');
        wfTagMap[w.name] = mainTag;
        wfAllTags[w.name] = tags;
      });
      // Tag color scheme (const avoids TDZ/hoisting issues)
      var _tagColor = function(t) {
        if (t === '图生图') return 'wf-tag-i2i';
        if (t === '文生图') return 'wf-tag-t2i';
        if (t === '文生视频') return 'wf-tag-t2v';
        if (t === '图生视频') return 'wf-tag-i2v';
        if (t === '放大') return 'wf-tag-cat';
        if (/^\d+K$/.test(t)) return 'wf-tag-res';
        return '';
      };
      let cards = wfs
        .map((w) => {
          const meta = A._wfMeta[w.name] || {};
          const displayName = meta.name || w.name.replace('.json', '');
          const count = wfCounts[w.name] || 0;
          const thumb = wfThumbs[w.name];
          const previewSrc = thumb ? `${API}/api/thumbs/${thumb}` : '';
          const previewImg = previewSrc
            ? `<img src="${previewSrc}" loading="lazy" alt="" draggable="false">`
            : `<div class="wf-card-icon">${CW.icon('settings-2')}</div>`;
          const catText = wfTagMap[w.name] || '其他';
          const extraTags = (wfAllTags[w.name] || []).filter(t => t !== catText).map(t =>
            `<span class="wf-tag ${_tagColor(t)} wf-tag-sm">${escH(t)}</span>`
          ).join('');
          return `<div class="wf-card" data-name="${escA(w.name)}" data-cat="${escH(catText)}" onmousedown="CW._wfCardDown(event)" onclick="if(!CW._wfCheckMove(event))CW.selectWF('${escA(w.name)}')">
        <div class="wf-card-preview">${previewImg}</div>
        <div class="wf-card-body">
          <div class="wf-card-name" title="${escA(w.name)}">
            <span class="wf-card-name-text">${escH(displayName)}</span>
            ${extraTags}
          </div>
        </div>
      </div>`;
        })
        .join('');
      grid.innerHTML = cards;
      // Build dynamic tabs from all workflow tags
      const allTags = new Set();
      wfs.forEach(w => {
        const meta = A._wfMeta[w.name] || {};
        const tags = meta.tags || [];
        const typeTag = window.CW.getWFType(w.name);
        const mainTag = typeTag ? typeTag.text : (tags[0] || '');
        wfTagMap[w.name] = mainTag;
        if (mainTag) allTags.add(mainTag);
      });
      // Sort: priority tags first, then alphabetically
      const sortedTags = [...allTags].sort((a, b) => {
        const ai = PRIORITY_TAGS.indexOf(a), bi = PRIORITY_TAGS.indexOf(b);
        if (ai >= 0 && bi >= 0) return ai - bi;
        if (ai >= 0) return -1;
        if (bi >= 0) return 1;
        return a.localeCompare(b, 'zh');
      });
      const tabsEl = $('#wfTabs');
      if (tabsEl) {
        let tabHtml = `<button class="wf-tab ${A._currentTab === '全部' ? 'active' : ''}" data-tab="全部" onclick="CW.switchTab('全部')"><span>全部</span> (${wfs.length})</button>`;
        for (const t of sortedTags) {
          const catWfs = wfs.filter(w => {
            const meta = A._wfMeta[w.name] || {};
            const tags = meta.tags || [];
            const typeTag = window.CW.getWFType(w.name);
            const mainTag = typeTag ? typeTag.text : (tags[0] || '');
            return mainTag === t;
          });
          tabHtml += `<button class="wf-tab wf-tab-${_tagCls(t)} ${A._currentTab === t ? 'active' : ''}" data-tab="${t}" onclick="CW.switchTab('${t}')"><span>${t}</span> (${catWfs.length})</button>`;
        }
        tabsEl.innerHTML = tabHtml;
        if (window.CW && typeof CW.refreshHistoryTypeFilters === 'function') {
          CW.refreshHistoryTypeFilters();
        }
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
      console.error("loadWorkflows:", e.message || "", e.stack || "(no stack)");
    }
  }


async function loadWfVersions(fname) {
    var list = $('#wfEditVersionList');
    var hint = $('#wfEditVersionHint');
    if (!list) return;
    list.innerHTML = '<span class="dim-tag">加载中...</span>';
    try {
      var r = await authFetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/versions');
      var d = await r.json();
      var versions = d.versions || {};
      var active = d.active_version || '';
      var keys = Object.keys(versions).sort();
      if (!keys.length) {
        // Show base version (current file) with download
        var baseHtml = '';
        if (d.base && d.base.filename) {
          baseHtml = '<div class="wf-version-item active">' +
            '<span class="wf-version-name">基础版本</span>' +
            '<span class="wf-version-filename">' + escH(d.base.filename) + '</span>' +
            '<div class="wf-version-actions">' +
              '<span class="wf-version-badge">'+CW.icon('check-circle')+' 当前</span>' +
              '<button class="wf-mgr-btn" onclick="CW.downloadWf(\'' + escA(d.base.filename) + '\')">'+CW.icon('download')+' 下载</button>' +
            '</div></div>';
        }
        list.innerHTML = baseHtml || '<span class="dim-tag">尚无版本</span>';
        if (hint) hint.textContent = '上传将保留当前版本';
        return;
      }
      var html = '';
      // Show base version first
      if (d.base && d.base.filename) {
        var isBaseActive = !active;
        html += '<div class="wf-version-item' + (isBaseActive ? ' active' : '') + '">';
        html += '<span class="wf-version-name">基础版本</span>';
        html += '<span class="wf-version-filename">' + escH(d.base.filename) + '</span>';
        html += '<div class="wf-version-actions">';
        if (isBaseActive) html += '<span class="wf-version-badge">'+CW.icon('check-circle')+' 当前</span>';
        html += '<button class="wf-mgr-btn" onclick="CW.downloadWf(\'' + escA(d.base.filename) + '\')">'+CW.icon('download')+' 下载</button>';
        html += '</div></div>';
      }
      for (var k of keys) {
        var isActive = k === active;
        html += '<div class="wf-version-item' + (isActive ? ' active' : '') + '">';
        html += '<span class="wf-version-name">' + escH(k) + '</span>';
        html += '<div class="wf-version-actions">';
        if (isActive) {
          html += '<span class="wf-version-badge">'+CW.icon('check-circle')+' 当前</span>';
          html += '<button class="wf-mgr-btn" onclick="CW.downloadWf(\'' + escA(fname) + '\',\'' + escA(k) + '\')">'+CW.icon('download')+' 下载</button>';
        } else {
          html += '<button class="wf-mgr-btn wf-version-activate" onclick="CW.activateWfVersion(\'' + escA(fname) + '\',\'' + escA(k) + '\')">激活</button>';
          html += '<button class="wf-mgr-btn" onclick="CW.downloadWf(\'' + escA(fname) + '\',\'' + escA(k) + '\')">'+CW.icon('download')+' 下载</button>';
        }
        // Delete (v1 cannot be deleted)
        if (k !== 'v1') {
          html += '<button class="wf-mgr-btn danger" onclick="CW.delVersion(\'' + escA(fname) + '\',\'' + escA(k) + '\')" title="删除版本">'+CW.icon('trash-2')+' 删除</button>';
        }
        html += '</div></div>';
      }
      list.innerHTML = html;
      if (hint) hint.textContent = keys.length + ' 个版本';
    } catch (e) {
      list.innerHTML = '<span class="wf-err-tag">加载失败</span>';
    }
  }

  async function activateWfVersion(fname, version) {
    try {
      var r = await fetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/activate-version', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: version }),
      });
      if (!r.ok) { var d = await r.json(); throw new Error(d.detail || 'Activate failed'); }
      alert('✅ 已切换到版本 ' + version);
      loadWfVersions(fname);
      loadWorkflows();
    } catch (e) { alert('激活失败: ' + e.message); }
  }

  async function delVersion(fname, version) {
    if (!confirm('确定删除版本 ' + version + ' 吗？')) return;
    try {
      var r = await fetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/versions/' + encodeURIComponent(version), { method: 'DELETE' });
      if (!r.ok) { var d = await r.json(); throw new Error(d.detail || '删除失败'); }
      if (window.CW && window.CW.loadWfVersions) CW.loadWfVersions(fname);
    } catch(e) { alert('删除失败: ' + e.message); }
  }

  if (!window.CW) window.CW = {};

function setMgrFilter(val) {
    _mgrFilter = val || '';
    renderMgrFilterTabs();
}

function onWfMgrDeviceChange(deviceId) {
    var btn = $('#wfMgrSyncBtn');
    if (btn) btn.disabled = !deviceId;
}

function manualSyncWorkflows() {
    var sel = $('#wfMgrDeviceSelect');
    var deviceId = sel ? sel.value : '';
    if (!deviceId) return;
    syncRemoteWorkflows();
}

  window.CW.selectWF = selectWF;
  window.CW.loadWfVersions = loadWfVersions;
  window.CW.activateWfVersion = activateWfVersion;
window.CW.delVersion = delVersion;
  window.CW.clearWF = clearWF;
  window.CW.delWF = delWF;
  window.CW.uploadWF = uploadWF;
  window.CW.toggleWfShare = toggleWfShare;
  window.CW.openWfMgr = openWfMgr;
  window.CW.closeWfMgr = closeWfMgr;
  window.CW.openWfEdit = openWfEdit;
  window.CW.closeWfEdit = closeWfEdit;
  window.CW.saveWfEdit = saveWfEdit;
  window.CW.onAddWfTag = onAddWfTag;
  window.CW.onWfThumbUpload = onWfThumbUpload;
  window.CW.onWfThumbClick = onWfThumbClick;
  window.CW.downloadWf = downloadWf;
  window.CW.openWfDel = openWfDel;
  window.CW.closeWfDel = closeWfDel;
  window.CW.confirmWfDel = confirmWfDel;
  window.CW.loadWfDirs = loadWfDirs;
  window.CW.showAddDir = showAddDir;
  window.CW.hideAddDir = hideAddDir;
  window.CW.addWfDir = addWfDir;
  window.CW.removeWfDir = removeWfDir;
  // ── Drag-to-reorder (desktop + mobile touch) ──
  var WF_MGR = {};
  WF_MGR._mgrDragStart = function(e) {
    _mgrDragIdx = parseInt(e.currentTarget.closest('.wf-mgr-card').dataset.idx);
    e.currentTarget.style.opacity = '.4';
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(_mgrDragIdx));
  };
  WF_MGR._mgrDragOver = function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    var card = e.currentTarget.closest('.wf-mgr-card');
    if (card) card.style.borderTop = '2px solid var(--accent)';
  };
  WF_MGR._mgrDrop = function(e) {
    e.preventDefault();
    var card = e.currentTarget.closest('.wf-mgr-card');
    if (card) card.style.borderTop = '';
    var targetIdx = parseInt(card ? card.dataset.idx : -1);
    _mgrApplyReorder(targetIdx);
  };
  WF_MGR._mgrDragEnd = function(e) {
    _mgrDragIdx = -1;
    e.currentTarget.style.opacity = '';
    $$('.wf-mgr-card').forEach(function(c) { c.style.borderTop = ''; });
  };

  // Shared reorder logic
  function _mgrApplyReorder(targetIdx) {
    if (_mgrDragIdx === targetIdx || _mgrDragIdx < 0) return;
    var entries = Object.entries(A._wfMeta);
    _mgrSortEntries(entries);
    var moved = entries.splice(_mgrDragIdx, 1)[0];
    entries.splice(targetIdx, 0, moved);
    for (var i = 0; i < entries.length; i++) {
      var fn = entries[i][0];
      if (!A._wfMeta[fn]) A._wfMeta[fn] = {};
      A._wfMeta[fn].sort_order = i;
    }
    _mgrSaveSortOrder(entries);
    renderWfGrid();
  }

  function _mgrSaveSortOrder(entries) {
    fetch(API + '/api/workflows/meta/sort', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(
        entries.map(function(e, i) { return [e[0], i]; })
      ))
    }).catch(function(err) { console.error('sort save failed:', err); });
  }

  // Touch-based drag for mobile
  var _touchDragEl = null;
  var _touchStartY = 0;
  var _touchStartIdx = -1;
  var _touchGhost = null;
  var _touchTargetIdx = -1;

  WF_MGR._touchDragStart = function(e) {
    var handle = e.currentTarget;
    var card = handle.closest('.wf-mgr-card');
    if (!card) return;
    _touchDragEl = card;
    _touchStartIdx = parseInt(card.dataset.idx);
    _touchStartY = e.touches[0].clientY;
    _touchTargetIdx = _touchStartIdx;
    _mgrDragIdx = _touchStartIdx;
    // Create ghost element
    _touchGhost = card.cloneNode(true);
    _touchGhost.style.position = 'fixed';
    _touchGhost.style.zIndex = '9999';
    _touchGhost.style.opacity = '0.85';
    _touchGhost.style.pointerEvents = 'none';
    _touchGhost.style.width = card.offsetWidth + 'px';
    _touchGhost.style.left = card.getBoundingClientRect().left + 'px';
    _touchGhost.style.top = (e.touches[0].clientY - 20) + 'px';
    _touchGhost.style.boxShadow = '0 4px 20px rgba(0,0,0,.3)';
    document.body.appendChild(_touchGhost);
    card.style.opacity = '0.3';
    e.preventDefault();
  };

  WF_MGR._touchDragMove = function(e) {
    if (!_touchGhost) return;
    e.preventDefault();
    var y = e.touches[0].clientY;
    _touchGhost.style.top = (y - 20) + 'px';
    // Find target card under touch point
    _touchGhost.style.display = 'none';
    var el = document.elementFromPoint(e.touches[0].clientX, y);
    _touchGhost.style.display = '';
    if (!el) return;
    var targetCard = el.closest('.wf-mgr-card');
    if (targetCard && targetCard !== _touchDragEl) {
      _touchTargetIdx = parseInt(targetCard.dataset.idx);
      $$('.wf-mgr-card').forEach(function(c) { c.style.borderTop = ''; });
      targetCard.style.borderTop = '2px solid var(--accent)';
    }
  };

  WF_MGR._touchDragEnd = function(e) {
    if (_touchGhost) {
      _touchGhost.remove();
      _touchGhost = null;
    }
    if (_touchDragEl) {
      _touchDragEl.style.opacity = '';
      _touchDragEl = null;
    }
    $$('.wf-mgr-card').forEach(function(c) { c.style.borderTop = ''; });
    if (_touchTargetIdx !== _touchStartIdx && _touchTargetIdx >= 0) {
      _mgrApplyReorder(_touchTargetIdx);
    }
    _touchTargetIdx = -1;
    _mgrDragIdx = -1;
  };

  // Expose as window.WF_MGR too
  window.WF_MGR = WF_MGR;

  // ── Remote Workflow Sync ──
  var _syncing = false;

  async function syncRemoteWorkflows() {
    if (_syncing) return;
    var sel = $('#wfMgrDeviceSelect');
    var deviceId = sel ? sel.value : '';
      if (!deviceId) {
      if (label) { label.textContent = '请先选择要同步的设备'; label.className = 'wf-sync-err'; }
      return;
    }
    _syncing = true;
    var btn = $('#wfSyncBtn');
    var label = $('#wfSyncLabel');
    if (btn) { btn.disabled = true; btn.textContent = '同步中...'; }
    if (label) { label.textContent = '同步远程工作流中...'; label.className = ''; }
    try {
      var r = await fetch(API + '/api/workflows/sync?device=' + encodeURIComponent(deviceId), { method: 'POST' });
      var d = await r.json();
      if (d.ok && d.data) {
        var data = d.data;
        var msg = '';
        if (data.synced > 0) msg += '已同步 ' + data.synced + ' 个工作流';
        else msg += '已是最新';
        if (data.errors > 0) msg += '，' + data.errors + ' 个错误';
        msg += '（共扫描 ' + data.total + ' 个）';
        if (label) { label.textContent = msg; label.className = 'wf-sync-ok'; }
        if (data.synced > 0) {
          // Refresh workflow lists
          loadWorkflows();
          loadWfMeta();
        }
      } else {
        if (label) { label.textContent = '同步失败: ' + (d.detail || JSON.stringify(d)); label.className = 'wf-sync-err'; }
      }
    } catch (e) {
      if (label) { label.textContent = '同步出错: ' + e.message; label.className = 'wf-sync-err'; }
    } finally {
      _syncing = false;
      if (btn) { btn.disabled = false; btn.textContent = '同步'; }
      // Auto-clear status after 10 seconds
      setTimeout(function() {
        var lbl = $('#wfSyncLabel');
        if (lbl && lbl.className !== 'wf-sync-err') {
          lbl.textContent = '点击同步从远程设备拉取工作流';
          lbl.className = 'dim-tag';
        }
      }, 10000);
    }
  }

  window.CW.switchTab = switchTab;
  window.CW.loadWorkflows = loadWorkflows;
  window.CW.setMgrFilter = setMgrFilter;
  window.CW.onWfMgrDeviceChange = onWfMgrDeviceChange;
  window.CW.manualSyncWorkflows = manualSyncWorkflows;
  window.CW.syncRemoteWorkflows = syncRemoteWorkflows;
  window.CW.loadWfMeta = loadWfMeta;
  window.CW.mgrFilterTag = mgrFilterTag;
  window.CW.renderMgrFilterTabs = renderMgrFilterTabs;
  window.CW.getMgrSortBy = function() { return 'manual'; };

})();
