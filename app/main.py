from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .comfy_client import ComfyClient, ComfyError
from .picker import pick_files
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
    save_uploaded_video, stage_image,
)
from .upscale import build_video_upscale_workflow, stage_video
from .validation import validate_shot
from .workflow import build_shot_workflow, load_template


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
        return normalize_comfy_url(settings.get("comfy_url") or DEFAULT_REMOTE_COMFY_URL)
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


class CollectResultBody(BaseModel):
    shot_id: str


class UpscaleResultBody(BaseModel):
    shot_id: str
    result_id: str
    target_resolution: str = "720p"


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
    app = FastAPI(title="ComfyUI Ref2VA Tool")
    fixed_client = client
    comfy_clients: dict[str, Any] = {}
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

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/app.css")
    def css():
        return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.get("/app.js")
    def js():
        return FileResponse(STATIC / "app.js", media_type="application/javascript")

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
    def health():
        try:
            target_url, target_client = current_target()
            stats = target_client.system_stats()
            return {"ok": True, "stats": stats, "comfy_url": target_url, "template": str(template_file)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "template": str(template_file)}

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
        return {"ok": True}

    @app.post("/api/read-text")
    def read_text(body: PathBody):
        path = Path(body.path)
        if not path.is_file():
            raise HTTPException(404, "提示词文件不存在")
        return {"text": path.read_text(encoding="utf-8-sig")}

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
            template = load_template(template_file)
            output_prefix = f"codex_ref2va_tool/{body.output_name}"
            workflow = build_shot_workflow(
                template,
                relative_names,
                body.prompt,
                body.duration,
                body.seed,
                output_prefix,
                resolution=body.resolution,
                aspect_ratio=body.aspect_ratio,
                generation_mode=body.generation_mode,
                continue_from_previous=body.continue_from_previous,
                previous_output_name=body.previous_output_name,
                will_be_continued=body.will_be_continued,
                save_latent=body.save_latent,
                turbo_lora_enabled=body.turbo_lora_enabled,
                sage_attention_enabled=body.sage_attention_enabled,
                sampling_steps=body.sampling_steps,
                audio_tail_carryover=body.audio_tail_carryover,
                audio_feather_ticks=body.audio_feather_ticks,
                reference_video_names=relative_video_names,
            )
            stamp = time.strftime("%Y%m%d-%H%M%S")
            run_dir = data / "runs" / body.output_name / f"{stamp}-{uuid.uuid4().hex[:6]}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "workflow_api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
            result = target_client.submit(workflow, comfy_client_id)
            (run_dir / "run.json").write_text(json.dumps({"request": shot, "response": result}, ensure_ascii=False, indent=2), encoding="utf-8")
            estimated_seconds = estimate_workflow_seconds(workflow)
            return {
                **result, "run_dir": str(run_dir), "output_prefix": output_prefix,
                "comfy_url": target_url,
                "submitted_at": time.time(), "estimated_seconds": estimated_seconds,
            }
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
                entry = history[prompt_id]
                completed = bool(entry.get("status", {}).get("completed"))
                return {"status": "completed" if completed else "failed", "history": entry}
            queue = target_client.queue()
            for item in queue.get("queue_running", []):
                if len(item) > 1 and item[1] == prompt_id:
                    remaining, source = estimate_queue_remaining(queue, prompt_id, target_client)
                    live = getattr(target_client, "progress", lambda _id: None)(prompt_id) or {}
                    return {"status": "running", "estimated_remaining_seconds": remaining,
                            "eta_source": source, "progress_percent": live.get("progress_percent")}
            for item in queue.get("queue_pending", []):
                if len(item) > 1 and item[1] == prompt_id:
                    remaining, source = estimate_queue_remaining(queue, prompt_id, target_client)
                    return {"status": "queued", "estimated_remaining_seconds": remaining,
                            "eta_source": source}
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
            added = preserve(
                outputs,
                target_client.download_output if remote else output_dir_path,
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
            return {"results": existing, "added": added}
        except HTTPException:
            raise
        except (ValueError, FileNotFoundError, ComfyError) as exc:
            raise HTTPException(400, str(exc)) from exc

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
            safe_output = re.sub(
                r"[^\w\u4e00-\u9fff-]+", "_", Path(source.get("filename") or "video").stem,
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
        shot["results"] = [item for item in shot.get("results", []) if item.get("id") != result_id]
        save_project(data / "storyboard.json", project)
        return {"ok": True, "results": shot["results"]}

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
