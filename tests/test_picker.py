from app.picker import build_picker_script, parse_picker_output


def test_image_picker_script_uses_multiselect_and_image_filter():
    script = build_picker_script("images")
    assert "$dialog.Multiselect = $true" in script
    assert "*.png;*.jpg;*.jpeg;*.webp" in script
    assert "System.Windows.Forms" in script


def test_text_picker_script_is_single_select():
    script = build_picker_script("text")
    assert "$dialog.Multiselect = $false" in script
    assert "*.txt" in script


def test_picker_output_accepts_json_array_string_and_empty():
    assert parse_picker_output('["C:\\\\a.png","D:\\\\图.png"]') == [r"C:\a.png", r"D:\图.png"]
    assert parse_picker_output('"C:\\\\prompt.txt"') == [r"C:\prompt.txt"]
    assert parse_picker_output("[]") == []
