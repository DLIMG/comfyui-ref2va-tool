from app.prompt_director import compile_director_prompt, normalize_director


def test_r2va_director_injects_inside_existing_description_without_touching_refs():
    prompt = (
        "subject_definitions:\n<Subject 1> is the actor in <Picture 1>.\n"
        "detailed_description:\n[Shot 1] <Subject 1> waits.\n"
        "overall_soundscape:\nRoom tone."
    )
    compiled, note = compile_director_prompt(prompt, "r2va", {
        "enabled": True, "shot_type": "close_up", "camera_motion": "push_in_slow",
        "audio_cue": "dialogue", "continuity": "latent",
    })

    assert note is not None
    assert compiled.count("Director execution:") == 1
    assert "detailed_description:\nDirector execution:" in compiled
    assert "<Picture 1>" in compiled
    assert "<Subject 1> waits." in compiled


def test_fl2va_director_targets_shared_description_and_is_idempotent():
    prompt = "integrated_multimodal_description:\n[Shot 1] The pose changes."
    settings = {"enabled": True, "shot_type": "medium", "camera_motion": "static"}
    first, _ = compile_director_prompt(prompt, "fl2va", settings)
    second, _ = compile_director_prompt(first, "fl2va", settings)

    assert second.count("Director execution:") == 1
    assert "integrated_multimodal_description:\nDirector execution:" in second


def test_disabled_or_invalid_director_preserves_source_prompt():
    prompt = "free prompt <Picture 1>"
    compiled, note = compile_director_prompt(prompt, "r2va", {"enabled": False})
    assert compiled == prompt
    assert note is None
    normalized = normalize_director({"enabled": True, "shot_type": "unknown", "camera_motion": "bad"})
    assert normalized["shot_type"] == "medium"
    assert normalized["camera_motion"] == "static"
