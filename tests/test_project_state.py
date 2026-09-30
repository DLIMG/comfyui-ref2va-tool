from pathlib import Path

from app.project_state import (
    persist_project_runtime,
    restore_imported_project,
    runtime_state_path,
)


def project(root: Path, name: str, shot_id: str = "S01"):
    return {
        "name": name,
        "project_dir": str(root),
        "shots": [{"id": shot_id, "title": "shot", "status": "draft", "results": []}],
    }


def test_runtime_sidecars_are_separated_by_storyboard_name(tmp_path):
    one = project(tmp_path, "版本一")
    two = project(tmp_path, "版本二")
    assert runtime_state_path(one, tmp_path / "data") != runtime_state_path(two, tmp_path / "data")


def test_import_restores_saved_runtime_for_target_project(tmp_path):
    saved = project(tmp_path, "版本一")
    saved["shots"][0].update({
        "status": "completed",
        "prompt_id": "prompt-1",
        "results": [{"id": "result-1", "path": str(tmp_path / "video.mp4")}],
    })
    persist_project_runtime(saved, tmp_path / "data")
    imported = project(tmp_path, "版本一")

    restored, recovered = restore_imported_project(imported, project(tmp_path, "另一个版本"), tmp_path / "data")

    assert recovered == 0
    assert restored["shots"][0]["prompt_id"] == "prompt-1"
    assert restored["shots"][0]["results"][0]["id"] == "result-1"


def test_import_discovers_real_videos_when_sidecar_is_missing(tmp_path):
    imported = project(tmp_path, "版本一")
    video = tmp_path / "06_生成视频" / "版本一" / "S01" / ("a" * 32) / "S01_take.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")

    restored, recovered = restore_imported_project(imported, {}, tmp_path / "data")

    assert recovered == 1
    result = restored["shots"][0]["results"][0]
    assert result["path"] == str(video.resolve())
    assert result["recovered"] is True
    assert restored["shots"][0]["status"] == "completed"


def test_import_does_not_mix_runtime_between_storyboard_names(tmp_path):
    saved = project(tmp_path, "版本一")
    saved["shots"][0]["results"] = [{"id": "old", "path": str(tmp_path / "old.mp4")}]
    persist_project_runtime(saved, tmp_path / "data")

    restored, recovered = restore_imported_project(project(tmp_path, "版本二"), saved, tmp_path / "data")

    assert recovered == 0
    assert restored["shots"][0]["results"] == []
