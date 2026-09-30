from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
CANVAS = (ROOT / "app" / "static" / "canvas.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")


def test_infinite_canvas_is_an_alternate_storyboard_view():
    assert 'id="canvas-mode-toggle"' in INDEX
    assert 'id="canvas-workspace"' in INDEX
    assert 'id="infinite-canvas"' in INDEX
    assert '<script src="/canvas.js"></script>' in INDEX
    assert "window.Ref2VACanvas?.render(board)" in APP


def test_canvas_supports_pan_zoom_draggable_nodes_and_persistent_layout():
    assert "canvas_position" in CANVAS
    assert "pointerdown" in CANVAS
    assert "wheel" in CANVAS
    assert "scheduleSave()" in CANVAS
    assert "canvas-link.latent" in CSS
    assert ".infinite-canvas" in CSS


def test_references_are_first_class_nodes_with_connectable_inputs():
    assert "function assetGraph(project)" in CANVAS
    assert "canvas-asset" in CANVAS
    assert "canvas_asset_positions" in CANVAS
    assert "inputPaths" in CANVAS
    assert "供 ${consumers.length} 镜使用" in CANVAS
    assert ".canvas-link.asset" in CSS


def test_every_canvas_node_has_an_in_canvas_inspector_and_results_become_nodes():
    assert 'id="canvas-inspector"' in INDEX
    assert "function renderInspector(currentBoard)" in CANVAS
    assert "canvas-inspector-prompt" in CANVAS
    assert "const resultGraph" in CANVAS
    assert "canvas_result_positions" in CANVAS
    assert "canvas-result" in CANVAS
    assert ".canvas-inspector" in CSS


def test_selected_nodes_animate_their_connected_lines():
    assert "canvas-link asset ${item.asset.kind}${active}" in CANVAS
    assert "canvas-link sequence${inherited}${active}" in CANVAS
    assert "canvas-link result${active}" in CANVAS
    assert ".canvas-link.active" in CSS
    assert "canvas-active-flow" in CSS
    assert "<circle class=\"canvas-link-port" not in CANVAS


def test_result_card_videos_are_reused_across_canvas_renders():
    assert "function detachResultVideos" in CANVAS
    assert "function attachResultVideos" in CANVAS
    assert "const reusableVideos = detachResultVideos()" in CANVAS
    assert "attachResultVideos(results, reusableVideos)" in CANVAS


def test_canvas_keeps_generation_order_explicit():
    assert 'id="canvas-sort-shots"' in INDEX
    assert "sortByCanvasPosition" in CANVAS
    assert "continue_from_previous = false" in CANVAS
    assert "submitShot(shot)" in CANVAS


def test_canvas_script_has_a_dedicated_static_route():
    MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/canvas.js")' in MAIN
    assert 'STATIC / "canvas.js"' in MAIN
