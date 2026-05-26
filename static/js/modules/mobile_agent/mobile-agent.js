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

  function renderInlineMarkdown(value) {
    var html = escH(value || '');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    return html;
  }

  function renderMarkdown(value) {
    var text = String(value || '').replace(/\r\n/g, '\n').trim();
    if (!text) return '';
    var parts = text.split(/```/);
    var html = '';
    var renderTextPart = function (part) {
      var out = '';
      var paragraph = [];
      var listItems = [];
      var listType = '';
      var flushParagraph = function () {
        if (!paragraph.length) return;
        out += '<p>' + paragraph.map(renderInlineMarkdown).join('<br>') + '</p>';
        paragraph = [];
      };
      var flushList = function () {
        if (!listItems.length) return;
        out += '<' + listType + '>' + listItems.map(function (item) {
          return '<li>' + renderInlineMarkdown(item) + '</li>';
        }).join('') + '</' + listType + '>';
        listItems = [];
        listType = '';
      };
      part.split('\n').forEach(function (rawLine) {
        var line = rawLine.trim();
        var match;
        if (!line) {
          flushParagraph();
          flushList();
          return;
        }
        if ((match = line.match(/^(#{1,3})\s+(.+)$/))) {
          flushParagraph();
          flushList();
          out += '<h' + match[1].length + '>' + renderInlineMarkdown(match[2]) + '</h' + match[1].length + '>';
          return;
        }
        if ((match = line.match(/^>\s?(.+)$/))) {
          flushParagraph();
          flushList();
          out += '<blockquote>' + renderInlineMarkdown(match[1]) + '</blockquote>';
          return;
        }
        if ((match = line.match(/^[-*]\s+(.+)$/))) {
          flushParagraph();
          if (listType && listType !== 'ul') flushList();
          listType = 'ul';
          listItems.push(match[1]);
          return;
        }
        if ((match = line.match(/^\d+[.)]\s+(.+)$/))) {
          flushParagraph();
          if (listType && listType !== 'ol') flushList();
          listType = 'ol';
          listItems.push(match[1]);
          return;
        }
        flushList();
        paragraph.push(line);
      });
      flushParagraph();
      flushList();
      return out;
    };
    parts.forEach(function (part, index) {
      if (index % 2 === 1) {
        var code = part.replace(/^[a-zA-Z0-9_-]+\n/, '');
        html += '<pre><code>' + escH(code).replace(/\n+$/g, '') + '</code></pre>';
        return;
      }
      html += renderTextPart(part);
    });
    return html;
  }

  function renderPlainText(value) {
    return escH(value || '').replace(/\r?\n/g, '<br>');
  }
  var API = window.CW_MOBILE_API_BASE || A.API || window.CW_API_BASE || '';
  var JOB_API = window.CW_JOB_API_BASE || A.API || window.CW_API_BASE || API;
  var authFetch = A.authFetch || function (url, opts) {
    if (window.CW && CW.auth && typeof CW.auth.apiFetch === 'function') {
      return CW.auth.apiFetch(url, opts);
    }
    return fetch(url, opts);
  };
  var STORAGE_KEY = 'ez_mobile_agent_thread:v1';
  var THREADS_KEY = 'ez_mobile_agent_threads:v1';
  var THINKING_TIMEOUT_MS = 30000;
  var remoteThreadsLoaded = false;
  var threadSyncTimers = {};
  var answerTimers = {};
  var STYLE_HINTS = {
    cinematic: '电影感光影，富有层次的镜头氛围',
    anime: '精致动漫风格，清晰线条和明快色彩',
    realistic: '真实摄影质感，自然光影和细节'
  };
  var RATIO_DIMENSIONS = {
    '1:1': { width: 1024, height: 1024 },
    '3:4': { width: 960, height: 1280 },
    '9:16': { width: 720, height: 1280 }
  };
  var TEXTAREA_MIN_HEIGHT = 28;
  var TEXTAREA_MAX_HEIGHT = 112;

  var state = {
    root: null,
    mode: 'home',
    text: '',
    understanding: null,
    messages: [],
    lastResult: null,
    pendingMessageId: '',
    pendingJobId: '',
    activeThreadId: '',
    menuOpen: false,
    deletedAnswerRefs: [],
    loading: false,
    scrollPending: false,
    authHookBound: false,
    error: '',
    active: false,
    sourceImageFile: null,
    sourceImageName: '',
    sourceImagePreviewUrl: '',
    voiceRecording: false,
    voicePending: false,
    voiceBusy: false,
    voiceStatus: '',
    lastVoiceError: null,
    voiceRecorder: null,
    voiceStream: null,
    voiceChunks: [],
    voiceMimeType: '',
    chromeResizeObserver: null,
    previewResult: null,
    inputBlurTimer: null,
    inputActiveTimer: null,
    auraEnterTimer: null
  };

  function icon(name) {
    var paths = {
      mic: '<path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z"/><path d="M19 11a7 7 0 0 1-14 0"/><path d="M12 18v3"/><path d="M8 21h8"/>',
      'chevron-left': '<path d="m15 18-6-6 6-6"/>',
      x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
      plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
      sparkles: '<path d="M12 3l1.7 4.1L18 9l-4.3 1.9L12 15l-1.7-4.1L6 9l4.3-1.9L12 3Z"/><path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z"/>',
      image: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="m21 15-5-5L5 19"/>',
      send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
      'switch-horizontal': '<path d="M16 3h5v5"/><path d="M4 20 21 3"/><path d="M21 16v5h-5"/><path d="M15 15l6 6"/><path d="M4 4l5 5"/>',
      'thumbs-up': '<path d="M7 10v11"/><path d="M15 5.9 14 10h5.8a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 18.4 21H7"/><path d="M7 10H3v11h4"/><path d="M14 10V5.5A2.5 2.5 0 0 0 11.5 3L7 10"/>',
      'rotate-cw': '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
      'trash-2': '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/>',
      download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
      'file-text': '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>'
    };
    if (paths[name]) {
      return '<svg class="cw-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + paths[name] + '</svg>';
    }
    var rendered = window.CW && typeof CW.icon === 'function' ? CW.icon(name) : '';
    if (rendered) return rendered;
    return '';
  }

  function toast(message, type) {
    if (window.CW && typeof CW.showToast === 'function') {
      CW.showToast(message, type || 'info');
    }
  }

  function makeId(prefix) {
    return String(prefix || 'msg') + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  }

  function currentUser() {
    return window.CW && CW.auth && typeof CW.auth.getCurrentUser === 'function' ? CW.auth.getCurrentUser() : null;
  }

  function readThreads() {
    if (!window.localStorage) return [];
    try {
      var parsed = JSON.parse(localStorage.getItem(THREADS_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.filter(function (item) { return item && item.id; }) : [];
    } catch (_) {
      return [];
    }
  }

  function sortedThreads() {
    return readThreads().slice().sort(function (a, b) {
      return (parseInt(b.updatedAt || 0, 10) || 0) - (parseInt(a.updatedAt || 0, 10) || 0);
    });
  }

  function writeThreads(threads) {
    if (!window.localStorage) return;
    try {
      localStorage.setItem(THREADS_KEY, JSON.stringify((threads || []).slice(0, 30)));
    } catch (_) {}
  }

  function mergeThreads(localThreads, remoteThreads) {
    var byId = {};
    (localThreads || []).concat(remoteThreads || []).forEach(function (thread) {
      if (!thread || !thread.id) return;
      var prev = byId[thread.id];
      var nextTime = parseInt(thread.updatedAt || 0, 10) || 0;
      var prevTime = prev ? (parseInt(prev.updatedAt || 0, 10) || 0) : -1;
      if (!prev || nextTime >= prevTime) {
        byId[thread.id] = thread;
      }
    });
    return Object.keys(byId).map(function (id) { return byId[id]; }).sort(function (a, b) {
      return (parseInt(b.updatedAt || 0, 10) || 0) - (parseInt(a.updatedAt || 0, 10) || 0);
    }).slice(0, 30);
  }

  function canSyncThreads() {
    return !!(currentUser() && authFetch);
  }

  function syncThreadToServer(thread) {
    if (!thread || !thread.id || !canSyncThreads()) return Promise.resolve(null);
    return authFetch(API + '/api/mobile-agent/threads/' + encodeURIComponent(thread.id), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(thread)
    }).catch(function () { return null; });
  }

  function scheduleThreadSync(thread) {
    if (!thread || !thread.id || !canSyncThreads()) return;
    var id = thread.id;
    if (threadSyncTimers[id] && typeof clearTimeout === 'function') {
      clearTimeout(threadSyncTimers[id]);
    }
    var run = function () {
      threadSyncTimers[id] = null;
      syncThreadToServer(thread);
    };
    if (typeof setTimeout === 'function') {
      threadSyncTimers[id] = setTimeout(run, 260);
    } else {
      run();
    }
  }

  function deleteThreadFromServer(threadId) {
    if (!threadId || !canSyncThreads()) return Promise.resolve(null);
    return authFetch(API + '/api/mobile-agent/threads/' + encodeURIComponent(threadId), {
      method: 'DELETE'
    }).catch(function () { return null; });
  }

  function syncLocalThreadsToServer(localThreads, remoteThreads) {
    if (!canSyncThreads()) return;
    var remoteTimes = {};
    (remoteThreads || []).forEach(function (thread) {
      if (!thread || !thread.id) return;
      remoteTimes[thread.id] = parseInt(thread.updatedAt || 0, 10) || 0;
    });
    (localThreads || []).slice(0, 30).forEach(function (thread) {
      if (!thread || !thread.id) return;
      var localTime = parseInt(thread.updatedAt || 0, 10) || 0;
      if (!Object.prototype.hasOwnProperty.call(remoteTimes, thread.id) || localTime > remoteTimes[thread.id]) {
        scheduleThreadSync(thread);
      }
    });
  }

  async function loadRemoteThreads() {
    if (!canSyncThreads()) return readThreads();
    try {
      var res = await authFetch(API + '/api/mobile-agent/threads');
      var payload = await res.json();
      if (!res.ok || payload.ok === false) return readThreads();
      var remote = Array.isArray(payload.data) ? payload.data : [];
      var local = readThreads();
      var merged = mergeThreads(local, remote);
      writeThreads(merged);
      syncLocalThreadsToServer(local, remote);
      remoteThreadsLoaded = true;
      if (state.active) renderActive();
      return merged;
    } catch (_) {
      return readThreads();
    }
  }

  async function refreshPendingJobState() {
    if (!state.pendingJobId || !canSyncThreads()) return null;
    try {
      var res = await authFetch(JOB_API + '/api/jobs/' + encodeURIComponent(state.pendingJobId));
      if (!res.ok) return null;
      var job = await res.json();
      handleJobUpdate(job);
      return job;
    } catch (_) {
      return null;
    }
  }

  function refreshOnForeground() {
    if (document && document.hidden) return;
    if (canSyncThreads()) loadRemoteThreads();
    if (state.pendingJobId) refreshPendingJobState();
  }

  function threadTitle(messages) {
    var userMsg = (messages || []).find(function (msg) { return msg && msg.role === 'user' && msg.text; });
    var title = userMsg ? userMsg.text : '新对话';
    return String(title || '新对话').trim().slice(0, 34);
  }

  function threadPreview(messages) {
    var last = (messages || []).slice().reverse().find(function (msg) { return msg && msg.text; });
    return String(last && last.text ? last.text : '继续这个创作上下文').trim().slice(0, 60);
  }

  function currentThreadSnapshot() {
    return {
      id: state.activeThreadId || makeId('thread'),
      title: threadTitle(state.messages),
      preview: threadPreview(state.messages),
      updatedAt: Date.now(),
      messages: state.messages.slice(-40),
      deletedAnswerRefs: state.deletedAnswerRefs.slice(-8),
      lastResult: state.lastResult || null,
      pendingMessageId: state.pendingMessageId || '',
      pendingJobId: state.pendingJobId || ''
    };
  }

  function upsertCurrentThread() {
    if (!state.messages.length && !state.lastResult && !state.pendingJobId) return;
    if (!state.activeThreadId) state.activeThreadId = makeId('thread');
    var snapshot = currentThreadSnapshot();
    var threads = readThreads().filter(function (item) { return item.id !== snapshot.id; });
    threads.unshift(snapshot);
    writeThreads(threads);
    scheduleThreadSync(snapshot);
  }

  function prepareHomeSubmitThread() {
    if (state.mode !== 'home') return;
    if (state.messages.length || state.lastResult || state.pendingJobId) {
      saveConversation();
    }
    state.activeThreadId = makeId('thread');
    state.messages = [];
    state.lastResult = null;
    state.pendingMessageId = '';
    state.pendingJobId = '';
    state.deletedAnswerRefs = [];
    state.understanding = null;
    state.menuOpen = false;
  }

  function applyThread(thread) {
    thread = thread || {};
    state.activeThreadId = thread.id || makeId('thread');
    state.messages = Array.isArray(thread.messages) ? thread.messages.slice(-40) : [];
    state.lastResult = thread.lastResult || null;
    state.pendingMessageId = thread.pendingMessageId || '';
    state.pendingJobId = thread.pendingJobId || '';
    state.deletedAnswerRefs = Array.isArray(thread.deletedAnswerRefs) ? thread.deletedAnswerRefs.slice(-8) : [];
    var lastConfirm = state.messages.slice().reverse().find(function (msg) {
      return msg && msg.type === 'confirm' && msg.data;
    });
    state.understanding = lastConfirm ? lastConfirm.data : null;
  }

  function loadConversation() {
    if (!window.localStorage) return;
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      var parsed = JSON.parse(raw);
      applyThread(Object.assign({ id: parsed.activeThreadId || parsed.id || makeId('thread') }, parsed));
      upsertCurrentThread();
      refreshPendingJobState();
    } catch (_) {}
  }

  function saveConversation() {
    if (!window.localStorage) return;
    try {
      if (!state.activeThreadId) state.activeThreadId = makeId('thread');
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        id: state.activeThreadId,
        activeThreadId: state.activeThreadId,
        messages: state.messages.slice(-40),
        deletedAnswerRefs: state.deletedAnswerRefs.slice(-8),
        lastResult: state.lastResult || null,
        pendingMessageId: state.pendingMessageId || '',
        pendingJobId: state.pendingJobId || ''
      }));
      upsertCurrentThread();
    } catch (_) {}
  }

  function addMessage(message) {
    var msg = Object.assign({ id: makeId('msg'), role: 'assistant', type: 'text', text: '' }, message || {});
    state.messages.push(msg);
    state.messages = state.messages.slice(-40);
    saveConversation();
    return msg;
  }

  function updateMessage(id, patch) {
    for (var i = 0; i < state.messages.length; i++) {
      if (state.messages[i] && state.messages[i].id === id) {
        state.messages[i] = Object.assign({}, state.messages[i], patch || {});
        saveConversation();
        return state.messages[i];
      }
    }
    return null;
  }

  function findMessage(id) {
    if (id) {
      for (var i = 0; i < state.messages.length; i++) {
        if (state.messages[i] && state.messages[i].id === id) return state.messages[i];
      }
    }
    return null;
  }

  function lastAssistantActionMessage() {
    for (var i = state.messages.length - 1; i >= 0; i--) {
      var msg = state.messages[i];
      if (msg && msg.role === 'assistant' && (msg.type === 'text' || msg.type === 'error' || msg.type === 'confirm')) {
        return msg;
      }
    }
    return null;
  }

  function clearAnswerTimer(messageId) {
    if (!messageId || !answerTimers[messageId]) return;
    if (typeof clearTimeout === 'function') clearTimeout(answerTimers[messageId]);
    delete answerTimers[messageId];
  }

  function startAnswerTimer(messageId, token) {
    clearAnswerTimer(messageId);
    if (!messageId || typeof setTimeout !== 'function') return;
    answerTimers[messageId] = setTimeout(function () {
      var msg = findMessage(messageId);
      if (!msg || msg.request_token !== token || msg.type !== 'thinking') return;
      updateMessage(messageId, {
        role: 'assistant',
        type: 'error',
        text: '回复超时，请重新回答。',
        error_code: 'answer_timeout',
        can_regenerate: true
      });
      state.loading = false;
      state.mode = 'conversation';
      renderMessagePatch(messageId);
    }, THINKING_TIMEOUT_MS);
  }

  function lastConfirmData() {
    var msg = state.messages.slice().reverse().find(function (item) {
      return item && item.type === 'confirm' && item.data;
    });
    return msg && msg.data ? msg.data : (state.understanding || null);
  }

  function buildMemorySummary(messages, brief, lastResult) {
    var parts = [];
    if (brief && (brief.display_summary || brief.compiled_prompt)) {
      parts.push('上一版创作方案：' + (brief.display_summary || brief.compiled_prompt));
    }
    if (brief && brief.style) parts.push('上一版风格：' + brief.style);
    if (brief && brief.aspect_ratio) parts.push('上一版画幅：' + brief.aspect_ratio);
    if (lastResult && (lastResult.image || lastResult.thumb || lastResult.id)) {
      parts.push('上一张生成结果：' + (lastResult.image || lastResult.thumb || lastResult.id));
    }
    var important = (messages || []).filter(function (msg) {
      return msg && msg.role === 'assistant' && msg.important && msg.text;
    }).slice(-4).map(function (msg) { return msg.text; });
    if (important.length) {
      parts.push('重点认可：' + important.join(' / '));
    }
    var deletedRefs = (state.deletedAnswerRefs || []).slice(-3).map(function (item) {
      return item && item.text ? item.text : '';
    }).filter(Boolean);
    if (deletedRefs.length) {
      parts.push('已删除答复仅作参考：' + deletedRefs.join(' / '));
    }
    var recent = (messages || []).slice(-6).map(function (msg) {
      return (msg.role === 'assistant' ? 'EZ' : '用户') + '：' + msg.text;
    }).join(' / ');
    if (recent) parts.push('最近对话：' + recent);
    return parts.join('\n').slice(0, 1600);
  }

  function getConversationContext(currentText) {
    var current = String(currentText || '').trim();
    var textMessages = state.messages.filter(function (msg) {
      return msg && msg.text && (msg.role === 'user' || msg.role === 'assistant');
    }).slice(-16).map(function (msg) {
      return {
        role: msg.role,
        text: msg.text,
        important: !!msg.important,
        feedback: msg.feedback || ''
      };
    });
    if (current && textMessages.length) {
      var last = textMessages[textMessages.length - 1];
      if (last && last.role === 'user' && String(last.text || '').trim() === current) {
        textMessages.pop();
      }
    }
    var brief = lastConfirmData();
    var activeBrief = brief ? {
      intent: brief.intent || '',
      display_summary: brief.display_summary || '',
      compiled_prompt: brief.compiled_prompt || '',
      style: brief.style || '',
      aspect_ratio: brief.aspect_ratio || '',
      workflow: brief.resolved_workflow || brief.workflow || '',
      source_result: brief.source_result || null
    } : null;
    var contextPayload = {
      last_result: state.lastResult || null,
      active_brief: activeBrief,
      memory_summary: buildMemorySummary(textMessages, activeBrief, state.lastResult || null),
      messages: textMessages
    };
    if (state.deletedAnswerRefs && state.deletedAnswerRefs.length) {
      contextPayload.deleted_answer_refs = state.deletedAnswerRefs.slice(-8);
    }
    return contextPayload;
  }

  function apiErrorMessage(payload, res, fallback) {
    var detail = payload && payload.detail;
    var message = payload && (payload.error || payload.message || payload.question);
    if (Array.isArray(detail)) {
      message = detail.map(function (item) {
        return item && item.msg ? item.msg : String(item || '');
      }).filter(Boolean).join('；');
    } else if (detail != null) {
      message = String(detail);
    }
    if ((res && res.status === 401) || /not authenticated/i.test(message || '')) {
      return '请先登录后使用移动端创作。';
    }
    return message || fallback || '请求失败，请稍后重试。';
  }

  function generateErrorMessage(message) {
    var text = String(message || '').trim();
    var lower = text.toLowerCase();
    if (lower.indexOf('no available instances') >= 0 || lower.indexOf('no enabled instances') >= 0) {
      return '没有可用出图实例，请检查设备配置或启动 ComfyUI 实例。';
    }
    if (lower.indexOf('no healthy instances') >= 0) {
      return '出图实例暂不可用，请稍后重试或检查 ComfyUI 状态。';
    }
    return text || '提交生成失败。';
  }

  async function requireLoggedInForMobileAgent() {
    if (!(window.CW && CW.auth)) return true;
    if (window.CW.authReady && typeof window.CW.authReady.then === 'function') {
      try { await window.CW.authReady; } catch (_) {}
    }
    if (typeof CW.auth.getCurrentUser !== 'function') return true;
    if (CW.auth.getCurrentUser()) return true;
    state.error = '请先登录后开始生成。';
    renderActive();
    if (typeof CW.auth.showLogin === 'function') {
      CW.auth.showLogin();
    }
    return false;
  }

  function setRootHtml(html) {
    if (!state.root) return;
    state.root.innerHTML = html;
    state.root.classList.remove('hidden');
    if (document.documentElement && document.documentElement.classList) {
      document.documentElement.classList.add('mobile-agent-boot');
    }
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
    if (state.auraEnterTimer) {
      clearTimeout(state.auraEnterTimer);
      state.auraEnterTimer = null;
    }
    if (state.inputActiveTimer) {
      clearTimeout(state.inputActiveTimer);
      state.inputActiveTimer = null;
    }
    if (state.inputBlurTimer) {
      clearTimeout(state.inputBlurTimer);
      state.inputBlurTimer = null;
    }
    state.root.classList.add('hidden');
    state.root.classList.remove('is-aura-entering', 'is-input-active', 'is-input-breathing', 'is-input-blurring');
    state.root.innerHTML = '';
    if (document.documentElement && document.documentElement.classList) {
      document.documentElement.classList.remove('mobile-agent-boot');
    }
    if (document.body && document.body.removeAttribute) {
      document.body.removeAttribute('data-mobile-agent-active');
    }
  }

  function activateMobileAgent() {
    if (!state.root) return;
    state.active = true;
    renderHome();
    startAuraEnter();
  }

  function startAuraEnter() {
    if (!state.root || !state.root.classList) return;
    if (state.auraEnterTimer) clearTimeout(state.auraEnterTimer);
    state.root.classList.remove('is-aura-entering');
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(function () {
        if (state.root && state.root.classList) state.root.classList.add('is-aura-entering');
      });
    } else {
      state.root.classList.add('is-aura-entering');
    }
    state.auraEnterTimer = setTimeout(function () {
      if (state.root && state.root.classList) state.root.classList.remove('is-aura-entering');
      state.auraEnterTimer = null;
    }, 5000);
  }

  function userInitial(user) {
    var name = user && (user.username || user.name || user.id || user.sub);
    return String(name || '我').trim().slice(0, 1).toUpperCase();
  }

  function renderTopBar() {
    var user = currentUser();
    var avatar = user
      ? '<button class="mobile-agent-avatar" type="button" data-action="toggle-account-menu" aria-label="账户菜单">' + escH(userInitial(user)) + '</button>'
      : '<button class="mobile-agent-login-btn" type="button" data-action="login">登录</button>';
    return '<div class="mobile-agent-topbar">' +
      '<button class="mobile-agent-brand" type="button" data-action="home-main" aria-label="移动端首页">' +
        '<span class="mobile-agent-logo-wrap"><img src="static/icons/ez-site-logo-64.png" alt="EZ ComfyUI logo"></span>' +
        '<span class="mobile-agent-brand-title">Ez ComfyUI</span>' +
      '</button>' +
      avatar +
      renderAccountMenu() +
    '</div>';
  }

  function renderAccountMenu() {
    var user = currentUser();
    return '<div class="mobile-agent-menu' + (state.menuOpen ? ' is-open' : '') + '" role="menu" aria-hidden="' + (state.menuOpen ? 'false' : 'true') + '">' +
      (user ? '<div class="mobile-agent-menu-user"><div><span>' + escH(user.username || user.name || '当前用户') + '</span><small>' + escH(user.role === 'admin' ? '管理员' : '用户') + '</small></div><button class="mobile-agent-menu-logout" type="button" data-action="logout">退出</button></div>' : '') +
      '<button type="button" data-action="new-chat">新建对话</button>' +
      '<button type="button" data-action="history-home">历史对话列表</button>' +
      '<button type="button" data-action="account-settings">账户设置</button>' +
      '<button type="button" data-action="desktop-home">桌面主页面</button>' +
    '</div>';
  }

  function renderThreadList(expanded) {
    var threads = sortedThreads();
    if (!threads.length) return '';
    var visibleThreads = expanded ? threads.slice(0, 30) : threads.slice(0, 1);
    var title = expanded ? '全部历史对话' : '历史对话';
    return '<div class="mobile-agent-history-list' + (expanded ? ' is-expanded' : '') + '" aria-label="' + title + '">' +
      '<div class="mobile-agent-history-head">' +
        (expanded
          ? '<button class="mobile-agent-history-title" type="button" data-action="home">全部历史对话</button>'
          : '<button class="mobile-agent-history-title" type="button" data-action="open-history">历史对话</button>') +
        (expanded ? '<span>' + visibleThreads.length + ' 个话题</span>' : '<span>最近</span>') +
      '</div>' +
      visibleThreads.map(function (thread) {
        return '<div class="mobile-agent-history-row">' +
          '<button class="mobile-agent-history-item" type="button" data-action="open-thread" data-thread-id="' + escH(thread.id) + '">' +
            '<strong>' + escH(thread.title || '未命名对话') + '</strong>' +
            '<span>' + escH(thread.preview || '继续创作') + '</span>' +
          '</button>' +
          '<button class="mobile-agent-thread-delete" type="button" data-action="delete-thread" data-thread-id="' + escH(thread.id) + '" aria-label="删除对话">' + icon('x') + '</button>' +
        '</div>';
      }).join('') +
    '</div>';
  }

  function renderComposer() {
    var imageIcon = icon('image');
    var plusIcon = icon('plus');
    var micIcon = icon('mic');
    var sendIcon = icon('send');
    var imagePreview = state.sourceImageName
      ? '<div class="mobile-agent-compose-attachment" aria-label="' + escH(state.sourceImageName) + ' 图片已添加">' +
          (state.sourceImagePreviewUrl ? '<img src="' + escH(state.sourceImagePreviewUrl) + '" alt="已选择图片预览">' : '<span class="mobile-agent-attachment-icon">' + imageIcon + '</span>') +
          '<button class="mobile-agent-attachment-remove" type="button" data-action="remove-image" aria-label="移除图片">×</button>' +
        '</div>'
      : '';
    var voiceActive = state.voicePending || state.voiceRecording || state.voiceBusy;
    var voiceLabel = state.voiceBusy ? '正在识别' : '正在录音识别';
    var voiceWave = '<span class="mobile-agent-wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>';
    var voiceInner = voiceActive
      ? micIcon + '<span class="mobile-agent-voice-label">' + voiceLabel + '</span>' + voiceWave
      : micIcon;
    return '' +
      '<div class="mobile-agent-compose" role="group" aria-label="对话输入">' +
        '<div class="mobile-agent-input-row' + (voiceActive ? ' is-voice-active' : '') + '">' +
          '<button class="mobile-agent-icon-btn mobile-agent-plus-btn" type="button" data-action="image" title="图片输入" aria-label="图片输入">' + plusIcon + '</button>' +
        '<div class="mobile-agent-compose-body' + (state.sourceImageName ? ' has-attachment' : '') + '">' +
            '<textarea id="mobileAgentText" rows="1" aria-label="对话内容" placeholder="请输入对话内容" autocomplete="off">' + escH(state.text) + '</textarea>' +
          imagePreview +
        '</div>' +
          '<button class="mobile-agent-icon-btn mobile-agent-voice-btn' + (voiceActive ? ' is-recording' : '') + '" type="button" data-action="voice" title="' + (voiceActive ? '停止录音' : '语音输入') + '" aria-label="' + (voiceActive ? '停止录音' : '语音输入') + '"' + (state.voiceBusy ? ' disabled' : '') + '>' + voiceInner + '</button>' +
          '<button class="mobile-agent-send-btn mobile-agent-send-icon-btn" type="button" data-action="understand" aria-label="' + (state.loading ? '理解中' : '发送') + '"' + (state.loading ? ' disabled' : '') + '>' +
            '<span>' + (state.loading ? '理解中' : '发送') + '</span>' + sendIcon +
          '</button>' +
        '</div>' +
      '</div>';
  }

  function syncTextAreaHeight(textarea) {
    if (!textarea || !textarea.style) return;
    textarea.style.height = 'auto';
    var measured = parseInt(textarea.scrollHeight || TEXTAREA_MIN_HEIGHT, 10);
    var next = Math.max(TEXTAREA_MIN_HEIGHT, Math.min(TEXTAREA_MAX_HEIGHT, measured || TEXTAREA_MIN_HEIGHT));
    textarea.style.height = next + 'px';
    textarea.style.overflowY = next >= TEXTAREA_MAX_HEIGHT ? 'auto' : 'hidden';
  }

  function syncComposerHeight() {
    if (!state.root || !state.root.querySelector) return;
    syncTextAreaHeight(state.root.querySelector('#mobileAgentText'));
    syncConversationChromeMetrics();
  }

  function renderHome() {
    var voiceActive = state.voicePending || state.voiceRecording || state.voiceBusy;
    var voiceText = voiceActive ? '' : state.voiceStatus;
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="home">' +
        renderTopBar() +
        '<input id="mobileAgentImageFile" class="mobile-agent-file" type="file" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif">' +
        '<div class="mobile-agent-hero">' +
          '<div class="mobile-agent-copy">' +
            '<h1>智能创作</h1>' +
            '<p>说出想法，EZ 会先整理成可确认的创作方案。</p>' +
          '</div>' +
        '</div>' +
        renderThreadList(false) +
        renderComposer() +
        (voiceText ? '<div class="mobile-agent-voice-status" role="status">' + escH(voiceText) + '</div>' : '') +
        (state.error ? '<div class="mobile-agent-error" role="alert">' + escH(state.error) + '</div>' : '') +
      '</section>'
    );
    syncComposerHeight();
  }

  function renderHistoryView() {
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="history">' +
        renderTopBar() +
        '<div class="mobile-agent-history-page">' +
          '<button class="mobile-agent-back-btn" type="button" data-action="home" aria-label="返回首页">' + icon('chevron-left') + '<span>返回</span></button>' +
          renderThreadList(true) +
        '</div>' +
      '</section>'
    );
  }

  function renderActive() {
    if (state.mode === 'conversation' || state.mode === 'confirm' || state.mode === 'generating') {
      renderConversation();
    } else if (state.mode === 'history') {
      renderHistoryView();
    } else {
      renderHome();
    }
  }

  function mediaSrc(item) {
    if (!item) return '';
    if (item.thumb) return JOB_API + '/api/thumbs/' + item.thumb;
    if (item.image) return JOB_API + '/api/images/' + item.image;
    if (item.filename) return JOB_API + '/api/images/' + item.filename;
    return item.url || '';
  }

  function fullMediaSrc(item) {
    if (!item) return '';
    if (item.image) return JOB_API + '/api/images/' + item.image;
    if (item.filename) return JOB_API + '/api/images/' + item.filename;
    if (item.url) return item.url;
    if (item.thumb) return JOB_API + '/api/thumbs/' + item.thumb;
    return '';
  }

  function resultPromptText(msg) {
    return String((msg && (msg.prompt || msg.prompt_preview || msg.task_description)) || '').trim();
  }

  function attachmentSrc(item) {
    if (!item) return '';
    var url = item.preview_url || item.url || '';
    if (!url) return '';
    if (API && url.indexOf('/api/mobile-agent/') === 0) return API + url;
    if (/^(blob:|data:|https?:\/\/|\/)/.test(url)) return url;
    return API + url;
  }

  function renderMessageAttachments(attachments) {
    if (!Array.isArray(attachments) || !attachments.length) return '';
    return '<div class="mobile-agent-message-attachments">' + attachments.map(function (item) {
      var src = attachmentSrc(item);
      var name = item && item.name ? item.name : '图片';
      return '<figure class="mobile-agent-message-attachment">' +
        (src ? '<img src="' + escH(src) + '" alt="' + escH(name) + '">' : '<span>' + icon('image') + '</span>') +
        '<figcaption>' + escH(name) + '</figcaption>' +
      '</figure>';
    }).join('') + '</div>';
  }

  function renderAnswerActions(msg) {
    if (!msg || msg.role !== 'assistant') return '';
    if (msg.type !== 'text' && msg.type !== 'error') return '';
    var liked = msg.feedback === 'liked' || msg.important;
    return '<div class="mobile-agent-answer-actions">' +
      '<button class="mobile-agent-answer-action' + (liked ? ' is-liked' : '') + '" type="button" data-action="like-answer" data-message-id="' + escH(msg.id || '') + '" aria-label="点赞" aria-pressed="' + (liked ? 'true' : 'false') + '">' + icon('thumbs-up') + '</button>' +
      '<button class="mobile-agent-answer-action" type="button" data-action="regenerate-answer" data-message-id="' + escH(msg.id || '') + '" aria-label="重新回答">' + icon('rotate-cw') + '</button>' +
      '<button class="mobile-agent-answer-action" type="button" data-action="delete-answer" data-message-id="' + escH(msg.id || '') + '" aria-label="删除">' + icon('trash-2') + '</button>' +
    '</div>';
  }

  function firstArrayValue(value) {
    return Array.isArray(value) ? (value.find(function (item) { return !!item; }) || '') : '';
  }

  function firstBatchValue(job, key) {
    var items = job && Array.isArray(job.batch_items) ? job.batch_items : [];
    for (var i = 0; i < items.length; i++) {
      if (items[i] && items[i][key]) return items[i][key];
    }
    return '';
  }

  function resultFromJob(job) {
    job = job || {};
    var image = job.image || job.pending_image || firstArrayValue(job.images) || firstBatchValue(job, 'filename');
    var thumb = job.thumb || job.pending_thumb || firstArrayValue(job.thumbs) || firstBatchValue(job, 'thumb');
    var mediaType = job.media_type || job.pending_media_type || firstArrayValue(job.media_types) || firstBatchValue(job, 'media_type') || 'image';
    return {
      id: job.id || state.pendingJobId,
      image: image || '',
      thumb: thumb || '',
      media_type: mediaType || 'image',
      workflow: job.workflow || '',
      prompt: job.prompt_preview || job.prompt || ''
    };
  }

  function jobProgressValue(progress) {
    var pct = progress && typeof progress.pct !== 'undefined' ? parseInt(progress.pct, 10) : NaN;
    if (isNaN(pct)) return 0;
    return Math.max(0, Math.min(100, pct));
  }

  function renderTaskCard(msg) {
    var pct = jobProgressValue(msg.progress);
    var jobId = msg.job_id || msg.jobId || state.pendingJobId || '';
    var shortId = jobId ? String(jobId).slice(-6) : '';
    var status = msg.status || 'queued';
    var isError = status === 'error' || msg.type === 'error';
    var text = msg.text || jobStatusLabel(status) || '已加入生成队列';
    var data = msg.data || {};
    var description = msg.task_description || msg.prompt_preview || data.display_summary || data.compiled_prompt || '';
    var workflowLabel = msg.workflow_title || msg.workflow_label || data.workflow_title || data.workflow_label || data.resolved_workflow || msg.workflow || '';
    return '<article class="mobile-agent-message mobile-agent-message-assistant" data-message-id="' + escH(msg.id || '') + '">' +
      '<div class="mobile-agent-task-card' + (isError ? ' is-error' : '') + '" data-mobile-job-id="' + escH(jobId) + '">' +
        '<div class="mobile-agent-task-preview" aria-hidden="true">' +
          '<span></span><span></span><span></span>' +
        '</div>' +
        '<div class="mobile-agent-task-meta">' +
          '<div class="mobile-agent-section-label">当前任务' + (shortId ? ' #' + escH(shortId) : '') + '</div>' +
          (description ? '<div class="mobile-agent-task-description">' + escH(description) + '</div>' : '') +
          (workflowLabel ? '<div class="mobile-agent-task-workflow">工作流：' + escH(workflowLabel) + '</div>' : '') +
          '<div class="mobile-agent-task-title">' + escH(text) + '</div>' +
          '<div class="mobile-agent-task-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '">' +
            '<i style="width:' + pct + '%"></i>' +
          '</div>' +
          (isError || msg.can_retry ? '<div class="mobile-agent-task-actions"><button class="mobile-agent-task-action mobile-agent-task-retry" type="button" data-action="retry-generate" data-message-id="' + escH(msg.id || '') + '" aria-label="重试生成">' + icon('rotate-cw') + '<span>重试</span></button></div>' : '') +
        '</div>' +
      '</div>' +
    '</article>';
  }

  function renderConfirmCard(data, messageId) {
    data = data || {};
    var options = data.options || {};
    var selectedStyle = data.style || data.selected_style || '';
    var selectedRatio = data.aspect_ratio || data.selected_ratio || '';
    var styles = options.allowed_styles || data.allowed_styles || data.styles || data.style_chips || (selectedStyle ? [selectedStyle] : []);
    var ratios = options.allowed_ratios || data.allowed_ratios || data.aspect_ratios || data.ratios || (selectedRatio ? [selectedRatio] : []);
    var showStyleOptions = shouldShowOption(data, 'style', selectedStyle, styles);
    var showRatioOptions = shouldShowOption(data, 'aspect_ratio', selectedRatio, ratios);
    var workflowChoices = Array.isArray(data.workflow_choices) ? data.workflow_choices : (Array.isArray(options.workflow_choices) ? options.workflow_choices : []);
    var selectedWorkflow = data.resolved_workflow || '';
    var summary = data.display_summary || data.compiled_prompt || state.text || '请确认创作方案';
    var workflowReady = !!data.resolved_workflow && !data.error_code;
    var warning = !workflowReady ? (data.question || '当前默认工作流暂不可用，请返回修改或联系管理员配置。') : '';
    var workflowLabel = data.workflow_title || data.workflow_label || data.resolved_workflow || '';
    var workflowMenuOpen = !!data.workflow_menu_open;
    var title = data.intent === 'image_to_image' ? '准备修改这张图' : '准备生成这张图';
    var generationPending = !!state.pendingJobId || !!state.pendingMessageId;
    return '' +
      '<div class="mobile-agent-confirm-card">' +
        '<div class="mobile-agent-section-label">EZ 已整理好方案</div>' +
        '<h2>' + escH(title) + '</h2>' +
        '<div class="mobile-agent-summary">' + escH(summary) + '</div>' +
        (workflowReady ? '<div class="mobile-agent-workflow-status">已匹配工作流：<span>' + escH(workflowLabel) + '</span>' +
          (workflowChoices.length > 1 ? '<button class="mobile-agent-workflow-switch" type="button" data-action="toggle-workflow-menu" data-message-id="' + escH(messageId || '') + '" aria-label="切换工作流" aria-expanded="' + (workflowMenuOpen ? 'true' : 'false') + '">' + icon('switch-horizontal') + '</button>' : '') +
        '</div>' : '') +
        (warning ? '<div class="mobile-agent-error" role="alert">' + escH(warning) + '</div>' : '') +
        (workflowChoices.length > 1 && workflowMenuOpen ? '<div class="mobile-agent-workflow-menu" role="menu" aria-label="可选工作流">' +
          '<div class="mobile-agent-chip-group" aria-label="工作流">' + workflowChoices.map(function (item) {
            var workflow = item && item.workflow ? String(item.workflow) : '';
            if (!workflow) return '';
            var active = selectedWorkflow && workflow === String(selectedWorkflow);
            return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '" role="menuitemradio" aria-checked="' + (active ? 'true' : 'false') + '" data-action="select-option" data-option="workflow" data-value="' + escH(workflow) + '" data-message-id="' + escH(messageId || '') + '">' + escH(item.title || workflow) + '</button>';
          }).join('') + '</div>' +
        '</div>' : '') +
        (showStyleOptions ? '<div class="mobile-agent-option-block">' +
          '<span>风格</span>' +
          '<div class="mobile-agent-chip-group" aria-label="风格">' + styles.map(function (item) {
            var active = selectedStyle && String(item) === String(selectedStyle);
            return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '" data-action="select-option" data-option="style" data-value="' + escH(item) + '" data-message-id="' + escH(messageId || '') + '">' + escH(item) + '</button>';
          }).join('') + '</div>' +
        '</div>' : '') +
        (showRatioOptions ? '<div class="mobile-agent-option-block">' +
          '<span>画幅</span>' +
          '<div class="mobile-agent-chip-group" aria-label="画幅">' + ratios.map(function (item) {
            var active = selectedRatio && String(item) === String(selectedRatio);
            return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '" data-action="select-option" data-option="aspect_ratio" data-value="' + escH(item) + '" data-message-id="' + escH(messageId || '') + '">' + escH(item) + '</button>';
          }).join('') + '</div>' +
        '</div>' : '') +
        '<button class="mobile-agent-send-btn" type="button" data-action="generate" data-message-id="' + escH(messageId || '') + '"' + (workflowReady && !generationPending ? '' : ' disabled') + '>' + icon('sparkles') + '<span>' + (generationPending ? '生成中' : '生成') + '</span></button>' +
      '</div>';
  }

  function shouldShowOption(data, option, selected, values) {
    var requirements = (data && data.option_requirements) || ((data && data.options && data.options.option_requirements) || null);
    if (requirements && Object.prototype.hasOwnProperty.call(requirements, option)) {
      return !!requirements[option] && Array.isArray(values) && values.length > 1;
    }
    if (option === 'style') return !selected && Array.isArray(values) && values.length > 1;
    return Array.isArray(values) && values.length > 1;
  }

  function findResultMessage(messageId) {
    if (messageId) {
      return state.messages.find(function (item) { return item && item.id === messageId && item.type === 'result'; }) || null;
    }
    var results = state.messages.filter(function (item) { return item && item.type === 'result'; });
    return results.length ? results[results.length - 1] : null;
  }

  function renderResultCard(msg) {
    var src = mediaSrc(msg);
    var fullSrc = fullMediaSrc(msg) || src;
    var prompt = resultPromptText(msg);
    var promptOpen = !!msg.prompt_open;
    return '<div class="mobile-agent-result-card">' +
      (src ? '<button class="mobile-agent-result-image-btn" type="button" data-action="open-result-preview" data-message-id="' + escH(msg.id || '') + '" aria-label="放大查看生成结果"><img src="' + escH(src) + '" alt="生成结果"></button>' : '') +
      '<div class="mobile-agent-result-status">生成完成</div>' +
      '<div class="mobile-agent-result-actions">' +
        (fullSrc ? '<a class="mobile-agent-result-action" href="' + escH(fullSrc) + '" download>' + icon('download') + '<span>下载</span></a>' : '') +
        (prompt ? '<button class="mobile-agent-result-action" type="button" data-action="toggle-result-prompt" data-message-id="' + escH(msg.id || '') + '">' + icon('file-text') + '<span>' + (promptOpen ? '收起提示词' : '提示词') + '</span></button>' : '') +
      '</div>' +
      (prompt && promptOpen ? '<pre class="mobile-agent-result-prompt"><code>' + escH(prompt) + '</code></pre>' : '') +
    '</div>';
  }

  function renderResultPreviewOverlay() {
    var preview = state.previewResult || null;
    if (!preview || !preview.src) return '';
    return '<div class="mobile-agent-preview-overlay" role="dialog" aria-modal="true" aria-label="生成结果预览">' +
      '<button class="mobile-agent-preview-close" type="button" data-action="close-result-preview" aria-label="关闭预览">' + icon('x') + '</button>' +
      '<img src="' + escH(preview.src) + '" alt="生成结果预览">' +
      (preview.prompt ? '<pre class="mobile-agent-preview-prompt"><code>' + escH(preview.prompt) + '</code></pre>' : '') +
    '</div>';
  }

  function renderMessage(msg) {
    if (!msg) return '';
    var mid = msg.id ? ' data-message-id="' + escH(msg.id) + '"' : '';
    if (msg.role === 'user') {
      return '<article class="mobile-agent-message mobile-agent-message-user"' + mid + '><div>' +
        renderMessageAttachments(msg.attachments) +
        (msg.text ? '<div class="mobile-agent-message-text">' + renderPlainText(msg.text || '') + '</div>' : '') +
      '</div></article>';
    }
    if (msg.type === 'thinking') {
      return '<article class="mobile-agent-message mobile-agent-message-assistant"' + mid + '>' +
        '<div class="mobile-agent-thinking" role="status" aria-label="模型正在思考">' +
          '<span class="mobile-agent-thinking-dot"></span>' +
          '<span class="mobile-agent-thinking-dot"></span>' +
          '<span class="mobile-agent-thinking-dot"></span>' +
        '</div>' +
      '</article>';
    }
    if (msg.type === 'confirm') {
      return '<article class="mobile-agent-message mobile-agent-message-assistant"' + mid + '>' + renderConfirmCard(msg.data || {}, msg.id) + '</article>';
    }
    if (msg.type === 'result') {
      return '<article class="mobile-agent-message mobile-agent-message-assistant"' + mid + '>' +
        renderResultCard(msg) +
      '</article>';
    }
    if (msg.type === 'task') {
      return renderTaskCard(msg);
    }
    if (msg.type === 'status') {
      return '<article class="mobile-agent-message mobile-agent-message-assistant"' + mid + '><div class="mobile-agent-status-card">' + escH(msg.text || '正在生成') + '</div></article>';
    }
    return '<article class="mobile-agent-message mobile-agent-message-assistant"' + mid + '>' +
      '<div class="mobile-agent-assistant-stack">' +
        '<div class="mobile-agent-markdown">' + renderMarkdown(msg.text || '') + '</div>' +
        renderAnswerActions(msg) +
      '</div>' +
    '</article>';
  }

  function patchRenderedMessage(messageId) {
    if (!messageId || !state.root || !state.root.querySelector) return false;
    var chat = state.root.querySelector('.mobile-agent-chat');
    if (!chat || !chat.querySelector) return false;
    var safeId = String(messageId).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    var target = chat.querySelector('[data-message-id="' + safeId + '"]');
    var msg = state.messages.find(function (item) { return item && item.id === messageId; });
    if (!target || !msg) return false;
    target.outerHTML = renderMessage(msg);
    scrollChatToLatest();
    return true;
  }

  function patchTaskMessageDom(messageId, msg) {
    if (!messageId || !msg || msg.type !== 'task' || !state.root || !state.root.querySelector) return false;
    var safeId = String(messageId).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    var target = state.root.querySelector('[data-message-id="' + safeId + '"]');
    var card = target && target.querySelector ? target.querySelector('.mobile-agent-task-card') : null;
    if (!target || !card) return false;
    var pct = jobProgressValue(msg.progress);
    var jobId = msg.job_id || msg.jobId || state.pendingJobId || '';
    var shortId = jobId ? String(jobId).slice(-6) : '';
    var isError = msg.status === 'error' || msg.type === 'error';
    if (isError || msg.can_retry) return false;
    var title = card.querySelector('.mobile-agent-task-title');
    var label = card.querySelector('.mobile-agent-section-label');
    var bar = card.querySelector('.mobile-agent-task-bar');
    var fill = bar && bar.querySelector ? bar.querySelector('i') : null;
    card.classList.toggle('is-error', !!isError);
    card.setAttribute('data-mobile-job-id', jobId);
    if (label) label.textContent = '当前任务' + (shortId ? ' #' + shortId : '');
    if (title) title.textContent = msg.text || jobStatusLabel(msg.status) || '正在生成';
    if (bar) bar.setAttribute('aria-valuenow', String(pct));
    if (fill) fill.style.width = pct + '%';
    scrollChatToLatest();
    return true;
  }

  function patchAssistantTextDom(messageId, msg) {
    if (!messageId || !msg || (msg.type !== 'text' && msg.type !== 'error') || !state.root || !state.root.querySelector) return false;
    var safeId = String(messageId).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    var target = state.root.querySelector('[data-message-id="' + safeId + '"]');
    var body = target && target.querySelector ? target.querySelector('.mobile-agent-markdown') : null;
    if (!target || !body) return false;
    body.innerHTML = renderMarkdown(msg.text || '');
    scrollChatToLatest();
    return true;
  }

  function renderMessagePatch(messageId) {
    if (state.active && (state.mode === 'conversation' || state.mode === 'generating')) {
      var msg = findMessage(messageId);
      if (patchTaskMessageDom(messageId, msg) || patchAssistantTextDom(messageId, msg) || patchRenderedMessage(messageId)) return;
    }
    renderActive();
  }

  function syncConversationChromeMetrics() {
    if (!state.root || !state.root.querySelector || !state.root.style) return;
    var footer = state.root.querySelector('.mobile-agent-conversation-footer');
    var header = state.root.querySelector('.mobile-agent-panel[data-view="conversation"] .mobile-agent-topbar');
    var footerHeight = footer && typeof footer.getBoundingClientRect === 'function'
      ? footer.getBoundingClientRect().height
      : 156;
    var headerHeight = header && typeof header.getBoundingClientRect === 'function'
      ? header.getBoundingClientRect().height
      : 92;
    state.root.style.setProperty('--mobile-footer-space', Math.ceil(footerHeight + 26) + 'px');
    state.root.style.setProperty('--mobile-header-space', Math.ceil(headerHeight + 28) + 'px');
  }

  function bindConversationChromeMetrics() {
    if (state.chromeResizeObserver && typeof state.chromeResizeObserver.disconnect === 'function') {
      state.chromeResizeObserver.disconnect();
      state.chromeResizeObserver = null;
    }
    syncConversationChromeMetrics();
    if (typeof ResizeObserver !== 'function' || !state.root || !state.root.querySelector) return;
    var footer = state.root.querySelector('.mobile-agent-conversation-footer');
    var header = state.root.querySelector('.mobile-agent-panel[data-view="conversation"] .mobile-agent-topbar');
    state.chromeResizeObserver = new ResizeObserver(syncConversationChromeMetrics);
    if (footer) state.chromeResizeObserver.observe(footer);
    if (header) state.chromeResizeObserver.observe(header);
  }

  function renderConversation() {
    var voiceActive = state.voicePending || state.voiceRecording || state.voiceBusy;
    var voiceText = voiceActive ? '' : state.voiceStatus;
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="conversation">' +
        renderTopBar() +
        '<input id="mobileAgentImageFile" class="mobile-agent-file" type="file" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif">' +
        '<div class="mobile-agent-chat" aria-live="polite">' + state.messages.map(renderMessage).join('') + '</div>' +
        '<div class="mobile-agent-conversation-footer">' +
          renderComposer() +
          (voiceText ? '<div class="mobile-agent-voice-status" role="status">' + escH(voiceText) + '</div>' : '') +
          (state.error ? '<div class="mobile-agent-error" role="alert">' + escH(state.error) + '</div>' : '') +
        '</div>' +
        renderResultPreviewOverlay() +
      '</section>'
    );
    bindConversationChromeMetrics();
    syncComposerHeight();
    scrollChatToLatest();
  }

  function revealAssistantText(messageId, fullText) {
    fullText = String(fullText || '');
    if (!messageId || !fullText) {
      updateMessage(messageId, { type: 'text', text: fullText });
      renderMessagePatch(messageId);
      return Promise.resolve();
    }
    if (typeof setTimeout !== 'function') {
      updateMessage(messageId, { type: 'text', text: fullText });
      renderMessagePatch(messageId);
      return Promise.resolve();
    }
    var index = 0;
    var chunk = fullText.length > 80 ? 3 : 2;
    return new Promise(function (resolve) {
      var tick = function () {
        index = Math.min(fullText.length, index + chunk);
        updateMessage(messageId, { type: 'text', text: fullText.slice(0, index) });
        var msg = findMessage(messageId);
        if (!patchAssistantTextDom(messageId, msg)) renderMessagePatch(messageId);
        if (index >= fullText.length) {
          resolve();
          return;
        }
        setTimeout(tick, 18);
      };
      tick();
    });
  }

  function scrollChatToLatest() {
    if (!window.setTimeout || state.scrollPending) return;
    state.scrollPending = true;
    var schedule = window.requestAnimationFrame || window.setTimeout;
    schedule(function () {
      state.scrollPending = false;
      var chat = state.root && state.root.querySelector ? state.root.querySelector('.mobile-agent-chat') : null;
      if (chat) chat.scrollTop = chat.scrollHeight;
    }, 0);
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
    var workflowReady = !!data.resolved_workflow && !data.error_code;
    var warning = state.error || (!workflowReady ? (data.question || '当前默认工作流暂不可用，请返回修改或联系管理员配置。') : '');
    var workflowLabel = data.workflow_title || data.workflow_label || data.resolved_workflow || '';
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="confirm">' +
        '<button class="mobile-agent-back" type="button" data-action="home">' + icon('chevron-left') + ' 返回</button>' +
        '<div class="mobile-agent-confirm-main">' +
          '<div class="mobile-agent-section-label">EZ 已整理好方案</div>' +
          '<h1>准备生成这张图</h1>' +
          '<div class="mobile-agent-summary">' + escH(summary) + '</div>' +
          (workflowReady ? '<div class="mobile-agent-workflow-status">已匹配工作流：' + escH(workflowLabel) + '</div>' : '') +
          (warning ? '<div class="mobile-agent-error" role="alert">' + escH(warning) + '</div>' : '') +
        '</div>' +
        '<div class="mobile-agent-option-block">' +
          '<span>风格</span>' +
          '<div class="mobile-agent-chip-group" aria-label="风格">' + styles.map(function (item) {
            var active = selectedStyle && String(item) === String(selectedStyle);
            return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '" data-action="select-option" data-option="style" data-value="' + escH(item) + '">' + escH(item) + '</button>';
          }).join('') + '</div>' +
        '</div>' +
        '<div class="mobile-agent-option-block">' +
          '<span>画幅</span>' +
          '<div class="mobile-agent-chip-group" aria-label="画幅">' + ratios.map(function (item) {
            var active = selectedRatio && String(item) === String(selectedRatio);
            return '<button type="button" class="mobile-agent-chip' + (active ? ' is-selected' : '') + '" data-action="select-option" data-option="aspect_ratio" data-value="' + escH(item) + '">' + escH(item) + '</button>';
          }).join('') + '</div>' +
        '</div>' +
        '<div class="mobile-agent-actions">' +
          '<button class="mobile-agent-secondary-btn" type="button" data-action="home">返回修改</button>' +
          '<button class="mobile-agent-send-btn" type="button" data-action="generate"' + (workflowReady ? '' : ' disabled') + '>' + icon('sparkles') + '<span>生成</span></button>' +
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

  async function uploadSourceImageAttachment() {
    if (!state.sourceImageFile) return [];
    if (typeof window.FormData !== 'function') {
      throw new Error('当前浏览器不支持图片附件提交。');
    }
    var fd = new FormData();
    fd.append('file', state.sourceImageFile, state.sourceImageName || state.sourceImageFile.name || 'image.png');
    var res = await authFetch(API + '/api/mobile-agent/upload-attachment', {
      method: 'POST',
      body: fd
    });
    var payload = await res.json();
    if (!res.ok || payload.ok === false) {
      throw new Error(apiErrorMessage(payload, res, '图片上传失败'));
    }
    var item = payload.data || payload;
    return [{
      id: item.id || '',
      name: item.name || state.sourceImageName || '图片',
      mime_type: item.mime_type || item.type || '',
      media_type: item.media_type || 'image',
      size: item.size || state.sourceImageFile.size || 0,
      url: item.url || '',
      preview_url: item.url || state.sourceImagePreviewUrl || ''
    }];
  }

  async function requestAssistantAnswer(messageId, requestText, hasImage, submittedAttachments, contextSnapshot) {
    var token = makeId('req');
    updateMessage(messageId, {
      role: 'assistant',
      type: 'thinking',
      text: '',
      request_text: requestText,
      request_has_image: !!hasImage,
      request_attachments: submittedAttachments || [],
      request_context: contextSnapshot || {},
      request_token: token,
      can_regenerate: true,
      feedback: '',
      important: false
    });
    startAnswerTimer(messageId, token);
    try {
      var res = await authFetch(API + '/api/mobile-agent/understand', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: requestText,
          has_image: !!hasImage,
          has_video: false,
          attachments: (submittedAttachments || []).map(function (item) {
            return Object.assign({}, item, { preview_url: undefined });
          }),
          context: contextSnapshot || {}
        })
      });
      var payload = await res.json();
      var current = findMessage(messageId);
      if (!current || current.request_token !== token || current.error_code === 'answer_timeout') return null;
      clearAnswerTimer(messageId);
      if (!res.ok || payload.ok === false) {
        throw new Error(apiErrorMessage(payload, res, '理解失败'));
      }
      state.understanding = payload.data || payload;
      if (state.understanding.response_type === 'chat') {
        var replyText = state.understanding.assistant_message || state.understanding.question || '你可以继续补充创作想法。';
        updateMessage(messageId, {
          role: 'assistant',
          type: 'text',
          text: '',
          request_token: '',
          can_regenerate: true,
          data: {
            draft_requirement: state.understanding.draft_requirement || {},
            missing_slots: state.understanding.missing_slots || []
          }
        });
        state.mode = 'conversation';
        state.loading = false;
        await revealAssistantText(messageId, replyText);
      } else {
        updateMessage(messageId, {
          role: 'assistant',
          type: 'confirm',
          text: state.understanding.display_summary || state.understanding.compiled_prompt || '已整理好创作方案',
          request_token: '',
          data: state.understanding
        });
        state.mode = 'confirm';
      }
      return state.understanding;
    } catch (err) {
      clearAnswerTimer(messageId);
      var currentAfterError = findMessage(messageId);
      if (!currentAfterError || currentAfterError.request_token !== token) return null;
      throw err;
    }
  }

  async function submitUnderstand() {
    if (state.loading) return;
    state.error = '';
    var hasSourceImage = !!state.sourceImageFile;
    var requestText = state.text.trim() || (hasSourceImage ? '请分析这张图片' : '');
    if (!requestText && !hasSourceImage) {
      state.error = '先输入一点创作想法。';
      renderHome();
      return;
    }
    prepareHomeSubmitThread();
    state.loading = true;
    renderHome();
    try {
      var submittedAttachments = hasSourceImage ? await uploadSourceImageAttachment() : [];
      var contextSnapshot = getConversationContext(requestText);
      if (submittedAttachments.length) {
        contextSnapshot.attachments = submittedAttachments.map(function (item) {
          return Object.assign({}, item, { preview_url: undefined });
        });
      }
      state.mode = 'conversation';
      addMessage({ role: 'user', type: 'text', text: requestText, attachments: submittedAttachments });
      var pendingReply = addMessage({
        role: 'assistant',
        type: 'thinking',
        text: '',
        request_text: requestText,
        request_has_image: hasSourceImage || submittedAttachments.length > 0,
        request_attachments: submittedAttachments,
        request_context: contextSnapshot
      });
      state.text = '';
      clearImagePreview();
      renderActive();
      await requestAssistantAnswer(
        pendingReply.id,
        requestText,
        hasSourceImage || submittedAttachments.length > 0,
        submittedAttachments,
        contextSnapshot
      );
      saveConversation();
      state.loading = false;
      renderActive();
    } catch (err) {
      state.error = err && err.message ? err.message : '理解失败，请稍后重试。';
      if (typeof pendingReply !== 'undefined' && pendingReply && pendingReply.id) {
        updateMessage(pendingReply.id, { role: 'assistant', type: 'error', text: state.error });
      } else {
        addMessage({ role: 'assistant', type: 'error', text: state.error });
      }
      state.loading = false;
      if (state.messages.length) state.mode = 'conversation';
      renderActive();
    } finally {
      state.loading = false;
    }
  }

  async function submitGenerate(messageId) {
    if (state.pendingJobId || state.pendingMessageId) {
      toast('已有任务在生成队列中', 'info');
      return;
    }
    var confirmMessage = messageId
      ? state.messages.find(function (msg) { return msg && msg.id === messageId; })
      : null;
    if (!confirmMessage) {
      confirmMessage = state.messages.slice().reverse().find(function (msg) {
        return msg && (msg.type === 'confirm' || (msg.type === 'task' && msg.status === 'error' && msg.data));
      });
    }
    var data = (confirmMessage && confirmMessage.data) || state.understanding || {};
    state.error = '';
    if (!data.resolved_workflow || data.error_code) {
      state.error = data.question || '默认工作流暂不可用。';
      renderHome();
      return;
    }
    if (!(await requireLoggedInForMobileAgent())) return;

    var retryJobId = confirmMessage && confirmMessage.type === 'task' && confirmMessage.status === 'error'
      ? (confirmMessage.job_id || confirmMessage.jobId || '')
      : '';
    if (retryJobId) {
      await retryBackendJob(confirmMessage, retryJobId);
      return;
    }

    var generationSummary = data.display_summary || data.compiled_prompt || '';
    var generationPrompt = data.compiled_prompt || data.display_summary || '';
    state.mode = 'generating';
    var taskPatch = {
      role: 'assistant',
      type: 'task',
      text: '正在提交到生成队列',
      task_description: generationSummary,
      prompt_preview: generationPrompt,
      workflow_title: data.workflow_title || data.workflow_label || data.resolved_workflow || '',
      data: data,
      status: 'submitting',
      can_retry: false,
      progress: { pct: 0 }
    };
    var pending = confirmMessage ? updateMessage(confirmMessage.id, taskPatch) : addMessage(taskPatch);
    state.pendingMessageId = pending.id;
    renderActive();
    try {
      var res = await authFetch(JOB_API + '/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow: data.resolved_workflow,
          fields: data.field_values || {},
          creative_brief: data.creative_brief || null,
          width: data.width || 0,
          height: data.height || 0
        })
      });
      var payload = await res.json();
      if (!res.ok || payload.detail) {
        throw new Error(generateErrorMessage(payload.detail || payload.error || payload.message));
      }
      state.jobId = payload.job_id;
      state.pendingJobId = payload.job_id || '';
      updateMessage(state.pendingMessageId, {
        role: 'assistant',
        type: 'task',
        text: '已加入生成队列',
        task_description: generationSummary,
        prompt_preview: generationPrompt,
        workflow_title: data.workflow_title || data.workflow_label || data.resolved_workflow || '',
        data: data,
        status: 'queued',
        can_retry: false,
        job_id: payload.job_id || '',
        progress: { pct: 0 }
      });
      syncSharedJobState({
        id: payload.job_id || '',
        status: 'queued',
        message: '排队中...',
        workflow: data.resolved_workflow,
        prompt_preview: generationPrompt,
        width: data.width || 0,
        height: data.height || 0,
        progress: { pct: 0 }
      });
      saveConversation();
      toast('已开始生成', 'success');
      renderMessagePatch(state.pendingMessageId);
    } catch (err) {
      var errorText = err && err.message ? err.message : '提交生成失败。';
      var failedMessageId = state.pendingMessageId;
      state.pendingJobId = '';
      state.pendingMessageId = '';
      state.error = '';
      updateMessage(failedMessageId, {
        role: 'assistant',
        type: 'task',
        text: errorText,
        task_description: generationSummary,
        prompt_preview: generationPrompt,
        workflow_title: data.workflow_title || data.workflow_label || data.resolved_workflow || '',
        data: data,
        status: 'error',
        can_retry: true,
        progress: { pct: 0 }
      });
      saveConversation();
      state.mode = 'conversation';
      renderActive();
    }
  }

  async function retryBackendJob(message, jobId) {
    if (!message || !jobId) return;
    var data = message.data || state.understanding || {};
    state.mode = 'generating';
    state.pendingMessageId = message.id;
    updateMessage(message.id, {
      role: 'assistant',
      type: 'task',
      text: '正在恢复实例并重新提交',
      task_description: message.task_description || data.display_summary || data.compiled_prompt || '',
      prompt_preview: message.prompt_preview || message.prompt || data.compiled_prompt || data.display_summary || '',
      workflow_title: message.workflow_title || data.workflow_title || data.workflow_label || data.resolved_workflow || '',
      data: data,
      status: 'submitting',
      can_retry: false,
      job_id: jobId,
      progress: { pct: 0 }
    });
    renderMessagePatch(message.id);
    try {
      var res = await authFetch(JOB_API + '/api/jobs/' + encodeURIComponent(jobId) + '/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      var payload = await res.json();
      if (!res.ok || payload.detail) {
        throw new Error(generateErrorMessage(payload.detail || payload.error || payload.message));
      }
      state.pendingJobId = payload.job_id || '';
      updateMessage(message.id, {
        role: 'assistant',
        type: 'task',
        text: '已重新加入生成队列',
        task_description: message.task_description || data.display_summary || data.compiled_prompt || '',
        prompt_preview: message.prompt_preview || message.prompt || data.compiled_prompt || data.display_summary || '',
        workflow_title: message.workflow_title || data.workflow_title || data.workflow_label || data.resolved_workflow || '',
        data: data,
        status: 'queued',
        can_retry: false,
        job_id: payload.job_id || jobId,
        progress: { pct: 0 }
      });
      saveConversation();
      renderMessagePatch(message.id);
      refreshPendingJobState();
    } catch (err) {
      var errorText = err && err.message ? err.message : '重试提交失败。';
      state.pendingJobId = '';
      state.pendingMessageId = '';
      updateMessage(message.id, {
        role: 'assistant',
        type: 'task',
        text: errorText,
        task_description: message.task_description || data.display_summary || data.compiled_prompt || '',
        prompt_preview: message.prompt_preview || message.prompt || data.compiled_prompt || data.display_summary || '',
        workflow_title: message.workflow_title || data.workflow_title || data.workflow_label || data.resolved_workflow || '',
        data: data,
        status: 'error',
        can_retry: true,
        job_id: jobId,
        progress: { pct: 0 }
      });
      saveConversation();
      state.mode = 'conversation';
      renderMessagePatch(message.id);
    }
  }

  function resolveAnswerMessage(messageId) {
    return findMessage(messageId) || lastAssistantActionMessage();
  }

  function likeAnswer(messageId) {
    var msg = resolveAnswerMessage(messageId);
    if (!msg) return;
    var liked = msg.feedback === 'liked' || msg.important;
    updateMessage(msg.id, {
      feedback: liked ? '' : 'liked',
      important: liked ? false : true
    });
    saveConversation();
    if (!patchRenderedMessage(msg.id)) renderMessagePatch(msg.id);
  }

  async function regenerateAnswer(messageId) {
    if (state.loading) return;
    var msg = resolveAnswerMessage(messageId);
    if (!msg) return;
    var requestText = msg.request_text || '';
    if (!requestText) {
      var before = state.messages.slice(0, state.messages.indexOf(msg)).reverse().find(function (item) {
        return item && item.role === 'user' && item.text;
      });
      requestText = before ? before.text : '';
    }
    if (!requestText) return;
    var attachments = Array.isArray(msg.request_attachments) ? msg.request_attachments : [];
    var contextSnapshot = msg.request_context || getConversationContext(requestText);
    state.loading = true;
    state.mode = 'conversation';
    updateMessage(msg.id, {
      role: 'assistant',
      type: 'thinking',
      text: '',
      error_code: '',
      feedback: '',
      important: false,
      request_text: requestText,
      request_has_image: !!msg.request_has_image,
      request_attachments: attachments,
      request_context: contextSnapshot
    });
    renderMessagePatch(msg.id);
    try {
      await requestAssistantAnswer(msg.id, requestText, !!msg.request_has_image, attachments, contextSnapshot);
      state.loading = false;
      saveConversation();
      renderMessagePatch(msg.id);
    } catch (err) {
      updateMessage(msg.id, {
        role: 'assistant',
        type: 'error',
        text: err && err.message ? err.message : '重新回答失败，请稍后再试。',
        can_regenerate: true
      });
      state.loading = false;
      saveConversation();
      renderMessagePatch(msg.id);
    }
  }

  function deleteAnswer(messageId) {
    var msg = resolveAnswerMessage(messageId);
    if (!msg) return;
    clearAnswerTimer(msg.id);
    if (msg.text) {
      state.deletedAnswerRefs.push({
        text: String(msg.text || '').slice(0, 500),
        request_text: String(msg.request_text || '').slice(0, 300),
        deletedAt: Date.now(),
        important: false
      });
      state.deletedAnswerRefs = state.deletedAnswerRefs.slice(-8);
    }
    state.messages = state.messages.filter(function (item) { return !item || item.id !== msg.id; });
    if (state.pendingMessageId === msg.id) state.pendingMessageId = '';
    saveConversation();
    renderActive();
  }

  function toggleResultPrompt(messageId) {
    var msg = findResultMessage(messageId);
    if (!msg) return;
    msg.prompt_open = !msg.prompt_open;
    saveConversation();
    renderActive();
  }

  function openResultPreview(messageId) {
    var msg = findResultMessage(messageId);
    if (!msg) return;
    var src = fullMediaSrc(msg) || mediaSrc(msg);
    if (!src) return;
    state.previewResult = {
      src: src,
      prompt: resultPromptText(msg)
    };
    renderActive();
  }

  function closeResultPreview() {
    state.previewResult = null;
    renderActive();
  }

  function handleJobUpdate(job) {
    if (!job || !state.pendingJobId || String(job.id || '') !== String(state.pendingJobId)) return;
    if (job.status === 'done' || job.status === 'checking') {
      var doneMessageId = state.pendingMessageId;
      var taskMessage = findMessage(doneMessageId) || {};
      var result = resultFromJob(job);
      result.prompt = result.prompt || taskMessage.prompt_preview || taskMessage.prompt || taskMessage.task_description || '';
      state.lastResult = result;
      updateMessage(doneMessageId, Object.assign({
        role: 'assistant',
        type: 'result',
        text: '生成完成'
      }, result));
      state.pendingJobId = '';
      state.pendingMessageId = '';
      saveConversation();
      state.mode = 'conversation';
      renderMessagePatch(doneMessageId);
      return;
    }
    if (job.status === 'error') {
      var errorMessageId = state.pendingMessageId;
      var failed = state.messages.find(function (msg) { return msg && msg.id === errorMessageId; }) || {};
      updateMessage(errorMessageId, {
        role: 'assistant',
        type: 'task',
        text: job.message || '生成失败',
        task_description: failed.task_description || job.prompt_preview || '',
        prompt_preview: failed.prompt_preview || failed.prompt || job.prompt_preview || job.prompt || '',
        workflow_title: failed.workflow_title || job.workflow || '',
        data: failed.data || state.understanding || {},
        status: 'error',
        can_retry: true,
        job_id: job.id || state.pendingJobId,
        progress: job.progress || { pct: 0 }
      });
      state.pendingJobId = '';
      state.pendingMessageId = '';
      saveConversation();
      state.mode = 'conversation';
      renderMessagePatch(errorMessageId);
      return;
    }
    var statusText = job.message || jobStatusLabel(job.status) || '正在生成';
    var pct = jobProgressValue(job.progress);
    if (!isNaN(pct) && pct > 0 && pct < 100) statusText += ' ' + pct + '%';
    updateMessage(state.pendingMessageId, {
      role: 'assistant',
      type: 'task',
      text: statusText,
      status: job.status || 'generating',
      can_retry: false,
      job_id: job.id || state.pendingJobId,
      progress: job.progress || { pct: pct }
    });
    saveConversation();
    renderMessagePatch(state.pendingMessageId);
  }

  function syncSharedJobState(job) {
    if (!job || !job.id) return;
    try {
      if (window.CW && typeof CW.onJobUpdate === 'function') {
        CW.onJobUpdate(job);
      } else if (A.jobs) {
        A.jobs[job.id] = Object.assign({}, A.jobs[job.id] || {}, job);
      }
    } catch (_) {}
  }

  function jobStatusLabel(status) {
    var labels = {
      dispatching: '正在匹配出图实例',
      queued: '已加入生成队列',
      starting_comfyui: '正在启动 ComfyUI',
      preparing: '正在准备工作流',
      submitting: '正在提交工作流',
      generating: '正在生成',
      downloading: '正在拉取结果'
    };
    return labels[String(status || '')] || '';
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
      syncTextAreaHeight(event.target);
      syncConversationChromeMetrics();
    }
  }

  function onFocusIn(event) {
    if (event.target && event.target.id === 'mobileAgentText' && state.root && state.root.classList) {
      if (state.auraEnterTimer) {
        clearTimeout(state.auraEnterTimer);
        state.auraEnterTimer = null;
      }
      state.root.classList.remove('is-aura-entering', 'is-input-breathing');
      if (state.inputBlurTimer) {
        clearTimeout(state.inputBlurTimer);
        state.inputBlurTimer = null;
      }
      if (state.inputActiveTimer) clearTimeout(state.inputActiveTimer);
      state.root.classList.remove('is-input-blurring');
      state.root.classList.add('is-input-active');
      state.inputActiveTimer = setTimeout(function () {
        if (state.root && state.root.classList && state.root.classList.contains('is-input-active')) {
          state.root.classList.add('is-input-breathing');
        }
        state.inputActiveTimer = null;
      }, 4200);
    }
  }

  function onFocusOut(event) {
    if (event.target && event.target.id === 'mobileAgentText' && state.root && state.root.classList) {
      if (state.inputActiveTimer) {
        clearTimeout(state.inputActiveTimer);
        state.inputActiveTimer = null;
      }
      state.root.classList.remove('is-input-active', 'is-input-breathing');
      state.root.classList.add('is-input-blurring');
      if (state.inputBlurTimer) clearTimeout(state.inputBlurTimer);
      state.inputBlurTimer = setTimeout(function () {
        if (state.root && state.root.classList) state.root.classList.remove('is-input-blurring');
        state.inputBlurTimer = null;
      }, 4200);
    }
  }

  function onKeydown(event) {
    if (!event.target || event.target.id !== 'mobileAgentText') return;
    if (event.isComposing) return;
    if (event.key !== 'Enter' || event.shiftKey) return;
    if (typeof event.preventDefault === 'function') event.preventDefault();
    state.text = event.target.value || state.text;
    return submitUnderstand();
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
    state.lastVoiceError = {
      name: name,
      message: message,
      href: location.href,
      isSecureContext: !!window.isSecureContext,
      hasMediaDevices: !!(window.navigator && window.navigator.mediaDevices),
      hasGetUserMedia: !!(window.navigator && window.navigator.mediaDevices && window.navigator.mediaDevices.getUserMedia),
      hasMediaRecorder: typeof window.MediaRecorder === 'function'
    };
    if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
      return '当前页面不是安全上下文，手机浏览器可能无法完成麦克风授权。请使用 HTTPS 访问。';
    }
    if (raw.indexOf('notfound') >= 0 || raw.indexOf('device not found') >= 0 || raw.indexOf('requested device not found') >= 0) {
      return '没有找到可用麦克风，因此不会弹出授权框。请检查系统输入设备。';
    }
    if (raw.indexOf('notallowed') >= 0 || raw.indexOf('permission') >= 0 || raw.indexOf('denied') >= 0) {
      return '麦克风授权没有生效。请在浏览器网站设置和系统隐私设置中确认已允许麦克风，然后重试。';
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
      renderActive();
      return;
    }
    if (!window.FormData || !window.Blob) {
      state.error = '当前浏览器不支持语音文件转写。';
      state.voiceStatus = '';
      renderActive();
      return;
    }
    state.voiceBusy = true;
    state.voiceStatus = '正在转写语音';
    renderActive();
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
      renderActive();
    }
  }

  async function startVoiceCapture() {
    if (state.voiceBusy) return;
    if (state.voiceRecording) {
      stopVoiceCapture();
      return;
    }
    state.error = '';
    state.lastVoiceError = null;
    state.voicePending = true;
    state.voiceStatus = '正在请求麦克风';
    renderActive();
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
      renderActive();
    } catch (err) {
      stopVoiceStream();
      state.voiceRecorder = null;
      state.voicePending = false;
      state.voiceRecording = false;
      state.voiceStatus = '';
      state.error = voiceCaptureMessage(err);
      renderActive();
    }
  }

  function stopVoiceCapture() {
    var recorder = state.voiceRecorder;
    state.voicePending = false;
    state.voiceRecording = false;
    state.voiceStatus = '正在转写语音';
    renderActive();
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

  function ratioDimensions(ratio) {
    var dims = RATIO_DIMENSIONS[String(ratio || '')] || RATIO_DIMENSIONS['1:1'];
    return { width: dims.width, height: dims.height };
  }

  function stripStyleHints(prompt) {
    var text = String(prompt || '').trim();
    Object.keys(STYLE_HINTS).forEach(function (key) {
      var hint = STYLE_HINTS[key];
      text = text.replace(new RegExp('，?' + escapeRegExp(hint), 'g'), '');
    });
    return text.replace(/[，,、\s]+$/g, '').trim();
  }

  function escapeRegExp(value) {
    return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function applyStyleToPrompt(prompt, style) {
    var base = stripStyleHints(prompt);
    var hint = STYLE_HINTS[String(style || '')] || '';
    if (!hint) return base;
    return base ? base + '，' + hint : hint;
  }

  function refreshPromptFields(data, oldPrompt) {
    if (!data || !data.field_values) return;
    var nextPrompt = data.compiled_prompt || '';
    Object.keys(data.field_values).forEach(function (key) {
      var value = data.field_values[key];
      if (typeof value !== 'string') return;
      var lowerKey = String(key || '').toLowerCase();
      var promptKey = /::(text|prompt|positive_prompt|caption)$/.test(lowerKey) || lowerKey.indexOf('prompt') >= 0;
      if (promptKey || !oldPrompt || value === oldPrompt || stripStyleHints(value) === stripStyleHints(oldPrompt)) {
        data.field_values[key] = nextPrompt;
      }
    });
  }

  function selectedWorkflowChoice(data, value) {
    var choices = data && Array.isArray(data.workflow_choices) ? data.workflow_choices : [];
    return choices.find(function (item) {
      return item && String(item.workflow || '') === String(value || '');
    }) || null;
  }

  function toggleWorkflowMenu(messageId) {
    var confirmMessage = messageId ? state.messages.find(function (msg) { return msg && msg.id === messageId; }) : null;
    var data = (confirmMessage && confirmMessage.data) || state.understanding;
    if (!data) return;
    var choices = Array.isArray(data.workflow_choices) ? data.workflow_choices : [];
    if (choices.length <= 1) return;
    data.workflow_menu_open = !data.workflow_menu_open;
    state.understanding = data;
    saveConversation();
    renderActive();
  }

  function selectConfirmOption(messageId, option, value) {
    var confirmMessage = messageId ? state.messages.find(function (msg) { return msg && msg.id === messageId; }) : null;
    var data = (confirmMessage && confirmMessage.data) || state.understanding;
    if (!data) return;
    var oldPrompt = data.compiled_prompt || '';
    if (option === 'style') {
      data.style = value || '';
      data.compiled_prompt = applyStyleToPrompt(oldPrompt, data.style);
      data.display_summary = stripStyleHints(data.compiled_prompt);
      if (data.creative_brief) {
        data.creative_brief.style = data.style;
        data.creative_brief.final_prompt = data.compiled_prompt;
      }
      refreshPromptFields(data, oldPrompt);
    } else if (option === 'aspect_ratio') {
      data.aspect_ratio = value || '1:1';
      var dims = ratioDimensions(data.aspect_ratio);
      data.width = dims.width;
      data.height = dims.height;
      if (data.creative_brief) data.creative_brief.aspect_ratio = data.aspect_ratio;
      data.options = Object.assign({}, data.options || {}, {
        aspect_ratio: data.aspect_ratio,
        width: data.width,
        height: data.height
      });
    } else if (option === 'workflow') {
      var choice = selectedWorkflowChoice(data, value);
      if (!choice) return;
      data.resolved_workflow = choice.workflow || data.resolved_workflow || '';
      data.workflow_title = choice.title || choice.workflow || data.workflow_title || '';
      data.workflow_label = data.workflow_title;
      data.field_values = choice.field_values || data.field_values || {};
      data.error_code = '';
      data.question = '';
      data.workflow_menu_open = false;
    }
    if (confirmMessage) {
      confirmMessage.text = data.display_summary || data.compiled_prompt || confirmMessage.text;
    }
    state.understanding = data;
    saveConversation();
    renderActive();
  }

  function resetThreadState() {
    clearImagePreview();
    state.activeThreadId = makeId('thread');
    state.mode = 'home';
    state.text = '';
    state.understanding = null;
    state.messages = [];
    state.lastResult = null;
    state.pendingMessageId = '';
    state.pendingJobId = '';
    state.deletedAnswerRefs = [];
    state.loading = false;
    state.error = '';
    state.menuOpen = false;
  }

  function newChat() {
    saveConversation();
    resetThreadState();
    saveConversation();
    renderHome();
  }

  function openThread(threadId) {
    var thread = readThreads().find(function (item) { return item.id === threadId; });
    if (!thread) return;
    saveConversation();
    applyThread(thread);
    state.mode = 'conversation';
    state.menuOpen = false;
    state.error = '';
    renderConversation();
    refreshPendingJobState();
  }

  function deleteThread(threadId) {
    if (!threadId) return;
    var threads = readThreads().filter(function (item) { return item.id !== threadId; });
    writeThreads(threads);
    deleteThreadFromServer(threadId);
    if (state.activeThreadId === threadId) {
      resetThreadState();
    }
    state.menuOpen = false;
    renderActive();
  }

  function openAccountSettings() {
    state.menuOpen = false;
    renderActive();
    if (window.CW && CW.auth) {
      if (currentUser() && typeof CW.auth.showAccountTab === 'function') {
        CW.auth.showAccountTab('profile');
      } else if (typeof CW.auth.showLogin === 'function') {
        CW.auth.showLogin();
      }
    }
  }

  async function openLogin() {
    state.menuOpen = false;
    if (window.CW && window.CW.authReady && typeof window.CW.authReady.then === 'function') {
      try { await window.CW.authReady; } catch (_) {}
    }
    if (currentUser()) {
      renderActive();
      return;
    }
    renderActive();
    if (window.CW && CW.auth && typeof CW.auth.showLogin === 'function') {
      CW.auth.showLogin();
    }
  }

  function goDesktopHome() {
    saveConversation();
    location.href = '/comfy';
  }

  function logoutMobile() {
    state.menuOpen = false;
    if (window.CW && CW.auth && typeof CW.auth.logout === 'function') {
      CW.auth.logout();
    } else if (window.localStorage && typeof localStorage.removeItem === 'function') {
      localStorage.removeItem('v4_token');
    }
    renderActive();
  }

  function toggleAccountMenu() {
    state.menuOpen = !state.menuOpen;
    var menu = state.root && state.root.querySelector ? state.root.querySelector('.mobile-agent-menu') : null;
    if (!menu) {
      renderActive();
      return;
    }
    menu.classList.toggle('is-open', !!state.menuOpen);
    menu.setAttribute('aria-hidden', state.menuOpen ? 'false' : 'true');
  }

  function closeAccountMenu() {
    if (!state.menuOpen) return;
    state.menuOpen = false;
    var menu = state.root && state.root.querySelector ? state.root.querySelector('.mobile-agent-menu') : null;
    if (!menu) {
      renderActive();
      return;
    }
    menu.classList.remove('is-open');
    menu.setAttribute('aria-hidden', 'true');
  }

  function syncAfterAuthReady() {
    var afterAuth = function () {
      if (state.messages.length || state.lastResult || state.pendingJobId) {
        upsertCurrentThread();
      }
      loadRemoteThreads().finally(function () {
        if (state.pendingJobId) refreshPendingJobState();
        if (state.active) renderActive();
      });
    };
    if (window.CW && window.CW.authReady && typeof window.CW.authReady.then === 'function') {
      window.CW.authReady.finally(afterAuth);
      return;
    }
    if (currentUser()) {
      afterAuth();
      return;
    }
    if (typeof setInterval !== 'function' || typeof clearInterval !== 'function') return;
    var attempts = 0;
    var timer = setInterval(function () {
      attempts += 1;
      if (window.CW && window.CW.authReady && typeof window.CW.authReady.then === 'function') {
        clearInterval(timer);
        window.CW.authReady.finally(afterAuth);
      } else if (attempts >= 30) {
        clearInterval(timer);
      }
    }, 100);
  }

  function handleMobileAuthChange() {
    state.menuOpen = false;
    remoteThreadsLoaded = false;
    if (currentUser()) {
      if (state.messages.length || state.lastResult || state.pendingJobId) {
        upsertCurrentThread();
      }
      return loadRemoteThreads().finally(function () {
        if (state.pendingJobId) refreshPendingJobState();
        if (state.active) renderActive();
      });
    }
    if (state.active) renderActive();
    return Promise.resolve(readThreads());
  }

  function bindMobileAuthRefreshHook() {
    if (state.authHookBound || !window.CW) return;
    state.authHookBound = true;
    var previousRefresh = window.CW.refreshForAuthChange;
    window.CW.refreshForAuthChange = function () {
      var previousResult = typeof previousRefresh === 'function' ? previousRefresh() : null;
      if (!isRouteActive() && !state.active) return previousResult;
      return Promise.resolve(previousResult).catch(function () { return null; }).then(handleMobileAuthChange);
    };
  }

  function onClick(event) {
    var clickTarget = event.target || null;
    if (state.menuOpen && clickTarget && clickTarget.closest) {
      var insideMenu = clickTarget.closest('.mobile-agent-menu');
      var menuTrigger = clickTarget.closest('[data-action="toggle-account-menu"]');
      if (!insideMenu && !menuTrigger) closeAccountMenu();
    }
    var btn = event.target && event.target.closest ? event.target.closest('[data-action]') : null;
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    if (action === 'home' || action === 'home-main') {
      state.mode = 'home';
      state.menuOpen = false;
      renderHome();
      return;
    }
    if (action === 'history-home' || action === 'open-history') {
      state.mode = 'history';
      state.menuOpen = false;
      renderHistoryView();
      return;
    }
    if (action === 'toggle-account-menu') {
      toggleAccountMenu();
      return;
    }
    if (action === 'new-chat') newChat();
    if (action === 'open-thread') openThread(btn.getAttribute('data-thread-id') || '');
    if (action === 'delete-thread') deleteThread(btn.getAttribute('data-thread-id') || '');
    if (action === 'login') openLogin();
    if (action === 'logout') logoutMobile();
    if (action === 'account-settings') openAccountSettings();
    if (action === 'desktop-home') goDesktopHome();
    if (action === 'image') openImagePicker();
    if (action === 'remove-image') {
      clearImagePreview();
      renderActive();
    }
    if (action === 'voice') startVoiceCapture();
    if (action === 'understand') submitUnderstand();
    if (action === 'toggle-workflow-menu') toggleWorkflowMenu(btn.getAttribute('data-message-id') || '');
    if (action === 'select-option') selectConfirmOption(
      btn.getAttribute('data-message-id') || '',
      btn.getAttribute('data-option') || '',
      btn.getAttribute('data-value') || ''
    );
    if (action === 'generate') submitGenerate(btn.getAttribute('data-message-id') || '');
    if (action === 'retry-generate') submitGenerate(btn.getAttribute('data-message-id') || '');
    if (action === 'like-answer') likeAnswer(btn.getAttribute('data-message-id') || '');
    if (action === 'regenerate-answer') regenerateAnswer(btn.getAttribute('data-message-id') || '');
    if (action === 'delete-answer') deleteAnswer(btn.getAttribute('data-message-id') || '');
    if (action === 'toggle-result-prompt') toggleResultPrompt(btn.getAttribute('data-message-id') || '');
    if (action === 'open-result-preview') openResultPreview(btn.getAttribute('data-message-id') || '');
    if (action === 'close-result-preview') closeResultPreview();
  }

  function initMobileAgent() {
    state.root = $('#mobileAgentRoot');
    if (!state.root || state.root.dataset.mobileAgentReady === '1') return;
    state.root.dataset.mobileAgentReady = '1';
    loadConversation();
    state.root.addEventListener('input', onInput);
    state.root.addEventListener('focusin', onFocusIn);
    state.root.addEventListener('focusout', onFocusOut);
    state.root.addEventListener('keydown', onKeydown);
    state.root.addEventListener('change', onChange);
    state.root.addEventListener('click', onClick);
    if (window.addEventListener) window.addEventListener('hashchange', syncRoute);
    if (window.addEventListener) window.addEventListener('focus', refreshOnForeground);
    if (window.addEventListener) window.addEventListener('pageshow', refreshOnForeground);
    if (document.addEventListener) document.addEventListener('visibilitychange', refreshOnForeground);
    bindMobileAuthRefreshHook();
    syncAfterAuthReady();
    syncRoute();
  }

  window.CW = window.CW || {};
  window.CW.mobileAgent = {
    init: initMobileAgent,
    renderHome: renderHome,
    renderVoice: renderVoice,
    renderConfirm: renderConfirm,
    renderConversation: renderConversation,
    renderGenerating: renderGenerating,
    submitUnderstand: submitUnderstand,
    submitGenerate: submitGenerate,
    regenerateAnswer: regenerateAnswer,
    likeAnswer: likeAnswer,
    deleteAnswer: deleteAnswer,
    handleJobUpdate: handleJobUpdate,
    getConversationContext: getConversationContext,
    startVoiceCapture: startVoiceCapture,
    stopVoiceCapture: stopVoiceCapture,
    getVoiceDiagnostics: function () { return state.lastVoiceError ? Object.assign({}, state.lastVoiceError) : null; },
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
