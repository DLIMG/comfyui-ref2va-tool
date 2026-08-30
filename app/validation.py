from __future__ import annotations

import re
from pathlib import Path
from typing import Any


REQUIRED_SECTIONS = (
    "subject_definitions:",
    "summary:",
    "retention_analysis:",
    "detailed_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
)
GENERATION_MODES = ("r2va", "fl2va")


def validate_shot(shot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    generation_mode = str(shot.get("generation_mode") or "r2va")
    continuation = bool(shot.get("continue_from_previous", False))
    if generation_mode not in GENERATION_MODES:
        errors.append(f"不支持的生成模式: {generation_mode}")
    references = shot.get("references") or []
    reference_videos = shot.get("reference_videos") or []
    if not references and not reference_videos:
        errors.append("至少添加一张参考图或一段参考视频")
    if generation_mode == "fl2va" and not continuation and len(references) < 2:
        errors.append("FL2VA首段必须依次提供首帧和尾帧")
    if continuation and not str(shot.get("previous_output_name") or "").strip():
        errors.append("延续镜头必须指定上一镜输出名称")
    for index, reference in enumerate(references, start=1):
        if not Path(str(reference)).is_file():
            errors.append(f"参考图不存在（Picture {index}）: {reference}")
    if len(reference_videos) > 3:
        errors.append("参考视频最多3段")
    if generation_mode != "r2va" and reference_videos:
        errors.append("参考视频当前仅支持R2VA模式")
    for index, reference in enumerate(reference_videos, start=1):
        path = Path(str(reference))
        if not path.is_file():
            errors.append(f"参考视频不存在（Video {index}）: {reference}")
        elif path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
            errors.append(f"参考视频格式不支持（Video {index}）: {reference}")

    prompt = str(shot.get("prompt") or "")
    if not prompt.strip():
        errors.append("提示词不能为空")

    try:
        if float(shot.get("duration", 0)) <= 0:
            errors.append("时长必须大于0")
    except (TypeError, ValueError):
        errors.append("时长必须是数字")

    output_name = str(shot.get("output_name") or "")
    if not output_name or not re.fullmatch(r"[\w\u4e00-\u9fff.-]+", output_name, flags=re.UNICODE):
        errors.append("输出名称不能为空，且不能包含路径分隔符或特殊符号")
    return errors
