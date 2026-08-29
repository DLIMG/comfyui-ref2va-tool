import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_api import FakeComfy


ROOT = Path(__file__).parents[1]
PROJECT_MERGE_MODULE = ROOT / "app" / "static" / "project-merge.js"


def run_merge(current, imported):
    script = """
const merge = require(process.argv[1]);
const current = JSON.parse(process.argv[2]);
const imported = JSON.parse(process.argv[3]);
try {
  process.stdout.write(JSON.stringify({value: merge.mergeImportedProject(current, imported)}));
} catch (error) {
  process.stdout.write(JSON.stringify({error: error.message}));
}
"""
    completed = subprocess.run(
        ["node", "-e", script, str(PROJECT_MERGE_MODULE), json.dumps(current), json.dumps(imported)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_imported_project_controls_config_order_and_shot_membership_while_preserving_runtime():
    current = {"name": "current", "project_dir": "C:/current", "shots": [
        {"id": "keep", "title": "old", "prompt_id": "p1", "run_dir": "run", "status": "completed", "error": "", "results": [{"id": "r1"}]},
        {"id": "removed", "results": [{"id": "old"}]},
    ]}
    imported = {"name": "imported", "project_dir": "", "setting": 7, "shots": [
        {"id": "new", "title": "first"},
        {"id": "keep", "title": "updated", "results": []},
    ]}

    result = run_merge(current, imported)["value"]

    assert result["name"] == "imported"
    assert result["setting"] == 7
    assert result["project_dir"] == "C:/current"
    assert [shot["id"] for shot in result["shots"]] == ["new", "keep"]
    assert result["shots"][1] == {
        "id": "keep", "title": "updated", "prompt_id": "p1", "run_dir": "run",
        "status": "completed", "error": "", "results": [{"id": "r1"}],
    }


def test_nonempty_imported_results_make_imported_runtime_a_complete_export():
    current = {"shots": [{"id": "a", "prompt_id": "old", "status": "completed", "results": [{"id": "old"}]}]}
    imported = {"project_dir": "D:/export", "shots": [{"id": "a", "prompt_id": "new", "status": "failed", "error": "x", "results": [{"id": "new"}]}]}

    result = run_merge(current, imported)["value"]

    assert result["project_dir"] == "D:/export"
    assert result["shots"][0] == imported["shots"][0]


def test_different_project_directory_does_not_inherit_same_id_runtime():
    current = {"name": "旧项目", "project_dir": "G:/projects/old", "shots": [{
        "id": "01A", "title": "旧片段", "prompt_id": "old-prompt",
        "status": "completed", "results": [{"id": "old-result"}],
    }]}
    imported = {"name": "新项目", "project_dir": "G:/projects/new", "shots": [{
        "id": "01A", "title": "新片段", "prompt_id": "", "run_dir": "",
        "status": "draft", "error": "", "results": [],
    }]}

    result = run_merge(current, imported)["value"]

    assert result["shots"][0] == imported["shots"][0]


def test_invalid_imported_shots_throw_without_mutating_either_input():
    current = {"shots": [{"id": "a", "results": [{"id": "old"}]}]}
    imported = {"shots": "invalid"}
    script = """
const merge = require(process.argv[1]);
const current = JSON.parse(process.argv[2]);
const imported = JSON.parse(process.argv[3]);
const before = JSON.stringify([current, imported]);
let threw = false;
try { merge.mergeImportedProject(current, imported); } catch (_) { threw = true; }
process.stdout.write(JSON.stringify({threw, unchanged: before === JSON.stringify([current, imported])}));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(PROJECT_MERGE_MODULE), json.dumps(current), json.dumps(imported)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    assert json.loads(completed.stdout) == {"threw": True, "unchanged": True}


def test_import_rejects_null_shot():
    result = run_merge({"shots": []}, {"shots": [None]})

    assert "error" in result


def test_import_rejects_primitive_shot():
    result = run_merge({"shots": []}, {"shots": [7]})

    assert "error" in result


def test_import_rejects_blank_shot_id():
    result = run_merge({"shots": []}, {"shots": [{"id": "  "}]})

    assert "error" in result


def test_import_rejects_duplicate_shot_ids():
    result = run_merge({"shots": []}, {"shots": [{"id": "01A"}, {"id": "01A"}]})

    assert "error" in result


def test_project_merge_script_is_served_and_loaded_before_app(tmp_path):
    browser = TestClient(create_app(client=FakeComfy(), data_dir=tmp_path))
    response = browser.get("/project-merge.js")
    html = browser.get("/").text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "mergeImportedProject" in response.text
    assert html.index('<script src="/project-merge.js"></script>') < html.index('<script src="/app.js"></script>')


def test_import_handler_merges_before_assignment_and_reports_errors():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "Ref2VAProjectMerge.mergeImportedProject(board,imported)" in source
    assert "catch(e)" in source
    assert "导入失败：" in source
