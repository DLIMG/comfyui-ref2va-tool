from __future__ import annotations

import hashlib
import math
import re
import shutil
from pathlib import Path
from typing import Any

from .workflow import RESOLUTION_MAP


_RATIOS = {"16:9": (16, 9), "9:16": (9, 16), "4:3": (4, 3), "3:4": (3, 4), "1:1": (1, 1)}


def target_dimensions(resolution: str, aspect_ratio: str, multiple: int = 32) -> tuple[int, int]:
    if resolution not in RESOLUTION_MAP:
        raise ValueError(f"不支持的目标清晰度: {resolution}")
    if aspect_ratio not in _RATIOS:
        raise ValueError(f"不支持的画幅: {aspect_ratio}")
    width_ratio, height_ratio = _RATIOS[aspect_ratio]
    total_pixels = RESOLUTION_MAP[resolution] * 1024 * 1024
    scale = math.sqrt(total_pixels / (width_ratio * height_ratio))
    return (
        round(width_ratio * scale / multiple) * multiple,
        round(height_ratio * scale / multiple) * multiple,
    )


def stage_video(source: str | Path, target_dir: str | Path) -> Path:
    source_path = Path(source)
    if not source_path.is_file() or source_path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise FileNotFoundError(f"待放大视频不存在或格式不支持: {source_path}")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:12]
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", source_path.stem, flags=re.UNICODE).strip("_") or "video"
    destination = Path(target_dir) / f"{safe_stem}_{digest}{source_path.suffix.lower()}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination


def build_video_upscale_workflow(
    input_name: str,
    output_prefix: str,
    *,
    aspect_ratio: str,
    target_resolution: str = "720p",
) -> dict[str, Any]:
    if target_resolution not in {"720p", "1080p"}:
        raise ValueError("高清放大仅支持720P或1080P")
    width, height = target_dimensions(target_resolution, aspect_ratio)
    downscale_ratio = math.sqrt(RESOLUTION_MAP[target_resolution] / RESOLUTION_MAP["480p"]) / 4
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"file": input_name}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "4": {"class_type": "ImageUpscaleWithModelBatched", "inputs": {
            "upscale_model": ["3", 0], "images": ["2", 0], "per_batch": 1,
            "downscale_ratio": downscale_ratio, "downscale_method": "lanczos", "precision": "float16",
        }},
        "5": {"class_type": "ImageScale", "inputs": {
            "image": ["4", 0], "upscale_method": "lanczos", "width": width, "height": height, "crop": "disabled",
        }},
        "6": {"class_type": "CreateVideo", "inputs": {
            "images": ["5", 0], "fps": ["2", 2], "audio": ["2", 1],
            "bit_depth": ["2", 3], "color_space": ["2", 4],
        }},
        "7": {"class_type": "SaveVideo", "inputs": {
            "video": ["6", 0], "filename_prefix": output_prefix, "format": "mp4", "codec": "h264",
        }},
    }
