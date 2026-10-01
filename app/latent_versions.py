"""Immutable per-submission AV latents, alongside the stable continuation slot."""

from __future__ import annotations

import copy
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from .storage import load_project, save_project


def add_versioned_latent_output(workflow: dict[str, Any], output_name: str) -> str:
    source = workflow.get("308") or workflow.get("203")
    if not source or source.get("class_type") != "H3ContinuousSaveLatent":
        raise ValueError("工作流缺少 AV latent 保存节点")
    name = f"{output_name}__run_{uuid.uuid4().hex}"
    node = copy.deepcopy(source)
    node["inputs"]["filename_prefix"] = f"codex_ref2va_tool/latents/{name}"
    node_id = str(max(int(key) for key in workflow if str(key).isdigit()) + 1)
    workflow[node_id] = node
    return name


def history_workflow(entry: dict[str, Any]) -> dict[str, Any]:
    prompt = entry.get("prompt")
    return prompt[2] if isinstance(prompt, (list, tuple)) and len(prompt) > 2 and isinstance(prompt[2], dict) else {}


def versioned_latent_name(workflow: dict[str, Any], output_name: str) -> str:
    prefix = f"codex_ref2va_tool/latents/{output_name}__run_"
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "H3ContinuousSaveLatent":
            continue
        inputs = node.get("inputs") or {}
        filename = str(inputs.get("filename_prefix") or "")
        if re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}", filename) and inputs.get("clip_index") == 1:
            return filename.rsplit("/", 1)[-1]
    return ""


def _record_path(data: Path, category: str, target_url: str, key: str) -> Path:
    digest = hashlib.sha256(f"{target_url}|{key}".encode("utf-8")).hexdigest()
    return data / "latent_versions" / category / f"{digest}.json"


def record_latent_run(data: Path, target_url: str, prompt_id: str, output_name: str,
                      latent_name: str, pass_number: int) -> None:
    record = {"prompt_id": prompt_id, "output_name": output_name,
              "latent_name": latent_name, "pass_number": pass_number, "comfy_url": target_url}
    save_project(_record_path(data, "prompts", target_url, prompt_id), record)


def latent_run(data: Path, target_url: str, prompt_id: str) -> dict[str, Any]:
    path = _record_path(data, "prompts", target_url, prompt_id)
    return load_project(path) if path.is_file() else {}


def validate_result_latent(latent_name: str, prompt_id: str = "", client: Any = None) -> None:
    """Legacy slots are usable only while their original job is the latest writer."""
    if re.search(r"__run_[0-9a-f]{32}$", latent_name):
        return
    unavailable = "无法确认该历史视频的旧版 latent 归属，可能已被覆盖；请重新一采后精修"
    if not prompt_id or client is None:
        raise ValueError(unavailable)

    def writes_slot(workflow: dict[str, Any]) -> bool:
        return any(
            isinstance(node, dict) and node.get("class_type") == "H3ContinuousSaveLatent"
            and (node.get("inputs") or {}).get("filename_prefix") == f"codex_ref2va_tool/latents/{latent_name}"
            and (node.get("inputs") or {}).get("clip_index", 1) == 1
            for node in workflow.values()
        )

    writers = []
    history = client.histories()
    for job_id, entry in history.items():
        if not isinstance(entry, dict) or not writes_slot(history_workflow(entry)):
            continue
        timestamps = [message[1].get("timestamp") for message in (entry.get("status") or {}).get("messages", [])
                      if isinstance(message, (list, tuple)) and len(message) > 1
                      and message[0] == "execution_start" and isinstance(message[1], dict)]
        if not timestamps or not isinstance(timestamps[0], (int, float)):
            raise ValueError(unavailable)
        writers.append((timestamps[0], job_id))
    source = history.get(prompt_id) or {}
    status = source.get("status") or {}
    source_stamps = [stamp for stamp, job_id in writers if job_id == prompt_id]
    if (not writers or not status.get("completed") or status.get("status_str", "success") != "success"
            or len(source_stamps) != 1
            or any(stamp >= source_stamps[0] for stamp, job_id in writers if job_id != prompt_id)):
        raise ValueError(unavailable)
    queue = client.queue()
    for job in [*queue.get("queue_running", []), *queue.get("queue_pending", [])]:
        if isinstance(job, (list, tuple)) and len(job) > 2 and isinstance(job[2], dict) and writes_slot(job[2]):
            raise ValueError("已有任务正在或即将覆盖该旧版 latent，请等待完成后选择对应结果")
