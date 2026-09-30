from pathlib import Path

import pytest

from app.storage import (
    default_project,
    load_project,
    migrate_project_references,
    save_project,
    save_uploaded_image,
    save_uploaded_video,
    stage_image,
)


def test_default_project_enables_global_acceleration():
    assert default_project()["advanced_settings"] == {
        "turbo_lora_enabled": True,
        "sage_attention_enabled": True,
        "sampling_steps": 8,
        "resolution": "0.4mp",
        "refine_target_resolution": "0.9mp",
        "generation_target": "local",
        "comfy_url": "http://192.168.11.103:8188",
    }


def test_project_round_trip_preserves_chinese(tmp_path):
    project = default_project()
    project["name"] = "古鼎新叛变"
    project["shots"] = [{"id": "第一镜", "references": ["人物.png"]}]
    path = tmp_path / "project.json"
    save_project(path, project)
    assert load_project(path) == project


def test_missing_project_returns_default(tmp_path):
    project = load_project(tmp_path / "missing.json")
    assert project["name"] == "未命名项目"
    assert project["shots"] == []


def test_stage_image_uses_hash_and_deduplicates(tmp_path):
    source = tmp_path / "古 鼎新.png"
    source.write_bytes(b"same-image")
    target = tmp_path / "input"
    first = stage_image(source, target)
    second = stage_image(source, target)
    assert first == second
    assert first.exists()
    assert len(list(target.iterdir())) == 1
    assert "古_鼎新" in first.name


def test_save_uploaded_image_uses_safe_hashed_name(tmp_path):
    saved = save_uploaded_image("古 鼎新?.PNG", b"image-content", tmp_path / "uploads")
    assert saved.is_file()
    assert saved.read_bytes() == b"image-content"
    assert saved.suffix == ".png"
    assert "?" not in saved.name


def test_save_uploaded_image_rejects_non_image_extension(tmp_path):
    with pytest.raises(ValueError, match="不支持的图片格式"):
        save_uploaded_image("prompt.txt", b"text", tmp_path / "uploads")


def test_save_uploaded_video_uses_safe_hashed_name(tmp_path):
    saved = save_uploaded_video("参考 视频?.MP4", b"video-content", tmp_path / "uploads")
    assert saved.is_file()
    assert saved.read_bytes() == b"video-content"
    assert saved.suffix == ".mp4"


def test_migrate_project_references_rewrites_known_paths_without_mutating_input():
    old_path = r"G:\旧目录\古鼎新.png"
    new_path = r"G:\项目\角色资产\古鼎新.png"
    untouched = r"G:\项目\角色资产\副官.png"
    project = {"name": "送错的密令", "shots": [{"id": "01A", "references": [old_path, untouched]}]}

    migrated = migrate_project_references(project, {old_path: new_path})

    assert migrated["shots"][0]["references"] == [new_path, untouched]
    assert project["shots"][0]["references"] == [old_path, untouched]
