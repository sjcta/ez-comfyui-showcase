const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '../..');
const SOURCE = fs.readFileSync(path.join(ROOT, 'static/js/modules/mobile_agent/mobile-agent.js'), 'utf8');

class FakeClassList {
  constructor(initial) {
    this.values = new Set(initial || []);
  }

  add(name) {
    this.values.add(name);
  }

  remove(name) {
    this.values.delete(name);
  }

  contains(name) {
    return this.values.has(name);
  }

  toString() {
    return Array.from(this.values).join(' ');
  }
}

class FakeElement {
  constructor(id) {
    this.id = id || '';
    this.dataset = {};
    this.innerHTML = '';
    this.listeners = {};
    this.value = '';
    this.classList = new FakeClassList(['mobile-agent', 'hidden']);
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }

  dispatch(type, target) {
    if (!this.listeners[type]) return undefined;
    const event = target && target.target ? target : { target };
    return this.listeners[type](event);
  }
}

class FakeFormData {
  constructor() {
    this.items = [];
  }

  append(name, value, filename) {
    this.items.push({ name, value, filename });
  }
}

function makeContext(options = {}) {
  const root = new FakeElement('mobileAgentRoot');
  const storage = Object.assign({}, options.storage || {});
  const deferred = {};
  const timers = [];
  const body = {
    dataset: options.bodyDataset || {},
    setAttribute() {},
    removeAttribute() {},
  };
  const document = {
    readyState: 'complete',
    body,
    documentElement: { style: { setProperty() {} } },
    querySelector(selector) {
      return selector === '#mobileAgentRoot' ? root : null;
    },
    getElementById(id) {
      return id === 'mobileAgentRoot' ? root : null;
    },
    createElement() {
      return { textContent: '', innerHTML: '' };
    },
    addEventListener() {},
  };
  const calls = [];
  const windowListeners = {};
  const context = {
    console,
    document,
    localStorage: {
      getItem(key) { return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : ''; },
      setItem(key, value) { storage[key] = String(value); },
      removeItem(key) { delete storage[key]; },
      _dump() { return Object.assign({}, storage); },
    },
    isSecureContext: options.isSecureContext !== false,
    location: { hash: options.hash || '', protocol: 'http:', pathname: options.pathname || '/', port: options.port || '' },
    addEventListener(type, handler) {
      windowListeners[type] = handler;
    },
    setTimeout: options.withFakeTimers
      ? function (handler, delay) {
        timers.push({ handler, delay, cleared: false });
        return timers.length;
      }
      : setTimeout,
    clearTimeout: options.withFakeTimers
      ? function (id) {
        if (timers[id - 1]) timers[id - 1].cleared = true;
      }
      : clearTimeout,
    runTimers() {
      timers.slice().forEach((timer) => {
        if (!timer.cleared) {
          timer.cleared = true;
          timer.handler();
        }
      });
    },
    dispatchWindow(type) {
      if (windowListeners[type]) return windowListeners[type]({ type });
      return undefined;
    },
    fetch(url, request) {
      calls.push({ url, request });
      if (url === '/api/mobile-agent/threads') {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({ ok: true, data: options.remoteThreads || [] });
          },
        });
      }
      if (/^\/api\/mobile-agent\/threads\/[^/]+$/.test(url)) {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({
              ok: true,
              data: request && request.body ? JSON.parse(request.body) : {},
            });
          },
        });
      }
      if (url === '/api/mobile-agent/upload-attachment') {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({
              ok: true,
              data: {
                id: 'att_1',
                name: 'face_front.png',
                mime_type: 'image/png',
                media_type: 'image',
                size: 1234,
                url: '/api/mobile-agent/attachments/att_1',
              },
            });
          },
        });
      }
      if (options.deferUnderstand && url === '/api/mobile-agent/understand') {
        return new Promise((resolve) => {
          deferred.resolveUnderstand = resolve;
        });
      }
      if (url === '/api/generate') {
        if (options.generateFailure) {
          return Promise.resolve({
            ok: false,
            json() {
              return Promise.resolve({ ok: false, error: 'no healthy instances' });
            },
          });
        }
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({ job_id: 'job_mobile_1', seed: 123 });
          },
        });
      }
      if (/^\/api\/jobs\/[^/]+\/retry$/.test(url)) {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({ job_id: 'job_retry_1', seed: 456 });
          },
        });
      }
      if (/^\/api\/jobs\/[^/]+$/.test(url)) {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve(options.jobStatus || {
              id: 'job_mobile_1',
              status: 'generating',
              message: '生成中',
              progress: { pct: 50 },
            });
          },
        });
      }
      if (options.understandFailure) {
        return Promise.resolve({
          ok: false,
          json() {
            return Promise.resolve({ ok: false, error: '需要登录后使用。' });
          },
        });
      }
      if (options.understandUnauthorized) {
        return Promise.resolve({
          ok: false,
          status: 401,
          json() {
            return Promise.resolve({ detail: 'Not authenticated' });
          },
        });
      }
      const body = request && request.body ? JSON.parse(request.body) : {};
      if (options.agentChatResponse) {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({
              ok: true,
              data: {
                response_type: 'chat',
                intent: 'clarify',
                assistant_message: options.markdownReply || '可以。你想做什么主体的图？',
                question: options.markdownReply || '可以。你想做什么主体的图？',
                missing_slots: ['subject'],
                draft_requirement: { ready: false, prompt_text: '' },
                resolved_workflow: '',
                needs_confirmation: true,
              },
            });
          },
        });
      }
      return Promise.resolve({
        ok: true,
        json() {
          return Promise.resolve({
            ok: true,
            data: {
              intent: body.context && body.context.last_result ? 'image_to_image' : 'text_to_image',
              display_summary: '后端摘要：海边日落',
              compiled_prompt: 'fallback prompt',
              creative_brief: {
                task_type: body.context && body.context.last_result ? 'image_to_image' : 'text_to_image',
                subject: '海边日落',
                scene: '海边',
                style: 'cinematic',
                lighting: '日落自然光',
                composition: '',
                mood: '',
                negative: '',
                edit_instruction: '',
                source_image: '',
                final_prompt: 'fallback prompt',
              },
              style: 'cinematic',
              aspect_ratio: '9:16',
              workflow: body.context && body.context.last_result ? 'default_image_to_image' : 'default_text_to_image',
              resolved_workflow: body.context && body.context.last_result ? 'i2i-test.json' : 't2i-test.json',
              field_values: { '1::text': 'prompt' },
              workflow_choices: [
                {
                  workflow: body.context && body.context.last_result ? 'i2i-test.json' : 't2i-test.json',
                  title: body.context && body.context.last_result ? '默认图生图' : '默认文生图',
                  field_values: { '1::text': 'prompt' },
                },
                {
                  workflow: 't2i-fast.json',
                  title: '快速文生图',
                  field_values: { '2::text': 'fast prompt' },
                },
              ],
              width: 720,
              height: 1280,
              options: {
                allowed_styles: ['cinematic', 'anime', 'realistic'],
                allowed_ratios: ['9:16', '1:1'],
              },
              option_requirements: options.resolvedOptions
                ? { style: false, aspect_ratio: false }
                : { style: true, aspect_ratio: true },
            },
          });
        },
      });
    },
    FormData: FakeFormData,
    window: null,
  };
  if (options.withPendingMic) {
    context.navigator = {
      mediaDevices: {
        getUserMedia() {
          return new Promise(() => {});
        },
      },
    };
    context.MediaRecorder = function MediaRecorder() {};
  }
  if (options.withMissingMic) {
    context.navigator = {
      mediaDevices: {
        getUserMedia() {
          const err = new Error('Requested device not found');
          err.name = 'NotFoundError';
          return Promise.reject(err);
        },
      },
    };
    context.MediaRecorder = function MediaRecorder() {};
  }
  if (options.withDeniedMic) {
    context.navigator = {
      mediaDevices: {
        getUserMedia() {
          const err = new Error('Permission denied');
          err.name = 'NotAllowedError';
          return Promise.reject(err);
        },
      },
    };
    context.MediaRecorder = function MediaRecorder() {};
  }
  context.window = context;
  context.__APP__ = {
    API: '',
    $(selector) {
      return document.querySelector(selector);
    },
    escH(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    },
  };
  if (options.withIcon) {
    context.CW = { icon(name) { return `<i data-icon="${name}"></i>`; } };
  } else {
    context.CW = {};
  }
  if (options.withLoggedOutAuth) {
    context.loginShown = false;
    context.CW.authReady = Promise.resolve(null);
    context.CW.auth = {
      getCurrentUser() { return null; },
      showLogin() { context.loginShown = true; },
    };
  }
  if (options.withLoggedInAuth) {
    context.currentAuthUser = { id: 'u1', sub: 'u1', username: 'cta', role: 'admin' };
    context.loggedOut = false;
    context.accountTab = '';
    context.CW.authReady = Promise.resolve(null);
    context.CW.auth = {
      getCurrentUser() { return context.currentAuthUser; },
      showAccountTab(tab) { context.accountTab = tab; },
      showLogin() { context.loginShown = true; },
      logout() {
        context.loggedOut = true;
        context.currentAuthUser = null;
      },
    };
  }
  return { context, root, calls, storage, deferred, windowListeners, timers };
}

