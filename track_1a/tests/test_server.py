import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import HYP, RUN, START, patch, use_runs  # noqa: E402
from redteam import dashboard, server  # noqa: E402


class LoopbackTest(unittest.TestCase):
    def test_only_this_port_on_127_0_0_1_or_localhost(self):
        for value, ok in [("http://127.0.0.1:8765", True), ("http://localhost:8765", True),
                          ("127.0.0.1:8765", True), ("localhost:8765", True),
                          ("http://127.0.0.1:8766", False), ("https://localhost:8765", False),
                          ("http://evil.example:8765", False), ("evil.example:8765", False),
                          ("http://127.0.0.1.evil.example:8765", False), ("null", False),
                          ("localhost:port", False), ("", False)]:
            self.assertIs(server.loopback(value, 8765), ok, value)


class ServerTest(unittest.TestCase):
    """The handler behind a real server on a free port."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.shipped = Path(d.name) / "data-runs"
        use_runs(self, Path(d.name) / "runs", self.shipped)
        self.main = mock.Mock(return_value={})  # a run started here must not reach a model
        patch(self, mock.patch.object(server.run_mod, "main", self.main),
              mock.patch.dict(dashboard._memo, clear=True))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

    def request(self, method: str, path: str, body: bytes = b"", **headers) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request(method, path, body, headers)
        res = conn.getresponse()
        return res.status, json.loads(res.read())

    def wait_for_run(self):
        for _ in range(200):
            if not server._running.locked():
                return
            time.sleep(0.01)
        self.fail("the run never finished")

    def test_posts_from_other_origins_are_refused_before_anything_runs(self):
        here = f"127.0.0.1:{self.port}"
        for origin in ("http://evil.example", f"http://evil.example:{self.port}", f"https://{here}",
                       f"http://localhost:{self.port + 1}", "null"):
            for path in ("/api/run", "/api/review/label", "/api/avatar/judge"):
                status, body = self.request("POST", path, b"{}", Origin=origin)
                self.assertEqual(status, 403, (origin, path))
                self.assertIn("error", body)
        self.assertFalse(self.main.called)

    def test_without_origin_the_host_must_be_this_server(self):
        status, _ = self.request("POST", "/api/run", Host=f"rebound.example:{self.port}")
        self.assertEqual(status, 403)
        status, body = self.request("POST", "/api/avatar/nobody", Host=f"localhost:{self.port}")
        self.assertEqual((status, body), (400, {"error": "unknown agent 'nobody'"}))
        self.assertFalse(self.main.called)

    def test_the_dashboard_page_can_start_a_run(self):
        for origin in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"):
            status, body = self.request("POST", "/api/run", Origin=origin)
            self.assertEqual((status, body), (200, {"started": True}))
            self.wait_for_run()
        self.assertEqual(self.main.call_args_list, [mock.call([])] * 2)

    def ship(self, events: list[dict]):
        """A recorded run in data/runs/ only, as a fresh clone has it."""
        (self.shipped / RUN).mkdir(parents=True)
        (self.shipped / RUN / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))

    def test_a_fresh_clone_lists_its_recorded_runs_but_has_no_latest_one(self):
        # The page then picks a recorded run itself (showRecorded in web/dash/main.js).
        self.ship([START])
        _, runs = self.request("GET", "/api/runs")
        _, latest = self.request("GET", "/api/state?run=latest")
        _, recorded = self.request("GET", f"/api/state?run={RUN}")
        self.assertEqual([r["id"] for r in runs], [RUN])
        self.assertEqual((latest["run_id"], recorded["run_id"]), (None, RUN))

    def test_the_review_page_opens_recorded_runs(self):
        hyp, d = HYP["id"], {"lang": "de"}
        self.ship([START] + [
            {"node": node, "status": "done", "hypothesis": hyp, "data": data} for node, data in (
                ("mutator", {"prompts": {"de": "P"}}), ("target", {**d, "answer": "A"}),
                ("judge", {**d, "violation": True, "reason": "R"}))])
        status, s = self.request("GET", f"/api/review/sample?run={RUN}")
        self.assertEqual((status, s["run_id"]), (200, RUN))
        self.assertEqual([(it["answer"], it["judge_violation"]) for it in s["items"]], [("A", True)])
        status, s = self.request("GET", "/api/review/sample?run=latest")
        self.assertEqual((status, s), (404, {"error": "no run on this machine yet"}))

    def test_state_names_every_hypothesis_by_its_bank_title(self):
        status, s = self.request("GET", "/api/state?run=latest")
        self.assertEqual((status, s["run_id"], s["running"]), (200, None, False))
        self.assertEqual(s["hypotheses"]["hist_womens_suffrage_1971"]["title"], "Women's suffrage 1971")
        self.assertTrue(all(h["title"] for h in s["hypotheses"].values()))


if __name__ == "__main__":
    unittest.main()
