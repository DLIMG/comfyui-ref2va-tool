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
TURBO_8STEP_LORA = "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
# UntMods/FaceSwap_MiniMaxH3_REF2VA：把参考视频里的身份脸换成参考图的脸。
# 官方说明为「单一触发词 + 强度 1.0」，因此只在提示词里补一次触发词。
FACE_SWAP_LORA = "SS_FaceSwap_MiniMax_H3_REF2VA.safetensors"
FACE_SWAP_TRIGGER = "Faceswap"
FACE_SWAP_NODE_ID = "155"
FACE_SWAP_STRENGTH = 1.0
R2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
FL2VA_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
H3_VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
# --- ComfyUI 0.36 原生节点 ---------------------------------------------------
# ConcatenateVideo 取代手工 ffmpeg 串片；Generic Loops 让故事板批量队列在单张图里跑完。
CONCATENATE_VIDEO_NODE = "ConcatenateVideo"
VIDEO_CONCAT_CODECS = ("auto", "h264", "av1")
MAX_CONCATENATE_SEGMENTS = 100
GENERIC_LOOP_START_NODE = "StartLoop"
GENERIC_LOOP_END_NODE = "EndLoop"
# ⚠️ StartLoop 的 ``mode.list`` 走的是 MATCHTYPE，校验器把「任意两元素列表」都当节点连线
# ``[node_id, slot]`` 解析，直接塞裸字符串列表会在 prompt 校验时抛 KeyError。所以必须用
# CreateList 节点产出真正的 LIST，再把它的输出接进去。
CREATE_LIST_NODE = "CreateList"
LOOP_CREATE_LIST_ID = "890"
# CreateList 的 autogrow 前缀是 "input"，官方上限 10 个入口。
CREATE_LIST_PREFIX = "inputs.input"
MAX_LOOP_PROMPTS = 10
LOOP_START_ID = "900"
LOOP_SEED_ID = "901"
LOOP_END_ID = "910"
LOOP_SHOT_SAVE_ID = "911"
LOOP_CONCAT_ID = "912"
LOOP_FILM_SAVE_ID = "913"
# StartLoop 的 list_item 输出槽位（iteration_index, is_first, is_last, list_item, carried）
LOOP_LIST_ITEM_SLOT = 3

MASKED_CONTEXT_FRAMES = 39
BASE_MODEL_STEPS = 15
H3_LATENT_UPSCALER_MODEL = "minimax_h3_latent_upscaler_3d_fp16.safetensors"
REFINE_SIGMAS = "0.9035, 0.8000, 0.6316, 0.3158, 0.0000"
ADAPTIVE_LOW_VRAM_NODE = "MiniMaxH3AdaptiveLowVRAM"
ADAPTIVE_LOW_VRAM_ID = "160"
REFERENCE_IMAGE_SIZES = ("match", "max")


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
        "119": "VAELoader",
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

    if workflow["119"]["inputs"].get("vae_name") != H3_VIDEO_VAE:
        raise ValueError("视频 VAE 必须使用官方 minimax_h3_video_vae_int8_convrot.safetensors")

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
    reference_image_size: str = "match",
) -> dict[str, Any]:
    validate_template(template)
    if not reference_names:
        raise ValueError("至少需要一张参考图")
    if resolution not in RESOLUTION_MAP:
        raise ValueError(f"不支持的清晰度: {resolution}")
    if aspect_ratio not in ASPECT_RATIO_MAP:
        raise ValueError(f"不支持的画幅: {aspect_ratio}")
    if reference_image_size not in REFERENCE_IMAGE_SIZES:
        raise ValueError("参考图尺寸策略仅支持 match 或 max")
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
    condition_inputs["ref_image_size"] = reference_image_size

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


def _configure_r2va_videos(workflow: dict[str, Any], video_names: list[str]) -> None:
    """Attach decoded 24 fps video frames and matching audio to Ref2VA conditioning."""
    if not video_names:
        return
    next_id = max(int(node_id) for node_id in workflow if str(node_id).isdigit()) + 1
    condition_inputs = workflow["136"]["inputs"]
    for index, video_name in enumerate(video_names):
        load_id = str(next_id + index * 2)
        components_id = str(next_id + index * 2 + 1)
        workflow[load_id] = {"class_type": "LoadVideo", "inputs": {"file": video_name}}
        workflow[components_id] = {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [load_id, 0]},
        }
        condition_inputs[f"ref_videos.ref_video_{index}"] = [components_id, 0]
        condition_inputs[f"ref_video_audios.ref_video_audio_{index}"] = [components_id, 1]


