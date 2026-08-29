from pathlib import Path

import pytest

from app.results import delete_managed_result, find_fallback_outputs, find_video_outputs, preserve_results


def test_find_video_outputs_accepts_common_video_shapes():
    entry = {"outputs": {
        "1": {"videos": [{"filename": "a.mp4", "subfolder": "x", "type": "output"}]},
        "2": {"gifs": [{"filename": "b.webp"}, {"filename": "b.webm"}]},
        "3": {"files": [{"filename": "c.mov"}, {"filename": "still.png"}]},
    }}
    assert [item["filename"] for item in find_video_outputs(entry)] == ["a.mp4", "b.webm", "c.mov"]


def test_find_fallback_outputs_matches_safe_prefix(tmp_path):
    (tmp_path / "shot_00001_.mp4").write_bytes(b"one")
    (tmp_path / "shot_00002_.webm").write_bytes(b"two")
    (tmp_path / "other_00001_.mp4").write_bytes(b"other")
    found = find_fallback_outputs("shot", tmp_path)
    assert [item["filename"] for item in found] == ["shot_00001_.mp4", "shot_00002_.webm"]


def test_preserve_results_copies_source_without_deleting_it(tmp_path):
    output = tmp_path / "comfy"
    output.mkdir()
    source = output / "片段_00001_.mp4"
    source.write_bytes(b"video")
    results = preserve_results(
        [{"filename": source.name, "subfolder": "", "type": "output"}],
        output,
        tmp_path / "results",
        project_name="送错的密令",
        shot_id="01A",
        prompt_id="prompt-1",
    )
    assert len(results) == 1
    assert Path(results[0]["path"]).read_bytes() == b"video"
    assert source.exists()
    assert results[0]["prompt_id"] == "prompt-1"
    assert results[0]["id"]


def test_preserve_results_does_not_duplicate_output_root_subfolder(tmp_path):
    output = tmp_path / "codex_ref2va_tool"
    output.mkdir()
    source = output / "01A_偷拍布防图_00001_.mp4"
    source.write_bytes(b"video")

    results = preserve_results(
        [{"filename": source.name, "subfolder": "codex_ref2va_tool", "type": "output"}],
        output,
        tmp_path / "results",
        project_name="送错的密令",
        shot_id="01A",
        prompt_id="prompt-1",
    )

    assert len(results) == 1
    assert Path(results[0]["path"]).read_bytes() == b"video"
    assert source.exists()


def test_delete_managed_result_deletes_file_and_empty_leaf(tmp_path):
    root = tmp_path / "results"
    leaf = root / "project" / "shot" / "run"
    leaf.mkdir(parents=True)
    video = leaf / "result.mp4"
    video.write_bytes(b"video")
    delete_managed_result(video, root)
    assert not video.exists()
    assert not leaf.exists()
    assert root.exists()


def test_delete_managed_result_accepts_missing_managed_file(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    delete_managed_result(root / "project" / "missing.mp4", root)


def test_delete_managed_result_rejects_outside_path(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    with pytest.raises(ValueError, match="结果库"):
        delete_managed_result(outside, root)
    assert outside.exists()


def test_delete_managed_result_rejects_root_itself(tmp_path):
    root = tmp_path / "results"
    root.mkdir()

    with pytest.raises(ValueError, match="结果库"):
        delete_managed_result(root, root)

    assert root.is_dir()
