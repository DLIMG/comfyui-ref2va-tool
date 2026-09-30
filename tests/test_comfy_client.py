import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import app.comfy_client as comfy_client_module
from app.comfy_client import ComfyClient, ComfyError


class Handler(BaseHTTPRequestHandler):
    submitted = None
    uploaded = None

    def log_message(self, *_args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/system_stats":
            self._send(200, {"system": {"comfyui_version": "test"}})
        elif parsed.path == "/internal/logs/raw":
            self._send(200, {"entries": [{"t": "2026-01-01T00:00:00", "m": "[INFO] ready\n"}]})
        elif parsed.path == "/queue":
            self._send(200, {"queue_running": [], "queue_pending": []})
        elif parsed.path == "/history/abc":
            self._send(200, {"abc": {"status": {"completed": True}, "outputs": {}}})
        elif parsed.path == "/view":
            assert parse_qs(parsed.query)["filename"] == ["movie.mp4"]
            payload = b"video-bytes"
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._send(500, {"error": "boom"})

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(size)
        if self.path == "/upload/image":
            Handler.uploaded = payload
            self._send(200, {"name": "reference.png", "subfolder": "codex_ref2va_tool", "type": "input"})
        else:
            Handler.submitted = json.loads(payload)
            self._send(200, {"prompt_id": "abc", "number": 1, "node_errors": {}})


@pytest.fixture()
def client():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ComfyClient(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()


def test_client_calls_local_api(client):
    assert client.system_stats()["system"]["comfyui_version"] == "test"
    assert client.logs()["entries"][0]["m"] == "[INFO] ready\n"
    assert client.queue()["queue_running"] == []
    assert client.history("abc")["abc"]["status"]["completed"] is True


def test_submit_wraps_prompt(client):
    result = client.submit({"1": {"class_type": "X", "inputs": {}}}, "client-1")
    assert result["prompt_id"] == "abc"
    assert Handler.submitted["prompt"]["1"]["class_type"] == "X"
    assert Handler.submitted["client_id"] == "client-1"


def test_free_memory_keeps_models_loaded_by_default(client):
    client.free_memory()

    assert Handler.submitted == {"unload_models": False, "free_memory": True}


def test_upload_input_and_download_output(client):
    uploaded = client.upload_input("reference.png", b"image-bytes")
    progress = []
    downloaded = client.download_output(
        {"filename": "movie.mp4", "subfolder": "clips", "type": "output"},
        lambda received, total: progress.append((received, total)),
    )

    assert uploaded["subfolder"] == "codex_ref2va_tool"
    assert b'filename="reference.png"' in Handler.uploaded
    assert b"image-bytes" in Handler.uploaded
    assert downloaded == b"video-bytes"
    assert progress[-1][0] == len(downloaded)
    assert progress[-1][1] == len(downloaded)


def test_error_response_raises_readable_error(client):
    with pytest.raises(ComfyError, match="boom"):
        client._request("GET", "/missing")


def test_live_progress_tracker_estimates_from_actual_sampler_step_time():
    assert hasattr(comfy_client_module, "LiveProgressTracker")
    tracker = comfy_client_module.LiveProgressTracker()
    tracker.ingest({"type": "progress_state", "data": {"prompt_id": "p1", "nodes": {
        "125": {"state": "running", "value": 1, "max": 8}
    }}}, now=100.0)
    tracker.ingest({"type": "progress_state", "data": {"prompt_id": "p1", "nodes": {
        "125": {"state": "running", "value": 2, "max": 8}
    }}}, now=120.0)

    progress = tracker.get("p1")
    assert progress["progress_percent"] == 25.0
    assert progress["sample_remaining_seconds"] == 120
    assert progress["seconds_per_step"] == 20.0
