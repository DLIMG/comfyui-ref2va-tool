from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


TARGETS = {
    "condition": ("136", "MiniMaxH3ReferenceToVideo"),
    "prompt": ("138", "PrimitiveStringMultiline"),
    "duration": ("132", "PrimitiveFloat"),
    "seed": ("129", "RandomNoise"),
    "save": ("92", "SaveVideo"),
    "resolution": ("115", "ResolutionSelector"),
}

RESOLUTION_MAP = {
    **{f"{value / 10:.1f}mp": value / 10 for value in range(2, 11)},
    "480p": 0.4,
    "720p": 0.9,
    "1080p": 2.1,
}
ASPECT_RATIO_MAP = {
    "16:9": "16:9 (Widescreen)",
    "9:16": "9:16 (Portrait Widescreen)",
    "4:3": "4:3 (Standard)",
    "3:4": "3:4 (Portrait Standard)",
    "1:1": "1:1 (Square)",
}
TURBO_8STEP_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
R2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
FL2VA_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
MASKED_CONTEXT_FRAMES = 39
BASE_MODEL_STEPS = 15


def load_template(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        workflow = json.load(handle)
    validate_template(workflow)
    return workflow


def validate_template(workflow: dict[str, Any]) -> None:
    if not isinstance(workflow, dict) or "nodes" in workflow:
        raise ValueError("工作流必须是 ComfyUI API 格式")
    for node_id, expected_type in TARGETS.values():
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != expected_type:
            raise ValueError(f"缺少节点 {node_id}: {expected_type}")
        if not isinstance(node.get("inputs"), dict):
            raise ValueError(f"节点 {node_id} 缺少 inputs")

    required_nodes = {
        "127": "UNETLoader",
        "150": "LoraLoaderModelOnly",
        "142": "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "124": "BasicScheduler",
        "126": "BasicGuider",
        "123": "KSamplerSelect",
    }
    for node_id, expected_type in required_nodes.items():
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != expected_type:
            raise ValueError(f"缺少核心节点 {node_id}: {expected_type}")
        if not isinstance(node.get("inputs"), dict):
            raise ValueError(f"核心节点 {node_id} 缺少 inputs")

    lora_inputs = workflow["150"]["inputs"]
    if lora_inputs.get("model") != ["127", 0] or lora_inputs.get("lora_name") != TURBO_8STEP_LORA:
        raise ValueError("8-step LoRA 必须连接 UNETLoader 127 并使用指定模型")
    if workflow["142"]["inputs"].get("model") != ["150", 0]:
        raise ValueError("SageAttention 必须连接 8-step LoRA 150")
    if workflow["124"]["inputs"].get("model") != ["142", 0]:
        raise ValueError("BasicScheduler 必须连接 SageAttention 142")
    if workflow["126"]["inputs"].get("model") != ["142", 0]:
        raise ValueError("BasicGuider 必须连接 SageAttention 142")
    if workflow["124"]["inputs"].get("scheduler") != "simple":
        raise ValueError("BasicScheduler scheduler 必须是 simple")
    if workflow["124"]["inputs"].get("steps") != 8:
        raise ValueError("BasicScheduler steps 必须是 8")
    if workflow["123"]["inputs"].get("sampler_name") != "res_multistep":
        raise ValueError("采样器必须是 res_multistep")

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "MiniMaxH3TeaCache":
            raise ValueError("工作流不得包含 TeaCache 节点")
        lora_name = node.get("inputs", {}).get("lora_name")
        if isinstance(lora_name, str) and "4step" in lora_name.lower():
            raise ValueError("工作流不得包含 4-step LoRA")


def build_workflow(
    template: dict[str, Any],
    reference_names: list[str],
    prompt: str,
    duration: float,
    seed: int,
    output_prefix: str,
    resolution: str = "480p",
    aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    validate_template(template)
    if not reference_names:
        raise ValueError("至少需要一张参考图")
    if resolution not in RESOLUTION_MAP:
        raise ValueError(f"不支持的清晰度: {resolution}")
    if aspect_ratio not in ASPECT_RATIO_MAP:
        raise ValueError(f"不支持的画幅: {aspect_ratio}")
    result = copy.deepcopy(template)
    condition_inputs = result["136"]["inputs"]
    referenced_load_ids = {
        value[0]
        for key, value in condition_inputs.items()
        if key.startswith("ref_images.ref_image_")
        and isinstance(value, list)
        and len(value) == 2
        and isinstance(result.get(str(value[0])), dict)
        and result[str(value[0])].get("class_type") == "LoadImage"
    }
    for node_id in referenced_load_ids:
        result.pop(str(node_id))

    for key in list(condition_inputs):
        if key.startswith("ref_images.ref_image_"):
            condition_inputs.pop(key)

    next_id = max(int(node_id) for node_id in result if str(node_id).isdigit()) + 1
    for index, image_name in enumerate(reference_names):
        node_id = str(next_id + index)
        result[node_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        condition_inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]

    result["138"]["inputs"]["value"] = prompt
    result["132"]["inputs"]["value"] = float(duration)
    result["129"]["inputs"]["noise_seed"] = int(seed)
    result["92"]["inputs"]["filename_prefix"] = output_prefix.replace("\\", "/")
    result["115"]["inputs"]["megapixels"] = RESOLUTION_MAP[resolution]
    result["115"]["inputs"]["aspect_ratio"] = ASPECT_RATIO_MAP[aspect_ratio]
    return result


def _load_image_node(image_name: str) -> dict[str, Any]:
    return {"class_type": "LoadImage", "inputs": {"image": image_name}}


def _configure_acceleration(
    workflow: dict[str, Any],
    turbo_lora_enabled: bool,
    sage_attention_enabled: bool,
    sampling_steps: int | None,
) -> None:
    sampling_steps = sampling_steps if sampling_steps is not None else (8 if turbo_lora_enabled else BASE_MODEL_STEPS)
    if not 1 <= sampling_steps <= 100:
        raise ValueError("采样步数必须在 1 到 100 之间")
    model_source = ["127", 0]
    if turbo_lora_enabled:
        model_source = ["150", 0]
    else:
        workflow.pop("150", None)

    if sage_attention_enabled:
        workflow["142"]["inputs"]["model"] = model_source
        model_source = ["142", 0]
    else:
        workflow.pop("142", None)

    workflow["124"]["inputs"]["model"] = model_source
    workflow["126"]["inputs"]["model"] = model_source
    workflow["124"]["inputs"]["steps"] = sampling_steps


def _remove_condition_reference_loaders(workflow: dict[str, Any]) -> None:
    condition = workflow.get("136", {}).get("inputs", {})
    referenced = {
        str(value[0])
        for key, value in condition.items()
        if key.startswith("ref_images.ref_image_")
        and isinstance(value, list)
        and len(value) == 2
    }
    for node_id in referenced:
        if workflow.get(node_id, {}).get("class_type") == "LoadImage":
            workflow.pop(node_id, None)


def _configure_fl2va_start(workflow: dict[str, Any], references: list[str]) -> None:
    _remove_condition_reference_loaders(workflow)
    workflow["127"]["inputs"]["unet_name"] = FL2VA_MODEL
    workflow["200"] = _load_image_node(references[0])
    workflow["201"] = _load_image_node(references[1])
    inputs: dict[str, Any] = {
        "clip": ["128", 0],
        "vae": ["119", 0],
        "prompt": ["138", 0],
        "width": ["115", 0],
        "height": ["115", 1],
        "duration": ["132", 0],
        "ref_image_size": "match",
        "first_frame": ["200", 0],
        "last_frame": ["201", 0],
    }
    for index, reference in enumerate(references[2:], start=1):
        node_id = str(204 + index)
        workflow[node_id] = _load_image_node(reference)
        inputs[f"qwen_reference_{index}"] = [node_id, 0]
    workflow["136"] = {"class_type": "H3ContinuousStartV14", "inputs": inputs}


def _handover_inputs() -> dict[str, Any]:
    return {
        "images": ["122", 0],
        "preset": "Balanced",
        "analysis_window": 72,
        "freeze_hold": 8,
        "safety_margin": 3,
        "context_frames": "39",
        "analysis_size": 192,
        "final_mean_diff_threshold": 0.012,
        "final_active_pixel_threshold": 0.025,
        "max_final_active_area_percent": 3.0,
        "transition_mean_diff_threshold": 0.002,
        "transition_active_pixel_threshold": 0.01,
        "max_transition_active_area_percent": 1.0,
        "min_static_transition_percent": 70.0,
        "max_consecutive_motion_outliers": 2,
        "final_reference_frames": 15,
        "min_final_match_percent": 75.0,
        "max_consecutive_final_outliers": 3,
        "safety_mode": "fixed",
    }


def _add_latent_outputs(
    workflow: dict[str, Any], output_name: str, continuation: bool,
    will_be_continued: bool, save_latent: bool,
) -> None:
    needs_handover = continuation or save_latent or will_be_continued
    if not needs_handover:
        return
    workflow["202"] = {
        "class_type": "H3ContinuousAnalyzeHandoverV14",
        "inputs": _handover_inputs(),
    }
    save_inputs: dict[str, Any] = {
        "latent": ["125", 0],
        "filename_prefix": f"codex_ref2va_tool/latents/{output_name}",
        "clip_index": 1,
        "handover": ["202", 0],
    }
    stitch_inputs: dict[str, Any] = {
        "images": ["122", 0],
        "output_mode": "Stitch Ready" if will_be_continued else "Final Clip",
        "handover": ["202", 0],
        "audio": ["121", 0],
    }
    if continuation:
        save_inputs["head_context_frames"] = ["201", 2]
        stitch_inputs["head_context_frames"] = ["201", 2]
    if save_latent or will_be_continued:
        workflow["203"] = {"class_type": "H3ContinuousSaveLatent", "inputs": save_inputs}
    workflow["204"] = {"class_type": "H3ContinuousStitchOutputV14", "inputs": stitch_inputs}
    workflow["130"]["inputs"]["images"] = ["204", 0]
    workflow["130"]["inputs"]["audio"] = ["204", 1]


def _configure_continuation(
    workflow: dict[str, Any],
    prompt: str,
    duration: float,
    previous_output_name: str,
    generation_mode: str,
    references: list[str],
    audio_tail_carryover: str = "Full Previous Tail",
    audio_feather_ticks: int = 0,
) -> None:
    total_duration = float(duration) + MASKED_CONTEXT_FRAMES / 24.0
    workflow["132"]["inputs"]["value"] = total_duration
    workflow["200"] = {
        "class_type": "H3ContinuousLoadLatent",
        "inputs": {
            "latent_path": f"codex_ref2va_tool/latents/{previous_output_name}_00001.safetensors",
            "clip_index": 1,
        },
    }
    continue_inputs: dict[str, Any] = {
        "clip": ["128", 0],
        "vae": ["119", 0],
        "previous_latent": ["200", 0],
        "handover": ["200", 3],
        "prompt": prompt,
        "width": ["115", 0],
        "height": ["115", 1],
        "duration": total_duration,
        "masked_context_frames": "39",
        "audio_feather_ticks": audio_feather_ticks,
        "ref_image_size": "match",
        "duration_mode": "Total Generation",
        "audio_tail_carryover": audio_tail_carryover,
    }
    if generation_mode == "fl2va":
        _remove_condition_reference_loaders(workflow)
        workflow.pop("136", None)
        workflow["127"]["inputs"]["unet_name"] = FL2VA_MODEL
        if references:
            workflow["205"] = _load_image_node(references[0])
            continue_inputs["last_frame"] = ["205", 0]
        for index, reference in enumerate(references[1:], start=1):
            node_id = str(205 + index)
            workflow[node_id] = _load_image_node(reference)
            continue_inputs[f"qwen_reference_{index}"] = [node_id, 0]
    workflow["201"] = {"class_type": "H3ContinuousContinueV14", "inputs": continue_inputs}
    workflow["125"]["inputs"]["latent_image"] = ["201", 1]
    workflow["126"]["inputs"]["conditioning"] = ["201", 0] if generation_mode == "fl2va" else ["136", 0]


def build_shot_workflow(
    template: dict[str, Any],
    reference_names: list[str],
    prompt: str,
    duration: float,
    seed: int,
    output_prefix: str,
    resolution: str = "480p",
    aspect_ratio: str = "16:9",
    generation_mode: str = "r2va",
    continue_from_previous: bool = False,
    previous_output_name: str = "",
    will_be_continued: bool = False,
    save_latent: bool = False,
    turbo_lora_enabled: bool = True,
    sage_attention_enabled: bool = True,
    sampling_steps: int | None = None,
    audio_tail_carryover: str = "Full Previous Tail",
    audio_feather_ticks: int = 0,
) -> dict[str, Any]:
    if generation_mode not in {"r2va", "fl2va"}:
        raise ValueError(f"不支持的生成模式: {generation_mode}")
    if continue_from_previous and not previous_output_name.strip():
        raise ValueError("延续镜头必须指定上一镜输出名称")
    if generation_mode == "fl2va" and not continue_from_previous and len(reference_names) < 2:
        raise ValueError("FL2VA首段必须依次提供首帧和尾帧")

    result = build_workflow(
        template, reference_names, prompt, duration, seed, output_prefix,
        resolution=resolution, aspect_ratio=aspect_ratio,
    )
    result["127"]["inputs"]["unet_name"] = R2VA_MODEL if generation_mode == "r2va" else FL2VA_MODEL
    _configure_acceleration(result, turbo_lora_enabled, sage_attention_enabled, sampling_steps)
    if generation_mode == "fl2va" and not continue_from_previous:
        _configure_fl2va_start(result, reference_names)
        result["125"]["inputs"]["latent_image"] = ["136", 1]
        result["126"]["inputs"]["conditioning"] = ["136", 0]
    if continue_from_previous:
        _configure_continuation(
            result, prompt, duration, previous_output_name, generation_mode, reference_names,
            audio_tail_carryover=audio_tail_carryover,
            audio_feather_ticks=audio_feather_ticks,
        )
    _add_latent_outputs(
        result, output_prefix.rsplit("/", 1)[-1], continue_from_previous,
        will_be_continued, save_latent,
    )
    return result
