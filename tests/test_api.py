import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app, estimate_queue_remaining


PROJECT_TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "minimax_h3_turbo_8step_ref2va_api.json"


class FakeComfy:
    def __init__(self, history_data=None):
        self.history_data = history_data

    def system_stats(self):
        return {"system": {"comfyui_version": "test"}}

    def logs(self):
        return {"entries": [{"t": "2026-01-01T00:00:00", "m": "[INFO] ready\n"}]}

    def submit(self, workflow, client_id):
        self.workflow = workflow
        return {"prompt_id": "p1", "number": 1, "node_errors": {}}

    def history(self, prompt_id):
        if self.history_data is not None:
            return self.history_data
        return {prompt_id: {"status": {"completed": True}, "outputs": {}}}

    def queue(self):
        return {"queue_running": [], "queue_pending": []}

    def cancel(self, prompt_id):
        self.cancelled_prompt_id = prompt_id
        return {"cancelled": True}


class AdaptiveLowVRAMComfy(FakeComfy):
    def object_info(self):
        return {"MiniMaxH3AdaptiveLowVRAM": {"display_name": "MiniMax H3 Adaptive Low VRAM"}}


def test_chinese_shot_card_survives_storyboard_save_and_import(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    project = {
        "name": "逐镜修改",
        "shots": [{"id": "A07", "title": "转身", "prompt": "[Shot 1] He turns.",
                   "shot_card_zh": "先看向门口，停半秒，再缓慢转身。",
                   "shot_card_needs_sync": True}],
    }

    assert client.put("/api/storyboard", json=project).status_code == 200
    assert client.get("/api/storyboard").json()["shots"][0]["shot_card_zh"] == project["shots"][0]["shot_card_zh"]
    imported = client.post("/api/storyboard/import", json={"project": project})
    assert imported.status_code == 200
    assert imported.json()["project"]["shots"][0]["shot_card_needs_sync"] is True


def test_director_preview_compiles_without_rewriting_source_prompt(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    source = "integrated_multimodal_description:\n[Shot 1] The actor turns."

    response = client.post("/api/prompts/director", json={
        "prompt": source, "generation_mode": "fl2va",
        "director": {"enabled": True, "shot_type": "medium_close", "camera_motion": "arc"},
    })

    assert response.status_code == 200
    assert response.json()["prompt"].count("Director execution:") == 1
    assert source == "integrated_multimodal_description:\n[Shot 1] The actor turns."


def test_comfy_logs_proxies_terminal_entries(tmp_path):
    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).get("/api/comfy-logs")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["entries"][0]["m"] == "[INFO] ready\n"


def test_submit_auto_injects_adaptive_low_vram_when_target_supports_it(tmp_path):
    comfy = AdaptiveLowVRAMComfy()
    client = TestClient(create_app(client=comfy, data_dir=tmp_path))
    image = tmp_path / "ref.png"
    image.write_bytes(b"png")
    payload = {
        "id": "A01", "title": "test", "references": [str(image)],
        "reference_videos": [], "reference_audios": [], "prompt": "prompt",
        "duration": 7, "seed": 1, "resolution": "0.6mp", "aspect_ratio": "16:9",
        "output_name": "adaptive_test", "generation_mode": "r2va",
        "continue_from_previous": False, "previous_output_name": "",
        "will_be_continued": False, "save_latent": False,
        "turbo_lora_enabled": True, "sage_attention_enabled": True,
        "sampling_steps": 8, "audio_tail_carryover": "Full Previous Tail",
        "audio_feather_ticks": 0,
    }

    response = client.post("/api/submit", json=payload)

    assert response.status_code == 200
    assert response.json()["adaptive_low_vram"] is True
    assert comfy.workflow["160"]["class_type"] == "MiniMaxH3AdaptiveLowVRAM"


def test_queue_eta_adds_live_running_remainder_and_jobs_ahead():
    workflow = {
        "132": {"inputs": {"value": 10}},
        "115": {"inputs": {"megapixels": .4}},
    }
    queue = {
        "queue_running": [[0, "running", workflow, {"client_id": "c1"}]],
        "queue_pending": [[1, "ahead", workflow, {}], [2, "target", workflow, {}]],
    }
    class ProgressComfy:
        def progress(self, prompt_id):
            return {"sample_remaining_seconds": 120} if prompt_id == "running" else None
        def watch_progress(self, _client_id):
            pass

    remaining, source = estimate_queue_remaining(queue, "target", ProgressComfy())
    assert remaining == 1320
    assert source == "queue_plus_live_sampling"


def test_memory_cleanup_keeps_models_resident_and_returns_stats(tmp_path):
    class MemoryComfy(FakeComfy):
        def __init__(self):
            super().__init__()
            self.unload_models = None

        def free_memory(self, unload_models=False):
            self.unload_models = unload_models
            return {}

        def system_stats(self):
            return {"system": {"ram_free": 12 * 1024 ** 3}}

    fake = MemoryComfy()
    response = TestClient(create_app(client=fake, data_dir=tmp_path)).post(
        "/api/memory/cleanup", json={}
    )

    assert response.status_code == 200
    assert fake.unload_models is False
    assert response.json()["stats"]["system"]["ram_free"] == 12 * 1024 ** 3


def test_memory_pressure_unloads_models(tmp_path, monkeypatch):
    class MemoryComfy(FakeComfy):
        def __init__(self):
            super().__init__()
            self.calls = []

        def free_memory(self, unload_models=False):
            self.calls.append(unload_models)
            return {}

        def system_stats(self):
            return {"system": {"ram_free": 2 * 1024 ** 3}}

    monkeypatch.setenv("REF2VA_MIN_FREE_RAM_GB", "6")
    fake = MemoryComfy()
    response = TestClient(create_app(client=fake, data_dir=tmp_path)).post(
        "/api/memory/cleanup", json={}
    )

    assert response.status_code == 200
    assert fake.calls == [True]
    assert response.json()["reason"] == "low_system_memory"


def test_home_and_health(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    browser = TestClient(app)
    html = browser.get("/")
    assert html.status_code == 200
    assert 'id="reference-list"' in html.text
    assert 'id="prompt"' in html.text
    assert 'id="submit"' in html.text
    assert 'id="storyboard-toolbar"' in html.text
    assert 'id="storyboard-body"' in html.text
    assert 'id="editor-template"' in html.text
    assert 'id="add-shot"' in html.text
    assert 'id="submit-selected"' in html.text
    assert 'id="submit-all"' in html.text
    assert 'id="toggle-select-all"' in html.text
    health = browser.get("/api/health").json()
    assert health["ok"] is True


def test_batch_preflight_accepts_previous_shot_in_same_serial_batch(tmp_path):
    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).post(
        "/api/batch/preflight",
        json={"shots": [{"id": "S02", "output_name": "S02", "continue_from_previous": True,
                         "previous_output_name": "S01", "previous_in_batch": True}]},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "errors": []}


def test_batch_preflight_requires_existing_latent_when_previous_not_selected(tmp_path):
    comfy_output = tmp_path / "comfy_output"
    app = create_app(client=FakeComfy(), data_dir=tmp_path, comfy_output=comfy_output)
    browser = TestClient(app)
    payload = {"shots": [{"id": "S02", "output_name": "S02", "continue_from_previous": True,
                           "previous_output_name": "S01", "previous_in_batch": False}]}
    missing = browser.post("/api/batch/preflight", json=payload).json()
    assert missing["ok"] is False
    assert "S01" in missing["errors"][0]

    latent = comfy_output / "latents" / "S01_00001.safetensors"
    latent.parent.mkdir(parents=True)
    latent.write_bytes(b"latent")
    assert browser.post("/api/batch/preflight", json=payload).json() == {"ok": True, "errors": []}


def test_cancel_generation_delegates_exact_prompt_id_to_comfyui(tmp_path):
    fake = FakeComfy()
    response = TestClient(create_app(client=fake, data_dir=tmp_path)).post("/api/cancel/p-running")

    assert response.status_code == 200
    assert response.json() == {"cancelled": True, "prompt_id": "p-running"}
    assert fake.cancelled_prompt_id == "p-running"


def test_cancel_all_cancels_exact_snapshot_and_updates_storyboard(tmp_path):
    class QueueComfy(FakeComfy):
        def __init__(self):
            super().__init__()
            self.cancelled = []

        def queue(self):
            return {
                "queue_running": [[1, "p-running", {}, {}]],
                "queue_pending": [[2, "p-pending", {}, {}]],
            }

        def cancel(self, prompt_id):
            self.cancelled.append(prompt_id)
            return {"cancelled": True}

    fake = QueueComfy()
    browser = TestClient(create_app(client=fake, data_dir=tmp_path))
    browser.put("/api/storyboard", json={"shots": [
        {"id": "S1", "prompt_id": "p-running", "status": "running", "results": []},
        {"id": "S2", "prompt_id": "p-pending", "status": "queued", "results": []},
    ]})

    response = browser.post("/api/queue/cancel-all")

    assert response.status_code == 200
    assert response.json()["cancelled"] == 2
    assert fake.cancelled == ["p-running", "p-pending"]
    shots = browser.get("/api/storyboard").json()["shots"]
    assert [shot["status"] for shot in shots] == ["cancelled", "cancelled"]


def test_queue_endpoint_lists_all_comfyui_jobs_and_matches_storyboard(tmp_path):
    class QueueComfy(FakeComfy):
        def queue(self):
            return {"queue_running": [[1, "known", {}, {}]], "queue_pending": [[2, "external", {}, {}]]}

        def progress(self, prompt_id):
            return {"progress_percent": 25} if prompt_id == "known" else None

    browser = TestClient(create_app(client=QueueComfy(), data_dir=tmp_path))
    browser.put("/api/storyboard", json={"shots": [{"id": "01A", "title": "已知分镜", "prompt_id": "known", "results": []}]})
    payload = browser.get("/api/queue").json()
    assert payload["running"] == 1
    assert payload["pending"] == 1
    assert payload["jobs"][0]["shot_id"] == "01A"
    assert payload["jobs"][0]["progress_percent"] == 25
    assert payload["jobs"][1]["prompt_id"] == "external"


def test_task_missing_from_queue_and_history_is_failed_not_permanently_queued(tmp_path):
    class MissingComfy(FakeComfy):
        def history(self, prompt_id):
            return {}

    response = TestClient(create_app(client=MissingComfy(), data_dir=tmp_path)).get(
        "/api/task-status/orphaned-prompt"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "不在 ComfyUI 队列或历史记录中" in response.json()["error"]


def test_known_task_gets_queue_to_history_transition_grace(tmp_path):
    class MissingComfy(FakeComfy):
        def history(self, prompt_id):
            return {}

    browser = TestClient(create_app(client=MissingComfy(), data_dir=tmp_path))
    browser.put("/api/storyboard", json={"shots": [{
        "id": "01A", "status": "completed", "results": [],
        "refine_job": {"prompt_id": "transitioning", "status": "running"},
    }]})
    payload = browser.get("/api/task-status/transitioning").json()
    assert payload["status"] == "syncing"
    assert payload["transitioning"] is True


def test_playlist_javascript_is_served(tmp_path):
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    response = browser.get("/playlist.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "buildContinuousPlaylist" in response.text


def test_media_player_javascript_is_served(tmp_path):
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    response = browser.get("/media-player.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "replaceMediaElement" in response.text


def test_file_preview_serves_local_image(tmp_path):
    image = tmp_path / "预览.png"
    image.write_bytes(b"png-bytes")
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    response = TestClient(app).get("/api/file-preview", params={"path": str(image)})
    assert response.status_code == 200
    assert response.content == b"png-bytes"


def test_read_text_and_submit(tmp_path):
    source = tmp_path / "图.png"
    source.write_bytes(b"image")
    prompt_file = tmp_path / "提示词.txt"
    sections = [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
    ]
    prompt = "\n".join(f"{item}\n内容" for item in sections)
    prompt_file.write_text(prompt, encoding="utf-8")
    fake = FakeComfy()
    app = create_app(client=fake, data_dir=tmp_path)
    browser = TestClient(app)
    assert browser.post("/api/read-text", json={"path": str(prompt_file)}).json()["text"] == prompt
    response = browser.post("/api/submit", json={
        "references": [str(source)], "prompt": prompt, "duration": 6,
        "seed": 9, "output_name": "shot_01",
    })
    assert response.status_code == 200
    assert response.json()["prompt_id"] == "p1"
    assert fake.workflow["138"]["inputs"]["value"] == prompt
    assert fake.workflow["132"]["inputs"]["value"] == 6.0


def test_submit_payload_uses_project_turbo_template_and_preserves_dynamic_controls(tmp_path):
    source = tmp_path / "reference.png"
    source.write_bytes(b"image")
    prompt = "\n".join(
        f"{section}\n内容" for section in [
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
        ]
    )
    fake = FakeComfy()
    app = create_app(client=fake, data_dir=tmp_path, template_path=PROJECT_TEMPLATE)

    response = TestClient(app).post("/api/submit", json={
        "references": [str(source)], "prompt": prompt, "duration": 9.5,
        "seed": 2468, "output_name": "turbo_shot", "resolution": "720p",
        "aspect_ratio": "3:4",
    })

    assert response.status_code == 200
    submitted = fake.workflow
    assert submitted["150"]["inputs"]["model"] == ["127", 0]
    assert submitted["142"]["inputs"]["model"] == ["150", 0]
    assert submitted["124"]["inputs"]["model"] == ["142", 0]
    assert submitted["126"]["inputs"]["model"] == ["142", 0]
    assert "141" not in submitted and "152" not in submitted
    assert submitted["138"]["inputs"]["value"] == prompt
    assert submitted["132"]["inputs"]["value"] == 9.5
    assert submitted["129"]["inputs"]["noise_seed"] == 2468
    assert submitted["92"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/turbo_shot"
    assert submitted["115"]["inputs"]["megapixels"] == 0.9
    assert submitted["115"]["inputs"]["aspect_ratio"] == "3:4 (Portrait Standard)"


def test_submit_validation_error(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    response = TestClient(app).post("/api/submit", json={
        "references": [], "prompt": "", "duration": 0, "seed": 1, "output_name": "bad/name",
    })
    assert response.status_code == 422
    assert "至少添加一张参考图" in response.json()["detail"]


def test_submit_fl2va_mode_builds_first_last_workflow(tmp_path):
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"first")
    last.write_bytes(b"last")
    prompt = "\n".join(f"{name}\n内容" for name in [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
    ])
    fake = FakeComfy()
    response = TestClient(create_app(client=fake, data_dir=tmp_path / "data")).post("/api/submit", json={
        "references": [str(first), str(last)], "prompt": prompt, "duration": 6,
        "seed": 9, "output_name": "shot_01", "generation_mode": "fl2va",
        "save_latent": True,
    })
    assert response.status_code == 200
    assert fake.workflow["136"]["class_type"] == "H3ContinuousStartV14"
    assert fake.workflow["203"]["inputs"]["filename_prefix"].endswith("/shot_01")


def test_submit_eta_includes_masked_context_for_continuation(tmp_path):
    image = tmp_path / "ref.png"
    image.write_bytes(b"ref")
    prompt = "\n".join(f"{name}\ncontent" for name in [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
    ])
    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path / "data")).post(
        "/api/submit", json={
            "references": [str(image)], "prompt": prompt, "duration": 15,
            "output_name": "shot_02", "continue_from_previous": True,
            "previous_output_name": "shot_01", "resolution": "480p",
        },
    )
    assert response.status_code == 200
    assert response.json()["estimated_seconds"] == 998


def test_submit_r2va_latent_continuation_resolves_previous_output(tmp_path):
    image = tmp_path / "identity.png"
    image.write_bytes(b"identity")
    prompt = "\n".join(f"{name}\n内容" for name in [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
    ])
    fake = FakeComfy()
    response = TestClient(create_app(client=fake, data_dir=tmp_path / "data")).post("/api/submit", json={
        "references": [str(image)], "prompt": prompt, "duration": 6,
        "seed": 10, "output_name": "shot_02", "generation_mode": "r2va",
        "continue_from_previous": True, "previous_output_name": "shot_01",
    })
    assert response.status_code == 200
    assert fake.workflow["200"]["inputs"]["latent_path"].endswith("shot_01_00001.safetensors")
    assert fake.workflow["126"]["inputs"]["conditioning"] == ["136", 0]
    assert fake.workflow["125"]["inputs"]["latent_image"] == ["201", 1]


def test_submit_continuation_without_previous_output_is_rejected(tmp_path):
    image = tmp_path / "identity.png"
    image.write_bytes(b"identity")
    prompt = "\n".join(f"{name}\n内容" for name in [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
    ])
    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path / "data")).post("/api/submit", json={
        "references": [str(image)], "prompt": prompt, "duration": 6,
        "seed": 10, "output_name": "shot_01", "continue_from_previous": True,
    })
    assert response.status_code == 422
    assert "上一镜" in response.json()["detail"]


def test_storyboard_round_trip_with_twenty_independent_shots(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    browser = TestClient(app)
    shots = [{"id": f"{i:02d}A", "title": f"片段{i}", "references": [f"图{i}.png"]} for i in range(20)]
    project = {"name": "古鼎新叛变", "shots": shots}
    saved = browser.put("/api/storyboard", json=project)
    assert saved.status_code == 200
    restored = browser.get("/api/storyboard").json()
    assert restored == project
    restored["shots"][1]["references"].append("新图.png")
    assert restored["shots"][0]["references"] == ["图0.png"]


def test_missing_storyboard_returns_default(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    result = TestClient(app).get("/api/storyboard").json()
    assert result == {
        "name": "未命名项目",
        "advanced_settings": {
            "turbo_lora_enabled": True,
                "sage_attention_enabled": True,
                "sampling_steps": 8,
                "resolution": "0.4mp",
                "refine_target_resolution": "0.9mp",
                "generation_target": "local",
                "comfy_url": "http://192.168.11.103:8188",
        },
        "shots": [],
    }


def test_task_status_and_output_directory(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    browser = TestClient(app)
    assert browser.get("/api/task-status/p1").json()["status"] == "completed"
    output = browser.get("/api/output-dir").json()["path"]
    assert output.endswith(r"ComfyUI\output\codex_ref2va_tool")


def test_upload_multiple_images_preserves_order(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    response = TestClient(app).post(
        "/api/upload-images",
        files=[
            ("files", ("第一张.png", b"first", "image/png")),
            ("files", ("第二张.webp", b"second", "image/webp")),
        ],
    )
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert len(paths) == 2
    assert Path(paths[0]).read_bytes() == b"first"
    assert Path(paths[1]).read_bytes() == b"second"


def test_upload_rejects_non_image_file(tmp_path):
    app = create_app(client=FakeComfy(), data_dir=tmp_path)
    response = TestClient(app).post(
        "/api/upload-images",
        files=[("files", ("提示词.txt", b"text", "text/plain"))],
    )
    assert response.status_code == 400
    assert "不支持的图片格式" in response.json()["detail"]


def test_submit_passes_resolution_and_aspect_ratio_to_workflow(tmp_path):
    source = tmp_path / "图.png"
    source.write_bytes(b"image")
    prompt = "\n".join(
        f"{section}\n内容" for section in [
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
        ]
    )
    fake = FakeComfy()
    app = create_app(client=fake, data_dir=tmp_path)
    response = TestClient(app).post("/api/submit", json={
        "references": [str(source)], "prompt": prompt, "duration": 6,
        "seed": 9, "output_name": "shot_01", "resolution": "1080p",
        "aspect_ratio": "1:1",
    })
    assert response.status_code == 200
    assert fake.workflow["115"]["inputs"]["megapixels"] == 2.1
    assert fake.workflow["115"]["inputs"]["aspect_ratio"] == "1:1 (Square)"


def test_submit_passes_global_acceleration_switches_to_workflow(tmp_path):
    source = tmp_path / "ref.png"
    source.write_bytes(b"image")
    fake = FakeComfy()
    browser = TestClient(create_app(client=fake, data_dir=tmp_path / "data"))

    response = browser.post("/api/submit", json={
        "references": [str(source)], "prompt": "prompt", "duration": 6,
        "seed": 9, "output_name": "shot_01",
        "turbo_lora_enabled": False,
        "sage_attention_enabled": False,
    })

    assert response.status_code == 200
    assert "150" not in fake.workflow
    assert "142" not in fake.workflow
    assert fake.workflow["124"]["inputs"]["steps"] == 15
    assert response.json()["estimated_seconds"] == 675
    run_dir = Path(response.json()["run_dir"])
    request = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["request"]
    assert request["turbo_lora_enabled"] is False
    assert request["sage_attention_enabled"] is False


def test_collect_stream_and_delete_result(tmp_path):
    comfy_output = tmp_path / "comfy_output"
    comfy_output.mkdir()
    video = comfy_output / "shot_00001_.mp4"
    video.write_bytes(b"video-content")
    prompt_id = "prompt-result"
    fake = FakeComfy({prompt_id: {"status": {"completed": True}, "outputs": {
        "92": {"videos": [{"filename": video.name, "subfolder": "", "type": "output"}]}
    }}})
    app = create_app(client=fake, data_dir=tmp_path, comfy_output=comfy_output)
    browser = TestClient(app)
    project = {"name": "项目", "shots": [{
        "id": "01A", "output_name": "shot", "prompt_id": prompt_id,
        "status": "completed", "results": [],
    }]}
    assert browser.put("/api/storyboard", json=project).status_code == 200

    collected = browser.post("/api/results/collect", json={"shot_id": "01A"})
    assert collected.status_code == 200
    result = collected.json()["added"][0]
    assert Path(result["path"]).read_bytes() == b"video-content"
    duplicate = browser.post("/api/results/collect", json={"shot_id": "01A"}).json()
    assert duplicate["added"] == []

    streamed = browser.get(f'/api/results/video/01A/{result["id"]}')
    assert streamed.status_code == 200
    assert streamed.content == b"video-content"
    deleted = browser.delete(f'/api/results/01A/{result["id"]}')
    assert deleted.status_code == 200
    assert deleted.json()["results"] == []
    assert deleted.json()["prompt_id"] == ""
    assert not Path(result["path"]).exists()
    saved = browser.get("/api/storyboard").json()
    assert saved["shots"][0]["prompt_id"] == ""
    recollect = browser.post("/api/results/collect", json={"shot_id": "01A"})
    assert recollect.status_code == 409


def test_successful_collection_recovers_failed_shot_status(tmp_path):
    comfy_output = tmp_path / "comfy_output"
    comfy_output.mkdir()
    video = comfy_output / "recovered_00001_.mp4"
    video.write_bytes(b"recovered-video")
    prompt_id = "accepted-before-http-error"
    fake = FakeComfy({prompt_id: {"status": {"completed": True}, "outputs": {
        "92": {"videos": [{"filename": video.name, "subfolder": "", "type": "output"}]}
    }}})
    browser = TestClient(create_app(client=fake, data_dir=tmp_path, comfy_output=comfy_output))
    browser.put("/api/storyboard", json={"name": "项目", "shots": [{
        "id": "01A", "output_name": "recovered", "prompt_id": prompt_id,
        "status": "failed", "error": "Unexpected token 'I'", "results": [],
    }]})

    response = browser.post("/api/results/collect", json={"shot_id": "01A"})

    assert response.status_code == 200
    shot = browser.get("/api/storyboard").json()["shots"][0]
    assert shot["status"] == "completed"
    assert shot["error"] == ""


def test_collect_falls_back_to_output_prefix_when_history_is_missing(tmp_path):
    comfy_output = tmp_path / "comfy_output"
    comfy_output.mkdir()
    (comfy_output / "旧片段_00001_.mp4").write_bytes(b"old-video")
    app = create_app(client=FakeComfy({}), data_dir=tmp_path, comfy_output=comfy_output)
    browser = TestClient(app)
    browser.put("/api/storyboard", json={"name": "项目", "shots": [{
        "id": "01B", "output_name": "旧片段", "prompt_id": "cleared",
        "status": "completed", "results": [],
    }]})
    response = browser.post("/api/results/collect", json={"shot_id": "01B"})
    assert response.status_code == 200
    assert Path(response.json()["added"][0]["path"]).read_bytes() == b"old-video"


def test_delete_rejects_result_path_outside_library(tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"keep")
    app = create_app(client=FakeComfy(), data_dir=tmp_path, comfy_output=tmp_path / "output")
    browser = TestClient(app)
    browser.put("/api/storyboard", json={"name": "项目", "shots": [{
        "id": "01A", "results": [{"id": "bad", "path": str(outside)}],
    }]})
    response = browser.delete("/api/results/01A/bad")
    assert response.status_code == 400
    assert outside.exists()


def test_collect_uses_project_generated_video_directory(tmp_path):
    project_dir = tmp_path / "project"
    comfy_output = tmp_path / "comfy_output"
    comfy_output.mkdir()
    source = comfy_output / "shot_00001_.mp4"
    source.write_bytes(b"video")
    prompt_id = "project-result"
    fake = FakeComfy({prompt_id: {"outputs": {
        "92": {"videos": [{"filename": source.name, "subfolder": "", "type": "output"}]}
    }}})
    browser = TestClient(create_app(client=fake, data_dir=tmp_path / "data", comfy_output=comfy_output))
    browser.put("/api/storyboard", json={"name": "project", "project_dir": str(project_dir), "shots": [{
        "id": "01A", "prompt_id": prompt_id, "results": [],
    }]})

    response = browser.post("/api/results/collect", json={"shot_id": "01A"})

    assert response.status_code == 200
    result_path = Path(response.json()["added"][0]["path"])
    assert result_path.is_relative_to(project_dir / "06_生成视频")
    assert result_path.read_bytes() == b"video"
    assert source.exists()


def test_collect_without_project_dir_uses_legacy_results_directory(tmp_path):
    comfy_output = tmp_path / "comfy_output"
    comfy_output.mkdir()
    source = comfy_output / "shot_00001_.mp4"
    source.write_bytes(b"legacy")
    prompt_id = "legacy-result"
    fake = FakeComfy({prompt_id: {"outputs": {
        "92": {"videos": [{"filename": source.name, "subfolder": "", "type": "output"}]}
    }}})
    data_dir = tmp_path / "data"
    browser = TestClient(create_app(client=fake, data_dir=data_dir, comfy_output=comfy_output))
    browser.put("/api/storyboard", json={"name": "legacy", "project_dir": "  ", "shots": [{
        "id": "01A", "prompt_id": prompt_id, "results": [],
    }]})

    response = browser.post("/api/results/collect", json={"shot_id": "01A"})

    assert response.status_code == 200
    assert Path(response.json()["added"][0]["path"]).is_relative_to(data_dir / "results")


def test_collect_rejects_relative_project_dir(tmp_path):
    data_dir = tmp_path / "data"
    browser = TestClient(create_app(client=FakeComfy(), data_dir=data_dir))
    browser.put("/api/storyboard", json={"project_dir": "relative/project", "shots": [{
        "id": "01A", "prompt_id": "p1", "results": [],
    }]})

    response = browser.post("/api/results/collect", json={"shot_id": "01A"})

    assert response.status_code == 400
    assert "project_dir 必须是绝对路径" in response.json()["detail"]


def test_collect_reports_project_results_directory_creation_failure(tmp_path):
    project_dir = tmp_path / "project-file"
    project_dir.write_text("not a directory", encoding="utf-8")
    data_dir = tmp_path / "data"
    browser = TestClient(create_app(client=FakeComfy(), data_dir=data_dir))
    browser.put("/api/storyboard", json={"project_dir": str(project_dir), "shots": [{
        "id": "01A", "prompt_id": "p1", "results": [],
    }]})

    response = browser.post("/api/results/collect", json={"shot_id": "01A"})

    assert response.status_code == 400
    assert "无法创建项目结果目录" in response.json()["detail"]


def test_delete_accepts_result_in_current_project_directory(tmp_path):
    project_dir = tmp_path / "project"
    video = project_dir / "06_生成视频" / "project" / "01A" / "run" / "result.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path / "data"))
    browser.put("/api/storyboard", json={"project_dir": str(project_dir), "shots": [{
        "id": "01A", "results": [{"id": "current", "path": str(video)}],
    }]})

    response = browser.delete("/api/results/01A/current")

    assert response.status_code == 200
    assert not video.exists()


def test_delete_accepts_legacy_result_when_project_has_current_directory(tmp_path):
    data_dir = tmp_path / "data"
    video = data_dir / "results" / "project" / "01A" / "run" / "result.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    browser = TestClient(create_app(client=FakeComfy(), data_dir=data_dir))
    browser.put("/api/storyboard", json={"project_dir": str(tmp_path / "project"), "shots": [{
        "id": "01A", "results": [{"id": "legacy", "path": str(video)}],
    }]})

    response = browser.delete("/api/results/01A/legacy")

    assert response.status_code == 200
    assert not video.exists()


def test_delete_rejects_result_outside_legacy_and_current_project_directories(tmp_path):
    outside = tmp_path / "outside" / "result.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"keep")
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path / "data"))
    browser.put("/api/storyboard", json={"project_dir": str(tmp_path / "project"), "shots": [{
        "id": "01A", "results": [{"id": "outside", "path": str(outside)}],
    }]})

    response = browser.delete("/api/results/01A/outside")

    assert response.status_code == 400
    assert "允许的结果库" in response.json()["detail"]
    assert outside.exists()


def test_video_serves_result_in_current_project_directory(tmp_path):
    project_dir = tmp_path / "project"
    video = project_dir / "06_生成视频" / "project" / "01A" / "run" / "result.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"current-video")
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path / "data"))
    browser.put("/api/storyboard", json={"project_dir": str(project_dir), "shots": [{
        "id": "01A", "results": [{"id": "current", "path": str(video)}],
    }]})

    response = browser.get("/api/results/video/01A/current")

    assert response.status_code == 200
    assert response.content == b"current-video"


def test_video_serves_legacy_result_when_project_has_current_directory(tmp_path):
    data_dir = tmp_path / "data"
    video = data_dir / "results" / "project" / "01A" / "run" / "result.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"legacy-video")
    browser = TestClient(create_app(client=FakeComfy(), data_dir=data_dir))
    browser.put("/api/storyboard", json={"project_dir": str(tmp_path / "project"), "shots": [{
        "id": "01A", "results": [{"id": "legacy", "path": str(video)}],
    }]})

    response = browser.get("/api/results/video/01A/legacy")

    assert response.status_code == 200
    assert response.content == b"legacy-video"


def test_video_rejects_result_outside_legacy_and_current_project_directories(tmp_path):
    outside = tmp_path / "outside" / "result.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"private")
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path / "data"))
    browser.put("/api/storyboard", json={"project_dir": str(tmp_path / "project"), "shots": [{
        "id": "01A", "results": [{"id": "outside", "path": str(outside)}],
    }]})

    response = browser.get("/api/results/video/01A/outside")

    assert response.status_code == 400
    assert "允许的结果库" in response.json()["detail"]


