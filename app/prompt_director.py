"""Deterministic MiniMaxDirector-style prompt preprocessor.

The ComfyUI MiniMaxDirector node owns a complete generation graph. Ref2VA
needs only its useful planning layer: a short, explicit shot/camera/audio cue
inserted into an existing H3 prompt without changing reference labels, media
bindings, or AV-latent handover. Keeping this compiler local also makes the
same storyboard portable between local and remote ComfyUI targets.
"""
from __future__ import annotations

import re
from typing import Any


SHOT_TYPES = {
    "wide": "wide establishing shot", "medium": "medium shot",
    "medium_close": "medium close-up", "close_up": "close-up",
    "extreme_close_up": "extreme close-up", "over_shoulder": "over-the-shoulder shot",
    "pov": "POV shot",
}
CAMERA_MOTIONS = {
    "static": "holds a static shot", "push_in_slow": "pushes in with small amplitude at slow speed",
    "pull_out_slow": "pulls out with small amplitude at slow speed",
    "pan": "pans with small amplitude at normal speed", "truck": "trucks with small amplitude at normal speed",
    "tracking": "uses a tracking shot at normal speed", "arc": "moves in a small arc at slow speed",
    "handheld": "uses restrained handheld movement",
}
AUDIO_CUES = {
    "ambient": "Keep only scene ambience and synchronized physical sounds in this cue.",
    "dialogue": "Keep dialogue only inside existing <d> tags; do not turn production instructions into speech.",
    "action_sync": "Synchronize the specified physical action and its diegetic sound without adding new events.",
    "music": "Leave non-diegetic music in the existing non_diegetic_music section only.",
    "silent": "Keep the scene quiet except for explicitly described sounds.",
}
CONTINUITY = {
    "preserve": "Preserve identity, wardrobe, props, screen direction, spatial layout, and lighting already defined by the prompt and references.",
    "latent": "Preserve the incoming AV-latent handover; do not introduce a cut, reset, or new source asset.",
    "keyframe": "Follow the existing keyframe path and land on the declared end state without adding a cut.",
}


def normalize_director(value: dict[str, Any] | None) -> dict[str, str | bool]:
    """Return a safe, portable director configuration with conservative defaults."""
    value = value or {}
    fields = {
        "shot_type": (SHOT_TYPES, "medium"), "camera_motion": (CAMERA_MOTIONS, "static"),
        "audio_cue": (AUDIO_CUES, "ambient"), "continuity": (CONTINUITY, "preserve"),
    }
    result: dict[str, str | bool] = {"enabled": bool(value.get("enabled", False))}
    for name, (choices, default) in fields.items():
        candidate = str(value.get(name) or default)
        result[name] = candidate if candidate in choices else default
    return result


def director_note(value: dict[str, Any] | None) -> str:
    config = normalize_director(value)
    return (
        f"Use a {SHOT_TYPES[str(config['shot_type'])]}. The camera "
        f"{CAMERA_MOTIONS[str(config['camera_motion'])]}. "
        f"{AUDIO_CUES[str(config['audio_cue'])]} {CONTINUITY[str(config['continuity'])]}"
    )


def compile_director_prompt(
    prompt: str, generation_mode: str, director: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Insert one director sentence into the correct H3 body field, idempotently."""
    config = normalize_director(director)
    if not config["enabled"]:
        return prompt, None
    note = director_note(config)
    marker = "Director execution: "
    cleaned = re.sub(r"(?m)^Director execution: .*\n?", "", str(prompt)).strip()
    field = "detailed_description:" if generation_mode == "r2va" else "integrated_multimodal_description:"
    if field in cleaned:
        return cleaned.replace(field, f"{field}\n{marker}{note}", 1), note
    return f"{marker}{note}\n{cleaned}".strip(), note