async function run() {
  {
    const { context, root } = makeContext({ withIcon: false });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    assert.strictEqual(root.innerHTML, '', 'module should not render by default');
    assert(root.classList.contains('hidden'), 'root should remain hidden by default');
  }

  {
    const { context, root } = makeContext({ pathname: '/app/', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    assert(root.innerHTML.includes('智能创作'), 'app subpath should render mobile shell by default');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true, withFakeTimers: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('focusin', { id: 'mobileAgentText' });
    assert(root.classList.contains('is-input-active'), 'focused composer should activate the blue input aura');
    assert(!root.classList.contains('is-input-blurring'), 'focused composer should cancel any blur transition');

    root.dispatch('focusout', { id: 'mobileAgentText' });
    assert(!root.classList.contains('is-input-active'), 'blurred composer should leave active aura state');
    assert(root.classList.contains('is-input-blurring'), 'blurred composer should keep a short animated settle state');

    context.runTimers();
    assert(!root.classList.contains('is-input-blurring'), 'blur settle class should be removed after the animation window');
  }

  {
    const { context, root, storage } = makeContext({
      hash: '#mobile-agent',
      withIcon: true,
      withLoggedInAuth: true,
      storage: {
        'ez_mobile_agent_threads:v1': JSON.stringify([{
          id: 'thread_1',
          title: '猫咪玩耍的照片',
          preview: '准备生成这张图',
          updatedAt: 1,
          messages: [{ role: 'user', type: 'text', text: '猫咪玩耍的照片' }],
          lastResult: null,
        }]),
      },
    });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    assert(root.innerHTML.includes('mobile-agent-avatar'), 'logged-in mobile shell should show an avatar menu trigger');
    assert(root.innerHTML.includes('历史对话'), 'home should expose conversation history');
    assert(root.innerHTML.includes('猫咪玩耍的照片'), 'home should list stored conversations');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return { getAttribute(name) { return name === 'data-action' ? 'toggle-account-menu' : ''; } };
      },
    });
    assert(root.innerHTML.includes('新建对话'), 'avatar menu should include new chat');
    assert(root.innerHTML.includes('data-action="logout"'), 'avatar menu should include logout');
    assert(root.innerHTML.includes('账户设置'), 'avatar menu should include account settings');
    assert(root.innerHTML.includes('桌面主页面'), 'avatar menu should include desktop page entry');
    assert(!root.innerHTML.includes('mobile-agent-menu-thread-row'), 'avatar menu should not include recent conversation topics');

    root.dispatch('click', {
      closest() {
        return null;
      },
    });
    assert(!root.innerHTML.includes('mobile-agent-menu is-open'), 'clicking outside the avatar menu should close it');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return { getAttribute(name) { return name === 'data-action' ? 'toggle-account-menu' : ''; } };
      },
    });

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'account-settings',
            }[name] || '';
          },
        };
      },
    });
    assert.strictEqual(context.accountTab, 'profile', 'account settings should open the shared account profile modal');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'logout',
            }[name] || '';
          },
        };
      },
    });
    assert.strictEqual(context.loggedOut, true, 'avatar menu logout should call shared auth logout');
    assert(root.innerHTML.includes('data-action="login"'), 'mobile shell should rerender logged-out state after logout');

    context.currentAuthUser = { id: 'u1', sub: 'u1', username: 'cta', role: 'admin' };
    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'open-thread',
              'data-thread-id': 'thread_1',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('mobile-agent-chat'), 'history item should reopen the conversation view');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return { getAttribute(name) { return name === 'data-action' ? 'home-main' : ''; } };
      },
    });
    assert(root.innerHTML.includes('智能创作'), 'back to home should return to the mobile home screen');
    assert(root.innerHTML.includes('历史对话'), 'back to home should keep the history list visible');
  }

  {
    const { context, root, calls, storage } = makeContext({
      hash: '#mobile-agent',
      withIcon: true,
      withLoggedInAuth: true,
      withFakeTimers: true,
      remoteThreads: [{
        id: 'thread_remote',
        title: '远端话题',
        preview: '数据库中的对话',
        updatedAt: 2,
        messages: [{ role: 'user', type: 'text', text: '远端话题' }],
      }],
      storage: {
        'ez_mobile_agent_threads:v1': JSON.stringify([{
          id: 'thread_local',
          title: '本地未同步话题',
          preview: '登录后应写入数据库',
          updatedAt: 3,
          messages: [{ role: 'user', type: 'text', text: '本地未同步话题' }],
        }]),
      },
    });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    await context.CW.refreshForAuthChange();
    context.runTimers();

    assert(calls.some((call) => call.url === '/api/mobile-agent/threads'), 'mobile auth refresh should load remote conversation threads');
    assert(calls.some((call) => call.url === '/api/mobile-agent/threads/thread_local' && call.request && call.request.method === 'PUT'), 'mobile auth refresh should migrate newer local threads into the database');
    const merged = JSON.parse(storage['ez_mobile_agent_threads:v1']);
    assert(merged.some((thread) => thread.id === 'thread_remote'), 'mobile auth refresh should merge database threads into local history');
  }

  {
    const { context, root, calls, storage } = makeContext({
      hash: '#mobile-agent',
      withIcon: true,
      withLoggedInAuth: true,
      storage: {
        'ez_mobile_agent_threads:v1': JSON.stringify([{
          id: 'thread_delete',
          title: '需要删除的话题',
          preview: '同时清理本地和数据库',
          updatedAt: 4,
          messages: [{ role: 'user', type: 'text', text: '需要删除的话题' }],
        }]),
      },
    });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'delete-thread',
              'data-thread-id': 'thread_delete',
            }[name] || '';
          },
        };
      },
    });

    const remaining = JSON.parse(storage['ez_mobile_agent_threads:v1']);
    assert(!remaining.some((thread) => thread.id === 'thread_delete'), 'delete thread should remove the topic from browser localStorage');
    assert(calls.some((call) => call.url === '/api/mobile-agent/threads/thread_delete' && call.request && call.request.method === 'DELETE'), 'delete thread should request database removal for logged-in users');
  }

  {
    const threadStorage = {
      'ez_mobile_agent_threads:v1': JSON.stringify([
        {
          id: 'thread_old',
          title: '最早的猫咪草稿',
          preview: '旧话题',
          updatedAt: 1,
          messages: [{ role: 'user', type: 'text', text: '最早的猫咪草稿' }],
        },
        {
          id: 'thread_latest',
          title: '最新进行中的雨夜猫咪',
          preview: '生成完成',
          updatedAt: 3,
          messages: [{ role: 'user', type: 'text', text: '最新进行中的雨夜猫咪' }],
        },
        {
          id: 'thread_mid',
          title: '中间的机器人讨论',
          preview: '继续讨论',
          updatedAt: 2,
          messages: [{ role: 'user', type: 'text', text: '中间的机器人讨论' }],
        },
      ]),
    };
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true, storage: threadStorage });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    assert(root.innerHTML.includes('最新进行中的雨夜猫咪'), 'home should show the latest interacted topic');
    assert.strictEqual((root.innerHTML.match(/mobile-agent-history-row/g) || []).length, 1, 'home should only render one inline history row');
    assert(root.innerHTML.includes('data-action="open-history"'), 'history title should open the expanded topic view');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return { getAttribute(name) { return name === 'data-action' ? 'open-history' : ''; } };
      },
    });

    assert(root.innerHTML.includes('全部历史对话'), 'expanded history view should make the topic list primary');
    assert(root.innerHTML.includes('最新进行中的雨夜猫咪'), 'expanded history should include latest topic');
    assert(root.innerHTML.includes('最早的猫咪草稿'), 'expanded history should include older topic');
    assert(root.innerHTML.includes('中间的机器人讨论'), 'expanded history should include middle topic');
    assert(!root.innerHTML.includes('mobile-agent-compose'), 'expanded history should hide the text input');
    assert(!root.innerHTML.includes('mobile-agent-input-row'), 'expanded history should hide the bottom buttons');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'open-thread',
              'data-thread-id': 'thread_mid',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('mobile-agent-chat'), 'choosing a topic should switch back into the conversation window');
    assert(root.innerHTML.includes('中间的机器人讨论'), 'chosen topic should be loaded into the conversation');
    assert(root.innerHTML.includes('mobile-agent-input-row'), 'conversation should restore the composer controls');
  }

  {
    const savedThread = {
      id: 'thread_memory',
      activeThreadId: 'thread_memory',
      messages: [
        { id: 'u1', role: 'user', type: 'text', text: '帮我出一张赛博朋克猫咪' },
        {
          id: 'a1',
          role: 'assistant',
          type: 'confirm',
          text: '赛博朋克猫咪，雨夜，霓虹灯，电影感',
          data: {
            intent: 'text_to_image',
            display_summary: '赛博朋克猫咪，雨夜，霓虹灯，电影感',
            compiled_prompt: '赛博朋克猫咪，雨夜，霓虹灯，电影感',
            style: 'cinematic',
            aspect_ratio: '1:1',
            resolved_workflow: 't2i-test.json',
          },
        },
        {
          id: 'r1',
          role: 'assistant',
          type: 'result',
          text: '生成完成',
          image: 'user1/2026-05-25/cat.png',
          thumb: 'user1/2026-05-25/cat-thumb.jpg',
          media_type: 'image',
          prompt: '赛博朋克猫咪，雨夜，霓虹灯，电影感',
        },
      ],
      lastResult: {
        id: 'job_memory',
        image: 'user1/2026-05-25/cat.png',
        thumb: 'user1/2026-05-25/cat-thumb.jpg',
        media_type: 'image',
        prompt: '赛博朋克猫咪，雨夜，霓虹灯，电影感',
      },
      pendingMessageId: '',
      pendingJobId: '',
    };
    const { context, root, calls } = makeContext({
      hash: '#mobile-agent',
      withIcon: true,
      storage: {
        'ez_mobile_agent_thread:v1': JSON.stringify(savedThread),
        'ez_mobile_agent_threads:v1': JSON.stringify([savedThread]),
      },
    });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '改成更明亮一些' });
    await context.CW.mobileAgent.submitUnderstand();

    const body = JSON.parse(calls[0].request.body);
    assert.strictEqual(body.text, '改成更明亮一些');
    assert(!body.context.last_result, 'home composer should start a fresh thread instead of reusing the last generated result');
    assert(!body.context.active_brief, 'home composer should not carry the previous thread brief into a fresh topic');
    assert(!body.context.memory_summary.includes('上一张生成结果'), 'home composer should not include previous result memory when starting from home');
    assert(!body.context.messages.some((msg) => msg.role === 'user' && msg.text === '改成更明亮一些'), 'current turn should not be duplicated in context');
    const savedThreads = JSON.parse(context.localStorage._dump()['ez_mobile_agent_threads:v1']);
    assert(savedThreads.length >= 2, 'home send should preserve the old topic and create a new topic');
    assert.notStrictEqual(savedThreads[0].id, 'thread_memory', 'home send should make the submitted text the latest new topic');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true, agentChatResponse: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '我想要出一张图' });
    await context.CW.mobileAgent.submitUnderstand();

    assert.strictEqual(calls[0].url, '/api/mobile-agent/understand');
    assert(root.innerHTML.includes('mobile-agent-chat'), 'chat response should stay in conversation view');
    assert(root.innerHTML.includes('可以。你想做什么主体的图？'), 'chat response should render the assistant text');
    assert(!root.innerHTML.includes('mobile-agent-confirm-card'), 'chat response should not render a generation confirm card');
    assert(!root.innerHTML.includes('data-action="generate"'), 'chat response should not expose generate action before requirements are ready');
  }

  {
    const { context, root, calls, deferred } = makeContext({ hash: '#mobile-agent', withIcon: true, deferUnderstand: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '模型思考测试' });
    const pending = context.CW.mobileAgent.submitUnderstand();

    assert.strictEqual(calls[0].url, '/api/mobile-agent/understand');
    assert(root.innerHTML.includes('模型思考测试'), 'user message should render immediately while the model is thinking');
    assert(root.innerHTML.includes('mobile-agent-thinking'), 'assistant should render a thinking bubble before the API returns');
    assert(root.innerHTML.includes('mobile-agent-thinking-dot'), 'thinking bubble should use three animated dots');

    deferred.resolveUnderstand({
      ok: true,
      json() {
        return Promise.resolve({
          ok: true,
          data: {
            response_type: 'chat',
            intent: 'general_chat',
            assistant_message: '这是模型返回后的自然回复。',
            question: '这是模型返回后的自然回复。',
            missing_slots: [],
            draft_requirement: { ready: false, prompt_text: '' },
            resolved_workflow: '',
            needs_confirmation: true,
          },
        });
      },
    });
    await pending;

    assert(!root.innerHTML.includes('mobile-agent-thinking'), 'thinking bubble should be replaced after the reply returns');
    assert(root.innerHTML.includes('这是模型返回后的自然回复。'), 'assistant reply should render in the conversation');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    assert(root.innerHTML.includes('智能创作'), 'hash route should render mobile shell');
    assert(root.innerHTML.includes('id="mobileAgentImageFile"'), 'home should include image file input');
    assert(root.innerHTML.includes('data-action="image"'), 'image icon should be clickable');
    assert(root.innerHTML.includes('data-action="voice"'), 'voice icon should be clickable');
    assert(root.innerHTML.includes('mobile-agent-compose-body'), 'compose body should wrap text and attachments');

    root.dispatch('input', { id: 'mobileAgentText', value: '海边日落' });
    await context.CW.mobileAgent.submitUnderstand();

    assert.strictEqual(calls[0].url, '/api/mobile-agent/understand');
    assert.deepStrictEqual(JSON.parse(calls[0].request.body), {
      text: '海边日落',
      has_image: false,
      has_video: false,
      attachments: [],
      context: {
        last_result: null,
        active_brief: null,
        memory_summary: '',
        messages: [],
      },
    });
    assert(root.innerHTML.includes('mobile-agent-chat'), 'submit should switch into a conversation view');
    assert(root.innerHTML.includes('mobile-agent-message-user'), 'conversation should keep the user message');
    assert(root.innerHTML.includes('mobile-agent-confirm-card'), 'assistant response should render as an inline confirmation card');
    assert(root.innerHTML.includes('后端摘要：海边日落'), 'confirm should render backend display summary');
    assert(root.innerHTML.includes('cinematic'), 'confirm should render selected style and style chips');
    assert(root.innerHTML.includes('9:16'), 'confirm should render selected ratio and ratio chips');
    assert(root.innerHTML.includes('realistic'), 'confirm should render allowed style chips');
    assert(root.innerHTML.includes('1:1'), 'confirm should render allowed ratio chips');
    assert(root.innerHTML.includes('data-action="toggle-workflow-menu"'), 'confirm should expose a compact workflow switch');
    assert(!root.innerHTML.includes('mobile-agent-workflow-menu'), 'confirm should keep workflow choices collapsed by default');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'toggle-workflow-menu',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('mobile-agent-workflow-menu'), 'workflow switch should open the workflow menu');
    assert(root.innerHTML.includes('快速文生图'), 'workflow menu should expose selectable workflow chips');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'select-option',
              'data-message-id': '',
              'data-option': 'aspect_ratio',
              'data-value': '1:1',
            }[name] || '';
          },
        };
      },
    });
    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'select-option',
              'data-message-id': '',
              'data-option': 'style',
              'data-value': 'anime',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('class="mobile-agent-chip is-selected" data-action="select-option" data-option="style" data-value="anime"'), 'style chip click should update selected state');

    await context.CW.mobileAgent.submitGenerate();

    assert.strictEqual(calls[1].url, '/api/generate');
    const generateBody = JSON.parse(calls[1].request.body);
    assert.deepStrictEqual(generateBody, {
      workflow: 't2i-test.json',
      fields: { '1::text': 'fallback prompt，精致动漫风格，清晰线条和明快色彩' },
      creative_brief: {
        task_type: 'text_to_image',
        subject: '海边日落',
        scene: '海边',
        style: 'anime',
        lighting: '日落自然光',
        composition: '',
        mood: '',
        negative: '',
        edit_instruction: '',
        source_image: '',
        final_prompt: 'fallback prompt，精致动漫风格，清晰线条和明快色彩',
        aspect_ratio: '1:1',
      },
      width: 1024,
      height: 1024,
    });
    assert(root.innerHTML.includes('已加入生成队列'), 'generation submit should show that the job was actually queued');
    assert(root.innerHTML.includes('mobile-agent-task-card'), 'queued generation should render a dynamic task placeholder in the conversation');
    assert(root.innerHTML.includes('当前任务'), 'queued generation should label the current task status');
    assert(root.innerHTML.includes('fallback prompt'), 'queued generation should show the task content description');
    assert(!root.innerHTML.includes('mobile-agent-confirm-card'), 'generation should replace the confirm card instead of appending a second task card below it');
    assert(!root.innerHTML.includes('aria-label="风格"'), 'generation task state should remove choice controls');

    await context.CW.mobileAgent.submitGenerate();
    assert.strictEqual(calls.length, 2, 'pending generation should not submit duplicate jobs');

    context.CW.mobileAgent.handleJobUpdate({
      id: 'job_mobile_1',
      status: 'starting_comfyui',
      message: '启动 ComfyUI #A...',
      progress: { pct: 0 },
    });
    assert(root.innerHTML.includes('启动 ComfyUI #A...'), 'intermediate job updates should replace the generic pending text');
    assert(root.innerHTML.includes('role="progressbar"'), 'intermediate job updates should keep the task progress surface visible');

    context.CW.mobileAgent.handleJobUpdate({
      id: 'job_mobile_1',
      status: 'checking',
      pending_image: 'user1/2026-05-25/cat.png',
      pending_thumb: 'user1/2026-05-25/cat-thumb.jpg',
      pending_media_type: 'image',
      images: ['user1/2026-05-25/cat.png'],
      thumbs: ['user1/2026-05-25/cat-thumb.jpg'],
      workflow: 't2i-test.json',
    });

    assert(root.innerHTML.includes('/api/thumbs/user1/2026-05-25/cat-thumb.jpg'), 'completed job should render image result in the conversation');
    assert(root.innerHTML.includes('mobile-agent-result-card is-fresh'), 'completed job should animate the task card into a fresh result card once');
    assert(root.innerHTML.includes('生成完成'), 'completed job should label the result as done');
    assert(root.innerHTML.includes('data-action="open-result-preview"'), 'completed image should be clickable for preview');
    assert(root.innerHTML.includes('download'), 'completed result should expose a download link');
    assert(root.innerHTML.includes('data-action="toggle-result-prompt"'), 'completed result should expose a prompt toggle');
    assert(context.CW.mobileAgent.getConversationContext().last_result.image === 'user1/2026-05-25/cat.png', 'completed job should become the next-turn image context');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'toggle-result-prompt',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('mobile-agent-result-prompt'), 'prompt toggle should reveal the full prompt block');
    assert(root.innerHTML.includes('fallback prompt，精致动漫风格'), 'prompt block should show the complete prompt');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'open-result-preview',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('mobile-agent-preview-overlay'), 'clicking the result image should open the mobile preview overlay');
    assert(root.innerHTML.includes('/api/images/user1/2026-05-25/cat.png'), 'preview should use the full image source');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'close-result-preview',
            }[name] || '';
          },
        };
      },
    });
    assert(!root.innerHTML.includes('mobile-agent-preview-overlay'), 'preview close should dismiss the overlay');

    root.dispatch('input', { id: 'mobileAgentText', value: '改成赛博朋克风格' });
    await context.CW.mobileAgent.submitUnderstand();

    const followupBody = JSON.parse(calls[2].request.body);
    assert.strictEqual(followupBody.context.last_result.image, 'user1/2026-05-25/cat.png');
    assert(followupBody.context.active_brief, 'follow-up context should include the previous confirmed creative brief');
    assert(followupBody.context.active_brief.compiled_prompt.includes('fallback prompt'), 'follow-up context should remember the previous prompt');
    assert(followupBody.context.memory_summary.includes('上一版创作方案'), 'follow-up context should include a concise memory summary');
    assert(!followupBody.context.messages.some((msg) => msg.role === 'user' && msg.text === '改成赛博朋克风格'), 'current user text should not be duplicated inside context messages');
    assert.strictEqual(followupBody.text, '改成赛博朋克风格');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '海边日落' });
    await context.CW.mobileAgent.submitUnderstand();

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'select-option',
              'data-message-id': '',
              'data-option': 'workflow',
              'data-value': 't2i-fast.json',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('已匹配工作流：<span>快速文生图</span>'), 'workflow chip click should update selected workflow status');
    assert(!root.innerHTML.includes('mobile-agent-workflow-menu'), 'workflow menu should close after selecting a workflow');

    await context.CW.mobileAgent.submitGenerate();

    const generateBody = JSON.parse(calls[1].request.body);
    assert.strictEqual(generateBody.workflow, 't2i-fast.json', 'generation should submit the selected workflow');
    assert.deepStrictEqual(generateBody.fields, { '2::text': 'fast prompt' }, 'generation should submit selected workflow field mapping');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true, generateFailure: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '海边日落' });
    await context.CW.mobileAgent.submitUnderstand();
    await context.CW.mobileAgent.submitGenerate();

    assert.strictEqual(calls[1].url, '/api/generate');
    assert(root.innerHTML.includes('mobile-agent-task-card is-error'), 'failed submit should keep a visible task card');
    assert(root.innerHTML.includes('出图实例暂不可用'), 'failed submit should show localized failure text');
    assert(root.innerHTML.includes('data-action="retry-generate"'), 'failed submit should expose a retry button');
    assert(root.innerHTML.includes('后端摘要：海边日落'), 'failed submit should keep task prompt details');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'retry-generate',
              'data-message-id': 'ignored',
            }[name] || '';
          },
        };
      },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.strictEqual(calls.length, 3, 'retry button should submit generation again');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true, withLoggedInAuth: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '海边日落' });
    await context.CW.mobileAgent.submitUnderstand();
    await context.CW.mobileAgent.submitGenerate();
    context.CW.mobileAgent.handleJobUpdate({
      id: 'job_mobile_1',
      status: 'error',
      message: '实例占用超时',
      progress: { pct: 0 },
      workflow: 't2i-test.json',
      prompt_preview: '后端摘要：海边日落',
    });
    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'retry-generate',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    const retryIndex = calls.findIndex((call) => call.url === '/api/jobs/job_mobile_1/retry');
    assert(retryIndex >= 0, 'job failure retry should call the authoritative backend retry endpoint: ' + calls.map((call) => call.url).join(', '));
    assert(!calls.slice(retryIndex).some((call) => call.url === '/api/generate'), 'job failure retry should not resubmit directly through /api/generate: ' + calls.map((call) => call.url).join(', '));
  }

  {
    const { context, root, calls, windowListeners } = makeContext({
      hash: '#mobile-agent',
      withIcon: true,
      withLoggedInAuth: true,
      jobStatus: {
        id: 'job_resume_1',
        status: 'done',
        image: 'resume.png',
        thumb: 'resume_thumb.jpg',
        media_type: 'image',
        prompt_preview: '回到前台结果',
      },
      storage: {
        'ez_mobile_agent_thread:v1': JSON.stringify({
          id: 'thread_resume',
          activeThreadId: 'thread_resume',
          pendingJobId: 'job_resume_1',
          pendingMessageId: 'msg_task',
          messages: [{
            id: 'msg_task',
            role: 'assistant',
            type: 'task',
            text: '生成中',
            status: 'generating',
            job_id: 'job_resume_1',
            data: { resolved_workflow: 't2i-test.json' },
          }],
        }),
      },
    });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    assert(windowListeners.focus, 'mobile agent should listen for foreground resume');
    await windowListeners.focus({ type: 'focus' });
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert(calls.some((call) => call.url === '/api/jobs/job_resume_1'), 'foreground resume should fetch pending job status');
    assert(root.innerHTML.includes('resume_thumb.jpg'), 'foreground resume should patch completed image into conversation');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true, resolvedOptions: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '真实摄影风格，1:1，猫咪玩耍' });
    await context.CW.mobileAgent.submitUnderstand();

    assert(root.innerHTML.includes('mobile-agent-confirm-card'), 'resolved request should still render a compact confirm card');
    assert(!root.innerHTML.includes('aria-label="风格"'), 'explicit style should not ask the user to choose style again');
    assert(!root.innerHTML.includes('aria-label="画幅"'), 'explicit ratio should not ask the user to choose ratio again');
    assert(root.innerHTML.includes('生成'), 'resolved request should keep a single generate action');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    let prevented = false;

    root.dispatch('input', { id: 'mobileAgentText', value: '键盘发送测试' });
    await root.dispatch('keydown', {
      target: { id: 'mobileAgentText', value: '键盘发送测试' },
      key: 'Enter',
      ctrlKey: false,
      metaKey: false,
      preventDefault() { prevented = true; },
    });

    assert.strictEqual(calls[0].url, '/api/mobile-agent/understand');
    assert.strictEqual(JSON.parse(calls[0].request.body).text, '键盘发送测试');
    assert.strictEqual(prevented, true, 'Enter should send and prevent textarea newline');

    let shiftPrevented = false;
    await root.dispatch('keydown', {
      target: { id: 'mobileAgentText', value: '换行测试' },
      key: 'Enter',
      shiftKey: true,
      preventDefault() { shiftPrevented = true; },
    });
    assert.strictEqual(shiftPrevented, false, 'Shift+Enter should keep the normal textarea newline behavior');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', understandFailure: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '赛博朋克城市夜景' });
    await context.CW.mobileAgent.submitUnderstand();

    assert(root.innerHTML.includes('需要登录后使用。'), 'understand failure should show backend error');
    assert(!root.innerHTML.includes('disabled>'), 'understand failure should re-enable the send button');
    assert(root.innerHTML.includes('<span>发送</span>'), 'understand failure should restore the send label');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', understandUnauthorized: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '一张海边日落' });
    await context.CW.mobileAgent.submitUnderstand();

    assert(root.innerHTML.includes('请先登录后使用移动端创作。'), 'unauthorized understand should show a clear login message');
    assert(!root.innerHTML.includes('理解失败'), 'unauthorized understand should not fall back to generic failure');
    assert(!root.innerHTML.includes('Not authenticated'), 'unauthorized understand should not leak backend auth text');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withLoggedOutAuth: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '一张海边日落' });
    await context.CW.mobileAgent.submitUnderstand();

    assert.strictEqual(calls[0].url, '/api/mobile-agent/understand');
    assert(root.innerHTML.includes('mobile-agent-confirm-card'), 'logged-out visitor should still get a creation plan');
    assert.strictEqual(context.loginShown, false, 'logged-out understand should not open the login modal');

    await context.CW.mobileAgent.submitGenerate();

    assert.strictEqual(calls.length, 1, 'logged-out generate should not call the generate API');
    assert.strictEqual(context.loginShown, true, 'logged-out generate should open the login modal when available');
    assert(root.innerHTML.includes('请先登录后开始生成。'), 'logged-out generate should explain that login is only needed for output');
  }

  {
    const { context, root } = makeContext({ pathname: '/', port: '18002', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    assert(root.innerHTML.includes('智能创作'), 'isolated mobile test port should render mobile shell at root');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true, withPendingMic: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return { getAttribute() { return 'voice'; } };
      },
    });

    assert(root.innerHTML.includes('is-voice-active'), 'voice capture should expand the composer row inline');
    assert(root.innerHTML.includes('mobile-agent-wave'), 'voice capture should show waveform animation markup');
    assert(root.innerHTML.includes('正在录音识别'), 'voice capture should label the expanded recording button');
    assert(root.innerHTML.includes('data-view="home"'), 'voice button should not navigate to a separate screen');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true, withMissingMic: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    await context.CW.mobileAgent.startVoiceCapture();

    assert(root.innerHTML.includes('没有找到可用麦克风'), 'missing microphone should show a friendly localized error');
    assert(!root.innerHTML.includes('Requested device not found'), 'missing microphone should not leak browser error text');
    assert(!root.innerHTML.includes('is-voice-active'), 'missing microphone should collapse the recording pill');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    await context.CW.mobileAgent.startVoiceCapture();

    assert(root.innerHTML.includes('当前浏览器没有开放麦克风接口'), 'browser without mediaDevices should explain that no permission prompt can open');
    assert(!root.innerHTML.includes('media devices unavailable'), 'browser capability error should not leak implementation text');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true, withDeniedMic: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    await context.CW.mobileAgent.startVoiceCapture();

    assert(root.innerHTML.includes('麦克风授权没有生效'), 'permission failure after prompt should explain that authorization did not take effect');
    assert(!root.innerHTML.includes('Permission denied'), 'permission failure should not leak browser error text');
    assert.strictEqual(context.CW.mobileAgent.getVoiceDiagnostics().name, 'NotAllowedError');
  }

  {
    const { context, root } = makeContext({ hash: '#mobile-agent', withIcon: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    root.dispatch('change', {
      id: 'mobileAgentImageFile',
      files: [{ name: 'face_front.png' }],
    });

    assert(root.innerHTML.includes('mobile-agent-compose-body has-attachment'), 'image attachment should live inside the compose body');
    assert(root.innerHTML.includes('mobile-agent-compose-attachment'), 'image attachment should render as an inline compose thumbnail');
    assert(root.innerHTML.includes('mobile-agent-attachment-remove'), 'image attachment should expose a circular remove badge');
    assert(!root.innerHTML.includes('<strong>face_front.png</strong>'), 'image attachment should not render as a separate filename bar');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true, agentChatResponse: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });
    root.dispatch('change', {
      id: 'mobileAgentImageFile',
      files: [{ name: 'face_front.png', type: 'image/png', size: 1234 }],
    });
    root.dispatch('input', { id: 'mobileAgentText', value: '图片内容分析' });
    await context.CW.mobileAgent.submitUnderstand();

    assert.strictEqual(calls[0].url, '/api/mobile-agent/upload-attachment', 'image should be uploaded before understand request');
    assert.strictEqual(calls[1].url, '/api/mobile-agent/understand', 'understand request should follow attachment upload');
    const body = JSON.parse(calls[1].request.body);
    assert.strictEqual(body.text, '图片内容分析');
    assert.strictEqual(body.has_image, true);
    assert.strictEqual(body.attachments[0].id, 'att_1');
    assert.strictEqual(body.context.attachments[0].url, '/api/mobile-agent/attachments/att_1');
    assert(root.innerHTML.includes('mobile-agent-message-attachment'), 'submitted image should appear inside the user message');
    assert(root.innerHTML.includes('face_front.png'), 'submitted image message should keep attachment name');
    assert(!root.innerHTML.includes('mobile-agent-compose-body has-attachment'), 'composer attachment should clear after submit');
  }

  {
    const { context, root } = makeContext({
      hash: '#mobile-agent',
      withIcon: true,
      agentChatResponse: true,
      markdownReply: '# 分析\n\n图片内容分析：\n\n1. 主体：猫咪\n2. 风格：**赛博朋克**\n\n- 氛围：霓虹雨夜\n\n> 适合做成电影感\n\n```text\nneon cat\n```',
    });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '图片内容分析' });
    await context.CW.mobileAgent.submitUnderstand();

    assert(root.innerHTML.includes('<h1>分析</h1>'), 'assistant markdown heading should render');
    assert(root.innerHTML.includes('<ol>'), 'assistant markdown numbered list should render as an ordered list');
    assert(root.innerHTML.includes('<ul>'), 'assistant markdown bullet list should render as a list');
    assert(root.innerHTML.includes('<li>主体：猫咪</li>'), 'assistant markdown list items should render');
    assert(root.innerHTML.includes('<strong>赛博朋克</strong>'), 'assistant markdown bold text should render');
    assert(root.innerHTML.includes('<blockquote>适合做成电影感</blockquote>'), 'assistant markdown quote should render');
    assert(root.innerHTML.includes('<pre><code>neon cat'), 'assistant fenced code should render');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true, agentChatResponse: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '你会干嘛？' });
    await context.CW.mobileAgent.submitUnderstand();

    assert(root.innerHTML.includes('data-action="like-answer"'), 'assistant answer should expose a like action');
    assert(root.innerHTML.includes('data-action="regenerate-answer"'), 'assistant answer should expose a regenerate action');
    assert(root.innerHTML.includes('data-action="delete-answer"'), 'assistant answer should expose a delete action');
    assert(root.innerHTML.includes('M7 10v11'), 'assistant like action should render a local thumbs-up svg');
    assert(root.innerHTML.includes('M21 12a9'), 'assistant regenerate action should render a local rotate svg');
    assert(root.innerHTML.includes('M3 6h18'), 'assistant delete action should render a local trash svg');
    assert(!root.innerHTML.includes('data-icon="thumbs-up"'), 'assistant answer actions should not depend on shared sprite icons');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'like-answer',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('is-liked'), 'liked answer action should become selected');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'like-answer',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(!root.innerHTML.includes('is-liked'), 'liked answer action should be cancellable');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'like-answer',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(root.innerHTML.includes('is-liked'), 'liked answer action should be selectable again after cancel');

    root.dispatch('input', { id: 'mobileAgentText', value: '继续说' });
    await context.CW.mobileAgent.submitUnderstand();
    const followupBody = JSON.parse(calls[calls.length - 1].request.body);
    assert(followupBody.context.memory_summary.includes('重点认可'), 'liked assistant answer should be emphasized in memory summary');
    assert(followupBody.context.messages.some((msg) => msg.important === true), 'liked assistant answer should mark context message as important');
  }

  {
    const { context, root, calls } = makeContext({ hash: '#mobile-agent', withIcon: true, agentChatResponse: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '介绍一下你自己' });
    await context.CW.mobileAgent.submitUnderstand();
    const before = calls.length;

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'regenerate-answer',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.strictEqual(calls.length, before + 1, 'regenerate should request this answer again');
    assert.strictEqual(JSON.parse(calls[calls.length - 1].request.body).text, '介绍一下你自己');

    root.dispatch('click', {
      closest(selector) {
        if (selector !== '[data-action]') return null;
        return {
          getAttribute(name) {
            return {
              'data-action': 'delete-answer',
              'data-message-id': '',
            }[name] || '';
          },
        };
      },
    });
    assert(!root.innerHTML.includes('可以。你想做什么主体的图？'), 'delete should remove the assistant answer from the visible conversation');

    root.dispatch('input', { id: 'mobileAgentText', value: '删除后继续' });
    await context.CW.mobileAgent.submitUnderstand();
    const afterDeleteBody = JSON.parse(calls[calls.length - 1].request.body);
    assert(afterDeleteBody.context.memory_summary.includes('已删除答复仅作参考'), 'deleted answer should remain only as weak reference context');
    assert(!afterDeleteBody.context.memory_summary.includes('重点认可：可以。你想做什么主体的图？'), 'deleted answer should not be promoted as strong memory');
  }

  {
    const { context, root, deferred } = makeContext({ hash: '#mobile-agent', withIcon: true, deferUnderstand: true, withFakeTimers: true });
    vm.runInNewContext(SOURCE, context, { filename: 'mobile-agent.js' });

    root.dispatch('input', { id: 'mobileAgentText', value: '慢一点的问题' });
    const pending = context.CW.mobileAgent.submitUnderstand();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert(root.innerHTML.includes('mobile-agent-thinking'), 'pending request should initially show thinking dots');

    context.runTimers();
    assert(!root.innerHTML.includes('mobile-agent-thinking-dot'), 'timed-out request should stop showing thinking dots');
    assert(root.innerHTML.includes('回复超时'), 'timed-out request should show a timeout answer state');
    assert(root.innerHTML.includes('data-action="regenerate-answer"'), 'timed-out answer should allow regeneration');

    deferred.resolveUnderstand({
      ok: true,
      json() {
        return Promise.resolve({
          ok: true,
          data: {
            response_type: 'chat',
            assistant_message: '迟到的回答不应该覆盖超时状态',
          },
        });
      },
    });
    await pending;
    assert(!root.innerHTML.includes('迟到的回答不应该覆盖超时状态'), 'late response should not overwrite the timeout state');
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
