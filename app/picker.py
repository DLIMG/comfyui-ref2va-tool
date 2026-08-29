from __future__ import annotations

import json
import subprocess


def build_picker_script(kind: str) -> str:
    if kind == "images":
        multiple = "$true"
        filter_text = "图片|*.png;*.jpg;*.jpeg;*.webp|所有文件|*.*"
        title = "选择参考图"
        result = "$dialog.FileNames"
    elif kind == "text":
        multiple = "$false"
        filter_text = "文本|*.txt|所有文件|*.*"
        title = "选择H3提示词"
        result = "$dialog.FileName"
    else:
        raise ValueError("未知文件选择类型")
    return f"""
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '{title}'
$dialog.Filter = '{filter_text}'
$dialog.Multiselect = {multiple}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  {result} | ConvertTo-Json -Compress
}} else {{
  '[]'
}}
""".strip()


def parse_picker_output(output: str) -> list[str]:
    value = json.loads(output.strip() or "[]")
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def pick_files(kind: str) -> list[str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-Command", build_picker_script(kind)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        creationflags=flags,
    )
    return parse_picker_output(completed.stdout)
