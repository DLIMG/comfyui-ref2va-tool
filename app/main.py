from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .comfy_client import ComfyClient, ComfyError
from .director_pack import MAX_PACK_UNCOMPRESSED_BYTES, convert_director_pack, extract_director_pack
from .picker import pick_files
from .prompt_director import compile_director_prompt, normalize_director
from .project_state import persist_project_runtime, restore_imported_project
from .results import (
    delete_managed_result,
    find_fallback_outputs,
    find_video_outputs,
    managed_root_containing,
    preserve_results,
    preserve_downloaded_results,
    resolve_managed_results_root,
)
from .storage import (
    load_project, migrate_project_references, save_project, save_uploaded_image,
    save_uploaded_video, save_uploaded_audio_media, stage_audio, stage_image, stage_video,
)
from .validation import validate_shot
from .video_probe import find_dimension_mismatch
from .video_analyzer_import import preview_video_analyzer
from .workflow import (
    ADAPTIVE_LOW_VRAM_NODE,
    MAX_CONCATENATE_SEGMENTS,
    VIDEO_CONCAT_CODECS,
    build_concatenate_workflow,
    build_refine_workflow,
    build_shot_workflow,
    load_template,
)


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_TEMPLATE = ROOT / "app" / "templates" / "minimax_h3_turbo_8step_ref2va_api.json"
DEFAULT_COMFY_INPUT = Path(r"G:\ComfyUI\input\codex_ref2va_tool")
DEFAULT_COMFY_OUTPUT = Path(r"G:\ComfyUI\output\codex_ref2va_tool")
LOCAL_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_REMOTE_COMFY_URL = "http://192.168.11.103:8188"


def normalize_comfy_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("ComfyUI 地址必须是有效的 http://IP:端口 或 https://地址")
    return url


def configured_comfy_url(project: dict[str, Any]) -> str:
    settings = project.get("advanced_settings") or {}
    if settings.get("generation_target") == "remote":
        configured = str(settings.get("comfy_url") or "").strip()
        if configured in {"http://127.0.0.1:8188", "http://localhost:8188"}:
            configured = DEFAULT_REMOTE_COMFY_URL
        return normalize_comfy_url(configured or DEFAULT_REMOTE_COMFY_URL)
    return LOCAL_COMFY_URL


def estimate_workflow_seconds(workflow: dict[str, Any]) -> int:
    duration = float(workflow.get("132", {}).get("inputs", {}).get("value", 6))
    megapixels = float(workflow.get("115", {}).get("inputs", {}).get("megapixels", .4))
    steps = int(workflow.get("124", {}).get("inputs", {}).get("steps", 8))
    return max(60, round(duration * 60 * megapixels / .4 * steps / 8))


def estimate_queue_remaining(queue: dict[str, Any], prompt_id: str, comfy: Any) -> tuple[int | None, str]:
    total = 0
    used_live = False
    running = queue.get("queue_running", [])
    pending = queue.get("queue_pending", [])
    for item in running:
        if len(item) < 3:
            continue
        if len(item) > 3 and isinstance(item[3], dict):
            getattr(comfy, "watch_progress", lambda _id: None)(str(item[3].get("client_id") or ""))
        live = getattr(comfy, "progress", lambda _id: None)(item[1])
        if live and live.get("sample_remaining_seconds") is not None:
            total += int(live["sample_remaining_seconds"])
            used_live = True
        else:
            total += estimate_workflow_seconds(item[2])
        if item[1] == prompt_id:
            return total, "live_sampling" if used_live else "workflow_estimate"
    for item in pending:
        if len(item) < 3:
            continue
        total += estimate_workflow_seconds(item[2])
        if item[1] == prompt_id:
            return total, "queue_plus_live_sampling" if used_live else "queue_estimate"
    return None, "unknown"


class PathBody(BaseModel):
    path: str


class SubmitBody(BaseModel):
    references: list[str]
    reference_videos: list[str] = Field(default_factory=list)
    reference_audios: list[str] = Field(default_factory=list)
    prompt: str
    duration: float = 6
    seed: int = 1
    output_name: str = "shot_01"
    resolution: str = "480p"
    aspect_ratio: str = "16:9"
    generation_mode: str = "r2va"
    continue_from_previous: bool = False
    previous_output_name: str = ""
    will_be_continued: bool = False
    save_latent: bool = False
    turbo_lora_enabled: bool = True
    sage_attention_enabled: bool = True
    sampling_steps: int | None = None
    audio_tail_carryover: str = "Full Previous Tail"
    audio_feather_ticks: int = 0
    previous_comfy_url: str = ""
    face_swap_enabled: bool = False
    reference_image_size: str = "match"
    director: dict[str, Any] = Field(default_factory=dict)


class DirectorCompileBody(BaseModel):
    prompt: str
    generation_mode: str = "r2va"
    director: dict[str, Any] = Field(default_factory=dict)


class CollectResultBody(BaseModel):
    shot_id: str


class RefineBody(BaseModel):
    shot_id: str
    target_resolution: str = "0.9mp"
    source_latent_name: str = ""
    pass_number: int = Field(default=2, ge=2, le=9)
    # 默认整张直出（低噪声重采，不分块）；只有真放大到单块仍超显存时才开时空瓦片。
    split_tiling: bool = False


class MemoryCleanupBody(BaseModel):
    unload_models: bool = False
    oom_recovery: bool = False


class BatchPreflightShot(BaseModel):
    id: str
    output_name: str
    continue_from_previous: bool = False
    previous_output_name: str = ""
    previous_in_batch: bool = False


class BatchPreflightBody(BaseModel):
    shots: list[BatchPreflightShot]


class ImportProjectBody(BaseModel):
    project: dict[str, Any]


class VideoAnalyzerImportBody(BaseModel):
    directory: str
    reference_video: str = ""


class ConcatBody(BaseModel):
    """整片串接：把若干已完成镜头交给 ComfyUI 0.36 原生 ConcatenateVideo。"""

    shot_ids: list[str] = Field(default_factory=list)
    output_name: str = "full_cut"
    codec: str = "auto"
    comfy_url: str = ""


class ConcatCollectBody(BaseModel):
    prompt_id: str
    output_name: str = "full_cut"
    comfy_url: str = ""


