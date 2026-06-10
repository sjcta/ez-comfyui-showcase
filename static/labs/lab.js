(function() {
  'use strict';

  var state = {
    projects: [],
    lock: { active: false },
    token: sessionStorage.getItem('ez_lab_resource_lock_token') || '',
    pollers: {}
  };
  var APP_BASE = location.pathname.replace(/\/labs(?:\/[^/]+)?\/?$/, '');
  if (APP_BASE === '/') APP_BASE = '';

  function appUrl(path) {
    return (APP_BASE || '') + path;
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function esc(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }
  function readCookie(name) {
    var prefix = encodeURIComponent(name) + '=';
    var parts = String(document.cookie || '').split(';');
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].trim();
      if (part.indexOf(prefix) === 0) return decodeURIComponent(part.slice(prefix.length));
    }
    return '';
  }
  function csrfHeaders() {
    var csrf = readCookie('ez_comfyui_csrf');
    return csrf ? { 'X-CSRF-Token': csrf } : {};
  }
  function routeProject() {
    var match = location.pathname.match(/\/labs\/([^/]+)/);
    return match ? match[1] : '';
  }
  function mediaFor(project) {
    if (project.id === 'bernini') return appUrl('/static/labs/assets/bernini-icon.png');
    if (project.id === 'joyai') return appUrl('/static/labs/assets/joyai-echo-gallery.png');
    if (project.hero_image) return appUrl(project.hero_image);
    return '';
  }
  function lockText(lock) {
    if (!lock || !lock.active) return '未锁定，ComfyUI 队列可正常出队。';
    var until = lock.expires_at ? new Date(Number(lock.expires_at) * 1000).toLocaleString() : '未设置过期时间';
    return (lock.project || '外部项目') + ' 正在占用 GPU；ComfyUI 新任务会保持排队，直到释放或过期。过期：' + until;
  }
  function projectReady(project) {
    return !!(project.status && project.status.source_exists && project.status.checkpoint_ready);
  }
  function missingCheckpointText(project) {
    var paths = project.status && project.status.checkpoint_paths ? project.status.checkpoint_paths : [];
    if (!paths.length) return '未配置 checkpoint 路径。';
    return '缺少官方 CLI 权重：' + paths.join(' / ');
  }
  function modeCanStart(project, mode) {
    return projectReady(project) && !(mode && mode.disabled);
  }
  function readinessText(project, mode) {
    if (mode && mode.external_workflow && !projectReady(project)) {
      return '官方 CLI 权重未就绪；该模式已在主界面工作流 ' + mode.external_workflow + ' 中可测。';
    }
    if (!project.status || !project.status.source_exists) return '源码未就绪，需先执行部署脚本。';
    if (!project.status.checkpoint_ready) return missingCheckpointText(project);
    if (mode && mode.disabled) return mode.disabled_reason || '当前模式暂不可运行。';
    return mode.description || '';
  }
  function updateLockPanel() {
    var panel = $('#lockPanel');
    var text = $('#lockText');
    var title = $('#lockTitle');
    if (!panel || !text || !title) return;
    panel.classList.toggle('locked', !!(state.lock && state.lock.active));
    title.textContent = state.lock && state.lock.active ? 'GPU 已锁定' : 'GPU 未锁定';
    text.textContent = lockText(state.lock);
  }
  function defaultPrompt(project, mode) {
    if (project.id === 'joyai') {
      return 'ID_A is a documentary host in a quiet studio, speaking in a calm warm voice. At normal speed, ID_A looks into the camera and says, "This is a short JoyAI-Echo playground test." The shot is realistic, softly lit, and framed as a stable medium close-up. No background music.';
    }
    if (project.id === 'hyworld2') {
      return 'Reconstruct the uploaded scene into a navigable 3D world asset with stable geometry, clean depth, and consistent camera alignment.';
    }
    if (mode === 'i2i') return 'Remove the distracting object while preserving the original lighting, perspective, texture, and all other scene details.';
    if (mode === 'v2v') return 'Make a controlled cinematic edit while preserving the original subject identity, camera motion, background, and temporal consistency.';
    if (mode === 'r2v') return 'Use the uploaded reference images to create a coherent short video with stable identity, natural motion, and consistent lighting.';
    if (mode === 'rv2v') return 'Apply the reference image content to the source video while preserving the original pose, motion, camera framing, background, and lighting.';
    if (mode === 't2v') return 'A realistic cinematic shot of a person walking through soft morning light, natural motion, stable camera, detailed environment, smooth temporal consistency.';
    return 'A high quality realistic image with balanced composition, natural lighting, detailed textures, and clean subject structure.';
  }
  function modeList(project) {
    return project.playground && Array.isArray(project.playground.modes) ? project.playground.modes : [];
  }
  function selectedMode(project, form) {
    var modes = modeList(project);
    var modeId = form.elements.mode.value || (modes[0] && modes[0].id);
    return modes.find(function(item) { return item.id === modeId; }) || modes[0] || {};
  }
  function applyModeDefaults(project, form, mode, overwritePrompt) {
    var defaults = mode.defaults || {};
    ['seed', 'width', 'height', 'frames', 'fps', 'steps'].forEach(function(name) {
      if (defaults[name] != null) form.elements[name].value = defaults[name];
    });
    var prompt = form.elements.prompt;
    prompt.placeholder = defaultPrompt(project, mode.id);
    if (overwritePrompt && !prompt.value.trim()) prompt.value = defaultPrompt(project, mode.id);
    updateUploadFields(form, mode);
    var btn = $('[data-action="start"]', form);
    if (btn) {
      btn.disabled = !modeCanStart(project, mode);
      btn.textContent = btn.disabled ? '权重未就绪' : '启动测试';
    }
  }
  function requirementText(kind, requires) {
    var min = Number(requires['min_' + kind] || requires[kind] || 0);
    if (min <= 0) return '';
    return '至少上传 ' + min + (kind === 'images' ? ' 张图片' : ' 个视频');
  }
  function updateUploadFields(form, mode) {
    var requires = mode.requires || {};
    ['images', 'videos'].forEach(function(kind) {
      var field = $('.upload-field[data-upload="' + kind + '"]', form);
      if (!field) return;
      var text = requirementText(kind, requires);
      var input = $('input', field);
      field.hidden = !text;
      input.required = !!text;
      $('small', field).textContent = text || '当前模式不需要上传。';
    });
    $('.mode-note', form).textContent = readinessText(form.__project, mode);
  }
  function renderRunPanel(project, node, run) {
    var panel = $('.run-panel', node);
    panel.hidden = false;
    $('.run-status', panel).textContent = run.status || 'queued';
    $('.run-status', panel).dataset.status = run.status || 'queued';
    $('.run-facts', panel).innerHTML = ''
      + '<dt>Run ID</dt><dd>' + esc(run.run_id || '-') + '</dd>'
      + '<dt>输入</dt><dd>' + esc(run.input_file || '-') + '</dd>'
      + '<dt>输出</dt><dd>' + esc(run.output_path || '-') + '</dd>'
      + '<dt>日志</dt><dd>' + esc(run.log_path || '-') + '</dd>';
    $('.run-command', panel).textContent = run.command_text || '';
    $('.run-log', panel).textContent = run.log_tail || '';
    if (run.status === 'queued' || run.status === 'running') startPolling(project, node, run.run_id);
  }
  function startPolling(project, node, runId) {
    var key = project.id + ':' + runId;
    if (state.pollers[key]) return;
    state.pollers[key] = window.setInterval(async function() {
      try {
        var res = await fetch(appUrl('/api/labs/playground/runs/' + encodeURIComponent(project.id) + '/' + encodeURIComponent(runId)), { cache: 'no-store' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var run = await res.json();
        renderRunPanel(project, node, run);
        if (run.status !== 'queued' && run.status !== 'running') {
          window.clearInterval(state.pollers[key]);
          delete state.pollers[key];
        }
      } catch (err) {
        window.clearInterval(state.pollers[key]);
        delete state.pollers[key];
      }
    }, 5000);
  }
  async function ensureLock(project) {
    if (state.lock && state.lock.active && state.token) return true;
    var ok = await acquireLock(project, true);
    if (!ok) alert('资源锁获取失败，请确认没有其它实验项目正在占用 GPU。');
    return ok;
  }
  async function submitPlayground(project, node, ev) {
    ev.preventDefault();
    var form = ev.currentTarget;
    var mode = selectedMode(project, form);
    if (!modeCanStart(project, mode)) {
      alert(readinessText(project, mode));
      return;
    }
    if (!(await ensureLock(project))) return;

    var btn = $('[data-action="start"]', form);
    btn.disabled = true;
    btn.textContent = '启动中...';
    try {
      var fd = new FormData(form);
      fd.append('project', project.id);
      fd.append('lock_token', state.token || '');
      var res = await fetch(appUrl('/api/labs/playground/start'), {
        method: 'POST',
        headers: csrfHeaders(),
        body: fd
      });
      var data = await res.json().catch(function() { return {}; });
      if (!res.ok) {
        var detail = data.detail || data.message || '启动失败';
        if (detail && detail.message) detail = detail.message;
        throw new Error(detail);
      }
      renderRunPanel(project, node, data);
    } catch (err) {
      alert(err && err.message ? err.message : '启动失败');
    } finally {
      btn.disabled = false;
      btn.textContent = '启动测试';
    }
  }
  function wirePlayground(project, node) {
    var form = $('.playground-form', node);
    form.__project = project;
    var select = form.elements.mode;
    var modes = modeList(project);
    select.innerHTML = modes.map(function(mode) {
      return '<option value="' + esc(mode.id) + '">' + esc(mode.label || mode.id) + '</option>';
    }).join('');
    if (!modes.length) {
      form.classList.add('disabled');
      $('[data-action="start"]', form).disabled = true;
      $('.mode-note', form).textContent = 'Manifest 还没有 playground 配置。';
      return;
    }
    applyModeDefaults(project, form, modes[0], false);
    select.addEventListener('change', function() {
      applyModeDefaults(project, form, selectedMode(project, form), false);
    });
    form.addEventListener('submit', submitPlayground.bind(null, project, node));
  }
  function renderProject(project) {
    var tmpl = $('#projectTemplate');
    var node = tmpl.content.firstElementChild.cloneNode(true);
    node.dataset.project = project.id;
    node.querySelector('.project-media').style.backgroundImage = 'url("' + mediaFor(project) + '")';
    node.querySelector('.project-kind').textContent = project.kind || 'lab';
    node.querySelector('h2').textContent = project.short_name || project.name || project.id;
    node.querySelector('.project-license').textContent = project.license_note || '';
    var ready = projectReady(project);
    var status = node.querySelector('.project-status');
    status.textContent = ready ? '可运行' : (project.status && project.status.source_exists ? '权重待准备' : '源码未就绪');
    status.classList.toggle('ready', !!ready);
    var facts = node.querySelector('.project-facts');
    facts.innerHTML = ''
      + '<dt>源码</dt><dd>' + esc(project.status && project.status.source_exists ? project.status.source_path : project.local_source) + '</dd>'
      + '<dt>Commit</dt><dd>' + esc(project.source_commit || '-') + '</dd>'
      + '<dt>权重</dt><dd>' + esc(project.status && project.status.checkpoint_ready ? '已就绪' : '未完整检测到') + '</dd>'
      + '<dt>Manifest</dt><dd>' + esc(project.manifest_file || '-') + '</dd>';
    var repo = node.querySelector('.project-actions a');
    repo.href = project.repo_url || project.model_url || '#';
    var cases = node.querySelector('.case-list');
    cases.innerHTML = (project.official_cases || []).map(function(item) {
      return '<div class="case-item"><strong>' + esc(item.name || item.case_file) + '</strong>'
        + '<span>case: ' + esc(item.case_file || '-') + '</span>'
        + '<span>output: ' + esc(item.output || '-') + '</span>'
        + '<pre>' + esc(item.command || '') + '</pre></div>';
    }).join('');
    node.querySelector('.setup-commands').textContent = (project.setup_commands || []).join('\n');
    node.querySelector('[data-action="lock"]').addEventListener('click', function() { acquireLock(project); });
    node.querySelector('[data-action="release"]').addEventListener('click', function() { releaseLock(); });
    wirePlayground(project, node);
    return node;
  }
  function render() {
    updateLockPanel();
    var grid = $('#projectGrid');
    var selected = routeProject();
    document.querySelectorAll('[data-project-link]').forEach(function(link) {
      link.href = appUrl('/labs/' + link.dataset.projectLink);
      link.classList.toggle('active', link.dataset.projectLink === selected || (!selected && link.dataset.projectLink === 'bernini'));
    });
    var visible = state.projects.filter(function(project) { return !selected || project.id === selected; });
    if (!visible.length) {
      grid.innerHTML = '<div class="lab-empty">没有找到测试项目，或当前账号没有权限读取实验室状态。</div>';
      return;
    }
    var first = visible[0];
    $('#labTitle').textContent = (first.short_name || first.name || '模型') + ' Playground';
    $('#labSubtitle').textContent = first.playground && first.playground.summary
      ? first.playground.summary
      : '上传素材、输入 prompt，并用官方 runner 快速验证模型能力。';
    grid.innerHTML = '';
    visible.forEach(function(project) {
      grid.appendChild(renderProject(project));
    });
  }
  async function load() {
    try {
      var res = await fetch(appUrl('/api/labs/projects'), { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      state.projects = data.projects || [];
      state.lock = data.resource_lock || { active: false };
      render();
    } catch (err) {
      $('#lockPanel').classList.add('error');
      $('#lockText').textContent = '读取失败：' + (err && err.message ? err.message : err);
      $('#projectGrid').innerHTML = '<div class="lab-empty">请先以管理员账号登录主界面，再打开测试实验室。</div>';
    }
  }
  async function acquireLock(project, quiet) {
    var lockConfig = project.resource_lock || {};
    var payload = {
      project: lockConfig.project || project.short_name || project.id,
      reason: lockConfig.reason || (project.short_name || project.id) + ' lab is using GPU',
      ttl_sec: lockConfig.default_ttl_sec || 21600,
      token: state.token || ''
    };
    var res = await fetch(appUrl('/api/resource-lock/acquire'), {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
      body: JSON.stringify(payload)
    });
    var data = await res.json();
    if (!res.ok) {
      if (!quiet) alert(data && data.detail && data.detail.message ? data.detail.message : '资源锁获取失败');
      await load();
      return false;
    }
    if (data.token) {
      state.token = data.token;
      sessionStorage.setItem('ez_lab_resource_lock_token', data.token);
    }
    state.lock = data;
    if (!quiet) render();
    else updateLockPanel();
    return true;
  }
  async function releaseLock() {
    var res = await fetch(appUrl('/api/resource-lock/release'), {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
      body: JSON.stringify({ token: state.token || '' })
    });
    if (!res.ok) {
      var data = await res.json().catch(function() { return {}; });
      alert(data.detail || '资源释放失败');
      return;
    }
    sessionStorage.removeItem('ez_lab_resource_lock_token');
    state.token = '';
    await load();
  }
  load();
})();
