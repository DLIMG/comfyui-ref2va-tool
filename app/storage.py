from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


def default_project() -> dict[str, Any]:
    return {
        "name": "未命名项目",
        "advanced_settings": {
            "turbo_lora_enabled": True,
            "sage_attention_enabled": True,
            "sampling_steps": 8,
            "resolution": "0.4mp",
            "auto_upscale_enabled": False,
            "upscale_resolution": "720p",
            "generation_target": "local",
            "comfy_url": "http://192.168.11.103:8188",
        },
        "shots": [],
    }


def load_project(path: str | Path) -> dict[str, Any]:
    project_path = Path(path)
    if not project_path.exists():
        return default_project()
    with project_path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def migrate_project_references(project: dict[str, Any], migrations: dict[str, str]) -> dict[str, Any]:
    migrated = copy.deepcopy(project)
    for shot in migrated.get("shots", []):
        references = shot.get("references")
        if isinstance(references, list):
            shot["references"] = [migrations.get(reference, reference) for reference in references]
    return migrated


def save_project(path: str | Path, project: dict[str, Any]) -> None:
    project_path = Path(path)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=project_path.name, suffix=".tmp", dir=project_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(project, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, project_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stage_image(source: str | Path, target_dir: str | Path) -> Path:
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"参考图不存在: {source_path}")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:12]
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", source_path.stem, flags=re.UNICODE).strip("_") or "image"
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    destination = target / f"{safe_stem}_{digest}{source_path.suffix.lower()}"
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination


def save_uploaded_image(filename: str, content: bytes, upload_dir: str | Path) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise ValueError(f"不支持的图片格式: {suffix or '无扩展名'}")
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", Path(filename).stem, flags=re.UNICODE).strip("_") or "image"
    digest = hashlib.sha256(content).hexdigest()[:12]
    target = Path(upload_dir)
    target.mkdir(parents=True, exist_ok=True)
    destination = target / f"{safe_stem}_{digest}{suffix}"
    if not destination.exists():
        destination.write_bytes(content)
    return destination.resolve()


def save_uploaded_video(filename: str, content: bytes, upload_dir: str | Path) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError(f"不支持的视频格式: {suffix or '无扩展名'}")
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", Path(filename).stem, flags=re.UNICODE).strip("_") or "video"
    digest = hashlib.sha256(content).hexdigest()[:12]
    target = Path(upload_dir)
    target.mkdir(parents=True, exist_ok=True)
    destination = target / f"{safe_stem}_{digest}{suffix}"
    if not destination.exists():
        destination.write_bytes(content)
    return destination.resolve()
