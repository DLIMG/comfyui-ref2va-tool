from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.video_analyzer_import import preview_video_analyzer


PROMPT = """subject_definitions:
<Subject 1> is shown in <Picture 1> and <Video 1>.
summary:
A short scene.
retention_analysis:
Preserve <Subject 1>.
detailed_description:
[Shot 1] <Subject 1> moves.
overall_soundscape:
Use <Audio 1>.
non_diegetic_music:
None.
"""


def test_video_analyzer_preview_maps_assets_without_queuing(tmp_path: Path):
    (tmp_path / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    frames = tmp_path / "keyframes"
    frames.mkdir()
    (frames / "shot_1.jpg").write_bytes(b"frame")
    video = tmp_path / "original.mp4"
    video.write_bytes(b"video")

    shot, warnings = preview_video_analyzer(str(tmp_path), str(video))

    assert shot["references"] == [str(frames / "shot_1.jpg")]
    assert shot["reference_videos"] == [str(video)]
    assert shot["reference_audios"] == []
    assert shot["prompt"] == PROMPT.strip()
    assert shot["status"] == "draft" and shot["prompt_id"] == "" and shot["results"] == []
    assert any("Audio" in warning for warning in warnings)


def test_video_analyzer_preview_rejects_missing_frame_number(tmp_path: Path):
    (tmp_path / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    frames = tmp_path / "keyframes"
    frames.mkdir()
    (frames / "shot_2.jpg").write_bytes(b"frame")

    with pytest.raises(ValueError, match="从 1 连续"):
        preview_video_analyzer(str(tmp_path))


def test_preview_endpoint_does_not_replace_storyboard(tmp_path: Path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    client = TestClient(create_app(client=object(), data_dir=tmp_path / "data"))

    response = client.post("/api/storyboard/preview-video-analyzer", json={"directory": str(analysis)})

    assert response.status_code == 200
    assert response.json()["shot"]["generation_mode"] == "r2va"
    assert client.get("/api/storyboard").json()["shots"] == []