def test_video_rejects_result_path_equal_to_allowed_root(tmp_path):
    data_dir = tmp_path / "data"
    results_root = data_dir / "results"
    results_root.mkdir(parents=True)
    browser = TestClient(create_app(client=FakeComfy(), data_dir=data_dir))
    browser.put("/api/storyboard", json={"shots": [{
        "id": "01A", "results": [{"id": "root", "path": str(results_root)}],
    }]})

    response = browser.get("/api/results/video/01A/root")

    assert response.status_code == 400
    assert "允许的结果库" in response.json()["detail"]


def test_delete_rejects_result_path_equal_to_allowed_root(tmp_path):
    data_dir = tmp_path / "data"
    results_root = data_dir / "results"
    results_root.mkdir(parents=True)
    browser = TestClient(create_app(client=FakeComfy(), data_dir=data_dir))
    browser.put("/api/storyboard", json={"shots": [{
        "id": "01A", "results": [{"id": "root", "path": str(results_root)}],
    }]})

    response = browser.delete("/api/results/01A/root")

    assert response.status_code == 400
    assert "允许的结果库" in response.json()["detail"]
    assert results_root.is_dir()


# --- ComfyUI 0.36 原生 ConcatenateVideo 整片串接 -------------------------------


def _fake_mp4(width: int, height: int) -> bytes:
    head = b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\xbdavc1" + b"\x00" * 8 + b"\x00" * 16
    return b"ftypisommoovstsd" + head + width.to_bytes(2, "big") + height.to_bytes(2, "big")


