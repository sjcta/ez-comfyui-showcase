import json
import subprocess
import textwrap
import unittest


class StatusButtonRuntimeTest(unittest.TestCase):
    def test_job_updates_keep_cached_dual_instance_progress_visible(self):
        script = textwrap.dedent(
            r"""
            const fs = require('fs');
            const vm = require('vm');

            function el() {
              return {
                textContent: '',
                className: '',
                title: '',
                dataset: {},
                style: {},
                classList: { add() {}, remove() {} }
              };
            }

            const elements = {
              '#svcComfyUI': el(),
              '#comfyState': el(),
              '#statusbar': el()
            };
            const jobs = {
              a: { id: 'a', status: 'generating', instance: 'A', target_node_id: 'n1', progress: { pct: 30 } },
              b: { id: 'b', status: 'generating', instance: 'B', target_node_id: 'n1', progress: { pct: 10 } }
            };
            let statusPayload = {
              instances: [
                { name: 'A', node_id: 'n1', up: true, queue_running: 1, queue_pending: 0, progress: 30 },
                { name: 'B', node_id: 'n1', up: true, queue_running: 1, queue_pending: 0, progress: 10 }
              ],
              gpu: {}
            };

            global.window = {
              __APP__: {
                API: '',
                jobs,
                $: (selector) => elements[selector] || null,
                $$: () => [],
                escH: (value) => String(value),
                escA: (value) => String(value)
              },
              CW: {},
              matchMedia: () => ({ matches: false })
            };
            global.fetch = async () => ({ json: async () => statusPayload });

            vm.runInThisContext(fs.readFileSync('static/js/modules/status.js', 'utf8'));

            (async () => {
              await window.CW.pollStatus();
              const initial = elements['#comfyState'].textContent;
              jobs.b.progress.pct = 22;
              window.CW.syncComfyServiceButton();
              const afterJobUpdate = elements['#comfyState'].textContent;
              jobs.a.status = 'done';
              statusPayload = {
                instances: [
                  { name: 'A', node_id: 'n1', up: true, queue_running: 0, queue_pending: 0, progress: 0 },
                  { name: 'B', node_id: 'n1', up: true, queue_running: 1, queue_pending: 0, progress: 22 }
                ],
                gpu: {}
              };
              await window.CW.pollStatus();
              const afterStatusRefresh = elements['#comfyState'].textContent;
              console.log(JSON.stringify({ initial, afterJobUpdate, afterStatusRefresh }));
            })().catch((err) => {
              console.error(err && err.stack ? err.stack : err);
              process.exit(1);
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

        self.assertEqual(data["initial"], "A: 30% | B: 10%")
        self.assertEqual(data["afterJobUpdate"], "A: 30% | B: 22%")
        self.assertEqual(data["afterStatusRefresh"], "运行中 22%")

    def test_untracked_remote_running_is_not_displayed_as_zero_percent(self):
        script = textwrap.dedent(
            r"""
            const fs = require('fs');
            const vm = require('vm');

            function el() {
              return {
                textContent: '',
                className: '',
                title: '',
                dataset: {},
                style: {},
                classList: { add() {}, remove() {} }
              };
            }

            const elements = {
              '#svcComfyUI': el(),
              '#comfyState': el(),
              '#statusbar': el()
            };
            global.window = {
              __APP__: {
                API: '',
                jobs: {},
                $: (selector) => elements[selector] || null,
                $$: () => [],
                escH: (value) => String(value),
                escA: (value) => String(value)
              },
              CW: {},
              matchMedia: () => ({ matches: false })
            };
            global.fetch = async () => ({
              json: async () => ({
                instances: [
                  {
                    name: 'A',
                    node_id: 'n1',
                    up: true,
                    queue_running: 1,
                    queue_pending: 0,
                    progress: 0,
                    progress_known: false,
                    remote_untracked_running: true
                  }
                ],
                gpu: {}
              })
            });

            vm.runInThisContext(fs.readFileSync('static/js/modules/status.js', 'utf8'));

            (async () => {
              await window.CW.pollStatus();
              console.log(JSON.stringify({ text: elements['#comfyState'].textContent }));
            })().catch((err) => {
              console.error(err && err.stack ? err.stack : err);
              process.exit(1);
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

        self.assertEqual(data["text"], "未追踪任务中")
        self.assertNotIn("0%", data["text"])

    def test_statusbar_vram_text_includes_gpu_pressure(self):
        script = textwrap.dedent(
            r"""
            const fs = require('fs');
            const vm = require('vm');

            function el() {
              return {
                textContent: '',
                className: '',
                title: '',
                dataset: {},
                style: {},
                classList: { add() {}, remove() {} },
                appendChild() {}
              };
            }

            const elements = {
              '#svcComfyUI': el(),
              '#comfyState': el(),
              '#statusbar': el(),
              '#vramFill': el(),
              '#vramText': el(),
              '#gpuTemp': el(),
              '#gpuUtil': el(),
              '#vramSegments': el()
            };
            global.document = { createElement: () => el() };
            global.window = {
              __APP__: {
                API: '',
                jobs: {},
                $: (selector) => elements[selector] || null,
                $$: () => [],
                escH: (value) => String(value),
                escA: (value) => String(value),
                currentTargetInstance: 'A'
              },
              CW: {},
              matchMedia: () => ({ matches: true })
            };
            global.fetch = async () => ({
              json: async () => ({
                instances: [
                  {
                    name: 'A',
                    node_id: 'n1',
                    up: true,
                    queue_running: 0,
                    queue_pending: 0,
                    gpu: {
                      vram_used_mb: 63180,
                      vram_total_mb: 122573,
                      vram_pct: 52,
                      temp_c: 49,
                      util_pct: 37
                    }
                  }
                ],
                gpu: {}
              })
            });

            vm.runInThisContext(fs.readFileSync('static/js/modules/status.js', 'utf8'));

            (async () => {
              await window.CW.pollStatus();
              console.log(JSON.stringify({
                text: elements['#vramText'].textContent,
                state: elements['#statusbar'].dataset.state
              }));
            })().catch((err) => {
              console.error(err && err.stack ? err.stack : err);
              process.exit(1);
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

        self.assertIn("GPU 37%", data["text"])
        self.assertIn("49 °C", data["text"])
        self.assertEqual(data["state"], "busy")


if __name__ == "__main__":
    unittest.main()
