"""Safe, deliberately narrow import of AIMixer MiniMax H3 Director packs.

The Director plugin owns its executable timeline format.  This module only
converts the portable authoring layer (shared parameters, asset groups and
media) into a Ref2VA storyboard.  It never imports cache, generated output,
segment continuity or latent state.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .storage import AUDIO_MEDIA_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, default_project


PACK_FORMAT = "minimax-h3-director-pack"
MAX_PACK_ENTRIES = 2_000
MAX_PACK_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_PACK_FILE_BYTES = 2 * 1024 * 1024 * 1024
PACK_MEDIA_ROOT = "director_pack_imports"
_SLOT_RE = re.compile(r"^(Picture([1-9])|Video([1-3])|Audio([1-3])|start|end)\.[A-Za-z0-9]{1,8}$", re.I)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Director 包中的 {path.name} 不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Director 包中的 {path.name} 必须是对象")
    return value


def _safe_member(name: str) -> PurePosixPath:
    value = PurePosixPath(name.replace("\\", "/"))
    if not name or value.is_absolute() or ".." in value.parts or any(part in {"", "."} for part in value.parts):
        raise ValueError("Director 包包含不安全的文件路径")
    if any(ord(char) > 127 for char in name):
        raise ValueError("Director 包路径必须使用 ASCII 名称")
    return value


def extract_director_pack(pack_path: Path, destination_root: Path) -> Path:
    """Extract a pack beneath ``destination_root`` after zip-slip and size checks."""
    if pack_path.suffix.lower() != ".zip":
        raise ValueError("Director 包必须是 .mmxpack.zip 或 .zip 文件")
    try:
        archive = zipfile.ZipFile(pack_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("Director 包不是有效 ZIP 文件") from exc
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos or len(infos) > MAX_PACK_ENTRIES:
            raise ValueError("Director 包文件数量为空或超过安全上限")
        total = 0
        for info in infos:
            _safe_member(info.filename)
            if info.file_size < 0 or info.file_size > MAX_PACK_FILE_BYTES:
                raise ValueError("Director 包包含超过安全上限的单个文件")
            total += info.file_size
            if total > MAX_PACK_UNCOMPRESSED_BYTES:
                raise ValueError("Director 包解压后的总大小超过安全上限")
        root = destination_root / PACK_MEDIA_ROOT / uuid.uuid4().hex
        root.mkdir(parents=True, exist_ok=False)
        for info in infos:
            target = root.joinpath(*_safe_member(info.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return root


def _task_type(pack_meta: dict[str, Any], shared: dict[str, Any]) -> str:
    raw = str(pack_meta.get("taskType") or pack_meta.get("task_type") or shared.get("taskType") or "").lower()
    if "fl2v" in raw or "first" in raw and "last" in raw:
        return "fl2va"
    if "r2v" in raw or "reference" in raw:
        return "r2va"
    raise ValueError("首版仅支持 Director 的 r2v（参考主体）与 fl2v（首尾帧）包")


def _media_path(root: Path, raw: Any, allowed_extensions: set[str]) -> Path | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        raw = raw.get("imageFile") or raw.get("videoFile") or raw.get("audioFile") or raw.get("fileName")
    candidate = PurePosixPath(str(raw).replace("\\", "/").lstrip("/"))
    if not candidate.parts or ".." in candidate.parts or candidate.is_absolute():
        return None
    path = root.joinpath(*candidate.parts)
    if path.is_file() and path.suffix.lower() in allowed_extensions:
        return path.resolve()
    return None


def _slots(root: Path, folder: Path, records: Any, kind: str) -> list[Path]:
    extension_set = IMAGE_EXTENSIONS if kind == "image" else VIDEO_EXTENSIONS if kind == "video" else AUDIO_MEDIA_EXTENSIONS
    value_key = "imageFile" if kind == "image" else "videoFile" if kind == "video" else "audioFile"
    # Director 包的 index 约定不统一：ComfyUI 插件扫描目录时按 `PictureN` 记为 N-1（0 起），
    # 而部分导出包直接写 1 起。因此先按原始值收齐，再整体判断基准并统一归一化到 1 起，
    # 避免 0 起与 1 起两套编号在合并时互相覆盖（旧实现用 `or` 兜底，index=0 会被当成缺失）。
    raw: list[tuple[int, Path]] = []
    if isinstance(records, list):
        for position, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            path = _media_path(root, record.get(value_key) or record.get("fileName"), extension_set)
            if not path:
                continue
            raw_index = record.get("index")
            if raw_index is None:
                raw_index = record.get("slot")
            try:
                slot = int(raw_index) if raw_index is not None else position
            except (TypeError, ValueError):
                slot = position
            raw.append((slot, path))
    offset = 1 if raw and min(slot for slot, _ in raw) == 0 else 0
    found: dict[int, Path] = {}
    for slot, path in raw:
        found[slot + offset] = path
    prefix = {"image": "Picture", "video": "Video", "audio": "Audio"}[kind]
    for path in folder.iterdir() if folder.is_dir() else []:
        match = re.fullmatch(rf"{prefix}(\d+)\.[A-Za-z0-9]{{1,8}}", path.name, re.I)
        if match and path.suffix.lower() in extension_set:
            found.setdefault(int(match.group(1)), path.resolve())
    return [found[index] for index in sorted(found)]


def _keyframe(root: Path, folder: Path, record: Any, name: str) -> Path | None:
    candidate = _media_path(root, record, IMAGE_EXTENSIONS)
    if candidate:
        return candidate
    for path in folder.glob(f"{name}.*"):
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            return path.resolve()
    return None


def _prompt(*parts: Any) -> str:
    return "\n\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _safe_id(value: Any, index: int, seen: set[str]) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("_.") or f"D{index:02d}"
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}_{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _duration(group: dict[str, Any]) -> float:
    try:
        value = float(group.get("durationSec"))
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    try:
        frames = int(group.get("frameCount") or group.get("length") or 124)
        return max(1.0, frames / 24)
    except (TypeError, ValueError):
        return 5.0


def convert_director_pack(root: Path) -> tuple[dict[str, Any], list[str]]:
    """Convert extracted Director authoring assets to a clean Ref2VA project."""
    pack_meta = _read_json(root / "pack.json")
    if pack_meta.get("format") not in {None, "", PACK_FORMAT}:
        raise ValueError("不是受支持的 MiniMax H3 Director 包")
    shared_folder = root / "shared_params"
    shared_json = _read_json(shared_folder / "shared_params.json")
    generation_mode = _task_type(pack_meta, shared_json)
    enabled = bool(shared_json.get("commonEnabled") or shared_json.get("common_enabled"))
    shared = {
        "enabled": enabled,
        "prompt": str(shared_json.get("prompt") or "").strip(),
        "references": [str(path) for path in _slots(root, shared_folder, shared_json.get("refs"), "image")],
        "reference_videos": [str(path) for path in _slots(root, shared_folder, shared_json.get("refVideos") or shared_json.get("ref_videos"), "video")],
        "reference_audios": [str(path) for path in _slots(root, shared_folder, shared_json.get("refAudios") or shared_json.get("ref_audios"), "audio")],
    }
    warnings: list[str] = ["未导入 Director 段间引导、缓存、Refine、源视频编辑或任何 AV Latent 状态。"]
    if not enabled and any(shared[key] for key in ("prompt", "references", "reference_videos", "reference_audios")):
        warnings.append("Director 包的公共参数原本未启用；素材已保留在公共层，但提交时不会生效，直到你在工作台启用它。")
    if generation_mode == "fl2va" and (shared["reference_videos"] or shared["reference_audios"]):
        warnings.append("FL2VA 不使用公共视频/音频参考，已保留但不会提交。")

    groups_root = root / "asset_groups"
    group_dirs = sorted((path for path in groups_root.iterdir() if path.is_dir()), key=lambda path: path.name) if groups_root.is_dir() else []
    if not group_dirs:
        raise ValueError("Director 包没有可导入的 asset_groups 素材组")
    shots: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, folder in enumerate(group_dirs, start=1):
        group = _read_json(folder / "group.json")
        shot_id = _safe_id(group.get("id"), index, seen_ids)
        local_images = _slots(root, folder, group.get("refs"), "image")
        if generation_mode == "fl2va":
            start = _keyframe(root, folder, group.get("startImage") or group.get("genImage"), "start")
            end = _keyframe(root, folder, group.get("endImage"), "end")
            if not start or not end:
                raise ValueError(f"FL2V 素材组 {folder.name} 缺少可用的首帧或尾帧")
            references = [str(start), str(end), *map(str, local_images)]
            videos: list[str] = []
            audios: list[str] = []
        else:
            references = [str(path) for path in local_images]
            videos = [str(path) for path in _slots(root, folder, group.get("refVideos") or group.get("ref_videos"), "video")]
            audios = [str(path) for path in _slots(root, folder, group.get("refAudios") or group.get("ref_audios"), "audio")]
        shots.append({
            "id": shot_id,
            "title": str(group.get("title") or group.get("name") or f"Director {index:02d}"),
            "output_name": f"{shot_id}_Director",
            "references": references,
            "reference_videos": videos,
            "reference_audios": audios,
            "prompt": str(group.get("prompt") or "").strip(),
            "duration": _duration(group),
            "seed": int((pack_meta.get("widgets") or {}).get("seed") or 1),
            "resolution": "0.4mp",
            "aspect_ratio": "16:9",
            "generation_mode": generation_mode,
            "continue_from_previous": False,
            "save_latent": False,
            "audio_tail_carryover": "No Audio Carryover",
            "audio_feather_ticks": 0,
            "selected": False,
            "status": "draft",
            "prompt_id": "",
            "run_dir": "",
            "error": "",
            "results": [],
            "director_pack_group": folder.name,
        })
    project = default_project()
    task_label = "R2VA" if generation_mode == "r2va" else "FL2VA"
    project.update({
        "name": f"Director 导入_{task_label}",
        "shared": shared,
        "shots": shots,
        "director_pack_source": {"format": PACK_FORMAT, "root": str(root), "task_type": generation_mode},
    })
    widgets = pack_meta.get("widgets") if isinstance(pack_meta.get("widgets"), dict) else {}
    if isinstance(widgets.get("steps"), int) and 1 <= widgets["steps"] <= 100:
        project["advanced_settings"]["sampling_steps"] = widgets["steps"]
    return project, warnings
