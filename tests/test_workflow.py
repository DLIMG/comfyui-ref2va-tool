import copy
import json
from pathlib import Path

import pytest

from app.workflow import (
    build_batch_loop_workflow,
    build_concatenate_workflow,
    build_refine_workflow,
    build_shot_workflow,
    build_workflow,
    load_template,
    validate_template,
)


TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "minimax_h3_turbo_8step_ref2va_api.json"


def test_build_refine_workflow_uses_h3_av_latent_upscale_and_low_noise_sample():
    result = build_refine_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7,
        "codex_ref2va_tool/shot_p2", "shot", target_resolution="0.9mp",
    )
    assert result["300"]["class_type"] == "H3ContinuousLoadLatent"
    assert result["301"]["class_type"] == "LTXVSeparateAVLatent"
    assert result["302"]["class_type"] == "MinimaxH3LatentUpscaler3D"
    assert result["302"]["inputs"]["mode"] == "megapixels"
    assert result["302"]["inputs"]["mode.megapixels"] == .9
    assert result["303"]["class_type"] == "LTXVConcatAVLatent"
    assert result["304"]["class_type"] == "ManualSigmas"
    assert result["305"]["class_type"] == "MMH3TemporalSplitParamsV10"
    assert result["305"]["inputs"]["chunk_frames"] == 73
    assert result["306"]["class_type"] == "MMH3SpatialSplitParamsV10"
    assert result["306"]["inputs"]["tile_width"] == 512
    assert result["307"]["class_type"] == "MMH3SplitUpscale"
    assert result["307"]["inputs"]["latent"] == ["303", 0]
    assert result["307"]["inputs"]["temporal_split_param"] == ["305", 0]
    assert result["307"]["inputs"]["spatial_split_param"] == ["306", 0]
    assert result["122"]["inputs"]["samples"] == ["307", 0]
    assert result["121"]["inputs"]["samples"] == ["307", 0]


def test_refine_continuation_stitches_with_literal_integer_context_count():
    result = build_refine_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7,
        "codex_ref2va_tool/shot_p2", "shot", target_resolution="0.4mp",
        source_context_frames=39,
    )
    assert result["309"]["inputs"]["head_context_frames"] == 39


def test_refine_intermediate_clip_reuses_handover_for_exact_head_and_tail_trim():
    result = build_refine_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7,
        "codex_ref2va_tool/shot_p2", "shot", target_resolution="0.4mp",
        source_context_frames=39, will_be_continued=True,
    )
    assert result["309"]["inputs"]["output_mode"] == "Stitch Ready"
    assert result["309"]["inputs"]["handover"] == ["300", 3]
    assert result["308"]["inputs"]["handover"] == ["300", 3]
    assert result["308"]["inputs"]["head_context_frames"] == 39


def test_load_and_validate_real_template():
    workflow = load_template(TEMPLATE)
    validate_template(workflow)
    assert workflow["119"]["inputs"]["vae_name"] == "minimax_h3_video_vae_int8_convrot.safetensors"
    assert workflow["136"]["class_type"] == "MiniMaxH3ReferenceToVideo"


def test_template_uses_only_the_active_turbo_8step_model_chain():
    workflow = load_template(TEMPLATE)

    assert workflow["127"]["class_type"] == "UNETLoader"
    assert workflow["150"] == {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": ["127", 0],
            "lora_name": "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors",
            "strength_model": 1.0,
        },
    }
    assert workflow["142"] == {
        "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "inputs": {"model": ["150", 0]},
    }
    assert workflow["124"]["inputs"]["model"] == ["142", 0]
    assert workflow["126"]["inputs"]["model"] == ["142", 0]
    assert workflow["124"]["inputs"]["scheduler"] == "simple"
    assert workflow["124"]["inputs"]["steps"] == 8
    assert workflow["123"]["inputs"]["sampler_name"] == "res_multistep"
    assert "141" not in workflow  # disabled TeaCache
    assert "152" not in workflow  # disabled 4-step LoRA
    assert "TeaCache" not in workflow["92"]["inputs"]["filename_prefix"]


