"""把当前故事板同步写回「它被导入时用的那个 JSON 文件」。

工具的工作副本一直是 ``data/storyboard.json``（外加 ``project_states/`` 里的
运行时快照）；通过「打开 JSON」打开的文件会自动记录为源文件，后续编辑同步回写。

当项目打开并自动绑定到某个源文件（``board["source_json_path"]``）之后，每次保存都会
把合并后的 storyboard 原样写回该文件，让磁盘上的作者副本保持同步。
「打开 JSON」会自动设置这个字段；新建故事板和无源文件的包导入使用内部工作副本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import save_project


SOURCE_PATH_FIELD = "source_json_path"


def normalize_source_path(raw: Any) -> str:
    """把用户给的路径规整成绝对 ``*.json`` 路径；空值返回空串。

    校验失败抛 ``ValueError``，调用方负责转成 4xx。
    """
    text = str(raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    path = Path(text).expanduser()
    if path.is_dir():
        raise ValueError("源文件路径指向的是一个目录，请填到具体 .json 文件")
    if path.suffix.lower() != ".json":
        raise ValueError("源文件必须是 .json 文件")
    if not path.parent.is_dir():
        raise ValueError(f"源文件所在目录不存在：{path.parent}")
    return str(path.resolve())


def mirror_source_json(project: dict[str, Any]) -> dict[str, Any]:
    """把 *project* 写回它绑定的源 JSON；**永不抛异常**。

    返回 ``{"mirrored": bool, "mirror_path": str, "mirror_error": str}``，
    供接口回给前端做状态提示。未绑定、内容未变、或写失败时 ``mirrored`` 为 False。
    """
    result: dict[str, Any] = {"mirrored": False, "mirror_path": "", "mirror_error": ""}
    raw = project.get(SOURCE_PATH_FIELD) if isinstance(project, dict) else ""
    if not str(raw or "").strip():
        return result
    try:
        target = Path(normalize_source_path(raw))
    except ValueError as exc:
        result["mirror_error"] = str(exc)
        return result
    result["mirror_path"] = str(target)
    try:
        # save_project 用 json.dump(..., ensure_ascii=False, indent=2) 且不补尾换行；
        # 这里用同样的序列化方式做「内容没变就别写」的比较，避免每次自动保存都动文件 mtime。
        rendered = json.dumps(project, ensure_ascii=False, indent=2)
        if target.is_file() and target.read_text(encoding="utf-8") == rendered:
            return result
        save_project(target, project)
        result["mirrored"] = True
    except OSError as exc:
        result["mirror_error"] = f"同步写回失败：{exc}"
    return result
