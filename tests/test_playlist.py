import json
import subprocess
from pathlib import Path


PLAYLIST_MODULE = Path(__file__).parents[1] / "app" / "static" / "playlist.js"


def run_playlist(expression, payload):
    script = f"""
const playlist = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const output = {expression};
process.stdout.write(JSON.stringify(output));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(PLAYLIST_MODULE), json.dumps(payload)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_builds_playlist_in_shot_order_and_skips_shots_without_results():
    shots = [
        {"id": "shot-2", "title": "Second", "results": [{"id": "result-2"}]},
        {"id": "empty", "title": "Empty", "results": []},
        {"id": "shot-1", "title": "First", "results": [{"id": "result-1"}]},
    ]

    items = run_playlist("playlist.buildContinuousPlaylist(input)", shots)

    assert items == [
        {"shotId": "shot-2", "title": "Second", "result": {"id": "result-2"}},
        {"shotId": "shot-1", "title": "First", "result": {"id": "result-1"}},
    ]


def test_latest_result_uses_newest_valid_created_at_even_when_invalid_is_later():
    results = [
        {"id": "newest", "created_at": "2026-08-21T12:00:00Z"},
        {"id": "older", "created_at": "2026-08-20T12:00:00Z"},
        {"id": "invalid", "created_at": "not-a-date"},
    ]

    result = run_playlist("playlist.latestResult(input)", results)

    assert result["id"] == "newest"


def test_latest_result_breaks_valid_date_ties_with_later_array_item():
    results = [
        {"id": "first", "created_at": "2026-08-21T12:00:00Z"},
        {"id": "second", "created_at": "2026-08-21T12:00:00Z"},
    ]

    result = run_playlist("playlist.latestResult(input)", results)

    assert result["id"] == "second"


def test_latest_result_falls_back_to_later_item_when_all_dates_are_invalid_or_missing():
    results = [
        {"id": "missing"},
        {"id": "invalid", "created_at": "not-a-date"},
        {"id": "later-missing"},
    ]

    result = run_playlist("playlist.latestResult(input)", results)

    assert result["id"] == "later-missing"


def test_reconcile_preserves_current_result_id_when_still_present():
    payload = {
        "items": [{"result": {"id": "a"}}, {"result": {"id": "b"}}],
        "currentResultId": "b",
        "previousIndex": 0,
    }

    index = run_playlist(
        "playlist.reconcilePlaylistIndex(input.items, input.currentResultId, input.previousIndex)",
        payload,
    )

    assert index == 1


def test_reconcile_clamps_previous_index_when_current_result_disappears():
    payload = {
        "items": [{"result": {"id": "a"}}, {"result": {"id": "b"}}],
        "currentResultId": "gone",
        "previousIndex": 9,
    }

    index = run_playlist(
        "playlist.reconcilePlaylistIndex(input.items, input.currentResultId, input.previousIndex)",
        payload,
    )

    assert index == 1


def test_reconcile_empty_playlist_returns_zero():
    payload = {"items": [], "currentResultId": "gone", "previousIndex": 3}

    index = run_playlist(
        "playlist.reconcilePlaylistIndex(input.items, input.currentResultId, input.previousIndex)",
        payload,
    )

    assert index == 0


def test_playlist_module_stays_free_of_media_dom_operations():
    source = PLAYLIST_MODULE.read_text(encoding="utf-8")

    assert "replaceMediaElement" not in source
    assert ".cloneNode(" not in source
