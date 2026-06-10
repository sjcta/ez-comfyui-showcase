import json
import subprocess
import textwrap
import unittest


class ToastThrottleTest(unittest.TestCase):
    def test_generation_toasts_only_allow_converged_job_states(self):
        script = textwrap.dedent(
            r"""
            const fs = require('fs');
            const vm = require('vm');

            class Element {
              constructor(tag) {
                this.tag = tag;
                this.children = [];
                this.parentNode = null;
                this.id = '';
                this.className = '';
                this._text = '';
                this.attrs = {};
              }
              appendChild(child) {
                child.parentNode = this;
                this.children.push(child);
                return child;
              }
              removeChild(child) {
                this.children = this.children.filter((x) => x !== child);
                child.parentNode = null;
              }
              querySelectorAll(selector) {
                if (selector !== '.toast') return [];
                return this.children.filter((child) => String(child.className || '').includes('toast'));
              }
              setAttribute(name, value) {
                this.attrs[name] = String(value);
              }
              getAttribute(name) {
                return this.attrs[name] || null;
              }
              querySelector(selector) {
                if (selector === '.toast-close') return { addEventListener: () => {} };
                return null;
              }
              set innerHTML(value) {
                this._text = String(value || '').replace(/<[^>]+>/g, '');
              }
              get textContent() {
                return this._text;
              }
            }

            const elements = {};
            global.document = {
              body: new Element('body'),
              getElementById: (id) => elements[id] || null,
              createElement: (tag) => new Element(tag)
            };
            const originalAppend = document.body.appendChild.bind(document.body);
            document.body.appendChild = (child) => {
              if (child.id) elements[child.id] = child;
              return originalAppend(child);
            };
            global.window = {
              __APP__: {
                escH: (s) => String(s),
                escA: (s) => String(s),
                $: () => null,
                $$: () => [],
                API: '',
                jobs: {}
              },
              CW: { icon: () => '' }
            };
            global.CW = window.CW;
            global.setTimeout = () => 0;

            vm.runInThisContext(fs.readFileSync('static/js/modules/ui.js', 'utf8'));
            window.CW.toast('abc 文生图 开始出图', 'generating');
            window.CW.toast('abc 文生图 排队中', 'queued');
            window.CW.toast('abc 文生图 出图中', 'generating');
            window.CW.toast('abc 文生图 拉取图片', 'queued');
            window.CW.toast('abc 文生图 结束出图', 'done');

            const container = elements.toastContainer;
            console.log(JSON.stringify({
              count: container.children.length,
              messages: container.children.map((child) => child.textContent),
              scopes: container.children.map((child) => child.getAttribute('data-toast-scope'))
            }));
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=".",
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout.strip())

        self.assertEqual(data["count"], 1)
        self.assertFalse(any("排队中" in msg for msg in data["messages"]))
        self.assertFalse(any("出图中" in msg for msg in data["messages"]))
        self.assertTrue(any("结束出图" in msg for msg in data["messages"]))
        self.assertEqual(data["scopes"], ["generation"])
        self.assertFalse(any("开始出图" in msg for msg in data["messages"]))
        self.assertFalse(any("拉取图片" in msg for msg in data["messages"]))


if __name__ == "__main__":
    unittest.main()
