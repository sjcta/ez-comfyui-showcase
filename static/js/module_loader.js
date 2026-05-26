/**
 * module_loader.js
 * Unified loader for Ez ComfyUI Showcase.
 * Loads core app + modules in a stable order, then boots the app once.
 */
(function () {
  'use strict';

  var base = 'static/js';
  var version = '1779822800';
  var normalizedPath = String(location.pathname || '').replace(/\/+$/, '');
  var isMobileAgentPath = normalizedPath === '/app' || location.hash === '#mobile-agent';
  var runtimeApiBase = (location.protocol === 'file:')
    ? 'http://localhost:18000'
    : (normalizedPath === '/app' ? '/comfy' : '');
  if (normalizedPath === '/app') {
    window.CW_MOBILE_API_BASE = '/app';
    window.CW_JOB_API_BASE = '/comfy';
  } else if (isMobileAgentPath) {
    window.CW_MOBILE_API_BASE = '';
    window.CW_JOB_API_BASE = runtimeApiBase;
  }
  var desktopCoreModules = [
    base + '/app.js?v=' + version,
    base + '/modules/icons.js?v=' + version,
    base + '/modules/status.js?v=' + version,
    base + '/modules/ui.js?v=' + version,
    base + '/modules/workflows.js?v=' + version,
    base + '/modules/history.js?v=' + version,
    base + '/modules/generate.js?v=' + version,
    base + '/modules/mobile_agent/mobile-agent.js?v=' + version,
    base + '/modules/auth.js?v=' + version,
    base + '/modules/card_manager.js?v=' + version,
    base + '/modules/poll_manager.js?v=' + version
  ];
  var mobileCoreModules = [
    base + '/modules/icons.js?v=' + version,
    base + '/modules/ui.js?v=' + version,
    base + '/modules/auth.js?v=' + version,
    base + '/modules/poll_manager.js?v=' + version,
    base + '/modules/mobile_agent/mobile-agent.js?v=' + version
  ];
  var loggedInModules = [
    base + '/modules/log_panel.js?v=' + version,
    base + '/modules/node-editor.js?v=' + version,
    base + '/modules/nodes.js?v=' + version
  ];
  var loggedInModulesPromise = null;

  function escH(value) {
    var d = document.createElement('div');
    d.textContent = value == null ? '' : String(value);
    return d.innerHTML;
  }

  function escA(value) {
    return String(value == null ? '' : value).replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  function initMobileSharedApp() {
    var jobs = {};
    var jobFields = {};
    var historyItems = [];
    var setVH = function () {
      document.documentElement.style.setProperty('--vh', String(window.innerHeight * 0.01) + 'px');
    };
    if (!window.__APP__) {
      window.__APP__ = {
        $: function (selector) { return document.querySelector(selector); },
        $$: function (selector) { return document.querySelectorAll(selector); },
        escH: escH,
        escA: escA,
        API: runtimeApiBase,
        jobs: jobs,
        jobFields: jobFields,
        historyItems: historyItems
      };
    }
    setVH();
    window.addEventListener('resize', setVH);
    window.addEventListener('orientationchange', setVH);
  }

  function loadScript(src) {
    return new Promise(function(resolve, reject) {
      var el = document.createElement('script');
      el.src = src;
      el.async = false;
      el.onload = function() { resolve(src); };
      el.onerror = function() { reject(new Error('Failed to load ' + src)); };
      document.head.appendChild(el);
    });
  }

  function loadStylesheet(href) {
    return new Promise(function(resolve, reject) {
      var el = document.createElement('link');
      el.rel = 'stylesheet';
      el.href = href;
      el.onload = function() { resolve(href); };
      el.onerror = function() { reject(new Error('Failed to load ' + href)); };
      document.head.appendChild(el);
    });
  }

  function loadFontPreconnects() {
    var urls = [
      'https://fonts.googleapis.com',
      'https://fonts.gstatic.com'
    ];
    for (var i = 0; i < urls.length; i++) {
      var rel = i === 1 ? 'preconnect' : 'preconnect';
      if (!document.querySelector('link[href="' + urls[i] + '"]')) {
        var link = document.createElement('link');
        link.rel = rel;
        link.href = urls[i];
        if (i === 1) link.crossOrigin = 'anonymous';
        document.head.appendChild(link);
      }
    }
    if (!document.querySelector('link[data-cw-fonts]')) {
      var fontLink = document.createElement('link');
      fontLink.rel = 'stylesheet';
      fontLink.dataset.cwFonts = '1';
      fontLink.href = 'https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap';
      document.head.appendChild(fontLink);
    }
  }

  function loadSprite(href) {
    return fetch(href).then(function(r) { return r.text(); }).then(function(svg) {
      if (!document.getElementById('cwIconSprite')) {
        var box = document.createElement('div');
        box.innerHTML = svg;
        var sprite = box.firstElementChild;
        if (sprite) {
          sprite.id = 'cwIconSprite';
          var slot = document.getElementById('cw-sprite-slot');
          if (slot && slot.parentNode) slot.parentNode.replaceChild(sprite, slot);
          else document.body.insertBefore(sprite, document.body.firstChild);
        }
      }
    });
  }

  function loadLoggedInModules(user) {
    if (!user || !user.role) return Promise.resolve(false);
    if (loggedInModulesPromise) return loggedInModulesPromise;
    loggedInModulesPromise = (async function() {
      for (var j = 0; j < loggedInModules.length; j++) {
        await loadScript(loggedInModules[j]);
      }
      return true;
    })().catch(function(err) {
      loggedInModulesPromise = null;
      throw err;
    });
    return loggedInModulesPromise;
  }

  async function boot() {
    window.CW = window.CW || {};
    window.CW.__skipAutoBoot = true;
    window.CW_API_BASE = runtimeApiBase;
    window.CW.loadLoggedInModules = loadLoggedInModules;
    loadFontPreconnects();
    if (!document.getElementById('cwStyleLink')) {
      var link = document.createElement('link');
      link.id = 'cwStyleLink';
      link.rel = 'stylesheet';
      link.href = 'static/css/style.css?v=' + version;
      document.head.appendChild(link);
    }
    await loadStylesheet('static/css/mobile-agent.css?v=' + version);
    await loadSprite('static/icons/sprite.svg?v=' + version);
    if (isMobileAgentPath) initMobileSharedApp();
    var modulesToLoad = isMobileAgentPath ? mobileCoreModules : desktopCoreModules;
    for (var i = 0; i < modulesToLoad.length; i++) {
      await loadScript(modulesToLoad[i]);
    }
    if (!isMobileAgentPath && window.CW.initCardManager) window.CW.initCardManager();
    if (window.CW.initPollManager) window.CW.initPollManager();
    if (!isMobileAgentPath && window.CW._bootApp) window.CW._bootApp();
    if (window.CW.initMobileAgent) window.CW.initMobileAgent();
    if (window.CW.pollManager && window.CW.pollManager.start) window.CW.pollManager.start();
    var authReady = window.CW.authReady || Promise.resolve(null);
    authReady.then(function(user) {
      if (isMobileAgentPath) return;
      if (window.CW.loadWorkflows) window.CW.loadWorkflows();
      if (window.CW.loadHistory) window.CW.loadHistory();
      if (user && user.role) {
        return loadLoggedInModules(user).catch(function(err) {
          console.warn('logged-in modules failed:', err && err.message ? err.message : err);
        });
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
