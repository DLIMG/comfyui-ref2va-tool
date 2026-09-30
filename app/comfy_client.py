from __future__ import annotations

import json
import mimetypes
import uuid
import threading
import time
from typing import Any, Callable
from urllib import error, request


class ComfyError(RuntimeError):
    pass


class LiveProgressTracker:
    def __init__(self):
        self._samples: dict[tuple[str, str], dict[str, float]] = {}
        self._latest: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def ingest(self, message: dict[str, Any], now: float | None = None) -> None:
        if message.get("type") != "progress_state":
            return
        data = message.get("data") or {}
        prompt_id = str(data.get("prompt_id") or "")
        if not prompt_id:
            return
        timestamp = time.monotonic() if now is None else now
        running = [
            (str(node_id), node) for node_id, node in (data.get("nodes") or {}).items()
            if node.get("state") == "running" and float(node.get("max") or 0) > 1
        ]
        if not running:
            return
        node_id, node = max(running, key=lambda item: float(item[1].get("max") or 0))
        value, maximum = float(node.get("value") or 0), float(node.get("max") or 0)
        key = (prompt_id, node_id)
        with self._lock:
            sample = self._samples.setdefault(key, {"time": timestamp, "value": value})
            delta_value, delta_time = value - sample["value"], timestamp - sample["time"]
            seconds_per_step = delta_time / delta_value if delta_value > 0 and delta_time > 0 else None
            previous = self._latest.get(prompt_id, {})
            if seconds_per_step is None:
                seconds_per_step = previous.get("seconds_per_step")
            remaining = round((maximum - value) * seconds_per_step) if seconds_per_step else None
            self._latest[prompt_id] = {
                "progress_percent": round(value / maximum * 100, 1),
                "value": value,
                "max": maximum,
                **({"seconds_per_step": seconds_per_step, "sample_remaining_seconds": remaining}
                   if seconds_per_step else {}),
            }

    def get(self, prompt_id: str) -> dict[str, float] | None:
        with self._lock:
            value = self._latest.get(prompt_id)
            return dict(value) if value else None


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.live_progress = LiveProgressTracker()
        self._listener_lock = threading.Lock()
        self._listener_client_id = ""
        self._listener_thread: threading.Thread | None = None

    def _ensure_progress_listener(self, client_id: str) -> None:
        with self._listener_lock:
            if self._listener_thread and self._listener_thread.is_alive() and self._listener_client_id == client_id:
                return
            self._listener_client_id = client_id
            self._listener_thread = threading.Thread(
                target=self._listen_progress, args=(client_id,), daemon=True
            )
            self._listener_thread.start()

    def _listen_progress(self, client_id: str) -> None:
        try:
            import websocket
            ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws = websocket.create_connection(f"{ws_url}/ws?clientId={client_id}", timeout=self.timeout)
            while self._listener_client_id == client_id:
                payload = ws.recv()
                if isinstance(payload, str):
                    self.live_progress.ingest(json.loads(payload))
        except Exception:
            return

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("error", body)
            except json.JSONDecodeError:
                message = body
            raise ComfyError(f"ComfyUI HTTP {exc.code}: {message}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise ComfyError(f"无法连接 ComfyUI: {exc}") from exc

    def _multipart(self, path: str, fields: dict[str, str], filename: str, content: bytes) -> dict[str, Any]:
        boundary = f"----ref2va-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"), b"\r\n",
            ])
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content, b"\r\n", f"--{boundary}--\r\n".encode(),
        ])
        req = request.Request(
            self.base_url + path, data=b"".join(chunks), method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with request.urlopen(req, timeout=max(self.timeout, 60)) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            raise ComfyError(f"上传到 ComfyUI 失败: {exc}") from exc

    def system_stats(self):
        return self._request("GET", "/system_stats")

    def object_info(self):
        return self._request("GET", "/object_info")

    def logs(self):
        """Return ComfyUI's in-memory terminal log buffer."""
        return self._request("GET", "/internal/logs/raw")

    def free_memory(self, unload_models: bool = False):
        """Ask ComfyUI to release caches, optionally unloading resident models."""
        return self._request(
            "POST", "/free",
            {"unload_models": bool(unload_models), "free_memory": True},
        )

    def queue(self):
        return self._request("GET", "/queue")

    def history(self, prompt_id: str):
        return self._request("GET", f"/history/{prompt_id}")

    def submit(self, workflow: dict[str, Any], client_id: str):
        self._ensure_progress_listener(client_id)
        return self._request("POST", "/prompt", {"prompt": workflow, "client_id": client_id})

    def progress(self, prompt_id: str):
        return self.live_progress.get(prompt_id)

    def watch_progress(self, client_id: str) -> None:
        if client_id:
            self._ensure_progress_listener(client_id)

    def cancel(self, prompt_id: str):
        return self._request("POST", f"/api/jobs/{prompt_id}/cancel")

    def upload_input(self, filename: str, content: bytes, subfolder: str = "codex_ref2va_tool"):
        return self._multipart(
            "/upload/image",
            {"subfolder": subfolder, "type": "input", "overwrite": "true"},
            filename,
            content,
        )

    def download_output(
        self,
        output: dict[str, str],
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> bytes:
        from urllib.parse import urlencode

        query = urlencode({
            "filename": output.get("filename", ""),
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        })
        try:
            with request.urlopen(f"{self.base_url}/view?{query}", timeout=max(self.timeout, 120)) as response:
                total_header = response.headers.get("Content-Length")
                total = int(total_header) if total_header and total_header.isdigit() else None
                received = 0
                chunks: list[bytes] = []
                if progress_callback:
                    progress_callback(0, total)
                while chunk := response.read(1024 * 1024):
                    chunks.append(chunk)
                    received += len(chunk)
                    if progress_callback:
                        progress_callback(received, total)
                return b"".join(chunks)
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            raise ComfyError(f"下载 ComfyUI 输出失败: {exc}") from exc