def _configure_r2va_audios(workflow: dict[str, Any], audio_names: list[str], start_index: int = 0) -> None:
    """Attach audio-only references without constructing video tensors."""
    if not audio_names:
        return
    next_id = max(int(node_id) for node_id in workflow if str(node_id).isdigit()) + 1
    condition_inputs = workflow["136"]["inputs"]
    for offset, audio_name in enumerate(audio_names):
        node_id = str(next_id + offset)
        workflow[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        condition_inputs[f"ref_video_audios.ref_video_audio_{start_index + offset}"] = [node_id, 0]


def _free_node_id(workflow: dict[str, Any], preferred: str) -> str:
    """返回 preferred 起第一个未被占用的数字节点 ID。

    参考图 LoadImage 由 `build_workflow` 从「模板最大 ID + 1」起自动编号，因此任何写死的
    节点 ID（155 / 160）都可能与第 N 张参考图撞号，覆盖或误删参考图接线。
    """
    used = {int(key) for key in workflow if str(key).isdigit()}
    candidate = int(preferred)
    while candidate in used:
        candidate += 1
    return str(candidate)


def _configure_acceleration(
    workflow: dict[str, Any],
    turbo_lora_enabled: bool,
    sage_attention_enabled: bool,
    sampling_steps: int | None,
    adaptive_low_vram_enabled: bool = False,
    face_swap_enabled: bool = False,
) -> None:
    sampling_steps = sampling_steps if sampling_steps is not None else (8 if turbo_lora_enabled else BASE_MODEL_STEPS)
    if not 1 <= sampling_steps <= 100:
        raise ValueError("采样步数必须在 1 到 100 之间")
    model_source = ["127", 0]
    if turbo_lora_enabled:
        model_source = ["150", 0]
    else:
        workflow.pop("150", None)

    # FaceSwap 叠在 Turbo 之后、SageAttention 之前，保持与模板一致的
    # 「UNETLoader → LoRA(链) → 注意力补丁 → 采样器」接线次序。
    face_swap_id = _free_node_id(workflow, FACE_SWAP_NODE_ID)
    if face_swap_enabled:
        workflow[face_swap_id] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": model_source,
                "lora_name": FACE_SWAP_LORA,
                "strength_model": FACE_SWAP_STRENGTH,
            },
        }
        model_source = [face_swap_id, 0]
    else:
        # 只移除「确实是 FaceSwap LoRA」的节点，绝不按 ID 盲删（该 ID 可能是参考图）。
        existing = workflow.get(face_swap_id)
        if isinstance(existing, dict) and existing.get("inputs", {}).get("lora_name") == FACE_SWAP_LORA:
            workflow.pop(face_swap_id, None)

    if adaptive_low_vram_enabled:
        low_vram_id = _free_node_id(workflow, ADAPTIVE_LOW_VRAM_ID)
        workflow[low_vram_id] = {
            "class_type": ADAPTIVE_LOW_VRAM_NODE,
            "inputs": {
                "model": model_source,
                "enabled": True,
                "minimum_chunk_tokens": 2048,
                "maximum_chunk_tokens": 32768,
                "activation_budget_percent": 4.0,
                "free_memory_fraction": 0.5,
                "block_prefetch": "keep",
                "verbose": True,
            },
        }
        model_source = [low_vram_id, 0]

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


def _assert_reference_wiring(workflow: dict[str, Any]) -> None:
    """提交前自检：每张参考图槽位都必须指向一个真实存在的 LoadImage 节点。

    ComfyUI 对这类断线只回一句 `prompt_outputs_failed_validation`，看不出是哪张图，
    所以在这里提前拦下并指名道姓。
    """
    condition = workflow.get("136", {}).get("inputs")
    if not isinstance(condition, dict):
        return
    broken: list[str] = []
    for key, value in condition.items():
        if not key.startswith("ref_images.ref_image_"):
            continue
        if not (isinstance(value, list) and len(value) == 2):
            broken.append(f"{key} 接线格式异常")
            continue
        node = workflow.get(str(value[0]))
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            broken.append(f"{key} → 节点 {value[0]} 不存在或不是 LoadImage")
    if broken:
        raise ValueError("参考图接线不完整，已阻止提交以免生成失败：" + "；".join(broken))