def available_system_memory(stats: dict[str, Any]) -> int | None:
    system = stats.get("system") or {}
    for key in ("ram_free", "memory_free", "available_memory"):
        value = system.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def create_app(
    client: Any | None = None,
    data_dir: str | Path | None = None,
    template_path: str | Path = DEFAULT_TEMPLATE,
    comfy_input: str | Path | None = None,
    comfy_output: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="H3 Continuous Shot Studio")
    fixed_client = client
    transfer_progress: dict[str, dict[str, Any]] = {}
    comfy_clients: dict[str, Any] = {}
    queue_history_transition_since: dict[str, float] = {}
    data = Path(data_dir or ROOT / "data")
    input_dir = Path(comfy_input or (DEFAULT_COMFY_INPUT if data_dir is None else data / "comfy_input"))
    output_dir_path = Path(comfy_output or DEFAULT_COMFY_OUTPUT)
    results_root = data / "results"
    template_file = Path(template_path)
    comfy_client_id = uuid.uuid4().hex

    def client_for_url(value: str | None = None):
        if fixed_client is not None:
            return fixed_client
        url = normalize_comfy_url(value or configured_comfy_url(load_project(data / "storyboard.json")))
        if url not in comfy_clients:
            comfy_clients[url] = ComfyClient(url)
        return comfy_clients[url]

    def current_target() -> tuple[str, Any]:
        url = configured_comfy_url(load_project(data / "storyboard.json"))
        return url, client_for_url(url)

    def stage_for_target(source: str | Path, target_url: str, target_client: Any) -> str:
        if target_url == LOCAL_COMFY_URL or fixed_client is not None:
            staged = stage_image(source, input_dir)
            return f"codex_ref2va_tool/{staged.name}"
        staged = stage_image(source, data / "remote_staging")
        response = target_client.upload_input(staged.name, staged.read_bytes())
        name = Path(str(response.get("name") or staged.name)).name
        subfolder = str(response.get("subfolder") or "codex_ref2va_tool").strip("/\\")
        return f"{subfolder}/{name}" if subfolder else name

    def stage_video_for_target(source: str | Path, target_url: str, target_client: Any) -> str:
        if target_url == LOCAL_COMFY_URL or fixed_client is not None:
            staged = stage_video(source, input_dir)
            return f"codex_ref2va_tool/{staged.name}"
        staged = stage_video(source, data / "remote_staging")
        response = target_client.upload_input(staged.name, staged.read_bytes())
        name = Path(str(response.get("name") or staged.name)).name
        subfolder = str(response.get("subfolder") or "codex_ref2va_tool").strip("/\\")
        return f"{subfolder}/{name}" if subfolder else name

    def stage_audio_for_target(source: str | Path, target_url: str, target_client: Any) -> str:
        target = input_dir if target_url == LOCAL_COMFY_URL or fixed_client is not None else data / "remote_staging"
        staged = stage_audio(source, target)
        if target_url == LOCAL_COMFY_URL or fixed_client is not None:
            return f"codex_ref2va_tool/{staged.name}"
        response = target_client.upload_input(staged.name, staged.read_bytes())
        name = Path(str(response.get("name") or staged.name)).name
        subfolder = str(response.get("subfolder") or "codex_ref2va_tool").strip("/\\")
        return f"{subfolder}/{name}" if subfolder else name

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/app.css")
    def css():
        return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.get("/app.js")
    def js():
        return FileResponse(STATIC / "app.js", media_type="application/javascript")

    @app.get("/canvas.js")
    def canvas_js():
        return FileResponse(STATIC / "canvas.js", media_type="application/javascript")

    @app.get("/playlist.js")
    def playlist_js():
        return FileResponse(STATIC / "playlist.js", media_type="application/javascript")

    @app.get("/media-player.js")
    def media_player_js():
        return FileResponse(STATIC / "media-player.js", media_type="application/javascript")

    @app.get("/project-merge.js")
    def project_merge_js():
        return FileResponse(STATIC / "project-merge.js", media_type="application/javascript")

    @app.get("/api/file-preview")
    def file_preview(path: str):
        image = Path(path)
        if not image.is_file() or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(404, "图片不存在")
        return FileResponse(image)

    @app.get("/api/video-preview")
    def video_preview(path: str):
        video = Path(path)
        if not video.is_file() or video.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
            raise HTTPException(404, "视频不存在")
        return FileResponse(video)

    @app.get("/api/health")
    def health(comfy_url: str | None = None):
        try:
            if comfy_url:
                target_url = normalize_comfy_url(comfy_url)
                target_client = client_for_url(target_url)
            else:
                target_url, target_client = current_target()
            stats = target_client.system_stats()
            return {"ok": True, "stats": stats, "comfy_url": target_url, "template": str(template_file)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "template": str(template_file)}

    @app.get("/api/device-stats")
    def device_stats(comfy_url: str | None = None):
        try:
            if comfy_url:
                target_url = normalize_comfy_url(comfy_url)
                target_client = client_for_url(target_url)
            else:
                target_url, target_client = current_target()
            raw = target_client.system_stats()
            system = raw.get("system") or {}
            devices = raw.get("devices") or []
            gpu = devices[0] if devices else {}
            ram_total, ram_free = int(system.get("ram_total") or 0), int(system.get("ram_free") or 0)
            vram_total, vram_free = int(gpu.get("vram_total") or 0), int(gpu.get("vram_free") or 0)
            payload: dict[str, Any] = {
                "ok": True, "comfy_url": target_url, "device_name": str(gpu.get("name") or "未检测到 GPU"),
                "cpu_percent": None, "ram_percent": round((ram_total - ram_free) / ram_total * 100, 1) if ram_total else None,
                "ram_used": ram_total - ram_free, "ram_total": ram_total,
                "gpu_percent": None, "vram_percent": round((vram_total - vram_free) / vram_total * 100, 1) if vram_total else None,
                "vram_used": vram_total - vram_free, "vram_total": vram_total,
                "temperature": None, "fan_percent": None, "power_watts": None,
                "disks": [],
            }
            if target_url == LOCAL_COMFY_URL:
                try:
                    import psutil
                    payload["cpu_percent"] = psutil.cpu_percent(interval=None)
                    payload["ram_percent"] = psutil.virtual_memory().percent
                except (ImportError, OSError):
                    pass
                try:
                    query = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed,power.draw",
                         "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, check=True,
                    ).stdout.strip().splitlines()[0].split(",")
                    values = [part.strip() for part in query]
                    number = lambda value: None if value in {"", "[N/A]", "N/A"} else float(value)
                    payload.update({"gpu_percent": number(values[0]), "vram_used": (number(values[1]) or 0) * 1024**2,
                                    "vram_total": (number(values[2]) or 0) * 1024**2, "temperature": number(values[3]),
                                    "fan_percent": number(values[4]), "power_watts": number(values[5])})
                    if payload["vram_total"]:
                        payload["vram_percent"] = round(payload["vram_used"] / payload["vram_total"] * 100, 1)
                except (OSError, subprocess.SubprocessError, IndexError, ValueError):
                    pass
            else:
                try:
                    hostname = urlparse(target_url).hostname
                    if not hostname:
                        raise ValueError("云端 ComfyUI 地址缺少主机名")
                    monitor_urls = [
                        f"http://{hostname}:8191/api/device-stats",
                        f"http://{hostname}:8190/api/device-stats",
                    ]
                    for monitor_url in monitor_urls:
                        try:
                            with urlrequest.urlopen(monitor_url, timeout=3) as response:
                                monitor = json.loads(response.read().decode("utf-8"))
                            if not monitor.get("ok"):
                                continue
                            for key in ("device_name", "cpu_percent", "ram_percent", "ram_used", "ram_total",
                                        "gpu_percent", "vram_percent", "vram_used", "vram_total",
                                        "temperature", "fan_percent", "power_watts", "disks"):
                                if monitor.get(key) is not None:
                                    payload[key] = monitor[key]
                            payload["monitor_url"] = monitor_url
                            break
                        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                            continue
                except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                    pass
            return payload
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/comfy-logs")
    def comfy_logs(comfy_url: str | None = None):
        try:
            target_url = normalize_comfy_url(comfy_url) if comfy_url else configured_comfy_url(
                load_project(data / "storyboard.json")
            )
            payload = client_for_url(target_url).logs()
            entries = payload.get("entries", []) if isinstance(payload, dict) else []
            return {"ok": True, "comfy_url": target_url, "entries": entries[-500:]}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "entries": []}

    @app.post("/api/memory/cleanup")
    def cleanup_memory(body: MemoryCleanupBody):
        """Release transient ComfyUI caches between serial jobs.

        Models stay resident unless the caller explicitly requests the slower
        low-memory/OOM recovery path.
        """
        try:
            _, target_client = current_target()
            stats_before = target_client.system_stats()
            free_ram = available_system_memory(stats_before)
            minimum_free_ram = int(float(os.getenv("REF2VA_MIN_FREE_RAM_GB", "6")) * 1024 ** 3)
            pressure = free_ram is not None and free_ram < minimum_free_ram
            unload_models = body.unload_models or body.oom_recovery or pressure
            target_client.free_memory(unload_models=unload_models)
            stats = target_client.system_stats()
            return {
                "ok": True,
                "unloaded_models": unload_models,
                "reason": "oom" if body.oom_recovery else "low_system_memory" if pressure else "cache_cleanup",
                "free_ram_before": free_ram,
                "minimum_free_ram": minimum_free_ram,
                "stats": stats,
            }
        except (ComfyError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/batch/preflight")
    def batch_preflight(body: BatchPreflightBody):
        errors: list[str] = []
        target_url, _ = current_target()
        latent_root = output_dir_path / "latents"
        for shot in body.shots:
            if not shot.continue_from_previous or shot.previous_in_batch:
                continue
            previous = shot.previous_output_name.strip()
            if not previous or not re.fullmatch(r"[\w\u4e00-\u9fff.-]+", previous, flags=re.UNICODE):
                errors.append(f"{shot.id} 缺少有效的紧邻上一镜输出名")
                continue
            if target_url != LOCAL_COMFY_URL:
                continue
            latent_path = latent_root / f"{previous}_00001.safetensors"
            if not latent_path.is_file():
                errors.append(f"{shot.id} 需要上一镜 {previous} 的 Latent；请把上一镜一并选中，或先单独生成上一镜")
        return {"ok": not errors, "errors": errors}

    @app.get("/api/storyboard")
    def get_storyboard():
        return load_project(data / "storyboard.json")

    @app.put("/api/storyboard")
    def put_storyboard(project: dict[str, Any]):
        if not isinstance(project.get("shots"), list):
            raise HTTPException(422, "故事板 shots 必须是数组")
        migration_path = data / "reference_migrations.json"
        migrations = load_project(migration_path) if migration_path.is_file() else {}
        project = migrate_project_references(project, migrations)
        save_project(data / "storyboard.json", project)
        state_path = persist_project_runtime(project, data)
        return {"ok": True, "state_path": str(state_path)}

    @app.post("/api/storyboard/import")
    def import_storyboard(body: ImportProjectBody):
        current = load_project(data / "storyboard.json")
        if isinstance(current.get("shots"), list):
            persist_project_runtime(current, data)
        try:
            merged, recovered = restore_imported_project(body.project, current, data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        save_project(data / "storyboard.json", merged)
        state_path = persist_project_runtime(merged, data)
        return {"ok": True, "project": merged, "recovered_results": recovered, "state_path": str(state_path)}

    @app.post("/api/storyboard/import-director-pack")
    async def preview_director_pack(pack: UploadFile = File(...)):
        """Convert, but do not save, an AIMixer Director authoring pack.

        The browser receives the proposed storyboard first and must explicitly
        call the normal import endpoint to replace the active project.
        """
        filename = str(pack.filename or "").lower()
        if not filename.endswith(".zip"):
            raise HTTPException(422, "请选择 Director 导出的 .mmxpack.zip 文件")
        incoming_dir = data / "imports" / "director_pack_uploads"
        incoming_dir.mkdir(parents=True, exist_ok=True)
        incoming = incoming_dir / f"{uuid.uuid4().hex}.mmxpack.zip"
        size = 0
        try:
            with incoming.open("wb") as handle:
                while chunk := await pack.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_PACK_UNCOMPRESSED_BYTES:
                        raise ValueError("Director 包上传大小超过安全上限")
                    handle.write(chunk)
            extracted = extract_director_pack(incoming, data / "imports")
            project, warnings = convert_director_pack(extracted)
            return {
                "ok": True,
                "project": project,
                "warnings": warnings,
                "summary": {
                    "shots": len(project["shots"]),
                    "mode": project["director_pack_source"]["task_type"],
                    "shared_references": len(project["shared"]["references"]),
                },
            }
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await pack.close()

    @app.post("/api/storyboard/preview-video-analyzer")
    def preview_video_analyzer_draft(body: VideoAnalyzerImportBody):
        try:
            shot, warnings = preview_video_analyzer(body.directory, body.reference_video)
        except (OSError, UnicodeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"shot": shot, "warnings": warnings}

    @app.post("/api/read-text")
    def read_text(body: PathBody):
        path = Path(body.path)
        if not path.is_file():
            raise HTTPException(404, "提示词文件不存在")
        return {"text": path.read_text(encoding="utf-8-sig")}

    @app.post("/api/prompts/director")
    def compile_prompt_director(body: DirectorCompileBody):
        if body.generation_mode not in {"r2va", "fl2va"}:
            raise HTTPException(422, "Director 仅支持 R2VA 或 FL2VA")
        prompt, note = compile_director_prompt(body.prompt, body.generation_mode, body.director)
        return {"prompt": prompt, "note": note, "director": normalize_director(body.director)}

    @app.post("/api/pick-images")
    def pick_images():
        return {"paths": pick_files("images")}

    @app.post("/api/pick-videos")
    def pick_videos():
        return {"paths": pick_files("videos")}

    @app.post("/api/upload-images")
    async def upload_images(files: list[UploadFile] = File(...)):
        paths: list[str] = []
        try:
            for upload in files:
                content = await upload.read()
                paths.append(str(save_uploaded_image(upload.filename or "image", content, data / "uploads")))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"paths": paths}

    @app.post("/api/upload-videos")
    async def upload_videos(files: list[UploadFile] = File(...)):
        paths: list[str] = []
        try:
            for upload in files:
                content = await upload.read()
                paths.append(str(save_uploaded_video(upload.filename or "video", content, data / "uploads")))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"paths": paths}

    @app.post("/api/upload-audios")
    async def upload_audios(files: list[UploadFile] = File(...)):
        paths: list[str] = []
        try:
            for upload in files:
                content = await upload.read()
                paths.append(str(save_uploaded_audio_media(upload.filename or "audio", content, data / "uploads")))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"paths": paths}

    @app.post("/api/pick-text")
    def pick_text():
        paths = pick_files("text")
        if not paths:
            return {"path": "", "text": ""}
        path = paths[0]
        return {"path": path, "text": Path(path).read_text(encoding="utf-8-sig")}

    @app.post("/api/submit")
    def submit(body: SubmitBody):
        shot = body.model_dump()
        errors = validate_shot(shot)
        if errors:
            raise HTTPException(422, "；".join(errors))
        try:
            target_url, target_client = current_target()
            if body.continue_from_previous and body.previous_comfy_url:
                if normalize_comfy_url(body.previous_comfy_url) != target_url:
                    raise ValueError("续镜必须与上一镜使用同一台生成设备")
            relative_names = [stage_for_target(path, target_url, target_client) for path in body.references]
            relative_video_names = [
                stage_video_for_target(path, target_url, target_client) for path in body.reference_videos
            ]
            relative_audio_names = [
                stage_audio_for_target(path, target_url, target_client) for path in body.reference_audios
            ]
            object_info = getattr(target_client, "object_info", lambda: {})()
            adaptive_low_vram_enabled = ADAPTIVE_LOW_VRAM_NODE in object_info
            template = load_template(template_file)
            compiled_prompt, director_note = compile_director_prompt(
                body.prompt, body.generation_mode, body.director,
            )
            output_prefix = f"codex_ref2va_tool/{body.output_name}"
            workflow = build_shot_workflow(
                template,
                relative_names,
                compiled_prompt,
                body.duration,
                body.seed,
                output_prefix,
                resolution=body.resolution,
                aspect_ratio=body.aspect_ratio,
                generation_mode=body.generation_mode,
                continue_from_previous=body.continue_from_previous,
                previous_output_name=body.previous_output_name,
                will_be_continued=body.will_be_continued,
                # Every first pass remains eligible for deferred H3 refinement.
                save_latent=True,
                turbo_lora_enabled=body.turbo_lora_enabled,
                sage_attention_enabled=body.sage_attention_enabled,
                sampling_steps=body.sampling_steps,
                audio_tail_carryover=body.audio_tail_carryover,
                audio_feather_ticks=body.audio_feather_ticks,
                reference_video_names=relative_video_names,
                reference_audio_names=relative_audio_names,
                adaptive_low_vram_enabled=adaptive_low_vram_enabled,
                face_swap_enabled=body.face_swap_enabled,
                reference_image_size=body.reference_image_size,
            )
            stamp = time.strftime("%Y%m%d-%H%M%S")
            run_dir = data / "runs" / body.output_name / f"{stamp}-{uuid.uuid4().hex[:6]}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "workflow_api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
            result = target_client.submit(workflow, comfy_client_id)
            (run_dir / "run.json").write_text(json.dumps({
                "request": shot, "response": result, "director": normalize_director(body.director),
                "director_note": director_note, "compiled_prompt": compiled_prompt,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            estimated_seconds = estimate_workflow_seconds(workflow)
            return {
                **result, "run_dir": str(run_dir), "output_prefix": output_prefix,
                "comfy_url": target_url,
                "adaptive_low_vram": adaptive_low_vram_enabled, "director_note": director_note,
                "submitted_at": time.time(), "estimated_seconds": estimated_seconds,
            }
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/refine")
    def submit_refine(body: RefineBody):
        project = load_project(data / "storyboard.json")
        shot = next((item for item in project.get("shots", []) if item.get("id") == body.shot_id), None)
        if shot is None:
            raise HTTPException(404, "分镜不存在")
        shot_for_validation = dict(shot)
        if shot.get("continue_from_previous"):
            index = project.get("shots", []).index(shot)
            if index > 0:
                shot_for_validation["previous_output_name"] = project.get("shots", [])[index - 1].get("output_name", "")
        errors = validate_shot(shot_for_validation)
        if errors:
            raise HTTPException(422, "；".join(errors))
        if body.target_resolution not in {f"{value / 10:.1f}mp" for value in range(4, 11)}:
            raise HTTPException(422, "二采目标仅支持0.4–1.0 MP")
        if shot.get("generation_mode") == "fl2va":
            raise HTTPException(422, "FL2VA首尾帧锚定镜头默认不做二采，避免首尾帧漂移")
        try:
            target_url, target_client = current_target()
            object_info = getattr(target_client, "object_info", lambda: {})()
            # 直出（默认）只需要放大 + 重采两件工具；时空瓦片参数节点仅在
            # body.split_tiling=True 时才要求存在。
            required_refine_nodes = {
                "MinimaxH3LatentUpscaler3D", "MMH3SplitUpscale",
            }
            if body.split_tiling:
                required_refine_nodes |= {
                    "MMH3TemporalSplitParamsV10", "MMH3SpatialSplitParamsV10",
                }
            missing_refine_nodes = sorted(required_refine_nodes - set(object_info)) if object_info else []
            if missing_refine_nodes:
                raise ValueError(
                    "当前生成设备缺少H3二采节点: "
                    + ", ".join(missing_refine_nodes)
                    + "；请更新 Comfyui_Minimax_h3_latent_Upscaler 并重启"
                )
            adaptive_low_vram_enabled = bool(object_info) and ADAPTIVE_LOW_VRAM_NODE in object_info
            source_name = body.source_latent_name.strip() or str(shot.get("output_name") or "")
            if not source_name:
                raise ValueError("缺少一采 Latent 名称")
            if target_url == LOCAL_COMFY_URL:
                latent_path = output_dir_path / "latents" / f"{source_name}_00001.safetensors"
                if not latent_path.is_file():
                    raise FileNotFoundError(f"找不到可二采 Latent: {latent_path}")
            relative_names = [stage_for_target(path, target_url, target_client) for path in shot.get("references", [])]
            relative_videos = [
                stage_video_for_target(path, target_url, target_client)
                for path in shot.get("reference_videos", [])
            ]
            output_name = f"{shot['output_name']}_p{body.pass_number}"
            settings = project.get("advanced_settings") or {}
            shot_index = project.get("shots", []).index(shot)
            will_be_continued = (
                shot_index + 1 < len(project.get("shots", []))
                and bool(project["shots"][shot_index + 1].get("continue_from_previous"))
            )
            workflow = build_refine_workflow(
                load_template(template_file), relative_names, str(shot.get("prompt") or ""),
                float(shot.get("duration") or 6), int(shot.get("seed") or 1) + body.pass_number - 1,
                f"codex_ref2va_tool/{output_name}", source_name,
                target_resolution=body.target_resolution,
                aspect_ratio=str(shot.get("aspect_ratio") or "16:9"),
                generation_mode=str(shot.get("generation_mode") or "r2va"),
                reference_video_names=relative_videos,
                turbo_lora_enabled=settings.get("turbo_lora_enabled", True),
                sage_attention_enabled=settings.get("sage_attention_enabled", True),
                sampling_steps=settings.get("sampling_steps"),
                source_context_frames=39 if shot.get("continue_from_previous") else 0,
                will_be_continued=will_be_continued,
                reference_image_size=str(shot.get("reference_image_size") or "match"),
                adaptive_low_vram_enabled=adaptive_low_vram_enabled,
                split_tiling=body.split_tiling,
            )
            stamp = time.strftime("%Y%m%d-%H%M%S")
            run_dir = data / "runs" / output_name / f"{stamp}-{uuid.uuid4().hex[:6]}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "workflow_api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
            result = target_client.submit(workflow, comfy_client_id)
            shot["refine_job"] = {
                "status": "queued", "prompt_id": result["prompt_id"], "pass_number": body.pass_number,
                "source_latent_name": source_name, "output_name": output_name,
                "target_resolution": body.target_resolution, "comfy_url": target_url,
                "run_dir": str(run_dir), "error": "",
            }
            save_project(data / "storyboard.json", project)
            return {**result, "refine_job": shot["refine_job"]}
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/status/{prompt_id}")
    def status(prompt_id: str, comfy_url: str = ""):
        try:
            return client_for_url(comfy_url or None).history(prompt_id)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/task-status/{prompt_id}")
    def task_status(prompt_id: str, comfy_url: str = ""):
        try:
            target_client = client_for_url(comfy_url or None)
            history = target_client.history(prompt_id)
            if prompt_id in history:
                queue_history_transition_since.pop(prompt_id, None)
                entry = history[prompt_id]
                completed = bool(entry.get("status", {}).get("completed"))
                return {"status": "completed" if completed else "failed", "history": entry}
            queue = target_client.queue()
            for item in queue.get("queue_running", []):
                if len(item) > 1 and item[1] == prompt_id:
                    queue_history_transition_since.pop(prompt_id, None)
                    remaining, source = estimate_queue_remaining(queue, prompt_id, target_client)
                    live = getattr(target_client, "progress", lambda _id: None)(prompt_id) or {}
                    return {"status": "running", "estimated_remaining_seconds": remaining,
                            "eta_source": source, "progress_percent": live.get("progress_percent")}
            for item in queue.get("queue_pending", []):
                if len(item) > 1 and item[1] == prompt_id:
                    queue_history_transition_since.pop(prompt_id, None)
                    remaining, source = estimate_queue_remaining(queue, prompt_id, target_client)
                    return {"status": "queued", "estimated_remaining_seconds": remaining,
                            "eta_source": source}
            project = load_project(data / "storyboard.json")
            known_active = any(
                (str(shot.get("prompt_id") or "") == prompt_id and shot.get("status") in {"queued", "running"})
                or (str((shot.get("refine_job") or {}).get("prompt_id") or "") == prompt_id
                    and (shot.get("refine_job") or {}).get("status") in {"queued", "running"})
                for shot in project.get("shots", [])
            )
            if known_active or prompt_id in queue_history_transition_since:
                started = queue_history_transition_since.setdefault(prompt_id, time.monotonic())
                if time.monotonic() - started < 90:
                    return {"status": "syncing", "transitioning": True,
                            "error": "ComfyUI 正在把任务从运行队列写入历史记录"}
                queue_history_transition_since.pop(prompt_id, None)
            return {
                "status": "failed",
                "error": "任务不在 ComfyUI 队列或历史记录中，已作为失效任务释放",
            }
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/cancel/{prompt_id}")
    def cancel_task(prompt_id: str, comfy_url: str = ""):
        try:
            result = client_for_url(comfy_url or None).cancel(prompt_id)
            return {"cancelled": bool(result.get("cancelled")), "prompt_id": prompt_id}
        except ComfyError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/queue/cancel-all")
    def cancel_all_tasks(comfy_url: str = ""):
        """Cancel every queued/running prompt on one explicit ComfyUI target."""
        try:
            target_url = normalize_comfy_url(comfy_url) if comfy_url else configured_comfy_url(
                load_project(data / "storyboard.json")
            )
            target_client = client_for_url(target_url)
            queue = target_client.queue()
            prompt_ids: list[str] = []
            for key in ("queue_running", "queue_pending"):
                for item in queue.get(key, []):
                    if len(item) > 1 and str(item[1]) not in prompt_ids:
                        prompt_ids.append(str(item[1]))
            cancelled: list[str] = []
            failed: list[dict[str, str]] = []
            for prompt_id in prompt_ids:
                try:
                    result = target_client.cancel(prompt_id)
                    if result.get("cancelled"):
                        cancelled.append(prompt_id)
                    else:
                        failed.append({"prompt_id": prompt_id, "error": "ComfyUI 未确认取消"})
                except ComfyError as exc:
                    failed.append({"prompt_id": prompt_id, "error": str(exc)})
            if cancelled:
                project = load_project(data / "storyboard.json")
                for shot in project.get("shots", []):
                    shot_url = str(shot.get("comfy_url") or target_url)
                    if str(shot.get("prompt_id") or "") in cancelled and normalize_comfy_url(shot_url) == target_url:
                        shot["status"] = "cancelled"
                        shot["error"] = ""
                        shot["estimated_remaining_seconds"] = 0
                    refine = shot.get("refine_job") or {}
                    refine_url = str(refine.get("comfy_url") or target_url)
                    if str(refine.get("prompt_id") or "") in cancelled and normalize_comfy_url(refine_url) == target_url:
                        refine["status"] = "cancelled"
                        refine["error"] = ""
                save_project(data / "storyboard.json", project)
                persist_project_runtime(project, data)
            return {"ok": not failed, "target": target_url, "requested": len(prompt_ids),
                    "cancelled": len(cancelled), "cancelled_prompt_ids": cancelled, "failed": failed}
        except (ValueError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/queue")
    def generation_queue(comfy_url: str = ""):
        """Return all running and pending jobs reported by ComfyUI."""
        try:
            target_client = client_for_url(comfy_url or None)
            raw = target_client.queue()
            project = load_project(data / "storyboard.json")
            known: dict[str, dict[str, str]] = {}
            for shot in project.get("shots", []):
                prompt_id = str(shot.get("prompt_id") or "")
                if prompt_id:
                    known[prompt_id] = {"shot_id": str(shot.get("id") or ""), "title": str(shot.get("title") or shot.get("output_name") or "")}
                refine = shot.get("refine_job") or {}
                refine_id = str(refine.get("prompt_id") or "")
                if refine_id:
                    known[refine_id] = {"shot_id": str(shot.get("id") or ""), "title": f"{shot.get('title') or shot.get('output_name') or ''}·{refine.get('pass_number', 2)}采"}
            jobs = []
            for status, key in (("running", "queue_running"), ("queued", "queue_pending")):
                for position, item in enumerate(raw.get(key, []), start=1):
                    if len(item) < 2:
                        continue
                    prompt_id = str(item[1])
                    meta = known.get(prompt_id, {})
                    live = getattr(target_client, "progress", lambda _id: None)(prompt_id) or {}
                    jobs.append({"prompt_id": prompt_id, "status": status, "position": position,
                                 "shot_id": meta.get("shot_id", ""),
                                 "title": meta.get("title", "") or f"ComfyUI 任务 {prompt_id[:8]}",
                                 "progress_percent": live.get("progress_percent")})
            return {"jobs": jobs, "running": len(raw.get("queue_running", [])), "pending": len(raw.get("queue_pending", []))}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/results/collect")
    def collect_results(body: CollectResultBody):
        project_path = data / "storyboard.json"
        project = load_project(project_path)
        shot = next((item for item in project.get("shots", []) if item.get("id") == body.shot_id), None)
        if shot is None:
            raise HTTPException(404, "分镜不存在")
        existing = shot.setdefault("results", [])
        prompt_id = str(shot.get("prompt_id") or "")
        if not prompt_id:
            raise HTTPException(409, "该分镜还没有生成任务")
        if any(item.get("prompt_id") == prompt_id for item in existing):
            shot["status"] = "completed"
            shot["error"] = ""
            save_project(project_path, project)
            return {"results": existing, "added": []}
        try:
            collection_root = resolve_managed_results_root(project, results_root, create=True)
            target_url = normalize_comfy_url(shot.get("comfy_url") or configured_comfy_url(project))
            target_client = client_for_url(target_url)
            history = target_client.history(prompt_id)
            outputs = find_video_outputs(history.get(prompt_id, {}))
            remote = fixed_client is None and target_url != LOCAL_COMFY_URL
            if not outputs and not remote:
                outputs = find_fallback_outputs(str(shot.get("output_name") or ""), output_dir_path)
                collected_sources = {item.get("source", {}).get("filename") for item in existing}
                outputs = [item for item in outputs if item.get("filename") not in collected_sources]
            if not outputs:
                raise HTTPException(409, "任务已完成，但暂未找到可收集的视频文件")
            preserve = preserve_downloaded_results if remote else preserve_results
            downloader: Any = output_dir_path
            if remote:
                started_at = time.monotonic()
                transfer_progress[body.shot_id] = {
                    "status": "transferring", "bytes_received": 0,
                    "total_bytes": None, "bytes_per_second": 0,
                }

                def on_progress(received: int, total: int | None) -> None:
                    elapsed = max(time.monotonic() - started_at, .001)
                    transfer_progress[body.shot_id] = {
                        "status": "transferring", "bytes_received": received,
                        "total_bytes": total, "bytes_per_second": received / elapsed,
                    }

                downloader = lambda output: target_client.download_output(output, on_progress)
            added = preserve(
                outputs,
                downloader,
                collection_root,
                project_name=str(project.get("name") or "未命名项目"),
                shot_id=body.shot_id,
                prompt_id=prompt_id,
            )
            if not added:
                raise HTTPException(409, "找到输出记录，但视频文件尚未写入完成")
            existing.extend(added)
            for item in added:
                item["resolution"] = str(shot.get("resolution") or "")
            shot["status"] = "completed"
            shot["error"] = ""
            save_project(project_path, project)
            if remote:
                current = transfer_progress.get(body.shot_id, {})
                transfer_progress[body.shot_id] = {**current, "status": "completed"}
            return {"results": existing, "added": added}
        except HTTPException:
            raise
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            current = transfer_progress.get(body.shot_id, {})
            if current:
                transfer_progress[body.shot_id] = {**current, "status": "failed", "error": str(exc)}
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/results/transfer/{shot_id}")
    def result_transfer_progress(shot_id: str):
        return transfer_progress.get(shot_id, {
            "status": "waiting", "bytes_received": 0,
            "total_bytes": None, "bytes_per_second": 0,
        })

    @app.post("/api/results/concatenate")
    def concatenate_results(body: ConcatBody):
        """用 ComfyUI 0.36 原生 ConcatenateVideo 把多个已完成镜头串成整片。

        ConcatenateVideo 只做容器级串接、不重新解码，所以要求所有片段分辨率
        完全一致；不一致时在排队前就拦下来，避免跑完才在 SaveVideo 报错。
        """
        if len(body.shot_ids) < 2:
            raise HTTPException(422, "至少选择两个镜头才能串片")
        if len(body.shot_ids) > MAX_CONCATENATE_SEGMENTS:
            raise HTTPException(422, f"最多串接 {MAX_CONCATENATE_SEGMENTS} 段视频")
        if body.codec not in VIDEO_CONCAT_CODECS:
            raise HTTPException(422, f"不支持的串片编码: {body.codec}")
        if not re.fullmatch(r"[\w\u4e00-\u9fff.-]+", body.output_name or ""):
            raise HTTPException(422, "输出名称不能为空，且不能包含路径分隔符或特殊符号")
        project_path = data / "storyboard.json"
        project = load_project(project_path)
        shots_by_id = {str(item.get("id")): item for item in project.get("shots", [])}

        picked: list[tuple[str, dict[str, Any]]] = []
        for shot_id in body.shot_ids:
            shot = shots_by_id.get(str(shot_id))
            if shot is None:
                raise HTTPException(404, f"分镜不存在: {shot_id}")
            ready = [
                item for item in shot.get("results", [])
                if item.get("status") == "ready"
                and Path(str(item.get("path") or "")).is_file()
            ]
            if not ready:
                raise HTTPException(409, f"分镜 {shot_id} 还没有可用的视频结果")
            picked.append((str(shot_id), ready[-1]))

        mismatch = find_dimension_mismatch([(sid, item["path"]) for sid, item in picked])
        if mismatch is not None:
            left_id, left_size, right_id, right_size = mismatch
            raise HTTPException(
                422,
                "ConcatenateVideo 只做容器级串接（不解码），要求所有镜头分辨率完全一致："
                f"{left_id} 是 {left_size[0]}x{left_size[1]}，{right_id} 是 {right_size[0]}x{right_size[1]}。"
                "请统一用同一档清晰度/画幅重跑，或先把不一致的镜头升采样到相同尺寸。",
            )

        try:
            target_url = normalize_comfy_url(body.comfy_url or configured_comfy_url(project))
            target_client = client_for_url(target_url)
            staged_names = [
                stage_video_for_target(item["path"], target_url, target_client)
                for _, item in picked
            ]
            workflow = build_concatenate_workflow(
                staged_names,
                f"codex_ref2va_tool/{body.output_name}",
                codec=body.codec,
            )
            stamp = time.strftime("%Y%m%d-%H%M%S")
            run_dir = data / "runs" / "_film" / f"{body.output_name}-{stamp}-{uuid.uuid4().hex[:6]}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "workflow_api.json").write_text(
                json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = target_client.submit(workflow, comfy_client_id)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "request": body.model_dump(),
                        "response": result,
                        "segments": [sid for sid, _ in picked],
                    },
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            prompt_id = str(result.get("prompt_id") or "")
            return {
                **result,
                "run_dir": str(run_dir),
                "comfy_url": target_url,
                "segments": [sid for sid, _ in picked],
                "output_name": body.output_name,
                "submitted_at": time.time(),
                "estimated_seconds": estimate_workflow_seconds(workflow),
                "collect_prompt_id": prompt_id,
            }
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/results/concatenate/collect")
    def collect_concatenated(body: ConcatCollectBody):
        """把串片产物收进项目结果库，落在 ``_整片`` 分组下。"""
        project_path = data / "storyboard.json"
        project = load_project(project_path)
        try:
            target_url = normalize_comfy_url(body.comfy_url or configured_comfy_url(project))
            target_client = client_for_url(target_url)
            history = target_client.history(body.prompt_id)
            outputs = find_video_outputs(history.get(body.prompt_id, {}))
            remote = fixed_client is None and target_url != LOCAL_COMFY_URL
            if not outputs and not remote:
                outputs = find_fallback_outputs(body.output_name, output_dir_path)
            if not outputs:
                raise HTTPException(409, "未找到串片输出，任务可能仍在执行")
            collection_root = resolve_managed_results_root(project, results_root, create=True)
            project_name = str(project.get("name") or "未命名项目")
            if remote:
                added = preserve_downloaded_results(
                    outputs,
                    lambda output: target_client.download_output(output),
                    collection_root,
                    project_name=project_name,
                    shot_id="_整片",
                    prompt_id=body.prompt_id,
                )
            else:
                added = preserve_results(
                    outputs,
                    output_dir_path,
                    collection_root,
                    project_name=project_name,
                    shot_id="_整片",
                    prompt_id=body.prompt_id,
                )
            if not added:
                raise HTTPException(409, "找到输出记录，但视频文件尚未写入完成")
            return {"results": added, "added": added, "shot_id": "_整片"}
        except HTTPException:
            raise
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    '''Removed legacy pixel-space 4x-UltraSharp upscale API.
    @app.post("/api/results/upscale")
    def submit_upscale(body: UpscaleResultBody):
        project_path = data / "storyboard.json"
        project = load_project(project_path)
        shot = next((item for item in project.get("shots", []) if item.get("id") == body.shot_id), None)
        if shot is None:
            raise HTTPException(404, "分镜不存在")
        source = next((item for item in shot.get("results", []) if item.get("id") == body.result_id), None)
        if source is None:
            raise HTTPException(404, "视频结果不存在")
        try:
            managed_root = resolve_managed_results_root(project, results_root)
            managed_root_containing(source.get("path") or "", [managed_root])
            target_url = configured_comfy_url(project)
            target_client = client_for_url(target_url)
            if fixed_client is None and target_url != LOCAL_COMFY_URL:
                staged = stage_video(source["path"], data / "remote_staging")
                uploaded = target_client.upload_input(staged.name, staged.read_bytes())
                uploaded_subfolder = str(uploaded.get("subfolder") or "codex_ref2va_tool").strip("/\\")
                uploaded_name = Path(str(uploaded.get("name") or staged.name)).name
                input_name = f"{uploaded_subfolder}/{uploaded_name}" if uploaded_subfolder else uploaded_name
            else:
                staged = stage_video(source["path"], input_dir)
                input_name = f"codex_ref2va_tool/{staged.name}"
            # 显式双反斜杠写法（不用 r 前缀）：某些 Python 构建会把跨行调用首参位置的
            # r 前缀误判成独立标识符，从而对裸反斜杠转义抛 SyntaxWarning。语义完全一致。
            safe_output = re.sub(
                "[^\\w\\u4e00-\\u9fff-]+", "_", Path(source.get("filename") or "video").stem,
                flags=re.UNICODE,
            ).strip("_") or "video"
            output_prefix = f"codex_ref2va_tool/{safe_output}_{body.target_resolution}"
            workflow = build_video_upscale_workflow(
                input_name, output_prefix,
                aspect_ratio=str(shot.get("aspect_ratio") or "9:16"),
                target_resolution=body.target_resolution,
            )
            stamp = time.strftime("%Y%m%d-%H%M%S")
            run_dir = data / "runs" / "upscale" / body.shot_id / f"{stamp}-{uuid.uuid4().hex[:6]}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "workflow_api.json").write_text(
                json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            response = target_client.submit(workflow, comfy_client_id)
            source["upscale"] = {
                "status": "queued", "prompt_id": response["prompt_id"],
                "target_resolution": body.target_resolution, "run_dir": str(run_dir), "error": "",
                "comfy_url": target_url,
            }
            (run_dir / "run.json").write_text(
                json.dumps({"request": body.model_dump(), "response": response}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            save_project(project_path, project)
            return {**response, "upscale": source["upscale"]}
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/results/upscale/collect")
    def collect_upscale(body: UpscaleResultBody):
        project_path = data / "storyboard.json"
        project = load_project(project_path)
        shot = next((item for item in project.get("shots", []) if item.get("id") == body.shot_id), None)
        if shot is None:
            raise HTTPException(404, "分镜不存在")
        results = shot.setdefault("results", [])
        source = next((item for item in results if item.get("id") == body.result_id), None)
        if source is None:
            raise HTTPException(404, "原视频结果不存在")
        job = source.get("upscale") or {}
        prompt_id = str(job.get("prompt_id") or "")
        if not prompt_id:
            raise HTTPException(409, "该视频没有高清放大任务")
        if any(item.get("upscale_prompt_id") == prompt_id for item in results):
            job["status"] = "completed"
            save_project(project_path, project)
            return {"results": results, "added": []}
        try:
            target_url = normalize_comfy_url(job.get("comfy_url") or configured_comfy_url(project))
            target_client = client_for_url(target_url)
            outputs = find_video_outputs(target_client.history(prompt_id).get(prompt_id, {}))
            if not outputs:
                raise HTTPException(409, "高清任务已结束，但暂未找到输出视频")
            root = resolve_managed_results_root(project, results_root, create=True)
            remote = fixed_client is None and target_url != LOCAL_COMFY_URL
            preserve = preserve_downloaded_results if remote else preserve_results
            added = preserve(
                outputs, target_client.download_output if remote else output_dir_path, root,
                str(project.get("name") or "未命名项目"), body.shot_id, prompt_id,
            )
            if not added:
                raise HTTPException(409, "高清输出视频尚未写入完成")
            for item in added:
                item.update({
                    "kind": "upscaled", "source_result_id": body.result_id,
                    "upscale_prompt_id": prompt_id,
                    "resolution": str(job.get("target_resolution") or body.target_resolution),
                })
            results.extend(added)
            job["status"] = "completed"
            job["error"] = ""
            save_project(project_path, project)
            return {"results": results, "added": added}
        except HTTPException:
            raise
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    '''
    def get_saved_result(shot_id: str, result_id: str):
        project = load_project(data / "storyboard.json")
        shot = next((item for item in project.get("shots", []) if item.get("id") == shot_id), None)
        if shot is None:
            raise HTTPException(404, "分镜不存在")
        result = next((item for item in shot.get("results", []) if item.get("id") == result_id), None)
        if result is None:
            raise HTTPException(404, "生成结果不存在")
        return project, shot, result

    def get_allowed_result_path(project: dict[str, Any], result: dict[str, Any]) -> tuple[Path, Path]:
        project_results_root = resolve_managed_results_root(project, results_root)
        result_path = Path(str(result.get("path") or ""))
        containing_root = managed_root_containing(result_path, [results_root, project_results_root])
        return result_path, containing_root

    @app.get("/api/results/video/{shot_id}/{result_id}")
    def result_video(shot_id: str, result_id: str):
        project, _, result = get_saved_result(shot_id, result_id)
        try:
            video, _ = get_allowed_result_path(project, result)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not video.is_file():
            raise HTTPException(404, "视频文件不存在")
        if video.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv"}:
            raise HTTPException(400, "不支持的视频格式")
        return FileResponse(video)

    @app.delete("/api/results/{shot_id}/{result_id}")
    def delete_result(shot_id: str, result_id: str):
        project, shot, result = get_saved_result(shot_id, result_id)
        try:
            result_path, containing_root = get_allowed_result_path(project, result)
            delete_managed_result(result_path, containing_root)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        deleted_prompt_id = str(result.get("prompt_id") or "")
        shot["results"] = [item for item in shot.get("results", []) if item.get("id") != result_id]
        # Completed prompts remain permanently available in ComfyUI history.
        # Detach an intentionally deleted prompt after its final managed copy is
        # removed, otherwise the frontend poller downloads the result again.
        if (
            deleted_prompt_id
            and str(shot.get("prompt_id") or "") == deleted_prompt_id
            and not any(str(item.get("prompt_id") or "") == deleted_prompt_id for item in shot["results"])
        ):
            shot["prompt_id"] = ""
        save_project(data / "storyboard.json", project)
        return {"ok": True, "results": shot["results"], "prompt_id": str(shot.get("prompt_id") or "")}

    @app.get("/api/output-dir")
    def output_dir():
        return {"path": str(output_dir_path)}

    @app.post("/api/open-path")
    def open_path(body: PathBody):
        path = Path(body.path)
        target = path if path.is_dir() else path.parent
        if not target.exists():
            raise HTTPException(404, "路径不存在")
        os.startfile(str(target))
        return {"ok": True}

    return app


app = create_app()
