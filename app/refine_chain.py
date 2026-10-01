"""二采（H3 低噪声重采样）派生链的归属与截断规则。

工具里"这一次算第几采"不应该由散落字段去猜，而应该由**产出这条视频的那次提交**
决定：

    一采    pass=1   latent = {output_name}__run_{唯一编号}
    N 采    pass=N   latent = {output_name}_p{N}__run_{唯一编号}

固定名称仍用于续镜；历史结果缺少独立 latent 时只做兼容推断，不能据此确认版本归属。

每条 result 都记住自己是被哪个 latent 采出来的，于是"点某条视频的二采"就能明确
得到下一次是第几采、以及拿哪个 latent 当输入；删掉链尾产物时也要顺手把残留的
refine_job 作废，否则下一次会误判成"再往上采一档"（用户遇到的三采 bug）。
"""

from __future__ import annotations

import re
from typing import Any

# 产物视频/ latent 的名字里带着 `_p2_` / `_p3_` 这样的档位标记，
# 用于给没有 pass_number 字段的历史结果做兜底推断。
PASS_IN_NAME = re.compile(r"_p(\d+)(?:_|$)")


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def latent_name_for_pass(output_name: str, pass_number: int) -> str:
    """第 ``pass_number`` 采所使用的 latent 名（一采没有 ``_pN`` 后缀）。"""
    base = str(output_name or "")
    return base if pass_number <= 1 else f"{base}_p{pass_number}"


def pass_from_filename(filename: str) -> int:
    match = PASS_IN_NAME.search(str(filename or ""))
    return int(match.group(1)) if match else 1


def output_pass(filename: str, output_name: str) -> int | None:
    """Match an entire SaveVideo filename, rather than a shared name prefix."""
    match = re.fullmatch(
        re.escape(output_name) + r"(?:_p([2-9]))?_\d{5,}_?\.(?:mp4|webm|mov|mkv)",
        str(filename or ""),
    )
    return (int(match.group(1)) if match.group(1) else 1) if match else None


def result_pass_number(result: dict[str, Any]) -> int:
    """这条 result 是第几采。显式字段优先，老数据按文件名推断。"""
    recorded = _positive_int(result.get("pass_number"))
    if recorded:
        return recorded
    return pass_from_filename(result.get("filename"))


def result_latent_name(result: dict[str, Any], shot: dict[str, Any]) -> str:
    """这条 result 是哪次采样产出的（也就是它自带的 latent）。"""
    remembered = str(result.get("latent_name") or "").strip()
    if remembered:
        return remembered
    return latent_name_for_pass(str(shot.get("output_name") or ""), result_pass_number(result))


def plan_refine_from_result(
    shot: dict[str, Any],
    source_result: dict[str, Any],
) -> tuple[int, str]:
    """基于用户点的那条视频，算出下一采的 (pass_number, 输入 latent 名)。

    点一采视频 -> 二采；点二采视频 -> 三采。既不看链尾残留状态，也不做猜测。
    """
    current_pass = result_pass_number(source_result)
    return current_pass + 1, result_latent_name(source_result, shot)


def refresh_refine_chain(shot: dict[str, Any]) -> dict[str, Any]:
    """按现存 results 重建链尾；链尾产物已被删除时作废残留的 refine_job。

    返回 ``{"changed": bool, "cleared": bool, "max_pass": int}``。
    """
    results = shot.get("results") or []
    max_pass = max((result_pass_number(item) for item in results), default=0)
    job = shot.get("refine_job") or {}
    # Active jobs have not necessarily produced a result yet. Deleting an old
    # video must not detach their polling / collection target.
    if not job or job.get("status") in {"queued", "running", "syncing"}:
        return {"changed": False, "cleared": False, "max_pass": max_pass}

    job_pass = _positive_int(job.get("pass_number")) or 0
    job_prompt = str(job.get("prompt_id") or "")
    # 只有"这次二采产出的结果还在"时，这条链才算还挂着。
    still_attached = job_pass >= 2 and (
        (job_prompt and any(str(item.get("prompt_id") or "") == job_prompt for item in results))
        or (not job_prompt and max_pass >= job_pass)
    )
    if still_attached:
        return {"changed": False, "cleared": False, "max_pass": max_pass}

    del shot["refine_job"]
    return {"changed": True, "cleared": True, "max_pass": max_pass}


def latest_prompt_id(shot: dict[str, Any]) -> str:
    """剩余结果里档位最高的那条所对应的 prompt，用于回退 shot 的轮询目标。"""
    results = shot.get("results") or []
    if not results:
        return ""
    best = max(results, key=result_pass_number)
    return str(best.get("prompt_id") or "")
