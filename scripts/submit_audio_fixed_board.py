import json
import urllib.request
from pathlib import Path

BOARD_PATH = Path(
    r"G:\AI短剧生成\憋住世界就停了_Ref2VA_480p_V2"
    r"\04_分镜与提示词\憋住世界就停了_18镜头_V3_latent关键帧审核版.json"
)
BASE = "http://127.0.0.1:8765"

def call(method, path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))

board = json.loads(BOARD_PATH.read_text(encoding="utf-8-sig"))

submitted = []
for index, shot in enumerate(board["shots"]):
    previous = board["shots"][index - 1]["output_name"] if shot.get("continue_from_previous") else ""
    will_continue = index + 1 < len(board["shots"]) and bool(
        board["shots"][index + 1].get("continue_from_previous")
    )
    body = {
        "references": shot["references"],
        "prompt": shot["prompt"],
        "duration": shot["duration"],
        "seed": shot["seed"],
        "output_name": shot["output_name"],
        "resolution": shot.get("resolution", "480p"),
        "aspect_ratio": shot.get("aspect_ratio", "9:16"),
        "generation_mode": shot.get("generation_mode", "r2va"),
        "continue_from_previous": bool(shot.get("continue_from_previous")),
        "previous_output_name": previous,
        "will_be_continued": will_continue,
        "save_latent": bool(shot.get("save_latent")),
    }
    result = call("POST", "/api/submit", body)
    shot["status"] = "queued"
    shot["prompt_id"] = result["prompt_id"]
    shot["run_dir"] = result["run_dir"]
    shot["submitted_at"] = result.get("submitted_at")
    shot["estimated_seconds"] = result.get("estimated_seconds")
    submitted.append({"id": shot["id"], "prompt_id": result["prompt_id"], "number": result.get("number")})

BOARD_PATH.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(submitted, ensure_ascii=False, indent=2))
