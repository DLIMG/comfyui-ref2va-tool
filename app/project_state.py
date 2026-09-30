from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .results import VIDEO_EXTENSIONS
from .storage import load_project, save_project


RUNTIME_FIELDS = (
    "prompt_id", "run_dir", "comfy_url", "status", "error", "results",
    "submitted_at", "started_at", "estimated_seconds", "estimated_remaining_seconds",
    "eta_source", "progress_percent", "refine_job",
)


def _safe_name(value: str, fallback: str = "storyboard") -> str:
    return re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("_.") or fallback


def runtime_state_path(project: dict[str, Any], data_root: str | Path) -> Path:
    project_dir = str(project.get("project_dir") or "").strip()
    name = str(project.get("name") or "未命名项目").strip()
    if project_dir and Path(project_dir).is_absolute() and Path(project_dir).is_dir():
        return Path(project_dir) / "05_故事板配置" / ".ref2va-state" / f"{_safe_name(name)}.json"
    identity = f"{project_dir}|{name}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:16]
    return Path(data_root) / "project_states" / f"{_safe_name(name)}-{digest}.json"


def persist_project_runtime(project: dict[str, Any], data_root: str | Path) -> Path:
    snapshot = {
        "version": 1,
        "name": project.get("name", ""),
        "project_dir": project.get("project_dir", ""),
        "shots": [],
    }
    for shot in project.get("shots") or []:
        if not isinstance(shot, dict) or not str(shot.get("id") or "").strip():
            continue
        runtime = {"id": shot["id"], "output_name": shot.get("output_name", "")}
        for field in RUNTIME_FIELDS:
            if field in shot:
                runtime[field] = deepcopy(shot[field])
        snapshot["shots"].append(runtime)
    path = runtime_state_path(project, data_root)
    save_project(path, snapshot)
    return path


def load_project_runtime(project: dict[str, Any], data_root: str | Path) -> dict[str, Any] | None:
    path = runtime_state_path(project, data_root)
    return load_project(path) if path.is_file() else None


def _result_from_file(path: Path, shot: dict[str, Any]) -> dict[str, Any]:
    stat = path.stat()
    result_id = path.parent.name if re.fullmatch(r"[0-9a-fA-F]{16,64}", path.parent.name) else hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return {
        "id": result_id,
        "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "prompt_id": "",
        "path": str(path.resolve()),
        "filename": path.name,
        "source": {},
        "status": "ready",
        "error": "",
        "resolution": shot.get("resolution", ""),
        "recovered": True,
    }


def discover_project_results(project: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    project_dir = str(project.get("project_dir") or "").strip()
    if not project_dir or not Path(project_dir).is_absolute():
        return {}
    root = Path(project_dir) / "06_生成视频"
    if not root.is_dir():
        return {}
    discovered: dict[str, list[dict[str, Any]]] = {}
    for shot in project.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id") or "").strip()
        if not shot_id:
            continue
        candidates = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and shot_id.lower() in {part.lower() for part in path.parts}]
        if candidates:
            discovered[shot_id] = [_result_from_file(path, shot) for path in sorted(candidates, key=lambda item: item.stat().st_mtime)]
    return discovered


def restore_imported_project(imported: dict[str, Any], current: dict[str, Any], data_root: str | Path) -> tuple[dict[str, Any], int]:
    if not isinstance(imported, dict) or not isinstance(imported.get("shots"), list):
        raise ValueError("导入项目的 shots 必须是数组")
    seen: set[str] = set()
    for index, shot in enumerate(imported["shots"]):
        if not isinstance(shot, dict):
            raise ValueError(f"导入项目的第 {index + 1} 个片段必须是对象")
        shot_id = str(shot.get("id") or "").strip()
        if not shot_id:
            raise ValueError(f"导入项目的第 {index + 1} 个片段缺少有效 id")
        if shot_id in seen:
            raise ValueError(f"导入项目包含重复片段 id：{shot_id}")
        seen.add(shot_id)

    merged = deepcopy(imported)
    if not str(merged.get("project_dir") or "").strip():
        merged["project_dir"] = current.get("project_dir", "")
    saved = load_project_runtime(merged, data_root)
    saved_by_id = {shot.get("id"): shot for shot in (saved or {}).get("shots", []) if isinstance(shot, dict)}
    recovered = 0
    for shot in merged["shots"]:
        if shot.get("results"):
            continue
        runtime = saved_by_id.get(shot.get("id"))
        if runtime:
            for field in RUNTIME_FIELDS:
                if field in runtime:
                    shot[field] = deepcopy(runtime[field])

    discovered = discover_project_results(merged)
    for shot in merged["shots"]:
        existing = shot.setdefault("results", [])
        existing_paths = {str(Path(item.get("path", "")).resolve()).lower() for item in existing if item.get("path")}
        for result in discovered.get(shot.get("id"), []):
            if result["path"].lower() not in existing_paths:
                existing.append(result)
                existing_paths.add(result["path"].lower())
                recovered += 1
        if existing and shot.get("status") in {None, "", "draft", "failed"}:
            shot["status"] = "completed"
            shot["error"] = ""
    return merged, recovered
