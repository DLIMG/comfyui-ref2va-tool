"""Preview a VideoAnalyzer Ref2VA result as one editable storyboard draft."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from .storage import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


LABELS = {"Picture": "references", "Video": "reference_videos", "Audio": "reference_audios"}
SECTIONS = (
    "subject_definitions:", "summary:", "retention_analysis:",
    "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
)


def preview_video_analyzer(directory: str, reference_video: str = "") -> tuple[dict[str, Any], list[str]]:
    root = Path(directory).expanduser().resolve()
    prompt_file = root / "prompt.txt"
    if not prompt_file.is_file():
        raise ValueError("分析目录中找不到 prompt.txt")
    if prompt_file.stat().st_size > 200_000:
        raise ValueError("prompt.txt 超过 200 KB，无法作为单镜提示词导入")
    prompt = prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise ValueError("prompt.txt 为空")

    frames_dir = root / "keyframes"
    frame_files = sorted(
        (path for path in frames_dir.glob("shot_*.*") if path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: int(re.fullmatch(r"shot_(\d+)", path.stem).group(1))
        if re.fullmatch(r"shot_(\d+)", path.stem) else 10_000,
    ) if frames_dir.is_dir() else []
    frame_files = [path for path in frame_files if re.fullmatch(r"shot_(\d+)", path.stem)]
    if len(frame_files) > 9:
        raise ValueError("逐镜参考帧超过 9 张，请先在 VideoAnalyzer 中缩小镜头范围")
    frame_numbers = [int(re.fullmatch(r"shot_(\d+)", path.stem).group(1)) for path in frame_files]
    if frame_numbers != list(range(1, len(frame_files) + 1)):
        raise ValueError("keyframes/shot_N 文件编号必须从 1 连续排列，避免 Picture 错位")

    video = Path(reference_video).expanduser().resolve() if reference_video.strip() else None
    if video and (not video.is_file() or video.suffix.lower() not in VIDEO_EXTENSIONS):
        raise ValueError("参考视频路径不存在或格式不受支持")
    labels = {kind: {int(n) for n in re.findall(rf"<{kind}\s+(\d+)>", prompt, re.IGNORECASE)} for kind in LABELS}
    warnings = ["这是可编辑草稿；导入前后都要核对逐镜标签、时长、原声音轨和素材对应关系。"]
    if not all(section in prompt for section in SECTIONS):
        warnings.append("提示词未包含完整的 Ref2VA 六段标题，请在编辑器中检查。")
    if labels["Picture"] and max(labels["Picture"]) > len(frame_files):
        warnings.append(f"提示词引用到 Picture {max(labels['Picture'])}，但只找到 {len(frame_files)} 张 shot_N 参考帧。")
    if labels["Video"] and not video:
        warnings.append("提示词包含 Video 标签；请在镜头编辑器中补充原参考视频。")
    if video and labels["Video"] and max(labels["Video"]) > 1:
        warnings.append("提示词引用多个 Video 标签；当前只映射一段原参考视频，其他视频需手动补齐。")
    if labels["Audio"]:
        warnings.append("请核实 Audio 标签是否对应参考视频原声；若不是，请手动添加纯音频参考并重编号。")
    if not frame_files and not video:
        warnings.append("尚无可用参考素材；导入后需手动添加图片、视频或音频。")

    shot_id = f"VA_{uuid.uuid4().hex[:8]}"
    shot = {
        "id": shot_id,
        "title": f"VideoAnalyzer 草稿 · {root.name}",
        "output_name": shot_id,
        "references": [str(path) for path in frame_files],
        "reference_videos": [str(video)] if video else [],
        "reference_audios": [],
        "prompt": prompt,
        "generation_mode": "r2va",
        "continue_from_previous": False,
        "save_latent": False,
        "duration": 6,
        "seed": 1,
        "resolution": "0.4mp",
        "aspect_ratio": "16:9",
        "selected": False,
        "status": "draft",
        "prompt_id": "",
        "run_dir": "",
        "error": "",
        "results": [],
    }
    return shot, warnings
