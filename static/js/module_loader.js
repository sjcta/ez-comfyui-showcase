/**
 * module_loader.js
 * Unified loader for Ez ComfyUI Showcase.
 * Loads core app + modules in a stable order, then boots the app once.
 */
(function () {
  'use strict';

  var base = 'static/js';
  var version = '1779056000';
  var runtimeApiBase = (location.protocol === 'file:')
    ? 'http://localhost:18000'
    : '';
  var coreModules = [
    base + '/app.js?v=' + version,
    base + '/modules/icons.js?v=' + version,
    base + '/modules/status.js?v=' + version,
    base + '/modules/ui.js?v=' + version,
    base + '/modules/workflows.js?v=' + version,
    base + '/modules/history.js?v=' + version,
    base + '/modules/generate.js?v=' + version,
    base + '/modules/auth.js?v=' + version,
    base + '/modules/card_manager.js?v=' + version,
    base + '/modules/poll_manager.js?v=' + version
  ];
  var loggedInModules = [
    base + '/modules/log_panel.js?v=' + version,
    base + '/modules/node-editor.js?v=' + version,
    base + '/modules/nodes.js?v=' + version
  ];
  var loggedInModulesPromise = null;

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
    await loadSprite('static/icons/sprite.svg?v=' + version);
    for (var i = 0; i < coreModules.length; i++) {
      await loadScript(coreModules[i]);
    }
    if (window.CW.initCardManager) window.CW.initCardManager();
    if (window.CW.initPollManager) window.CW.initPollManager();
    if (window.CW._bootApp) window.CW._bootApp();
    if (window.CW.pollManager && window.CW.pollManager.start) window.CW.pollManager.start();
    var authReady = window.CW.authReady || Promise.resolve(null);
    authReady.then(function(user) {
      if (user && user.role) {
        return loadLoggedInModules(user).then(function() {
          if (window.CW.loadWorkflows) window.CW.loadWorkflows();
          if (window.CW.loadHistory) window.CW.loadHistory();
        });
      }
      if (window.CW.loadWorkflows) window.CW.loadWorkflows();
      if (window.CW.loadHistory) window.CW.loadHistory();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