def _shot_with_result(tmp_path, shot_id: str, width: int, height: int) -> dict:
    video = tmp_path / f"{shot_id}.mp4"
    video.write_bytes(_fake_mp4(width, height))
    return {
        "id": shot_id,
        "title": shot_id,
        "prompt": "prompt",
        "output_name": shot_id,
        "results": [{
            "id": f"{shot_id}-r1", "created_at": "2026-09-19T00:00:00Z", "prompt_id": f"{shot_id}-p",
            "path": str(video), "filename": video.name, "source": {}, "status": "ready", "error": "",
        }],
    }


def test_concatenate_requires_at_least_two_shots(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))

    response = client.post("/api/results/concatenate", json={"shot_ids": ["A01"]})

    assert response.status_code == 422
    assert "至少选择两个镜头" in response.json()["detail"]


def test_concatenate_rejects_invalid_output_name(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))

    response = client.post(
        "/api/results/concatenate", json={"shot_ids": ["A01", "A02"], "output_name": "../evil"},
    )

    assert response.status_code == 422
    assert "输出名称" in response.json()["detail"]


def test_concatenate_reports_shot_without_ready_result(tmp_path):
    comfy = FakeComfy()
    client = TestClient(create_app(client=comfy, data_dir=tmp_path))
    client.put("/api/storyboard", json={"name": "P", "shots": [
        _shot_with_result(tmp_path, "A01", 1280, 720),
        {"id": "A02", "title": "A02", "prompt": "p", "output_name": "A02", "results": []},
    ]})

    response = client.post("/api/results/concatenate", json={"shot_ids": ["A01", "A02"]})

    assert response.status_code == 409
    assert "A02" in response.json()["detail"]


