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
    localStorage: { getItem() { return ''; } },
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
      return Promise.resolve({
        ok: true,
        json() {
          return Promise.resolve({
            ok: true,
            data: {
              display_summary: '后端摘要：海边日落',
              compiled_prompt: 'fallback prompt',
              style: '电影感',
              aspect_ratio: '16:9',
              resolved_workflow: 't2i-test.json',
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
  return { context, root, calls };
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

    root.dispatch('input', { id: 'mobileAgentText', value: '海边日落' });
    await context.CW.mobileAgent.submitUnderstand();

    assert.strictEqual(calls[0].url, '/api/mobile-agent/understand');
    assert.deepStrictEqual(JSON.parse(calls[0].request.body), {
      text: '海边日落',
      has_image: false,
      has_video: false,
    });
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
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