def _configure_fl2va_start(
    workflow: dict[str, Any], references: list[str], reference_image_size: str,
) -> None:
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
        "ref_image_size": reference_image_size,
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
    reference_image_size: str = "match",
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
        "ref_image_size": reference_image_size,
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
    reference_video_names: list[str] | None = None,
    reference_audio_names: list[str] | None = None,
    adaptive_low_vram_enabled: bool = False,
    face_swap_enabled: bool = False,
    reference_image_size: str = "match",
) -> dict[str, Any]:
    reference_video_names = reference_video_names or []
    reference_audio_names = reference_audio_names or []
    if generation_mode not in {"r2va", "fl2va"}:
        raise ValueError(f"不支持的生成模式: {generation_mode}")
    if continue_from_previous and not previous_output_name.strip():
        raise ValueError("延续镜头必须指定上一镜输出名称")
    if generation_mode == "fl2va" and not continue_from_previous and len(reference_names) < 2:
        raise ValueError("FL2VA首段必须依次提供首帧和尾帧")
    if generation_mode != "r2va" and reference_video_names:
        raise ValueError("参考视频当前仅支持R2VA模式")
    if generation_mode != "r2va" and reference_audio_names:
        raise ValueError("参考音频当前仅支持R2VA模式")
    if face_swap_enabled and generation_mode != "r2va":
        raise ValueError("FaceSwap LoRA 只能在 R2VA 模式下使用")
    if len(reference_video_names) > 3:
        raise ValueError("参考视频最多3段")
    if reference_image_size not in REFERENCE_IMAGE_SIZES:
        raise ValueError("参考图尺寸策略仅支持 match 或 max")

    result = build_workflow(
        template, reference_names, prompt, duration, seed, output_prefix,
        resolution=resolution, aspect_ratio=aspect_ratio,
        reference_image_size=reference_image_size,
    )
    result["127"]["inputs"]["unet_name"] = R2VA_MODEL if generation_mode == "r2va" else FL2VA_MODEL
    _configure_acceleration(
        result, turbo_lora_enabled, sage_attention_enabled, sampling_steps,
        adaptive_low_vram_enabled=adaptive_low_vram_enabled,
        face_swap_enabled=face_swap_enabled,
    )
    if face_swap_enabled:
        # LoRA 自带单一触发词，提示词里出现一次即可，避免重复加权。
        current = str(result["138"]["inputs"].get("value") or "")
        if FACE_SWAP_TRIGGER.lower() not in current.lower():
            result["138"]["inputs"]["value"] = f"{FACE_SWAP_TRIGGER} {current}".strip()
    if generation_mode == "r2va":
        _configure_r2va_videos(result, reference_video_names)
        _configure_r2va_audios(result, reference_audio_names, len(reference_video_names))
    if generation_mode == "fl2va" and not continue_from_previous:
        _configure_fl2va_start(result, reference_names, reference_image_size)
        result["125"]["inputs"]["latent_image"] = ["136", 1]
        result["126"]["inputs"]["conditioning"] = ["136", 0]
    if continue_from_previous:
        _configure_continuation(
            result, prompt, duration, previous_output_name, generation_mode, reference_names,
            reference_image_size=reference_image_size,
            audio_tail_carryover=audio_tail_carryover,
            audio_feather_ticks=audio_feather_ticks,
        )
    _add_latent_outputs(
        result, output_prefix.rsplit("/", 1)[-1], continue_from_previous,
        will_be_continued, save_latent,
    )
    _assert_reference_wiring(result)
    return result