def test_adaptive_low_vram_is_inserted_before_attention_only_when_enabled():
    template = load_template(TEMPLATE)

    disabled = build_shot_workflow(
        template, ["one.png"], "prompt", 5, 7, "project/off",
        adaptive_low_vram_enabled=False,
    )
    assert "160" not in disabled
    assert disabled["142"]["inputs"]["model"] == ["150", 0]

    enabled = build_shot_workflow(
        template, ["one.png"], "prompt", 7, 7, "project/auto",
        adaptive_low_vram_enabled=True,
    )
    assert enabled["160"]["class_type"] == "MiniMaxH3AdaptiveLowVRAM"
    assert enabled["160"]["inputs"]["model"] == ["150", 0]
    assert enabled["160"]["inputs"]["activation_budget_percent"] == 4.0
    assert enabled["142"]["inputs"]["model"] == ["160", 0]
    assert enabled["124"]["inputs"]["model"] == ["142", 0]
    assert enabled["126"]["inputs"]["model"] == ["142", 0]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda workflow: workflow["150"]["inputs"].update(model=["999", 0]), "8-step LoRA"),
        (lambda workflow: workflow["150"]["inputs"].update(lora_name="wrong.safetensors"), "8-step LoRA"),
        (lambda workflow: workflow["142"]["inputs"].update(model=["127", 0]), "SageAttention"),
        (lambda workflow: workflow["124"]["inputs"].update(model=["150", 0]), "BasicScheduler"),
        (lambda workflow: workflow["126"]["inputs"].update(model=["150", 0]), "BasicGuider"),
        (lambda workflow: workflow["124"]["inputs"].update(scheduler="normal"), "simple"),
        (lambda workflow: workflow["124"]["inputs"].update(steps=20), "8"),
        (lambda workflow: workflow["123"]["inputs"].update(sampler_name="euler"), "res_multistep"),
        (
            lambda workflow: workflow.update(
                {"999": {"class_type": "MiniMaxH3TeaCache", "inputs": {"model": ["142", 0]}}}
            ),
            "TeaCache",
        ),
        (
            lambda workflow: workflow.update(
                {"999": {"class_type": "LoraLoaderModelOnly", "inputs": {
                    "model": ["127", 0],
                    "lora_name": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
                    "strength_model": 1.0,
                }}}
            ),
            "4-step",
        ),
    ],
)
def test_validate_template_rejects_broken_turbo_execution_state(mutation, message):
    workflow = load_template(TEMPLATE)
    mutation(workflow)

    with pytest.raises(ValueError, match=message):
        validate_template(workflow)


@pytest.mark.parametrize("count", [1, 4, 6])
def test_build_workflow_supports_arbitrary_reference_count(count):
    template = load_template(TEMPLATE)
    original_model = copy.deepcopy(template["127"])
    original_sampler = copy.deepcopy(template["123"])
    refs = [f"shot/ref_{i}.png" for i in range(count)]

    result = build_workflow(template, refs, "六段提示词", 8.0, 12345, "project/shot_01")

    condition_inputs = result["136"]["inputs"]
    ref_keys = sorted(k for k in condition_inputs if k.startswith("ref_images.ref_image_"))
    assert ref_keys == [f"ref_images.ref_image_{i}" for i in range(count)]
    load_nodes = [node for node in result.values() if node.get("class_type") == "LoadImage"]
    assert sorted(node["inputs"]["image"] for node in load_nodes) == sorted(refs)
    for index, reference_name in enumerate(refs):
        load_node_id, output_index = condition_inputs[f"ref_images.ref_image_{index}"]
        assert output_index == 0
        assert result[load_node_id]["class_type"] == "LoadImage"
        assert result[load_node_id]["inputs"]["image"] == reference_name
    assert result["138"]["inputs"]["value"] == "六段提示词"
    assert result["132"]["inputs"]["value"] == 8.0
    assert result["129"]["inputs"]["noise_seed"] == 12345
    assert result["92"]["inputs"]["filename_prefix"] == "project/shot_01"
    assert result["127"] == original_model
    assert result["123"] == original_sampler


