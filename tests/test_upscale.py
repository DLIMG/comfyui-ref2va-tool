import importlib
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_api import FakeComfy


def test_build_480p_to_720p_upscale_workflow_preserves_audio_and_fps():
    assert importlib.util.find_spec("app.upscale") is not None
    build_video_upscale_workflow = importlib.import_module("app.upscale").build_video_upscale_workflow
    workflow = build_video_upscale_workflow(
        "codex_ref2va_tool/source.mp4", "codex_ref2va_tool/upscaled/source_720p",
        aspect_ratio="9:16", target_resolution="720p",
    )

    assert workflow["1"] == {"class_type": "LoadVideo", "inputs": {"file": "codex_ref2va_tool/source.mp4"}}
    assert workflow["3"]["inputs"]["model_name"] == "4x-UltraSharp.pth"
    assert workflow["4"]["inputs"]["per_batch"] == 1
    assert workflow["4"]["inputs"]["precision"] == "float16"
    assert workflow["4"]["inputs"]["downscale_method"] == "lanczos"
    assert workflow["5"]["inputs"]["width"] == 736
    assert workflow["5"]["inputs"]["height"] == 1280
    assert workflow["6"]["inputs"]["fps"] == ["2", 2]
    assert workflow["6"]["inputs"]["audio"] == ["2", 1]


def test_build_upscale_workflow_supports_1080p():
    build = importlib.import_module("app.upscale").build_video_upscale_workflow
    workflow = build("source.mp4", "out", aspect_ratio="16:9", target_resolution="1080p")
    assert workflow["5"]["inputs"]["width"] > 1280
    assert workflow["5"]["inputs"]["height"] > 720
    assert workflow["7"]["class_type"] == "SaveVideo"


def test_submit_upscale_queues_comfy_workflow_and_persists_job(tmp_path):
    result_file = tmp_path / "results" / "project" / "S01" / "r1" / "source.mp4"
    result_file.parent.mkdir(parents=True)
    result_file.write_bytes(b"video")
    fake = FakeComfy()
    browser = TestClient(create_app(client=fake, data_dir=tmp_path))
    browser.put("/api/storyboard", json={"name": "project", "shots": [{
        "id": "S01", "aspect_ratio": "9:16", "results": [{
            "id": "r1", "path": str(result_file), "filename": "source.mp4", "status": "ready",
        }],
    }]})

    response = browser.post("/api/results/upscale", json={
        "shot_id": "S01", "result_id": "r1", "target_resolution": "720p",
    })

    assert response.status_code == 200
    assert fake.workflow["3"]["inputs"]["model_name"] == "4x-UltraSharp.pth"
    source = browser.get("/api/storyboard").json()["shots"][0]["results"][0]
    assert source["upscale"]["status"] == "queued"
    assert source["upscale"]["prompt_id"] == "p1"
    assert source["upscale"]["target_resolution"] == "720p"


def test_collect_upscale_adds_new_managed_result(tmp_path):
    comfy_output = tmp_path / "comfy_output"
    comfy_output.mkdir()
    upscaled = comfy_output / "source_720p_00001_.mp4"
    upscaled.write_bytes(b"upscaled")
    prompt_id = "upscale-prompt"
    fake = FakeComfy({prompt_id: {"status": {"completed": True}, "outputs": {
        "7": {"videos": [{"filename": upscaled.name, "subfolder": "", "type": "output"}]}
    }}})
    source_file = tmp_path / "results" / "project" / "S01" / "r1" / "source.mp4"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"source")
    browser = TestClient(create_app(client=fake, data_dir=tmp_path, comfy_output=comfy_output))
    browser.put("/api/storyboard", json={"name": "project", "shots": [{
        "id": "S01", "results": [{
            "id": "r1", "path": str(source_file), "filename": "source.mp4", "status": "ready",
            "upscale": {"status": "queued", "prompt_id": prompt_id, "target_resolution": "720p"},
        }],
    }]})

    response = browser.post("/api/results/upscale/collect", json={"shot_id": "S01", "result_id": "r1"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[1]["kind"] == "upscaled"
    assert results[1]["source_result_id"] == "r1"
    assert results[1]["resolution"] == "720p"
    assert Path(results[1]["path"]).read_bytes() == b"upscaled"