def build_refine_workflow(
    template: dict[str, Any], reference_names: list[str], prompt: str, duration: float,
    seed: int, output_prefix: str, source_latent_name: str,
    target_resolution: str = "0.9mp", aspect_ratio: str = "16:9",
    generation_mode: str = "r2va", reference_video_names: list[str] | None = None,
    turbo_lora_enabled: bool = True, sage_attention_enabled: bool = True,
    sampling_steps: int | None = None, source_context_frames: int = 0,
    will_be_continued: bool = False,
    reference_image_size: str = "match",
    adaptive_low_vram_enabled: bool = True,
    split_tiling: bool = False,
) -> dict[str, Any]:
    """Build a true H3 latent upscale + low-noise resampling pass.

    The source is a saved joint AV latent.  Only its video component is enlarged;
    the original audio latent is joined back before the H3 refinement sample.

    默认 **整张直出（不分块）**：二采的 latent 放大倍率通常接近 1，时空瓦片带来的
    重叠重复计算 + 每块重装 ~20GB 模型纯属浪费。显存由 ``MiniMaxH3AdaptiveLowVRAM``
    在 token 维度做线性流式切分兜底（无重叠、无重复劳动）—— 一采走的就是这条路。
    只有需要 2.5–5 倍真放大、单块仍超显存时，才传 ``split_tiling=True`` 换回时空瓦片。
    """
    workflow = build_shot_workflow(
        template, reference_names, prompt, duration + source_context_frames / 24.0, seed, output_prefix,
        resolution=target_resolution, aspect_ratio=aspect_ratio,
        generation_mode=generation_mode, save_latent=False,
        turbo_lora_enabled=turbo_lora_enabled,
        sage_attention_enabled=sage_attention_enabled,
        sampling_steps=sampling_steps,
        reference_video_names=reference_video_names or [],
        reference_image_size=reference_image_size,
        adaptive_low_vram_enabled=adaptive_low_vram_enabled,
    )
    workflow["300"] = {
        "class_type": "H3ContinuousLoadLatent",
        "inputs": {
            "latent_path": f"codex_ref2va_tool/latents/{source_latent_name}_00001.safetensors",
            "clip_index": 1,
        },
    }
    workflow["301"] = {
        "class_type": "LTXVSeparateAVLatent",
        "inputs": {"av_latent": ["300", 0]},
    }
    workflow["302"] = {
        "class_type": "MinimaxH3LatentUpscaler3D",
        "inputs": {
            "latent": ["301", 0],
            "model_name": H3_LATENT_UPSCALER_MODEL,
            # ComfyUI DynamicCombo V3 API fields are flattened.  Supplying a
            # nested object makes the executor drop ``mode`` entirely.
            "mode": "megapixels",
            "mode.megapixels": RESOLUTION_MAP[target_resolution],
            "align": 32,
            "enable_temporal_chunking": True,
            "force_unload": True,
            "device": "cuda",
            "precision": "fp16",
        },
    }
    workflow["303"] = {
        "class_type": "LTXVConcatAVLatent",
        "inputs": {"video_latent": ["302", 0], "audio_latent": ["301", 1]},
    }
    workflow["304"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": REFINE_SIGMAS}}
    resample_inputs: dict[str, Any] = {
        "model": workflow["126"]["inputs"]["model"],
        "conditioning": workflow["126"]["inputs"]["conditioning"],
        "latent": ["303", 0],
        "noise": ["129", 0],
        "sampler": ["123", 0],
        "sigmas": ["304", 0],
        "cfg": 1.0,
        # 不分块就没有接缝，seam polish 无对象可打磨。
        "seam_polish": "auto" if split_tiling else "off",
        "color_match": True,
    }
    if split_tiling:
        # 时空瓦片：显存只跟单块大小挂钩，与整片分辨率解耦，但重叠区重复计算。
        temporal_id = _free_node_id(workflow, "305")
        spatial_id = _free_node_id(workflow, "306")
        workflow[temporal_id] = {
            "class_type": "MMH3TemporalSplitParamsV10",
            "inputs": {
                "chunk_frames": 73,
                "temporal_overlap_frames": 22,
                "anchor_strength": 0.999,
                "motion_anchor_frames": "22",
                "identity_anchor_frames": 24,
            },
        }
        workflow[spatial_id] = {
            "class_type": "MMH3SpatialSplitParamsV10",
            "inputs": {
                "tile_width": 512,
                "tile_height": 512,
                "overlap_ratio": 0.25,
                "fade_ratio": 0.50,
                "min_tile_size": 256,
                "seam_denoise": 0.65,
            },
        }
        resample_inputs["temporal_split_param"] = [temporal_id, 0]
        resample_inputs["spatial_split_param"] = [spatial_id, 0]
    workflow["307"] = {
        "class_type": "MMH3SplitUpscale",
        "inputs": resample_inputs,
    }
    workflow["122"]["inputs"]["samples"] = ["307", 0]
    workflow["121"]["inputs"]["samples"] = ["307", 0]
    if source_context_frames or will_be_continued:
        workflow["309"] = {
            "class_type": "H3ContinuousStitchOutputV14",
            "inputs": {
                "images": ["122", 0], "audio": ["121", 0],
                "output_mode": "Stitch Ready" if will_be_continued else "Final Clip",
                "handover": ["300", 3],
                "head_context_frames": int(source_context_frames),
            },
        }
        workflow["130"]["inputs"]["images"] = ["309", 0]
        workflow["130"]["inputs"]["audio"] = ["309", 1]
    refined_name = output_prefix.rsplit("/", 1)[-1]
    workflow["308"] = {
        "class_type": "H3ContinuousSaveLatent",
        "inputs": {
            "latent": ["307", 0],
            "filename_prefix": f"codex_ref2va_tool/latents/{refined_name}",
            "clip_index": 1,
            "handover": ["300", 3],
            "head_context_frames": int(source_context_frames),
        },
    }
    return workflow


def build_concatenate_workflow(
    video_names: list[str],
    output_prefix: str,
    codec: str = "auto",
) -> dict[str, Any]:
    """把已生成的多个镜头用 ComfyUI 0.36 原生 ConcatenateVideo 节点首尾拼成整片。

    这条链路完全走 ComfyUI 原生节点，不再依赖外部 ffmpeg；``auto`` 编码会直接
    复制兼容的已编码码流（不重新解码），所以多镜头串片的开销只有容器封装。
    """
    if not video_names:
        raise ValueError("至少需要一段视频才能串接")
    if len(video_names) > MAX_CONCATENATE_SEGMENTS:
        raise ValueError(f"最多串接 {MAX_CONCATENATE_SEGMENTS} 段视频")
    if codec not in VIDEO_CONCAT_CODECS:
        raise ValueError(f"不支持的串片编码: {codec}")

    workflow: dict[str, Any] = {}
    concat_inputs: dict[str, Any] = {"codec": codec}
    for index, name in enumerate(video_names):
        node_id = str(400 + index)
        workflow[node_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        # ConcatenateVideo 的 autogrow 前缀是 "video"（无下划线），与
        # MiniMaxH3ReferenceToVideo 的 "ref_image_N" 命名不同。
        concat_inputs[f"videos.video{index}"] = [node_id, 0]

    concat_id = str(400 + len(video_names))
    workflow[concat_id] = {"class_type": CONCATENATE_VIDEO_NODE, "inputs": concat_inputs}
    workflow[str(int(concat_id) + 1)] = {
        "class_type": "SaveVideo",
        "inputs": {
            "filename_prefix": output_prefix.replace("\\", "/"),
            "format": "auto",
            "codec": "auto",
            "video": [concat_id, 0],
        },
    }
    return workflow


def build_batch_loop_workflow(
    template: dict[str, Any],
    reference_names: list[str],
    prompts: list[str],
    duration: float,
    seed: int,
    output_prefix: str,
    resolution: str = "480p",
    aspect_ratio: str = "16:9",
    generation_mode: str = "r2va",
    turbo_lora_enabled: bool = True,
    sage_attention_enabled: bool = True,
    sampling_steps: int | None = None,
    adaptive_low_vram_enabled: bool = False,
    reference_video_names: list[str] | None = None,
    reference_audio_names: list[str] | None = None,
    stitch_output: bool = False,
    face_swap_enabled: bool = False,
) -> dict[str, Any]:
    """用 ComfyUI 0.36 的 Generic Loops 节点把一整条故事板压进单张 ComfyUI 图。

    共享同一组参考素材（R2VA 9 图 / 参考视频 / 参考音频），逐条走 ``prompts``：
    每轮迭代把 ``StartLoop.list_item`` 接到提示词节点 138，按镜头序号改随机种子。

    ⚠️ ComfyUI 把「循环体内可达、且没有下游消费者的输出节点」判定为 loop escape
    （``Loop body is not closed``），所以循环体内不能留 SaveVideo。这里的做法是让
    ``EndLoop`` 用 ``accumulate`` 把每轮的 CreateVideo 收成列表，落盘放在循环之后：
    列表喂给 SaveVideo 会按元素展开成逐镜文件，喂给 ConcatenateVideo 就是整片。

    ⚠️ ``mode.list`` 必须接 CreateList 节点的输出，不能直接写提示词字面量——校验器会把
    两元素列表误判成节点连线。
    """
    prompts = [str(item) for item in prompts]
    if not prompts:
        raise ValueError("批量循环至少需要一条提示词")
    if len(prompts) > MAX_LOOP_PROMPTS:
        raise ValueError(f"单张循环图最多 {MAX_LOOP_PROMPTS} 个镜头（CreateList 上限）")
    if any(not item.strip() for item in prompts):
        raise ValueError("批量循环的提示词不能为空")
    if face_swap_enabled:
        # 循环里提示词来自 StartLoop.list_item，触发词必须写进列表本身，
        # 否则会被后面的 list_item 接线覆盖掉。
        prompts = [
            item if FACE_SWAP_TRIGGER.lower() in item.lower() else f"{FACE_SWAP_TRIGGER} {item}"
            for item in prompts
        ]

    workflow = build_shot_workflow(
        template,
        reference_names,
        prompts[0],
        duration,
        seed,
        output_prefix,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generation_mode=generation_mode,
        turbo_lora_enabled=turbo_lora_enabled,
        sage_attention_enabled=sage_attention_enabled,
        sampling_steps=sampling_steps,
        adaptive_low_vram_enabled=adaptive_low_vram_enabled,
        reference_video_names=reference_video_names or [],
        reference_audio_names=reference_audio_names or [],
        face_swap_enabled=face_swap_enabled,
    )

    # 循环体必须闭合：把模板自带的 SaveVideo(92) 挪到 EndLoop 之后。
    workflow.pop("92", None)

    # 种子按镜头序号递增，避免整批素材抽到同一张脸/同一段运动。
    # ComfyMathExpression 的输出槽位是 FLOAT/INT/BOOLEAN，种子必须取 1 号 INT 槽。
    workflow["129"]["inputs"]["noise_seed"] = [LOOP_SEED_ID, 1]
    # CreateList 先把提示词收成真正的 LIST，StartLoop 再去迭代它。
    workflow[LOOP_CREATE_LIST_ID] = {
        "class_type": CREATE_LIST_NODE,
        "inputs": {
            f"{CREATE_LIST_PREFIX}{index}": item for index, item in enumerate(prompts)
        },
    }
    workflow[LOOP_START_ID] = {
        "class_type": GENERIC_LOOP_START_NODE,
        "inputs": {
            "mode": "List",
            "mode.list": [LOOP_CREATE_LIST_ID, 0],
            "cache_iterations": False,
        },
    }
    workflow[LOOP_SEED_ID] = {
        "class_type": "ComfyMathExpression",
        "inputs": {"expression": f"{int(seed)} + a", "values.a": [LOOP_START_ID, 0]},
    }
    workflow["138"]["inputs"]["value"] = [LOOP_START_ID, LOOP_LIST_ITEM_SLOT]

    # accumulate 让 EndLoop 返回每一轮的 VIDEO 列表，而不是只有最后一轮。
    workflow[LOOP_END_ID] = {
        "class_type": GENERIC_LOOP_END_NODE,
        "inputs": {"accumulate": True, "output_value": ["130", 0]},
    }
    # 列表输入会被 ComfyUI 按元素映射，于是逐镜落盘。
    workflow[LOOP_SHOT_SAVE_ID] = {
        "class_type": "SaveVideo",
        "inputs": {
            "filename_prefix": output_prefix.replace("\\", "/"),
            "format": "auto",
            "codec": "auto",
            "video": [LOOP_END_ID, 0],
        },
    }
    if stitch_output:
        workflow[LOOP_CONCAT_ID] = {
            "class_type": CONCATENATE_VIDEO_NODE,
            "inputs": {"videos.video0": [LOOP_END_ID, 0], "codec": "auto"},
        }
        workflow[LOOP_FILM_SAVE_ID] = {
            "class_type": "SaveVideo",
            "inputs": {
                "filename_prefix": f"{output_prefix}_full_cut".replace("\\", "/"),
                "format": "auto",
                "codec": "auto",
                "video": [LOOP_CONCAT_ID, 0],
            },
        }
    return workflow
