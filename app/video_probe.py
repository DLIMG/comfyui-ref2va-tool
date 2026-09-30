"""纯 Python 的 MP4 视频尺寸探测。

ComfyUI 0.36 的原生 ``ConcatenateVideo`` 只做容器级串接（不解码），因此要求所有
片段分辨率完全一致，否则在 SaveVideo 阶段抛出
``Accumulated videos have incompatible frame dimensions``。
本地工具在排队前先探测一遍，把这类错误挡在提交之前。
"""

from __future__ import annotations

from pathlib import Path


# VisualSampleEntry 的宽高字段：type 本身 4 字节，之后 8 字节（6 保留 +
# 2 data_reference_index），再加 16 字节 pre_defined/reserved，随后是 2 字节宽、
# 2 字节高。偏移量以 type 字符串的起始下标为基准。
_SAMPLE_ENTRY_TYPES = (b"avc1", b"avc3", b"hvc1", b"hev1", b"av01", b"vp09", b"mp4v")
_WIDTH_OFFSET = 28
_HEIGHT_OFFSET = 30
_HEADER_SCAN_BYTES = 8 * 1024 * 1024


def probe_video_dimensions(path: str | Path) -> tuple[int, int] | None:
    """返回 ``(width, height)``；无法从文件头解析时返回 ``None``。"""
    target = Path(path)
    try:
        with target.open("rb") as handle:
            head = handle.read(_HEADER_SCAN_BYTES)
    except OSError:
        return None

    best: tuple[int, int] | None = None
    for marker in _SAMPLE_ENTRY_TYPES:
        start = head.find(marker)
        while start != -1:
            width_at = start + _WIDTH_OFFSET
            height_at = start + _HEIGHT_OFFSET
            if height_at + 2 <= len(head):
                width = int.from_bytes(head[width_at:width_at + 2], "big")
                height = int.from_bytes(head[height_at:height_at + 2], "big")
                if width > 0 and height > 0:
                    # 同一文件里可能命中多个采样描述，优先保留最大的有效尺寸。
                    if best is None or width * height > best[0] * best[1]:
                        best = (width, height)
                    break
            start = head.find(marker, start + 4)
        if best is not None:
            break
    return best


def find_dimension_mismatch(
    segments: list[tuple[str, str | Path]],
) -> tuple[str, tuple[int, int], str, tuple[int, int]] | None:
    """在 ``[(标签, 路径), ...]`` 中找出第一处分辨率不一致的片段对。

    返回 ``(标签A, 尺寸A, 标签B, 尺寸B)``；全部一致或无法探测时返回 ``None``。
    """
    reference: tuple[str, tuple[int, int]] | None = None
    for label, path in segments:
        size = probe_video_dimensions(path)
        if size is None:
            continue
        if reference is None:
            reference = (label, size)
            continue
        if size != reference[1]:
            return reference[0], reference[1], label, size
    return None