def test_r2va_attaches_reference_video_frames_and_matching_audio():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["cat.png"], "<Picture 1>替换<Video 1>中的人物", 15, 123,
        "project/cat_video", reference_video_names=["source.mp4"],
    )

    inputs = result["136"]["inputs"]
    frame_node = inputs["ref_videos.ref_video_0"][0]
    audio_node = inputs["ref_video_audios.ref_video_audio_0"][0]
    assert frame_node == audio_node
    assert result[frame_node]["class_type"] == "GetVideoComponents"
    load_node = result[frame_node]["inputs"]["video"][0]
    assert result[load_node] == {"class_type": "LoadVideo", "inputs": {"file": "source.mp4"}}
    assert inputs["ref_videos.ref_video_0"][1] == 0
    assert inputs["ref_video_audios.ref_video_audio_0"][1] == 1


def test_r2va_attaches_audio_only_reference_without_video_decoder():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["person.png"], "<Audio 1> guides the voice", 5, 123,
        "project/voice", reference_audio_names=["voice.wav"],
    )

    inputs = result["136"]["inputs"]
    audio_node = inputs["ref_video_audios.ref_video_audio_0"][0]
    assert result[audio_node] == {"class_type": "LoadAudio", "inputs": {"audio": "voice.wav"}}
    assert not any(node.get("class_type") in {"LoadVideo", "GetVideoComponents"} for node in result.values())


def test_r2va_numbers_audio_only_references_after_video_audio():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["person.png"], "prompt", 5, 123, "project/mixed",
        reference_video_names=["motion.mp4"], reference_audio_names=["voice.wav"],
    )

    inputs = result["136"]["inputs"]
    assert "ref_video_audios.ref_video_audio_0" in inputs
    audio_node = inputs["ref_video_audios.ref_video_audio_1"][0]
    assert result[audio_node]["class_type"] == "LoadAudio"


def test_build_does_not_mutate_template():
    template = load_template(TEMPLATE)
    before = json.dumps(template, ensure_ascii=False, sort_keys=True)
    build_workflow(template, ["one.png"], "prompt", 6, 7, "out")
    assert json.dumps(template, ensure_ascii=False, sort_keys=True) == before


def test_build_preserves_load_images_not_referenced_by_condition_node():
    template = load_template(TEMPLATE)
    template["999"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "independent.png"},
    }

    result = build_workflow(template, ["replacement.png"], "prompt", 6, 7, "out")

    assert result["999"] == template["999"]


def test_build_sets_resolution_and_portrait_aspect_ratio():
    template = load_template(TEMPLATE)

    result = build_workflow(
        template,
        ["one.png"],
        "prompt",
        6,
        7,
        "out",
        resolution="720p",
        aspect_ratio="9:16",
    )

    assert result["115"]["inputs"]["megapixels"] == 0.9
    assert result["115"]["inputs"]["aspect_ratio"] == "9:16 (Portrait Widescreen)"


@pytest.mark.parametrize(
    ("turbo_enabled", "sage_enabled", "expected_model", "expected_steps"),
    [
        (True, True, ["142", 0], 8),
        (True, False, ["150", 0], 8),
        (False, True, ["142", 0], 15),
        (False, False, ["127", 0], 15),
    ],
)
def test_build_configures_global_acceleration_chain(
    turbo_enabled, sage_enabled, expected_model, expected_steps
):
    result = build_shot_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7, "out",
        turbo_lora_enabled=turbo_enabled,
        sage_attention_enabled=sage_enabled,
    )

    assert ("150" in result) is turbo_enabled
    assert ("142" in result) is sage_enabled
    if sage_enabled:
        assert result["142"]["inputs"]["model"] == (["150", 0] if turbo_enabled else ["127", 0])
    assert result["124"]["inputs"]["model"] == expected_model
    assert result["126"]["inputs"]["model"] == expected_model
    assert result["124"]["inputs"]["steps"] == expected_steps


def test_global_sampling_steps_override_scheduler():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7, "out", sampling_steps=12,
    )
    assert result["124"]["inputs"]["steps"] == 12


@pytest.mark.parametrize("preset, megapixels", [
    (f"{value / 10:.1f}mp", value / 10) for value in range(2, 11)
])
def test_build_supports_storyboard_test_megapixel_presets(preset, megapixels):
    result = build_workflow(
        load_template(TEMPLATE),
        ["one.png"],
        "prompt",
        6,
        7,
        "out",
        resolution=preset,
    )

    assert result["115"]["inputs"]["megapixels"] == megapixels


