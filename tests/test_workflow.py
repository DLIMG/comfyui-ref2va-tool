import copy
import json
from pathlib import Path

import pytest

from app.workflow import build_shot_workflow, build_workflow, load_template, validate_template


TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "minimax_h3_turbo_8step_ref2va_api.json"


def test_load_and_validate_real_template():
    workflow = load_template(TEMPLATE)
    validate_template(workflow)
    assert workflow["136"]["class_type"] == "MiniMaxH3ReferenceToVideo"


def test_template_uses_only_the_active_turbo_8step_model_chain():
    workflow = load_template(TEMPLATE)

    assert workflow["127"]["class_type"] == "UNETLoader"
    assert workflow["150"] == {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": ["127", 0],
            "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
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
