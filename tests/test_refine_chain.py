"""二采链归属规则，以及"删掉二采后重新二采"必须还是二采的回归护栏。

修的是一个真实事故：用户删掉二采产物后重新点一采的二采，工具却提交了三采
（因为只在链尾 refine_job 上推档位，删除没有作废这条链）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.refine_chain import (
    latest_prompt_id,
    latent_name_for_pass,
    pass_from_filename,
    plan_refine_from_result,
    refresh_refine_chain,
    result_latent_name,
    result_pass_number,
)


class FakeComfy:
    def __init__(self, files: dict[str, bytes] | None = None,
                 outputs: dict[str, dict] | None = None,
                 history_all: dict[str, dict] | None = None):
        self.files = files or {}
        self.outputs = outputs or {}
        self.history_all = history_all if history_all is not None else {}
        self.submitted: list[dict] = []

    def system_stats(self):
        return {"system": {"comfyui_version": "test"}}

    def logs(self):
        return {"entries": []}

    def object_info(self):
        return {"MinimaxH3LatentUpscaler3D": {}, "MMH3SplitUpscale": {}}

    def histories(self):
        return self.history_all

    def history(self, prompt_id):
        entry = self.outputs.get(prompt_id, {"status": {"completed": True}, "outputs": {}})
        return {prompt_id: entry}

    def queue(self):
        return {"queue_running": [], "queue_pending": []}

    def submit(self, workflow, client_id):
        self.submitted.append(workflow)
        return {"prompt_id": f"prompt-{len(self.submitted)}", "number": 1, "node_errors": {}}

    def download_output(self, output, progress_callback=None):
        return self.files.get(str(output.get("filename")), b"fake-video")

    def cancel(self, prompt_id):
        return {"cancelled": True}


# ---------------------------------------------------------------- 纯规则 ----


def test_pass_number_prefers_recorded_value_and_falls_back_to_filename():
    assert result_pass_number({"pass_number": 3, "filename": "a_p2_00001_.mp4"}) == 3
    assert result_pass_number({"filename": "shot_00004_.mp4"}) == 1
    assert result_pass_number({"filename": "shot_p2_00001_.mp4"}) == 2
    assert result_pass_number({}) == 1


def test_pass_from_filename_ignores_mid_name_matches():
    assert pass_from_filename("shot_p2_00001_.mp4") == 2
    assert pass_from_filename("shot_p2") == 2
    assert pass_from_filename("shot_p2x_00001_.mp4") == 1
    assert pass_from_filename("") == 1


def test_latent_name_for_pass_keeps_first_pass_bare():
    assert latent_name_for_pass("shot", 1) == "shot"
    assert latent_name_for_pass("shot", 2) == "shot_p2"


def test_plan_refine_uses_the_clicked_result_not_the_chain_tail():
    shot = {"output_name": "shot"}
    first = {"id": "r1", "pass_number": 1, "filename": "shot_00004_.mp4"}
    second = {"id": "r2", "pass_number": 2, "filename": "shot_p2_00001_.mp4"}
    assert plan_refine_from_result(shot, first) == (2, "shot")
    assert plan_refine_from_result(shot, second) == (3, "shot_p2")


def test_result_latent_name_backfills_legacy_rows():
    shot = {"output_name": "shot"}
    assert result_latent_name({"filename": "shot_p2_00001_.mp4"}, shot) == "shot_p2"
    assert result_latent_name({"filename": "shot_00004_.mp4"}, shot) == "shot"


def test_chain_is_dropped_when_its_product_is_gone():
    shot = {
        "output_name": "shot",
        "results": [{"id": "r1", "pass_number": 1}],
        "refine_job": {"pass_number": 2, "prompt_id": "p2", "status": "completed"},
    }
    assert refresh_refine_chain(shot)["cleared"] is True
    assert "refine_job" not in shot


def test_chain_survives_while_its_product_is_still_listed():
    shot = {
        "output_name": "shot",
        "results": [{"id": "r1", "pass_number": 1}, {"id": "r2", "pass_number": 2, "prompt_id": "p2"}],
        "refine_job": {"pass_number": 2, "prompt_id": "p2", "status": "completed"},
    }
    assert refresh_refine_chain(shot)["cleared"] is False
    assert shot["refine_job"]["pass_number"] == 2


def test_latest_prompt_id_follows_the_highest_pass():
    shot = {"results": [
        {"prompt_id": "p1", "pass_number": 1},
        {"prompt_id": "p3", "pass_number": 3},
        {"prompt_id": "p2", "pass_number": 2},
    ]}
    assert latest_prompt_id(shot) == "p3"
    assert latest_prompt_id({"results": []}) == ""


# --------------------------------------------------------------- 接口层 ----


def managed_result(tmp_path: Path, folder: str, filename: str) -> str:
    """结果库里的一个托管文件（delete 接口只会删除库内的文件）。"""
    leaf = tmp_path / "results" / "测试项目" / "C1" / folder
    leaf.mkdir(parents=True, exist_ok=True)
    target = leaf / filename
    target.write_bytes(b"video")
    return str(target)


def make_board(tmp_path: Path) -> dict:
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"png")
    return {
        "name": "测试项目",
        "project_dir": "",
        "advanced_settings": {
            "generation_target": "remote",
            "comfy_url": "http://192.168.11.103:8188",
        },
        "shots": [{
            "id": "C1", "output_name": "shot_a", "prompt": "测试镜头",
            "duration": 6, "seed": 1, "generation_mode": "r2va",
            "aspect_ratio": "16:9", "references": [str(reference)],
            "results": [
                {"id": "first", "prompt_id": "p1", "pass_number": 1,
                 "latent_name": "shot_a__run_" + "a" * 32,
                 "filename": "shot_a_00004_.mp4",
                 "path": managed_result(tmp_path, "first", "shot_a_00004_.mp4")},
                {"id": "second", "prompt_id": "p2", "pass_number": 2,
                 "latent_name": "shot_a_p2__run_" + "b" * 32,
                 "filename": "shot_a_p2_00001_.mp4",
                 "path": managed_result(tmp_path, "second", "shot_a_p2_00001_.mp4")},
            ],
            "refine_job": {
                "status": "completed", "prompt_id": "p2", "pass_number": 2,
                "output_name": "shot_a_p2", "source_latent_name": "shot_a",
            },
        }],
    }


def write_board(tmp_path: Path, board: dict) -> TestClient:
    (tmp_path / "storyboard.json").write_text(
        json.dumps(board, ensure_ascii=False), encoding="utf-8",
    )
    return TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))


def test_deleting_the_refine_product_drops_the_chain(tmp_path):
    client = write_board(tmp_path, make_board(tmp_path))
    response = client.delete("/api/results/C1/second")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["refine_cleared"] is True
    assert payload["next_pass"] == 2

    saved = json.loads((tmp_path / "storyboard.json").read_text(encoding="utf-8"))
    shot = saved["shots"][0]
    assert "refine_job" not in shot
    assert [item["id"] for item in shot["results"]] == ["first"]


def test_refining_the_first_pass_again_stays_a_second_pass(tmp_path):
    """事故复现：删掉二采后点一采的二采，不能再变成三采。"""
    client = write_board(tmp_path, make_board(tmp_path))
    client.delete("/api/results/C1/second")

    response = client.post("/api/refine", json={
        "shot_id": "C1",
        "target_resolution": "0.9mp",
        # 前端若按旧逻辑把档位算成 3，服务端也要以"点的那条视频"为准纠正回来。
        "pass_number": 3,
        "source_latent_name": "shot_a_p2",
        "source_result_id": "first",
    })
    assert response.status_code == 200, response.text
    job = response.json()["refine_job"]
    assert job["pass_number"] == 2
    assert job["output_name"] == "shot_a_p2"
    assert job["source_latent_name"] == "shot_a__run_" + "a" * 32


def test_deleting_the_first_pass_only_leaves_the_chain_alone(tmp_path):
    client = write_board(tmp_path, make_board(tmp_path))
    response = client.delete("/api/results/C1/first")
    assert response.status_code == 200, response.text
    assert response.json()["refine_cleared"] is False


def outputs_for(*filenames: str) -> dict:
    return {"status": {"completed": True}, "outputs": {
        "130": {"videos": [{"filename": name, "subfolder": "", "type": "output"}
                           for name in filenames]},
    }}


def test_collecting_a_refine_result_tags_its_pass(tmp_path):
    """收集二采产物时要标注档位，否则下次点它就不知道是第几采。"""
    board = make_board(tmp_path)
    shot = board["shots"][0]
    shot["results"] = [item for item in shot["results"] if item["id"] == "first"]
    shot["prompt_id"] = "p2"
    shot["resolution"] = "0.9mp"
    comfy_out = tmp_path / "comfyout"
    comfy_out.mkdir()
    (comfy_out / "shot_a_p2_00005_.mp4").write_bytes(b"video")
    (tmp_path / "storyboard.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    client = TestClient(create_app(
        client=FakeComfy(outputs={"p2": outputs_for("shot_a_p2_00005_.mp4")}),
        data_dir=tmp_path, comfy_input=tmp_path / "comfyin", comfy_output=comfy_out,
    ))

    response = client.post("/api/results/collect", json={"shot_id": "C1"})
    assert response.status_code == 200, response.text
    added = response.json()["added"]
    assert len(added) == 1
    assert added[0]["pass_number"] == 2
    assert added[0]["latent_name"] == "shot_a_p2"


def test_recoverable_lists_what_comfyui_still_has(tmp_path):
    board = make_board(tmp_path)
    board["shots"][0]["results"] = []
    (tmp_path / "storyboard.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    fake = FakeComfy(history_all={
        "p1": outputs_for("shot_a_00004_.mp4"),
        "p2": outputs_for("shot_a_p2_00001_.mp4"),
        "other": outputs_for("别家_00001_.mp4"),
    })
    client = TestClient(create_app(client=fake, data_dir=tmp_path))

    payload = client.get("/api/results/recoverable/C1").json()
    names = sorted(item["filename"] for item in payload["files"])
    assert names == ["shot_a_00004_.mp4", "shot_a_p2_00001_.mp4"]
    assert len(payload["missing"]) == 2
    passes = {item["filename"]: item["pass_number"] for item in payload["files"]}
    assert passes["shot_a_p2_00001_.mp4"] == 2


def test_restore_pulls_deleted_videos_back(tmp_path):
    board = make_board(tmp_path)
    board["shots"][0]["results"] = []
    (tmp_path / "storyboard.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    fake = FakeComfy(
        files={"shot_a_00004_.mp4": b"first", "shot_a_p2_00001_.mp4": b"second"},
        history_all={"p1": outputs_for("shot_a_00004_.mp4"),
                     "p2": outputs_for("shot_a_p2_00001_.mp4")},
    )
    client = TestClient(create_app(client=fake, data_dir=tmp_path))

    response = client.post("/api/results/restore", json={"shot_id": "C1"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["restored"] == 2
    paths = {item["filename"]: Path(item["path"]) for item in payload["added"]}
    assert paths["shot_a_00004_.mp4"].read_bytes() == b"first"
    assert paths["shot_a_p2_00001_.mp4"].read_bytes() == b"second"
    assert [item["pass_number"] for item in payload["added"]] == [1, 2]

    # 第二次调用不应重复下载。
    again = client.post("/api/results/restore", json={"shot_id": "C1"}).json()
    assert again["restored"] == 0


def test_restore_repairs_a_record_whose_file_is_gone(tmp_path):
    """删除事故的残骸形态：记录还在、文件没了。

    这时不能判成"已经有了"而放着不管，也不能再挂一份重复卡片。
    """
    board = make_board(tmp_path)
    shot = board["shots"][0]
    shot["results"] = [item for item in shot["results"] if item["id"] == "first"]
    Path(shot["results"][0]["path"]).unlink()
    (tmp_path / "storyboard.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    fake = FakeComfy(files={"shot_a_00004_.mp4": b"fresh"},
                     history_all={"p1": outputs_for("shot_a_00004_.mp4")})
    client = TestClient(create_app(client=fake, data_dir=tmp_path))

    listed = client.get("/api/results/recoverable/C1").json()
    assert [item["has_local"] for item in listed["files"]] == [False]

    payload = client.post("/api/results/restore", json={"shot_id": "C1"}).json()
    assert payload["restored"] == 1
    assert payload["repaired"] == 1
    assert payload["appended"] == 0
    assert len(payload["results"]) == 1
    assert Path(payload["results"][0]["path"]).read_bytes() == b"fresh"


@pytest.mark.parametrize("status", ["queued", "running", "syncing"])
def test_deleting_old_result_keeps_active_refine_tracking(tmp_path, status):
    board = make_board(tmp_path)
    board["shots"][0]["refine_job"].update(status=status, prompt_id="active-refine")
    client = write_board(tmp_path, board)
    response = client.delete("/api/results/C1/first")
    assert response.status_code == 200
    assert response.json()["refine_cleared"] is False
    saved = client.get("/api/storyboard").json()["shots"][0]
    assert saved["refine_job"]["prompt_id"] == "active-refine"
    assert saved["refine_job"]["status"] == status


def test_restoration_excludes_similar_names_and_wrong_workflow(tmp_path):
    board = make_board(tmp_path)
    board["shots"][0]["results"] = []
    write_board(tmp_path, board)
    wrong_graph = outputs_for("shot_a_00008_.mp4")
    wrong_graph["prompt"] = [0, "wrong", {"92": {
        "class_type": "SaveVideo", "inputs": {"filename_prefix": "shot_ab"},
    }}]
    fake = FakeComfy(history_all={
        "first": outputs_for("shot_a_00001_.mp4"),
        "refine": outputs_for("shot_a_p2_00001_.mp4"),
        "collision": outputs_for("shot_ab_00001_.mp4", "shot_a_extra_00001_.mp4",
                                 "shot_a_p2_extra_00001_.mp4"),
        "wrong": wrong_graph,
    })
    client = TestClient(create_app(client=fake, data_dir=tmp_path))
    listed = client.get("/api/results/recoverable/C1").json()["files"]
    assert {item["filename"] for item in listed} == {"shot_a_00001_.mp4", "shot_a_p2_00001_.mp4"}
    restored = client.post("/api/results/restore", json={"shot_id": "C1"}).json()
    assert {item["filename"] for item in restored["added"]} == {item["filename"] for item in listed}


def test_manual_restore_cannot_bypass_shot_ownership(tmp_path):
    board = make_board(tmp_path)
    write_board(tmp_path, board)
    fake = FakeComfy(history_all={"other": outputs_for("shot_ab_00001_.mp4")})
    client = TestClient(create_app(client=fake, data_dir=tmp_path))
    response = client.post("/api/results/restore", json={"shot_id": "C1", "files": [{
        "filename": "shot_ab_00001_.mp4", "subfolder": "", "prompt_id": "other",
    }]})
    assert response.status_code == 400
    assert len(client.get("/api/storyboard").json()["shots"][0]["results"]) == 2


def test_history_restoration_preserves_versioned_latent(tmp_path):
    from app.latent_versions import add_versioned_latent_output
    board = make_board(tmp_path)
    board["shots"][0]["results"] = []
    write_board(tmp_path, board)
    workflow = {
        "92": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "shot_a_p2"}},
        "308": {"class_type": "H3ContinuousSaveLatent", "inputs": {
            "latent": ["307", 0], "filename_prefix": "codex_ref2va_tool/latents/shot_a_p2", "clip_index": 1,
        }},
    }
    latent_name = add_versioned_latent_output(workflow, "shot_a_p2")
    entry = outputs_for("shot_a_p2_00001_.mp4")
    entry["prompt"] = [0, "refine", workflow]
    client = TestClient(create_app(client=FakeComfy(history_all={"refine": entry}), data_dir=tmp_path))
    result = client.post("/api/results/restore", json={"shot_id": "C1"}).json()["added"][0]
    assert result["latent_name"] == latent_name
    assert result["pass_number"] == 2


def test_repeated_generations_and_refines_keep_distinct_latents_after_restart(tmp_path):
    board = make_board(tmp_path)
    shot = board["shots"][0]
    shot["results"] = []
    shot.pop("refine_job")
    write_board(tmp_path, board)
    output = tmp_path / "comfyout"
    output.mkdir()
    fake = FakeComfy()
    client = TestClient(create_app(client=fake, data_dir=tmp_path, comfy_output=output))
    request = {key: shot[key] for key in ["references", "prompt", "duration", "seed", "output_name", "generation_mode", "aspect_ratio"]}
    request["resolution"] = "0.4mp"
    collected = []
    for index in range(2):
        response = client.post("/api/submit", json=request)
        assert response.status_code == 200, response.text
        run = response.json()
        workflow = fake.submitted[-1]
        assert workflow["203"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/latents/shot_a"
        archives = [node for node in workflow.values() if node.get("class_type") == "H3ContinuousSaveLatent"
                    and node["inputs"]["filename_prefix"].endswith(run["latent_name"])]
        assert len(archives) == 1
        assert archives[0]["inputs"]["latent"] == workflow["203"]["inputs"]["latent"]
        assert archives[0]["inputs"]["handover"] == workflow["203"]["inputs"]["handover"]
        filename = f"shot_a_{index + 1:05d}_.mp4"
        (output / filename).write_bytes(b"video")
        fake.outputs[run["prompt_id"]] = outputs_for(filename)
        shot.update(prompt_id=run["prompt_id"], comfy_url=run["comfy_url"], run_dir=run["run_dir"])
        assert client.put("/api/storyboard", json=board).status_code == 200
        # The association must survive restarting the web tool, without a history graph.
        client = TestClient(create_app(client=fake, data_dir=tmp_path, comfy_output=output))
        response = client.post("/api/results/collect", json={"shot_id": "C1"})
        assert response.status_code == 200, response.text
        shot["results"] = response.json()["results"]
        collected.append(response.json()["added"][0])
        assert collected[-1]["latent_name"] == run["latent_name"]
    assert collected[0]["latent_name"] != collected[1]["latent_name"]
    refined = []
    for _ in range(2):
        response = client.post("/api/refine", json={"shot_id": "C1", "source_result_id": collected[0]["id"]})
        assert response.status_code == 200, response.text
        job = response.json()["refine_job"]
        assert job["pass_number"] == 2
        assert job["source_latent_name"] == collected[0]["latent_name"]
        workflow = fake.submitted[-1]
        assert workflow["300"]["inputs"]["latent_path"].endswith(collected[0]["latent_name"] + "_00001.safetensors")
        assert workflow["308"]["inputs"]["filename_prefix"].endswith("/shot_a_p2")
        refined.append(job["latent_name"])
    assert refined[0] != refined[1]


def test_legacy_result_without_immutable_latent_is_rejected(tmp_path):
    board = make_board(tmp_path)
    board["shots"][0]["results"][0].pop("latent_name")
    client = write_board(tmp_path, board)
    response = client.post("/api/refine", json={"shot_id": "C1", "source_result_id": "first"})
    assert response.status_code == 400
    assert "无法确认" in response.json()["detail"]


def legacy_history(timestamp, completed=True):
    entry = outputs_for("shot_a_00004_.mp4")
    entry["prompt"] = [0, "p1", {"203": {"class_type": "H3ContinuousSaveLatent", "inputs": {
        "filename_prefix": "codex_ref2va_tool/latents/shot_a", "clip_index": 1,
    }}}]
    entry["status"].update(completed=completed, messages=[["execution_start", {"timestamp": timestamp}]])
    return entry


def test_current_legacy_result_can_refine_when_history_proves_ownership(tmp_path):
    board = make_board(tmp_path)
    board["shots"][0]["results"][0].pop("latent_name")
    write_board(tmp_path, board)
    fake = FakeComfy(history_all={"p1": legacy_history(100)})
    client = TestClient(create_app(client=fake, data_dir=tmp_path))
    response = client.post("/api/refine", json={"shot_id": "C1", "source_result_id": "first"})
    assert response.status_code == 200, response.text
    assert response.json()["refine_job"]["source_latent_name"] == "shot_a"
    assert "__run_" in response.json()["refine_job"]["latent_name"]


@pytest.mark.parametrize("completed", [True, False])
def test_legacy_source_is_rejected_if_a_later_job_may_have_overwritten_it(tmp_path, completed):
    board = make_board(tmp_path)
    board["shots"][0]["results"][0].pop("latent_name")
    write_board(tmp_path, board)
    fake = FakeComfy(history_all={"p1": legacy_history(100), "newer": legacy_history(200, completed)})
    client = TestClient(create_app(client=fake, data_dir=tmp_path))
    response = client.post("/api/refine", json={"shot_id": "C1", "source_result_id": "first"})
    assert response.status_code == 400
    assert fake.submitted == []


def test_legacy_source_is_rejected_when_a_pending_job_will_overwrite_it(tmp_path):
    board = make_board(tmp_path)
    board["shots"][0]["results"][0].pop("latent_name")
    write_board(tmp_path, board)
    fake = FakeComfy(history_all={"p1": legacy_history(100)})
    fake.queue = lambda: {"queue_running": [], "queue_pending": [legacy_history(200)["prompt"]]}
    client = TestClient(create_app(client=fake, data_dir=tmp_path))
    response = client.post("/api/refine", json={"shot_id": "C1", "source_result_id": "first"})
    assert response.status_code == 400
    assert "覆盖" in response.json()["detail"]
    assert fake.submitted == []
