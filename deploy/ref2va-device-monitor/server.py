from __future__ import annotations

import json
import os
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
previous_cpu: tuple[int, int] | None = None


def cpu_percent() -> float | None:
    global previous_cpu
    try:
        fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
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
        for line in Path("/proc/meminfo").read_text().splitlines():
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
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed,power.draw",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True, text=True, timeout=3, check=True,
    )
    values = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",")]
    used_mb, total_mb = optional_number(values[2]), optional_number(values[3])
    return {
        "device_name": values[0],
        "gpu_percent": optional_number(values[1]),
        "vram_used": used_mb * 1024**2 if used_mb is not None else None,
        "vram_total": total_mb * 1024**2 if total_mb is not None else None,
        "vram_percent": round(used_mb / total_mb * 100, 1) if used_mb is not None and total_mb else None,
        "temperature": optional_number(values[4]),
        "fan_percent": optional_number(values[5]),
        "power_watts": optional_number(values[6]),
    }


def disk_stats() -> list[dict]:
    result = subprocess.run(
        ["df", "-B1", "--output=source,target,size,used,avail,pcent", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs"],
        capture_output=True, text=True, timeout=3, check=True,
    )
    disks = []
    for line in result.stdout.splitlines()[1:]:
        values = line.split()
        if len(values) != 6 or not values[0].startswith("/dev/"):
            continue
        source, mount, total, used, available, percent = values
        disks.append({
            "source": source, "mount": mount, "total": int(total), "used": int(used),
            "available": int(available), "percent": float(percent.rstrip("%")),
        })
    return disks


def snapshot() -> dict:
    ram_used, ram_total, ram_percent = memory_stats()
    payload = {
        "ok": True, "timestamp": time.time(), "cpu_percent": cpu_percent(),
        "ram_used": ram_used, "ram_total": ram_total, "ram_percent": ram_percent,
        "load_average": [round(value, 2) for value in os.getloadavg()] if hasattr(os, "getloadavg") else [],
    }
    try:
        payload.update(gpu_stats())
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        payload.update({key: None for key in (
            "device_name", "gpu_percent", "vram_used", "vram_total", "vram_percent",
            "temperature", "fan_percent", "power_watts",
        )})
    try:
        payload["disks"] = disk_stats()
    except (OSError, subprocess.SubprocessError, ValueError):
        payload["disks"] = []
    return payload


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps({"ok": True}).encode()
        elif self.path == "/api/device-stats":
            body = json.dumps(snapshot()).encode()
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("REF2VA_MONITOR_PORT", "8190"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
