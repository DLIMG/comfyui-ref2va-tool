"""按修复后的规则重算已导入导演包工程的参考图槽位。

背景
----
`app/director_pack._slots` 早期实现写成 `record.get("index") or record.get("slot") or position`。
ComfyUI 插件的 `refs.index` 是 **0 起**（`Picture1 -> 0`），于是 0 被当成缺失而回退到 1 起的位置号，
第 1 张被第 2 张顶掉，目录扫描再把末位补成重复项 —— 每段参考图整体错位一格。
本脚本用修复后的 `convert_director_pack` 重新算一遍并写回工程文件。

用法
----
    python scripts/repair_director_pack_refs.py                 # 修 data/storyboard.json
    python scripts/repair_director_pack_refs.py <工程.json>
    python scripts/repair_director_pack_refs.py <工程.json> --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.director_pack import convert_director_pack  # noqa: E402


def _names(paths: list[str]) -> list[str]:
    return [Path(path).name for path in paths]


def main() -> int:
    parser = argparse.ArgumentParser(description="修复导演包导入后的参考图槽位错位")
    parser.add_argument("project", nargs="?", default=str(ROOT / "data" / "storyboard.json"))
    parser.add_argument("--dry-run", action="store_true", help="只打印差异，不写文件")
    args = parser.parse_args()

    project_path = Path(args.project)
    if not project_path.is_file():
        print(f"[FAIL] 找不到工程文件：{project_path}")
        return 1

    project = json.loads(project_path.read_text(encoding="utf-8-sig"))
    source = project.get("director_pack_source") or {}
    pack_root = Path(str(source.get("root") or ""))
    if not pack_root.is_dir():
        print(f"[FAIL] 工程未记录可用的导演包目录：{pack_root}")
        return 1

    converted, _warnings = convert_director_pack(pack_root)
    expected = {
        str(shot.get("director_pack_group")): shot.get("references") or []
        for shot in converted.get("shots", [])
    }

    changed = 0
    for shot in project.get("shots", []):
        group = str(shot.get("director_pack_group") or "")
        if group not in expected:
            continue
        current = list(shot.get("references") or [])
        fixed = list(expected[group])
        if _names(current) == _names(fixed):
            print(f"  [OK]   段 {group} {shot.get('id')} 槽位已正确（{len(fixed)} 张）")
            continue
        changed += 1
        print(f"  [FIX]  段 {group} {shot.get('id')}")
        print(f"         修正前: {_names(current)}")
        print(f"         修正后: {_names(fixed)}")
        shot["references"] = fixed

    if not changed:
        print("\n无需修复。")
        return 0

    if args.dry_run:
        print(f"\n[DRY-RUN] 共 {changed} 段待修，未写入文件。")
        return 0

    backup = project_path.with_suffix(project_path.suffix + ".before_ref_repair.bak")
    shutil.copy2(project_path, backup)
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\n已修复 {changed} 段；原文件备份在 {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
