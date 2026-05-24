/**
 * Mobile Agent Creator shell.
 */
(function () {
  'use strict';

  var A = window.__APP__ || {};
  var $ = A.$ || function (sel) { return document.querySelector(sel); };
  var escH = A.escH || function (value) {
    var d = document.createElement('div');
    d.textContent = value == null ? '' : String(value);
    return d.innerHTML;
  };
  var API = A.API || window.CW_API_BASE || '';
  var authFetch = A.authFetch || function (url, opts) {
    if (window.CW && CW.auth && typeof CW.auth.apiFetch === 'function') {
      return CW.auth.apiFetch(url, opts);
    }
    return fetch(url, opts);
  };

  var state = {
    root: null,
    mode: 'home',
    text: '',
    understanding: null,
    loading: false,
    error: '',
    active: false,
    sourceImageFile: null,
    sourceImageName: '',
    sourceImagePreviewUrl: '',
    voiceRecording: false,
    voicePending: false,
    voiceBusy: false,
    voiceStatus: '',
    voiceRecorder: null,
    voiceStream: null,
    voiceChunks: [],
    voiceMimeType: ''
  };

  function icon(name) {
    var paths = {
      mic: '<path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z"/><path d="M19 11a7 7 0 0 1-14 0"/><path d="M12 18v3"/><path d="M8 21h8"/>',
      'chevron-left': '<path d="m15 18-6-6 6-6"/>',
      sparkles: '<path d="M12 3l1.7 4.1L18 9l-4.3 1.9L12 15l-1.7-4.1L6 9l4.3-1.9L12 3Z"/><path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z"/>'
    };
    if (paths[name]) {
      return '<svg class="cw-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + paths[name] + '</svg>';
    }
    var rendered = window.CW && typeof CW.icon === 'function' ? CW.icon(name) : '';
    if (rendered) return rendered;
    var fallbackPaths = {
      image: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="m21 15-5-5L5 19"/>',
      send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>'
    };
    return fallbackPaths[name]
      ? '<svg class="cw-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + fallbackPaths[name] + '</svg>'
      : '';
  }

  function toast(message, type) {
    if (window.CW && typeof CW.showToast === 'function') {
      CW.showToast(message, type || 'info');
    }
  }

  function setRootHtml(html) {
    if (!state.root) return;
    state.root.innerHTML = html;
    state.root.classList.remove('hidden');
    if (document.body && document.body.setAttribute) {
      document.body.setAttribute('data-mobile-agent-active', 'on');
    }
  }

  function isRouteActive() {
    var path = String(location.pathname || '').replace(/\/+$/, '');
    return location.hash === '#mobile-agent' ||
      path === '/app' ||
      (path === '' && String(location.port || '') === '18002') ||
      !!(document.body && document.body.dataset && document.body.dataset.mobileAgent === 'on');
  }

  function hideMobileAgent() {
    state.active = false;
    if (!state.root) return;
    state.root.classList.add('hidden');
    state.root.innerHTML = '';
    if (document.body && document.body.removeAttribute) {
      document.body.removeAttribute('data-mobile-agent-active');
    }
  }

  function activateMobileAgent() {
    if (!state.root) return;
    state.active = true;
    renderHome();
  }

  function renderHome() {
    var imageIcon = icon('image');
    var micIcon = icon('mic');
    var sendIcon = icon('send');
    var imagePreview = state.sourceImageName
      ? '<div class="mobile-agent-attachment">' +
          (state.sourceImagePreviewUrl ? '<img src="' + escH(state.sourceImagePreviewUrl) + '" alt="已选择图片预览">' : '<span class="mobile-agent-attachment-icon">' + imageIcon + '</span>') +
          '<div><strong>' + escH(state.sourceImageName) + '</strong><span>图片已添加</span></div>' +
          '<button type="button" data-action="remove-image" aria-label="移除图片">×</button>' +
        '</div>'
      : '';
    var voiceActive = state.voicePending || state.voiceRecording || state.voiceBusy;
    var voiceLabel = state.voiceBusy ? '正在识别' : '正在录音识别';
    var voiceWave = '<span class="mobile-agent-wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>';
    var voiceInner = voiceActive
      ? micIcon + '<span class="mobile-agent-voice-label">' + voiceLabel + '</span>' + voiceWave
      : micIcon;
    var voiceText = voiceActive ? '' : state.voiceStatus;
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="home">' +
        '<input id="mobileAgentImageFile" class="mobile-agent-file" type="file" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif">' +
        '<div class="mobile-agent-hero">' +
          '<div class="mobile-agent-brand">' +
            '<span class="mobile-agent-logo-wrap"><img src="static/icons/ez-site-logo-64.png" alt="EZ ComfyUI logo"></span>' +
            '<span class="mobile-agent-brand-title">Ez ComfyUI</span>' +
          '</div>' +
          '<div class="mobile-agent-copy">' +
            '<h1>智能创作</h1>' +
            '<p>说出想法，EZ 会先整理成可确认的创作方案。</p>' +
          '</div>' +
        '</div>' +
        '<label class="mobile-agent-compose">' +
          '<span>描述你想生成的画面</span>' +
          '<textarea id="mobileAgentText" rows="5" placeholder="例如：一张赛博朋克风格的城市夜景，霓虹灯，电影感" autocomplete="off">' + escH(state.text) + '</textarea>' +
        '</label>' +
        imagePreview +
        (voiceText ? '<div class="mobile-agent-voice-status" role="status">' + escH(voiceText) + '</div>' : '') +
        (state.error ? '<div class="mobile-agent-error" role="alert">' + escH(state.error) + '</div>' : '') +
        '<div class="mobile-agent-input-row' + (voiceActive ? ' is-voice-active' : '') + '">' +
          '<button class="mobile-agent-icon-btn" type="button" data-action="image" title="图片输入" aria-label="图片输入">' + imageIcon + '</button>' +
          '<button class="mobile-agent-icon-btn' + (voiceActive ? ' is-recording' : '') + '" type="button" data-action="voice" title="' + (voiceActive ? '停止录音' : '语音输入') + '" aria-label="' + (voiceActive ? '停止录音' : '语音输入') + '"' + (state.voiceBusy ? ' disabled' : '') + '>' + voiceInner + '</button>' +
          '<button class="mobile-agent-send-btn" type="button" data-action="understand" aria-label="发送理解"' + (state.loading ? ' disabled' : '') + '>' +
            '<span>' + (state.loading ? '理解中' : '发送') + '</span>' + sendIcon +
          '</button>' +
        '</div>' +
      '</section>'
    );
  }

  function renderVoice() {
    var transcribePath = API + '/api/mobile-agent/transcribe';
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="voice">' +
        '<button class="mobile-agent-back" type="button" data-action="home">' + icon('chevron-left') + ' 返回</button>' +
        '<div class="mobile-agent-voice-orb">' + icon('mic') + '</div>' +
        '<h1>语音输入</h1>' +
        '<p>录音与转写会接入 <code>' + escH(transcribePath) + '</code>，当前先保留入口。</p>' +
        '<button class="mobile-agent-send-btn" type="button" data-action="home">完成</button>' +
      '</section>'
    );
  }

  function renderConfirm() {
    var data = state.understanding || {};
    var options = data.options || {};
    var selectedStyle = data.style || data.selected_style || '';
    var selectedRatio = data.aspect_ratio || data.selected_ratio || '';
    var styles = options.allowed_styles || data.allowed_styles || data.styles || data.style_chips || (selectedStyle ? [selectedStyle] : []);
    var ratios = options.allowed_ratios || data.allowed_ratios || data.aspect_ratios || data.ratios || (selectedRatio ? [selectedRatio] : []);
    var summary = data.display_summary || data.compiled_prompt || state.text || '请确认创作方案';
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="confirm">' +
        '<button class="mobile-agent-back" type="button" data-action="home">' + icon('chevron-left') + ' 返回</button>' +
        '<div class="mobile-agent-section-label">创作方案</div>' +
        '<h1>确认后开始生成</h1>' +
        '<p class="mobile-agent-summary">' + escH(summary) + '</p>' +
        (state.error ? '<div class="mobile-agent-error" role="alert">' + escH(state.error) + '</div>' : '') +
        '<div class="mobile-agent-selected">' +
          (selectedStyle ? '<span>风格：' + escH(selectedStyle) + '</span>' : '') +
          (selectedRatio ? '<span>画幅：' + escH(selectedRatio) + '</span>' : '') +
        '</div>' +
        '<div class="mobile-agent-chip-group" aria-label="风格">' + styles.map(function (item) {
          var active = selectedStyle && String(item) === String(selectedStyle);
          return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '">' + escH(item) + '</button>';
        }).join('') + '</div>' +
        '<div class="mobile-agent-chip-group" aria-label="画幅">' + ratios.map(function (item) {
          var active = selectedRatio && String(item) === String(selectedRatio);
          return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '">' + escH(item) + '</button>';
        }).join('') + '</div>' +
        '<div class="mobile-agent-actions">' +
          '<button class="mobile-agent-secondary-btn" type="button" data-action="home">返回修改</button>' +
          '<button class="mobile-agent-send-btn" type="button" data-action="generate">' + icon('sparkles') + '<span>生成</span></button>' +
        '</div>' +
      '</section>'
    );
  }

  function renderGenerating() {
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="generating" aria-live="polite">' +
        '<div class="mobile-agent-spinner" aria-hidden="true"></div>' +
        '<h1>正在准备生成</h1>' +
        '<p>移动端生成链路将在 Task 5 接入，这里先保留独立状态页。</p>' +
        '<button class="mobile-agent-secondary-btn" type="button" data-action="home">回到首页</button>' +
      '</section>'
    );
  }

  async function submitUnderstand() {
    if (state.loading) return;
    state.error = '';
    if (!state.text.trim()) {
      state.error = '先输入一点创作想法。';
      renderHome();
      return;
    }
    state.loading = true;
    renderHome();
    try {
      var res = await authFetch(API + '/api/mobile-agent/understand', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: state.text,
          has_image: !!state.sourceImageFile,
          has_video: false
        })
      });
      var payload = await res.json();
      if (!res.ok || payload.ok === false) {
        throw new Error(payload.error || '理解失败');
      }
      state.understanding = payload.data || payload;
      state.mode = 'confirm';
      renderConfirm();
    } catch (err) {
      state.error = err && err.message ? err.message : '理解失败，请稍后重试。';
      state.loading = false;
      renderHome();
    } finally {
      state.loading = false;
    }
  }

  async function submitGenerate() {
    var data = state.understanding || {};
    state.error = '';
    if (!data.resolved_workflow || data.error_code) {
      state.error = data.question || '默认工作流暂不可用。';
      if (state.mode === 'confirm' || state.understanding) renderConfirm();
      else renderHome();
      return;
    }
    state.mode = 'generating';
    renderGenerating();
    try {
      var res = await authFetch(API + '/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow: data.resolved_workflow,
          fields: data.field_values || {},
          width: data.width || 0,
          height: data.height || 0
        })
      });
      var payload = await res.json();
      if (!res.ok || payload.detail) {
        throw new Error(payload.detail || '提交生成失败。');
      }
      state.jobId = payload.job_id;
      toast('已开始生成', 'success');
    } catch (err) {
      state.error = err && err.message ? err.message : '提交生成失败。';
      state.mode = 'confirm';
      renderConfirm();
    }
  }

  function syncRoute() {
    if (!state.root) return;
    if (isRouteActive()) {
      activateMobileAgent();
    } else {
      hideMobileAgent();
    }
  }

  function openMobileAgent() {
    if (location.hash !== '#mobile-agent') {
      location.hash = '#mobile-agent';
    }
    activateMobileAgent();
  }

  function onInput(event) {
    if (event.target && event.target.id === 'mobileAgentText') {
      state.text = event.target.value;
    }
  }

  function clearImagePreview() {
    if (state.sourceImagePreviewUrl && window.URL && typeof window.URL.revokeObjectURL === 'function') {
      window.URL.revokeObjectURL(state.sourceImagePreviewUrl);
    }
    state.sourceImageFile = null;
    state.sourceImageName = '';
    state.sourceImagePreviewUrl = '';
  }

  function openImagePicker() {
    var input = document.getElementById ? document.getElementById('mobileAgentImageFile') : null;
    if (input && typeof input.click === 'function') input.click();
  }

  function onChange(event) {
    if (!event.target || event.target.id !== 'mobileAgentImageFile') return;
    var file = event.target.files && event.target.files[0];
    if (!file) return;
    clearImagePreview();
    state.error = '';
    state.sourceImageFile = file;
    state.sourceImageName = file.name || '已选择图片';
    if (window.URL && typeof window.URL.createObjectURL === 'function') {
      state.sourceImagePreviewUrl = window.URL.createObjectURL(file);
    }
    renderHome();
  }

  function stopVoiceStream() {
    var stream = state.voiceStream;
    state.voiceStream = null;
    if (stream && typeof stream.getTracks === 'function') {
      stream.getTracks().forEach(function (track) {
        if (track && typeof track.stop === 'function') track.stop();
      });
    }
  }

  function voiceCaptureMessage(err) {
    var name = err && err.name ? String(err.name) : '';
    var message = err && err.message ? String(err.message) : '';
    var raw = (name + ' ' + message).toLowerCase();
    if (raw.indexOf('notfound') >= 0 || raw.indexOf('device not found') >= 0 || raw.indexOf('requested device not found') >= 0) {
      return '没有找到可用麦克风，因此不会弹出授权框。请检查系统输入设备。';
    }
    if (raw.indexOf('notallowed') >= 0 || raw.indexOf('permission') >= 0 || raw.indexOf('denied') >= 0) {
      return '麦克风权限未开启，请允许浏览器访问麦克风。';
    }
    if (raw.indexOf('notreadable') >= 0 || raw.indexOf('trackstart') >= 0 || raw.indexOf('hardware') >= 0) {
      return '麦克风暂时不可用，可能正被其他应用占用。';
    }
    if (raw.indexOf('not supported') >= 0 || raw.indexOf('不支持') >= 0 || raw.indexOf('media devices unavailable') >= 0) {
      return '当前浏览器没有开放麦克风接口，请使用 HTTPS 页面或 Chrome/Safari 再试。';
    }
    return '麦克风启动失败，请检查设备和浏览器权限。';
  }

  async function transcribeVoiceChunks(chunks, mimeType) {
    stopVoiceStream();
    state.voiceRecorder = null;
    state.voiceRecording = false;
    state.voicePending = false;
    if (!chunks || !chunks.length) {
      state.voiceStatus = '';
      renderHome();
      return;
    }
    if (!window.FormData || !window.Blob) {
      state.error = '当前浏览器不支持语音文件转写。';
      state.voiceStatus = '';
      renderHome();
      return;
    }
    state.voiceBusy = true;
    state.voiceStatus = '正在转写语音';
    renderHome();
    try {
      var blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
      var fd = new FormData();
      fd.append('file', blob, 'voice.webm');
      fd.append('timeout_ms', '8000');
      var res = await authFetch(API + '/api/mobile-agent/transcribe', { method: 'POST', body: fd });
      var payload = await res.json();
      if (!res.ok || payload.ok === false) throw new Error(payload.message || payload.error || '转写失败');
      var transcript = String(payload.transcript || payload.text || '').trim();
      if (transcript) {
        state.text = state.text.trim() ? state.text.trim() + '\n' + transcript : transcript;
        state.voiceStatus = '语音已转成文字';
      } else {
        state.voiceStatus = '没有识别到文字';
      }
    } catch (err) {
      state.error = '语音转写失败：' + (err && err.message ? err.message : '请稍后重试。');
      state.voiceStatus = '';
    } finally {
      state.voiceBusy = false;
      renderHome();
    }
  }

  async function startVoiceCapture() {
    if (state.voiceBusy) return;
    if (state.voiceRecording) {
      stopVoiceCapture();
      return;
    }
    state.error = '';
    state.voicePending = true;
    state.voiceStatus = '正在请求麦克风';
    renderHome();
    try {
      var mediaDevices = window.navigator && window.navigator.mediaDevices;
      if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
        var unsupported = new Error('media devices unavailable');
        unsupported.name = 'NotSupportedError';
        throw unsupported;
      }
      if (typeof window.MediaRecorder !== 'function') {
        throw new Error('当前浏览器不支持录音');
      }
      var stream = await mediaDevices.getUserMedia({ audio: true });
      var recorder = new MediaRecorder(stream);
      state.voiceChunks = [];
      state.voiceMimeType = recorder.mimeType || 'audio/webm';
      recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) state.voiceChunks.push(event.data);
      };
      recorder.onstop = function () {
        transcribeVoiceChunks(state.voiceChunks.slice(), state.voiceMimeType);
      };
      state.voiceStream = stream;
      state.voiceRecorder = recorder;
      state.voicePending = false;
      state.voiceRecording = true;
      state.voiceStatus = '正在听，点击麦克风停止';
      recorder.start();
      renderHome();
    } catch (err) {
      stopVoiceStream();
      state.voiceRecorder = null;
      state.voicePending = false;
      state.voiceRecording = false;
      state.voiceStatus = '';
      state.error = voiceCaptureMessage(err);
      renderHome();
    }
  }

  function stopVoiceCapture() {
    var recorder = state.voiceRecorder;
    state.voicePending = false;
    state.voiceRecording = false;
    state.voiceStatus = '正在转写语音';
    renderHome();
    try {
      if (recorder && recorder.state !== 'inactive' && typeof recorder.stop === 'function') {
        recorder.stop();
      } else {
        transcribeVoiceChunks(state.voiceChunks.slice(), state.voiceMimeType);
      }
    } catch (err) {
      transcribeVoiceChunks(state.voiceChunks.slice(), state.voiceMimeType);
    }
  }

  function onClick(event) {
    var btn = event.target && event.target.closest ? event.target.closest('[data-action]') : null;
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    if (action === 'home') renderHome();
    if (action === 'image') openImagePicker();
    if (action === 'remove-image') {
      clearImagePreview();
      renderHome();
    }
    if (action === 'voice') startVoiceCapture();
    if (action === 'understand') submitUnderstand();
    if (action === 'generate') submitGenerate();
  }

  function initMobileAgent() {
    state.root = $('#mobileAgentRoot');
    if (!state.root || state.root.dataset.mobileAgentReady === '1') return;
    state.root.dataset.mobileAgentReady = '1';
    state.root.addEventListener('input', onInput);
    state.root.addEventListener('change', onChange);
    state.root.addEventListener('click', onClick);
    if (window.addEventListener) window.addEventListener('hashchange', syncRoute);
    syncRoute();
  }

  window.CW = window.CW || {};
  window.CW.mobileAgent = {
    init: initMobileAgent,
    renderHome: renderHome,
    renderVoice: renderVoice,
    renderConfirm: renderConfirm,
    renderGenerating: renderGenerating,
    submitUnderstand: submitUnderstand,
    submitGenerate: submitGenerate,
    startVoiceCapture: startVoiceCapture,
    stopVoiceCapture: stopVoiceCapture,
    open: openMobileAgent,
    close: hideMobileAgent
  };
  window.CW.initMobileAgent = initMobileAgent;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMobileAgent);
  } else {
    initMobileAgent();
  }
})();
