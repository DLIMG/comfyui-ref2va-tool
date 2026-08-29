from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[1] / "启动工具.bat"


def test_windows_launcher_uses_crlf_and_ascii_only():
    content = LAUNCHER.read_bytes()
    assert b"\r\n" in content
    assert b"\n" not in content.replace(b"\r\n", b"")
    content.decode("ascii")
    assert b'cd /d "%~dp0"' in content
    assert b"if errorlevel 1" in content
