import json
from pathlib import Path
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PollManagerResumeTest(unittest.TestCase):
    def test_missing_active_job_refreshes_history(self):
        script = textwrap.dedent(
            r"""
            const fs = require('fs');
            const vm = require('vm');

            const jobs = {
              'job-1': { id: 'job-1', status: 'generating', progress: { pct: 80 } }
            };
            const calls = { loadHistory: 0, rerender: 0 };

            global.window = {
              __APP__: { API: '', jobs },
              CW: {
                auth: {
                  isLoggedIn: () => true,
                  apiFetch: async (url) => ({ json: async () => [] })
                },
                loadHistory: async () => { calls.loadHistory += 1; },
                forceGalleryRerender: () => { calls.rerender += 1; },
                syncComfyServiceButton: () => {}
              }
            };
            global.document = { addEventListener: () => {} };
            global.setTimeout = () => 0;
            global.clearTimeout = () => {};
            global.setInterval = () => 0;
            global.clearInterval = () => {};
            global.WebSocket = function() {};
            global.location = { protocol: 'http:', host: '127.0.0.1:18000', pathname: '/' };

            vm.runInThisContext(fs.readFileSync('static/js/modules/poll_manager.js', 'utf8'));
            const manager = new window.CW.PollManager();
            manager._doHTTPPoll();

            setImmediate(() => {
              console.log(JSON.stringify({
                jobExists: Object.prototype.hasOwnProperty.call(jobs, 'job-1'),
                loadHistory: calls.loadHistory,
                rerender: calls.rerender
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

        self.assertFalse(data["jobExists"])
        self.assertGreaterEqual(data["loadHistory"], 1)
        self.assertGreaterEqual(data["rerender"], 1)

    def test_status_change_keeps_previous_job_until_on_job_update(self):
        source = (ROOT / "static/js/modules/poll_manager.js").read_text("utf-8")
        self.assertIn("var prev = jobs[id];", source)
        self.assertIn("self.onJobUpdate(sj);", source)
        self.assertNotIn("jobs[id] = sj;\n            self.onJobUpdate(sj);", source)

        app_source = (ROOT / "static/js/app.js").read_text("utf-8")
        self.assertIn("const prev = jobs[id];", app_source)
        self.assertIn("onJobUpdate(sj);", app_source)
        self.assertNotIn("jobs[id] = sj;\n          onJobUpdate(sj);", app_source)


if __name__ == "__main__":
    unittest.main()
