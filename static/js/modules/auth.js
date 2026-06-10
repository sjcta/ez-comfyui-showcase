/**
 * Auth Module — 用户认证（登录/注册/会话管理）
 */
(function() {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API;
  var _currentUser = null;
  var _dropdownOpen = false;
  var _historyFilters = {
    query: '',
    share: 'all',
    user: '',
    favorite: false,
    trash: false,
    hidden: false
  };
  var _historyHoverPreview = null;
  var _accountActiveTab = 'profile';
  var _usersCache = [];
  var _notificationRecords = [];
  var _notificationEditingId = null;
  var _siteNotificationItems = [];
  var _siteNotificationIndex = 0;
  var _siteNotificationLatestId = 0;
  var _siteNotificationCheckStarted = false;
  var _systemLlmProfiles = [];
  var _historyCache = [];
  var _expandedHistoryPrompts = {};
  var _historyFavorites = {};
  var HISTORY_FETCH_LIMIT = 5000;

  function _historyFavoriteStorageKey() {
    var ident = _currentUser && (_currentUser.id || _currentUser.user_id || _currentUser.username);
    return 'cw_history_favorites:' + (ident ? String(ident) : 'guest');
  }

  function _siteNotificationMuteStorageKey() {
    var ident = _currentUser && (_currentUser.id || _currentUser.user_id || _currentUser.username);
    return 'cw_site_notifications_muted_until:' + (ident ? String(ident) : 'guest');
  }

  function _loadHistoryFavorites() {
    var storageKey = _historyFavoriteStorageKey();
    try {
      var raw = localStorage.getItem(storageKey);
      if (raw) return JSON.parse(raw || '{}') || {};
      var legacy = localStorage.getItem('cw_history_favorites');
      var migrated = localStorage.getItem('cw_history_favorites_migrated:' + storageKey);
      if (legacy && !migrated && storageKey !== 'cw_history_favorites:guest') {
        localStorage.setItem(storageKey, legacy);
        localStorage.setItem('cw_history_favorites_migrated:' + storageKey, '1');
        return JSON.parse(legacy || '{}') || {};
      }
      return {};
    } catch (e) {
      return {};
    }
  }

  function _saveHistoryFavorites() {
    try {
      localStorage.setItem(_historyFavoriteStorageKey(), JSON.stringify(_historyFavorites || {}));
    } catch (e) {}
  }

  function _getToken() { return ''; }
  function _setToken(t) { _clearToken(); }
  function _clearToken() { localStorage.removeItem('v4_token'); }
  function isLoggedIn() { return !!_currentUser; }
  function getCurrentUser() { return _currentUser; }

  function getAuthHeaders() {
    return {};
  }

  function _readCookie(name) {
    try {
      var prefix = encodeURIComponent(name) + '=';
      var parts = String(document.cookie || '').split(';');
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i].trim();
        if (part.indexOf(prefix) === 0) return decodeURIComponent(part.slice(prefix.length));
      }
    } catch (e) {}
    return '';
  }

  function _isUnsafeMethod(method) {
    method = String(method || 'GET').toUpperCase();
    return method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE';
  }

  function _attachCsrfHeader(opts) {
    opts = opts || {};
    var method = opts.method || 'GET';
    if (_isUnsafeMethod(method)) {
      var csrf = _readCookie('ez_comfyui_csrf');
      if (csrf) {
        opts.headers = Object.assign({}, opts.headers || {}, { 'X-CSRF-Token': csrf });
      }
    }
    return opts;
  }

  function _clearPageStateBeforeLogoutReload() {
    try {
      if (window.CW && window.CW.pollManager && typeof window.CW.pollManager.stop === 'function') {
        window.CW.pollManager.stop();
      }
    } catch (e) {}
    try {
      if (window.__APP__) {
        if (window.__APP__.historyItems) window.__APP__.historyItems.length = 0;
        if (window.__APP__.jobs) {
          Object.keys(window.__APP__.jobs).forEach(function(id) {
            delete window.__APP__.jobs[id];
          });
        }
        window.__APP__.currentWF = '';
        window.__APP__.currentTargetInstance = '';
        window.__APP__.currentTargetNodeId = '';
        window.__APP__.manualTargetInstance = false;
        window.__APP__._wfMeta = {};
      }
    } catch (e) {}
    [
      ['gallery', ''],
      ['histCount', ''],
      ['wfGrid', '<div class="wf-empty">正在退出...</div>'],
      ['wfTabs', ''],
      ['quickFormFields', ''],
      ['advFields', '']
    ].forEach(function(pair) {
      var el = document.getElementById(pair[0]);
      if (el) el.innerHTML = pair[1];
    });
    var genTitle = document.getElementById('genTitle');
    if (genTitle) genTitle.style.display = 'none';
    var genForm = document.getElementById('genForm');
    if (genForm) genForm.style.display = 'none';
    var genFooter = document.querySelector('.gen-footer');
    if (genFooter) genFooter.style.display = 'none';
    var btnGenerate = document.getElementById('btnGenerate');
    if (btnGenerate) btnGenerate.disabled = true;
    try {
      if (window.CW && typeof window.CW.closeLB === 'function') window.CW.closeLB();
    } catch (e) {}
    try {
      if (typeof closeModal === 'function') closeModal();
    } catch (e) {}
  }

  function _reloadPageAfterLogout() {
    var url = new URL(window.location.href);
    url.searchParams.set('_logout', String(Date.now()));
    window.location.replace(url.toString());
  }

  function _isLogoutReload() {
    try {
      return new URL(window.location.href).searchParams.has('_logout');
    } catch (e) {
      return false;
    }
  }

  function _clearLogoutReloadMarker() {
    try {
      var url = new URL(window.location.href);
      if (!url.searchParams.has('_logout')) return;
      url.searchParams.delete('_logout');
      var nextUrl = url.pathname + (url.search || '') + (url.hash || '');
      window.history.replaceState(window.history.state, document.title, nextUrl);
    } catch (e) {}
  }

  function apiFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {}, getAuthHeaders());
    if (!opts.credentials) opts.credentials = 'include';
    opts = _attachCsrfHeader(opts);
    return fetch(url, opts);
  }

  function _withCacheBust(url) {
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    return url + sep + '_ts=' + Date.now();
  }

  function _mapAuthError(detail, fallbackText) {
    switch (detail) {
      case 'Username is required': return '请输入用户名';
      case 'Password is required': return '请输入密码';
      case 'Username does not exist': return '用户名不存在';
      case 'Incorrect password': return '密码错误';
      case 'User disabled': return '账号已被禁用';
      case 'Username already exists': return '用户名已存在';
      case 'Username (min 2) or password (min 6) too short': return '用户名至少 2 位，密码至少 6 位';
      default: return detail || fallbackText;
    }
  }

  function _parseJsonSafe(resp) {
    return resp.json().catch(function() { return {}; });
  }

  function _closeDropdown() {
    _dropdownOpen = false;
    var menu = $('#authDropdownMenu');
    var trigger = $('#authDropdownTrigger');
    if (menu) menu.classList.remove('open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
  }

  function _toggleDropdown() {
    _dropdownOpen = !_dropdownOpen;
    var menu = $('#authDropdownMenu');
    var trigger = $('#authDropdownTrigger');
    if (menu) menu.classList.toggle('open', _dropdownOpen);
    if (trigger) trigger.setAttribute('aria-expanded', _dropdownOpen ? 'true' : 'false');
  }

  document.addEventListener('click', function(e) {
    var wrap = $('#authDropdownWrap');
    if (!wrap || wrap.contains(e.target)) return;
    _closeDropdown();
  });

  function _handleAuthResponse(data, okText, failText) {
    if (data && (data.id || data.username || data.token)) {
      _clearToken();
      return fetch(API + '/auth/me', {
        credentials: 'include'
      }).then(function(r) {
        if (!r.ok) throw new Error('auth/me failed');
        return r.json();
      }).then(function(user) {
        _currentUser = user || data;
        _historyFavorites = _loadHistoryFavorites();
        return Promise.resolve(
          window.CW && typeof window.CW.loadLoggedInModules === 'function'
            ? window.CW.loadLoggedInModules(_currentUser)
            : null
        ).catch(function() {
          return null;
        }).then(function() {
          _updateUI();
          closeModal();
          CW.toast(okText, 'done');
          if (window.CW && CW.refreshForAuthChange) CW.refreshForAuthChange();
          _scheduleSiteNotifications();
          return _currentUser;
        });
      }).catch(function() {
        _currentUser = data;
        _historyFavorites = _loadHistoryFavorites();
        return Promise.resolve(
          window.CW && typeof window.CW.loadLoggedInModules === 'function'
            ? window.CW.loadLoggedInModules(_currentUser)
            : null
        ).catch(function() {
          return null;
        }).then(function() {
          _updateUI();
          closeModal();
          CW.toast(okText, 'done');
          if (window.CW && CW.refreshForAuthChange) CW.refreshForAuthChange();
          _scheduleSiteNotifications();
          return data;
        });
      });
    }
    CW.toast((data && (data.detail || data.error)) || failText, 'error');
    return data;
  }

  function register(username, password) {
    return fetch(API + '/auth/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'include',
      body: JSON.stringify({ username: username, password: password })
    }).then(function(r) {
      return _parseJsonSafe(r).then(function(data) {
        if (!r.ok) {
          throw new Error(_mapAuthError(data && data.detail, '注册失败'));
        }
        return data;
      });
    }).then(function(data) {
      return _handleAuthResponse(data, '注册成功', '注册失败');
    });
  }

  function login(username, password) {
    return fetch(API + '/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'include',
      body: JSON.stringify({ username: username, password: password })
    }).then(function(r) {
      return _parseJsonSafe(r).then(function(data) {
        if (!r.ok) {
          throw new Error(_mapAuthError(data && data.detail, '登录失败'));
        }
        return data;
      });
    }).then(function(data) {
      return _handleAuthResponse(data, '登录成功', '登录失败');
    });
  }

  function logout() {
    _clearPageStateBeforeLogoutReload();
    try {
      var logoutRequest = fetch(API + '/auth/logout', _attachCsrfHeader({
        method: 'POST',
        credentials: 'include',
        keepalive: true
      })).catch(function() {});
      var reloadTimeout = new Promise(function(resolve) {
        setTimeout(resolve, 1200);
      });
      Promise.race([logoutRequest, reloadTimeout]).then(_reloadPageAfterLogout, _reloadPageAfterLogout);
    } catch (e) {
      _reloadPageAfterLogout();
    }
    _clearToken();
    _currentUser = null;
    _historyFavorites = _loadHistoryFavorites();
    _closeDropdown();
    _updateUI();
    CW.toast('已退出', 'info');
  }

  function restoreSession() {
    if (_isLogoutReload()) {
      try {
        fetch(API + '/auth/logout', _attachCsrfHeader({
          method: 'POST',
          credentials: 'include',
          keepalive: true
        })).catch(function() {});
      } catch (e) {}
      _clearToken();
      _currentUser = null;
      _historyFavorites = _loadHistoryFavorites();
      _updateUI();
      _clearLogoutReloadMarker();
      return Promise.resolve(null);
    }
    return fetch(API + '/auth/me', {
      credentials: 'include'
    }).then(function(r) {
      if (!r.ok) throw new Error('Session expired');
      return r.json();
    }).then(function(user) {
      _currentUser = user;
      _historyFavorites = _loadHistoryFavorites();
      _updateUI();
      _scheduleSiteNotifications();
      return user;
    }).catch(function() {
      _clearToken();
      _currentUser = null;
      _historyFavorites = _loadHistoryFavorites();
      _updateUI();
      _scheduleSiteNotifications();
      return null;
    });
  }

  function _updateUI() {
    var container = $('#authContainer');
    if (!container) return;
    var gatedIds = ['tbDeviceBtn', 'tbWfMgrBtn', 'tbLogBtn'];
    gatedIds.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = _currentUser ? '' : 'none';
    });
    var adminOnly = document.querySelectorAll('[data-admin-only="true"]');
    for (var ai = 0; ai < adminOnly.length; ai++) {
      adminOnly[ai].classList.toggle('hidden', !(_currentUser && _currentUser.role === 'admin'));
    }
    if (_currentUser) {
      var roleLabel = _currentUser.role === 'admin' ? '管理员' : '用户';
      container.innerHTML =
        '<div class="auth-dropdown" id="authDropdownWrap">' +
          '<button class="tb-wf-mgr-btn auth-dropdown-trigger" id="authDropdownTrigger" type="button" aria-expanded="false" onclick="CW.auth.toggleDropdown()">' +
            '<span class="auth-user-icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="8" r="4"></circle><path d="M4 21a8 8 0 0 1 16 0"></path></svg></span>' +
            '<span>' + escH(_currentUser.username) + '</span>' +
            '<span class="auth-role-chip">' + roleLabel + '</span>' +
            '<span class="auth-caret">▾</span>' +
          '</button>' +
          '<div class="auth-dropdown-menu" id="authDropdownMenu">' +
            '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showAccountTab(\'profile\')">' + (window.CW && CW.icon ? CW.icon('user-round-pen') : '') + '我的账户</button>' +
            '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showAccountTab(\'history\')">' + (window.CW && CW.icon ? CW.icon('image') : '') + '出图历史</button>' +
            '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showAccountTab(\'trash\')">' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + '回收站</button>' +
            (_currentUser.role === 'admin' ? '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showAccountTab(\'users\')">' + (window.CW && CW.icon ? CW.icon('users') : '') + '用户管理</button>' : '') +
            (_currentUser.role === 'admin' ? '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showAccountTab(\'notifications\')">' + (window.CW && CW.icon ? CW.icon('bell') : '') + '网站通知</button>' : '') +
            (_currentUser.role === 'admin' ? '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showSystemSettings()">' + (window.CW && CW.icon ? CW.icon('settings') : '') + '系统设置</button>' : '') +
            '<button class="auth-dropdown-item danger" type="button" onclick="CW.auth.logout()">' + (window.CW && CW.icon ? CW.icon('log-out') : '') + '退出登录</button>' +
          '</div>' +
        '</div>';
      var genBtn = $('#btnGenerate');
      if (genBtn) genBtn.disabled = false;
    } else {
      container.innerHTML =
        '<button class="tb-wf-mgr-btn" onclick="CW.auth.showLogin()">登录</button>' +
        '<button class="tb-wf-mgr-btn auth-register-btn" onclick="CW.auth.showRegister()">注册</button>';
    }
  }

  function showLogin() { _showModal('login'); }
  function showRegister() { _showModal('register'); }

  function _shouldAutoFocusAuthInput() {
    if (!window.matchMedia) return true;
    return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  }

  function _showModal(mode) {
    var old = $('#authModalOverlay');
    if (old) old.remove();
    var html = '<div class="auth-modal-overlay" id="authModalOverlay" onclick="if(event.target===this)closeModal()">' +
      '<div class="auth-modal">' +
      '<div class="auth-modal-header">' +
      '<span class="auth-modal-title">' + (mode === 'login' ? '登录' : '注册') + '</span>' +
      '<button class="auth-modal-close" type="button" onclick="closeModal()">×</button></div>' +
      '<div class="auth-modal-body">' +
      '<div class="auth-field"><label>用户名</label><input type="text" id="authUsername" placeholder="输入用户名" class="auth-input"></div>' +
      '<div class="auth-field"><label>密码</label><input type="password" id="authPassword" placeholder="输入密码" class="auth-input"></div>' +
      (mode === 'register' ? '<div class="auth-field"><label>确认密码</label><input type="password" id="authPassword2" placeholder="再次输入密码" class="auth-input"></div>' : '') +
      '<div class="auth-error" id="authError" style="display:none"></div>' +
      '<button class="btn btn-primary auth-submit" id="authSubmitBtn">' + (mode === 'login' ? '登录' : '注册') + '</button>' +
      '<div class="auth-switch">' +
      (mode === 'login' ? '还没有账号？<a href="javascript:CW.auth.showRegister()">注册</a>' : '已有账号？<a href="javascript:CW.auth.showLogin()">登录</a>') +
      '</div></div></div></div>';
    var div = document.createElement('div');
    div.innerHTML = html;
    var overlay = div.firstElementChild;
    document.body.appendChild(overlay);
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
    else overlay.classList.add('open');
    setTimeout(function() {
      var input = $('#authUsername');
      if (input && overlay.classList.contains('open') && _shouldAutoFocusAuthInput()) input.focus();
    }, 320);
    $('#authSubmitBtn').onclick = function() {
      var u = $('#authUsername').value.trim();
      var p = $('#authPassword').value;
      var errEl = $('#authError');
      errEl.style.display = 'none';
      if (!u || !p) {
        errEl.textContent = '请填写完整';
        errEl.style.display = 'block';
        return;
      }
      if (mode === 'register') {
        var p2 = $('#authPassword2').value;
        if (p !== p2) {
          errEl.textContent = '两次密码不一致';
          errEl.style.display = 'block';
          return;
        }
        register(u, p).catch(function(err) {
          errEl.textContent = err && err.message ? err.message : '注册失败';
          errEl.style.display = 'block';
        });
      } else {
        login(u, p).catch(function(err) {
          errEl.textContent = err && err.message ? err.message : '登录失败';
          errEl.style.display = 'block';
        });
      }
    };
    $('#authPassword').onkeydown = function(e) {
      if (e.key === 'Enter') $('#authSubmitBtn').click();
    };
    if ($('#authPassword2')) {
      $('#authPassword2').onkeydown = function(e) {
        if (e.key === 'Enter') $('#authSubmitBtn').click();
      };
    }
  }

  function closeModal() {
    var el = $('#authModalOverlay');
    if (!el) return;
    if (window.CW && CW.setModalOpen) CW.setModalOpen(el, false, { removeAfterClose: true });
    else el.remove();
  }
  window.closeModal = closeModal;

  function showAccount(initialTab) {
    _closeDropdown();
    var old = $('#accountModalOverlay');
    if (old) old.remove();
    initialTab = initialTab || 'profile';
    var requestedHiddenInitial = initialTab === 'hidden';
    if (requestedHiddenInitial) initialTab = 'history';
    var html = '<div class="auth-modal-overlay" id="accountModalOverlay" onclick="if(event.target===this)CW.auth.closeAccount()">' +
      '<div class="account-modal">' +
      '<div class="auth-modal-header"><span class="auth-modal-title">' + (window.CW && CW.icon ? CW.icon('user-round-pen', 18) : '') + '账户管理</span>' +
      '<button class="auth-modal-close" type="button" onclick="CW.auth.closeAccount()">×</button></div>' +
      '<div class="account-tabs">' +
      '<button class="account-tab' + (initialTab === 'profile' ? ' active' : '') + '" data-tab="profile">我的账户</button>' +
      '<button class="account-tab' + (initialTab === 'history' ? ' active' : '') + '" data-tab="history">出图历史</button>' +
      '<button class="account-tab' + (initialTab === 'trash' ? ' active' : '') + '" data-tab="trash">回收站</button>' +
      (_currentUser && _currentUser.role === 'admin' ? '<button class="account-tab' + (initialTab === 'users' ? ' active' : '') + '" data-tab="users">用户管理</button>' : '') +
      (_currentUser && _currentUser.role === 'admin' ? '<button class="account-tab' + (initialTab === 'notifications' ? ' active' : '') + '" data-tab="notifications">网站通知</button>' : '') +
      '</div><div class="account-body" id="accountBody"></div></div></div>';
    var div = document.createElement('div');
    div.innerHTML = html;
    var overlay = div.firstElementChild;
    document.body.appendChild(overlay);
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
    else overlay.classList.add('open');
    $$('#accountModalOverlay .account-tab').forEach(function(btn) {
      btn.onclick = function() {
        _setAccountTab(btn.dataset.tab);
      };
    });
    _setAccountTab(requestedHiddenInitial ? 'hidden' : initialTab);
  }

  function showAccountTab(tab) {
    showAccount(tab || 'profile');
  }

  function closeAccount() {
    var el = $('#accountModalOverlay');
    if (!el) return;
    if (window.CW && CW.setModalOpen) CW.setModalOpen(el, false, { removeAfterClose: true });
    else el.remove();
  }

  function _sysBool(id) {
    var el = $('#' + id);
    return !!(el && el.checked);
  }

  function _sysNumber(id, fallback) {
    var el = $('#' + id);
    var value = el ? Number(el.value) : NaN;
    if (!Number.isFinite(value)) value = fallback;
    return Math.max(0, Math.min(1, value));
  }

  function _sysPositiveNumber(id, fallback) {
    var el = $('#' + id);
    var value = el ? Number(el.value) : NaN;
    if (!Number.isFinite(value)) value = fallback;
    return Math.max(1, value);
  }

  function _sysText(id) {
    var el = $('#' + id);
    return el ? el.value : '';
  }

  function _settingsSwitch(id, label, hint, checked) {
    return '<label class="system-settings-switch">' +
      '<input type="checkbox" id="' + id + '"' + (checked ? ' checked' : '') + '>' +
      '<span><strong>' + label + '</strong><small>' + hint + '</small></span>' +
      '</label>';
  }

  function _settingsNumber(id, label, hint, value) {
    var normalized = Number(value);
    if (!Number.isFinite(normalized)) normalized = 0;
    return '<label class="system-settings-field">' +
      '<span>' + label + '</span>' +
      '<input class="auth-input" id="' + id + '" type="number" min="0" max="1" step="0.01" value="' + escA(String(normalized)) + '">' +
      '<small>' + hint + '</small>' +
      '</label>';
  }

  function _settingsText(id, label, hint, value, type) {
    return '<label class="system-settings-field">' +
      '<span>' + label + '</span>' +
      '<input class="auth-input" id="' + id + '" type="' + (type || 'text') + '" value="' + escA(value || '') + '">' +
      '<small>' + hint + '</small>' +
      '</label>';
  }

  function _settingsTextarea(id, label, value) {
    return '<label class="system-settings-field system-settings-textarea">' +
      '<span>' + label + '</span>' +
      '<textarea class="auth-input" id="' + id + '" rows="4">' + escH(value || '') + '</textarea>' +
      '</label>';
  }

  function setSystemSettingsTab(tab) {
    var active = tab || 'llm';
    $$('#systemSettingsBody [data-system-settings-tab]').forEach(function(btn) {
      var selected = btn.getAttribute('data-system-settings-tab') === active;
      btn.classList.toggle('active', selected);
      btn.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    $$('#systemSettingsBody [data-system-settings-panel]').forEach(function(panel) {
      panel.classList.toggle('active', panel.getAttribute('data-system-settings-panel') === active);
    });
  }

  function _llmProfileById(id) {
    id = String(id || '').trim();
    for (var i = 0; i < _systemLlmProfiles.length; i++) {
      if (String(_systemLlmProfiles[i].id || '') === id) return _systemLlmProfiles[i];
    }
    return null;
  }

  function _renderLlmProfilePicker(activeId) {
    if (!_systemLlmProfiles.length) return '';
    var options = _systemLlmProfiles.map(function(profile) {
      var id = String(profile.id || '').trim();
      var caps = Array.isArray(profile.capabilities) ? profile.capabilities.join('/') : '';
      var label = String(profile.name || id || 'LLM API').trim() + (caps ? ' · ' + caps : '');
      return '<option value="' + escA(id) + '"' + (id === activeId ? ' selected' : '') + '>' + escH(label) + '</option>';
    }).join('');
    return '<div class="system-settings-profile-row">' +
      '<label class="system-settings-profile-label" for="sysLlmApiProfile">快速切换</label>' +
      '<select class="auth-input" id="sysLlmApiProfile" onchange="CW.auth.applySystemLlmProfile(this.value)">' + options + '</select>' +
      '<span class="system-settings-profile-hint">视觉反推建议使用带 vision/mmproj 的接口；Mac 本地 Q4 适合文本处理。</span>' +
    '</div>';
  }

  function applySystemLlmProfile(id) {
    var profile = _llmProfileById(id);
    if (!profile) return;
    var enabled = $('#sysLlmApiEnabled');
    if (enabled) enabled.checked = profile.enabled !== false;
    var base = $('#sysLlmApiBaseUrl');
    var model = $('#sysLlmApiModel');
    var key = $('#sysLlmApiKey');
    var timeout = $('#sysLlmApiTimeout');
    if (base) base.value = String(profile.base_url || '');
    if (model) model.value = String(profile.model || '');
    if (key) key.value = String(profile.api_key || '');
    if (timeout) timeout.value = String(profile.timeout || 180);
    var resultEl = $('#systemSettingsLlmTestResult');
    if (resultEl) resultEl.textContent = '已切换到 ' + (profile.name || profile.id || 'LLM API') + '，保存后生效。';
  }

  function _renderSystemSettings(data) {
    var body = $('#systemSettingsBody');
    if (!body) return;
    var cfg = (data && data.image_protection) || {};
    var patterns = cfg.prompt_patterns || {};
    var llm = (data && data.llm_api) || {};
    _systemLlmProfiles = Array.isArray(data && data.llm_api_profiles) ? data.llm_api_profiles.slice() : [];
    var activeProfileId = String((data && data.active_llm_api_profile) || '').trim();
    body.innerHTML =
      '<div class="system-settings-tabs" role="tablist" aria-label="系统设置分类">' +
        '<button class="system-settings-tab active" type="button" role="tab" aria-selected="true" data-system-settings-tab="llm" onclick="CW.auth.setSystemSettingsTab(\'llm\')">LLM API</button>' +
        '<button class="system-settings-tab" type="button" role="tab" aria-selected="false" data-system-settings-tab="protection" onclick="CW.auth.setSystemSettingsTab(\'protection\')">图片保护</button>' +
        '<button class="system-settings-tab" type="button" role="tab" aria-selected="false" data-system-settings-tab="patterns" onclick="CW.auth.setSystemSettingsTab(\'patterns\')">提示词规则</button>' +
      '</div>' +
      '<div class="system-settings-panel active" data-system-settings-panel="llm">' +
      '<div class="system-settings-section">' +
        '<div class="account-panel-head"><strong>LLM / 图片反推 API</strong><span>配置提示词优化、翻译和图片反推使用的 OpenAI-compatible 接口。</span></div>' +
        _renderLlmProfilePicker(activeProfileId) +
        '<div class="system-settings-grid">' +
          _settingsSwitch('sysLlmApiEnabled', '启用 LLM API', '关闭后图片反推会直接回退到 Prompt 辅助实例。', llm.enabled !== false) +
          _settingsText('sysLlmApiBaseUrl', 'Base URL', '例如 http://10.10.10.75:8000，不要带 /v1。', llm.base_url || 'http://10.10.10.75:8000') +
          _settingsText('sysLlmApiModel', '模型 ID', '例如 qwen36-gguf-q4-mtp 或服务端模型名。', llm.model || 'qwen36-gguf-q4-mtp') +
          _settingsText('sysLlmApiKey', 'API Key', '公网 DGX LLM 必填；保存后会脱敏显示。', llm.api_key || '', 'password') +
          _settingsText('sysLlmApiTimeout', '超时秒数', '开发阶段先保证识别成功率，建议 180 秒起；稳定后再按实测耗时收紧到 30-60 秒。', String(llm.timeout || 180), 'number') +
        '</div>' +
        '<div class="system-settings-test-row">' +
          '<button class="prompt-tool-btn system-settings-test-btn" type="button" id="systemSettingsLlmTest" onclick="CW.auth.testLlmApiSettings()">' + (window.CW && CW.icon ? CW.icon('server') : '') + ' 测试 LLM 接口</button>' +
        '</div>' +
        '<div class="system-settings-test-status prompt-result-meta" id="systemSettingsLlmTestResult" aria-live="polite"></div>' +
      '</div>' +
      '</div>' +
      '<div class="system-settings-panel" data-system-settings-panel="protection">' +
      '<div class="system-settings-section">' +
        '<div class="account-panel-head"><strong>图片保护</strong><span>三路组合：人工审查最高优先级；自动审查中 LLM 视觉或提示词任一路命中即保护，两路都未命中才放行。</span></div>' +
        '<div class="system-settings-grid">' +
          _settingsSwitch('sysImageProtectionEnabled', '启用图片保护', '关闭后所有图片都会按 safe 处理。', cfg.enabled !== false) +
          _settingsSwitch('sysLlmVisionEnabled', '启用大模型视觉审查', '只判断图片里实际可见的情色、漏点、性器官、半透明暴露和暴力血腥；不按皮肤面积保护。', !!cfg.llm_vision_enabled) +
          _settingsNumber('sysLlmVisionReviewPasses', '视觉复核轮数', '默认 3 轮；用于降低单次视觉大模型幻觉或漏判。', cfg.llm_vision_review_passes || 3) +
          _settingsNumber('sysLlmVisionProtectVotes', '视觉保护票数', '默认 2 票；达到该票数才算大模型视觉命中。', cfg.llm_vision_protect_votes || 2) +
          _settingsSwitch('sysPromptSignalsEnabled', '启用提示词审查', '与大模型视觉审查为 OR 关系：提示词命中情色或暴力血腥规则时，即使视觉审查未命中也会保护。', !!cfg.prompt_signals_enabled) +
          '<div class="system-settings-note"><strong>人工审查</strong><span>管理员在大图模式用盾牌按钮手动开启/解除保护；人工结果来源为 manual-admin，优先级高于大模型视觉和提示词审查。</span></div>' +
          _settingsSwitch('sysDetectorEnabled', '启用旧 detector 兼容兜底', '仅在 LLM 视觉不可用或关闭后排队兜底；建议常规保持关闭，避免猫狗等误伤。', cfg.detector_enabled !== false) +
          _settingsSwitch('sysPromptContextEnabled', '启用弱 detector 提示词确认', '仅服务旧 detector 兜底链路，不影响 LLM 视觉 + 提示词 OR 规则。', cfg.prompt_context_enabled !== false) +
          _settingsSwitch('sysVisualFallbackEnabled', '启用本地像素兜底', '仅在 LLM 视觉不可用或关闭时作为最后兜底；建议常规保持关闭。', !!cfg.visual_fallback_enabled) +
          _settingsNumber('sysDetectorThreshold', 'Detector 基础阈值', '单项检测低于该值会被忽略。', cfg.detector_threshold) +
          _settingsNumber('sysPairedBreastThreshold', '成对两点阈值', '两侧 EXPOSED_BREAST_F 的较低分必须达到该值。', cfg.paired_breast_threshold) +
          _settingsNumber('sysButtocksThreshold', '臀部裸露阈值', '背面全裸类 EXPOSED_BUTTOCKS 达到该值会保护。', cfg.buttocks_threshold) +
          _settingsNumber('sysWeakBreastPromptThreshold', '弱露点确认阈值', '低置信度 EXPOSED_BREAST_F 加提示词风险达到该值会保护。', cfg.weak_breast_prompt_threshold) +
          _settingsNumber('sysClassifierThreshold', '分类器阈值', '可选分类器 unsafe 分数阈值。', cfg.classifier_threshold) +
          _settingsNumber('sysVisualIntimateSkinThreshold', '视觉兜底肤色阈值', '像素兜底进入细查的最低肤色占比。', cfg.visual_intimate_skin_threshold) +
          _settingsNumber('sysStrongPromptSkinThreshold', '硬提示词肤色阈值', '提示词保护开启时，硬词命中所需肤色占比。', cfg.strong_prompt_skin_threshold) +
          _settingsNumber('sysStrongNudeSkinThreshold', '裸体提示词肤色阈值', '提示词保护开启时，裸体词命中所需肤色占比。', cfg.strong_nude_skin_threshold) +
          _settingsNumber('sysNsfwRiskSkinThreshold', '软提示词肤色阈值', '提示词保护开启时，软词命中所需肤色占比。', cfg.nsfw_risk_skin_threshold) +
        '</div>' +
      '</div>' +
      '</div>' +
      '<div class="system-settings-panel" data-system-settings-panel="patterns">' +
      '<div class="system-settings-section">' +
        '<div class="account-panel-head"><strong>提示词管理</strong><span>按正则片段管理；提示词审查开启后，任一规则命中即保护；关闭后只保留人工和视觉审查。</span></div>' +
        '<div class="system-settings-patterns">' +
          _settingsTextarea('sysPromptPatternHard', '硬保护词', patterns.hard) +
          _settingsTextarea('sysPromptPatternRisk', '软风险词', patterns.risk) +
          _settingsTextarea('sysPromptPatternStrongNude', '裸体强信号词', patterns.strong_nude) +
          _settingsTextarea('sysPromptPatternViolence', '暴力血腥词', patterns.violence) +
          _settingsTextarea('sysPromptPatternObsceneGesture', '不雅手势词', patterns.obscene_gesture) +
        '</div>' +
      '</div>' +
      '</div>';
    var saveBtn = $('#systemSettingsSave');
    if (saveBtn) saveBtn.onclick = saveSystemSettings;
    setSystemSettingsTab('llm');
  }

  function showSystemSettings() {
    if (!_currentUser || _currentUser.role !== 'admin') return;
    _closeDropdown();
    var old = $('#systemSettingsOverlay');
    if (old) old.remove();
    var html = '<div class="auth-modal-overlay" id="systemSettingsOverlay" onclick="if(event.target===this)CW.auth.closeSystemSettings()">' +
      '<div class="account-modal system-settings-modal">' +
        '<div class="auth-modal-header"><span class="auth-modal-title">' + (window.CW && CW.icon ? CW.icon('settings', 18) : '') + '系统设置</span>' +
        '<button class="auth-modal-close" type="button" onclick="CW.auth.closeSystemSettings()">×</button></div>' +
        '<div class="account-body system-settings-body" id="systemSettingsBody"><div class="account-loading">加载中...</div></div>' +
        '<div class="system-settings-footer"><button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.closeSystemSettings()">取消</button><button class="wf-mgr-btn account-action-btn btn-primary-action" type="button" id="systemSettingsSave">保存设置</button></div>' +
      '</div></div>';
    var div = document.createElement('div');
    div.innerHTML = html;
    var overlay = div.firstElementChild;
    document.body.appendChild(overlay);
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
    else overlay.classList.add('open');
    apiFetch(_withCacheBust(API + '/api/system-settings'), { cache: 'no-store' })
      .then(function(r) { if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '加载失败'); }); return r.json(); })
      .then(function(d) { _renderSystemSettings((d && d.data) || {}); })
      .catch(function(e) {
        var body = $('#systemSettingsBody');
        if (body) body.innerHTML = '<div class="account-error">' + escH(e.message || '加载失败') + '</div>';
      });
  }

  function closeSystemSettings() {
    var el = $('#systemSettingsOverlay');
    if (!el) return;
    if (window.CW && CW.setModalOpen) CW.setModalOpen(el, false, { removeAfterClose: true });
    else el.remove();
  }

  function saveSystemSettings() {
    var activeProfileId = _sysText('sysLlmApiProfile').trim();
    var profiles = _systemLlmProfiles.map(function(profile) {
      var copy = Object.assign({}, profile || {});
      if (String(copy.id || '') === activeProfileId) {
        copy.enabled = _sysBool('sysLlmApiEnabled');
        copy.base_url = _sysText('sysLlmApiBaseUrl').trim();
        copy.model = _sysText('sysLlmApiModel').trim();
        copy.api_key = _sysText('sysLlmApiKey').trim();
        copy.timeout = _sysPositiveNumber('sysLlmApiTimeout', 180);
      }
      return copy;
    });
    var payload = {
      llm_api: {
        enabled: _sysBool('sysLlmApiEnabled'),
        base_url: _sysText('sysLlmApiBaseUrl').trim(),
        model: _sysText('sysLlmApiModel').trim(),
        api_key: _sysText('sysLlmApiKey').trim(),
        timeout: _sysPositiveNumber('sysLlmApiTimeout', 180),
      },
      llm_api_profiles: profiles,
      active_llm_api_profile: activeProfileId,
      image_protection: {
        enabled: _sysBool('sysImageProtectionEnabled'),
        llm_vision_enabled: _sysBool('sysLlmVisionEnabled'),
        llm_vision_review_passes: _sysNumber('sysLlmVisionReviewPasses', 3),
        llm_vision_protect_votes: _sysNumber('sysLlmVisionProtectVotes', 2),
        detector_enabled: _sysBool('sysDetectorEnabled'),
        prompt_signals_enabled: _sysBool('sysPromptSignalsEnabled'),
        prompt_context_enabled: _sysBool('sysPromptContextEnabled'),
        visual_fallback_enabled: _sysBool('sysVisualFallbackEnabled'),
        detector_threshold: _sysNumber('sysDetectorThreshold', 0.45),
        paired_breast_threshold: _sysNumber('sysPairedBreastThreshold', 0.56),
        buttocks_threshold: _sysNumber('sysButtocksThreshold', 0.75),
        weak_breast_prompt_threshold: _sysNumber('sysWeakBreastPromptThreshold', 0.52),
        classifier_threshold: _sysNumber('sysClassifierThreshold', 0.68),
        visual_intimate_skin_threshold: _sysNumber('sysVisualIntimateSkinThreshold', 0.40),
        strong_prompt_skin_threshold: _sysNumber('sysStrongPromptSkinThreshold', 0.14),
        strong_nude_skin_threshold: _sysNumber('sysStrongNudeSkinThreshold', 0.14),
        nsfw_risk_skin_threshold: _sysNumber('sysNsfwRiskSkinThreshold', 0.18),
        prompt_patterns: {
          hard: _sysText('sysPromptPatternHard'),
          risk: _sysText('sysPromptPatternRisk'),
          strong_nude: _sysText('sysPromptPatternStrongNude'),
          violence: _sysText('sysPromptPatternViolence'),
          obscene_gesture: _sysText('sysPromptPatternObsceneGesture')
        }
      }
    };
    apiFetch(API + '/api/system-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '保存失败'); });
      return r.json();
    }).then(function(d) {
      _renderSystemSettings((d && d.data) || {});
      CW.toast('系统设置已保存', 'done');
    }).catch(function(e) {
      CW.toast(e.message || '保存失败', 'error');
    });
  }

  function testLlmApiSettings() {
    var resultEl = $('#systemSettingsLlmTestResult');
    var btn = $('#systemSettingsLlmTest');
    var payload = {
      llm_api: {
        enabled: _sysBool('sysLlmApiEnabled'),
        base_url: _sysText('sysLlmApiBaseUrl').trim(),
        model: _sysText('sysLlmApiModel').trim(),
        api_key: _sysText('sysLlmApiKey').trim(),
        timeout: _sysPositiveNumber('sysLlmApiTimeout', 180),
      }
    };
    if (resultEl) resultEl.textContent = '测试中...';
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 测试中';
    }
    apiFetch(API + '/api/system-settings/llm/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '测试失败'); });
      return r.json();
    }).then(function(d) {
      if (resultEl) resultEl.textContent = '连接成功 · ' + (d.provider || d.model || 'LLM');
      CW.toast('LLM 接口连接成功', 'done');
    }).catch(function(e) {
      if (resultEl) resultEl.textContent = e.message || '测试失败';
      CW.toast(e.message || '测试失败', 'error');
    }).finally(function() {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('server') : '') + ' 测试 LLM 接口';
      }
    });
  }

  function _getLocalNotificationMutedUntil() {
    try {
      return parseInt(localStorage.getItem(_siteNotificationMuteStorageKey()) || '0', 10) || 0;
    } catch (e) {
      return 0;
    }
  }

  function _setLocalNotificationMutedUntil(id) {
    try {
      localStorage.setItem(_siteNotificationMuteStorageKey(), String(Math.max(0, Number(id) || 0)));
    } catch (e) {}
  }

  function _renderNotificationRecordRows() {
    var rows = (_notificationRecords || []).map(function(n) {
      var id = escA(String(n.id || ''));
      return '<div class="notice-record-row">' +
        '<div class="notice-record-main"><strong>' + escH(n.title || '-') + '</strong><span>' + escH(n.created_at || '-') + (n.created_by_username ? ' · ' + escH(n.created_by_username) : '') + '</span></div>' +
        '<p>' + escH(n.content || '') + '</p>' +
        '<div class="notice-record-actions">' +
          '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.editSiteNotification(\'' + id + '\')">' + (window.CW && CW.icon ? CW.icon('pencil') : '') + ' 编辑</button>' +
          '<button class="wf-mgr-btn account-action-btn btn-delete" type="button" onclick="CW.auth.deleteSiteNotification(\'' + id + '\')">' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' 删除</button>' +
        '</div>' +
      '</div>';
    }).join('');
    return rows || '<div class="account-empty">暂无发送记录</div>';
  }

  function _renderNotificationsAdmin() {
    var body = $('#accountBody');
    if (!body) return;
    var isEditing = _notificationEditingId !== null && _notificationEditingId !== undefined;
    body.innerHTML =
      '<div class="account-section notice-admin-section">' +
        '<div class="account-panel-head">' +
          '<strong>网站通知</strong>' +
          '<span>发送后会保存记录，并在普通用户打开界面时弹出展示。</span>' +
        '</div>' +
        '<div class="notice-compose-card">' +
          '<input type="hidden" id="siteNoticeEditingId" value="' + (isEditing ? escA(String(_notificationEditingId)) : '') + '">' +
          '<input class="auth-input" id="siteNoticeTitle" maxlength="120" placeholder="通知标题">' +
          '<textarea class="auth-input" id="siteNoticeContent" rows="5" maxlength="4000" placeholder="通知内容"></textarea>' +
          '<div class="notice-compose-actions">' +
            (isEditing ? '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.cancelEditSiteNotification()">取消编辑</button>' : '') +
            '<button class="wf-mgr-btn account-action-btn btn-primary-action" type="button" onclick="CW.auth.sendSiteNotification()">' + (isEditing ? '保存修改' : '发送通知') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="account-list-card notice-record-card">' +
          '<div class="account-toolbar"><strong>发送记录</strong><span>' + escH(String((_notificationRecords || []).length)) + ' 条</span></div>' +
          '<div id="siteNoticeRecords">' + _renderNotificationRecordRows() + '</div>' +
        '</div>' +
      '</div>';
    if (isEditing) {
      var editing = (_notificationRecords || []).find(function(n) { return String(n.id) === String(_notificationEditingId); });
      if (editing) {
        var titleEl = $('#siteNoticeTitle');
        var contentEl = $('#siteNoticeContent');
        if (titleEl) titleEl.value = editing.title || '';
        if (contentEl) contentEl.value = editing.content || '';
      }
    }
  }

  function _loadNotificationsAdmin() {
    var body = $('#accountBody');
    if (body) body.innerHTML = '<div class="account-loading">加载中...</div>';
    apiFetch(_withCacheBust(API + '/api/site-notifications/admin'), { cache: 'no-store' }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '加载失败'); });
      return r.json();
    }).then(function(d) {
      _notificationRecords = (d.data || []).slice();
      _renderNotificationsAdmin();
    }).catch(function(e) {
      if (body) body.innerHTML = '<div class="account-error">' + escH(e.message || '加载失败') + '</div>';
    });
  }

  function _replaceNotificationRecord(record) {
    var replaced = false;
    _notificationRecords = (_notificationRecords || []).map(function(item) {
      if (String(item.id) !== String(record.id)) return item;
      replaced = true;
      return record;
    });
    if (!replaced) _notificationRecords.unshift(record);
  }

  function editSiteNotification(id) {
    if (!_currentUser || _currentUser.role !== 'admin') return;
    var record = (_notificationRecords || []).find(function(n) { return String(n.id) === String(id); });
    if (!record) return CW.toast('通知记录不存在', 'error');
    _notificationEditingId = String(record.id);
    _renderNotificationsAdmin();
    var titleEl = $('#siteNoticeTitle');
    if (titleEl && titleEl.focus) titleEl.focus();
  }

  function cancelEditSiteNotification() {
    _notificationEditingId = null;
    _renderNotificationsAdmin();
  }

  function sendSiteNotification() {
    if (!_currentUser || _currentUser.role !== 'admin') return;
    var titleEl = $('#siteNoticeTitle');
    var contentEl = $('#siteNoticeContent');
    var title = titleEl ? titleEl.value.trim() : '';
    var content = contentEl ? contentEl.value.trim() : '';
    if (!title || !content) return CW.toast('请填写标题和内容', 'warn');
    var editingIdEl = $('#siteNoticeEditingId');
    var rawId = editingIdEl ? editingIdEl.value.trim() : '';
    var id = rawId ? encodeURIComponent(rawId) : '';
    apiFetch(API + (id ? '/api/site-notifications/' + id : '/api/site-notifications'), {
      method: id ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, content: content })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || (id ? '保存失败' : '发送失败')); });
      return r.json();
    }).then(function(d) {
      if (titleEl) titleEl.value = '';
      if (contentEl) contentEl.value = '';
      if (d && d.data) {
        if (id) _replaceNotificationRecord(d.data);
        else _notificationRecords.unshift(d.data);
      }
      _notificationEditingId = null;
      _renderNotificationsAdmin();
      CW.toast(id ? '网站通知已保存' : '网站通知已发送', 'done');
    }).catch(function(e) {
      CW.toast(e.message || (id ? '保存失败' : '发送失败'), 'error');
    });
  }

  function deleteSiteNotification(rawId) {
    if (!_currentUser || _currentUser.role !== 'admin') return;
    if (!rawId) return;
    if (!confirm('确定删除这条网站通知吗？删除后普通用户将不再看到它。')) return;
    var id = encodeURIComponent(rawId);
    apiFetch(API + '/api/site-notifications/' + id, { method: 'DELETE' })
      .then(function(r) {
        if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '删除失败'); });
        return r.json();
      })
      .then(function() {
        _notificationRecords = (_notificationRecords || []).filter(function(n) { return String(n.id) !== String(rawId); });
        if (String(_notificationEditingId) === String(rawId)) _notificationEditingId = null;
        _renderNotificationsAdmin();
        CW.toast('网站通知已删除', 'done');
      })
      .catch(function(e) {
        CW.toast(e.message || '删除失败', 'error');
      });
  }

  function _closeSiteNotification() {
    var el = $('#siteNotificationOverlay');
    if (!el) return;
    if (window.CW && CW.setModalOpen) CW.setModalOpen(el, false, { removeAfterClose: true });
    else el.remove();
  }

  function _renderSiteNotificationModal() {
    var items = _siteNotificationItems || [];
    var item = items[_siteNotificationIndex];
    if (!item) {
      _closeSiteNotification();
      return;
    }
    var old = $('#siteNotificationOverlay');
    if (old) old.remove();
    var hasNext = _siteNotificationIndex < items.length - 1;
    var html = '<div class="auth-modal-overlay site-notice-overlay" id="siteNotificationOverlay" onclick="if(event.target===this)CW.auth.closeSiteNotification()">' +
      '<div class="site-notice-modal">' +
        '<div class="auth-modal-header"><span class="auth-modal-title">' + (window.CW && CW.icon ? CW.icon('bell', 18) : '') + '网站通知</span>' +
        '<button class="auth-modal-close" type="button" onclick="CW.auth.closeSiteNotification()">×</button></div>' +
        '<div class="site-notice-body">' +
          '<div class="site-notice-count">' + escH(String(_siteNotificationIndex + 1)) + ' / ' + escH(String(items.length)) + '</div>' +
          '<h3>' + escH(item.title || '通知') + '</h3>' +
          '<p>' + escH(item.content || '') + '</p>' +
          '<span>' + escH(item.created_at || '') + '</span>' +
        '</div>' +
        '<div class="site-notice-actions">' +
          '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.closeSiteNotification()">关闭</button>' +
          '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.muteSiteNotifications()">不再通知</button>' +
          (hasNext ? '<button class="wf-mgr-btn account-action-btn btn-primary-action" type="button" onclick="CW.auth.nextSiteNotification()">下一条</button>' : '') +
        '</div>' +
      '</div></div>';
    var div = document.createElement('div');
    div.innerHTML = html;
    var overlay = div.firstElementChild;
    document.body.appendChild(overlay);
    if (window.CW && CW.setModalOpen) CW.setModalOpen(overlay, true);
    else overlay.classList.add('open');
  }

  function nextSiteNotification() {
    if (_siteNotificationIndex < (_siteNotificationItems || []).length - 1) {
      _siteNotificationIndex += 1;
      _renderSiteNotificationModal();
    }
  }

  function muteSiteNotifications() {
    var targetId = _siteNotificationLatestId || ((_siteNotificationItems || []).reduce(function(maxId, item) {
      return Math.max(maxId, Number(item.id) || 0);
    }, 0));
    _setLocalNotificationMutedUntil(targetId);
    if (_currentUser) {
      apiFetch(API + '/api/site-notifications/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notification_id: targetId })
      }).catch(function() {});
    }
    _closeSiteNotification();
    CW.toast('已关闭当前通知', 'done');
  }

  function _checkSiteNotifications() {
    return apiFetch(_withCacheBust(API + '/api/site-notifications'), { cache: 'no-store' }).then(function(r) {
      if (!r.ok) return null;
      return r.json();
    }).then(function(d) {
      if (!(d && d.ok)) return;
      _siteNotificationLatestId = Number(d.latest_id || 0) || 0;
      var localMutedUntil = _getLocalNotificationMutedUntil();
      var items = (d.data || []).filter(function(item) {
        return (Number(item.id) || 0) > localMutedUntil;
      });
      if (!items.length) return;
      _siteNotificationItems = items;
      _siteNotificationIndex = 0;
      _renderSiteNotificationModal();
    }).catch(function(e) {
      console.warn('site notifications failed:', e && e.message ? e.message : e);
    });
  }

  function _scheduleSiteNotifications() {
    if (_siteNotificationCheckStarted) return;
    _siteNotificationCheckStarted = true;
    setTimeout(_checkSiteNotifications, 500);
  }

  function _renderAccountTab(tab) {
    var requestedHidden = tab === 'hidden';
    _accountActiveTab = requestedHidden ? 'history' : (tab || 'profile');
    if (tab === 'users') return _loadUsers();
    if (tab === 'notifications') return _loadNotificationsAdmin();
    if (tab === 'history' || requestedHidden) {
      _historyFilters.trash = false;
      _historyFilters.hidden = requestedHidden ? true : false;
      return _loadMyHistory();
    }
    if (tab === 'trash') {
      _historyFilters.trash = true;
      _historyFilters.hidden = false;
      _historyFilters.share = 'all';
      _historyFilters.favorite = false;
      return _loadMyHistory();
    }
    var body = $('#accountBody');
    var roleText = (_currentUser.role === 'admin') ? '管理员' : '普通用户';
    body.innerHTML =
      '<div class="account-section">' +
        '<div class="account-panel-head">' +
          '<strong>我的账户</strong>' +
          '<span>查看当前登录信息，并修改你的登录密码。</span>' +
        '</div>' +
        '<div class="account-profile-card">' +
          '<div class="account-profile-grid">' +
            '<div class="account-row"><span>用户名</span><strong>' + escH(_currentUser.username) + '</strong></div>' +
            '<div class="account-row"><span>账户 ID</span><strong>' + escH(_currentUser.id || '-') + '</strong></div>' +
            '<div class="account-row"><span>角色</span><strong>' + escH(roleText) + '</strong></div>' +
          '</div>' +
        '</div>' +
        '<div class="account-password-card">' +
          '<strong class="account-card-title">修改密码</strong>' +
          '<div class="account-form-grid">' +
            '<input class="auth-input" id="acctOldPass" type="password" placeholder="当前密码">' +
            '<input class="auth-input" id="acctNewPass" type="password" placeholder="新密码">' +
            '<button class="wf-mgr-btn account-action-btn btn-primary-action" id="acctChangePass">修改密码</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    $('#acctChangePass').onclick = _changePassword;
  }

  function _renderUsersFromCache() {
    var body = $('#accountBody');
    if (!body) return;
    var _roleOptionHtml = function(selectedRole, selectId) {
      return '<select class="user-role"' + (selectId ? ' id="' + selectId + '"' : '') + '>' +
        '<option value="user"' + (selectedRole === 'user' ? ' selected' : '') + '>普通</option>' +
        '<option value="admin"' + (selectedRole === 'admin' ? ' selected' : '') + '>管理员</option>' +
      '</select>';
    };
    var _statusButtonHtml = function(user) {
      var isSelf = !!(_currentUser && _currentUser.id === user.id);
      var isDisabled = !!user.disabled;
      var cls = 'wf-mgr-btn account-action-btn user-status-btn ' + (isDisabled ? 'is-disabled' : 'is-enabled') + (isSelf ? ' is-locked' : '');
      var label = isDisabled ? '禁用' : '可用';
      var attrs = isSelf
        ? ' disabled title="不能禁用当前登录账户"'
        : ' onclick="CW.auth.toggleUserDisabled(\'' + escA(user.id) + '\')"';
      return '<button class="' + cls + '" type="button" data-disabled="' + (isDisabled ? '1' : '0') + '"' + attrs + '>' + label + '</button>';
    };
    var rows = (_usersCache || []).map(function(u) {
      var isSelf = !!(_currentUser && _currentUser.id === u.id);
      var genCount = Number(u.generation_count || 0);
      return '<div class="user-row' + (isSelf ? ' is-self' : '') + '" data-uid="' + escA(u.id) + '">' +
        '<div class="user-ident">' +
          '<div class="user-ident-top"><strong>' + escH(u.username) + '</strong>' + (isSelf ? '<span class="account-self-tag">当前账户</span>' : '') + '</div>' +
          '<span>' + escH(u.id) + '</span>' +
          '<span class="user-gen-count">出图 ' + escH(String(genCount)) + ' 张</span>' +
        '</div>' +
        _roleOptionHtml(u.role) +
        _statusButtonHtml(u) +
        '<input class="auth-input user-pass" type="password" placeholder="重置密码">' +
        '<button class="wf-mgr-btn account-action-btn btn-save" type="button" onclick="CW.auth.saveUser(\'' + escA(u.id) + '\')">保存</button>' +
        '<button class="wf-mgr-btn account-action-btn btn-delete' + (isSelf ? ' is-disabled' : '') + '" type="button"' + (isSelf ? ' disabled title="不能删除当前登录账户"' : ' onclick="CW.auth.deleteUser(\'' + escA(u.id) + '\')"') + '>删除</button>' +
        '</div>';
    }).join('');
    body.innerHTML =
      '<div class="account-section">' +
        '<div class="account-panel-head">' +
          '<strong>用户管理</strong>' +
          '<span>管理员可以在这里新建、调整、禁用或删除平台用户。</span>' +
        '</div>' +
        '<div class="account-create-user">' +
          '<strong>新建用户</strong>' +
          '<div class="account-create-grid">' +
            '<input class="auth-input" id="newUserName" placeholder="用户名">' +
            '<input class="auth-input" id="newUserPassword" type="password" placeholder="至少 6 位密码" required minlength="6">' +
            _roleOptionHtml('user', 'newUserRole') +
            '<button class="wf-mgr-btn account-action-btn btn-primary-action" type="button" onclick="CW.auth.createUser()">创建用户</button>' +
          '</div>' +
        '</div>' +
        '<div class="account-list-card">' +
          '<div class="account-toolbar"><strong>注册用户</strong><span>' + escH(String((_usersCache || []).length)) + ' 个账户</span></div>' +
          '<div class="user-table-head">' +
            '<span>账户</span>' +
            '<span>角色</span>' +
            '<span>状态</span>' +
            '<span>密码</span>' +
            '<span>保存</span>' +
            '<span>删除</span>' +
          '</div>' +
          (rows || '<div class="account-empty">暂无用户</div>') +
        '</div>' +
      '</div>';
  }

  function _setAccountTab(tab) {
    var requestedHidden = tab === 'hidden';
    _accountActiveTab = requestedHidden ? 'history' : (tab || 'profile');
    $$('#accountModalOverlay .account-tab').forEach(function(x) {
      x.classList.toggle('active', x.dataset.tab === _accountActiveTab);
    });
    _renderAccountTab(requestedHidden ? 'hidden' : _accountActiveTab);
  }

  function _highlightUserRow(uid) {
    if (!uid) return;
    var rows = $$('#accountBody .user-row');
    rows.forEach(function(row) { row.classList.remove('is-highlighted'); });
    var target = document.querySelector('#accountBody .user-row[data-uid="' + uid + '"]');
    if (!target) return;
    target.classList.add('is-highlighted');
    target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
  }

  function jumpToUser(uid) {
    if (!_currentUser || _currentUser.role !== 'admin' || !uid) return;
    _setAccountTab('users');
    var hasUser = (_usersCache || []).some(function(u) { return String(u.id) === String(uid); });
    if (hasUser) {
      requestAnimationFrame(function() { _highlightUserRow(uid); });
      return;
    }
    _syncUsers().then(function() {
      if (_accountActiveTab !== 'users') _setAccountTab('users');
      requestAnimationFrame(function() { _highlightUserRow(uid); });
    });
  }

  function _changePassword() {
    var oldPass = $('#acctOldPass').value;
    var newPass = $('#acctNewPass').value;
    apiFetch(API + '/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: oldPass, new_password: newPass })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '修改失败'); });
      return r.json();
    }).then(function() {
      CW.toast('密码已修改', 'done');
      $('#acctOldPass').value = '';
      $('#acctNewPass').value = '';
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function _loadUsers() {
    var body = $('#accountBody');
    body.innerHTML = '<div class="account-loading">加载中...</div>';
    apiFetch(_withCacheBust(API + '/api/users'), { cache: 'no-store' }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '加载失败'); });
      return r.json();
    }).then(function(d) {
      _usersCache = (d.data || []).slice();
      return _syncUserGenerationCounts().then(function() {
        _renderUsersFromCache();
      });
    }).catch(function(e) {
      body.innerHTML = '<div class="account-error">' + escH(e.message) + '</div>';
    });
  }

  function _syncUsers() {
    return apiFetch(_withCacheBust(API + '/api/users'), { cache: 'no-store' }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '加载失败'); });
      return r.json();
    }).then(function(d) {
      _usersCache = (d.data || []).slice();
      return _syncUserGenerationCounts().then(function() {
        if (_accountActiveTab === 'users') _renderUsersFromCache();
        return _usersCache;
      });
    }).catch(function(e) {
      console.warn('sync users failed:', e && e.message ? e.message : e);
      return _usersCache;
    });
  }

  function _syncUserGenerationCounts() {
    return apiFetch(_withCacheBust(API + '/api/history/user-counts'), { cache: 'no-store' }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '加载失败'); });
      return r.json();
    }).then(function(d) {
      var counts = d.counts || {};
      _usersCache = (_usersCache || []).map(function(u) {
        return Object.assign({}, u, { generation_count: counts[String(u.id)] || 0 });
      });
      return _usersCache;
    }).catch(function(e) {
      console.warn('sync user generation counts failed:', e && e.message ? e.message : e);
      return _usersCache;
    });
  }

  function createUser() {
    var username = ($('#newUserName') && $('#newUserName').value.trim()) || '';
    var password = ($('#newUserPassword') && $('#newUserPassword').value) || '';
    var role = ($('#newUserRole') && $('#newUserRole').value) || 'user';
    if (!username) return CW.toast('请输入用户名', 'info');
    if (password.length < 6) return CW.toast('请输入至少 6 位密码', 'info');
    apiFetch(API + '/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, password: password, role: role })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '创建失败'); });
      return r.json();
    }).then(function(d) {
      if (d && d.data) _usersCache.push(d.data);
      CW.toast('用户已创建', 'done');
      _renderUsersFromCache();
      _syncUsers();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function toggleUserDisabled(uid) {
    var row = document.querySelector('.user-row[data-uid="' + uid + '"]');
    if (!row) return;
    var btn = row.querySelector('.user-status-btn');
    if (!btn || btn.disabled) return;
    var nextDisabled = btn.getAttribute('data-disabled') !== '1';
    btn.setAttribute('data-disabled', nextDisabled ? '1' : '0');
    btn.classList.toggle('is-disabled', nextDisabled);
    btn.classList.toggle('is-enabled', !nextDisabled);
    btn.textContent = nextDisabled ? '禁用' : '可用';
    CW.toast(nextDisabled ? '已切换为禁用状态' : '已切换为可用状态', 'info');
  }

  function saveUser(uid) {
    var row = document.querySelector('.user-row[data-uid="' + uid + '"]');
    if (!row) return;
    var pass = row.querySelector('.user-pass').value;
    var statusBtn = row.querySelector('.user-status-btn');
    var body = {
      role: row.querySelector('.user-role').value,
      disabled: statusBtn ? statusBtn.getAttribute('data-disabled') === '1' : false
    };
    if (pass) body.new_password = pass;
    apiFetch(API + '/api/users/' + encodeURIComponent(uid), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '保存失败'); });
      return r.json();
    }).then(function() {
      _usersCache = (_usersCache || []).map(function(u) {
        if (u.id !== uid) return u;
        return Object.assign({}, u, body);
      });
      CW.toast('用户已保存', 'done');
      _renderUsersFromCache();
      _syncUsers();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function deleteUser(uid) {
    if (!confirm('确定删除该用户吗？')) return;
    apiFetch(API + '/api/users/' + encodeURIComponent(uid), { method: 'DELETE' })
      .then(function(r) {
        if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '删除失败'); });
        return r.json();
      }).then(function() {
        _usersCache = (_usersCache || []).filter(function(u) { return u.id !== uid; });
        CW.toast('用户已删除', 'done');
        _renderUsersFromCache();
        _syncUsers();
      }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function _selectedHistoryIds() {
    return Array.from(document.querySelectorAll('#accountBody .hist-select:checked')).map(function(x) { return x.value; });
  }

  function _canDeleteHistoryItem(item) {
    if (_currentUser && _currentUser.role === 'admin') return true;
    var uid = _currentUser && (_currentUser.sub || _currentUser.id);
    var owner = item && item.user_id;
    return !!(uid && owner && String(uid) === String(owner));
  }

  function getHistoryActionState(item) {
    var hasUser = !!_currentUser;
    var hasItem = !!item;
    var id = hasItem && item.id ? String(item.id) : '';
    var favoriteKey = _historyFavoriteKey(item);
    return {
      hasUser: hasUser,
      canFavorite: !!(hasUser && id && favoriteKey),
      canShare: !!(hasUser && id),
      canHide: !!(hasUser && hasItem && id && _canDeleteHistoryItem(item)),
      canProtect: !!(hasUser && hasItem && id && _currentUser && _currentUser.role === 'admin'),
      canDelete: !!(hasUser && hasItem && _canDeleteHistoryItem(item)),
      isFavorited: !!(hasUser && favoriteKey && _historyFavorites[favoriteKey])
    };
  }

  function _ensureHistoryHoverPreview() {
    if (_historyHoverPreview) return _historyHoverPreview;
    var el = document.createElement('div');
    el.className = 'account-hist-floating-preview';
    el.innerHTML = '<img alt="">';
    document.body.appendChild(el);
    _historyHoverPreview = el;
    return el;
  }

  function _showHistoryHoverPreview(src, anchorEl) {
    if (!src || !anchorEl) return;
    var preview = _ensureHistoryHoverPreview();
    var img = preview.querySelector('img');
    var rect = anchorEl.getBoundingClientRect();
    var gap = 14;
    var width = Math.min(420, Math.floor(window.innerWidth * 0.42));
    var left = rect.right + gap;
    if (left + width > window.innerWidth - 16) {
      left = Math.max(16, rect.left - width - gap);
    }
    img.src = src;
    preview.style.width = width + 'px';
    preview.style.left = left + 'px';
    preview.style.top = (rect.top + rect.height / 2) + 'px';
    preview.classList.add('open');
  }

  function _hideHistoryHoverPreview() {
    if (!_historyHoverPreview) return;
    _historyHoverPreview.classList.remove('open');
  }

  function _matchHistoryFilter(item) {
    var query = (_historyFilters.query || '').trim().toLowerCase();
    var share = _historyFilters.share || 'all';
    var userFilter = _historyFilters.user || '';
    var favoriteOnly = !!_historyFilters.favorite;
    var trashMode = !!_historyFilters.trash;
    var hiddenMode = !!_historyFilters.hidden;
    var isDeleted = !!(item && (item.is_deleted || item.deleted_at));
    var isHidden = !!(item && item.is_hidden);
    if (trashMode !== isDeleted) return false;
    if (!trashMode && hiddenMode !== isHidden) return false;
    if (share === 'shared' && !item.is_public) return false;
    if (share === 'private' && item.is_public) return false;
    if (userFilter && String(item.user_id || '') !== String(userFilter)) return false;
    if (favoriteOnly && !isHistoryFavorited(item && item.id)) return false;
    if (!query) return true;
    var haystack = [
      item.filename || '',
      item.workflow || '',
      item.username || '',
      item.prompt || '',
      item.prompt_preview || '',
      item.time || ''
    ].join(' ').toLowerCase();
    return haystack.indexOf(query) >= 0;
  }

  function _historyWorkflowDisplayName(item) {
    var workflow = item && item.workflow ? String(item.workflow) : '';
    var meta = (A._wfMeta || {})[workflow] || {};
    if (window.CW && CW.workflowDisplayName) {
      return CW.workflowDisplayName(workflow, meta) || '未命名工作流';
    }
    var custom = String(meta.name || '').trim();
    return custom || workflow.replace(/\.json$/i, '') || '未命名工作流';
  }

  function _historyUsername(item) {
    var uid = item && item.user_id ? String(item.user_id) : '';
    if (item && item.username) return String(item.username);
    if (_currentUser && String(_currentUser.id || _currentUser.sub || '') === uid) {
      return _currentUser.username || '';
    }
    var matched = (_usersCache || []).find(function(u) { return String(u.id) === uid; });
    return matched ? (matched.username || '') : '';
  }

  function _historyUserOptions(items) {
    var seen = {};
    var list = [];
    (items || []).forEach(function(item) {
      var uid = String(item.user_id || '');
      if (!uid || seen[uid]) return;
      seen[uid] = true;
      var username = _historyUsername(item);
      list.push({
        id: uid,
        username: username || '',
        label: username ? (username + '（' + uid + '）') : uid
      });
    });
    return list.sort(function(a, b) {
      return a.label.localeCompare(b.label, 'zh');
    });
  }

  function filterHistoryByUser(uid) {
    _historyFilters.user = uid ? String(uid) : '';
    if (_accountActiveTab !== 'history' && _accountActiveTab !== 'trash') _setAccountTab('history');
    _renderHistoryFromCache();
    requestAnimationFrame(function() {
      var userSelect = $('#historyUserFilter');
      if (userSelect) userSelect.value = _historyFilters.user;
    });
  }

  async function _hydrateHistoryDetail(item) {
    if (!item || !item.id) return item;
    if (!item.__compact && item.prompt && item.field_values) return item;
    var detail = null;
    if (window.CW && typeof window.CW.getHistoryDetail === 'function') {
      detail = await window.CW.getHistoryDetail(item);
    } else {
      var r = await apiFetch(_withCacheBust(API + '/api/history/' + encodeURIComponent(item.id)), { cache: 'no-store' });
      if (!r.ok) return item;
      var d = await r.json();
      detail = d && d.data;
    }
    if (!detail || !detail.id) return item;
    for (var i = 0; i < _historyCache.length; i++) {
      if (String(_historyCache[i] && _historyCache[i].id) === String(detail.id)) {
        _historyCache[i] = Object.assign({}, _historyCache[i], detail, { __compact: false });
        return _historyCache[i];
      }
    }
    return detail;
  }

  async function toggleHistoryPrompt(id) {
    if (!id) return;
    var nextOpen = !_expandedHistoryPrompts[id];
    _expandedHistoryPrompts[id] = nextOpen;
    if (_accountActiveTab === 'history' || _accountActiveTab === 'trash') _renderHistoryFromCache();
    if (!nextOpen) return;
    var item = _findHistoryItem(id);
    if (!item || !item.__compact) return;
    try {
      await _hydrateHistoryDetail(item);
      if (_expandedHistoryPrompts[id] && (_accountActiveTab === 'history' || _accountActiveTab === 'trash')) _renderHistoryFromCache();
    } catch (e) {
      _safeToast(e && e.message ? e.message : '加载提示词失败', 'error');
    }
  }

  function _historyPromptText(item) {
    return String((item && (item.prompt || item.prompt_preview)) || '未记录提示词');
  }

  function _historyPromptDisplayText(item) {
    var content = _historyPromptText(item);
    try {
      var trimmed = content.trim();
      if (trimmed && (trimmed[0] === '{' || trimmed[0] === '[')) {
        return JSON.stringify(JSON.parse(trimmed), null, 2);
      }
    } catch (e) {}
    return content;
  }

  function copyHistoryPrompt(text) {
    var content = String(text || '').trim();
    if (!content) return _safeToast('没有可复制的提示词', 'info');
    var write = navigator.clipboard && navigator.clipboard.writeText
      ? navigator.clipboard.writeText(content)
      : Promise.reject(new Error('clipboard unavailable'));
    write.then(function() {
      _safeToast('提示词已复制', 'done');
    }).catch(function() {
      var ta = null;
      try {
        ta = document.createElement('textarea');
        ta.value = content;
        ta.setAttribute('readonly', 'readonly');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        ta.style.pointerEvents = 'none';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        _safeToast('提示词已复制', 'done');
      } catch (e) {
        _safeToast('复制失败，请手动复制', 'error');
      } finally {
        if (ta && ta.parentNode) ta.parentNode.removeChild(ta);
      }
    });
  }

  async function copyHistoryPromptById(id) {
    var item = _findHistoryItem(id);
    if (!item) return _safeToast('未找到这条出图记录', 'info');
    if (item.__compact) {
      try {
        item = await _hydrateHistoryDetail(item);
      } catch (e) {
        return _safeToast(e && e.message ? e.message : '加载提示词失败', 'error');
      }
    }
    copyHistoryPrompt(_historyPromptText(item));
  }

  function _historyFavoriteKey(item) {
    if (!item) return '';
    return String(item.id || item.filename || item.original || item.prompt || '');
  }

  function _findHistoryItem(id, fallbackItem) {
    if (fallbackItem) return fallbackItem;
    var item = (_historyCache || []).find(function(entry) { return String(entry.id) === String(id); });
    if (item) return item;
    var appItems = window.__APP__ && window.__APP__.historyItems;
    if (Array.isArray(appItems)) {
      item = appItems.find(function(entry) { return String(entry.id) === String(id); });
      if (item) return item;
    }
    return null;
  }

  function isHistoryFavorited(id, fallbackItem) {
    var item = _findHistoryItem(id, fallbackItem);
    var key = _historyFavoriteKey(item);
    return !!(key && _historyFavorites[key]);
  }

  function toggleHistoryFavorite(id, fallbackItem) {
    var item = _findHistoryItem(id, fallbackItem);
    if (!item) {
      CW.toast('未找到这条出图记录', 'info');
      return;
    }
    var key = _historyFavoriteKey(item);
    if (!key) {
      CW.toast('当前图片暂不支持收藏', 'info');
      return;
    }
    _historyFavorites[key] = !_historyFavorites[key];
    _saveHistoryFavorites();
    _syncHistoryFavoriteUi(item, _historyFavorites[key]);
    CW.toast(_historyFavorites[key] ? '已收藏' : '已取消收藏', _historyFavorites[key] ? 'favorite' : 'unfavorite');
    return _historyFavorites[key];
  }

  function _setFavoriteButtonState(btn, isFavorited) {
    if (!btn) return;
    btn.classList.toggle('is-active', !!isFavorited);
    btn.title = isFavorited ? '取消收藏' : '收藏';
    btn.setAttribute('aria-label', isFavorited ? '取消收藏' : '收藏');
    var svg = btn.querySelector('svg');
    if (svg) svg.setAttribute('fill', isFavorited ? 'currentColor' : 'none');
    if (btn.classList.contains('account-hist-favorite-btn')) {
      Array.from(btn.childNodes).forEach(function(node) {
        if (node.nodeType === Node.TEXT_NODE) node.remove();
      });
      btn.appendChild(document.createTextNode(isFavorited ? ' 已收藏' : ' 收藏'));
    }
  }

  function _syncHistoryFavoriteUi(item, isFavorited) {
    var ids = [item && item.id, item && item.filename, item && item.thumb]
      .filter(Boolean)
      .map(String);
    var cards = [];
    ids.forEach(function(id) {
      document.querySelectorAll('[data-hist-id="' + CSS.escape(id) + '"]').forEach(function(card) {
        if (cards.indexOf(card) < 0) cards.push(card);
      });
    });
    cards.forEach(function(card) {
      card.dataset.favorited = isFavorited ? '1' : '0';
      _setFavoriteButtonState(card.querySelector('.gi-fav-btn'), isFavorited);
    });
    document.querySelectorAll('.account-hist-favorite-btn').forEach(function(btn) {
      var onClick = btn.getAttribute('onclick') || '';
      if (!ids.some(function(id) { return onClick.indexOf(id) !== -1; })) return;
      _setFavoriteButtonState(btn, isFavorited);
    });
  }

  function _renderHistoryFromCache() {
    var body = $('#accountBody');
    if (!body) return;
    var items = _historyCache || [];
    var filtered = items.filter(_matchHistoryFilter);
    var isAdmin = _currentUser && _currentUser.role === 'admin';
    var trashMode = !!_historyFilters.trash;
    var hiddenMode = !!_historyFilters.hidden;
    var activeTotal = items.filter(function(item) {
      var isDeleted = !!(item && (item.is_deleted || item.deleted_at));
      var isHidden = !!(item && item.is_hidden);
      return isDeleted === trashMode && (trashMode || isHidden === hiddenMode);
    }).length;
    var rows = filtered.map(function(h) {
      var imageUrl = API + '/api/images/' + h.filename;
      var thumbUrl = API + '/api/thumbs/' + (h.thumb || h.filename);
      var promptDisplayText = _historyPromptDisplayText(h);
      var workflowName = _historyWorkflowDisplayName(h);
      var ownerName = _historyUsername(h);
      var ownerLabel = ownerName
        ? (ownerName + (h.user_id ? '（' + h.user_id + '）' : ''))
        : (h.user_id || '未知用户');
      var promptOpen = !!_expandedHistoryPrompts[h.id];
      var favoriteKey = _historyFavoriteKey(h);
      var isFavorited = !!(favoriteKey && _historyFavorites[favoriteKey]);
      var canDeleteItem = _canDeleteHistoryItem(h);
      var hiddenBadge = h.is_hidden
        ? '<span class="account-hidden-badge">' + (window.CW && CW.icon ? CW.icon('eye-off', 13) : '') + ' 已隐藏' + (h.hidden_at ? '：' + escH(h.hidden_at) : '') + '</span>'
        : '';
      var deletedBadge = h.is_deleted || h.deleted_at
        ? '<span class="account-deleted-badge">' + (window.CW && CW.icon ? CW.icon('trash-2', 13) : '') + ' 已删除' + (h.deleted_at ? '：' + escH(h.deleted_at) : '') + '</span>'
        : '';
      var actionHtml = trashMode
        ? '<button class="wf-mgr-btn account-action-btn" type="button" title="恢复图片" onclick="event.stopPropagation();CW.auth.restoreHistoryItem(\'' + escA(h.id) + '\')">' + (window.CW && CW.icon ? CW.icon('refresh-cw') : '') + ' 恢复</button>' +
          '<button class="wf-mgr-btn account-action-btn btn-delete" type="button" title="彻底删除" onclick="event.stopPropagation();CW.auth.permanentDeleteHistoryItem(\'' + escA(h.id) + '\')">' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' 彻底删除</button>'
        : hiddenMode
          ? '<button class="wf-mgr-btn account-action-btn" type="button" title="取消隐藏" onclick="event.stopPropagation();CW.auth.toggleHistoryHidden(\'' + escA(h.id) + '\', false)">' + (window.CW && CW.icon ? CW.icon('eye') : '') + ' 取消隐藏</button>' +
            '<a class="wf-mgr-btn account-action-btn" href="' + escA(API + '/api/images/' + h.filename) + '" download>' + (window.CW && CW.icon ? CW.icon('download') : '') + ' 下载</a>' +
            (canDeleteItem ? '<button class="account-hist-quick-delete" type="button" title="删除" aria-label="删除" onclick="event.stopPropagation();CW.auth.deleteHistoryItem(\'' + escA(h.id) + '\')">' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + '</button>' : '')
        : '<button class="wf-mgr-btn account-action-btn account-hist-favorite-btn' + (isFavorited ? ' is-active' : '') + '" type="button" title="' + (isFavorited ? '取消收藏' : '收藏') + '" aria-label="' + (isFavorited ? '取消收藏' : '收藏') + '" onclick="event.stopPropagation();CW.auth.toggleHistoryFavorite(\'' + escA(h.id) + '\')">' +
            '<svg class="cw-icon" width="14" height="14" viewBox="0 0 24 24" fill="' + (isFavorited ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 20.2-.7-.63C6.2 14.96 3 12.03 3 8.43 3 5.5 5.24 3.2 8.1 3.2c1.62 0 3.18.78 4.1 2 0 0 .02.03.04.05.92-1.27 2.5-2.05 4.16-2.05C19.26 3.2 21.5 5.5 21.5 8.43c0 3.6-3.2 6.53-8.3 11.14l-.7.63Z"/></svg>' +
            (isFavorited ? ' 已收藏' : ' 收藏') +
          '</button>' +
          '<button class="wf-mgr-btn account-action-btn" type="button" title="隐藏" onclick="event.stopPropagation();CW.auth.toggleHistoryHidden(\'' + escA(h.id) + '\', true)">' + (window.CW && CW.icon ? CW.icon('eye-off') : '') + ' 隐藏</button>' +
          '<button class="wf-mgr-btn account-action-btn share-state-btn ' + (h.is_public ? 'is-shared' : 'is-private') + '" type="button" title="' + (h.is_public ? '点击取消共享' : '点击设为共享') + '" onclick="CW.auth.toggleShare(\'' + escA(h.id) + '\',' + (!h.is_public) + ')">' + (window.CW && CW.icon ? CW.icon('share') : '') + (h.is_public ? ' 已共享' : ' 未共享') + '</button>' +
          '<a class="wf-mgr-btn account-action-btn" href="' + escA(API + '/api/images/' + h.filename) + '" download>' + (window.CW && CW.icon ? CW.icon('download') : '') + ' 下载</a>' +
          (canDeleteItem ? '<button class="account-hist-quick-delete" type="button" title="删除" aria-label="删除" onclick="event.stopPropagation();CW.auth.deleteHistoryItem(\'' + escA(h.id) + '\')">' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + '</button>' : '');
      return '<div class="account-hist-row' + (isAdmin ? ' is-admin' : '') + (trashMode ? ' is-deleted' : '') + '">' +
        (trashMode ? '' : '<input type="checkbox" class="hist-select" value="' + escA(h.id) + '">') +
        '<div class="account-hist-preview">' +
          '<button class="account-hist-thumb" type="button" title="悬停查看缩略预览，点击打开原图" onmouseenter="CW.auth.showHistoryHoverPreview(\'' + escA(thumbUrl) + '\', this)" onmouseleave="CW.auth.hideHistoryHoverPreview()" onclick="window.open(\'' + escA(imageUrl) + '\', \'_blank\', \'noopener\')">' +
            '<img src="' + escA(thumbUrl) + '" alt="' + escA(h.filename || '') + '">' +
          '</button>' +
        '</div>' +
        '<div class="account-hist-meta">' +
          (isAdmin
            ? '<div class="account-hist-admin-meta"><span>用户：<button class="account-inline-link" type="button" onclick="CW.auth.filterHistoryByUser(\'' + escA(h.user_id || '') + '\')">' + escH(ownerLabel) + '</button></span><span>时间：' + escH(h.time || '-') + '</span><span>工作流文件：' + escH(workflowName) + '（' + escH(h.workflow || '-') + '）</span><span>文件名：' + escH(h.filename || '-') + '</span></div>'
            : '<strong>' + escH(workflowName) + '</strong><span>文件名：' + escH(h.filename || '-') + '</span><span>时间：' + escH(h.time || '-') + '</span>') +
          deletedBadge +
          hiddenBadge +
          '<div class="account-hist-prompt-block">' +
            '<button class="account-hist-prompt-toggle" type="button" onclick="event.stopPropagation();CW.auth.toggleHistoryPrompt(\'' + escA(h.id) + '\')">' + (promptOpen ? '隐藏提示词' : '显示提示词') + '</button>' +
            (promptOpen ? '<div class="account-hist-prompt-panel"><button class="account-hist-copy-btn" type="button" title="复制提示词" aria-label="复制提示词" onclick="event.stopPropagation();CW.auth.copyHistoryPromptById(\'' + escA(h.id) + '\')">' + (window.CW && CW.icon ? CW.icon('copy', 14) : '复制') + '</button><pre class="account-hist-prompt-text">' + escH(promptDisplayText) + '</pre></div>' : '') +
          '</div>' +
        '</div>' +
        '<div class="account-hist-actions">' +
          actionHtml +
        '</div>' +
      '</div>';
    }).join('');
    body.innerHTML =
      '<div class="account-section">' +
        '<div class="account-panel-head">' +
          '<strong>' + (trashMode ? '回收站' : (isAdmin ? '全部出图历史' : '出图历史')) + '</strong>' +
          '<span>' + (trashMode ? '已删除的图片记录会保留在这里，可恢复或彻底清理。' : (hiddenMode ? '隐藏后的图片和视频不会出现在首页，只在这里管理。' : (isAdmin ? '管理员可查看和管理所有用户及公开图库中的出图记录。' : '管理你生成过的内容，支持筛选、分享、下载和批量清理。'))) + '</span>' +
        '</div>' +
        '<div class="account-list-card">' +
          '<div class="account-history-toolbar">' +
            '<input class="auth-input account-history-search" id="historySearchInput" placeholder="筛选文件名、工作流、用户、提示词" value="' + escA(_historyFilters.query) + '">' +
            (isAdmin ? '<select class="user-role account-history-user-filter" id="historyUserFilter"><option value="">全部用户</option>' + _historyUserOptions(items).map(function(u) { return '<option value="' + escA(u.id) + '"' + (_historyFilters.user === u.id ? ' selected' : '') + '>' + escH(u.label) + '</option>'; }).join('') + '</select>' : '') +
            '<div class="account-history-filter-segments" aria-label="历史筛选">' +
              '<div class="account-history-share-filter-group" role="group" aria-label="分享状态筛选">' +
                '<button class="account-history-filter-btn' + (_historyFilters.share === 'all' ? ' active' : '') + '" type="button" data-share-filter="all">全部</button>' +
                '<button class="account-history-filter-btn' + (_historyFilters.share === 'shared' ? ' active' : '') + '" type="button" data-share-filter="shared">已分享</button>' +
                '<button class="account-history-filter-btn' + (_historyFilters.share === 'private' ? ' active' : '') + '" type="button" data-share-filter="private">未分享</button>' +
              '</div>' +
              '<button class="account-history-filter-btn account-history-favorite-filter' + (_historyFilters.favorite ? ' active' : '') + '" type="button" data-favorite-filter="' + (_historyFilters.favorite ? 'on' : 'off') + '">已收藏</button>' +
              '<button class="account-history-filter-btn account-history-hidden-filter' + (_historyFilters.hidden ? ' active' : '') + '" type="button" data-hidden-filter="' + (_historyFilters.hidden ? 'on' : 'off') + '">已隐藏</button>' +
            '</div>' +
          '</div>' +
          '<div class="account-batch-actions">' +
            '<span class="account-history-count">显示 ' + escH(String(filtered.length)) + ' / ' + escH(String(activeTotal)) + ' 条</span>' +
            '<div class="account-batch-actions-right">' +
              (trashMode
                ? '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.restoreAllTrash()">' + (window.CW && CW.icon ? CW.icon('refresh-cw') : '') + ' 全部恢复</button><button class="wf-mgr-btn account-action-btn btn-delete" type="button" onclick="CW.auth.clearTrash()">' + (window.CW && CW.icon ? CW.icon('x-circle') : '') + ' 清空回收站</button>'
                : '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.downloadSelected()">' + (window.CW && CW.icon ? CW.icon('download') : '') + ' 批量下载</button><button class="wf-mgr-btn account-action-btn btn-delete" type="button" onclick="CW.auth.deleteSelected()">' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' 批量删除</button>') +
            '</div>' +
          '</div>' +
          (rows || '<div class="account-empty">没有符合筛选条件的出图记录</div>') +
        '</div>' +
      '</div>';
    var searchInput = $('#historySearchInput');
    if (searchInput) {
      searchInput.oninput = function() {
        _historyFilters.query = this.value || '';
        _renderHistoryFromCache();
      };
    }
    var userFilter = $('#historyUserFilter');
    if (userFilter) {
      userFilter.onchange = function() {
        _historyFilters.user = this.value || '';
        _renderHistoryFromCache();
      };
    }
    var shareBtns = $$('.account-history-filter-btn');
    for (var sbi = 0; sbi < shareBtns.length; sbi++) {
      shareBtns[sbi].onclick = function() {
        if (this.dataset.favoriteFilter) {
          _historyFilters.favorite = !_historyFilters.favorite;
        } else if (this.dataset.hiddenFilter) {
          _historyFilters.hidden = !_historyFilters.hidden;
        } else {
          _historyFilters.share = this.dataset.shareFilter || 'all';
        }
        _renderHistoryFromCache();
      };
    }
  }

  function _loadMyHistory() {
    var body = $('#accountBody');
    body.innerHTML = '<div class="account-loading">加载中...</div>';
    var scope = (_currentUser && _currentUser.role === 'admin') ? 'all' : 'mine';
    var limit = HISTORY_FETCH_LIMIT;
    Promise.all([
      apiFetch(_withCacheBust(API + '/api/history?scope=' + scope + '&limit=' + limit + '&compact=1'), { cache: 'no-store' }).then(function(r) { return r.json(); }),
      apiFetch(_withCacheBust(API + '/api/history?scope=hidden&limit=' + limit + '&compact=1'), { cache: 'no-store' }).then(function(r) { return r.json(); }),
      apiFetch(_withCacheBust(API + '/api/history?scope=trash&limit=' + limit + '&compact=1'), { cache: 'no-store' }).then(function(r) { return r.json(); })
    ]).then(function(results) {
      var normal = results[0] || {};
      var hidden = results[1] || {};
      var trash = results[2] || {};
      _historyCache = (normal.data || []).concat(hidden.data || [], trash.data || []);
      _renderHistoryFromCache();
    }).catch(function(e) { body.innerHTML = '<div class="account-error">' + escH(e.message) + '</div>'; });
  }

  function _syncMyHistory() {
    var scope = (_currentUser && _currentUser.role === 'admin') ? 'all' : 'mine';
    var limit = HISTORY_FETCH_LIMIT;
    return Promise.all([
      apiFetch(_withCacheBust(API + '/api/history?scope=' + scope + '&limit=' + limit + '&compact=1'), { cache: 'no-store' }).then(function(r) { return r.json(); }),
      apiFetch(_withCacheBust(API + '/api/history?scope=hidden&limit=' + limit + '&compact=1'), { cache: 'no-store' }).then(function(r) { return r.json(); }),
      apiFetch(_withCacheBust(API + '/api/history?scope=trash&limit=' + limit + '&compact=1'), { cache: 'no-store' }).then(function(r) { return r.json(); })
    ]).then(function(results) {
      var normal = results[0] || {};
      var hidden = results[1] || {};
      var trash = results[2] || {};
      if (!normal.ok) throw new Error(normal.detail || '加载失败');
      if (!hidden.ok) throw new Error(hidden.detail || '加载失败');
      if (!trash.ok) throw new Error(trash.detail || '加载失败');
      _historyCache = (normal.data || []).concat(hidden.data || [], trash.data || []);
      if (_accountActiveTab === 'history' || _accountActiveTab === 'trash') _renderHistoryFromCache();
      return _historyCache;
    }).catch(function(e) {
      console.warn('sync history failed:', e && e.message ? e.message : e);
      return _historyCache;
    });
  }

  function _safeToast(message, type) {
    if (window.CW && typeof window.CW.toast === 'function') window.CW.toast(message, type);
  }

  function _updateHistoryListShareState(list, id, makePublic) {
    if (!Array.isArray(list)) return false;
    var changed = false;
    for (var i = 0; i < list.length; i++) {
      if (String(list[i] && list[i].id) !== String(id)) continue;
      list[i] = Object.assign({}, list[i], { is_public: !!makePublic });
      changed = true;
    }
    return changed;
  }

  function _updateHistoryListHiddenState(list, id, makeHidden, hiddenAt) {
    if (!Array.isArray(list)) return false;
    var changed = false;
    for (var i = 0; i < list.length; i++) {
      if (String(list[i] && list[i].id) !== String(id)) continue;
      if (makeHidden) {
        list[i] = Object.assign({}, list[i], { is_hidden: true, hidden_at: hiddenAt || list[i].hidden_at || '' });
      } else {
        list[i] = Object.assign({}, list[i], { is_hidden: false, hidden_at: '', hidden_by: '' });
      }
      changed = true;
    }
    return changed;
  }

  function toggleShare(id, makePublic) {
    return apiFetch(API + '/api/history/' + encodeURIComponent(id) + '/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_public: makePublic })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '操作失败'); });
      return r.json();
    }).then(function() {
      _updateHistoryListShareState(_historyCache, id, makePublic);
      if (window.__APP__) {
        _updateHistoryListShareState(window.__APP__.historyItems, id, makePublic);
        _updateHistoryListShareState(window.__APP__._lbItems, id, makePublic);
      }
      _renderHistoryFromCache();
      _safeToast(makePublic ? '已分享到公共图库' : '已取消分享', 'done');
      return { id: id, is_public: !!makePublic };
    }).catch(function(e) {
      CW.toast(e.message, 'error');
      throw e;
    });
  }

  function toggleHistoryHidden(id, makeHidden) {
    makeHidden = makeHidden !== false;
    return apiFetch(API + '/api/history/' + encodeURIComponent(id) + '/hide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_hidden: makeHidden })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '操作失败'); });
      return r.json();
    }).then(function(d) {
      var hiddenAt = (d && d.hidden_at) || '';
      _updateHistoryListHiddenState(_historyCache, id, makeHidden, hiddenAt);
      if (window.__APP__) {
        _updateHistoryListHiddenState(window.__APP__._lbItems, id, makeHidden, hiddenAt);
        if (Array.isArray(window.__APP__.historyItems)) {
          if (makeHidden) {
            for (var i = window.__APP__.historyItems.length - 1; i >= 0; i--) {
              if (String(window.__APP__.historyItems[i] && window.__APP__.historyItems[i].id) === String(id)) {
                window.__APP__.historyItems.splice(i, 1);
              }
            }
          } else {
            _updateHistoryListHiddenState(window.__APP__.historyItems, id, makeHidden, hiddenAt);
          }
        }
      }
      _renderHistoryFromCache();
      _safeToast(makeHidden ? '已隐藏，首页不再显示' : '已取消隐藏', 'done');
      if (window.CW && typeof CW.loadHistory === 'function') CW.loadHistory();
      if (window.CW && typeof CW.loadWorkflows === 'function') CW.loadWorkflows();
      return { id: id, is_hidden: !!makeHidden, hidden_at: hiddenAt };
    }).catch(function(e) {
      CW.toast(e.message, 'error');
      throw e;
    });
  }

  function deleteSelected() {
    var ids = _selectedHistoryIds();
    if (!ids.length) return CW.toast('请选择记录', 'info');
    if (_historyFilters.trash) return permanentDeleteSelected();
    var allowed = (_historyCache || []).filter(function(item) {
      return ids.indexOf(String(item.id)) >= 0 && _canDeleteHistoryItem(item);
    }).map(function(item) { return String(item.id); });
    if (!allowed.length) return CW.toast('只能删除自己生成的内容', 'info');
    if (!confirm('确定删除选中的历史记录吗？')) return;
    apiFetch(API + '/api/history/batch-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: allowed })
    }).then(function(r) { return r.json(); }).then(function() {
      var deletedAt = new Date().toISOString().slice(0, 19).replace('T', ' ');
      _historyCache = (_historyCache || []).map(function(item) {
        if (allowed.indexOf(String(item.id)) < 0) return item;
        return Object.assign({}, item, { is_deleted: true, deleted_at: item.deleted_at || deletedAt });
      });
      CW.toast('已移入回收站', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    });
  }

  function deleteHistoryItem(id) {
    if (!id) return;
    var item = (_historyCache || []).find(function(entry) { return String(entry.id) === String(id); });
    if (item && !_canDeleteHistoryItem(item)) return CW.toast('只能删除自己生成的内容', 'info');
    apiFetch(API + '/api/history/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function(r) {
        if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '删除失败'); });
        return r.json();
      })
      .then(function(d) {
        var deletedAt = (d && d.deleted_at) || new Date().toISOString().slice(0, 19).replace('T', ' ');
        _historyCache = (_historyCache || []).map(function(entry) {
          if (String(entry.id) !== String(id)) return entry;
          return Object.assign({}, entry, { is_deleted: true, deleted_at: entry.deleted_at || deletedAt });
        });
        CW.toast('已移入回收站', 'done');
        _renderHistoryFromCache();
        _syncMyHistory();
        if (CW.loadHistory) CW.loadHistory();
      })
      .catch(function(e) { CW.toast(e.message || '删除失败', 'error'); });
  }

  function _postHistoryBatch(url, ids) {
    return apiFetch(API + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '操作失败'); });
      return r.json();
    });
  }

  function restoreSelected() {
    var ids = _selectedHistoryIds();
    if (!ids.length) return CW.toast('请选择记录', 'info');
    var allowed = (_historyCache || []).filter(function(item) {
      return ids.indexOf(String(item.id)) >= 0 && _canDeleteHistoryItem(item);
    }).map(function(item) { return String(item.id); });
    if (!allowed.length) return CW.toast('只能恢复自己生成的内容', 'info');
    _postHistoryBatch('/api/history/batch-restore', allowed).then(function() {
      _historyCache = (_historyCache || []).map(function(item) {
        if (allowed.indexOf(String(item.id)) < 0) return item;
        return Object.assign({}, item, { is_deleted: false, deleted_at: '', deleted_by: '' });
      });
      CW.toast('已恢复', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function restoreAllTrash() {
    var allowed = (_historyCache || []).filter(function(item) {
      return item && (item.is_deleted || item.deleted_at) && _matchHistoryFilter(item) && _canDeleteHistoryItem(item);
    }).map(function(item) { return String(item.id); });
    if (!allowed.length) return CW.toast('没有可恢复的记录', 'info');
    _postHistoryBatch('/api/history/batch-restore', allowed).then(function() {
      _historyCache = (_historyCache || []).map(function(item) {
        if (allowed.indexOf(String(item.id)) < 0) return item;
        return Object.assign({}, item, { is_deleted: false, deleted_at: '', deleted_by: '' });
      });
      CW.toast('已全部恢复', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function permanentDeleteSelected() {
    var ids = _selectedHistoryIds();
    if (!ids.length) return CW.toast('请选择记录', 'info');
    var allowed = (_historyCache || []).filter(function(item) {
      return ids.indexOf(String(item.id)) >= 0 && _canDeleteHistoryItem(item);
    }).map(function(item) { return String(item.id); });
    if (!allowed.length) return CW.toast('只能彻底删除自己生成的内容', 'info');
    if (!confirm('彻底删除后将无法恢复，确定继续吗？')) return;
    _postHistoryBatch('/api/history/batch-permanent-delete', allowed).then(function() {
      _historyCache = (_historyCache || []).filter(function(item) {
        return allowed.indexOf(String(item.id)) < 0;
      });
      CW.toast('已彻底删除', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function restoreHistoryItem(id) {
    if (!id) return;
    _postHistoryBatch('/api/history/batch-restore', [id]).then(function() {
      _historyCache = (_historyCache || []).map(function(item) {
        if (String(item.id) !== String(id)) return item;
        return Object.assign({}, item, { is_deleted: false, deleted_at: '', deleted_by: '' });
      });
      CW.toast('已恢复', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function permanentDeleteHistoryItem(id) {
    if (!id) return;
    if (!confirm('彻底删除后将无法恢复，确定继续吗？')) return;
    _postHistoryBatch('/api/history/batch-permanent-delete', [id]).then(function() {
      _historyCache = (_historyCache || []).filter(function(item) {
        return String(item.id) !== String(id);
      });
      CW.toast('已彻底删除', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function clearTrash() {
    if (!confirm('确定清空回收站吗？这会彻底删除其中的图片文件。')) return;
    apiFetch(API + '/api/history/trash/clear', { method: 'POST' }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '清空失败'); });
      return r.json();
    }).then(function() {
      _historyCache = (_historyCache || []).filter(function(item) {
        return !(item && (item.is_deleted || item.deleted_at));
      });
      CW.toast('回收站已清空', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  function downloadSelected() {
    var ids = _selectedHistoryIds();
    if (!ids.length) return CW.toast('请选择记录', 'info');
    apiFetch(API + '/api/history/batch-download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '下载失败'); });
      return r.blob();
    }).then(function(blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'ez-comfyui-history.zip';
      a.click();
      URL.revokeObjectURL(url);
    }).catch(function(e) { CW.toast(e.message, 'error'); });
  }

  window.CW = window.CW || {};
  window.CW.authReady = restoreSession();
  setTimeout(_updateUI, 100);
  window.CW.auth = {
    isLoggedIn: isLoggedIn,
    getCurrentUser: getCurrentUser,
    register: register,
    login: login,
    logout: logout,
    showLogin: showLogin,
    showRegister: showRegister,
    restoreSession: restoreSession,
    showAccount: showAccount,
    showAccountTab: showAccountTab,
    closeAccount: closeAccount,
    showSystemSettings: showSystemSettings,
    closeSystemSettings: closeSystemSettings,
    saveSystemSettings: saveSystemSettings,
    setSystemSettingsTab: setSystemSettingsTab,
    testLlmApiSettings: testLlmApiSettings,
    applySystemLlmProfile: applySystemLlmProfile,
    sendSiteNotification: sendSiteNotification,
    editSiteNotification: editSiteNotification,
    cancelEditSiteNotification: cancelEditSiteNotification,
    deleteSiteNotification: deleteSiteNotification,
    closeSiteNotification: _closeSiteNotification,
    nextSiteNotification: nextSiteNotification,
    muteSiteNotifications: muteSiteNotifications,
    jumpToUser: jumpToUser,
    createUser: createUser,
    saveUser: saveUser,
    toggleUserDisabled: toggleUserDisabled,
    deleteUser: deleteUser,
    toggleShare: toggleShare,
    toggleHistoryHidden: toggleHistoryHidden,
    filterHistoryByUser: filterHistoryByUser,
    toggleHistoryPrompt: toggleHistoryPrompt,
    toggleHistoryFavorite: toggleHistoryFavorite,
    isHistoryFavorited: isHistoryFavorited,
    copyHistoryPrompt: copyHistoryPrompt,
    copyHistoryPromptById: copyHistoryPromptById,
    deleteHistoryItem: deleteHistoryItem,
    deleteSelected: deleteSelected,
    restoreSelected: restoreSelected,
    restoreAllTrash: restoreAllTrash,
    permanentDeleteSelected: permanentDeleteSelected,
    restoreHistoryItem: restoreHistoryItem,
    permanentDeleteHistoryItem: permanentDeleteHistoryItem,
    clearTrash: clearTrash,
    getHistoryActionState: getHistoryActionState,
    canDeleteHistoryItem: _canDeleteHistoryItem,
    downloadSelected: downloadSelected,
    showHistoryHoverPreview: _showHistoryHoverPreview,
    hideHistoryHoverPreview: _hideHistoryHoverPreview,
    getAuthHeaders: getAuthHeaders,
    apiFetch: apiFetch,
    toggleDropdown: _toggleDropdown
  };

  if (!window.__EZ_AUTH_FETCH_PATCHED__) {
    window.__EZ_AUTH_FETCH_PATCHED__ = true;
    var _nativeFetch = window.fetch.bind(window);
    window.fetch = function(input, opts) {
      opts = opts || {};
      var url = (typeof input === 'string') ? input : (input && input.url) || '';
      var shouldAttach = false;
      var shouldBypassCache = false;
      try {
        var u = new URL(url, window.location.href);
        var apiUrl = new URL(API || '/', window.location.href);
        var apiPath = apiUrl.pathname.replace(/\/+$/, '');
        shouldAttach = u.origin === apiUrl.origin && u.pathname.indexOf(apiPath + '/api/') === 0;
        shouldBypassCache = shouldAttach && ((opts.method || 'GET').toUpperCase() === 'GET');
        if (shouldBypassCache) {
          u.searchParams.set('_ts', String(Date.now()));
          url = u.toString();
          if (typeof input === 'string') input = url;
          opts.cache = 'no-store';
        }
      } catch (e) {}
      if (shouldAttach) {
        opts.headers = Object.assign({}, opts.headers || {}, getAuthHeaders());
        if (!opts.credentials) opts.credentials = 'include';
        opts = _attachCsrfHeader(opts);
        if (shouldBypassCache) {
          opts.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
          opts.headers.Pragma = 'no-cache';
        }
      }
      return _nativeFetch(input, opts);
    };
  }
})();
