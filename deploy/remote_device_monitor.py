from __future__ import annotations

import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


previous_cpu: tuple[int, int] | None = None


def cpu_percent() -> float | None:
    global previous_cpu
    try:
        fields = [int(value) for value in open("/proc/stat", encoding="utf-8").readline().split()[1:]]
        idle, total = fields[3] + fields[4], sum(fields)
        current = (idle, total)
        if previous_cpu is None:
            previous_cpu = current
            return 0.0
        idle_delta, total_delta = idle - previous_cpu[0], total - previous_cpu[1]
        previous_cpu = current
        return round((1 - idle_delta / total_delta) * 100, 1) if total_delta else 0.0
    except (OSError, ValueError, IndexError):
        return None


def memory_stats() -> tuple[int | None, int | None, float | None]:
    try:
        values = {}
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
        total, available = values["MemTotal"], values["MemAvailable"]
        used = total - available
        return used, total, round(used / total * 100, 1)
    except (OSError, ValueError, KeyError):
        return None, None, None


def optional_number(value: str) -> float | None:
    value = value.strip()
    return None if value in {"", "N/A", "[N/A]"} else float(value)


def gpu_stats() -> dict:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed,power.draw",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=3, check=True,
    )
    values = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",")]
    used_mb, total_mb = optional_number(values[2]), optional_number(values[3])
    return {
        "device_name": values[0], "gpu_percent": optional_number(values[1]),
        "vram_used": used_mb * 1024**2 if used_mb is not None else None,
        "vram_total": total_mb * 1024**2 if total_mb is not None else None,
        "vram_percent": round(used_mb / total_mb * 100, 1) if used_mb is not None and total_mb else None,
        "temperature": optional_number(values[4]), "fan_percent": optional_number(values[5]),
        "power_watts": optional_number(values[6]),
    }


def snapshot() -> dict:
    ram_used, ram_total, ram_percent = memory_stats()
    payload = {
        "ok": True, "timestamp": time.time(), "cpu_percent": cpu_percent(),
        "ram_used": ram_used, "ram_total": ram_total, "ram_percent": ram_percent,
    }
    try:
        payload.update(gpu_stats())
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        payload.update({key: None for key in (
            "device_name", "gpu_percent", "vram_used", "vram_total", "vram_percent",
            "temperature", "fan_percent", "power_watts",
        )})
    return payload


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in {"/health", "/api/device-stats"}:
            self.send_error(404)
            return
        body = json.dumps({"ok": True} if self.path == "/health" else snapshot()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8190), Handler).serve_forever()
