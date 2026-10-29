import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scratchpad_mcp.bridge import Bridge, safe_path, start_http
from scratchpad_mcp.server import build_plugin


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.project = Path(self.temporary.name)
        self.bridge = Bridge(self.project, 0)
        self.register("edit-a", "edit")
        self.register("edit-b", "edit")

    def tearDown(self):
        self.temporary.cleanup()

    def register(self, peer, target):
        self.bridge.peers[peer] = {"target": target, "place": "Test", "place_id": "123", "seen": time.monotonic()}

    def test_windows_escape_paths_are_rejected(self):
        for relative in ("../escape.luau", "C:/escape.luau", "ReplicatedStorage/../evil.luau",
                         "ReplicatedStorage/foo\\..\\evil.luau", "ReplicatedStorage/C:evil.luau",
                         "ReplicatedStorage/NUL.luau", "ReplicatedStorage/dir./a.luau",
                         "/ReplicatedStorage/a.luau", "ReplicatedStorage//a.luau"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                safe_path(self.bridge.work, relative)
        self.assertEqual(safe_path(self.bridge.work, "ReplicatedStorage/Example.luau").name, "Example.luau")

    def test_sync_retries_until_ack_and_only_selected_peer(self):
        self.bridge.select("edit-a")
        path = safe_path(self.bridge.work, "ReplicatedStorage/Example.luau")
        path.parent.mkdir()
        path.write_text("return 1", encoding="utf-8")
        self.assertEqual(self.bridge.changes("edit-b"), [])
        first = self.bridge.changes("edit-a")[0]
        self.assertEqual(self.bridge.changes("edit-a"), [first])
        with self.assertRaises(ValueError):
            self.bridge.acknowledge({**first, "peer": "edit-b", "ok": True})
        self.bridge.acknowledge({**first, "peer": "edit-a", "ok": True})
        self.assertEqual(self.bridge.changes("edit-a"), [])
        path.write_text("return 2", encoding="utf-8")
        self.assertEqual(len(self.bridge.changes("edit-a")), 1)

    def test_export_snapshots_preserve_source_and_separate_batches(self):
        src = self.project / "src"
        src.mkdir()
        original = src / "keep.txt"
        original.write_text("keep", encoding="utf-8")
        self.bridge.select("edit-a")
        base = {"peer": "edit-a", "batch": "one", "part": 1, "parts": 2,
                "files": {"ReplicatedStorage/A.luau": "return 1"}}
        self.bridge.export(base)
        self.bridge.export({**base, "batch": "two", "files": {"ReplicatedStorage/B.luau": "return 2"}})
        self.bridge.export({**base, "part": 2, "files": {"ReplicatedStorage/C.luau": "return 3"}})
        snapshots = list(self.bridge.exports.iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertTrue((snapshots[0] / "ReplicatedStorage/A.luau").is_file())
        self.assertFalse((snapshots[0] / "ReplicatedStorage/B.luau").exists())
        self.assertEqual(original.read_text(), "keep")
        self.bridge.export({**base, "batch": "empty", "parts": 1, "files": []})

    def test_rejected_export_does_not_delete_source(self):
        self.bridge.select("edit-a")
        with self.assertRaises(ValueError):
            self.bridge.export({"peer": "edit-a", "batch": "bad", "part": 1, "parts": 1,
                                "files": {"ReplicatedStorage/foo\\..\\evil.luau": "bad"}})
        self.assertEqual(list(self.bridge.exports.iterdir()), [])

    def test_command_dispatch_result_and_peer_isolation(self):
        result = []
        thread = threading.Thread(target=lambda: result.append(self.bridge.execute("edit-a", "return 2", timeout=3)))
        thread.start()
        command = self.bridge.poll("edit-a", "edit", "Test", "123")
        self.assertEqual(command["code"], "return 2")
        with self.assertRaises(ValueError):
            self.bridge.result({"id": command["id"], "peer": "edit-b", "ok": True})
        self.bridge.result({"id": command["id"], "peer": "edit-a", "ok": True, "returns": ["2"]})
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["returns"], ["2"])

    def test_queued_timeout_expires_command(self):
        result = self.bridge.execute("edit-a", "return 1", timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["may_still_be_running"])
        self.assertEqual(self.bridge.commands[result["id"]]["state"], "expired")

    def test_dispatched_timeout_reports_uncertain_execution(self):
        result = []
        thread = threading.Thread(target=lambda: result.append(self.bridge.execute("edit-a", "return 1", timeout=1)))
        thread.start()
        command = self.bridge.poll("edit-a", "edit", "Test", "123")
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result[0]["may_still_be_running"])
        # A late result is accepted; the command is not returned to the queue for replay.
        self.bridge.result({"id": command["id"], "peer": "edit-a", "ok": True})
        self.assertEqual(self.bridge.commands[command["id"]]["state"], "completed")

    def test_http_requires_token_and_blocks_browser_origin_and_file_serving(self):
        http, thread = start_http(self.bridge)
        base = f"http://127.0.0.1:{self.bridge.port}"
        try:
            for headers in ({}, {"X-Scratchpad-Token": self.bridge.token, "Origin": "https://example.com"}):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(Request(base + "/api/status", headers=headers), timeout=2)
                self.assertEqual(raised.exception.code, 403)
                raised.exception.close()
            headers = {"X-Scratchpad-Token": self.bridge.token}
            with urlopen(Request(base + "/api/status", headers=headers), timeout=2) as response:
                self.assertEqual(json.load(response)["version"], "0.1.0a1")
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(base + "/work/anything", headers=headers), timeout=2)
            self.assertEqual(raised.exception.code, 404)
            raised.exception.close()
            for body in (b"[]", b"not json"):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(Request(base + "/api/export", headers=headers, data=body), timeout=2)
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()
        finally:
            http.shutdown()
            http.server_close()
            thread.join(2)

    def test_plugin_build_round_trip(self):
        import xml.etree.ElementTree as ET
        xml = build_plugin()
        source = ET.fromstring(xml).find(".//ProtectedString").text
        self.assertIn("X-Scratchpad-Token", source)
        self.assertIn("/api/ack", source)
        self.assertNotIn("Claude Code", source)


if __name__ == "__main__":
    unittest.main()
