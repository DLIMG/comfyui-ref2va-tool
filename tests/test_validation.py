from pathlib import Path

from app.validation import REQUIRED_SECTIONS, validate_shot


def valid_prompt():
    return "\n".join(f"{section}\n内容" for section in REQUIRED_SECTIONS)


def test_valid_shot_has_no_errors(tmp_path):
    image = tmp_path / "图.png"
    image.write_bytes(b"x")
    shot = {"references": [str(image)], "prompt": valid_prompt(), "duration": 6, "output_name": "shot_01"}
    assert validate_shot(shot) == []


def test_nonempty_freeform_prompt_is_accepted(tmp_path):
    image = tmp_path / "图.png"
    image.write_bytes(b"x")
    shot = {
        "references": [str(image)],
        "prompt": "[场景与影调全局]\n一镜到底，暖色正常时间，冻结后冷蓝。",
        "duration": 8,
        "output_name": "shot_freeform",
    }
    assert validate_shot(shot) == []


def test_invalid_shot_returns_chinese_errors(tmp_path):
    shot = {"references": [str(tmp_path / "missing.png")], "prompt": "summary:\n内容", "duration": 0, "output_name": "bad/name"}
    errors = validate_shot(shot)
    joined = " ".join(errors)
    assert "参考图不存在" in joined
    assert "时长必须大于0" in joined
    assert "输出名称" in joined


def test_requires_at_least_one_reference():
    errors = validate_shot({"references": [], "prompt": valid_prompt(), "duration": 6, "output_name": "ok"})
    assert "至少添加一张参考图、一段参考视频或一段参考音频" in errors


def test_r2va_accepts_video_as_the_only_reference(tmp_path):
    video = tmp_path / "参考.mp4"
    video.write_bytes(b"video")
    errors = validate_shot({
        "generation_mode": "r2va", "references": [], "reference_videos": [str(video)],
        "prompt": "使用<Video 1>的动作", "duration": 15, "output_name": "video_ref",
    })
    assert errors == []


def test_fl2va_rejects_reference_videos(tmp_path):
    first, last, video = tmp_path / "first.png", tmp_path / "last.png", tmp_path / "ref.mp4"
    first.write_bytes(b"x"); last.write_bytes(b"x"); video.write_bytes(b"x")
    errors = validate_shot({
        "generation_mode": "fl2va", "references": [str(first), str(last)],
        "reference_videos": [str(video)], "prompt": "prompt", "duration": 6, "output_name": "bad",
    })
    assert "参考视频当前仅支持R2VA模式" in errors


def test_rejects_unknown_generation_mode(tmp_path):
    image = tmp_path / "图.png"
    image.write_bytes(b"x")
    errors = validate_shot({
        "generation_mode": "unknown", "references": [str(image)],
        "prompt": valid_prompt(), "duration": 6, "output_name": "ok",
    })
    assert "生成模式" in " ".join(errors)


def test_rejects_unknown_reference_image_size(tmp_path):
    image = tmp_path / "图.png"
    image.write_bytes(b"x")
    errors = validate_shot({
        "references": [str(image)], "prompt": valid_prompt(), "duration": 6,
        "output_name": "ok", "reference_image_size": "custom",
    })
    assert any("match" in error and "max" in error for error in errors)


def test_fl2va_first_shot_requires_first_and_last_frames(tmp_path):
    image = tmp_path / "首帧.png"
    image.write_bytes(b"x")
    errors = validate_shot({
        "generation_mode": "fl2va", "continue_from_previous": False,
        "references": [str(image)], "prompt": valid_prompt(),
        "duration": 6, "output_name": "ok",
    })
    assert "首帧和尾帧" in " ".join(errors)


def test_continuation_requires_previous_output_name(tmp_path):
    image = tmp_path / "图.png"
    image.write_bytes(b"x")
    errors = validate_shot({
        "generation_mode": "r2va", "continue_from_previous": True,
        "previous_output_name": "", "references": [str(image)],
        "prompt": valid_prompt(), "duration": 6, "output_name": "ok",
    })
    assert "上一镜" in " ".join(errors)
