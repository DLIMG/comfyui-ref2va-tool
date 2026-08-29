from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv"}


def resolve_managed_results_root(
    project: dict[str, Any],
    legacy_root: str | Path,
    *,
    create: bool = False,
) -> Path:
    project_dir = str(project.get("project_dir") or "").strip()
    if project_dir:
        project_path = Path(project_dir)
        if not project_path.is_absolute():
            raise ValueError("project_dir 必须是绝对路径")
        root = project_path / "06_生成视频"
    else:
        root = Path(legacy_root)
    root = root.resolve()
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"无法创建项目结果目录：{root}") from exc
    return root


def managed_root_containing(path: str | Path, roots: list[str | Path]) -> Path:
    target = Path(path).resolve()
    for root_value in roots:
        root = Path(root_value).resolve()
        try:
            target.relative_to(root)
            if target != root:
                return root
        except ValueError:
            continue
    raise ValueError("拒绝删除允许的结果库以外的文件")


def _safe_name(value: str, fallback: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value, flags=re.UNICODE).strip("_") or fallback


def find_video_outputs(history_entry: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for node in (history_entry.get("outputs") or {}).values():
        if not isinstance(node, dict):
            continue
        for values in node.values():
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "")
                if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                found.append({
                    "filename": Path(filename).name,
                    "subfolder": str(item.get("subfolder") or ""),
                    "type": str(item.get("type") or "output"),
                })
    return found


def find_fallback_outputs(output_name: str, output_root: str | Path) -> list[dict[str, str]]:
    root = Path(output_root)
    prefix = Path(output_name).name
    if not root.is_dir() or not prefix:
        return []
    matches = [
        path for path in root.iterdir()
        if path.is_file() and path.name.startswith(prefix + "_") and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return [{"filename": path.name, "subfolder": "", "type": "output"} for path in sorted(matches)]


def preserve_results(
    outputs: list[dict[str, str]],
    comfy_output_root: str | Path,
    results_root: str | Path,
    project_name: str,
    shot_id: str,
    prompt_id: str,
) -> list[dict[str, Any]]:
    source_root = Path(comfy_output_root).resolve()
    target_root = Path(results_root).resolve()
    created_at = datetime.now(timezone.utc).isoformat()
    preserved: list[dict[str, Any]] = []
    for output in outputs:
        subfolder = Path(str(output.get("subfolder") or ""))
        filename = Path(output["filename"]).name
        source = (source_root / subfolder / filename).resolve()
        if not source.is_file() and subfolder.name == source_root.name:
            source = (source_root / filename).resolve()
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("ComfyUI 输出路径越界") from exc
        if not source.is_file():
            continue
        result_id = uuid.uuid4().hex
        leaf = target_root / _safe_name(project_name, "project") / _safe_name(shot_id, "shot") / result_id
        leaf.mkdir(parents=True, exist_ok=False)
        destination = leaf / source.name
        shutil.copy2(source, destination)
        preserved.append({
            "id": result_id,
            "created_at": created_at,
            "prompt_id": prompt_id,
            "path": str(destination),
            "filename": destination.name,
            "source": output,
            "status": "ready",
            "error": "",
        })
    return preserved


def preserve_downloaded_results(
    outputs: list[dict[str, str]],
    downloader,
    results_root: str | Path,
    project_name: str,
    shot_id: str,
    prompt_id: str,
) -> list[dict[str, Any]]:
    target_root = Path(results_root).resolve()
    created_at = datetime.now(timezone.utc).isoformat()
    preserved: list[dict[str, Any]] = []
    for output in outputs:
        filename = Path(str(output.get("filename") or "")).name
        if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        payload = downloader(output)
        if not payload:
            continue
        result_id = uuid.uuid4().hex
        leaf = target_root / _safe_name(project_name, "project") / _safe_name(shot_id, "shot") / result_id
        leaf.mkdir(parents=True, exist_ok=False)
        destination = leaf / filename
        destination.write_bytes(payload)
        preserved.append({
            "id": result_id,
            "created_at": created_at,
            "prompt_id": prompt_id,
            "path": str(destination),
            "filename": filename,
            "source": output,
            "status": "ready",
            "error": "",
        })
    return preserved


def delete_managed_result(path: str | Path, results_root: str | Path) -> None:
    root = Path(results_root).resolve()
    target = Path(path).resolve()
    if target == root:
        raise ValueError("拒绝删除结果库根目录")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("拒绝删除结果库以外的文件") from exc
    if target.is_file():
        target.unlink()
    parent = target.parent
    while parent != root and parent.exists():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
