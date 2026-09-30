"""MP4 尺寸探测：ConcatenateVideo 只做容器级串接，必须提前挡住分辨率不一致。"""

from pathlib import Path

from app.video_probe import find_dimension_mismatch, probe_video_dimensions


def _fake_mp4(width: int, height: int, sample_entry: bytes = b"avc1") -> bytes:
    """拼一个只含 VisualSampleEntry 头部的最小 MP4，供探测函数读取宽高。"""
    head = b"\x00\x00\x00\x00" + b"\x00\x00\x00\x01" + b"\x00\x00\x00\xbd" + sample_entry
    body = b"\x00" * 8 + b"\x00" * 16
    body += width.to_bytes(2, "big") + height.to_bytes(2, "big")
    return b"ftypisom" + b"moov" + b"stsd" + head + body + b"\x00" * 32


def test_probe_reads_visual_sample_entry_dimensions(tmp_path: Path):
    target = tmp_path / "clip.mp4"
    target.write_bytes(_fake_mp4(1280, 720))

    assert probe_video_dimensions(target) == (1280, 720)


def test_probe_supports_hevc_and_av1_sample_entries(tmp_path: Path):
    for entry, size in ((b"hvc1", (864, 480)), (b"av01", (360, 640)), (b"vp09", (1344, 768))):
        target = tmp_path / f"{entry.decode()}.mp4"
        target.write_bytes(_fake_mp4(*size, sample_entry=entry))
        assert probe_video_dimensions(target) == size


def test_probe_returns_none_for_unparsable_file(tmp_path: Path):
    target = tmp_path / "broken.mp4"
    target.write_bytes(b"not a video at all")

    assert probe_video_dimensions(target) is None


def test_probe_returns_none_for_missing_file(tmp_path: Path):
    assert probe_video_dimensions(tmp_path / "absent.mp4") is None


def test_find_dimension_mismatch_reports_first_conflicting_pair(tmp_path: Path):
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    third = tmp_path / "c.mp4"
    first.write_bytes(_fake_mp4(1280, 720))
    second.write_bytes(_fake_mp4(1280, 720))
    third.write_bytes(_fake_mp4(864, 480))

    mismatch = find_dimension_mismatch([("A01", first), ("A02", second), ("A03", third)])

    assert mismatch == ("A01", (1280, 720), "A03", (864, 480))


def test_find_dimension_mismatch_is_none_when_all_segments_match(tmp_path: Path):
    paths = []
    for index in range(3):
        target = tmp_path / f"shot{index}.mp4"
        target.write_bytes(_fake_mp4(1344, 768))
        paths.append((f"S{index}", target))

    assert find_dimension_mismatch(paths) is None


def test_find_dimension_mismatch_skips_unreadable_segments(tmp_path: Path):
    good = tmp_path / "good.mp4"
    good.write_bytes(_fake_mp4(1280, 720))
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"junk")

    assert find_dimension_mismatch([("A", broken), ("B", good)]) is None
