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
    this.listeners[type]({ target });
  }
}

function makeContext(options = {}) {
  const root = new FakeElement('mobileAgentRoot');
  const storage = Object.assign({}, options.storage || {});
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
    fetch(url, request) {
      calls.push({ url, request });
      if (url === '/api/generate') {
        return Promise.resolve({
          ok: true,
          json() {
            return Promise.resolve({ job_id: 'job_mobile_1', seed: 123 });
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
      return Promise.resolve({
        ok: true,
        json() {
          return Promise.resolve({
            ok: true,
            data: {
              intent: body.context && body.context.last_result ? 'image_to_image' : 'text_to_image',
              display_summary: '后端摘要：海边日落',
              compiled_prompt: 'fallback prompt',
              style: '电影感',
              aspect_ratio: '16:9',
              workflow: body.context && body.context.last_result ? 'default_image_to_image' : 'default_text_to_image',
              resolved_workflow: body.context && body.context.last_result ? 'i2i-test.json' : 't2i-test.json',
              field_values: { '1::text': 'prompt' },
              width: 720,
              height: 1280,
              options: {
                allowed_styles: ['电影感', '写实'],
                allowed_ratios: ['16:9', '1:1'],
              },
            },
          });
        },
      });
    },
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
  return { context, root, calls, storage };
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
      context: {
        last_result: null,
        messages: [{ role: 'user', text: '海边日落' }],
      },
    });
    assert(root.innerHTML.includes('mobile-agent-chat'), 'submit should switch into a conversation view');
    assert(root.innerHTML.includes('mobile-agent-message-user'), 'conversation should keep the user message');
    assert(root.innerHTML.includes('mobile-agent-confirm-card'), 'assistant response should render as an inline confirmation card');
    assert(root.innerHTML.includes('后端摘要：海边日落'), 'confirm should render backend display summary');
    assert(root.innerHTML.includes('电影感'), 'confirm should render selected style and style chips');
    assert(root.innerHTML.includes('16:9'), 'confirm should render selected ratio and ratio chips');
    assert(root.innerHTML.includes('写实'), 'confirm should render allowed style chips');
    assert(root.innerHTML.includes('1:1'), 'confirm should render allowed ratio chips');

    await context.CW.mobileAgent.submitGenerate();

    assert.strictEqual(calls[1].url, '/api/generate');
    const generateBody = JSON.parse(calls[1].request.body);
    assert.deepStrictEqual(generateBody, {
      workflow: 't2i-test.json',
      fields: { '1::text': 'prompt' },
      width: 720,
      height: 1280,
    });
    assert(root.innerHTML.includes('正在生成'), 'generation submit should append a pending assistant message');

    context.CW.mobileAgent.handleJobUpdate({
      id: 'job_mobile_1',
      status: 'done',
      image: 'user1/2026-05-25/cat.png',
      thumb: 'user1/2026-05-25/cat-thumb.jpg',
      media_type: 'image',
      workflow: 't2i-test.json',
    });

    assert(root.innerHTML.includes('/api/thumbs/user1/2026-05-25/cat-thumb.jpg'), 'completed job should render image result in the conversation');
    assert(root.innerHTML.includes('生成完成'), 'completed job should label the result as done');
    assert(context.CW.mobileAgent.getConversationContext().last_result.image === 'user1/2026-05-25/cat.png', 'completed job should become the next-turn image context');

    root.dispatch('input', { id: 'mobileAgentText', value: '改成赛博朋克风格' });
    await context.CW.mobileAgent.submitUnderstand();

    const followupBody = JSON.parse(calls[2].request.body);
    assert.strictEqual(followupBody.context.last_result.image, 'user1/2026-05-25/cat.png');
    assert.strictEqual(followupBody.text, '改成赛博朋克风格');
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

    assert(root.innerHTML.includes('请先登录后使用移动端创作。'), 'logged-out mobile agent should prompt for login before calling understand');
    assert.strictEqual(context.loginShown, true, 'logged-out mobile agent should open the login modal when available');
    assert.strictEqual(calls.length, 0, 'logged-out mobile agent should not call the understand API');
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
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