def test_build_r2va_workflow_saves_av_latent_and_handover():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7, "shot_01",
        generation_mode="r2va", save_latent=True,
    )

    assert result["136"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert result["202"]["class_type"] == "H3ContinuousAnalyzeHandoverV14"
    assert result["203"]["class_type"] == "H3ContinuousSaveLatent"
    assert result["203"]["inputs"]["latent"] == ["125", 0]
    assert result["203"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/latents/shot_01"
    assert result["203"]["inputs"]["handover"] == ["202", 0]
    assert result["204"]["inputs"]["output_mode"] == "Final Clip"


def test_build_uses_stitch_ready_only_when_the_next_shot_continues_it():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7, "shot_01",
        generation_mode="r2va", will_be_continued=True,
    )
    assert result["204"]["inputs"]["output_mode"] == "Stitch Ready"


def test_build_does_not_save_latent_when_switch_is_off_and_not_needed():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7, "shot_01",
        generation_mode="r2va", save_latent=False,
    )
    assert "202" not in result
    assert "203" not in result
    assert "204" not in result
    assert result["130"]["inputs"]["images"] == ["122", 0]


def test_next_shot_continuation_forces_previous_latent_save():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["one.png"], "prompt", 6, 7, "shot_01",
        generation_mode="r2va", save_latent=False, will_be_continued=True,
    )
    assert result["203"]["class_type"] == "H3ContinuousSaveLatent"


def test_build_fl2va_first_last_uses_first_two_references_as_keyframes():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["first.png", "last.png", "identity.png"],
        "prompt", 6, 7, "shot_01", generation_mode="fl2va",
    )

    assert result["136"]["class_type"] == "H3ContinuousStartV14"
    assert result["136"]["inputs"]["first_frame"] == ["200", 0]
    assert result["136"]["inputs"]["last_frame"] == ["201", 0]
    assert result["136"]["inputs"]["qwen_reference_1"] == ["205", 0]
    assert result["127"]["inputs"]["unet_name"] == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"


@pytest.mark.parametrize("reference_image_size", ["match", "max"])
def test_reference_image_size_is_forwarded_to_r2va_and_fl2va(reference_image_size):
    r2va = build_shot_workflow(
        load_template(TEMPLATE), ["identity.png"], "prompt", 6, 7, "r2va_size",
        generation_mode="r2va", reference_image_size=reference_image_size,
    )
    fl2va = build_shot_workflow(
        load_template(TEMPLATE), ["first.png", "last.png", "identity.png"], "prompt", 6, 7,
        "fl2va_size", generation_mode="fl2va", reference_image_size=reference_image_size,
    )

    assert r2va["136"]["inputs"]["ref_image_size"] == reference_image_size
    assert fl2va["136"]["inputs"]["ref_image_size"] == reference_image_size


def test_reference_image_size_is_forwarded_to_fl2va_latent_continuation():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["last.png", "identity.png"], "prompt", 6, 7, "shot_02",
        generation_mode="fl2va", continue_from_previous=True, previous_output_name="shot_01",
        reference_image_size="max",
    )

    assert result["201"]["inputs"]["ref_image_size"] == "max"


def test_reference_image_size_rejects_unknown_value():
    with pytest.raises(ValueError, match="参考图尺寸策略"):
        build_shot_workflow(
            load_template(TEMPLATE), ["identity.png"], "prompt", 6, 7, "invalid_size",
            reference_image_size="custom",
        )


