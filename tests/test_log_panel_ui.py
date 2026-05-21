import json
import subprocess
import textwrap
import unittest


class LogPanelUiTest(unittest.TestCase):
    def test_clear_log_hides_old_entries_after_reload_without_deleting_server_logs(self):
        script = textwrap.dedent(
            r"""
            const fs = require('fs');
            const vm = require('vm');

            class ClassList {
              constructor(names) { this.set = new Set(names || []); }
              add(...names) { names.forEach((name) => this.set.add(name)); }
              remove(...names) { names.forEach((name) => this.set.delete(name)); }
              contains(name) { return this.set.has(name); }
              toggle(name, force) {
                const next = force === undefined ? !this.set.has(name) : !!force;
                if (next) this.set.add(name);
                else this.set.delete(name);
                return next;
              }
            }

            class Element {
              constructor(id) {
                this.id = id || '';
                this.children = [];
                this.parentNode = null;
                this.dataset = {};
                this.style = { setProperty: () => {}, removeProperty: () => {} };
                this.classList = new ClassList(id === 'logPanel' ? ['log-panel--hidden'] : []);
                this.value = '';
                this.textContent = '';
                this.innerHTML = '';
                this.scrollTop = 0;
                this.scrollHeight = 0;
              }
              appendChild(child) {
                child.parentNode = this;
                this.children.push(child);
                this.scrollHeight = this.children.length;
                return child;
              }
              remove() {
                if (this.parentNode) {
                  this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
                  this.parentNode = null;
                }
              }
              querySelector() { return null; }
              addEventListener() {}
            }

            const elements = {
              logPanel: new Element('logPanel'),
              logBody: new Element('logBody'),
              logCount: new Element('logCount'),
              logLevelFilter: new Element('logLevelFilter'),
              colRight: new Element('colRight'),
              tbLogBtn: new Element('tbLogBtn'),
              logDockBtn: new Element('logDockBtn')
            };
            elements.logLevelFilter.value = '';
            const storage = {};
            let fetchCalls = 0;

            global.window = {
              CW: {
                auth: {
                  getCurrentUser: () => ({ id: 'u1', username: 'alice' })
                }
              },
              matchMedia: () => ({ matches: false }),
              addEventListener: () => {}
            };
            global.CW = window.CW;
            global.location = { pathname: '/', protocol: 'http:' };
            global.localStorage = {
              getItem: (key) => Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null,
              setItem: (key, value) => { storage[key] = String(value); }
            };
            global.document = {
              body: new Element('body'),
              readyState: 'loading',
              getElementById: (id) => elements[id] || null,
              createElement: () => new Element('created'),
              addEventListener: () => {}
            };
            global.requestAnimationFrame = (fn) => fn();
            global.setTimeout = () => 0;
            global.Date.now = () => 200000;
            global.fetch = () => {
              fetchCalls += 1;
              return Promise.resolve({
                ok: true,
                json: () => Promise.resolve([
                  { ts: 199, level: 'info', phase: '生成', msg: 'old', job_id: '', details: '' },
                  { ts: 201, level: 'info', phase: '生成', msg: 'new', job_id: '', details: '' }
                ])
              });
            };

            vm.runInThisContext(fs.readFileSync('static/js/modules/log_panel.js', 'utf8'));
            window.CW.clearLog();
            window.CW.toggleLog();

            Promise.resolve().then(() => Promise.resolve()).then(() => {
              console.log(JSON.stringify({
                fetchCalls,
                entries: window.CW._logEntries.map((entry) => entry.msg),
                count: elements.logCount.textContent,
                storedKeys: Object.keys(storage)
              }));
            });
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

        self.assertEqual(data["fetchCalls"], 1)
        self.assertEqual(data["entries"], ["new"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["storedKeys"], ["cw_log_clear_after:u1"])


if __name__ == "__main__":
    unittest.main()
