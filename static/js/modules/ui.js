/**
 * UI Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
var API = A.API, jobs = A.jobs;

function _ensureToastContainer() {
  var container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  return container;
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

function clearPrompt() {
  var inp = $('#promptInput');
  if (inp) { inp.value = ''; inp.dispatchEvent(new Event('input')); inp.focus(); }
}

function syncClearPromptButton() {
  var inp = $('#promptInput');
  var btn = $('#clearPromptBtn');
  if (!btn) return;
  var hasText = !!(inp && inp.value.trim());
  btn.classList.remove('hidden');
  btn.classList.toggle('is-invisible', !hasText);
  var actions = btn.closest ? btn.closest('.prompt-actions') : null;
  if (actions) actions.classList.toggle('has-content', hasText);
}

function _isGenerationStartToast(message, type) {
  return /开始出图/.test(String(message || '')) &&
    (type === 'generating' || type === 'queued' || type === 'info' || !type);
}

function _isGenerationStatusToastAllowed(message, type) {
  var text = String(message || '');
  if (type === 'done' || type === 'error') return true;
  if (type === 'queued') return /排队中/.test(text);
  if (type === 'generating') return /出图中/.test(text);
  return false;
}

function _isGenerationStatusToast(message, type) {
  var text = String(message || '');
  if (type === 'queued' || type === 'generating') return true;
  if (_isGenerationStartToast(text, type)) return true;
  if ((type === 'done' && /结束出图/.test(text)) || (type === 'error' && /失败/.test(text))) return true;
  return /(排队中|出图中|拉取图片|提交|准备|queued|preparing|starting_comfyui|submitting|generating|downloading)/i.test(text);
}

function showToast(message, type) {
  var container = _ensureToastContainer();
  type = type || 'info';
  var aliases = {
    success: 'done',
    warning: 'warn',
    danger: 'error',
    loading: 'generating'
  };
		  var resolvedType = aliases[type] || type;
  if (_isGenerationStatusToast(message, resolvedType) && !_isGenerationStatusToastAllowed(message, resolvedType)) {
    return;
  }
  var generationSlot = _isGenerationStatusToast(message, resolvedType);
				  var iconMap = {
		    info: 'info',
		    queued: 'clock',
		    generating: 'loader',
		    done: 'check-circle',
		    favorite: 'heart',
		    unfavorite: 'heart',
		    warn: 'alert-triangle',
		    error: 'x-circle'
		  };
  // Dedup: remove existing toast with same message
  var existing = container.querySelectorAll('.toast');
  for (var ei = 0; ei < existing.length; ei++) {
    if ((generationSlot && existing[ei].getAttribute && existing[ei].getAttribute('data-toast-scope') === 'generation') ||
        existing[ei].textContent.indexOf(message) >= 0) {
      existing[ei].parentNode.removeChild(existing[ei]);
      if (!generationSlot) break;
    }
  }
  var t = document.createElement('div');
	  t.className = 'toast toast-' + resolvedType;
  if (generationSlot && t.setAttribute) t.setAttribute('data-toast-scope', 'generation');
	  t.innerHTML = ''
	    + '<span class="toast-icon">' + (window.CW && CW.icon ? CW.icon(iconMap[resolvedType] || 'bell', 16) : '') + '</span>'
	    + '<span class="toast-content">'
	    +   '<span class="toast-message">' + escH(message) + '</span>'
	    + '</span>'
    + '<button class="toast-close" type="button" title="关闭">×</button>';
  var closeBtn = t.querySelector('.toast-close');
  if (closeBtn) closeBtn.addEventListener('click', function () {
    if (t.parentNode) t.parentNode.removeChild(t);
  });
  container.appendChild(t);
  setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 4000);
}

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

function rndSeed(btnEl) {
    const input = btnEl ? btnEl.parentElement.querySelector('input') : null;
    if (input) input.value = Math.floor(Math.random() * 2 ** 53);
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
    window.CW.loadWorkflows();
    window.CW.loadWfMeta();
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

function initAdvToggle() {
    $('#advToggle').addEventListener('click', () => {
      A.advOpen = !A.advOpen;
      $('#advToggle').classList.toggle('open', A.advOpen);
      $('#advBody').classList.toggle('open', A.advOpen);
    });
  }

  if (!window.CW) window.CW = {};
  window.CW.clearPrompt = clearPrompt;
  window.CW.initAdvToggle = initAdvToggle;
  window.CW.initOverlayUpload = initOverlayUpload;
  window.CW.initResizeHandle = initResizeHandle;
  window.CW.initDragScroll = initDragScroll;
  window.CW.toast = showToast;
  window.CW.syncClearPromptButton = syncClearPromptButton;
})();