def test_concatenate_blocks_mismatched_resolutions_before_queueing(tmp_path):
    comfy = FakeComfy()
    client = TestClient(create_app(client=comfy, data_dir=tmp_path))
    client.put("/api/storyboard", json={"name": "P", "shots": [
        _shot_with_result(tmp_path, "A01", 1280, 720),
        _shot_with_result(tmp_path, "A02", 864, 480),
    ]})

    response = client.post("/api/results/concatenate", json={"shot_ids": ["A01", "A02"]})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "1280x720" in detail and "864x480" in detail
    assert not hasattr(comfy, "workflow")


def test_concatenate_submits_native_concatenate_video_graph(tmp_path):
    comfy = FakeComfy()
    client = TestClient(create_app(client=comfy, data_dir=tmp_path))
    client.put("/api/storyboard", json={"name": "P", "shots": [
        _shot_with_result(tmp_path, "A01", 1344, 768),
        _shot_with_result(tmp_path, "A02", 1344, 768),
        _shot_with_result(tmp_path, "A03", 1344, 768),
    ]})

    response = client.post(
        "/api/results/concatenate",
        json={"shot_ids": ["A01", "A02", "A03"], "output_name": "full_cut", "codec": "h264"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_id"] == "p1"
    assert body["segments"] == ["A01", "A02", "A03"]
    assert body["comfy_url"] == "http://127.0.0.1:8188"

    workflow = comfy.workflow
    load_ids = [k for k, v in workflow.items() if v["class_type"] == "LoadVideo"]
    concat_ids = [k for k, v in workflow.items() if v["class_type"] == "ConcatenateVideo"]
    assert len(load_ids) == 3
    assert len(concat_ids) == 1
    concat = workflow[concat_ids[0]]
    assert concat["inputs"]["codec"] == "h264"
    assert sorted(k for k in concat["inputs"] if k.startswith("videos.")) == [
        "videos.video0", "videos.video1", "videos.video2",
    ]
    save_ids = [k for k, v in workflow.items() if v["class_type"] == "SaveVideo"]
    assert workflow[save_ids[0]]["inputs"]["video"] == [concat_ids[0], 0]


def test_concatenate_collect_stores_film_under_full_cut_group(tmp_path):
    film = tmp_path / "comfy_output" / "codex_ref2va_tool" / "full_cut_00001_.mp4"
    film.parent.mkdir(parents=True)
    film.write_bytes(_fake_mp4(1344, 768))
    comfy = FakeComfy(history_data={
        "p1": {
            "status": {"completed": True},
            "outputs": {"99": {"images": [{"filename": "full_cut_00001_.mp4", "subfolder": "codex_ref2va_tool", "type": "output"}]}},
        },
    })
    client = TestClient(create_app(client=comfy, data_dir=tmp_path, comfy_output=film.parent))
    client.put("/api/storyboard", json={"name": "P", "shots": []})

    response = client.post(
        "/api/results/concatenate/collect", json={"prompt_id": "p1", "output_name": "full_cut"},
    )

    assert response.status_code == 200
    added = response.json()["added"]
    assert response.json()["shot_id"] == "_整片"
    assert len(added) == 1
    assert Path(added[0]["path"]).is_file()
    # 结果落在 结果库/<项目名>/整片/<id>/ 下（_safe_name 会去掉首尾下划线）
    assert "整片" in added[0]["path"]

