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
    active: false
  };

  function icon(name) {
    return window.CW && typeof CW.icon === 'function' ? CW.icon(name) : '';
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
    return location.hash === '#mobile-agent' ||
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
    setRootHtml(
      '<section class="mobile-agent-panel" data-view="home">' +
        '<div class="mobile-agent-hero">' +
          '<div class="mobile-agent-avatar" aria-hidden="true">EZ</div>' +
          '<div>' +
            '<h1>智能创作</h1>' +
            '<p>说出想法，EZ 会先整理成可确认的创作方案。</p>' +
          '</div>' +
        '</div>' +
        '<label class="mobile-agent-compose">' +
          '<span>描述你想生成的画面</span>' +
          '<textarea id="mobileAgentText" rows="5" placeholder="例如：一张赛博朋克风格的城市夜景，霓虹灯，电影感" autocomplete="off">' + escH(state.text) + '</textarea>' +
        '</label>' +
        (state.error ? '<div class="mobile-agent-error" role="alert">' + escH(state.error) + '</div>' : '') +
        '<div class="mobile-agent-input-row">' +
          '<button class="mobile-agent-icon-btn" type="button" disabled title="图片输入稍后开放" aria-label="图片输入">' + imageIcon + '</button>' +
          '<button class="mobile-agent-icon-btn" type="button" data-action="voice" title="语音输入" aria-label="语音输入">' + micIcon + '</button>' +
          '<button class="mobile-agent-send-btn" type="button" data-action="understand" aria-label="发送理解"' + (state.loading ? ' disabled' : '') + '>' +
            '<span>' + (state.loading ? '理解中' : '发送') + '</span>' + sendIcon +
          '</button>' +
        '</div>' +
      '</section>'
    );
  }

  function renderVoice() {
    var transcribePath = '/api/mobile-agent/transcribe';
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
        body: JSON.stringify({ text: state.text })
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
      renderHome();
    } finally {
      state.loading = false;
    }
  }

  function submitGenerate() {
    state.mode = 'generating';
    renderGenerating();
    toast('移动端生成将在下一步接入', 'info');
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

  function onClick(event) {
    var btn = event.target && event.target.closest ? event.target.closest('[data-action]') : null;
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    if (action === 'home') renderHome();
    if (action === 'voice') renderVoice();
    if (action === 'understand') submitUnderstand();
    if (action === 'generate') submitGenerate();
  }

  function initMobileAgent() {
    state.root = $('#mobileAgentRoot');
    if (!state.root || state.root.dataset.mobileAgentReady === '1') return;
    state.root.dataset.mobileAgentReady = '1';
    state.root.addEventListener('input', onInput);
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
