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
    favorite: false
  };
  var _historyHoverPreview = null;
  var _accountActiveTab = 'profile';
  var _usersCache = [];
  var _historyCache = [];
  var _expandedHistoryPrompts = {};
  var _historyFavorites = {};

  function _getToken() { return localStorage.getItem('v4_token'); }
  function _setToken(t) { localStorage.setItem('v4_token', t); }
  function _clearToken() { localStorage.removeItem('v4_token'); }
  function isLoggedIn() { return !!_getToken(); }
  function getCurrentUser() { return _currentUser; }

  function getAuthHeaders() {
    var token = _getToken();
    return token ? { Authorization: 'Bearer ' + token } : {};
  }

  function apiFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {}, getAuthHeaders());
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
    if (data && data.token) {
      _setToken(data.token);
      return fetch(API + '/auth/me', {
        headers: { 'Authorization': 'Bearer ' + data.token }
      }).then(function(r) {
        if (!r.ok) throw new Error('auth/me failed');
        return r.json();
      }).then(function(user) {
        _currentUser = user || data;
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
          return _currentUser;
        });
      }).catch(function() {
        _currentUser = data;
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
    _clearToken();
    _currentUser = null;
    _closeDropdown();
    _updateUI();
    if (window.CW && CW.refreshForAuthChange) CW.refreshForAuthChange();
    CW.toast('已退出', 'info');
  }

  function restoreSession() {
    var token = _getToken();
    if (!token) { _updateUI(); return Promise.resolve(null); }
    return fetch(API + '/auth/me', {
      headers: { 'Authorization': 'Bearer ' + token }
    }).then(function(r) {
      if (!r.ok) throw new Error('Session expired');
      return r.json();
    }).then(function(user) {
      _currentUser = user;
      return Promise.resolve(
        window.CW && typeof window.CW.loadLoggedInModules === 'function'
          ? window.CW.loadLoggedInModules(user)
          : null
      ).catch(function() {
        return null;
      }).then(function() {
        _updateUI();
        if (window.CW && CW.refreshForAuthChange) CW.refreshForAuthChange();
        return user;
      });
    }).catch(function() {
      _clearToken();
      _updateUI();
      if (window.CW && CW.refreshForAuthChange) CW.refreshForAuthChange();
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
            '<button class="auth-dropdown-item" type="button" onclick="CW.auth.showAccount()">' + (window.CW && CW.icon ? CW.icon('user-round-pen') : '') + '账户管理</button>' +
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
    setTimeout(function() { $('#authUsername').focus(); }, 100);
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

  function showAccount() {
    _closeDropdown();
    var old = $('#accountModalOverlay');
    if (old) old.remove();
    var html = '<div class="auth-modal-overlay" id="accountModalOverlay" onclick="if(event.target===this)CW.auth.closeAccount()">' +
      '<div class="account-modal">' +
      '<div class="auth-modal-header"><span class="auth-modal-title">' + (window.CW && CW.icon ? CW.icon('user-round-pen', 18) : '') + '账户管理</span>' +
      '<button class="auth-modal-close" type="button" onclick="CW.auth.closeAccount()">×</button></div>' +
      '<div class="account-tabs">' +
      '<button class="account-tab active" data-tab="profile">我的账户</button>' +
      '<button class="account-tab" data-tab="history">出图历史</button>' +
      (_currentUser && _currentUser.role === 'admin' ? '<button class="account-tab" data-tab="users">所有用户</button>' : '') +
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
    _renderAccountTab('profile');
  }

  function closeAccount() {
    var el = $('#accountModalOverlay');
    if (!el) return;
    if (window.CW && CW.setModalOpen) CW.setModalOpen(el, false, { removeAfterClose: true });
    else el.remove();
  }

  function _renderAccountTab(tab) {
    _accountActiveTab = tab || 'profile';
    if (tab === 'users') return _loadUsers();
    if (tab === 'history') return _loadMyHistory();
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
          '<strong>所有用户</strong>' +
          '<span>管理员可以在这里新建、调整、禁用或删除平台用户。</span>' +
        '</div>' +
        '<div class="account-create-user">' +
          '<strong>新建用户</strong>' +
          '<div class="account-create-grid">' +
            '<input class="auth-input" id="newUserName" placeholder="用户名">' +
            '<input class="auth-input" id="newUserPassword" type="password" placeholder="默认 admin">' +
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
    _accountActiveTab = tab || 'profile';
    $$('#accountModalOverlay .account-tab').forEach(function(x) {
      x.classList.toggle('active', x.dataset.tab === _accountActiveTab);
    });
    _renderAccountTab(_accountActiveTab);
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
    return apiFetch(_withCacheBust(API + '/api/history?scope=all&limit=5000'), { cache: 'no-store' }).then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '加载失败'); });
      return r.json();
    }).then(function(d) {
      var counts = {};
      (d.data || []).forEach(function(item) {
        var uid = String(item.user_id || '');
        if (!uid) return;
        counts[uid] = (counts[uid] || 0) + 1;
      });
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
    var password = ($('#newUserPassword') && $('#newUserPassword').value) || 'admin';
    var role = ($('#newUserRole') && $('#newUserRole').value) || 'user';
    if (!username) return CW.toast('请输入用户名', 'info');
    apiFetch(API + '/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, password: password || 'admin', role: role })
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
    return meta.name || workflow.replace('.json', '') || '未命名工作流';
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
    if (_accountActiveTab !== 'history') _setAccountTab('history');
    _renderHistoryFromCache();
    requestAnimationFrame(function() {
      var userSelect = $('#historyUserFilter');
      if (userSelect) userSelect.value = _historyFilters.user;
    });
  }

  function toggleHistoryPrompt(id) {
    if (!id) return;
    _expandedHistoryPrompts[id] = !_expandedHistoryPrompts[id];
    if (_accountActiveTab === 'history') _renderHistoryFromCache();
  }

  function copyHistoryPrompt(text) {
    var content = String(text || '').trim();
    if (!content) return CW.toast('没有可复制的提示词', 'info');
    var write = navigator.clipboard && navigator.clipboard.writeText
      ? navigator.clipboard.writeText(content)
      : Promise.reject(new Error('clipboard unavailable'));
    write.then(function() {
      CW.toast('提示词已复制', 'done');
    }).catch(function() {
      try {
        var ta = document.createElement('textarea');
        ta.value = content;
        ta.setAttribute('readonly', 'readonly');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        CW.toast('提示词已复制', 'done');
      } catch (e) {
        CW.toast('复制失败，请手动复制', 'error');
      }
    });
  }

  function _historyFavoriteKey(item) {
    if (!item) return '';
    return String(item.id || item.filename || item.original || item.prompt || '');
  }

  function isHistoryFavorited(id) {
    var item = (_historyCache || []).find(function(entry) { return String(entry.id) === String(id); });
    var key = _historyFavoriteKey(item);
    return !!(key && _historyFavorites[key]);
  }

  function toggleHistoryFavorite(id) {
    var item = (_historyCache || []).find(function(entry) { return String(entry.id) === String(id); });
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
    if (_accountActiveTab === 'history') _renderHistoryFromCache();
    CW.toast(_historyFavorites[key] ? '已收藏' : '已取消收藏', 'done');
  }

  function _renderHistoryFromCache() {
    var body = $('#accountBody');
    if (!body) return;
    var items = _historyCache || [];
    var filtered = items.filter(_matchHistoryFilter);
    var isAdmin = _currentUser && _currentUser.role === 'admin';
    var rows = filtered.map(function(h) {
      var imageUrl = API + '/api/images/' + h.filename;
      var thumbUrl = API + '/api/thumbs/' + (h.thumb || h.filename);
      var promptText = h.prompt || h.prompt_preview || '未记录提示词';
      var workflowName = _historyWorkflowDisplayName(h);
      var ownerName = _historyUsername(h);
      var ownerLabel = ownerName
        ? (ownerName + (h.user_id ? '（' + h.user_id + '）' : ''))
        : (h.user_id || '未知用户');
      var promptOpen = !!_expandedHistoryPrompts[h.id];
      var favoriteKey = _historyFavoriteKey(h);
      var isFavorited = !!(favoriteKey && _historyFavorites[favoriteKey]);
      return '<div class="account-hist-row' + (isAdmin ? ' is-admin' : '') + '">' +
        '<input type="checkbox" class="hist-select" value="' + escA(h.id) + '">' +
        '<div class="account-hist-preview">' +
          '<button class="account-hist-thumb" type="button" title="悬停查看完整预览，点击打开原图" onmouseenter="CW.auth.showHistoryHoverPreview(\'' + escA(imageUrl) + '\', this)" onmouseleave="CW.auth.hideHistoryHoverPreview()" onclick="window.open(\'' + escA(imageUrl) + '\', \'_blank\', \'noopener\')">' +
            '<img src="' + escA(thumbUrl) + '" alt="' + escA(h.filename || '') + '">' +
          '</button>' +
          '<button class="account-hist-favorite-btn' + (isFavorited ? ' is-active' : '') + '" type="button" title="' + (isFavorited ? '取消收藏' : '收藏') + '" onclick="event.stopPropagation();CW.auth.toggleHistoryFavorite(\'' + escA(h.id) + '\')">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="' + (isFavorited ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 20.2-.7-.63C6.2 14.96 3 12.03 3 8.43 3 5.5 5.24 3.2 8.1 3.2c1.62 0 3.18.78 4.1 2 0 0 .02.03.04.05.92-1.27 2.5-2.05 4.16-2.05C19.26 3.2 21.5 5.5 21.5 8.43c0 3.6-3.2 6.53-8.3 11.14l-.7.63Z"/></svg>' +
          '</button>' +
        '</div>' +
        '<div class="account-hist-meta">' +
          (isAdmin
            ? '<div class="account-hist-admin-meta"><span>用户：<button class="account-inline-link" type="button" onclick="CW.auth.filterHistoryByUser(\'' + escA(h.user_id || '') + '\')">' + escH(ownerLabel) + '</button></span><span>时间：' + escH(h.time || '-') + '</span><span>工作流文件：' + escH(workflowName) + '（' + escH(h.workflow || '-') + '）</span><span>文件名：' + escH(h.filename || '-') + '</span></div>'
            : '<strong>' + escH(workflowName) + '</strong><span>文件名：' + escH(h.filename || '-') + '</span><span>时间：' + escH(h.time || '-') + '</span>') +
          '<div class="account-hist-prompt-block">' +
            '<button class="account-hist-prompt-toggle" type="button" onclick="CW.auth.toggleHistoryPrompt(\'' + escA(h.id) + '\')">' + (promptOpen ? '隐藏提示词' : '显示提示词') + '</button>' +
            (promptOpen ? '<div class="account-hist-prompt-panel"><button class="account-hist-copy-btn" type="button" title="复制提示词" onclick="CW.auth.copyHistoryPrompt(' + JSON.stringify(promptText) + ')">' + (window.CW && CW.icon ? CW.icon('copy', 14) : '复制') + '</button><p class="is-full">' + escH(promptText) + '</p></div>' : '') +
          '</div>' +
        '</div>' +
        '<div class="account-hist-actions">' +
          '<button class="wf-mgr-btn account-action-btn share-state-btn ' + (h.is_public ? 'is-shared' : 'is-private') + '" type="button" title="' + (h.is_public ? '点击取消共享' : '点击设为共享') + '" onclick="CW.auth.toggleShare(\'' + escA(h.id) + '\',' + (!h.is_public) + ')">' + (window.CW && CW.icon ? CW.icon('share') : '') + (h.is_public ? ' 已共享' : ' 未共享') + '</button>' +
          '<a class="wf-mgr-btn account-action-btn" href="' + escA(API + '/api/images/' + h.filename) + '" download>下载</a>' +
        '</div>' +
      '</div>';
    }).join('');
    body.innerHTML =
      '<div class="account-section">' +
        '<div class="account-panel-head">' +
          '<strong>' + (isAdmin ? '全部出图历史' : '出图历史') + '</strong>' +
          '<span>' + (isAdmin ? '管理员可查看和管理所有用户及公开图库中的出图记录。' : '管理你生成过的内容，支持筛选、分享、下载和批量清理。') + '</span>' +
        '</div>' +
        '<div class="account-list-card">' +
          '<div class="account-history-toolbar">' +
            '<input class="auth-input account-history-search" id="historySearchInput" placeholder="筛选文件名、工作流、用户、提示词" value="' + escA(_historyFilters.query) + '">' +
            (isAdmin ? '<select class="user-role account-history-user-filter" id="historyUserFilter"><option value="">全部用户</option>' + _historyUserOptions(items).map(function(u) { return '<option value="' + escA(u.id) + '"' + (_historyFilters.user === u.id ? ' selected' : '') + '>' + escH(u.label) + '</option>'; }).join('') + '</select>' : '') +
            '<div class="account-history-filter-segments" role="group" aria-label="分享状态筛选">' +
              '<button class="account-history-filter-btn' + (_historyFilters.share === 'all' ? ' active' : '') + '" type="button" data-share-filter="all">全部</button>' +
              '<button class="account-history-filter-btn' + (_historyFilters.share === 'shared' ? ' active' : '') + '" type="button" data-share-filter="shared">已分享</button>' +
              '<button class="account-history-filter-btn' + (_historyFilters.share === 'private' ? ' active' : '') + '" type="button" data-share-filter="private">未分享</button>' +
              '<button class="account-history-filter-btn account-history-favorite-filter' + (_historyFilters.favorite ? ' active' : '') + '" type="button" data-favorite-filter="' + (_historyFilters.favorite ? 'on' : 'off') + '"><svg width="14" height="14" viewBox="0 0 24 24" fill="' + (_historyFilters.favorite ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="m12 20.2-.7-.63C6.2 14.96 3 12.03 3 8.43 3 5.5 5.24 3.2 8.1 3.2c1.62 0 3.18.78 4.1 2 0 0 .02.03.04.05.92-1.27 2.5-2.05 4.16-2.05C19.26 3.2 21.5 5.5 21.5 8.43c0 3.6-3.2 6.53-8.3 11.14l-.7.63Z"/></svg>收藏</button>' +
            '</div>' +
          '</div>' +
          '<div class="account-batch-actions">' +
            '<span class="account-history-count">显示 ' + escH(String(filtered.length)) + ' / ' + escH(String(items.length)) + ' 条</span>' +
            '<div class="account-batch-actions-right">' +
              '<button class="wf-mgr-btn account-action-btn" type="button" onclick="CW.auth.downloadSelected()">批量下载</button>' +
              '<button class="wf-mgr-btn account-action-btn btn-delete" type="button" onclick="CW.auth.deleteSelected()">批量删除</button>' +
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
    var limit = (_currentUser && _currentUser.role === 'admin') ? 500 : 100;
    apiFetch(_withCacheBust(API + '/api/history?scope=' + scope + '&limit=' + limit), { cache: 'no-store' }).then(function(r) { return r.json(); }).then(function(d) {
      _historyCache = (d.data || []).slice();
      _renderHistoryFromCache();
    }).catch(function(e) { body.innerHTML = '<div class="account-error">' + escH(e.message) + '</div>'; });
  }

  function _syncMyHistory() {
    var scope = (_currentUser && _currentUser.role === 'admin') ? 'all' : 'mine';
    var limit = (_currentUser && _currentUser.role === 'admin') ? 500 : 100;
    return apiFetch(_withCacheBust(API + '/api/history?scope=' + scope + '&limit=' + limit), { cache: 'no-store' }).then(function(r) {
      return r.json();
    }).then(function(d) {
      if (!d.ok) throw new Error(d.detail || '加载失败');
      _historyCache = (d.data || []).slice();
      if (_accountActiveTab === 'history') _renderHistoryFromCache();
      return _historyCache;
    }).catch(function(e) {
      console.warn('sync history failed:', e && e.message ? e.message : e);
      return _historyCache;
    });
  }

  function _safeToast(message, type) {
    if (window.CW && typeof window.CW.toast === 'function') window.CW.toast(message, type);
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
      _historyCache = (_historyCache || []).map(function(item) {
        if (item.id !== id) return item;
        return Object.assign({}, item, { is_public: !!makePublic });
      });
      if (window.__APP__ && Array.isArray(window.__APP__.historyItems)) {
        for (var hi = 0; hi < window.__APP__.historyItems.length; hi++) {
          if (window.__APP__.historyItems[hi].id === id) {
            window.__APP__.historyItems[hi] = Object.assign({}, window.__APP__.historyItems[hi], { is_public: !!makePublic });
            break;
          }
        }
      }
      _renderHistoryFromCache();
      _safeToast(makePublic ? '已分享到公共图库' : '已取消分享', 'done');
      if (CW.loadHistory) CW.loadHistory();
      return { id: id, is_public: !!makePublic };
    }).catch(function(e) {
      CW.toast(e.message, 'error');
      throw e;
    });
  }

  function deleteSelected() {
    var ids = _selectedHistoryIds();
    if (!ids.length) return CW.toast('请选择记录', 'info');
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
      _historyCache = (_historyCache || []).filter(function(item) {
        return allowed.indexOf(String(item.id)) < 0;
      });
      CW.toast('已删除', 'done');
      _renderHistoryFromCache();
      _syncMyHistory();
      if (CW.loadHistory) CW.loadHistory();
    });
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
    closeAccount: closeAccount,
    jumpToUser: jumpToUser,
    createUser: createUser,
    saveUser: saveUser,
    toggleUserDisabled: toggleUserDisabled,
    deleteUser: deleteUser,
    toggleShare: toggleShare,
    filterHistoryByUser: filterHistoryByUser,
    toggleHistoryPrompt: toggleHistoryPrompt,
    toggleHistoryFavorite: toggleHistoryFavorite,
    isHistoryFavorited: isHistoryFavorited,
    copyHistoryPrompt: copyHistoryPrompt,
    deleteSelected: deleteSelected,
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
        if (shouldBypassCache) {
          opts.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
          opts.headers.Pragma = 'no-cache';
        }
      }
      return _nativeFetch(input, opts);
    };
  }
})();
