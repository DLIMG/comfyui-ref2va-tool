import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class FakeComfy:
    def system_stats(self):
        return {"system": {"comfyui_version": "test"}}


def pack_bytes(task_type, files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("pack.json", json.dumps({
            "format": "minimax-h3-director-pack", "formatVersion": 1,
            "taskType": task_type, "widgets": {"steps": 12, "seed": 42},
        }))
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


def test_director_r2v_pack_converts_shared_assets_without_merging_latent(tmp_path):
    content = pack_bytes("r2v", {
        "shared_params/shared_params.json": json.dumps({
            "commonEnabled": True, "prompt": "subject_definitions:\nShared soldier.",
            "refs": [{"index": 1, "imageFile": "shared_params/Picture1.png"}],
        }),
        "shared_params/Picture1.png": b"shared-image",
        "asset_groups/01/group.json": json.dumps({
            "id": "D01", "title": "推进", "durationSec": 6,
            "prompt": "detailed_description:\n[Shot 1] He advances.",
            "refs": [{"index": 2, "imageFile": "asset_groups/01/Picture2.png"}],
        }),
        "asset_groups/01/Picture2.png": b"local-image",
    })

    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).post(
        "/api/storyboard/import-director-pack",
        files={"pack": ("director.mmxpack.zip", content, "application/zip")},
    )

    assert response.status_code == 200
    project = response.json()["project"]
    assert project["shared"]["enabled"] is True
    assert project["shared"]["prompt"].startswith("subject_definitions")
    assert len(project["shared"]["references"]) == 1
    assert project["shots"][0]["generation_mode"] == "r2va"
    assert len(project["shots"][0]["references"]) == 1
    assert project["shots"][0]["continue_from_previous"] is False
    assert project["shots"][0]["save_latent"] is False
    assert project["advanced_settings"]["sampling_steps"] == 12


def test_director_fl2v_pack_keeps_keyframes_before_shared_images(tmp_path):
    content = pack_bytes("fl2v", {
        "shared_params/shared_params.json": json.dumps({
            "commonEnabled": True,
            "refs": [{"index": 1, "imageFile": "shared_params/Picture1.png"}],
        }),
        "shared_params/Picture1.png": b"shared-image",
        "asset_groups/01/group.json": json.dumps({"id": "F01", "prompt": "move"}),
        "asset_groups/01/start.png": b"first",
        "asset_groups/01/end.png": b"last",
    })

    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).post(
        "/api/storyboard/import-director-pack",
        files={"pack": ("director.mmxpack.zip", content, "application/zip")},
    )

    assert response.status_code == 200
    shot = response.json()["project"]["shots"][0]
    assert shot["generation_mode"] == "fl2va"
    assert shot["references"][0].endswith("start.png")
    assert shot["references"][1].endswith("end.png")
    assert "FL2VA 不使用公共视频" not in "\n".join(response.json()["warnings"])


def test_director_pack_rejects_zip_slip_and_unsupported_task(tmp_path):
    malicious = pack_bytes("v2v", {"../escape.txt": b"no", "shared_params/shared_params.json": "{}"})
    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).post(
        "/api/storyboard/import-director-pack",
        files={"pack": ("director.zip", malicious, "application/zip")},
    )

    assert response.status_code == 422
    assert "不安全" in response.json()["detail"]


def test_director_pack_zero_based_refs_keep_every_slot(tmp_path):
    """ComfyUI 插件的 refs.index 是 0 起（Picture1 -> 0）。

    旧实现写成 `record.get("index") or position`，0 被当成缺失而回退到 1 起的位置号，
    于是 Picture1 被 Picture2 顶掉、末位再被目录扫描补成重复项，整段参考图错位一格。
    """
    content = pack_bytes("r2v", {
        "asset_groups/01/group.json": json.dumps({
            "id": "D01", "title": "对峙", "durationSec": 12,
            "prompt": "subject_definitions:\nA meets B.",
            "refs": [
                {"index": index, "imageFile": f"asset_groups/01/Picture{index + 1}.png"}
                for index in range(5)
            ],
        }),
        **{f"asset_groups/01/Picture{index}.png": b"img" for index in range(1, 6)},
    })

    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).post(
        "/api/storyboard/import-director-pack",
        files={"pack": ("director.mmxpack.zip", content, "application/zip")},
    )

    assert response.status_code == 200
    references = response.json()["project"]["shots"][0]["references"]
    assert [Path(reference).name for reference in references] == [
        "Picture1.png", "Picture2.png", "Picture3.png", "Picture4.png", "Picture5.png",
    ]


def test_director_pack_one_based_refs_still_supported(tmp_path):
    content = pack_bytes("r2v", {
        "asset_groups/01/group.json": json.dumps({
            "id": "D01", "title": "对峙", "durationSec": 12,
            "prompt": "subject_definitions:\nA meets B.",
            "refs": [
                {"index": index, "imageFile": f"asset_groups/01/Picture{index}.png"}
                for index in range(1, 4)
            ],
        }),
        **{f"asset_groups/01/Picture{index}.png": b"img" for index in range(1, 4)},
    })

    response = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path)).post(
        "/api/storyboard/import-director-pack",
        files={"pack": ("director.mmxpack.zip", content, "application/zip")},
    )

    assert response.status_code == 200
    references = response.json()["project"]["shots"][0]["references"]
    assert [Path(reference).name for reference in references] == [
        "Picture1.png", "Picture2.png", "Picture3.png",
    ]