@pytest.mark.parametrize("generation_mode", [
    "fl2va",
    "r2va",
])
def test_build_continuation_loads_previous_latent_and_uses_masked_target(generation_mode):
    refs = ["first.png", "last.png"] if generation_mode == "fl2va" else ["identity.png"]
    result = build_shot_workflow(
        load_template(TEMPLATE), refs, "prompt", 6, 7, "shot_02",
        generation_mode=generation_mode, continue_from_previous=True,
        previous_output_name="shot_01",
    )

    assert result["200"] == {
        "class_type": "H3ContinuousLoadLatent",
        "inputs": {
            "latent_path": "codex_ref2va_tool/latents/shot_01_00001.safetensors",
            "clip_index": 1,
        },
    }
    assert result["201"]["class_type"] == "H3ContinuousContinueV14"
    assert result["201"]["inputs"]["previous_latent"] == ["200", 0]
    assert result["201"]["inputs"]["handover"] == ["200", 3]
    assert result["125"]["inputs"]["latent_image"] == ["201", 1]
    assert result["126"]["inputs"]["conditioning"] == (["201", 0] if generation_mode == "fl2va" else ["136", 0])
    if generation_mode == "r2va":
        assert result["136"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    else:
        assert "136" not in result
    assert result["204"]["inputs"]["head_context_frames"] == ["201", 2]
    assert "203" not in result


@pytest.mark.parametrize("generation_mode", ["r2va", "fl2va"])
def test_build_continuation_preserves_native_audio_handover_by_default(generation_mode):
    refs = ["identity.png"] if generation_mode == "r2va" else ["last.png"]

    result = build_shot_workflow(
        load_template(TEMPLATE), refs, "prompt", 6, 7, "shot_02",
        generation_mode=generation_mode, continue_from_previous=True,
        previous_output_name="shot_01",
    )

    continuation_inputs = result["201"]["inputs"]
    assert continuation_inputs["audio_tail_carryover"] == "Full Previous Tail"
    assert continuation_inputs["audio_feather_ticks"] == 0


@pytest.mark.parametrize("generation_mode", ["r2va", "fl2va"])
def test_build_continuation_accepts_conservative_audio_handover(generation_mode):
    refs = ["identity.png"] if generation_mode == "r2va" else ["last.png"]
    result = build_shot_workflow(
        load_template(TEMPLATE), refs, "prompt", 6, 7, "shot_02",
        generation_mode=generation_mode, continue_from_previous=True,
        previous_output_name="shot_01",
        audio_tail_carryover="Match Video Handover",
        audio_feather_ticks=8,
    )
    continuation_inputs = result["201"]["inputs"]
    assert continuation_inputs["audio_tail_carryover"] == "Match Video Handover"
    assert continuation_inputs["audio_feather_ticks"] == 8


@pytest.mark.parametrize("generation_mode", ["r2va", "fl2va"])
def test_build_continuation_accepts_no_audio_carryover(generation_mode):
    refs = ["identity.png"] if generation_mode == "r2va" else ["last.png"]
    result = build_shot_workflow(
        load_template(TEMPLATE), refs, "prompt", 6, 7, "shot_02",
        generation_mode=generation_mode, continue_from_previous=True,
        previous_output_name="shot_01",
        audio_tail_carryover="No Audio Carryover",
    )
    assert result["201"]["inputs"]["audio_tail_carryover"] == "No Audio Carryover"


# --- ComfyUI 0.36 原生 ConcatenateVideo / Generic Loops ----------------------


def test_build_concatenate_workflow_uses_native_video_autogrow_naming():
    result = build_concatenate_workflow(
        ["codex_ref2va_tool/a_00001.mp4", "codex_ref2va_tool/b_00001.mp4", "codex_ref2va_tool/c_00001.mp4"],
        "codex_ref2va_tool/full_cut",
    )

    assert result["400"]["class_type"] == "LoadVideo"
    assert result["402"]["class_type"] == "LoadVideo"
    assert result["403"]["class_type"] == "ConcatenateVideo"
    # autogrow 前缀是 video（无下划线），与 ref_image_N 不同
    assert result["403"]["inputs"]["videos.video0"] == ["400", 0]
    assert result["403"]["inputs"]["videos.video1"] == ["401", 0]
    assert result["403"]["inputs"]["videos.video2"] == ["402", 0]
    assert result["403"]["inputs"]["codec"] == "auto"
    assert result["404"]["class_type"] == "SaveVideo"
    assert result["404"]["inputs"]["video"] == ["403", 0]
    assert result["404"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/full_cut"


def test_build_concatenate_workflow_rejects_empty_or_oversized_input():
    with pytest.raises(ValueError, match="至少需要一段视频"):
        build_concatenate_workflow([], "out")
    with pytest.raises(ValueError, match="最多串接"):
        build_concatenate_workflow([f"v{i}.mp4" for i in range(101)], "out")


def test_build_concatenate_workflow_rejects_unknown_codec():
    with pytest.raises(ValueError, match="不支持的串片编码"):
        build_concatenate_workflow(["a.mp4", "b.mp4"], "out", codec="vp9")


@pytest.mark.parametrize("codec", ["auto", "h264", "av1"])
def test_build_concatenate_workflow_accepts_supported_codecs(codec):
    result = build_concatenate_workflow(["a.mp4", "b.mp4"], "out", codec=codec)

    # 两段视频时 LoadVideo 占 400/401，串片节点是 402，落盘节点是 403。
    assert result["402"]["inputs"]["codec"] == codec


def test_build_batch_loop_workflow_drives_prompt_from_start_loop():
    result = build_batch_loop_workflow(
        load_template(TEMPLATE), ["identity.png"], ["第一个镜头", "第二个镜头"], 6, 4321,
        "codex_ref2va_tool/batch/shot",
    )

    assert result["900"]["class_type"] == "StartLoop"
    assert result["900"]["inputs"]["mode"] == "List"
    # CreateList 的 autogrow 前缀是 "inputs.input"（带 s），输出 0 号槽是 LIST。
    # 直接把提示词字面量写进 mode.list 会被校验器当成节点连线而 KeyError。
    assert result["900"]["inputs"]["mode.list"] == ["890", 0]
    assert result["890"]["class_type"] == "CreateList"
    assert result["890"]["inputs"] == {
        "inputs.input0": "第一个镜头",
        "inputs.input1": "第二个镜头",
    }
    assert result["900"]["inputs"]["cache_iterations"] is False
    # list_item 是 StartLoop 的第 4 个输出槽
    assert result["138"]["inputs"]["value"] == ["900", 3]


def test_build_batch_loop_workflow_increments_seed_per_shot():
    result = build_batch_loop_workflow(
        load_template(TEMPLATE), ["identity.png"], ["p1", "p2", "p3"], 6, 1000,
        "codex_ref2va_tool/batch/shot",
    )

    # ComfyMathExpression 的 INT 输出是 1 号槽，必须取 1 而不是 0（FLOAT）
    assert result["129"]["inputs"]["noise_seed"] == ["901", 1]
    assert result["901"]["inputs"]["expression"] == "1000 + a"
    assert result["901"]["inputs"]["values.a"] == ["900", 0]


def test_build_batch_loop_workflow_moves_save_video_outside_the_loop_body():
    result = build_batch_loop_workflow(
        load_template(TEMPLATE), ["identity.png"], ["p1", "p2"], 6, 1,
        "codex_ref2va_tool/batch/shot",
    )

    assert result["910"]["class_type"] == "EndLoop"
    assert result["910"]["inputs"]["accumulate"] is True
    assert result["910"]["inputs"]["output_value"] == ["130", 0]
    # 循环体内不能有终止输出节点，否则 ComfyUI 报 Loop body is not closed
    assert "92" not in result
    assert result["911"]["class_type"] == "SaveVideo"
    assert result["911"]["inputs"]["video"] == ["910", 0]
    assert "912" not in result


def test_build_batch_loop_workflow_accumulates_and_stitches_film():
    result = build_batch_loop_workflow(
        load_template(TEMPLATE), ["identity.png"], ["p1", "p2"], 6, 1,
        "codex_ref2va_tool/full_cut", stitch_output=True,
    )

    assert result["912"]["class_type"] == "ConcatenateVideo"
    assert result["912"]["inputs"]["videos.video0"] == ["910", 0]
    assert result["913"]["class_type"] == "SaveVideo"
    assert result["913"]["inputs"]["video"] == ["912", 0]
    assert result["913"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/full_cut_full_cut"
    # 逐镜落盘仍然保留，方便单镜复看
    assert result["911"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/full_cut"


def test_build_batch_loop_workflow_rejects_blank_prompts():
    with pytest.raises(ValueError, match="至少需要一条提示词"):
        build_batch_loop_workflow(load_template(TEMPLATE), ["a.png"], [], 6, 1, "out")
    with pytest.raises(ValueError, match="不能为空"):
        build_batch_loop_workflow(load_template(TEMPLATE), ["a.png"], ["ok", "   "], 6, 1, "out")
    # CreateList 官方上限 10 个入口，超了要让 ComfyUI 之前就报错而不是排进队列
    with pytest.raises(ValueError, match="最多 10 个镜头"):
        build_batch_loop_workflow(
            load_template(TEMPLATE), ["a.png"], [f"p{i}" for i in range(11)], 6, 1, "out"
        )


def test_build_batch_loop_workflow_keeps_r2va_reference_videos_inside_loop():
    result = build_batch_loop_workflow(
        load_template(TEMPLATE), ["identity.png"], ["p1", "p2"], 6, 1,
        "codex_ref2va_tool/batch/shot",
        reference_video_names=["codex_ref2va_tool/ref.mp4"],
    )

    assert result["136"]["inputs"]["ref_videos.ref_video_0"][0] in result



# --- FaceSwap LoRA（UntMods/FaceSwap_MiniMaxH3_REF2VA） ------------------------


def test_face_swap_lora_sits_between_turbo_and_sage_attention():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["identity.png"], "prompt", 6, 7, "shot_01",
        reference_video_names=["codex_ref2va_tool/ref.mp4"],
        face_swap_enabled=True,
    )

    assert result["155"]["class_type"] == "LoraLoaderModelOnly"
    assert result["155"]["inputs"]["lora_name"] == "SS_FaceSwap_MiniMax_H3_REF2VA.safetensors"
    assert result["155"]["inputs"]["strength_model"] == 1.0
    assert result["155"]["inputs"]["model"] == ["150", 0]
    assert result["142"]["inputs"]["model"] == ["155", 0]
    assert result["124"]["inputs"]["model"] == ["142", 0]
    assert result["126"]["inputs"]["model"] == ["142", 0]


def test_face_swap_skips_turbo_lora_when_disabled():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["identity.png"], "prompt", 6, 7, "shot_01",
        reference_video_names=["codex_ref2va_tool/ref.mp4"],
        turbo_lora_enabled=False, face_swap_enabled=True,
    )

    assert "150" not in result
    assert result["155"]["inputs"]["model"] == ["127", 0]
    assert result["142"]["inputs"]["model"] == ["155", 0]


def test_face_swap_injects_single_trigger_word():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["identity.png"], "夜景街头特写", 6, 7, "shot_01",
        reference_video_names=["codex_ref2va_tool/ref.mp4"],
        face_swap_enabled=True,
    )

    assert result["138"]["inputs"]["value"] == "Faceswap 夜景街头特写"


def test_face_swap_does_not_duplicate_existing_trigger_word():
    result = build_shot_workflow(
        load_template(TEMPLATE), ["identity.png"], "faceswap 夜景街头特写", 6, 7, "shot_01",
        reference_video_names=["codex_ref2va_tool/ref.mp4"],
        face_swap_enabled=True,
    )

    assert result["138"]["inputs"]["value"] == "faceswap 夜景街头特写"


def test_face_swap_is_absent_by_default():
    result = build_shot_workflow(load_template(TEMPLATE), ["identity.png"], "prompt", 6, 7, "shot_01")

    assert "155" not in result
    assert result["142"]["inputs"]["model"] == ["150", 0]


def test_face_swap_rejects_fl2va_mode():
    with pytest.raises(ValueError, match="只能\u5728 R2VA"):
        build_shot_workflow(
            load_template(TEMPLATE), ["first.png", "last.png"], "prompt", 6, 7, "shot_01",
            generation_mode="fl2va", face_swap_enabled=True,
        )


def test_batch_loop_prepends_face_swap_trigger_into_prompt_list():
    result = build_batch_loop_workflow(
        load_template(TEMPLATE), ["identity.png"], ["镜头一", "Faceswap 镜头二"], 6, 1,
        "codex_ref2va_tool/batch/shot",
        reference_video_names=["codex_ref2va_tool/ref.mp4"],
        face_swap_enabled=True,
    )

    # 循环里提示词来自 StartLoop.list_item，触发词必须写进 CreateList 的列表本身
    assert result["900"]["inputs"]["mode.list"] == ["890", 0]
    assert result["890"]["inputs"] == {
        "inputs.input0": "Faceswap 镜头一",
        "inputs.input1": "Faceswap 镜头二",
    }
    assert result["155"]["inputs"]["model"] == ["150", 0]
