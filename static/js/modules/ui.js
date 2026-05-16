/**
 * UI Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs;

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

function showToast(message, type) {
  var container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  var icons = { queued: '○', generating: '◔', done: '✓', error: '×' };
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
  t.innerHTML = '<span class="toast-icon">' + (icons[type] || 'i') + '</span>' + escH(message);
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
})();
