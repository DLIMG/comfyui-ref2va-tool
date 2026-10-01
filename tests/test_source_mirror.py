import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.source_mirror import mirror_source_json, normalize_source_path


class FakeComfy:
    def system_stats(self):
        return {"system": {"comfyui_version": "test"}}

    def logs(self):
        return {"entries": []}

    def submit(self, workflow, client_id):
        return {"prompt_id": "p1", "number": 1, "node_errors": {}}

    def history(self, prompt_id):
        return {prompt_id: {"status": {"completed": True}, "outputs": {}}}

    def queue(self):
        return {"queue_running": [], "queue_pending": []}


def project(name: str = "磁盘项目") -> dict:
    return {
        "name": name,
        "project_dir": "",
        "advanced_settings": {},
        "shots": [{"id": "shot-1", "prompt": "一个测试镜头"}],
    }


def test_normalize_source_path_empty_values():
    assert normalize_source_path("") == ""
    assert normalize_source_path(None) == ""
    assert normalize_source_path("   ") == ""


def test_normalize_source_path_rejects_non_json(tmp_path):
    with pytest.raises(ValueError):
        normalize_source_path(tmp_path / "故事板.txt")


def test_normalize_source_path_rejects_directory(tmp_path):
    with pytest.raises(ValueError):
        normalize_source_path(tmp_path)


def test_normalize_source_path_missing_parent(tmp_path):
    with pytest.raises(ValueError):
        normalize_source_path(tmp_path / "不存在" / "a.json")


def test_mirror_writes_bound_source(tmp_path):
    source = tmp_path / "storyboard.json"
    source.write_text("{}", encoding="utf-8")
    payload = project()
    payload["source_json_path"] = str(source)
    result = mirror_source_json(payload)
    assert result["mirrored"] is True
    assert result["mirror_error"] == ""
    assert json.loads(source.read_text(encoding="utf-8"))["name"] == "磁盘项目"


def test_mirror_skips_when_content_unchanged(tmp_path):
    source = tmp_path / "storyboard.json"
    payload = project()
    payload["source_json_path"] = str(source)
    assert mirror_source_json(payload)["mirrored"] is True
    assert mirror_source_json(payload)["mirrored"] is False


def test_mirror_without_binding_is_noop(tmp_path):
    result = mirror_source_json(project())
    assert result == {"mirrored": False, "mirror_path": "", "mirror_error": ""}


def test_mirror_reports_error_instead_of_raising(tmp_path):
    payload = project()
    payload["source_json_path"] = str(tmp_path / "没有这个目录" / "x.json")
    result = mirror_source_json(payload)
    assert result["mirrored"] is False
    assert result["mirror_error"]
    assert not (tmp_path / "没有这个目录").exists()


def test_bind_endpoint_imports_and_mirrors_on_save(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    source = tmp_path / "校园.json"
    source.write_text(json.dumps(project("磁盘项目"), ensure_ascii=False), encoding="utf-8")

    bound = client.post("/api/storyboard/source-file", json={"path": str(source), "import_now": True})
    assert bound.status_code == 200, bound.text
    assert bound.json()["source_json_path"] == str(source.resolve())
    assert bound.json()["project"]["name"] == "磁盘项目"

    board = client.get("/api/storyboard").json()
    assert board["source_json_path"] == str(source.resolve())

    board["name"] = "改过名字的项目"
    saved = client.put("/api/storyboard", json=board)
    assert saved.status_code == 200, saved.text
    assert saved.json()["mirrored"] is True
    assert json.loads(source.read_text(encoding="utf-8"))["name"] == "改过名字的项目"


def test_unbind_stops_mirroring(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    source = tmp_path / "校园.json"
    source.write_text(json.dumps(project("磁盘项目"), ensure_ascii=False), encoding="utf-8")
    client.post("/api/storyboard/source-file", json={"path": str(source), "import_now": True})

    off = client.post("/api/storyboard/source-file", json={"path": "", "import_now": False})
    assert off.status_code == 200, off.text
    assert off.json()["source_json_path"] == ""

    board = client.get("/api/storyboard").json()
    board["name"] = "不应该写回磁盘"
    saved = client.put("/api/storyboard", json=board).json()
    assert saved["mirrored"] is False
    assert json.loads(source.read_text(encoding="utf-8"))["name"] == "磁盘项目"


def test_bind_endpoint_rejects_non_json(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    bad = tmp_path / "x.txt"
    bad.write_text("{}", encoding="utf-8")
    response = client.post("/api/storyboard/source-file", json={"path": str(bad), "import_now": True})
    assert response.status_code == 422


def test_bind_endpoint_rejects_unparsable_json(tmp_path):
    client = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    response = client.post("/api/storyboard/source-file", json={"path": str(broken), "import_now": True})
    assert response.status_code == 422
