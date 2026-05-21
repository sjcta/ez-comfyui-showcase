import json
import subprocess
import textwrap
import unittest


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


if __name__ == "__main__":
    unittest.main()
